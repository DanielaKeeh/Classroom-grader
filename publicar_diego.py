import sys
sys.path.insert(0, ".")
from src.classroom_client import ClassroomClient
from src.config import load_config
from src import db

cfg = load_config()
SUBMISSION_ID = "Cg4ItbSTp4UTEKmviOG6GQ"  # Diego Hernandez Tinajero
COURSEWORK_ID = "874766276521"  # Práctica 1

with db.get_conn() as conn:
    grade_row = conn.execute(
        "SELECT score_raw, score_pct FROM grades WHERE submission_id=?", (SUBMISSION_ID,)
    ).fetchone()

if not grade_row:
    print("No encontré una calificación guardada para Diego. Corre primero calificar_uno.py")
    sys.exit(1)

score = grade_row["score_raw"]
print(f"Nota guardada localmente: {score}/100")

client = ClassroomClient()
client.set_grade(cfg["course_id"], COURSEWORK_ID, SUBMISSION_ID, score=score, publish=True)
print(f"Listo — {score}/100 publicada y devuelta a Diego en Classroom real.")