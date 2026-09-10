"""
Configuración central del pipeline de calificación automática.
"""
import os
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"
CREDENTIALS_DIR = BASE_DIR / "credentials"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "calificaciones.db"
EXCEL_PATH = DATA_DIR / "calificaciones.xlsx"

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    # ESTE YA NO ES READONLY: necesitamos escribir calificaciones de vuelta.
    # Requiere borrar credentials/token.json y volver a autenticar una vez
    # que se agregue este scope (el token viejo no lo va a tener autorizado).
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

DEFAULT_CONFIG = {
    "course_ids": [],
    "weights": {
        "examen_departamental": 0.20,
        "examenes_por_tema": 0.20,
        "practicas": 0.20,
        "investigaciones": 0.20,
        "proyecto_final": 0.20,
    },
    "compile": {
        "compiler": "gcc",
        "flags": ["-std=c11", "-Wall", "-lm"],
        "timeout_seconds": 5,
    },
    "scheduler": {
        "check_interval_minutes": 30,
    },
    "plagiarism": {
        "enabled": True,
        "similarity_threshold": 0.90,
    },
    "claude_feedback": {
        "enabled": False,
        "model": "claude-sonnet-5",
    },
    "practica": {
        "problemas_por_practica": 5,
        "patron_nombre_archivo": r"^p([1-5])\.c$",  # case-insensitive al usarlo
    },
    # NUEVO: escritura de calificaciones de vuelta a Classroom.
    "classroom_write": {
        # Si es True, en cuanto se califica una entrega, el pipeline le pone
        # la nota (assignedGrade) Y la "devuelve" (return) para que el
        # alumno la vea de inmediato con notificación, SIN que tú la revises.
        "auto_publish": True,
        # Candado de seguridad: si la entrega salió marcada por el detector
        # de plagio, NO se auto-publica aunque auto_publish sea True — se
        # deja como draftGrade (solo tú la ves) para que decidas a mano.
        "skip_publish_if_plagiarism_flag": True,
    },
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
