# Classroom Grader — Programación Estructurada (IL352)

Pipeline que revisa automáticamente las Prácticas subidas a Google Classroom.
**Cada Práctica trae 5 problemas**, y el alumno sube un archivo `.c` por
problema, nombrado `p1.c`, `p2.c`, `p3.c`, `p4.c`, `p5.c` (según el número
de problema que le diste en la imagen/enunciado). El pipeline compila y
prueba cada uno por separado, y suma los 5 para la nota final de esa
Práctica (100 pts = 5 × 20 pts).

## Estado actual

Probado localmente de punta a punta con datos simulados: compilación,
casos de prueba, archivo faltante (se califica con 0 sin tronar), detección
de plagio por problema individual, base de datos, y exportación a Excel.
**Lo único que falta es conectar tu Classroom real** — sigue la sección 2.

## 1. Instalación

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

## 2. Habilitar la Google Classroom API (si ya la tenías de antes, sáltate esto)

1. [console.cloud.google.com](https://console.cloud.google.com/) con tu cuenta profesora.
2. Crea un proyecto (o usa el que ya tenías).
3. Habilita **Google Classroom API** y **Google Drive API**.
4. "Pantalla de consentimiento OAuth" (Google Auth Platform) → Externo →
   llena nombre/correo → agrégate como usuario de prueba.
5. "Credenciales" → "Crear credenciales" → "ID de cliente de OAuth" →
   tipo **Aplicación de escritorio** → descarga el JSON.
6. Renómbralo a `client_secret.json` y ponlo en `credentials/client_secret.json`.
7. Pon el `course_id` de tu Classroom real en `config.yaml`.

La primera vez que corras el pipeline te va a pedir login por navegador —
acepta con la cuenta de usuario de prueba. Esto genera `credentials/token.json`,
que ya no te lo vuelve a pedir después (se refresca solo).

**Nota WSL:** si el navegador no se abre solo, la terminal imprime una URL —
cópiala y pégala en tu navegador de Windows a mano. Si te sale un error de
"Scope has changed", ya está resuelto en `src/auth.py` (trae
`OAUTHLIB_RELAX_TOKEN_SCOPE=1` puesto de fábrica).

## 3. Convención de archivos que deben subir los alumnos

En las instrucciones de cada tarea de Classroom, deja siempre esta línea:

> Sube 5 archivos .c, nombrados p1.c, p2.c, p3.c, p4.c, p5.c (según el
> número de problema en la imagen). Debe compilar en C puro (no C++).

El pipeline (`classroom_client.py → extract_problem_files`) busca
exactamente esos nombres (sin distinguir mayúsculas/minúsculas) entre los
adjuntos de cada entrega. **Cualquier archivo con otro nombre se ignora**
—no truena el pipeline, simplemente ese problema queda sin calificar (0
puntos) y te va a aparecer así en el reporte para que lo revises tú.

## 4. Test cases: uno por problema, en una carpeta por tarea

```
tests/test_cases/<coursework_id>/
├── p1.json
├── p2.json
├── p3.json
├── p4.json
└── p5.json
```

El `coursework_id` real lo obtienes de Classroom una vez que sincronices
(`python -m src.main sync` te lo va a mostrar, o lo ves en los logs).
Mientras tanto, usa cualquier nombre para probar localmente — hay un
ejemplo completo ya armado en `tests/test_cases/coursework_demo/` y una
plantilla vacía en `tests/test_cases/EJEMPLO_coursework_id/`.

Formato de cada `pN.json` (idéntico al de antes, solo que ahora es un
archivo por problema en vez de por tarea completa):
```json
[
  {"name": "caso_1", "input": "5.0\n3.0\n", "expected_output": "15.00\n16.00\n", "points": 20}
]
```
Normalmente cada problema es un solo caso de prueba de 20 pts (todo o
nada), pero si quieres partirlo en sub-casos, los `points` de ese archivo
deben sumar 20.

## 5. Probar el motor de calificación sin Classroom

```python
from pathlib import Path
from src.grader import grade_practica, total_score
from src.config import DEFAULT_CONFIG

files = {
    1: Path("mi_p1.c"),
    2: Path("mi_p2.c"),
    # si falta alguno, simplemente no lo pongas en el diccionario
}
resultados = grade_practica(files, "coursework_demo", DEFAULT_CONFIG)
for i, r in resultados.items():
    print(f"p{i}: {r.score_raw}/{r.max_points}  compiló={r.compile_ok}")

total, maxp = total_score(resultados)
print(f"TOTAL: {total}/{maxp}")
```

## 6. Uso una vez conectado a Classroom

```bash
python -m src.main sync      # trae tareas + entregas + descarga p1.c...p5.c de cada quien
python -m src.main grade     # compila y califica lo pendiente (por problema, y suma)
python -m src.main export    # regenera data/calificaciones.xlsx desde SQLite
python -m src.main run       # las tres anteriores en un solo paso
```

El Excel trae 3 tipos de hoja: **Resumen** (promedio ponderado final),
**una por categoría** (nota agregada de cada Práctica/Examen/etc.), y
**Detalle_Problemas** (el desglose de cada uno de los 5 problemas, con las
filas en 0 resaltadas en rosa para que salten a la vista).

## 7. Automatizar por fecha límite

```bash
python -m src.scheduler --once   # una revisión
python -m src.scheduler          # loop, revisa cada N minutos (config.yaml)
```

## 8. Sobre la detección de plagio

Ahora compara **por problema individual entre alumnos** (todos los `p3.c`
de una Práctica entre sí, no el archivo completo de un alumno contra otro
— no tendría sentido comparar un p1.c contra un p4.c, son problemas
distintos). Sigue siendo `difflib` — sin dependencias, pero con falsos
positivos altos en programas cortos de intro. Trátalo como alerta para que
tú revises, no como veredicto automático. Más detalle sobre migrar a Moss
real: ver el docstring de `src/plagiarism.py`.

## 9. Estructura del proyecto

```
classroom-grader/
├── config.example.yaml
├── requirements.txt
├── credentials/              # client_secret.json y token.json (gitignored)
├── data/                      # calificaciones.db y .xlsx (gitignored)
├── tests/
│   ├── sample_c/               # .c de ejemplo para probar sin Classroom
│   └── test_cases/
│       └── <coursework_id>/     # p1.json...p5.json por cada Práctica real
└── src/
    ├── config.py
    ├── db.py                     # students, coursework, submissions,
    │                               submission_files, problem_grades, grades
    ├── grader.py                  # compila y prueba cada p{n}.c por separado
    ├── plagiarism.py               # similitud por problema entre alumnos
    ├── export_excel.py              # SQLite -> xlsx (con detalle por problema)
    ├── auth.py                       # OAuth de Google
    ├── classroom_client.py            # Classroom + Drive API, extrae p1.c...p5.c
    ├── main.py                         # orquestador: sync / grade / export / run
    └── scheduler.py                     # polling por fecha límite
```
