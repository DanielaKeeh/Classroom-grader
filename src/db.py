"""
Base de datos SQLite. NUEVO: students y coursework ahora guardan course_id,
para poder separar reportes por sección (D16 vs D23, etc.) en vez de
mezclarlos todos en un solo Excel.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    course_id       TEXT PRIMARY KEY,
    name            TEXT
);

CREATE TABLE IF NOT EXISTS students (
    student_id      TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    email           TEXT,
    course_id       TEXT
);

CREATE TABLE IF NOT EXISTS coursework (
    coursework_id   TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    unidad          INTEGER,
    max_points       REAL NOT NULL DEFAULT 100,
    due_date        TEXT,
    course_id       TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id     TEXT PRIMARY KEY,
    student_id        TEXT NOT NULL REFERENCES students(student_id),
    coursework_id     TEXT NOT NULL REFERENCES coursework(coursework_id),
    submitted_at      TEXT,
    late              INTEGER DEFAULT 0,
    status            TEXT DEFAULT 'pending',
    UNIQUE(student_id, coursework_id)
);

CREATE TABLE IF NOT EXISTS submission_files (
    submission_id     TEXT NOT NULL,
    problem_index     INTEGER NOT NULL,
    drive_file_id     TEXT,
    local_file_path   TEXT,
    PRIMARY KEY (submission_id, problem_index)
);

CREATE TABLE IF NOT EXISTS problem_grades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id     TEXT NOT NULL,
    problem_index     INTEGER NOT NULL,
    max_points        REAL NOT NULL,
    score_raw         REAL NOT NULL,
    compile_ok        INTEGER NOT NULL,
    tests_passed      INTEGER,
    tests_total       INTEGER,
    feedback          TEXT,
    graded_at         TEXT NOT NULL,
    UNIQUE(submission_id, problem_index)
);

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
        # Migración: si la base ya existía de antes de agregar course_id,
        # ALTER TABLE la pone al día sin perder datos. Si la columna ya
        # existe (base nueva), SQLite lanza error y lo ignoramos.
        for table, col in [("students", "course_id"), ("coursework", "course_id")]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # la columna ya existe


def upsert_course(conn, course_id, name):
    conn.execute(
        """INSERT INTO courses (course_id, name) VALUES (?, ?)
           ON CONFLICT(course_id) DO UPDATE SET name=excluded.name""",
        (course_id, name),
    )


def upsert_student(conn, student_id, full_name, email=None, course_id=None):
    conn.execute(
        """INSERT INTO students (student_id, full_name, email, course_id) VALUES (?, ?, ?, ?)
           ON CONFLICT(student_id) DO UPDATE SET
             full_name=excluded.full_name, email=excluded.email,
             course_id=COALESCE(excluded.course_id, students.course_id)""",
        (student_id, full_name, email, course_id),
    )


def upsert_coursework(conn, coursework_id, title, category, unidad, max_points, due_date, course_id=None):
    conn.execute(
        """INSERT INTO coursework (coursework_id, title, category, unidad, max_points, due_date, course_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(coursework_id) DO UPDATE SET
             title=excluded.title, category=excluded.category, unidad=excluded.unidad,
             max_points=excluded.max_points, due_date=excluded.due_date,
             course_id=COALESCE(excluded.course_id, coursework.course_id)""",
        (coursework_id, title, category, unidad, max_points, due_date, course_id),
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


def compute_final_grades(conn, weights: dict, course_id: str = None):
    """Si course_id se especifica, solo calcula para alumnos de esa sección."""
    query = """
        SELECT s.student_id, cw.category, AVG(g.score_pct) AS avg_pct
        FROM grades g
        JOIN submissions s ON s.submission_id = g.submission_id
        JOIN coursework cw ON cw.coursework_id = s.coursework_id
        JOIN students st ON st.student_id = s.student_id
    """
    params = ()
    if course_id:
        query += " WHERE st.course_id = ?"
        params = (course_id,)
    query += " GROUP BY s.student_id, cw.category"

    rows = conn.execute(query, params).fetchall()
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


def get_all_course_ids(conn) -> list:
    rows = conn.execute("SELECT DISTINCT course_id FROM students WHERE course_id IS NOT NULL").fetchall()
    return [r["course_id"] for r in rows]


def get_course_name(conn, course_id: str) -> str:
    row = conn.execute("SELECT name FROM courses WHERE course_id=?", (course_id,)).fetchone()
    return row["name"] if row and row["name"] else course_id
