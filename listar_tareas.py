from src.classroom_client import ClassroomClient
from src.config import load_config

cfg = load_config()
client = ClassroomClient()
tareas = client.list_coursework(cfg["course_id"])

for t in tareas:
    print(t["id"], "-", t["title"])