"""
Motor de calificación automática para entregas en C.

CAMBIO respecto a la primera versión: una Práctica ya no es "1 programa,
varios tests" — son 5 PROGRAMAS distintos (p1.c...p5.c), cada uno con sus
propios casos de prueba. Por eso los test cases ahora viven en una carpeta
por tarea, no en un solo archivo:

    tests/test_cases/<coursework_id>/p1.json
    tests/test_cases/<coursework_id>/p2.json
    ...
    tests/test_cases/<coursework_id>/p5.json

Cada p{n}.json tiene el mismo formato de antes:
[
  {"name": "caso_1", "input": "5\\n3\\n", "expected_output": "8\\n", "points": 20}
]
Normalmente cada problema es UN solo caso de prueba de 20 pts (todo o nada),
pero si quieres partir un problema en sub-casos (ej. 10+10), el formato ya lo
permite tal cual — solo asegúrate que los "points" de ese archivo sumen 20.
"""
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class TestResult:
    name: str
    passed: bool
    points: float
    got: str = ""
    expected: str = ""


@dataclass
class GradeResult:
    compile_ok: bool
    compile_log: str
    tests: list = field(default_factory=list)
    score_raw: float = 0.0
    max_points: float = 20.0

    @property
    def score_pct(self) -> float:
        return 0.0 if self.max_points == 0 else round(self.score_raw / self.max_points, 4)

    @property
    def tests_passed(self) -> int:
        return sum(1 for t in self.tests if t.passed)

    @property
    def tests_total(self) -> int:
        return len(self.tests)


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def compile_c(source_path: Path, work_dir: Path, cfg: dict):
    binary_path = work_dir / "program"
    compiler = cfg["compile"]["compiler"]
    flags = cfg["compile"]["flags"]
    cmd = [compiler, str(source_path), "-o", str(binary_path), *flags]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return False, "La compilación tardó demasiado (posible error de sintaxis grave).", None
    if proc.returncode != 0:
        return False, proc.stderr, None
    return True, proc.stderr, binary_path


def run_test_case(binary_path: Path, test_input: str, timeout_seconds: int):
    try:
        proc = subprocess.run(
            [str(binary_path)], input=test_input, capture_output=True, text=True, timeout=timeout_seconds,
        )
        return proc.stdout, False, proc.stderr
    except subprocess.TimeoutExpired:
        return "", True, "Tiempo límite excedido (posible ciclo infinito)."


def load_test_cases_for_problem(coursework_id: str, problem_index: int) -> list[dict]:
    path = config.BASE_DIR / "tests" / "test_cases" / coursework_id / f"p{problem_index}.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def grade_one_file(source_code_path: Path, test_cases: list[dict], max_points: float, cfg: dict) -> GradeResult:
    """Compila y prueba UN archivo .c contra su lista de test cases. Es la
    misma lógica de siempre, solo que ahora se llama una vez por problema."""
    with tempfile.TemporaryDirectory(prefix="grader_") as tmp:
        work_dir = Path(tmp)
        local_source = work_dir / "student_submission.c"
        local_source.write_text(source_code_path.read_text(encoding="utf-8", errors="replace"))

        compile_ok, compile_log, binary_path = compile_c(local_source, work_dir, cfg)
        if not compile_ok:
            return GradeResult(compile_ok=False, compile_log=compile_log, tests=[],
                                score_raw=0.0, max_points=max_points)

        results = []
        timeout = cfg["compile"]["timeout_seconds"]
        for case in test_cases:
            stdout, timed_out, stderr = run_test_case(binary_path, case.get("input", ""), timeout)
            passed = (not timed_out) and _normalize(stdout) == _normalize(case["expected_output"])
            results.append(TestResult(
                name=case.get("name", "sin_nombre"), passed=passed,
                points=case.get("points", 0), got=stdout, expected=case["expected_output"],
            ))

        score_raw = sum(t.points for t in results if t.passed)
        return GradeResult(compile_ok=True, compile_log=compile_log, tests=results,
                            score_raw=score_raw, max_points=max_points)


def grade_practica(files: dict[int, Path], coursework_id: str, cfg: dict) -> dict[int, GradeResult]:
    """
    files: {problem_index: path_al_archivo_c}. Puede traer menos de 5 llaves
    si al alumno le faltó subir algún problema — esos se califican con 0
    automático (no compilaron nada porque no hay nada que compilar).

    Regresa {problem_index: GradeResult} para los 5 problemas (1 a 5),
    incluyendo los que faltaron (con score 0 y compile_ok=False).
    """
    n_problemas = cfg["practica"]["problemas_por_practica"]
    results = {}

    for i in range(1, n_problemas + 1):
        test_cases = load_test_cases_for_problem(coursework_id, i)
        max_points = sum(c.get("points", 0) for c in test_cases) or 20.0

        if i not in files:
            results[i] = GradeResult(
                compile_ok=False,
                compile_log=f"No se encontró el archivo p{i}.c en la entrega.",
                tests=[], score_raw=0.0, max_points=max_points,
            )
            continue

        results[i] = grade_one_file(files[i], test_cases, max_points, cfg)

    return results


def total_score(problem_results: dict[int, GradeResult]) -> tuple[float, float]:
    """Regresa (score_raw_total, max_points_total) sumando los 5 problemas."""
    score = sum(r.score_raw for r in problem_results.values())
    maxp = sum(r.max_points for r in problem_results.values())
    return score, maxp
