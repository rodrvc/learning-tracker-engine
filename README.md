# learning-tracker

Motor de seguimiento de aprendizaje: registra intentos, calcula nivel de dominio
por objetivo y programa repasos. Independiente del dominio que se estudie.

**Estado:** en construcción. El contrato vive en `SPEC.md`.

## Principios

- **El historial es la única fuente de verdad.** Todo agregado (nivel, próximo
  repaso) es una proyección recalculable. Nada se guarda que no pueda derivarse.
- **El tiempo se inyecta, nunca se consulta.** El motor no llama a `now()`:
  recibe la fecha. Así se puede simular meses de estudio en un test.
- **Modular.** `core/` no sabe de almacenamiento, de CLI ni de UI.

## Instalacion y uso

```sh
pip install .                       # deja el ejecutable learning-tracker en el PATH
learning-tracker --help
```

Sin instalar, desde la raiz del repo, `python -m ui ...` hace lo mismo. El
detalle de cada subcomando esta en `ui/README.md`.

## Donde viven los datos

Los datos son del usuario, no del repo. Por defecto viven en la carpeta
estandar del sistema operativo, no en un `./data` relativo al directorio
actual: asi la CLI abre siempre el mismo store se ejecute desde donde se
ejecute, y quien clona el repo no acaba con sus datos dentro del proyecto.

| Sistema | Directorio por defecto |
| --- | --- |
| macOS | `~/Library/Application Support/learning-tracker` |
| Linux y el resto | `$XDG_DATA_HOME/learning-tracker`, o `~/.local/share/learning-tracker` si `XDG_DATA_HOME` no esta definida |

Precedencia: `--data DIR` gana a la variable de entorno
`LEARNING_TRACKER_DATA`, que gana al default del sistema operativo.
`learning-tracker --help` muestra el default efectivo de tu maquina. El
directorio se crea con permisos `0700`: solo su dueno entra.

Si tenias datos en un `./data` de una version anterior, la CLI avisa por stderr
con el comando exacto para moverlos y sigue funcionando con el destino nuevo.
No mueve ni copia nada por su cuenta.

## Copia de seguridad

Copiar el directorio de datos entero:

```sh
cp -R "$HOME/Library/Application Support/learning-tracker" ~/backup-learning-tracker
```

Restaurar es copiar de vuelta. Los archivos `.lock` de dentro son archivos
vacios de exclusion entre procesos: no hace falta copiarlos, y se recrean solos
en la siguiente escritura.

## Estructura

| Ruta | Qué es |
| --- | --- |
| `SPEC.md` | El contrato: niveles, evolución, garantías |
| `INTEGRATION.md` | Cómo conectarlo a una fuente de estudio (apuntes, quiz, agente tutor) |
| `core/` | Motor puro, sin I/O |
| `store/` | Persistencia |
| `tests/` | Suite de verificación |
| `ui/` | Visualización del progreso |
