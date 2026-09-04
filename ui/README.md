# ui — CLI de visualización del progreso

CLI de biblioteca estándar (`argparse`, sin dependencias) sobre la API pública
de `LearningTracker`. Esta capa **no calcula nada**: muestra lo que el motor
responde. No importa `core.leveling` ni `core.scheduling`, y no lee intentos
del store por su cuenta (un test con AST lo verifica).

## Uso

```
python -m ui [--data DIR] [--profile ID] [--as-of ISO8601] COMANDO ...
```

- `--data DIR`: directorio con `profiles.json` y `attempts.json` (default `./data`).
- `--profile ID`: perfil sobre el que se opera. Obligatorio salvo en `profile`.
- `--as-of ISO8601`: fecha de consulta. Si falta se usa el reloj del sistema.
  Una fecha sin zona horaria se asume UTC; se acepta el sufijo `Z`.

Comandos:

| Comando | Qué hace |
| --- | --- |
| `profile create ID --name NOMBRE` / `profile list` | Crea o lista perfiles |
| `objective add ID --title T [--domain D] [--weight W]` | Añade o reemplaza un objetivo |
| `objectives` | Catálogo del perfil con nivel y score en `--as-of` |
| `record ID --correct\|--wrong [--at ISO] [--kind K] [--confidence C] [--note N] [--id X]` | Registra un intento. Sin `--at` usa `--as-of` o el reloj |
| `state ID` | Estado completo de un objetivo (SPEC §1.5) |
| `due [--limit N]` | Qué toca repasar, por urgencia (SPEC §5.2) |
| `unstarted` | Objetivos sin ningún intento |
| `stale [--days N]` | Objetivos sin actividad en N días (default 14) |
| `summary` | Agregado del perfil: reparto por nivel, cobertura |
| `timeline ID --start ISO --end ISO [--step-days N]` | Serie temporal (SPEC §5.3) |
| `compare ID --earlier ISO --later ISO` | "¿Estaba mejor hace dos semanas?" (SPEC §5.1) |
| `check` | Chequeo de consistencia por conteos (SPEC §8, fallo 2) |

Códigos de salida: `0` ok; `1` solo en `check` cuando `ok=False`; `2` error de
uso o de dominio (`UnknownObjectiveError`, `DuplicateAttemptError`,
`InvalidAttemptError`, `StorageError`...). Nunca un traceback.

## Concurrencia del backend JSON

Cada escritura (registrar un intento, crear un perfil, añadir objetivos) toma un
lock exclusivo (`flock`) sobre un archivo vacío `attempts.json.lock` /
`profiles.json.lock` junto al JSON, así que dos CLIs que escriben a la vez en el
mismo `--data` no se pisan: la segunda espera a que termine la primera. La
garantía vale para procesos del mismo host; en sistemas de archivos de red (NFS,
SMB) `flock` no es fiable y no hay exclusión. Los `.lock` se pueden borrar sin
riesgo: se recrean en la siguiente escritura.

## Ejemplos

```sh
# Crear un perfil y un objetivo
python -m ui profile create ai-103 --name "Azure AI-103"
python -m ui --profile ai-103 objective add D3.2 --title "Content understanding" --domain D3

# Registrar la serie "mal, mal, mal, bien, mal" en fechas inyectadas
for d in 01 02 03; do python -m ui --profile ai-103 record D3.2 --wrong --at 2026-01-${d}T10:00Z; done
python -m ui --profile ai-103 record D3.2 --correct --at 2026-01-04T10:00Z
python -m ui --profile ai-103 record D3.2 --wrong   --at 2026-01-05T10:00Z

# ¿Cómo estaba el 3 de enero? (no cambia aunque se registren intentos después)
python -m ui --profile ai-103 --as-of 2026-01-03T12:00Z state D3.2

# ¿Estaba mejor hace dos semanas? Y qué toca repasar hoy
python -m ui --profile ai-103 compare D3.2 --earlier 2026-02-15 --later 2026-03-01
python -m ui --profile ai-103 due --limit 5
```
