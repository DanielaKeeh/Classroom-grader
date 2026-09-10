import sys
sys.path.insert(0, ".")
from src.classroom_client import ClassroomClient

client = ClassroomClient()
tareas = client.list_coursework("855520777058")  # D16
for t in tareas:
    print(t["id"], "-", t["title"])