"""
Envoltura sobre la Classroom API + Drive API.
"""
import io
import re
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from . import auth, config


def infer_category_and_unit(title: str) -> tuple[str, int | None]:
    t = title.lower()
    unidad = None
    for n in range(1, 7):
        if f"unidad {n}" in t or f"u{n}" in t:
            unidad = n
            break
    if "departamental" in t:
        return "examen_departamental", None
    if "examen" in t:
        return "examenes_por_tema", unidad
    if "práctica" in t or "practica" in t:
        return "practicas", unidad
    if "investigaci" in t:
        return "investigaciones", unidad
    if "proyecto" in t:
        return "proyecto_final", None
    return "sin_categoria", unidad


class ClassroomClient:
    def __init__(self):
        creds = auth.get_credentials()
        self.classroom = build("classroom", "v1", credentials=creds)
        self.drive = build("drive", "v3", credentials=creds)

    def list_courses(self):
        resp = self.classroom.courses().list().execute()
        return resp.get("courses", [])

    def list_students(self, course_id: str):
        students, page_token = [], None
        while True:
            resp = self.classroom.courses().students().list(
                courseId=course_id, pageToken=page_token
            ).execute()
            students.extend(resp.get("students", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return students

    def list_coursework(self, course_id: str):
        work, page_token = [], None
        while True:
            resp = self.classroom.courses().courseWork().list(
                courseId=course_id, pageToken=page_token
            ).execute()
            work.extend(resp.get("courseWork", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return work

    def list_submissions(self, course_id: str, coursework_id: str):
        subs, page_token = [], None
        while True:
            resp = self.classroom.courses().courseWork().studentSubmissions().list(
                courseId=course_id, courseWorkId=coursework_id, pageToken=page_token
            ).execute()
            subs.extend(resp.get("studentSubmissions", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return subs

    def download_drive_file(self, drive_file_id: str, dest_path: Path) -> Path:
        request = self.drive.files().get_media(fileId=drive_file_id)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with io.FileIO(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return dest_path

    def set_grade(self, course_id: str, coursework_id: str, submission_id: str,
                   score: float, publish: bool = False):
        """
        Escribe la calificación en Classroom.

        publish=False (default): solo pone draftGrade. Es una nota "borrador"
        que SOLO el profesor ve en Classroom — el alumno no se entera, no
        hay notificación. Úsalo para revisar antes de soltarlo.

        publish=True: pone assignedGrade (la nota real) Y llama a
        studentSubmissions().return_() para "devolver" la entrega — esto SÍ
        notifica al alumno de inmediato y ya no hay vuelta atrás en la
        notificación (la nota se puede corregir después, pero el aviso ya se mandó).
        """
        body = {"draftGrade": score}
        self.classroom.courses().courseWork().studentSubmissions().patch(
            courseId=course_id, courseWorkId=coursework_id, id=submission_id,
            updateMask="draftGrade", body=body,
        ).execute()

        if publish:
            self.classroom.courses().courseWork().studentSubmissions().patch(
                courseId=course_id, courseWorkId=coursework_id, id=submission_id,
                updateMask="assignedGrade", body={"assignedGrade": score},
            ).execute()
            self.classroom.courses().courseWork().studentSubmissions().return_(
                courseId=course_id, courseWorkId=coursework_id, id=submission_id, body={},
            ).execute()

    @staticmethod
    def extract_problem_files(submission: dict, patron: str = r"^p([1-5])\.c$") -> dict[int, str]:
        """
        Escanea los adjuntos de una entrega y regresa {problem_index: drive_file_id}
        para cada archivo que respete la convención p1.c...p5.c (sin importar
        mayúsculas/minúsculas). Archivos que no calzan con el patrón (nombre
        distinto, no es .c, es un .zip, una foto, etc.) se IGNORAN aquí a
        propósito — quedan fuera del diccionario, así que ese problema se
        califica con 0 (ver grader.grade_practica) y tú puedes revisarlos a
        mano si algo se ve raro en el reporte.
        """
        found: dict[int, str] = {}
        regex = re.compile(patron, re.IGNORECASE)

        for attachment in submission.get("assignmentSubmission", {}).get("attachments", []):
            drive_file = attachment.get("driveFile")
            if not drive_file:
                continue
            title = drive_file.get("title", "")
            match = regex.match(title.strip())
            if match:
                problem_index = int(match.group(1))
                found[problem_index] = drive_file.get("id")

        return found
