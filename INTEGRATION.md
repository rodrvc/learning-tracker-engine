# Cómo conectar el motor a una fuente de estudio

Este motor no sabe qué estudias. No tiene preguntas, no corrige, no conoce ningún
temario. Lleva la contabilidad: qué practicaste, cuándo acertaste y qué toca repasar.

Para que sirva hace falta una **fuente** que haga las preguntas — un repositorio de
apuntes, un banco de preguntas, un agente tutor, una app — y que le reporte los
resultados. Este documento explica ese acoplamiento, sin atarse a ninguna materia.

---

## El reparto

| El motor pone | La fuente pone |
| --- | --- |
| Qué toca repasar hoy | Las preguntas |
| El nivel por tema | Quién corrige |
| Cuándo se está olvidando algo | El material de estudio |
| El historial completo | La conversación con quien estudia |

El motor nunca decide si una respuesta fue correcta. **Eso lo decide la fuente** y se
lo comunica. Un `--correct` puede venir de un quiz automático, de un examen simulado o
de que la persona diga "esto lo tenía claro": al motor le da igual, solo cuenta.

---

## El ciclo

```
1. La fuente pregunta al motor qué toca      ->  due
2. La fuente elige material de esos temas
3. La fuente pregunta a la persona
4. La persona responde
5. La fuente le dice al motor cómo fue       ->  record --correct | --wrong
```

Sin el paso 1, la fuente pregunta lo que se le ocurre. Con él, pregunta **lo que se
está olvidando**. Ese es todo el valor del acoplamiento.

El paso 5 es obligatorio: un intento que no se registra no existe, y el motor no puede
inferirlo. Si la sesión termina sin registrar nada, el nivel no se mueve — y eso es
correcto, porque no hay evidencia de que se haya practicado.

---

## Paso 1 — Definir los objetivos

Un **objetivo** es la unidad más pequeña que tiene sentido repasar por separado. La
elección determina el grano de todo lo demás, así que conviene pensarla una vez:

| Fuente | Objetivo razonable |
| --- | --- |
| Repositorio de apuntes | Un apunte |
| Curso con módulos | Un módulo |
| Idioma | Un punto gramatical o un bloque de vocabulario |
| Temario de certificación | Un dominio, o un objetivo del temario |

Dos criterios prácticos:

- **Ni tan fino que nunca acumules intentos suficientes** (con menos de 2 el motor
  devuelve `UNASSESSED` a propósito), **ni tan grueso que "lo tengo flojo" no diga
  dónde**.
- **Estable en el tiempo.** El `objective_id` es la clave del historial: si se renombra,
  se pierde el hilo de lo practicado. Prefiere un identificador corto y sin acentos
  (`rag-grounding`), no el título completo del material.

```bash
learning-tracker --data <RUTA> profile create <perfil> --name "<Nombre>"
learning-tracker --data <RUTA> --profile <perfil> objective add rag-grounding \
    --title "RAG y grounding"
```

Dar de alta objetivos es idempotente en la práctica: hacerlo dos veces no duplica
historial, porque el historial vive en los intentos, no en el objetivo.

---

## Paso 2 — Consultar antes de preguntar

```bash
learning-tracker --data <RUTA> --profile <perfil> due
```

Devuelve lo vencido, **lo más urgente primero**. Si está vacío, no hay nada pendiente
y conviene mirar lo que aún no se ha tocado:

```bash
learning-tracker --data <RUTA> --profile <perfil> unstarted   # nunca practicado
learning-tracker --data <RUTA> --profile <perfil> stale       # sin actividad reciente
learning-tracker --data <RUTA> --profile <perfil> summary     # cómo va el conjunto
```

`unstarted` y `due` son deliberadamente distintos: *"nunca lo he visto"* y *"toca
repasarlo"* son cosas diferentes, y mezclarlas esconde el material sin cubrir.

---

## Paso 3 — Registrar el resultado

```bash
learning-tracker --data <RUTA> --profile <perfil> record rag-grounding --correct
learning-tracker --data <RUTA> --profile <perfil> record rag-grounding --wrong
```

Opciones útiles:

| Opción | Para qué |
| --- | --- |
| `--kind quiz\|exercise\|lab\|exam_sim\|self_report` | De dónde salió el intento |
| `--note "..."` | Qué se falló exactamente |
| `--at ISO8601` | Registrar con fecha pasada (sesión no anotada en su momento) |
| `--confidence N` | Se guarda, pero **no afecta al cálculo** |
| `--id <attempt_id>` | Idempotencia: repetir el mismo id lanza `DuplicateAttemptError` |

Una pregunta, un `record`. No agrupes cinco preguntas de un tema en un solo intento:
el motor pondera por recencia y necesita los intentos separados para ver la tendencia.

---

## Dónde viven los datos

