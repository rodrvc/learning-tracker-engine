# Entorno de demostración

Un entorno con datos sintéticos para mostrar Learning Tracker a colegios y
organismos públicos. Cuenta una historia en cinco minutos: una persona practica
y le aparece un repaso, la coordinación ve quién necesita ayuda y el resumen
diario llega a quien le toca repasar.

Todo es inventado: personas, apuntes y preguntas. El contenido de Azure sigue
los dominios públicos de los exámenes AI-900 (Azure AI Fundamentals) y AZ-900
(Azure Fundamentals) de Microsoft; los apuntes y las preguntas están escritos a
mano para la demo, sin material privado y sin llamar a ningún modelo.

## Partir en un comando

Una sola vez (Python 3.10+ y Docker):

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[web]"
cp .env.example .env
```

Cada vez que quieras mostrarlo:

```sh
LEARNING_TRACKER_DEMO_MODE=true scripts/dev-up.sh
```

Levanta Postgres, aplica las migraciones, carga los datos de demo y arranca la
aplicación en <http://127.0.0.1:8000>. Verás la franja "Entorno de
demostración" arriba y, en la cabecera, el selector de personas agrupado por
organización. El modo demo solo funciona con la autenticación apagada (lo que
`scripts/dev-up.sh` hace solo cuando no hay `LEARNING_TRACKER_CLERK_ISSUER`); con
autenticación activa la aplicación se niega a partir.

Si el puerto 5432 está ocupado, cambia `POSTGRES_PORT` en `.env` y el puerto de
`LEARNING_TRACKER_DATABASE_URL` para que coincidan.

## Reiniciar el estado

Las fechas son relativas a cuando se cargan los datos, así que conviene
reiniciar justo antes de cada demo (los repasos pendientes quedan "para hoy"):

```sh
scripts/demo-reset.sh        # equivale a: .venv/bin/python -m scripts.seed_demo --reset
```

Borra solo los datos de las organizaciones de demo (los ids de usuario
`demo_*` y las dos organizaciones; nada más) y los vuelve a cargar. Lo que
hayas practicado durante la demo desaparece. Sin `--reset`, el comando es
idempotente: no duplica nada, pero tampoco mueve las fechas ya cargadas.

## Quiénes son

**Colegio Demo** (docente `Docente Demo`, cuatro estudiantes de Historia y
Biología): Ana Rojas (constante), Bruno Soto (irregular), Carla Munoz (recién
empieza) y Diego Pino (dejó de practicar hace semanas).

**Servicio Público Demo** (coordinación `Marcela Fuentes`, siete funcionarios/as
que se preparan en Azure, con unas seis semanas de historia):

| Persona | Historia |
| --- | --- |
| Camila Araya | Fuerte y constante, domina casi todo |
| Felipe Gutiérrez | Constante, con algunos tropiezos y repasos al día |
| Javiera Muñoz | Constante, solo AI-900, aún le faltan objetivos |
| Sebastián Vega | Con dificultades: falla seguido, todo por repasar |
| Daniela Poblete | Con dificultades, solo AI-900 |
| Ignacio Tapia | Detenido: dejó de practicar hace unas dos semanas |
| Constanza Bravo | Nunca empezó |

La práctica con apuntes y preguntas está cargada para estas siete personas
(metas AI-900 y AZ-900). Para el recorrido usa el Servicio Público Demo.

## Guion de cinco minutos

Abre <http://127.0.0.1:8000>. El selector de la cabecera cambia quién es la
página; la elección queda guardada en el navegador.

1. **La persona que practica y ve un repaso (2 min).**
   - En el selector elige `Sebastián Vega (funcionario/a)`, bajo "Servicio Público Demo".
   - En **Aprendiendo** abre la meta "Azure AI Fundamentals (AI-900)": las
     unidades son los dominios del examen, con sus objetivos y su nivel.
   - Entra directo a la práctica en <http://127.0.0.1:8000/#/learning/azure-ai-900>
     y practica: la aplicación sirve primero lo que toca repasar, lo más atrasado
     antes. Responde dos o tres preguntas (acierta una a propósito) y lee la
     explicación de cada una.
   - Abre **Progreso**: el nivel y los repasos pendientes se mueven con cada respuesta.
     Un objetivo contestado bien sale de "por repasar"; uno fallado vuelve pronto.

2. **La coordinación ve quién necesita ayuda (1,5 min).**
   - En el selector elige `Marcela Fuentes (coordinación)`.
   - Aparece la pestaña **Vista docente**: una fila por funcionario/a y meta, con el
     nivel típico, los repasos pendientes y los objetivos sin practicar.
   - Cuéntalo así: Sebastián y Daniela tienen niveles bajos y mucho por repasar
     (necesitan apoyo); Ignacio tenía buen ritmo y se detuvo hace dos semanas
     (hay que contactarlo); Constanza no ha empezado; Camila y Felipe van bien.
   - Cada persona solo ve lo suyo; la coordinación ve el resumen, no las respuestas.

3. **El resumen diario (1,5 min).** Sin abrir la aplicación, cada persona recibe
   qué le toca repasar. En otra terminal, en la raíz del repo:

   ```sh
   set -a; source .env; set +a
   LEARNING_TRACKER_DIGEST_RECIPIENTS='{"demo_sp_sebastian":"sebastian@example.com","demo_sp_ignacio":"ignacio@example.com","demo_sp_camila":"camila@example.com"}' \
     .venv/bin/python -m scripts.send_due_digest
   ```

   Por defecto imprime los mensajes en la pantalla (no envía correo real). Verás
   el mensaje de Sebastián e Ignacio con los repasos más atrasados y el enlace
   para practicar, y que a Camila no le llega nada porque no tiene nada pendiente.
   Las líneas "no email mapped" son las personas sin correo configurado: es lo
   esperado. Detalles en [`due-digest.md`](due-digest.md).

## Si algo no sale

- El selector no aparece: la aplicación debe partir con `LEARNING_TRACKER_DEMO_MODE=true`
  y sin `LEARNING_TRACKER_CLERK_ISSUER`.
- Faltan personas o preguntas: ejecuta `scripts/demo-reset.sh`.
- Para volver al usuario local sin identidad, elige "Usuario local (sin identidad)".
