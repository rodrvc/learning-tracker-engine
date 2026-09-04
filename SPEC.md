# SPEC — Contrato del motor de tracking de aprendizaje

Versión 1.0 · 2026-09-02

Este documento es **el contrato**. El código de `core/` son firmas vacías; la
única fuente de verdad sobre el comportamiento es este archivo. Si el código y
la spec discrepan, **gana la spec**.

Está escrito para que dos personas que no hablan entre sí — quien implementa y
quien testea — lleguen al mismo resultado. Por eso cada regla lleva números y
cada ejemplo está recorrido paso a paso.

---

## 0. Vocabulario y decisiones de fondo

| Término | Qué es |
| --- | --- |
| **Perfil** (`Profile`) | Un tema de estudio con sus objetivos. Ej.: "AI-103". Es el contenedor raíz. |
| **Objetivo** (`Objective`) | Una unidad de conocimiento que se puede evaluar. Ej.: "elegir entre Azure AI Search y RAG manual". |
| **Intento** (`Attempt`) | Un hecho ocurrido: en tal fecha, sobre tal objetivo, se respondió bien o mal. **Inmutable.** |
| **Nivel** (`Level`) | Una **proyección** calculada del historial de intentos. Nunca se almacena como verdad. |
| **Instantánea** (`Snapshot`) | El nivel de uno o de todos los objetivos **tal como era en una fecha dada**. |

### Las tres decisiones que gobiernan todo lo demás

1. **El historial de intentos es el único dato persistente.** Nivel, próximo
   repaso, estadísticas: todo se recalcula. No hay contadores acumulativos que
   se puedan corromper, porque no hay contadores: hay una lista de hechos.
2. **El tiempo entra siempre por parámetro.** Ninguna función de `core/`
   consulta el reloj del sistema. Quien necesita "hoy" recibe un `Clock` o una
   fecha explícita.
3. **Toda consulta acepta un `as_of` (fecha de corte).** Preguntar el nivel es,
   en realidad, preguntar el nivel *en una fecha*. Si no se indica, se usa la
   fecha del reloj inyectado. No existe una consulta "sin tiempo".

---

## 1. Modelo de datos

### 1.1 Perfil — `Profile`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `profile_id` | `str` | Identificador estable. Ej.: `"ai-103"`. Único. |
| `name` | `str` | Nombre legible. Ej.: `"Microsoft AI-103"`. |
| `objectives` | `dict[str, Objective]` | Objetivos indexados por `objective_id`. |

Un perfil no tiene estado de progreso propio: su progreso es la agregación del
de sus objetivos. Multi-perfil funciona porque cada perfil es un contenedor
independiente y ningún `objective_id` cruza fronteras de perfil.

### 1.2 Objetivo — `Objective`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `objective_id` | `str` | Único **dentro del perfil**. Ej.: `"D3.2-content-understanding"`. |
| `title` | `str` | Descripción legible. |
| `domain` | `str \| None` | Agrupación opcional. Ej.: `"D3"`. |
| `weight` | `float` | Peso relativo en el examen, por defecto `1.0`. Solo informativo: **no afecta al nivel**. |

Un objetivo **no guarda** nivel, racha, contadores ni fecha de repaso. Todo eso
se deriva. Esto es deliberado (ver §8, fallos 1 y 3).

### 1.3 Intento — `Attempt`

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `attempt_id` | `str` | Identificador único e inmutable del intento. |
| `objective_id` | `str` | A qué objetivo pertenece. |
| `at` | `datetime` | **Cuándo ocurrió.** Con zona horaria (UTC recomendado). Lo inyecta quien registra; el motor no lo genera. |
| `correct` | `bool` | `True` = acierto, `False` = fallo. Es el único eje binario. |
| `kind` | `AttemptKind` | Naturaleza de la evidencia: `QUIZ`, `EXERCISE`, `LAB`, `EXAM_SIM`, `SELF_REPORT`. |
| `confidence` | `float \| None` | 0.0–1.0, autoevaluación opcional. **No afecta al nivel** en v1. |
| `note` | `str \| None` | Texto libre. Ej.: el enunciado, o por qué falló. |
| `recorded_at` | `datetime \| None` | Cuándo se escribió en el store, si difiere de `at`. Solo auditoría. |

**Un intento nunca se modifica ni se borra.** Si hubo un error de registro se
añade un intento correctivo o se marca en `note`; el historial es append-only.

### 1.4 Nivel — `Level`

Enum **ordenado**. Los valores numéricos existen para poder comparar y graficar
("¿estaba mejor hace dos semanas?" es `level_hace_dos_semanas > level_hoy`).

| Nivel | Valor | Significado |
| --- | --- | --- |
| `UNASSESSED` | 0 | Sin evidencia suficiente. |
| `WEAK` | 1 | Falla lo básico. |
| `LEARNING` | 2 | Entiende, falla detalles. |
| `COMPETENT` | 3 | Acierta consistentemente. |
| `MASTERED` | 4 | Acierta consistentemente y de forma sostenida en el tiempo. |

### 1.5 Estado de un objetivo — `ObjectiveState`

