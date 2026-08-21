from src.classroom_client import ClassroomClient

client = ClassroomClient()
courses = client.list_courses()
for c in courses:
    print(c["id"], "-", c["name"])