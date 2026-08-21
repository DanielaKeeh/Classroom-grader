"""
Capa de base de datos. SQLite es la fuente de verdad.

CAMBIO IMPORTANTE respecto a la primera versión: una entrega (submission) ya
no es "un archivo .c" — es una Práctica con 5 problemas, y el alumno sube un
.c por problema (p1.c...p5.c). Por eso ahora existen:

  - submission_files: cada archivo individual que subió el alumno, con a qué
    número de problema corresponde.
  - problem_grades: la calificación de CADA problema por separado (para que
    puedas ver el detalle: "en la Práctica 3, reprobó el problema 4").
  - grades: se queda igual que antes, pero ahora guarda el AGREGADO de los 5
    problemas (score_raw = suma de los 5, hasta 100).
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id      TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    email           TEXT
);

CREATE TABLE IF NOT EXISTS coursework (
    coursework_id   TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    unidad          INTEGER,
    max_points       REAL NOT NULL DEFAULT 100,
    due_date        TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id     TEXT PRIMARY KEY,
    student_id        TEXT NOT NULL REFERENCES students(student_id),
    coursework_id     TEXT NOT NULL REFERENCES coursework(coursework_id),
    submitted_at      TEXT,
    late              INTEGER DEFAULT 0,
    status            TEXT DEFAULT 'pending',
    -- pending | graded | no_files | partial_files (le faltan p_i.c) | plagiarism_flag
    UNIQUE(student_id, coursework_id)
);

-- Un renglón por cada archivo p1.c...p5.c que el alumno subió en esa entrega.
-- Si un alumno no sube algún problema, simplemente no hay renglón para ese
-- problem_index — eso es justo lo que usamos para calificarlo con 0.
CREATE TABLE IF NOT EXISTS submission_files (
    submission_id     TEXT NOT NULL REFERENCES submissions(submission_id),
    problem_index     INTEGER NOT NULL,   -- 1 a 5
    drive_file_id     TEXT,
    local_file_path   TEXT,
    PRIMARY KEY (submission_id, problem_index)
);

-- Calificación de CADA problema individual (detalle).
CREATE TABLE IF NOT EXISTS problem_grades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id     TEXT NOT NULL,
    problem_index     INTEGER NOT NULL,
    max_points        REAL NOT NULL,       -- normalmente 20
    score_raw         REAL NOT NULL,
    compile_ok        INTEGER NOT NULL,
    tests_passed      INTEGER,
    tests_total       INTEGER,
    feedback          TEXT,
    graded_at         TEXT NOT NULL,
    UNIQUE(submission_id, problem_index)
);

-- Calificación AGREGADA de la entrega completa (suma de los 5 problemas).
-- Esta es la que se usa para el promedio ponderado final (compute_final_grades).
CREATE TABLE IF NOT EXISTS grades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id     TEXT NOT NULL,
    score_raw         REAL NOT NULL,
    score_pct         REAL NOT NULL,
    plagiarism_score  REAL,
    plagiarism_with   TEXT,
    graded_at         TEXT NOT NULL,
    UNIQUE(submission_id)
);

CREATE VIEW IF NOT EXISTS v_student_category_avg AS
SELECT
    s.student_id,
    cw.category,
    AVG(g.score_pct) AS avg_pct,
    COUNT(*) AS n_items
FROM grades g
JOIN submissions s ON s.submission_id = g.submission_id
JOIN coursework cw ON cw.coursework_id = s.coursework_id
GROUP BY s.student_id, cw.category;
"""


@contextmanager
def get_conn():
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_student(conn, student_id, full_name, email=None):
    conn.execute(
        """INSERT INTO students (student_id, full_name, email) VALUES (?, ?, ?)
           ON CONFLICT(student_id) DO UPDATE SET full_name=excluded.full_name, email=excluded.email""",
        (student_id, full_name, email),
    )