Lo que devuelve una consulta. **Todos sus campos son derivados**, ninguno se
persiste.

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `objective_id` | `str` | — |
| `as_of` | `datetime` | Fecha de corte con la que se calculó. |
| `level` | `Level` | Nivel según §2. |
| `score` | `float` | Puntuación continua 0.0–1.0 que produce el nivel (§2.2). Permite comparar dos objetivos del mismo nivel. |
| `total_attempts` | `int` | Intentos con `at <= as_of`. |
| `correct_attempts` | `int` | De esos, cuántos `correct=True`. |
| `recent_window` | `tuple[bool, ...]` | Los últimos `N=8` resultados hasta `as_of`, **del más antiguo al más reciente**. |
| `first_attempt_at` | `datetime \| None` | — |
| `last_attempt_at` | `datetime \| None` | — |
| `distinct_days` | `int` | Número de **días naturales distintos** con al menos un intento. |
| `days_since_last` | `float \| None` | Días fraccionarios entre el último intento y `as_of`. Es el `gap` que alimenta el decaimiento (§2.2). `None` si no hay intentos. |
| `retention` | `float` | Factor de decaimiento aplicado, en `[RETENTION_FLOOR, 1.0]` (§2.2). |
| `next_review_at` | `datetime \| None` | Próximo repaso según §4. `None` si no hay intentos. |
| `is_due` | `bool` | `next_review_at <= as_of`. |

Nótese que **no hay campo `streak`**. Está prohibido por diseño (§8, fallo 1).

---

## 2. Cómo se calcula el nivel

El nivel es **una función pura del conjunto de intentos con `at <= as_of`**.
Mismo historial y misma fecha de corte ⇒ mismo nivel, siempre, en cualquier
máquina y en cualquier orden de inserción.

### 2.1 Constantes

| Constante | Valor | Qué es |
| --- | --- | --- |
| `WINDOW` | `8` | Cuántos intentos recientes forman la ventana. |
| `MIN_ATTEMPTS` | `2` | Mínimo de intentos para salir de `UNASSESSED`. |
| `DECAY_HALF_LIFE_DAYS` | `90` | Cada 90 días sin actividad, la retención se reduce a la mitad. |
| `RETENTION_FLOOR` | `0.40` | Suelo del factor de retención. **Solo afecta a `retention`, nunca al `raw`.** |
| `MASTERY_MIN_DAYS` | `2` | Días naturales distintos con intentos exigidos para `MASTERED`. |
| `MASTERY_MIN_SPAN_DAYS` | `7` | Días entre el primer y el último intento exigidos para `MASTERED`. |
| `MASTERY_MIN_RAW` | `0.95` | `raw` mínimo para ascender a `MASTERED` (ver §2.4). |

### 2.2 Paso a paso

**Paso 1 — Filtrar y ordenar.**
Toma todos los intentos del objetivo con `at <= as_of`. Ordénalos por `at`
ascendente. En caso de empate exacto de `at`, desempata por `attempt_id`
ascendente (lexicográfico). Este desempate hace el resultado independiente del
orden de inserción (§7, caso límite 3).

Llamemos `n` al total resultante.

**Paso 2 — Si `n < MIN_ATTEMPTS` (es decir, 0 o 1 intento) ⇒ `UNASSESSED`.**
`score = 0.0`. Se para aquí. Un solo acierto no es evidencia.

**Paso 3 — Ventana reciente.**
Toma los últimos `min(n, WINDOW)` intentos de la lista ordenada. Llamemos `w` a
su tamaño. Asigna a cada uno un **peso posicional**: el más reciente pesa `w`,
el siguiente `w-1`, … y el más antiguo de la ventana pesa `1`.

Ejemplo con `w=8`, de más antiguo a más reciente: pesos
`1, 2, 3, 4, 5, 6, 7, 8` (suma **36**).

Una ventana de 8 y no de 5 porque el usuario responde **preguntas sueltas**, no
exámenes completos: con ventana corta una sola respuesta movía demasiado el
nivel. Con 8, subir exige evidencia sostenida.

**Paso 4 — Puntuación cruda.**

```
raw = (suma de los pesos de los intentos CORRECTOS de la ventana)
      / (suma de todos los pesos de la ventana)
```

`raw` está en `[0.0, 1.0]`. Ponderar por recencia es lo que hace que la
tendencia se refleje: fallar lo último pesa más que haber fallado al principio.

**Paso 5 — Decaimiento por inactividad.**
Sea `gap = (as_of - last_attempt_at)` en días (fraccionarios, no redondeados).

```
retention = max(RETENTION_FLOOR, 0.5 ** (gap / DECAY_HALF_LIFE_DAYS))
score     = raw * retention
```

Si `gap <= 0`, `retention = 1.0`.

El conocimiento se oxida, pero no se evapora. Dos matices decisivos:

**El suelo se aplica SOLO a `retention`, nunca al `raw`.** Esta es la razón de
ser del suelo: el tiempo puede bajarte de dominado a débil, **pero no a cero**.

| Situación | `raw` | `retention` | `score` | Lectura |
| --- | --- | --- | --- | --- |
| Dominado y abandonado un año | 1.00 | 0.40 (suelo) | **0.400** | "lo abandoné" |
| Se falla siempre, recién visto | 0.10 | 1.00 | **0.100** | "no lo sé" |
| Se falla siempre y abandonado | 0.10 | 0.40 (suelo) | **0.040** | ambas cosas |

Sin el suelo, ambos casos convergían a ~0 y el score no podía distinguir *lo
dejé aparcado* de *nunca lo entendí*, que exigen acciones distintas: repasar
frente a estudiar de cero.

**Tabla de retención** (verificada, `HL=90`, suelo `0.40`):

