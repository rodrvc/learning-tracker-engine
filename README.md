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

## Estructura

| Ruta | Qué es |
| --- | --- |
| `SPEC.md` | El contrato: niveles, evolución, garantías |
| `INTEGRATION.md` | Cómo conectarlo a una fuente de estudio (apuntes, quiz, agente tutor) |
| `core/` | Motor puro, sin I/O |
| `store/` | Persistencia |
| `tests/` | Suite de verificación |
| `ui/` | Visualización del progreso |
