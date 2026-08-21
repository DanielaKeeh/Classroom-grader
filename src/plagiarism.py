"""
Detección de similitud entre entregas de un MISMO problema (ej. todos los
p3.c de la Práctica 4, entre sí) — no tiene sentido comparar el p1.c de un
alumno contra el p4.c de otro, son problemas distintos.
"""
import difflib
import re
from pathlib import Path


def _strip_noise(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    code = re.sub(r"//.*", "", code)
    code = re.sub(r"\s+", " ", code)
    return code.strip()


def similarity(code_a: str, code_b: str) -> float:
    a, b = _strip_noise(code_a), _strip_noise(code_b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def compute_similarity_matrix(submissions: dict[str, Path]) -> list[tuple[str, str, float]]:
    items = list(submissions.items())
    results = []
    codes = {sid: Path(path).read_text(encoding="utf-8", errors="replace") for sid, path in items}

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            sid_a, sid_b = items[i][0], items[j][0]
            score = similarity(codes[sid_a], codes[sid_b])
            results.append((sid_a, sid_b, score))

    return sorted(results, key=lambda r: r[2], reverse=True)


def flag_pairs(submissions: dict[str, Path], threshold: float) -> dict[str, tuple[str, float]]:
    matrix = compute_similarity_matrix(submissions)
    best = {}
    for sid_a, sid_b, score in matrix:
        if score < threshold:
            continue
        for sid, other in ((sid_a, sid_b), (sid_b, sid_a)):
            if sid not in best or score > best[sid][1]:
                best[sid] = (other, score)
    return best