| `gap` | 0 d | 7 d | 15 d | 30 d | 60 d | 90 d | 180 d | 365 d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `retention` | 1.000 | 0.948 | 0.891 | 0.794 | 0.630 | 0.500 | 0.400 | 0.400 |

A partir de ~119 días el suelo domina y la retención ya no baja más.

**Paso 6 — Umbrales.** El `score` se traduce a nivel:

| Condición sobre `score` | Nivel |
| --- | --- |
| `score >= 0.85` | `COMPETENT` (candidato a `MASTERED`, ver paso 7) |
| `0.60 <= score < 0.85` | `LEARNING` |
| `score < 0.60` | `WEAK` |

Los umbrales son **cerrados por abajo**: exactamente `0.85` es `COMPETENT`,
exactamente `0.60` es `LEARNING`.

**Paso 7 — Ascenso a `MASTERED`.**
Un candidato `COMPETENT` sube a `MASTERED` **solo si además** cumple las tres
condiciones de sostenimiento en el tiempo:

1. `distinct_days >= MASTERY_MIN_DAYS` (2), donde un día natural es la fecha
   **en UTC** del instante `at`, independientemente de la zona con que se
   registró, y
2. `(last_attempt_at - first_attempt_at) >= MASTERY_MIN_SPAN_DAYS` (7 días), y
3. `raw >= MASTERY_MIN_RAW` (0.95) — ver §2.4 sobre por qué 0.95 y no 1.0.

Si no las cumple, se queda en `COMPETENT`. No se puede dominar algo en una
tarde: es la traducción numérica de "evidencia en ≥2 sesiones separadas".

### 2.4 Por qué `MASTERED` exige `raw >= 0.95` y no `raw == 1.0`

Al pasar la ventana de 5 a 8 se revisó si los umbrales seguían teniendo
sentido. **Los umbrales de nivel (0.85 / 0.60) se mantienen**: siguen siendo
alcanzables y bien espaciados con ventana 8 — 5 aciertos finales de 8 dan
`raw = 0.833`, 6 dan `0.917`. No hay razón para moverlos.

**El criterio de `MASTERED` sí se ajustó**, de `raw == 1.0` a `raw >= 0.95`.
Con ventana 5, exigir perfección significaba 5 aciertos seguidos. Con ventana
8 significa **8 aciertos consecutivos sin un solo fallo**, y además cualquier
fallo tarda **8 intentos más** en salir de la ventana. El efecto medido:

| Ventana | `raw` | ¿`raw == 1.0`? | ¿`raw >= 0.95`? |
| --- | --- | --- | --- |
| 8 aciertos | 1.000 | sí | sí |
| 7 aciertos + 1 fallo en la posición **más antigua** (peso 1) | 0.972 | no | **sí** |
| 7 aciertos + 1 fallo en la penúltima posición más antigua (peso 2) | 0.944 | no | no |

Con `raw == 1.0`, un único fallo antiguo y ya casi purgado bloqueaba el ascenso
durante ocho intentos más, lo que hacía `MASTERED` prácticamente inalcanzable
para quien responde preguntas sueltas. `0.95` deja pasar exactamente ese caso —
un fallo residual en la posición de menor peso — y sigue rechazando cualquier
fallo más reciente. Las otras dos condiciones (≥2 días distintos, span ≥7 días)
no se tocan: son las que impiden dominar algo en una tarde.

Nótese además que `MASTERED` exige `score >= 0.85`, y con `raw = 1.0` el score
cae por debajo de 0.85 a los **22 días** de inactividad (el cruce exacto está
en `gap = 21.1019` días: a día 21 el score es 0.8507 y el objetivo **sigue
siendo** `MASTERED`; a día 22 es 0.8441 y cae directamente a `LEARNING`, porque
por debajo de 0.85 no hay ningún tramo intermedio — `COMPETENT` solo existe
como escalón cuando el `raw` no llega a 0.95). `MASTERED` sigue siendo, por
diseño, un estado que hay que sostener.

Conviene subrayar por qué el decaimiento **puede** hacer perder `MASTERED`
aunque las tres condiciones de sostenimiento del paso 7 sean inmunes al paso
del tiempo: `retention` no toca ni el `raw`, ni `distinct_days`, ni el span, así
que esas tres siguen cumpliéndose para siempre. Lo único que cae es el `score`,
y con él la condición previa de ser candidato (`score >= 0.85`) del paso 6. Un
objetivo abandonado deja de ser `MASTERED` por dejar de ser `COMPETENT`, no por
dejar de estar sostenido.

### 2.3 Resumen ejecutable en una línea

> Nivel = umbral(recencia_ponderada(últimos 8) × decaimiento con suelo 0.40),
> con `MASTERED` reservado a lo casi perfecto y sostenido ≥7 días.

---

## 3. Evolución: el recorrido de "mal, mal, mal, bien, mal"

Escenario canónico. Objetivo `X`, cinco intentos en **días consecutivos** para
que el decaimiento sea casi neutro. `as_of` = el instante del último intento en
cada fila, así que `gap = 0` y `retention = 1.0` (salvo la última fila).

| # | Fecha | Resultado | Ventana (viejo→nuevo) | Aciertos/Total | `raw` | `score` | **Nivel** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-01-01 | mal | `[F]` | — | — | 0.000 | `UNASSESSED` (n=1 < 2) |
| 2 | 2026-01-02 | mal | `[F,F]` | 0 / 3 | 0.000 | 0.000 | `WEAK` |
| 3 | 2026-01-03 | mal | `[F,F,F]` | 0 / 6 | 0.000 | 0.000 | `WEAK` |
| 4 | 2026-01-04 | **bien** | `[F,F,F,C]` | 4 / 10 | 0.400 | 0.400 | `WEAK` |
| 5 | 2026-01-05 | mal | `[F,F,F,C,F]` | 4 / 15 | 0.267 | 0.267 | `WEAK` |