El motor no elige la ubicación: se la pasa quien lo invoca, con `--data`.

**La recomendación es guardarlos junto al material de estudio**, no en una carpeta del
sistema. Los datos son de ese estudio, no de esa máquina:

```
tu-repo-de-estudio/
├── material/          <- los apuntes, preguntas, lo que sea
└── .learning/         <- attempts.json + profiles.json
```

Decide conscientemente si ese directorio entra en git:

- **Sí:** ganas historial y sincronización entre máquinas. Como el historial es
  append-only y cada `attempt_id` es único, un conflicto de merge se resuelve
  **uniendo las dos listas** — no hay estado mutable que reconciliar.
- **No** (añádelo a `.gitignore`): si el repositorio se comparte o se hace público, el
  progreso personal no queda a la vista. Entonces conviene una copia periódica:
  `cp -R .learning ~/backups/<proyecto>-$(date +%Y%m%d)`.

---

## Integrar un agente tutor

Si la fuente es un agente (Claude Code u otro), el acoplamiento son **instrucciones en
su `CLAUDE.md`**, no código. El patrón mínimo:

```markdown
## Seguimiento del progreso

Los datos viven en `.learning/`. Usa siempre `--data .learning/` y el perfil `<perfil>`.

**Al empezar una sesión de estudio**, consulta qué toca:

    learning-tracker --data .learning/ --profile <perfil> due

Si `due` está vacío, mira `unstarted` para material sin cubrir.
Elige el material de esos temas, no otros.

**Tras cada pregunta que le hagas a la persona**, registra el resultado:

    learning-tracker --data .learning/ --profile <perfil> record <objetivo> --correct
    learning-tracker --data .learning/ --profile <perfil> record <objetivo> --wrong

Una pregunta, un registro. Usa `--note` para anotar qué se falló.
No cierres la sesión sin registrar: un intento no registrado no existe.
```

Nada de esto es específico de una materia. Cambia el `<perfil>` y los objetivos, y el
mismo bloque sirve para cualquier temario.

---

## Integrar código

Si la fuente es un programa, sáltate la CLI y usa el motor como librería. `core/` solo
conoce dos Protocols (`AttemptStore`, `ProfileStore`), así que el almacenamiento lo
eliges tú:

```python
from core import LearningTracker
from store import JsonAttemptStore, JsonProfileStore, SystemClock

clock = SystemClock()
tracker = LearningTracker(
    profile_id="mi-perfil",
    attempts=JsonAttemptStore(".learning/attempts.json"),   # ruta de archivo,
    profiles=JsonProfileStore(".learning/profiles.json"),   # no de directorio
    clock=clock,
)

for objetivo in tracker.get_due():
    ...                                                      # preguntar
    tracker.record_attempt(
        objetivo.objective_id,
        correct=True,
        at=clock.now(),                                      # `at` es obligatorio
    )
```

Dos detalles que la firma impone a propósito:

- Los stores JSON reciben la **ruta de cada archivo**, no la del directorio.
- `record_attempt` exige `at`. El motor nunca llama al reloj por su cuenta —
  quien integra decide qué instante se registra, y por eso se pueden simular meses de
  estudio en un test. La CLI lo rellena con su reloj cuando no pasas `--at`.

Para usar otro almacenamiento (una base de datos, una API), implementa los Protocols de
`core/storage.py`. El motor no cambia: no sabe qué hay detrás.

Las garantías que debe cumplir cualquier implementación están en los docstrings de
`core/storage.py`, y son las que sostienen las invariantes del motor: `append` atómico
o excepción (nunca éxito silencioso a medias), rechazo de `attempt_id` duplicado, y
lecturas ordenadas por fecha.

---

## Qué esperar los primeros días

El motor arranca sin evidencia, y eso se nota:

| Momento | Qué verás |
| --- | --- |
| Intento 1 de un tema | `UNASSESSED`. Con menos de 2 intentos no asigna nivel |
| Intentos 2-3 | Aparece un nivel, todavía volátil |
| Primera semana | `due` empieza a tener sentido |
| Tras un mes sin tocar un tema | Baja solo, y vuelve a aparecer en `due` |

No es un error que al principio casi todo esté en `UNASSESSED` o en `unstarted`: es la
diferencia entre *"no lo sé"* y *"aún no hay evidencia"*, y el motor la mantiene a
propósito.

---

## Verificar que todo está sano

```bash
learning-tracker --data <RUTA> --profile <perfil> check
```

Compara conteos y sumas contra lo que hay en disco. Sale con código 1 si algo no cuadra.
Útil tras editar los JSON a mano o sincronizar entre máquinas.

Como el historial es la única fuente de verdad y todo lo demás se recalcula, casi
cualquier desajuste se arregla solo: no hay agregados persistidos que puedan quedar
corruptos.