def upsert_coursework(conn, coursework_id, title, category, unidad, max_points, due_date):
    conn.execute(
        """INSERT INTO coursework (coursework_id, title, category, unidad, max_points, due_date)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(coursework_id) DO UPDATE SET
             title=excluded.title, category=excluded.category, unidad=excluded.unidad,
             max_points=excluded.max_points, due_date=excluded.due_date""",
        (coursework_id, title, category, unidad, max_points, due_date),
    )


def upsert_submission(conn, submission_id, student_id, coursework_id, submitted_at, late, status="pending"):
    conn.execute(
        """INSERT INTO submissions (submission_id, student_id, coursework_id, submitted_at, late, status)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(submission_id) DO UPDATE SET
             submitted_at=excluded.submitted_at, late=excluded.late, status=excluded.status""",
        (submission_id, student_id, coursework_id, submitted_at, int(late), status),
    )


def upsert_submission_file(conn, submission_id, problem_index, drive_file_id, local_file_path):
    conn.execute(
        """INSERT INTO submission_files (submission_id, problem_index, drive_file_id, local_file_path)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(submission_id, problem_index) DO UPDATE SET
             drive_file_id=excluded.drive_file_id,
             local_file_path=COALESCE(excluded.local_file_path, submission_files.local_file_path)""",
        (submission_id, problem_index, drive_file_id, local_file_path),
    )


def get_submission_files(conn, submission_id) -> dict:
    """Regresa {problem_index: local_file_path} para una entrega."""
    rows = conn.execute(
        "SELECT problem_index, local_file_path FROM submission_files WHERE submission_id=?",
        (submission_id,),
    ).fetchall()
    return {r["problem_index"]: r["local_file_path"] for r in rows if r["local_file_path"]}


def save_problem_grade(conn, submission_id, problem_index, max_points, score_raw,
                        compile_ok, tests_passed, tests_total, feedback=""):
    conn.execute(
        """INSERT INTO problem_grades
             (submission_id, problem_index, max_points, score_raw, compile_ok,
              tests_passed, tests_total, feedback, graded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(submission_id, problem_index) DO UPDATE SET
             max_points=excluded.max_points, score_raw=excluded.score_raw,
             compile_ok=excluded.compile_ok, tests_passed=excluded.tests_passed,
             tests_total=excluded.tests_total, feedback=excluded.feedback,
             graded_at=excluded.graded_at""",
        (submission_id, problem_index, max_points, score_raw, int(compile_ok),
         tests_passed, tests_total, feedback, datetime.now(timezone.utc).isoformat()),
    )


def save_aggregate_grade(conn, submission_id, score_raw, max_points,
                          plagiarism_score=None, plagiarism_with=None):
    score_pct = 0.0 if max_points == 0 else round(score_raw / max_points, 4)
    conn.execute(
        """INSERT INTO grades (submission_id, score_raw, score_pct, plagiarism_score, plagiarism_with, graded_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(submission_id) DO UPDATE SET
             score_raw=excluded.score_raw, score_pct=excluded.score_pct,
             plagiarism_score=excluded.plagiarism_score, plagiarism_with=excluded.plagiarism_with,
             graded_at=excluded.graded_at""",
        (submission_id, score_raw, score_pct, plagiarism_score, plagiarism_with,
         datetime.now(timezone.utc).isoformat()),
    )
    status = "plagiarism_flag" if (plagiarism_score or 0) >= 1.0 else "graded"
    conn.execute("UPDATE submissions SET status=? WHERE submission_id=?", (status, submission_id))


def get_problem_grades(conn, submission_id) -> list:
    return conn.execute(
        "SELECT * FROM problem_grades WHERE submission_id=? ORDER BY problem_index",
        (submission_id,),
    ).fetchall()


def compute_final_grades(conn, weights: dict):
    rows = conn.execute("SELECT * FROM v_student_category_avg").fetchall()
    students = {}
    for r in rows:
        students.setdefault(r["student_id"], {})[r["category"]] = r["avg_pct"]

    result = {}
    for student_id, breakdown in students.items():
        final = 0.0
        for category, weight in weights.items():
            final += breakdown.get(category, 0.0) * weight
        result[student_id] = {"final": round(final * 100, 2), "breakdown": breakdown}
    return result