Obsérvese que con solo 5 intentos la ventana (que admite 8) aún no está llena:
los pesos son `1..n`, no `1..8`.

Comprobación de la fila 4: el único acierto es el más reciente de una ventana de
4, luego pesa `4`. Suma de pesos `1+2+3+4 = 10`. `raw = 4/10 = 0.400`.

Comprobación de la fila 5: la ventana es de 5, el acierto quedó en penúltima
posición y pesa `4`. Suma de pesos `1+2+3+4+5 = 15`. `raw = 4/15 = 0.2667`.

**Lo que importa de este ejemplo:** el nivel se mantiene `WEAK` de principio a
fin — que es la verdad — pero el `score` **sí se mueve** (0.000 → 0.400 →
0.267) y el `total_attempts` llega a 5. Con una racha, la fila 5 habría dicho
`streak = 0` y la fila 4 `streak = 1`, indistinguibles de "no se guardó nada".
Aquí se distingue perfectamente: hay 5 intentos registrados, hubo una mejora y
luego una recaída, y todo eso es consultable.

### 3.1 Continuación: la recuperación

Sigamos el mismo objetivo para ver el ascenso.

Se siguen sumando aciertos sueltos, uno por día. La ventana se llena en la
fila 8 (8 intentos) y a partir de ahí desplaza por la cola.

| # | Fecha | Resultado | Ventana (viejo→nuevo) | Aciertos/Total | `raw` | `score` | **Nivel** | Nota |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6 | 2026-01-06 | bien | `[F,F,F,C,F,C]` | 10 / 21 | 0.476 | 0.476 | `WEAK` | aún por debajo de 0.60 |
| 7 | 2026-01-07 | bien | `[F,F,F,C,F,C,C]` | 17 / 28 | 0.607 | 0.607 | `LEARNING` | cruza 0.60 |
| 8 | 2026-01-08 | bien | `[F,F,F,C,F,C,C,C]` | 25 / 36 | 0.694 | 0.694 | `LEARNING` | ventana llena (8) |
| 9 | 2026-01-09 | bien | `[F,F,C,F,C,C,C,C]` | 29 / 36 | 0.806 | 0.806 | `LEARNING` | sale el `F` más antiguo |
| 10 | 2026-01-10 | bien | `[F,C,F,C,C,C,C,C]` | 32 / 36 | 0.889 | 0.889 | `COMPETENT` | cruza 0.85 |
| 11 | 2026-01-11 | bien | `[C,F,C,C,C,C,C,C]` | 34 / 36 | 0.944 | 0.944 | `COMPETENT` | `raw < 0.95`, aún no `MASTERED` |
| 12 | 2026-01-12 | bien | `[F,C,C,C,C,C,C,C]` | 35 / 36 | 0.972 | 0.972 | **`MASTERED`** | `raw ≥ 0.95` ✔ · span 01-01→01-12 = 11 d ≥ 7 ✔ · 12 días distintos ≥ 2 ✔ |
| 13 | 2026-01-13 | bien | `[C,C,C,C,C,C,C,C]` | 36 / 36 | 1.000 | 1.000 | **`MASTERED`** | ventana perfecta |

Comprobación de la fila 12: el único fallo está en la posición más antigua, con
peso `1`; los aciertos suman `2+3+4+5+6+7+8 = 35` sobre `36`. `raw = 0.9722`.
Es exactamente el caso que motiva el umbral `0.95` de §2.4: con `raw == 1.0`
habría hecho falta un día más.

**Nótese cuánto más exigente es la subida con ventana 8.** Hicieron falta 7
aciertos consecutivos para pasar de `WEAK` a `COMPETENT`, y 9 para `MASTERED`.
Con ventana 5 bastaban 3 y 5. Eso es justo lo que se buscaba: que el nivel no
se mueva con una sola respuesta.

Y el efecto del olvido, sin ningún intento nuevo:

Partiendo de la fila 13 (`raw = 1.000`, último intento 2026-01-13):

| Consulta `as_of` | `gap` | `retention` | `score` | **Nivel** |
| --- | --- | --- | --- | --- |
| 2026-01-13 | 0 d | 1.000 | 1.000 | `MASTERED` |
| 2026-01-20 | 7 d | 0.948 | 0.948 | `MASTERED` |
| 2026-02-03 | 21 d | 0.851 | 0.851 | `MASTERED` |
| 2026-02-04 | 22 d | 0.844 | 0.844 | `LEARNING` |
| 2026-02-12 | 30 d | 0.794 | 0.794 | `LEARNING` |
| 2026-03-14 | 60 d | 0.630 | 0.630 | `LEARNING` |
| 2026-04-13 | 90 d | 0.500 | 0.500 | `WEAK` |
| 2026-07-12 | 180 d | 0.400 | 0.400 | `WEAK` (suelo) |
| 2027-01-13 | 365 d | 0.400 | 0.400 | `WEAK` (suelo) |

