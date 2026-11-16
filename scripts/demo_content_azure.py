"""Demo content: an Azure track for a public-service organization.

Plain data, no logic, so ``scripts/seed_demo.py`` stays short. The structure
follows the public "skills measured" outlines Microsoft publishes for two
fundamentals exams, AI-900 (Azure AI Fundamentals) and AZ-900 (Azure
Fundamentals): each exam is a goal, each exam domain is a unit (carried in
``Objective.domain``, the codebase's convention) and each unit holds a few
objectives.

Everything below is synthetic and written by hand: the notes are a short page
per unit and the questions are multiple choice. No private study material is
used and nothing here calls a model: the seed never needs an API key.
The text the user sees is Spanish (Chile, neutral); the code is English.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    stem: str
    #: Four option texts; the keys A to D are assigned in order.
    options: tuple[str, str, str, str]
    #: Index (0 to 3) of the correct option.
    correct: int
    explanation: str


@dataclass(frozen=True)
class Objective:
    objective_id: str
    title: str
    questions: tuple[Question, ...]


@dataclass(frozen=True)
class Unit:
    unit_id: str
    #: The unit as the exam domain is named; becomes ``Objective.domain``.
    name: str
    notes_title: str
    notes: str
    objectives: tuple[Objective, ...]


@dataclass(frozen=True)
class Course:
    topic_id: str
    name: str
    units: tuple[Unit, ...]


NOTES_SOURCE = "Apuntes sintéticos de demostración, a partir del esquema público de habilidades medidas de Microsoft"

AI_900 = Course(
    topic_id="azure-ai-900",
    name="Azure AI Fundamentals (AI-900)",
    units=(
        Unit(
            unit_id="ai-workloads",
            name="U1 · Cargas de trabajo de IA y consideraciones",
            notes_title="Cargas de trabajo de IA e IA responsable",
            notes=(
                "Una carga de trabajo de IA es un tipo de problema que un sistema resuelve con modelos: "
                "predecir valores, detectar anomalías, interpretar imágenes, procesar lenguaje o generar contenido nuevo. "
                "La visión por computadora interpreta imágenes y video; el procesamiento de lenguaje natural interpreta texto y voz. "
                "La IA generativa produce texto, imágenes o código a partir de una instrucción. "
                "Microsoft define seis principios de IA responsable: equidad, confiabilidad y seguridad, privacidad y seguridad de la información, "
                "inclusión, transparencia y responsabilidad. "
                "Un modelo que rechaza más solicitudes de un grupo de personas que de otro vulnera la equidad."
            ),
            objectives=(
                Objective(
                    "ai-tipos-carga",
                    "Reconocer las cargas de trabajo comunes de IA",
                    (
                        Question(
                            "Una municipalidad quiere que un sistema lea fotos de patentes de vehículos en una barrera de acceso. "
                            "¿Qué tipo de carga de trabajo de IA es?",
                            ("Procesamiento de lenguaje natural", "Visión por computadora", "Detección de anomalías", "Pronóstico de series de tiempo"),
                            1,
                            "Leer texto dentro de una imagen es visión por computadora (reconocimiento óptico de caracteres).",
                        ),
                        Question(
                            "Un servicio detecta transacciones inusuales en el pago de proveedores del Estado. ¿Qué carga de trabajo describe mejor ese caso?",
                            ("Detección de anomalías", "Traducción automática", "Reconocimiento facial", "Generación de imágenes"),
                            0,
                            "Encontrar valores que se alejan de lo habitual es detección de anomalías.",
                        ),
                    ),
                ),
                Objective(
                    "ai-principios",
                    "Describir los principios de IA responsable de Microsoft",
                    (
                        Question(
                            "Un sistema que prioriza solicitudes ciudadanas rechaza con más frecuencia las de ciertas comunas. ¿Qué principio vulnera?",
                            ("Transparencia", "Equidad", "Privacidad y seguridad", "Responsabilidad"),
                            1,
                            "La equidad exige que el sistema trate de manera comparable a todos los grupos de personas.",
                        ),
                    ),
                ),
                Objective(
                    "ai-transparencia",
                    "Explicar transparencia y responsabilidad en sistemas de IA",
                    (
                        Question(
                            "Una persona recibe una decisión automática y pide saber qué factores la influyeron. ¿Qué principio está en juego?",
                            ("Inclusión", "Confiabilidad y seguridad", "Transparencia", "Equidad"),
                            2,
                            "La transparencia implica que las personas entiendan cómo y por qué el sistema llega a un resultado.",
                        ),
                    ),
                ),
            ),
        ),
        Unit(
            unit_id="ml-fundamentos",
            name="U2 · Principios fundamentales del aprendizaje automático en Azure",
            notes_title="Aprendizaje automático: regresión, clasificación y agrupamiento",
            notes=(
                "El aprendizaje automático entrena un modelo con datos para que prediga o descubra patrones. "
                "La regresión predice un valor numérico, por ejemplo el tiempo de espera de un trámite. "
                "La clasificación asigna una categoría, por ejemplo si un reclamo es urgente o no. "
                "El agrupamiento (clustering) reúne casos parecidos sin etiquetas previas. "
                "Las características son los datos de entrada y la etiqueta es lo que se quiere predecir. "
                "Los datos se separan en entrenamiento y validación para medir si el modelo generaliza. "
                "Azure Machine Learning ofrece aprendizaje automático automatizado y un diseñador visual sin código."
            ),
            objectives=(
                Objective(
                    "ml-tecnicas",
                    "Distinguir regresión, clasificación y agrupamiento",
                    (
                        Question(
                            "Se quiere predecir cuántos días tardará en resolverse un reclamo. ¿Qué técnica corresponde?",
                            ("Clasificación", "Agrupamiento", "Regresión", "Detección de objetos"),
                            2,
                            "Cuando el resultado es un número continuo, se usa regresión.",
                        ),
                        Question(
                            "Un modelo debe decidir si un correo es spam o no es spam. ¿Qué técnica es?",
                            ("Clasificación", "Regresión", "Agrupamiento", "Reconocimiento de voz"),
                            0,
                            "Elegir entre categorías predefinidas es clasificación; con dos categorías es clasificación binaria.",
                        ),
                    ),
                ),
                Objective(
                    "ml-conceptos",
                    "Explicar características, etiquetas y conjuntos de entrenamiento y validación",
                    (
                        Question(
                            "En un modelo que predice la deserción de usuarios, ¿qué es la etiqueta?",
                            (
                                "Cada columna de datos de entrada",
                                "El valor que el modelo debe predecir",
                                "El algoritmo elegido",
                                "El servidor donde se entrena",
                            ),
                            1,
                            "La etiqueta es el resultado conocido que el modelo aprende a predecir; las características son las entradas.",
                        ),
                    ),
                ),
                Objective(
                    "ml-azure",
                    "Identificar capacidades de Azure Machine Learning",
                    (
                        Question(
                            "Una analista sin experiencia en programación quiere entrenar un modelo arrastrando y conectando módulos. ¿Qué capacidad de Azure Machine Learning usa?",
                            ("El diseñador", "Azure Policy", "Azure Monitor", "Las zonas de disponibilidad"),
                            0,
                            "El diseñador de Azure Machine Learning permite construir canalizaciones de forma visual, sin escribir código.",
                        ),
                    ),
                ),
            ),
        ),
        Unit(
            unit_id="vision",
            name="U3 · Cargas de trabajo de visión por computadora en Azure",
            notes_title="Visión por computadora en Azure",
            notes=(
                "La clasificación de imágenes asigna una etiqueta a la imagen completa; la detección de objetos además ubica cada objeto con un cuadro delimitador. "
                "El reconocimiento óptico de caracteres (OCR) extrae texto de imágenes y documentos escaneados. "
                "Azure AI Vision analiza imágenes y genera descripciones, etiquetas y lectura de texto. "
                "Azure AI Document Intelligence extrae campos de formularios, facturas y boletas. "
                "La detección facial identifica rostros en una imagen; su uso está sujeto a restricciones de IA responsable."
            ),
            objectives=(
                Objective(
                    "vis-tareas",
                    "Distinguir clasificación de imágenes y detección de objetos",
                    (
                        Question(
                            "Se necesita saber dónde está cada casco de seguridad en la foto de una obra, no solo si aparece. ¿Qué tarea corresponde?",
                            ("Clasificación de imágenes", "Detección de objetos", "Análisis de sentimiento", "Traducción"),
                            1,
                            "La detección de objetos entrega la ubicación de cada objeto, la clasificación solo una etiqueta global.",
                        ),
                        Question(
                            "Un modelo recibe una foto de una planta y responde únicamente 'enferma' o 'sana'. ¿Qué tarea realiza?",
                            ("Detección de objetos", "Reconocimiento óptico de caracteres", "Clasificación de imágenes", "Segmentación de voz"),
                            2,
                            "Asignar una etiqueta a la imagen completa es clasificación de imágenes.",
                        ),
                    ),
                ),
                Objective(
                    "vis-ocr",
                    "Describir el reconocimiento óptico de caracteres y la extracción de datos de documentos",
                    (
                        Question(
                            "Un servicio público quiere extraer el monto y la fecha de miles de facturas escaneadas. ¿Qué servicio de Azure es el más adecuado?",
                            ("Azure AI Document Intelligence", "Azure Policy", "Azure DevOps", "Azure Bastion"),
                            0,
                            "Document Intelligence extrae campos estructurados de formularios y facturas.",
                        ),
                    ),
                ),
                Objective(
                    "vis-servicios",
                    "Identificar los servicios de Azure para visión y rostros",
                    (
                        Question(
                            "¿Qué servicio de Azure genera descripciones y etiquetas para el contenido de una imagen?",
                            ("Azure AI Vision", "Azure Cosmos DB", "Azure Load Balancer", "Azure Key Vault"),
                            0,
                            "Azure AI Vision analiza imágenes y devuelve etiquetas, descripciones y texto leído.",
                        ),
                    ),
                ),
            ),
        ),
        Unit(
            unit_id="nlp",
            name="U4 · Cargas de trabajo de procesamiento de lenguaje natural en Azure",
            notes_title="Procesamiento de lenguaje natural en Azure",
            notes=(
                "El procesamiento de lenguaje natural interpreta texto y voz. "
                "La extracción de frases clave resume los temas de un texto; el reconocimiento de entidades encuentra nombres, lugares y fechas. "
                "El análisis de sentimiento indica si un texto es positivo, neutro o negativo. "
                "Azure AI Language reúne estas funciones. Azure AI Translator traduce texto entre idiomas. "
                "Azure AI Speech convierte voz en texto, texto en voz y puede traducir voz. "
                "Un bot conversacional combina reconocimiento de la intención de la persona con respuestas basadas en una base de conocimiento."
            ),
            objectives=(
                Objective(
                    "nlp-texto",
                    "Describir extracción de frases clave, entidades y sentimiento",
                    (
                        Question(
                            "Una oficina de reclamos quiere saber si los comentarios de la ciudadanía son positivos o negativos. ¿Qué función usa?",
                            ("Reconocimiento de entidades", "Análisis de sentimiento", "Detección de objetos", "Clasificación de imágenes"),
                            1,
                            "El análisis de sentimiento puntúa la actitud expresada en un texto.",
                        ),
                        Question(
                            "¿Qué función extrae del texto nombres de personas, lugares y fechas?",
                            ("Reconocimiento de entidades", "Síntesis de voz", "Regresión", "Agrupamiento"),
                            0,
                            "El reconocimiento de entidades nombradas identifica y categoriza esos elementos.",
                        ),
                    ),
                ),
                Objective(
                    "nlp-voz",
                    "Identificar capacidades de voz y traducción",
                    (
                        Question(
                            "Se quiere transcribir automáticamente las reuniones del consejo municipal. ¿Qué servicio corresponde?",
                            ("Azure AI Speech", "Azure Firewall", "Azure Blob Storage", "Azure Policy"),
                            0,
                            "Azure AI Speech convierte voz en texto (transcripción) y texto en voz.",
                        ),
                    ),
                ),
                Objective(
                    "nlp-conversacion",
                    "Describir la comprensión de lenguaje conversacional",
                    (
                        Question(
                            "En un asistente virtual, ¿qué es una 'intención'?",
                            (
                                "El idioma en el que se escribe",
                                "Lo que la persona quiere lograr con su mensaje",
                                "La región de Azure donde corre el bot",
                                "El nombre del servicio de traducción",
                            ),
                            1,
                            "La intención es el objetivo detrás de la frase, por ejemplo 'consultar el estado de un trámite'.",
                        ),
                    ),
                ),
            ),
        ),
        Unit(
            unit_id="genai",
            name="U5 · Cargas de trabajo de IA generativa en Azure",
            notes_title="IA generativa y Azure OpenAI",
            notes=(
                "La IA generativa crea contenido nuevo a partir de una instrucción llamada prompt. "
                "Los modelos de lenguaje grandes se entrenan con grandes volúmenes de texto y predicen la continuación más probable. "
                "Un copiloto es un asistente que ayuda a una persona dentro de una aplicación y siempre requiere su supervisión. "
                "Azure OpenAI Service ofrece modelos de lenguaje y de imágenes con controles de seguridad empresariales. "
                "Un buen prompt da contexto, indica el formato esperado y acota la tarea. "
                "Los modelos pueden inventar datos (alucinar), por eso las respuestas deben verificarse."
            ),
            objectives=(
                Objective(
                    "gen-conceptos",
                    "Describir los conceptos de IA generativa y los copilotos",
                    (
                        Question(
                            "¿Qué es un copiloto en el contexto de la IA generativa?",
                            (
                                "Un servidor de respaldo",
                                "Un asistente que apoya a la persona dentro de una aplicación",
                                "Un tipo de red virtual",
                                "Un formato de archivo de imágenes",
                            ),
                            1,
                            "Un copiloto asiste a la persona en su tarea; la decisión final sigue siendo humana.",
                        ),
                        Question(
                            "Un modelo de lenguaje responde con seguridad un dato que no existe. ¿Cómo se llama este comportamiento?",
                            ("Alucinación", "Regresión", "Segmentación", "Replicación geográfica"),
                            0,
                            "Cuando el modelo genera información falsa pero plausible se habla de alucinación.",
                        ),
                    ),
                ),
                Objective(
                    "gen-prompts",
                    "Explicar cómo mejorar un prompt",
                    (
                        Question(
                            "¿Cuál de estas prácticas mejora un prompt?",
                            (
                                "Dejarlo lo más breve posible, sin contexto",
                                "Indicar el contexto, la tarea y el formato de respuesta esperado",
                                "Escribirlo en mayúsculas",
                                "Repetir la misma palabra varias veces",
                            ),
                            1,
                            "El contexto, una tarea acotada y el formato esperado orientan al modelo hacia respuestas útiles.",
                        ),
                    ),
                ),
                Objective(
                    "gen-azure-openai",
                    "Identificar Azure OpenAI Service y su uso responsable",
                    (
                        Question(
                            "¿Qué servicio de Azure da acceso a modelos de lenguaje generativos con controles de seguridad empresariales?",
                            ("Azure OpenAI Service", "Azure Backup", "Azure Site Recovery", "Azure Advisor"),
                            0,
                            "Azure OpenAI Service ofrece modelos generativos dentro de Azure con filtros de contenido y controles de acceso.",
                        ),
                    ),
                ),
            ),
        ),
    ),
)

AZ_900 = Course(
    topic_id="azure-az-900",
    name="Azure Fundamentals (AZ-900)",
    units=(
        Unit(
            unit_id="cloud-concepts",
            name="U1 · Conceptos de la nube",
            notes_title="Conceptos de la nube",
            notes=(
                "La computación en la nube entrega recursos por internet y se paga por consumo, lo que cambia el gasto de capital (CapEx) por gasto operativo (OpEx). "
                "Sus beneficios incluyen alta disponibilidad, escalabilidad, elasticidad, agilidad y recuperación ante desastres. "
                "La responsabilidad se comparte: el proveedor cuida la infraestructura física y el cliente cuida sus datos y accesos. "
                "IaaS entrega máquinas virtuales y redes, PaaS entrega una plataforma para ejecutar aplicaciones y SaaS entrega la aplicación terminada. "
                "La nube puede ser pública, privada o híbrida."
            ),
            objectives=(
                Objective(
                    "cc-beneficios",
                    "Describir los beneficios de la nube y el modelo de consumo",
                    (
                        Question(
                            "Un servicio sube sus recursos cuando hay mucha demanda y los baja cuando termina. ¿Qué beneficio describe esto?",
                            ("Elasticidad", "Soberanía de datos", "Gasto de capital", "Redundancia geográfica"),
                            0,
                            "La elasticidad ajusta los recursos automáticamente a la demanda.",
                        ),
                        Question(
                            "¿Cómo cambia el gasto una organización al pasar de un centro de datos propio a la nube pública?",
                            (
                                "De gasto operativo a gasto de capital",
                                "De gasto de capital a gasto operativo",
                                "No cambia nada",
                                "Deja de pagar por completo",
                            ),
                            1,
                            "La nube se paga por consumo (OpEx) en lugar de comprar equipos por adelantado (CapEx).",
                        ),
                    ),
                ),
                Objective(
                    "cc-responsabilidad",
                    "Explicar el modelo de responsabilidad compartida",
                    (
                        Question(
                            "En un servicio SaaS, ¿qué sigue siendo siempre responsabilidad del cliente?",
                            (
                                "El edificio del centro de datos",
                                "Sus datos y quién tiene acceso a ellos",
                                "El hardware de red",
                                "La energía eléctrica",
                            ),
                            1,
                            "Sea cual sea el modelo de servicio, el cliente responde por sus datos, identidades y dispositivos.",
                        ),
                    ),
                ),
                Objective(
                    "cc-servicios",
                    "Diferenciar IaaS, PaaS y SaaS y los tipos de nube",
                    (
                        Question(
                            "Una repartición usa el correo en línea sin administrar servidores ni sistema operativo. ¿Qué modelo es?",
                            ("IaaS", "PaaS", "SaaS", "Nube privada"),
                            2,
                            "En SaaS el proveedor administra todo y el cliente solo usa la aplicación.",
                        ),
                    ),
                ),
            ),
        ),
        Unit(
            unit_id="arquitectura",
            name="U2 · Arquitectura y servicios de Azure",
            notes_title="Arquitectura y servicios de Azure",
            notes=(
                "Una región de Azure es un conjunto de centros de datos; las zonas de disponibilidad son ubicaciones físicamente separadas dentro de una región. "
                "Los recursos se organizan en grupos de recursos, dentro de suscripciones, que a su vez pueden agruparse en grupos de administración. "
                "Para cómputo Azure ofrece máquinas virtuales, App Service, contenedores y Azure Functions. "
                "Una red virtual conecta recursos de forma privada; VPN Gateway y ExpressRoute la conectan con la red local. "
                "El almacenamiento Blob guarda objetos y se replica con opciones como LRS, ZRS y GRS. "
                "Microsoft Entra ID gestiona identidades; la autenticación multifactor y el control de acceso basado en roles reducen el riesgo de accesos indebidos."
            ),
            objectives=(
                Objective(
                    "arq-regiones",
                    "Describir regiones, zonas de disponibilidad y la jerarquía de recursos",
                    (
                        Question(
                            "¿Qué ofrece una zona de disponibilidad dentro de una región de Azure?",
                            (
                                "Centros de datos separados físicamente para tolerar fallas de una ubicación",
                                "Un descuento en el precio de las máquinas virtuales",
                                "Un idioma distinto para el portal",
                                "Acceso a Azure sin internet",
                            ),
                            0,
                            "Las zonas aíslan fallas de energía, refrigeración o red entre sus centros de datos.",
                        ),
                        Question(
                            "¿Cuál es el contenedor lógico donde se agrupan recursos relacionados que se gestionan juntos?",
                            ("Grupo de recursos", "Zona de disponibilidad", "Etiqueta", "Red virtual"),
                            0,
                            "El grupo de recursos reúne recursos que comparten ciclo de vida y permisos.",
                        ),
                    ),
                ),
                Objective(
                    "arq-computo",
                    "Identificar opciones de cómputo y de redes",
                    (
                        Question(
                            "Una aplicación debe ejecutar un fragmento de código solo cuando llega un evento, sin administrar servidores. ¿Qué servicio conviene?",
                            ("Azure Functions", "Máquina virtual dedicada", "ExpressRoute", "Azure Bastion"),
                            0,
                            "Azure Functions es cómputo sin servidor, dirigido por eventos y cobrado por ejecución.",
                        ),
                    ),
                ),
                Objective(
                    "arq-almacenamiento",
                    "Describir el almacenamiento y las opciones de redundancia",
                    (
                        Question(
                            "¿Qué opción de redundancia copia los datos en tres zonas de disponibilidad de una misma región?",
                            ("LRS", "ZRS", "Sin redundancia", "Copia local en el equipo"),
                            1,
                            "ZRS replica de forma síncrona en tres zonas; LRS lo hace dentro de un solo centro de datos.",
                        ),
                    ),
                ),
                Objective(
                    "arq-identidad",
                    "Explicar identidad, acceso y seguridad en Azure",
                    (
                        Question(
                            "Una cuenta de funcionario es robada porque su contraseña se filtró. ¿Qué medida habría reducido más el riesgo?",
                            (
                                "Autenticación multifactor",
                                "Cambiar de región",
                                "Aumentar el tamaño de la máquina virtual",
                                "Usar almacenamiento redundante",
                            ),
                            0,
                            "La autenticación multifactor exige un segundo factor además de la contraseña.",
                        ),
                    ),
                ),
            ),
        ),
        Unit(
            unit_id="gobierno",
            name="U3 · Administración y gobierno de Azure",
            notes_title="Administración y gobierno de Azure",
            notes=(
                "La calculadora de precios estima el costo de una solución y la de TCO compara con un centro de datos propio. "
                "Las etiquetas (tags) permiten clasificar recursos para asignar costos. "
                "Azure Policy hace cumplir reglas, por ejemplo restringir las regiones permitidas; un bloqueo de recursos impide borrarlos o modificarlos por error. "
                "El portal, la CLI y PowerShell administran recursos; las plantillas ARM los despliegan de forma repetible como código. "
                "Azure Monitor recopila métricas y registros, Azure Advisor entrega recomendaciones y Service Health informa incidentes que afectan a la suscripción."
            ),
            objectives=(
                Objective(
                    "gob-costos",
                    "Describir herramientas de estimación y gestión de costos",
                    (
                        Question(
                            "Antes de migrar, una repartición quiere estimar el costo mensual de una solución en Azure. ¿Qué herramienta usa?",
                            ("Calculadora de precios", "Azure Monitor", "Bloqueo de recursos", "Azure Arc"),
                            0,
                            "La calculadora de precios permite estimar el costo de los servicios antes de contratarlos.",
                        ),
                        Question(
                            "¿Para qué sirven las etiquetas (tags) en el control de costos?",
                            (
                                "Para cifrar los datos",
                                "Para clasificar recursos y asignar el gasto a áreas o proyectos",
                                "Para aumentar la velocidad de red",
                                "Para crear copias de seguridad",
                            ),
                            1,
                            "Las etiquetas agregan metadatos que permiten agrupar y reportar costos por área o proyecto.",
                        ),
                    ),
                ),
                Objective(
                    "gob-politicas",
                    "Explicar Azure Policy y los bloqueos de recursos",
                    (
                        Question(
                            "Se quiere impedir que alguien cree recursos fuera de las regiones autorizadas. ¿Qué servicio se usa?",
                            ("Azure Policy", "Azure Advisor", "La calculadora de TCO", "Service Health"),
                            0,
                            "Azure Policy evalúa y hace cumplir reglas de la organización sobre los recursos.",
                        ),
                    ),
                ),
                Objective(
                    "gob-herramientas",
                    "Identificar herramientas de administración y monitoreo",
                    (
                        Question(
                            "¿Qué herramienta de Azure recopila métricas y registros para vigilar el estado de las aplicaciones?",
                            ("Azure Monitor", "Azure Blob Storage", "VPN Gateway", "Microsoft Entra ID"),
                            0,
                            "Azure Monitor reúne y analiza telemetría de recursos y aplicaciones.",
                        ),
                    ),
                ),
            ),
        ),
    ),
)

COURSES = (AI_900, AZ_900)

__all__ = ["AI_900", "AZ_900", "COURSES", "Course", "NOTES_SOURCE", "Objective", "Question", "Unit"]
