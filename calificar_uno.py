import sys
from pathlib import Path

sys.path.insert(0, ".")
from src import db, config
from src.grader import grade_practica, total_score

SUBMISSION_ID = "Cg4ItbSTp4UTEKmviOG6GQ"  # Diego Hernandez Tinajero
COURSEWORK_ID = "874766276521"  # Práctica 1

cfg = config.load_config()

with db.get_conn() as conn:
    files = {i: Path(p) for i, p in db.get_submission_files(conn, SUBMISSION_ID).items()}
    print(f"Archivos encontrados: {list(files.keys())}")

    results = grade_practica(files, COURSEWORK_ID, cfg)

    for i, r in results.items():
        print(f"p{i}: {r.score_raw}/{r.max_points}  ({r.tests_passed}/{r.tests_total} casos)")
        for t in r.tests:
            estado = "OK" if t.passed else "FALLO"
            print(f"   [{estado}] {t.name}")
        if not r.compile_ok:
            print("   ", r.compile_log.strip()[:200])

        feedback = r.compile_log if not r.compile_ok else f"{r.tests_passed}/{r.tests_total} pruebas pasadas."
        db.save_problem_grade(conn, SUBMISSION_ID, i, r.max_points, r.score_raw,
                               r.compile_ok, r.tests_passed, r.tests_total, feedback)

    total, maxp = total_score(results)
    db.save_aggregate_grade(conn, SUBMISSION_ID, total, maxp)
    print(f"\nTOTAL de Diego: {total}/{maxp}  ({100*total/maxp:.1f}%)")