Nótese que `MASTERED` **se pierde** por inactividad sin registrar ningún
intento nuevo: el nivel es función de la fecha de consulta, no un sello
permanente. Pero el descenso **se detiene en 0.400**: un año después el motor
sigue distinguiendo este tema (dominado y abandonado) de uno que nunca se supo.
El olvido lo degrada a `WEAK`, no lo borra.

### 3.2 Regla general de la evolución

- Un **acierto** entra en la ventana con el peso máximo y empuja el `score`
  hacia arriba; expulsa por la cola el intento más antiguo de la ventana.
- Un **fallo** hace lo mismo hacia abajo. Un fallo no borra el historial ni
  reinicia nada: reduce el `score` en proporción a su peso.
- El paso del tiempo sin intentos **solo baja** el `score`, nunca lo sube, y
  nunca por debajo de `raw × 0.40`.
- **Nada es irreversible.** Ocho aciertos consecutivos recuperan siempre
  `raw = 1.0` sea cual sea el pasado, porque la ventana solo mira 8.
- **Registrar un intento pone el `gap` a 0** y por tanto `retention = 1.0`.
  Responder una sola pregunta, aunque sea fallándola, detiene el decaimiento en
  seco: el objetivo vuelve a valorarse por lo que se sabe, no por lo que hace
  que no se toca.

### 3.3 El caso "pregunta suelta"

**El motor no requiere exámenes.** Una única respuesta a una única pregunta es
un `Attempt` completo, válido y suficiente. No hay concepto de "sesión mínima",
ni de quiz que haya que completar, ni intentos que deban agruparse: `kind` es
informativo y no cambia ningún cálculo.

Esto es deliberado, porque así estudia el usuario: preguntas parceladas a lo
largo de semanas, no simulacros completos. Dos consecuencias que conviene tener
presentes:

1. **Una respuesta suelta mueve poco el nivel** — es el motivo de la ventana de
   8. Hacen falta varias respuestas consistentes para cambiar de nivel, que es
   la definición operativa de "evidencia sostenida".
2. **Una respuesta suelta frena el decaimiento por completo.** Como `retention`
   depende solo de `last_attempt_at`, un intento aislado resetea el `gap` a 0.
   Un tema tocado ayer se valora al 100% de su `raw`, aunque el intento anterior
   fuese de hace tres meses.

De los dos efectos se sigue la lectura correcta: **contestar una pregunta suelta
mantiene vivo un tema, pero no lo promociona.** Subir de nivel exige volumen;
no bajar solo exige constancia.

---

## 4. Próximo repaso

Repetición espaciada con intervalos fijos. Se calcula, como todo, desde el
historial: **no hay un `ease` ni un `interval` almacenado que se pueda
corromper** (§8, fallo 3).

### 4.1 La escalera

`SCHEDULE_DAYS = [1, 3, 7, 14, 30]`

(El `30` de aquí son días de la escalera de repaso y no tiene relación con
`DECAY_HALF_LIFE_DAYS = 90`, que gobierna el olvido. Son dos mecanismos
distintos.)

### 4.2 Regla

1. Sea `S` la **racha de aciertos consecutivos al final** de la lista ordenada
   de intentos (contando desde el más reciente hacia atrás hasta el primer
   fallo). *Esto se usa exclusivamente para elegir el intervalo de repaso, y
   nunca como medida de progreso.*
2. Si `S == 0` (el último intento fue un fallo) ⇒ `índice = 0` ⇒ **1 día**.
3. Si `S >= 1` ⇒ `índice = min(S - 1, len(SCHEDULE_DAYS) - 1)`.
   - `S=1` → 1 día · `S=2` → 3 días · `S=3` → 7 días · `S=4` → 14 días ·
     `S>=5` → 30 días.
4. `next_review_at = last_attempt_at + índice_de_días`.
5. Si el objetivo alcanza `MASTERED`, el intervalo se multiplica por `2`
   (techo: 60 días).
6. Si no hay intentos: `next_review_at = None` y `is_due = False`.
   Un objetivo sin evidencia no está "vencido", está **sin empezar**; se listan
   por separado (§5.2).

### 4.3 Vencimiento

`is_due(as_of) == (next_review_at is not None and next_review_at <= as_of)`.

Aplicado al ejemplo de §3: tras la fila 5 (fallo del 2026-01-05), `S=0`, luego
`next_review_at = 2026-01-06`. Tras la fila 13 (2026-01-13), `S=8` y nivel
`MASTERED`, luego `30 × 2 = 60` días → `2026-03-14`.

---

## 5. Consultas

### 5.1 Estado en una fecha — la garantía temporal

`get_state(objective_id, as_of)` devuelve el `ObjectiveState` calculado
**ignorando por completo todo intento con `at > as_of`**.

Garantías:

- **Reproducibilidad histórica.** Consultar con `as_of = 2026-01-04` da hoy
  exactamente lo mismo que dará dentro de un año, aunque entretanto se hayan
  registrado cien intentos nuevos. Lo pasado no cambia.
- **Insensibilidad al orden de escritura.** Registrar los intentos en cualquier
  orden produce los mismos estados históricos, porque el corte es por `at`,
  nunca por orden de inserción ni por `recorded_at`.
- **Responde la pregunta del usuario.** "¿Estaba mejor hace dos semanas?" se
  responde comparando `get_state(o, hoy).score` con
  `get_state(o, hoy - 14d).score`, o directamente con `compare_states`.

Esto es posible **solo** porque el historial es append-only y el nivel se
recalcula. Es la razón estructural de la decisión 1 de §0.

