"""
Polling simple por fecha límite (sin Pub/Sub, sin webhook público).

Uso:
    python -m src.scheduler --once   # una sola pasada
    python -m src.scheduler          # loop infinito, revisa cada N minutos
"""
import sys
import time
from datetime import date, datetime

from . import config, db, main as pipeline


def _is_past_due(due_date_str: str | None) -> bool:
    if not due_date_str:
        return False
    return date.fromisoformat(due_date_str) < date.today()


def check_and_grade_due_tasks():
    cfg = config.load_config()
    pipeline.sync(cfg["course_id"])

    with db.get_conn() as conn:
        due_with_pending = conn.execute(
            """
            SELECT DISTINCT cw.coursework_id, cw.title, cw.due_date
            FROM coursework cw
            JOIN submissions s ON s.coursework_id = cw.coursework_id
            WHERE s.status IN ('pending', 'partial_files')
            """
        ).fetchall()

    any_due = any(_is_past_due(r["due_date"]) for r in due_with_pending)
    if any_due:
        print(f"[{datetime.now().isoformat()}] Hay tareas vencidas con entregas pendientes, calificando...")
        pipeline.grade_pending()
        from . import export_excel
        export_excel.export()
    else:
        print(f"[{datetime.now().isoformat()}] Nada vencido con pendientes por ahora.")


def loop_forever():
    cfg = config.load_config()
    interval = cfg["scheduler"]["check_interval_minutes"] * 60
    while True:
        try:
            check_and_grade_due_tasks()
        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(interval)


if __name__ == "__main__":
    if "--once" in sys.argv:
        check_and_grade_due_tasks()
    else:
        loop_forever()
