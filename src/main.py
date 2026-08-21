"""
Orquestador principal. Uso:

    python -m src.main sync        # trae de Classroom lo nuevo (tareas + entregas + p1.c...p5.c)
    python -m src.main grade       # califica todas las entregas pendientes ya descargadas
    python -m src.main run         # sync + grade + export en un solo paso
    python -m src.main export      # solo regenera el Excel desde SQLite
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

    with db.get_conn() as conn:
        for s in client.list_students(course_id):
            profile = s["profile"]
            db.upsert_student(conn, s["userId"], profile.get("name", {}).get("fullName", "?"),
                               profile.get("emailAddress"))

        for cw in client.list_coursework(course_id):
            category, unidad = infer_category_and_unit(cw.get("title", ""))
            max_points = cw.get("maxPoints", 100)
            due = cw.get("dueDate")
            due_str = f"{due['year']}-{due['month']:02d}-{due['day']:02d}" if due else None
            db.upsert_coursework(conn, cw["id"], cw.get("title", ""), category, unidad, max_points, due_str)

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
                    conn,
                    submission_id=sub["id"],
                    student_id=sub["userId"],
                    coursework_id=cw["id"],
                    submitted_at=sub.get("updateTime"),
                    late=sub.get("late", False),
                    status=status,
                )

                for problem_index, drive_file_id in problem_files.items():
                    dest = SUBMISSIONS_DIR / cw["id"] / sub["userId"] / f"p{problem_index}.c"
                    client.download_drive_file(drive_file_id, dest)  # siempre baja la versión más reciente
                    db.upsert_submission_file(conn, sub["id"], problem_index, drive_file_id, str(dest))
    print("Sync completo.")


def _plagiarism_flags_por_practica(rows, cfg) -> dict[str, dict[int, tuple]]:
    """
    Para cada problem_index (1-5), compara ese archivo entre todos los
    alumnos de esta tarea. Regresa {student_id: {problem_index: (otro_student_id, score)}}
    solo para los que superan el threshold.
    """
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
    """Deja un rastro persistente en un archivo, no solo en el print de
    terminal — así te enteras aunque no estuvieras viendo la consola cuando
    corrió el scheduler."""
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
            "SELECT * FROM submissions WHERE status IN ('pending', 'partial_files')"
        ).fetchall()

        by_coursework: dict[str, list] = {}
        for row in pending:
            by_coursework.setdefault(row["coursework_id"], []).append(row)

    for coursework_id, rows in by_coursework.items():
        plag_flags = _plagiarism_flags_por_practica(rows, cfg)

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

                # --- Escritura de vuelta a Classroom (opcional, según config) ---
                if classroom_client:
                    tiene_plagio = plag_score is not None
                    publicar = (
                        write_cfg.get("auto_publish", False)
                        and not (tiene_plagio and write_cfg.get("skip_publish_if_plagiarism_flag", True))
                    )
                    try:
                        classroom_client.set_grade(
                            cfg["course_id"], coursework_id, r["submission_id"],
                            score=total, publish=publicar,
                        )
                        if tiene_plagio and not publicar:
                            nombre = conn.execute(
                                "SELECT full_name FROM students WHERE student_id=?", (r["student_id"],)
                            ).fetchone()
                            nombre_str = nombre["full_name"] if nombre else r["student_id"]
                            titulo_tarea = conn.execute(
                                "SELECT title FROM coursework WHERE coursework_id=?", (coursework_id,)
                            ).fetchone()
                            titulo_str = titulo_tarea["title"] if titulo_tarea else coursework_id
                            mensaje = (
                                f"PLAGIO DETECTADO — {nombre_str} en '{titulo_str}' "
                                f"(similitud {plag_score:.2f} con {plag_with}). "
                                f"Nota calculada: {total}/{maxp} (SOLO como borrador, no publicada)."
                            )
                            _log_plagiarism_alert(cfg, mensaje)
                            print(f"  [PLAGIO - NO publicado, alerta guardada] {nombre_str}")
                        elif publicar:
                            print(f"  [PUBLICADO] submission {r['submission_id']}: {total}/{maxp}")
                        else:
                            print(f"  [BORRADOR] submission {r['submission_id']}: {total}/{maxp}")
                    except Exception as e:
                        print(f"  [ERROR al escribir en Classroom] submission {r['submission_id']}: {e}")

    print("Calificación completa.")


def run(course_id: str):
    sync(course_id)
    grade_pending()
    path = export_excel.export()
    print(f"Reporte actualizado en {path}")


if __name__ == "__main__":
    cfg = config.load_config()
    action = sys.argv[1] if len(sys.argv) > 1 else "run"

    if action == "sync":
        sync(cfg["course_id"])
    elif action == "grade":
        grade_pending()
    elif action == "export":
        export_excel.export()
    elif action == "run":
        run(cfg["course_id"])
    else:
        print(f"Acción desconocida: {action}. Usa sync | grade | export | run")