### 5.2 Qué toca repasar

`get_due(profile_id, as_of, ...)` devuelve los objetivos con `is_due == True`
en esa fecha, ordenados por urgencia: primero los más vencidos
(`as_of - next_review_at` mayor); a igualdad, el `score` más bajo primero; a
igualdad, `objective_id` ascendente (determinismo total).

Los objetivos **sin intentos** no aparecen aquí. Se obtienen con
`get_unstarted`, porque "nunca lo he visto" y "toca repasarlo" son cosas
distintas y mezclarlas oculta el material sin cubrir.

### 5.3 Series temporales

`get_timeline(objective_id, start, end, step)` devuelve una lista de
`ObjectiveState`, uno por cada fecha de la rejilla. Es `get_state` aplicado en
bucle; existe para graficar la evolución sin que la UI reimplemente el corte.

---

## 6. Invariantes del motor

Cualquier implementación debe cumplirlas. Son verificables desde fuera.

| # | Invariante |
| --- | --- |
| **I1** | **Append-only.** Ninguna operación de la API pública modifica o elimina un `Attempt` ya registrado. No existe `update_attempt` ni `delete_attempt`. |
| **I2** | **Ausencia de reloj interno.** Ninguna función de `core/` llama a `datetime.now()`, `date.today()`, `time.time()` ni equivalentes. El tiempo llega como parámetro o vía `Clock`. Es verificable con un grep sobre `core/`. |
| **I3** | **Determinismo.** `get_state(o, t)` con el mismo conjunto de intentos devuelve siempre lo mismo, en cualquier proceso, plataforma u orden de inserción. |
| **I4** | **Derivación total.** Todo campo de `ObjectiveState` es función pura de (intentos, `as_of`). Nada se lee de un agregado persistido. |
| **I5** | **Monotonía del corte.** Si `t1 <= t2`, entonces el conjunto de intentos considerados en `t1` es un subconjunto del de `t2`. (El nivel **no** es monótono; el conjunto sí.) |
| **I6** | **Reconstrucción.** Borrar cualquier caché o índice y recalcular desde los intentos produce un estado idéntico. Corolario: un agregado corrupto siempre se arregla recalculando. |
| **I7** | **Aislamiento entre perfiles.** Los intentos de un perfil no afectan a ningún estado de otro perfil. |
| **I8** | **Registro verificable.** Registrar un intento devuelve el `Attempt` persistido con su `attempt_id`; si la escritura falla, se lanza una excepción. **Nunca falla en silencio.** |
| **I9** | **Consistencia por conteo.** El chequeo de consistencia compara **conteos y sumas**, no pertenencia a conjuntos (§8, fallo 2). |
| **I10** | **Sin campo de racha en el estado.** `ObjectiveState` no expone `streak`. La racha existe solo como variable local del cálculo de repaso (§4.2). |

---

## 7. Casos límite

Respuesta esperada, sin ambigüedad. Quien testee puede escribir estos casos
directamente.

### C1 — Objetivo sin intentos
`level = UNASSESSED`, `score = 0.0`, `total_attempts = 0`,
`recent_window = ()`, `first_attempt_at = last_attempt_at = None`,
`next_review_at = None`, `is_due = False`.
No aparece en `get_due`. Sí aparece en `get_unstarted`.
**No es un error**: no se lanza excepción por consultar un objetivo sin
intentos. Sí se lanza (`UnknownObjectiveError`) si el objetivo no existe en el
perfil.

### C2 — Un solo intento
`level = UNASSESSED` (`n < MIN_ATTEMPTS`) y `score = 0.0`, **sea acierto o
fallo**. Pero `total_attempts = 1`, `recent_window = (True,)` o `(False,)`, y
`next_review_at` **sí se calcula** (§4). Es decir: el intento está registrado y
es visible, simplemente no basta para asignar nivel.

### C3 — Dos intentos el mismo día
Cuentan como **dos intentos independientes**. No se colapsan, no se promedian.
Ambos entran en la ventana con pesos distintos según su orden temporal.
Es el caso normal cuando se responden varias preguntas sueltas seguidas.
Para `distinct_days` cuentan como **un solo día** (se comparan fechas
naturales, no instantes) — lo cual afecta al ascenso a `MASTERED`. "Mismo
día" es **misma fecha en UTC** del instante `at`, no la fecha en la zona con
que se registró cada intento: dos intentos a `23:00-05:00` y `04:30+00:00`
del mismo día UTC son un solo día.
Si tienen el **mismo `at` exacto**, se ordenan por `attempt_id` ascendente.

### C4 — Intentos insertados fuera de orden cronológico
Registrar el intento del día 3 **después** del intento del día 5 es legal y no
lanza error. El motor ordena siempre por `at`, no por orden de llegada.
Consecuencia obligatoria: tras la inserción tardía, `get_state(o, día_4)` pasa
a incluir ese intento y **puede devolver un nivel distinto al que devolvía
antes**. Esto es correcto: se ha añadido información sobre el pasado, no se ha
alterado el pasado. `recorded_at` deja constancia de la inserción tardía.

### C5 — Hueco largo sin actividad
El decaimiento **tiene suelo**: `retention` nunca baja de `RETENTION_FLOOR`
(0.40), y por tanto `score` nunca baja de `raw × 0.40`. Un objetivo con
`raw = 1.0` y 90 días de hueco tiene `retention = 0.500` ⇒ `score = 0.500` ⇒
`WEAK`; con 365 días tiene `retention = 0.400` ⇒ `score = 0.400`, y ahí se
queda por mucho que pase el tiempo.

