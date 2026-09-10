"""
Orquestador principal.

    python -m src.main sync        # trae de TODAS las secciones (course_ids)
    python -m src.main grade       # califica lo pendiente
    python -m src.main run         # sync + grade + export
    python -m src.main export      # regenera un .xlsx POR SECCIÓN
"""
import sys
from pathlib import Path

from . import config, db, export_excel, plagiarism
from .classroom_client import ClassroomClient, infer_category_and_unit
from .grader import grade_practica, total_score

SUBMISSIONS_DIR = config.DATA_DIR / "submissions"


def sync(course_id: str):
    client = ClassroomClient()
    db.init_db()

    course_name = client.get_course_name(course_id)

    with db.get_conn() as conn:
        db.upsert_course(conn, course_id, course_name)

        for s in client.list_students(course_id):
            profile = s["profile"]
            db.upsert_student(conn, s["userId"], profile.get("name", {}).get("fullName", "?"),
                               profile.get("emailAddress"), course_id=course_id)

        for cw in client.list_coursework(course_id):
            category, unidad = infer_category_and_unit(cw.get("title", ""))
            max_points = cw.get("maxPoints", 100)
            due = cw.get("dueDate")
            due_str = f"{due['year']}-{due['month']:02d}-{due['day']:02d}" if due else None
            db.upsert_coursework(conn, cw["id"], cw.get("title", ""), category, unidad, max_points,
                                  due_str, course_id=course_id)

            for sub in client.list_submissions(course_id, cw["id"]):
                problem_files = ClassroomClient.extract_problem_files(sub)

                n_encontrados = len(problem_files)
                if n_encontrados == 0:
                    status = "no_files"
                elif n_encontrados < config.load_config()["practica"]["problemas_por_practica"]:
                    status = "partial_files"
                else:
                    status = "pending"

                db.upsert_submission(
                    conn, submission_id=sub["id"], student_id=sub["userId"],
                    coursework_id=cw["id"], submitted_at=sub.get("updateTime"),
                    late=sub.get("late", False), status=status,
                )

                for problem_index, drive_file_id in problem_files.items():
                    dest = SUBMISSIONS_DIR / cw["id"] / sub["userId"] / f"p{problem_index}.c"
                    if not dest.exists():
                        client.download_drive_file(drive_file_id, dest)
                    db.upsert_submission_file(conn, sub["id"], problem_index, drive_file_id, str(dest))

    print(f"Sync completo: {course_name} ({course_id})")


def sync_all(course_ids: list):
    for course_id in course_ids:
        print(f"--- Sync curso {course_id} ---")
        sync(course_id)


def _plagiarism_flags_por_practica(rows, cfg) -> dict[str, dict[int, tuple]]:
    flags: dict[str, dict[int, tuple]] = {}
    if not cfg["plagiarism"]["enabled"] or len(rows) < 2:
        return flags
    n_problemas = cfg["practica"]["problemas_por_practica"]
    with db.get_conn() as conn:
        for problem_index in range(1, n_problemas + 1):
            submissions_map = {}
            for r in rows:
                files = db.get_submission_files(conn, r["submission_id"])
                if problem_index in files:
                    submissions_map[r["student_id"]] = Path(files[problem_index])
            if len(submissions_map) < 2:
                continue
            pairs = plagiarism.flag_pairs(submissions_map, cfg["plagiarism"]["similarity_threshold"])
            for student_id, (other, score) in pairs.items():
                flags.setdefault(student_id, {})[problem_index] = (other, score)
    return flags


def _log_plagiarism_alert(cfg: dict, mensaje: str):
    config.ensure_dirs()
    alert_path = config.DATA_DIR / "alertas_plagio.txt"
    from datetime import datetime
    with open(alert_path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {mensaje}\n")


def grade_pending():
    cfg = config.load_config()
    write_cfg = cfg.get("classroom_write", {})
    classroom_client = ClassroomClient() if write_cfg.get("auto_publish", False) else None

    with db.get_conn() as conn:
        pending = conn.execute(
            "SELECT s.*, cw.course_id AS coursework_course_id FROM submissions s "
            "JOIN coursework cw ON cw.coursework_id = s.coursework_id "
            "WHERE s.status IN ('pending', 'partial_files')"
        ).fetchall()

        by_coursework: dict[str, list] = {}
        for row in pending:
            by_coursework.setdefault(row["coursework_id"], []).append(row)

    for coursework_id, rows in by_coursework.items():
        plag_flags = _plagiarism_flags_por_practica(rows, cfg)
        course_id_de_la_tarea = rows[0]["coursework_course_id"]

        with db.get_conn() as conn:
            for r in rows:
                files = {i: Path(p) for i, p in db.get_submission_files(conn, r["submission_id"]).items()}
                problem_results = grade_practica(files, coursework_id, cfg)

                for i, res in problem_results.items():
                    feedback = res.compile_log if not res.compile_ok else (
                        f"{res.tests_passed}/{res.tests_total} pruebas pasadas."
                    )
                    db.save_problem_grade(conn, r["submission_id"], i, res.max_points, res.score_raw,
                                           res.compile_ok, res.tests_passed, res.tests_total, feedback)

                total, maxp = total_score(problem_results)

                student_flags = plag_flags.get(r["student_id"], {})
                plag_score, plag_with = None, None
                if student_flags:
                    worst_problem = max(student_flags, key=lambda i: student_flags[i][1])
                    plag_with, plag_score = student_flags[worst_problem]
                    plag_with = f"{plag_with} (problema p{worst_problem})"

                db.save_aggregate_grade(conn, r["submission_id"], total, maxp, plag_score, plag_with)

                if classroom_client:
                    tiene_plagio = plag_score is not None
                    publicar = (
                        write_cfg.get("auto_publish", False)
                        and not (tiene_plagio and write_cfg.get("skip_publish_if_plagiarism_flag", True))
                    )
                    try:
                        classroom_client.set_grade(
                            course_id_de_la_tarea, coursework_id, r["submission_id"],
                            score=total, publish=publicar,
                        )
                        if tiene_plagio and not publicar:
                            nombre = conn.execute(
                                "SELECT full_name FROM students WHERE student_id=?", (r["student_id"],)
                            ).fetchone()
                            nombre_str = nombre["full_name"] if nombre else r["student_id"]
                            _log_plagiarism_alert(cfg, f"PLAGIO — {nombre_str} en '{coursework_id}' "
                                                        f"(similitud {plag_score:.2f} con {plag_with}). "
                                                        f"Nota: {total}/{maxp} (borrador, no publicada).")
                            print(f"  [PLAGIO - alerta guardada] {nombre_str}")
                        elif publicar:
                            print(f"  [PUBLICADO] {r['submission_id']}: {total}/{maxp}")
                        else:
                            print(f"  [BORRADOR] {r['submission_id']}: {total}/{maxp}")
                    except Exception as e:
                        print(f"  [ERROR al escribir en Classroom] {r['submission_id']}: {e}")

    print("Calificación completa.")


def run_all(course_ids: list):
    sync_all(course_ids)
    grade_pending()
    paths = export_excel.export()
    print(f"Reportes actualizados: {[str(p) for p in paths]}")


if __name__ == "__main__":
    cfg = config.load_config()
    action = sys.argv[1] if len(sys.argv) > 1 else "run"
    course_ids = cfg["course_ids"]

    if action == "sync":
        sync_all(course_ids)
    elif action == "grade":
        grade_pending()
    elif action == "export":
        export_excel.export()
    elif action == "run":
        run_all(course_ids)
    else:
        print(f"Acción desconocida: {action}. Usa sync | grade | export | run")