El suelo es lo que impide que "abandonado" y "nunca aprendido" colapsen al
mismo número (§2.2 paso 5).
`next_review_at` queda muy en el pasado, así que `is_due = True` y aparece el
primero en `get_due` por ser el más vencido. **El motor nunca "olvida" al
objetivo ni lo archiva por sí solo.**

### C6 — Consulta con `as_of` anterior al primer intento
Equivale a C1: el objetivo aún no tenía evidencia en esa fecha.
`level = UNASSESSED`. No es un error.

### C7 — Consulta con `as_of` en el futuro
Legal. Todos los intentos entran y el decaimiento se calcula con ese `gap`
futuro. Sirve para responder "¿cómo estaré de oxidado el día del examen?".

### C8 — Intento sobre un `objective_id` inexistente
`record_attempt` lanza `UnknownObjectiveError`. **No se autocrea el objetivo**:
un id mal escrito debe fallar ruidosamente, no fabricar un objetivo fantasma.

### C9 — `attempt_id` duplicado
`record_attempt` lanza `DuplicateAttemptError`. Garantiza idempotencia
detectable y protege I1: reintentar una escritura no duplica evidencia.

### C10 — Empate exacto en el umbral
`score == 0.85` ⇒ `COMPETENT`. `score == 0.60` ⇒ `LEARNING`.
La comparación es `>=`. Para evitar sorpresas de coma flotante, el `score` se
**redondea a 6 decimales** antes de aplicar los umbrales.

---

## 8. Cómo este diseño evita los fallos conocidos

Los cinco fallos diagnosticados en los sistemas anteriores, y la propiedad
estructural que los hace imposibles aquí.

### Fallo 1 — Confundir racha con progreso

> *Un objetivo con 5 respuestas mostraba `streak=1` y parecía que no se guardaba
> nada.*

**Qué lo impide:** `ObjectiveState` **no tiene campo `streak`** (I10). El
progreso se expresa con tres cosas que una racha no puede dar: `score` continuo
ponderado por recencia, `total_attempts` / `correct_attempts` que solo crecen, y
`recent_window` que muestra literalmente la secuencia. En el ejemplo de §3 la
fila 5 muestra `total_attempts=5`, `recent_window=(F,F,F,C,F)` y `score=0.267`:
es imposible confundirlo con "no se guardó nada".

La racha sobrevive únicamente como variable local del cálculo de intervalo de
repaso (§4.2), donde sí es la semántica correcta, y la spec dice explícitamente
que no se use como medida de progreso.

### Fallo 2 — Verificador que compara conjuntos en vez de conteos

> *Imprimía "OK · consistente" sobre un estado corrupto.*

**Qué lo impide:** `check_consistency` (§9.5) tiene contrato explícito de
comparar **conteos y sumas**, no pertenencia (I9), y devuelve un
`ConsistencyReport` con los números de ambos lados, no un booleano ni una
cadena. Un reporte que dice `store=7, recalculado=5` no puede imprimir "OK".
Además `ConsistencyReport.ok` se define como *todos los conteos coinciden*, no
como *no encontré discrepancias*. La ausencia de evidencia de error no es
`ok = True`.

### Fallo 3 — Contadores acumulativos corrompidos e irreversibles

> *`lapses` y `ease` se corrompieron y no se podían revertir.*

**Qué lo impide:** **no existen contadores acumulativos.** No hay `ease`, no hay
`lapses`, no hay `interval` almacenado. El intervalo de repaso se deriva de la
racha final, y la racha se deriva del historial (§4). Por I6, cualquier
corrupción de un agregado o caché se arregla borrándolo y recalculando; el único
dato irrecuperable sería un intento perdido, y los intentos son append-only e
inmutables (I1).

### Fallo 4 — Nada forzaba el registro; fallaba en silencio

> *Dependía de que un LLM se acordara de ejecutar un comando.*

**Qué lo impide, en tres capas:**

1. **I8:** `record_attempt` devuelve el `Attempt` persistido o lanza excepción.
   No hay camino "no hice nada y devolví None".
2. **Detección de silencio:** `get_stale` (§9.4) lista los objetivos sin
   intentos desde hace más de `n` días, y `get_unstarted` los que nunca tuvieron
   ninguno. Un estado congelado deja de ser invisible: aparece en una lista.
3. **`SessionRecorder` (§9.6):** contexto de sesión que exige cerrar
   declarando cuántos intentos se registraron. Si se cierra con cero, marca la
   sesión como `EMPTY` en vez de terminar en silencio. La disciplina de registro
   deja de depender de la memoria de quien opera.

La spec no puede obligar a nadie a ejecutar un comando, pero sí puede hacer que
**no ejecutarlo sea visible**. Eso es lo que hacen estas tres capas.

### Fallo 5 — Fechas no inyectables

> *Imposible probar la evolución temporal.*

**Qué lo impide:** I2. `core/` no tiene acceso al reloj: todas las funciones
reciben `as_of` explícito o un `Clock` inyectado. `FixedClock` permite fijar la
fecha en un test y `OffsetClock` avanzarla. Un bot puede simular seis meses de
estudio en milisegundos, que es exactamente lo que pide el requisito de la serie
deliberada "mal, mal, mal, bien, mal".

---

## 9. Superficie de la API

Los nombres exactos, tipos y docstrings viven en `core/`. Este es el mapa.

### 9.1 Abstracciones inyectables (`core/clock.py`, `core/storage.py`)

| Nombre | Qué es |
| --- | --- |
| `Clock` (Protocol) | `now() -> datetime`. Única puerta al tiempo real. |
| `FixedClock` | Devuelve siempre la misma fecha. Para tests. |
| `OffsetClock` | Un `Clock` base más un desplazamiento. Para simular avance. |
| `SystemClock` | El reloj real. **Vive en `store/`, no en `core/`**, para que I2 sea verificable con un grep sobre `core/`. |
| `AttemptStore` (Protocol) | Persistencia de intentos: `append(profile_id, attempt)`, `list_for_objective`, `list_all`, `count`, `exists`. Solo añade y lee. `profile_id` va en la llamada y no en `Attempt` (§1.3 no lo incluye): el store indexa por perfil, igual que en `list_for_objective`, `list_all` y `count`; `attempt_id` es único global (C9). |
| `ProfileStore` (Protocol) | Persistencia de perfiles y objetivos. |

### 9.2 Modelo (`core/models.py`)

`Profile`, `Objective`, `Attempt`, `AttemptKind`, `Level`, `ObjectiveState`,
`ProfileSummary`, `StateComparison`, `ConsistencyReport`, `SessionReport`.
Todos son *dataclasses* congeladas (`frozen=True`): inmutables por construcción.

### 9.3 Cálculo puro (`core/leveling.py`, `core/scheduling.py`)

| Función | Qué hace |
| --- | --- |
| `compute_score(attempts, as_of)` | Pasos 1–5 de §2.2, con suelo de retención. |
| `compute_level(score, attempts, as_of)` | Pasos 6–7 de §2.2. |
| `compute_state(objective_id, attempts, as_of)` | El `ObjectiveState` completo. |
| `compute_next_review(attempts, level)` | §4. |
| `trailing_success_run(attempts)` | La racha final. Uso interno de scheduling. |

Son funciones puras sobre listas de `Attempt`. No tocan el store ni el reloj.

### 9.4 Motor (`core/tracker.py` — clase `LearningTracker`)

| Método | Qué hace |
| --- | --- |
| `record_attempt(...)` | Registra un intento con fecha inyectada. Devuelve el `Attempt`. |
| `record_series(objective_id, results, start, step, kind)` | Registra una serie de resultados en fechas espaciadas. Atajo para el bot de verificación y los tests; reproduce §3. Devuelve la lista de `Attempt`. |
| `get_level(objective_id, as_of=None)` | El `Level` de un objetivo en una fecha. |
| `get_state(objective_id, as_of=None)` | El `ObjectiveState` completo. |
| `get_state_at(objective_id, as_of)` | Igual, con `as_of` obligatorio. Consulta histórica explícita. |
| `get_all_states(as_of=None)` | El estado de todos los objetivos del perfil, por `objective_id`. |
| `get_due(as_of=None, limit=None)` | Qué toca repasar (§5.2). |
| `get_unstarted(as_of=None)` | Objetivos sin ningún intento. |
| `get_stale(as_of=None, days=14)` | Objetivos sin actividad reciente (fallo 4). |
| `get_timeline(objective_id, start, end, step)` | Serie temporal de estados. |
| `compare_states(objective_id, earlier, later)` | "¿Estaba mejor hace dos semanas?" |
| `get_summary(as_of=None)` | Agregado del perfil: reparto por nivel, cobertura. |
| `get_profile()` | El `Profile` sobre el que opera este tracker. |
| `check_consistency(as_of=None)` | §8 fallo 2. Devuelve `ConsistencyReport`. |
| `rebuild(as_of=None)` | I6. No hay caché que borrar: recalcula el estado de todos los objetivos y devuelve cuántos recalculó. |
| `session(...)` | Abre un `SessionRecorder`. |
| `profile_id` (propiedad) | Perfil sobre el que opera este tracker. |
| `clock` (propiedad) | El reloj inyectado, solo lectura, expuesto para colaboradores como `SessionRecorder`. Sigue siendo I2: el `Clock` lo eligió quien construyó el tracker. |

`as_of=None` significa "usa `clock.now()`". Es la única concesión, y sigue
siendo tiempo inyectado: el `Clock` lo elige quien construye el tracker.

### 9.5 `ConsistencyReport`

Campos: `ok`, `checks` (lista de `ConsistencyCheck` con `name`, `expected`,
`actual`, `passed`), `objectives_checked`. `ok` es `True` solo si **todos** los
checks pasaron y se comprobó al menos un objetivo.

### 9.6 `SessionRecorder` (`core/session.py`)

Context manager. Acumula intentos y al cerrar produce un `SessionReport` con
`attempts_recorded`, `objectives_touched` y `status` (`RECORDED` o `EMPTY`).
Cerrar una sesión sin intentos es un resultado explícito y visible, no un
no-evento.

---

## 10. Lo que deliberadamente NO está en v1

Para que quien implemente no invente de más:

- `confidence` y `weight` se guardan pero **no afectan** a ningún cálculo.
- No hay dependencias entre objetivos (prerrequisitos).
- No hay dificultad por ítem ni modelo tipo SM-2 con `ease` variable — eso es
  exactamente el fallo 3.
- No hay borrado ni edición de intentos.
- Multi-perfil: el modelo lo soporta (perfiles aislados, I7) pero un
  `LearningTracker` opera sobre **un** perfil.
