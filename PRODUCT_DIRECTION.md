# Dirección de producto: revisión de logs asistida por LLM

Documento de propuesta tras revisar el repositorio. No describe funcionalidades ya implementadas. Las capacidades solicitadas están acordadas; los valores de ejemplo (cadencia, tamaño de segmento), tecnologías candidatas y objetivos de rendimiento siguen pendientes de validación en el piloto.

## Objetivo acordado

Revisar automáticamente los logs que normalmente nadie lee para identificar fallos de funcionamiento y problemas de seguridad, explicar la evidencia y facilitar la investigación humana. Poder ajustar sensibilidad, controlar notificaciones por tipo de problema, consultar un histórico y copiar contexto para pedir ayuda a otro LLM. Un mini-PC puede revisar sus propios logs y los de varias máquinas recibidos como archivos o carpetas. Toda la información debe estar vinculada a una máquina y una fuente desde el primer día, aunque solo exista una máquina. Rotación, compresión, filtros asistidos por chat y estadísticas por máquina/fuente forman parte del producto.

Los horarios SSH eran un ejemplo del usuario, no un requisito de producto. El perfil temporal no debe condicionar el diseño ni ser el centro de la aplicación. Se propone retirarlo del flujo principal durante la evolución, conservando recuperables los datos existentes. No se ha retirado código en esta revisión.

## Diagnóstico del prototipo

| Área | Estado observado | Cambio necesario |
| --- | --- | --- |
| Recolección | journald y archivos; seguimiento en vivo sin cursor/offset persistente | Descubrimiento local, máquinas y fuentes explícitas, carpetas de importación, captura duradera y recuperación ante rotación/reinicio |
| Selección | El prefiltro descarta mensajes sin palabras/prioridades conocidas | Las reglas priorizan; el análisis general también recibe mensajes sin señales conocidas |
| Agregación | Agrupa por host, servicio y firma; espera de proceso de 3 segundos y lotes de 15 | Ventanas configurables y presupuesto de tokens; preservar relaciones entre servicios y evidencia original |
| Persistencia | SQLite guarda alertas, supresiones, feedback y observaciones SSH | Máquinas/fuentes, segmentos de eventos comprimidos, índices, trabajos, problemas, apariciones, entregas, consumo y auditoría |
| Análisis | Una llamada por incidente, contexto parcial y resultado JSON validado | Primera revisión de ventanas generales; investigación contextual de candidatos; referencias comprobables |
| Recursos | Modelo, URL, timeout y máximo de salida configurables | Capacidad efectiva de contexto, presupuesto de entrada, cola, límites de trabajo y métricas |
| Feedback | Reglas por patrón, servicio, IP o texto; descartar una alerta puede crear supresión | Separar resolver, no notificar y excluir del análisis; reglas acotadas, previsualizadas y reversibles |
| Avisos | Escritorio y varios destinos; umbral de severidad | Avisar por problema nuevo o cambio relevante; limitar repeticiones, reintentar y registrar resultados |
| Interfaz | CLI | Panel web local; conservar CLI para diagnóstico y automatización |
| Evaluación | 202 tests aprobados y 3 fallidos en Python 3.12.3 | Reparar fallos relevantes y medir detecciones, omisiones, falsos positivos y coste con corpus independiente |

La revisión anterior reprodujo pérdida de un incidente al cerrar mientras se espera al LLM, diagnóstico saludable con el modelo ausente y ausencia de error con fuentes vacías. La suite fallida corresponde al perfil temporal SSH. No son resultados de una evaluación de calidad de un modelo real.

## Máquinas, fuentes e instalación

Jerarquía base: **instancia recolectora → máquina de origen → fuente → generación/archivo → evento → análisis → problema**. La máquina donde corre el programa no es necesariamente la que produjo el evento.

- **Máquina:** ID interno estable, nombre visible, tipo local/importada, hostname declarado, sistema/distribución/versión cuando se conozcan, zona horaria, etiquetas y notas de contexto. No exigir todos los datos para importar; marcar desconocidos. IP/hostname no son claves únicas y pueden cambiar o repetirse.
- **Fuente:** ID estable, máquina asignada, tipo journald/archivo/carpeta, ubicación, patrones de inclusión/exclusión de archivos, formato/parser, política de fechas, modo vivo/importación, frecuencia esperada, retención y estado de permisos. Un archivo rotado sigue perteneciendo a la misma fuente lógica.
- **Evento:** IDs de máquina/fuente, procedencia verificable dentro de la captura, fecha original y normalizada, fecha de recepción, fiabilidad temporal, texto y campos interpretados. El hostname que declara el mensaje se conserva como dato; no sustituye automáticamente la asociación configurada.
- **Problema:** máquina propietaria y fuentes/eventos relacionados; clave de agrupación que incluya la máquina. Una posible correlación entre máquinas será una relación explícita, nunca una fusión accidental de incidentes iguales.
- **Migración:** no atribuir automáticamente toda la base antigua al mini-PC: revisar hostnames/procedencia existentes y dejar registros ambiguos como origen sin asignar hasta resolverlos.

Ejemplo de organización en el mini-PC:

| Máquina | Fuentes |
| --- | --- |
| Mini-PC local | Journal del sistema y archivo de una aplicación |
| Servidor A | Carpeta `/srv/logs/servidor-a/`, con archivos activos y rotados |
| NAS | Archivo `/srv/logs/nas/system.log` o exportaciones comprimidas |

Una carpeta se asigna a una máquina por defecto. Un archivo agregado con varios emisores requiere un parser y un mapeo explícito; los emisores desconocidos quedan pendientes de asignación, sin crear máquinas confiables a partir de texto arbitrario.

### Experiencia «instalar y funciona»

1. Crear la máquina local y descubrir distribución/versión, disponibilidad real de journald y archivos convencionales legibles. La distribución orienta las sugerencias; no demuestra que una ruta exista ni que recoja todos los servicios.
2. Ofrecer un conjunto recomendado de fuentes detectadas y arrancar con valores seguros tras completar el alta inicial. No escanear todo el disco. Priorizar una fuente para datos duplicados entre journal y syslog cuando se pueda establecer su equivalencia.
3. Mostrar qué se puede leer, qué está vacío y qué requiere un permiso concreto. Ofrecer instrucciones ajustadas al equipo; no resolverlo ejecutando todo el panel como root. Sin fuentes válidas, el alta no puede aparecer como monitorización activa.
4. Detectar un servidor LLM local si está disponible, comprobar el modelo y validar una petición sintética. Si no existe, guiar su configuración o la de otro proveedor. No descargar modelos grandes ni enviar logs a un proveedor remoto de forma implícita.
5. Elegir desde ahora o importar un intervalo histórico. Los lotes históricos tienen prioridad y política de avisos separadas: un archivo del mes pasado no debe generar una ráfaga de avisos como si acabara de suceder.
6. **Añadir máquina → añadir archivo/carpeta → vista previa de formato, fechas y muestras → activar fuente.** El usuario puede aportar zona horaria/formato cuando no se detecten con fiabilidad.

Primera versión: varias máquinas mediante archivos/carpetas accesibles al recolector y fuentes locales, más un piloto de recepción continua fiable para el mini-PC. Los archivos pueden llegar por un mecanismo externo ya existente. El piloto puede reutilizar un reenviador de logs con cola persistente y transporte autenticado, opcionalmente a través de SSH; concretar el adaptador antes de prometer entrega duradera extremo a extremo. Registrar recepción reciente no prueba que el emisor siga vivo. Mostrar última fecha de evento y de recepción por separado, con retraso esperado configurable. El despliegue automático de agentes y una variedad de transportes gestionados siguen como fase posterior; el modelo de datos no depende del transporte.

## Flujo propuesto

1. Recoger de las fuentes seleccionadas, con permisos de solo lectura, asignación explícita a máquina y seguimiento de generaciones/rotación. Para importaciones, procesar cada entrega estable de forma recuperable.
2. Guardar los eventos y la posición de lectura de manera coherente antes de considerarlos recogidos. Aplicar exclusiones de análisis como estado trazable, conservando el evento conforme a su política de retención.
3. Crear trabajos duraderos por máquina, con fuentes y contribuciones identificadas, ventanas de eventos nuevos y un pequeño contexto solapado identificable. Repartir capacidad entre máquinas para que una importación grande no bloquee el equipo local.
4. Preparar lotes ajustados a la capacidad del modelo. Compactar repeticiones con conteos, tiempos y ejemplos vinculados a originales; conservar lo omitido de cada petición.
5. Revisar también mensajes sin palabras de error conocidas. Las señales deterministas adelantan trabajo urgente, pero no definen toda la cobertura del LLM.
6. Pedir al LLM hallazgos con referencias a eventos. Validar esquema y referencias antes de aceptar sus conclusiones.
7. Ampliar candidatos con consultas de solo lectura al histórico local, acotadas por tiempo, servicio, entidad y presupuesto.
8. Crear o actualizar un problema persistente, registrar su evolución y decidir si corresponde avisar.

La captura continúa aunque el LLM esté ocupado o caído. Un fallo de inferencia deja el trabajo pendiente o fallido/reintentable; no se convierte en un análisis limpio. El cierre no pierde eventos pendientes. Cada trabajo registra qué entrada vio realmente el modelo y qué modelo/configuración lo evaluó.

## Rotación, compresión y retención

Separar la rotación que hacen los productores de logs de la gestión del almacenamiento propio. La aplicación observa los archivos de origen; no modifica su logrotate, journal ni borra sus archivos al purgar el histórico interno.

### Recepción continua: conexión, archivos y análisis independientes

No usar «líneas analizadas → rotar el archivo de entrada» como condición de rotación. El diseño distingue:

- **Conexión:** puede permanecer abierta y transportar muchos bloques sucesivos.
- **Segmento de almacenamiento:** activo → sellado → comprimido; se sella por tamaño o antigüedad, sin esperar al LLM.
- **Trabajo de análisis:** pendiente → en curso → completado o reintentable/fallido, con cobertura registrada sobre IDs/rangos de eventos.
- **Retención:** decide cuándo purgar un segmento/evidencia; haber completado análisis permite liberar almacenamiento bajo esa política, pero no obliga a borrar inmediatamente el histórico.

Un segmento pendiente puede estar comprimido y seguir siendo analizable. Comprimir no equivale a descartar ni a marcar como analizado. El sistema conoce qué rangos ha procesado, sin recortar físicamente el principio del archivo activo.

El receptor controla el único escritor de cada segmento: al alcanzar un umbral, termina el registro actual, asegura los datos, sella el bloque, cambia al siguiente y continúa. Los registros entrantes esperan en una cola acotada durante ese cambio o se frena el transporte cuando sea necesario. La compresión trabaja después sobre el segmento inmutable; no necesita detener la conexión ni acceder al archivo activo.

Propuesta de partida para medir en el piloto: sellar al alcanzar 32 MiB de datos lógicos o 60 segundos desde la primera escritura, lo que ocurra antes; no generar segmentos vacíos. Son umbrales ajustables de almacenamiento, independientes del análisis cada 5 minutos y de sus lotes por tokens. La revisión urgente puede solicitar sellado anticipado; el coste de archivos pequeños y metadatos se medirá antes de fijar defaults.

Un trabajo puede combinar varios segmentos o dividir uno grande en múltiples peticiones. El límite de escaneo se fija sobre eventos duraderos completos; datos recibidos después quedan para el siguiente trabajo. Mantener continuidad y contexto entre segmentos, especialmente para mensajes multilínea. Usar en el transporte enmarcado explícito de eventos/lotes y conservar fragmentos incompletos; TCP/SSH no garantizan que una lectura sea exactamente una línea de log.

Si los archivos los escribe una herramienta externa, el receptor de la aplicación no debe rotarlos por su cuenta: configurar rotación/reapertura en esa herramienta o leerla como fuente externa. Renombrar un archivo en Linux no redirige el descriptor que el escritor ya tiene abierto. Para almacenamiento propio evitar copytruncate y reescritura de prefijos; implementar rotación en el escritor que controla los descriptores.

### Transporte remoto y recuperación de cortes

Arquitectura del piloto: **fuente remota → cola duradera del emisor → transporte autenticado → recepción duradera del servidor → segmentos/cola de análisis → LLM**. El agente/reenviador guarda su posición de fuente de forma coherente con su cola. Un reinicio no debe saltarse eventos leídos pero aún no guardados; no modificar ni truncar el log de la aplicación remota.

El túnel SSH puede proteger el canal y facilitar conectividad, pero no aporta por sí solo confirmación de escritura a disco, almacenamiento pendiente, recuperación de cursores ni eliminación de duplicados. Una tubería simple de `tail -f` a un archivo remoto solo sirve como experimento si se declaran esas limitaciones; no es la base de la entrega fiable.

Contrato de custodia: el emisor conserva lo no confirmado; el receptor confirma un lote únicamente al asumir su custodia en almacenamiento duradero recuperable. Esa confirmación **no espera al LLM ni al sellado de un segmento**: puede basarse en un diario/cola durable de recepción, con confirmaciones agrupadas. Distinguir ACK de transporte, aceptación en memoria y confirmación duradera; ninguna implementación queda validada solo porque el socket acepte bytes.

Cada entrega incluye identidad autenticada de máquina y referencias estables por fuente/generación/secuencia. Tras reconectar se reenvían lotes no confirmados; si se perdió una confirmación después de guardar, el receptor reconoce la repetición. Objetivo: entrega al menos una vez con ingestión idempotente. Concurrencia o prioridad pueden completar rangos fuera de orden: no avanzar la frontera confirmada más allá de un hueco. No usar solo timestamp o hash del mensaje como ID; las apariciones iguales siguen siendo eventos distintos.

Preferir integrar un reenviador existente donde sea viable: rsyslog con RELP y cola de disco es candidato para el piloto, con autenticación TLS o túnel SSH según despliegue. Revisar la semántica concreta de persistencia/ACK y sincronización de las versiones instaladas. RELP o una cola asistida por disco no implican automáticamente resistencia a un corte eléctrico. Si el protocolo/fuente no preserva IDs estables, declarar el límite de deduplicación o incorporar un adaptador; no prometer exactamente una aparición sin probarlo.

Ante servidor lleno o caído, dejar de confirmar nuevos datos y aplicar contrapresión para que queden pendientes en el emisor. El emisor tiene su propia cuota y política de saturación; frenar la red no evita que las aplicaciones sigan generando logs ni que roten sus originales. Avisar también de su reserva restante/huecos cuando el conector pueda reportarlos. Cualquier caducidad o descarte de emergencia debe quedar visible; no afirmar retención ilimitada.

### Leer fuentes que rotan o llegan comprimidas

- Seguir renombrados y reemplazos, drenar el descriptor anterior cuando sea posible y reconocer truncados. Persistir identidad de generación y posición, no solo el nombre de archivo. Resolver reinicios entre lectura y confirmación de forma idempotente.
- `copytruncate` tiene carreras propias: detectar truncados observables y señalar discontinuidades conocidas, sin garantizar reconstruir bytes que el productor haya perdido o sobrescrito entre lecturas. La documentación de logrotate describe ese riesgo.
- Carpetas: admitir patrones de nombres, subcarpetas opcionales y exclusiones de archivos; evitar enlaces/rutas que salgan del ámbito configurado. No confundir exclusión de archivos con regex sobre contenido.
- Para entregas, preferir archivo temporal y renombrado atómico o manifiesto de finalización. Si no existen, usar estabilidad de tamaño/fecha como heurística declarada y reintentar ante cambios; una pausa de escritura no garantiza entrega terminada.
- Primera entrega: archivos de texto y `.gz`; siguiente ampliación planificada: `.zst` y `.xz`. Lectura por streaming con límites de bytes descomprimidos, ratio, memoria y tiempo; registrar archivos corruptos, incompletos o de formato no soportado y continuar con las demás fuentes.
- No volver a analizar entero un comprimido en cada escaneo. Registrar identidad de entrega/contenido, estado y posición lógica recuperable; si el formato no permite saltar, releer de forma acotada e idempotente. Preservar nuevos eventos cuando un archivo se amplía o se reemplaza.
- Evitar la doble ingestión de un activo que luego llega como `.1.gz` usando procedencia/generaciones, manifiestos y solapamientos verificables. Un hash de mensaje aislado no basta: dos mensajes iguales pueden ser dos apariciones reales. Si no se puede demostrar equivalencia, conservar y marcar posible duplicado.
- Preservar eventos multilínea, encoding y formato temporal; no interpretar cada línea de un traceback como un problema independiente. Para fechas sin año/zona, marcar inferencia y conservar el dato original.

### Almacenamiento gestionado por la aplicación

Propuesta: SQLite para metadatos, índices, cola, problemas y consumo; texto original en segmentos duraderos, primero activos y después sellados/comprimidos por máquina/fuente y tamaño o intervalo. Evaluar Zstandard como compresión interna por su equilibrio entre velocidad y ratio; validar con datos representativos. El formato de entrada puede ser gzip aunque el almacenamiento interno use otro códec.

Los segmentos deben tener manifiesto, checksum y mapa de referencias para recuperar muestras sin descomprimir todo el histórico. Publicación atómica y recuperación tras caída: no confirmar el cursor hasta que los bytes y su referencia sean duraderos; detectar y recuperar escrituras parciales y segmentos huérfanos. La compresión de un segmento no invalida IDs ni referencias de evidencia.

Mantener búsqueda rápida sobre metadatos y texto reciente con presupuesto propio. Las búsquedas de texto en archivo frío descomprimen segmentos relevantes de forma acotada y muestran progreso. No duplicar indefinidamente todo el texto descomprimido en un índice que elimine el ahorro conseguido.

Retención configurable globalmente y por máquina/fuente: edad, bytes reales en disco, reserva de espacio libre y límites de eventos pendientes. Separar duración de originales, muestras de evidencia de problemas, metadatos e informes agregados. Si caduca un original, indicar qué evidencia sigue disponible y cuál falta; no conservar referencias que aparenten acceso completo.

Priorizar análisis de pendientes antes de caducarlos, con reserva acotada; si no cabe más información, aplicar una política explícita y mostrar pérdidas. La cola no puede eludir para siempre el límite de disco. Incluir base de datos, índices, muestras, segmentos temporales y compactación en el presupuesto y en la métrica de tamaño real.

El ahorro es medido, no una promesa del 90%: mostrar bytes originales, bytes comprimidos, sobrecarga y porcentaje efectivo. La compresión de disco **no reduce los tokens** del texto que se envía descomprimido al modelo.

## Primera versión del panel

Alcance: una instancia en un equipo Linux, un usuario local y varias máquinas de origen desde la primera versión, mediante fuentes locales, carpetas/archivos importados y el piloto de recepción continua. El administrador puede abrir el panel desde otro equipo mediante un túnel al servicio local; no se presupone escritorio en el mini-PC. Sin acceso público al panel ni administración remota de flotas.

- **Resumen global y por máquina:** problemas abiertos/nuevos; última revisión completada; fuentes legibles; retraso de cola y de recepción; estado del modelo y avisos fallidos. Distinguir sin hallazgos, sin datos y sin análisis.
- **Máquinas y fuentes:** alta local/importada, ficha de máquina, archivos/carpetas asociadas, descubrimiento, muestras de parsing y estado de rotación/importación. Selector global de máquina, incluyendo la local aunque sea la única.
- **Problemas:** lista filtrable por gravedad, servicio, fecha y estado; primera/última aparición, número de repeticiones y cambios de gravedad.
- **Detalle:** qué sucede, por qué puede importar, evidencia original con fecha/fuente, explicaciones alternativas, incertidumbre y siguientes comprobaciones. Acciones: copiar prompt, preguntar al asistente, marcar resuelto, silenciar y no notificar este tipo de problema.
- **Histórico:** eventos recogidos, problemas, revisiones, supresiones y cambios de configuración. Retención por días y tamaño; búsqueda y exportación. Mostrar cuándo la evidencia original ha caducado.
- **Estadísticas:** volumen, almacenamiento, cobertura, tokens, duración y problemas por máquina/fuente/período; filtros por tipo de trabajo, incluido chat.
- **Asistente:** conversación desde una máquina, fuente o problema; contexto seleccionado y filtros propuestos con vista previa.
- **Ajustes:** fuentes, proveedor/modelo, frecuencia, recursos, sensibilidad, notificaciones, reglas y retención/compresión. Probar la configuración con datos sintéticos de forma explícita.

El monitor funciona con el navegador cerrado. Una notificación de escritorio puede abrir el detalle si el destino ofrece esa capacidad; el panel conserva siempre el acceso al problema. El alta distingue sesión de escritorio local, mini-PC sin escritorio y navegador en otro equipo, según las decisiones de despliegue de la auditoría siguiente. El panel escucha en loopback; usa protección de sesión y de peticiones mutables, valida Host/Origin, escapa logs y salida del modelo y no expone credenciales. El proceso web no debe requerir root. Si el recolector necesita permisos adicionales, separarlos del panel.

## Sensibilidad y feedback

Separar tres controles para que cambiar uno no tenga efectos inesperados:

- **Sensibilidad:** ligero, equilibrado, exhaustivo. Define qué hipótesis débiles o problemas menores se muestran, manteniendo la gravedad ligada al impacto observado. Configuración versionada, con descripción de su comportamiento.
- **Notificaciones:** umbral, agrupación, recordatorios y silencio temporal. Cambiar avisos no borra problemas del histórico.
- **Esfuerzo de análisis:** frecuencia, profundidad, presupuesto y concurrencia. Un modo ligero debe declarar cualquier reducción de cobertura.

### Resolver, no notificar y excluir del análisis

| Acción | Efecto en análisis e histórico | Efecto en avisos |
| --- | --- | --- |
| Resolver | Cierra el problema; una nueva aparición puede reabrirlo | Sigue la política normal si reaparece |
| Silenciar durante un plazo | Se sigue analizando y actualizando | Suspende avisos del alcance elegido hasta la fecha indicada |
| No notificar este tipo de problema | Se sigue analizando, registrando y contando apariciones | Aplica una regla persistente de notificación, revisable y reversible |
| Excluir contenido del análisis | Conserva lo capturado según retención, marca coincidencias como excluidas y evita que entren al LLM | No habrá nuevos hallazgos derivados de ese contenido excluido |

La acción habitual de la ficha será **«No notificar este tipo de problema»**, sustituyendo «ignorar siempre». Definir alcance por máquina, fuente, servicio y firma/patrón, con duración opcional. Mostrar ejemplos coincidentes y qué ocurre si cambia la gravedad. No convertir la ausencia de avisos en clasificación de actividad benigna.

Las exclusiones de análisis se configuran en una pantalla distinta. No eliminan silenciosamente la evidencia del histórico. El usuario puede desactivar la regla y solicitar reanálisis del intervalo todavía retenido. Si posteriormente se añade descarte antes de almacenar, tendrá que ser otra política explícita, con contadores de pérdida; no se introduce implícitamente con los filtros de esta versión.

Las reglas globales son una elección expresa; por defecto se proponen dentro de la máquina/fuente seleccionada. Guardar versión, autor, fecha, motivo, alcance y contadores. La migración de las supresiones antiguas debe mostrar que antes podían saltarse análisis y proponer su conversión a reglas de notificación, sin reinterpretarlas a escondidas.

### Regex y filtros estructurados

Admitir regex excluyentes sobre el campo de mensaje o sobre la línea original, con campo/flags explícitos. Para «excluir esta IP», ofrecer primero un filtro estructurado de IP exacta o red CIDR cuando el parser extraiga el campo. Si solo hay texto, el asistente puede proponer regex con límites adecuados para evitar coincidencias parciales; la UI debe explicar si busca la IP en cualquier parte del texto o como origen/destino.

Cada filtro muestra: máquina/fuente, campo, acción, expresión, ejemplos que coinciden y que no, número/porcentaje de coincidencias sobre el intervalo probado y posibles errores. Aclarar si la vista previa usa una muestra o todo el intervalo; cero coincidencias en una muestra no garantiza impacto cero. Permitir probar positivos/negativos editables y deshacer la activación.

Validar con el mismo motor y semántica de regex en vista previa e ingestión. Usar motor con garantías de tiempo o evaluación aislada con límites efectivos de ejecución, longitud y complejidad; una expresión generada no puede bloquear el recolector. Un filtro inválido o que agota su presupuesto se muestra como fallido y no se interpreta como «excluir todo».

Las exclusiones de análisis se aplican también al preparar contexto histórico y búsquedas del asistente, para no reintroducir contenido excluido por otra vía. Un cambio autorizado de alcance o un reanálisis explícito permite incluirlo de nuevo. Las reglas de solo notificación no afectan a estas consultas.

### Chat integrado y ayuda para filtros

Usar por defecto el proveedor/modelo de análisis, en una sesión separada y con el contexto de la máquina/fuente/problema seleccionado visible. Compartir modelo no significa compartir conversación, preferencias ni permisos automáticamente. Permitir preguntas como «¿qué pasó antes de este fallo?» o «prepara un filtro para estos mensajes de esta IP».

El asistente consulta el histórico mediante herramientas de solo lectura y devuelve respuestas con referencias. Para filtros devuelve una propuesta estructurada: intención, alcance, acción, expresión y ejemplos. La app valida y ejecuta la previsualización sobre los datos; los conteos no los inventa el LLM. Después el usuario puede editar y pulsar **Aplicar** sobre esa propuesta concreta. Pedir una regex en el chat no activa una exclusión por sí solo.

Los logs son datos no confiables también en el chat; no autorizan cambios. No ofrecer shell libre ni permitir que una respuesta del modelo modifique filtros, borre archivos o cambie credenciales directamente. Copiar prompt y abrir el asistente respetan el alcance seleccionado y el tratamiento de datos sensibles.

El chat comparte un planificador de recursos con los análisis, con límites y prioridad para no paralizar el monitor. Registrar sus tokens como chat o asistencia de filtros y asociarlos a la máquina/fuente cuando corresponda. Una consulta global se registra como global o con atribución explícita; nunca se carga entera a cada máquina mencionada.

## Cadencia y capacidad del modelo

Propuesta inicial configurable: captura continua, revisión general cada 5 minutos y cola prioritaria para señales urgentes. Es un punto de partida a validar en este equipo, no un rendimiento demostrado. Presupuestos y reparto de cola por máquina/fuente, sin que un archivo masivo monopolice el modelo. Una única inferencia simultánea al comenzar; si un ciclo tarda más que su intervalo, no lanzar ciclos solapados ilimitados. Mostrar retraso y ajustar tamaño de lote o recursos.

El límite principal es de tokens de la petición completa, no un número fijo de líneas:

`entrada de logs <= contexto efectivo - instrucciones - contexto histórico - reserva de salida/razonamiento - margen`

Distinguir capacidad publicada del modelo y contexto realmente configurado en el servidor. Usar tokenizer compatible cuando esté disponible; en otro caso, estimación conservadora identificada como tal, margen y reducción/reintento ante desbordamiento. Los caracteres son un límite auxiliar, nunca garantía universal de tokens.

Para Ollama, consultar modelo y servidor, verificar el contexto asignado cuando el modelo esté cargado y establecer/verificar la configuración de contexto correspondiente. El cliente actual solo configura el máximo de salida; no presupone que eso limite la entrada. Otros proveedores necesitan adaptadores que traduzcan sus límites de contexto y generación.

Con mucho volumen: particionar por máquina/tiempo/servicio preservando contexto, compactar repeticiones y realizar revisión cruzada de resúmenes con referencias. Marcar eventos como vistos directamente, representados mediante agregación o pendientes/no analizados. Si se alcanza el límite de almacenamiento, registrar la pérdida y avisar; no prometer captura infinita.

En ajustes mostrar capacidad detectada/configurada, tamaño aproximado de lote, duración observada, errores, tokens y cola. La recomendación de modelo se basará en pruebas sintéticas del equipo y un corpus de detección; caber en RAM/VRAM no demuestra calidad de análisis.

## Análisis en dos pasadas con representación compacta

Primera pasada propuesta: construir de forma determinista una representación más pequeña de los eventos, manteniendo los originales comprimidos y referencias estables. El objetivo es evitar gastar tokens en campos repetidos, no eliminar contexto que pueda cambiar el diagnóstico.

- Extraer máquina, fuente, servicio y datos constantes a una cabecera compartida del lote, en vez de repetirlos en cada línea.
- Sustituir timestamps completos repetidos por una fecha/hora base y desplazamientos, o por primera/última aparición y conteos temporales al agrupar. Mantener orden, zona/fiabilidad temporal y separaciones relevantes. No borrar todas las fechas: una ráfaga de errores y los mismos errores repartidos en un mes no significan lo mismo.
- Agrupar repeticiones verificadas dentro de una ventana/máquina/fuente. Conservar cantidad, primeras/últimas apariciones, muestras, diversidad relevante y referencias; las variantes con cambios significativos siguen visibles. No convertir automáticamente IPs, usuarios, códigos de error y rutas diferentes en un único mensaje genérico.
- Mantener mensajes nuevos y contexto de secuencias aunque no contengan palabras clave. No usar una regex global que quite números/timestamps del cuerpo sin un parser que conozca su función.
- Medir tokens del lote resultante frente al original con el tokenizer disponible o una estimación identificada; el ahorro depende del formato. Esta compactación es diferente de comprimir bytes para disco o red.

Ejemplo conceptual para la primera pasada:

```text
Máquina: servidor-a | fuente: aplicación | ventana: 10:00–10:05 UTC
G17 | 420 apariciones | primera 10:01:02 | última 10:01:18
Mensaje: connection pool exhausted
Referencias: G17 resuelve al conjunto concreto de eventos originales
E93 | +80 s | Mensaje: recovery attempt failed, code=42
```

La aplicación genera IDs y conteos; el modelo no los inventa. Guardar versión de la transformación, eventos representados y límites/muestras aplicados. La cobertura distingue revisión de originales, revisión de representación compacta y eventos no seleccionados; nunca atribuir lectura literal de 420 eventos por haber visto una fila resumida.

Segunda pasada: cuando aparezca un candidato o haga falta aclarar una secuencia, resolver sus IDs contra el histórico, traer muestras originales y eventos vecinos por máquina/servicio/tiempo, con fechas y campos completos. El modelo amplía o descarta la hipótesis con evidencia referenciada. Evitar búsquedas vagas por coincidencia de texto como único vínculo entre las dos pasadas.

La selección de primera pasada condiciona lo que puede descubrir la segunda: no garantizar que recupere un problema cuya señal se eliminó o cuyo evento no entró. Evaluar la representación compacta frente a originales en un corpus con errores aislados, ráfagas, secuencias y actividad legítima. Si el original caducó, la segunda pasada muestra evidencia incompleta; no reconstruye datos inexistentes.

Ambas pasadas comparten el presupuesto: reservar capacidad configurable para ampliar candidatos, con máximo de consultas y contexto. Si se agota la reserva, registrar candidato pendiente de ampliar; una alerta preliminar debe indicar que la investigación no ha terminado. Ninguna ampliación elude exclusiones de análisis ni el alcance autorizado de máquina/fuente.

## Cuando el LLM no alcanza el ritmo de entrada

La captura/compresión debe ser independiente de la inferencia. Almacenamiento y contrapresión resuelven ráfagas o interrupciones acotadas; no solucionan un déficit permanente de capacidad. La medida principal combina tokens de entrada/salida, duración real de las llamadas y complejidad de tareas, no solo líneas por minuto.

Si se intentara poner todo el trabajo en cola, para trabajo comparable una tasa de entrada λ superior a la capacidad efectiva μ haría crecer el pendiente aproximadamente `(λ - μ) × tiempo`. Ejemplo ilustrativo con eventos de tamaño/coste parecido: entran 1.000/min y se revisan 200/min; quedan 800/min adicionales. Una cola de disco retrasa la saturación, pero no cambia esa diferencia; por ello la política elegida abajo limita el trabajo admitido a análisis y registra el resto como no analizado. La proyección de espacio real debe usar compresión observada, nuevos datos, retención, temporales e índices: terminar un análisis no libera disco mientras su histórico se conserve.

### Política preferida: presupuesto fijo y cobertura declarada

Ante sobrecarga, la política preferida por el usuario es **avisar y analizar solo el trabajo que cabe**, ofreciendo ayuda para reducir información repetida. No crear una deuda ilimitada de análisis como comportamiento normal. Presupuesto configurable por ciclo en tokens/tiempo/peticiones, repartido entre primera pasada, investigación y recuperación opcional; límite global y cuotas por máquina/fuente. Un máximo de líneas es un tope adicional, no una garantía de coste.

1. **Compactar antes de seleccionar:** aplicar la representación anterior y calcular cuánto cabe. Priorizar novedades y señales relevantes, reservando una parte para mensajes generales y distintas máquinas/fuentes. No tomar siempre las primeras N líneas, porque excluiría de forma sistemática lo que llegue al final o desde fuentes menos activas. La selección/muestra queda registrada y es reproducible.
2. **Avisar de déficit sostenido:** calcular demanda tras compactación y capacidad observada en varias ventanas; umbral y período configurables para no avisar por cada pico. Crear un único problema operativo actualizable y notificar sus cambios/recuperación. Incluir entrada, representación compacta, trabajo revisado, no seleccionado, retraso y causas; evitar un porcentaje que equipare filas compactadas con originales leídos.
3. **Acotar pendientes:** mantener una ventana breve de recuperación con cuota explícita. Lo que no se selecciona pasa a **no analizado por límite de capacidad**; no permanece para siempre en cola ni se marca como benigno. Conservar originales según retención para reanálisis manual o recuperación automática opcional dentro del presupuesto, sin prometer que ocurrirá antes de caducar. Con LLM caído la captura también continúa solo dentro de sus cuotas, con estado operativo visible.
4. **Sugerir reducciones concretas:** presentar las fuentes y patrones que más volumen/tokens representan, repeticiones compactables y filtros propuestos con muestras de coincidencias/no coincidencias y ahorro estimado. Distinguir compactar, no notificar y excluir del análisis: solo las opciones que reduzcan entrada/trabajo ahorran tokens. Aplicar exclusiones requiere la acción explícita del usuario sobre la propuesta; sobrecarga no autoriza activar filtros nuevos automáticamente.
5. **Ajustar capacidad si hace falta:** ofrecer un modelo más rápido evaluado, ajuste de contexto/salida o más recursos. Pausar importaciones voluntarias y limitar chat/reanálisis antes de perjudicar la revisión habitual. Aumentar concurrencia únicamente si mejora rendimiento medido dentro del límite de memoria.
6. **Disco cerca del límite:** es una política diferente del límite del LLM. Purgar datos con retención vencida y frenar recepción para usar la reserva remota; avisar antes de agotarla. Cuando ambas reservas se agotan, aplicar la política configurada de rechazo/caducidad/descarte con contadores y rangos afectados. Analizar menos no implica que deje de crecer el histórico recibido.

La UI muestra por ventana eventos recibidos, representados en primera pasada, originales consultados en segunda, excluidos por regla, no analizados por capacidad y pendientes acotados. Primera/segunda pasada pueden cubrir los mismos eventos: mostrar sus intersecciones o dimensiones separadas sin sumar dos veces el total. Marcar la vuelta a capacidad normal sin ocultar huecos históricos.

Separar saturación de **captura** (el receptor no guarda al ritmo de red), **disco** (retención/cola ocupan la cuota) e **inferencia** (hay datos duraderos pendientes). Cada caso tiene causas y remedios distintos. Ampliar disco ayuda a la reserva; comprimir ayuda al disco; ninguno aumenta automáticamente los tokens por segundo del modelo.

No intentar resolver sobrecarga cambiando únicamente de «cada 5 minutos» a «cada hora»: eso cambia latencia y tamaño de ventana, no el volumen diario a revisar. Los efectos de una compresión semántica más agresiva o un modelo más pequeño se deben evaluar en el corpus de detección.

## Estadísticas y contabilidad del trabajo

Dimensiones: período, máquina, fuente lógica, archivo/generación, modelo y tipo de tarea (análisis inicial, investigación, reanálisis, chat, ayuda de filtros, diagnóstico). Mostrar totales globales y detalle, con rangos temporales definidos: trabajo medido por fecha de recepción/ejecución y actividad del log por fecha del evento. Una importación antigua consume recursos hoy.

| Métrica | Definición |
| --- | --- |
| Bytes recibidos/leídos | Bytes de entrada física, incluyendo comprimidos; separar nuevas entregas de relecturas/reintentos |
| Volumen lógico | Bytes descomprimidos y eventos únicos incorporados; GB de texto lógico no equivale a GB de disco |
| Cobertura | Eventos incorporados, parseados/no interpretados, excluidos por regla, no analizados por capacidad, pendientes acotados, fallidos, vistos como originales o representados por compactación; contar eventos únicos y pasadas de análisis por separado |
| Compactación | Tokens/bytes antes y después, eventos/grupos representados, muestras omitidas, versión de transformación y ahorro medido o estimado; separar del ratio de compresión en disco |
| Datos enviados al modelo | Bytes/caracteres y tokens de entrada por petición, incluyendo contexto repetido; no presentarlos como volumen único recogido |
| Tokens | Entrada y salida reportadas por proveedor; caché/razonamiento cuando estén disponibles y con semántica documentada |
| Trabajo | Peticiones, reintentos, fallos, duración, rendimiento, tasas de entrada/salida, pendiente más antiguo y retraso de cola; separar captura, descompresión e inferencia |
| Reserva de recepción | Ocupación/cuota del receptor y emisor cuando sea observable, estado de confirmaciones/reenvíos, huecos, previsión de saturación con hipótesis visibles |
| Almacenamiento | Segmentos activos/comprimidos, base, índices, evidencia, temporales y total real; ratio de compresión y cuota disponible |
| Resultados | Problemas nuevos/reabiertos/resueltos, repeticiones, cambios de gravedad, avisos enviados/fallidos/silenciados y coincidencias de reglas |

Registrar un libro de peticiones y contribuciones, con ID idempotente del trabajo y un ID distinto para cada intento. Los reintentos consumen recursos aunque no generen un problema nuevo; contabilizarlos sin duplicar eventos únicos. Conservar agregados de consumo tras caducar originales, indicando la retención de cada nivel de detalle.

Ollama expone `prompt_eval_count`, `eval_count` y duraciones en la respuesta de chat. Guardar esos valores reportados, además del modelo/configuración usados. Si el proveedor no da uso o una llamada falla antes de reportarlo, registrar **desconocido** o **estimado** con procedencia; nunca reemplazarlo por un cero que parezca medido.

Para atribuir tokens por fuente/archivo, guardar las contribuciones al prompt y la política de reparto. En lotes de una fuente, el consumo total es directamente atribuible a ella; en lotes mixtos, los tokens de entrada pueden estimarse por fragmento y la salida/instrucciones compartidas requieren reparto explícito o una categoría compartida. El proveedor normalmente informa el total de la petición, no el gasto exacto causado por cada línea. Los totales de todas las atribuciones más el consumo compartido deben reconciliar con el total medido, sin contar cada llamada varias veces.

No sumar tokens cacheados o de razonamiento por segunda vez si el proveedor ya los incluye en entrada/salida. Las métricas se almacenan con su definición/proveedor. Coste monetario solo cuando se conozcan tarifas configuradas y fecha, marcado como estimación; inferencia local muestra tiempo/recursos, no un coste eléctrico inventado.

## Copiar prompt

Crear un texto autocontenido, legible y revisable antes de copiar:

- Máquina de origen, fuentes, sistema y versiones relevantes que se hayan recogido, sin inventar datos ausentes ni confundirlos con el mini-PC recolector.
- Problema, impacto aparente, primera y última aparición, frecuencia y estado.
- Muestras originales delimitadas como datos no confiables, con tiempos y fuentes.
- Contexto relacionado y referencias; distinguir observado, inferido y desconocido.
- Comprobaciones ya realizadas y resultados, únicamente si constan.
- Petición de diagnóstico, comprobaciones y soluciones con sus efectos y forma de revertirlas.

Previsualizar y ocultar credenciales; permitir anonimizar identificadores de forma consistente. Copiar no envía información a ningún servicio. Para contexto demasiado grande, ofrecer un prompt resumido y un archivo adjunto; no afirmar que todo cabe en cualquier LLM.

## Auditoría del plan: huecos que deben cerrarse antes de darlo por implementable

La visión está definida; faltaba concretar utilidad medible, despliegue sin escritorio y contratos entre captura/análisis/avisos. Estas son decisiones de diseño y criterios de entrega, no funcionalidades verificadas del prototipo.

### Utilidad real antes de ampliar infraestructura

El primer experimento debe responder «¿encuentra problemas útiles con el modelo y equipo previstos?». Preparar un corpus pequeño separado de los ejemplos de prompts: errores aislados, ráfagas, fallos encadenados entre servicios, señales de seguridad sin keywords, actividad legítima, registros tardíos y prompt injection. Etiquetar hallazgos esperados y evidencia; comparar reglas actuales, LLM con originales y LLM con representación compacta. Un evento puede apoyar varios hallazgos y un fallo puede requerir varios eventos.

Medir por problema precisión/recobrado, falsos avisos por máquina/día del corpus, omisiones por compactación/selección, latencia y consumo. La confianza que declara el LLM no es una probabilidad calibrada. El conjunto de evaluación debe reservar casos no usados para ajustar prompts; las referencias válidas por sí solas no demuestran que la interpretación sea correcta.

Registrar hardware real (RAM, CPU y GPU/VRAM si hay), modelo/revisión, contexto efectivo, versiones y carga concurrente. Una prueba sintética de conexión no sirve como benchmark. La matriz inicial de sistemas soportados, cifras objetivo y modelo recomendado se publican a partir de esa prueba; no prometer todas las distribuciones, un modelo óptimo o un rendimiento por nombre de mini-PC. Los objetivos mínimos de calidad/latencia/cobertura se fijan antes de ajustar repetidamente contra el corpus, y los resultados se reportan aunque no se alcancen.

### Contrato de resultados, problemas y cambios de configuración

El contrato actual de un veredicto por incidente es insuficiente para ventanas generales. La respuesta de primera pasada debe admitir **cero, uno o varios hallazgos**, cada uno con referencias, categoría, gravedad, hechos, hipótesis y necesidad de ampliación. Separar resultado vacío válido, respuesta inválida/truncada, fallo del proveedor y trabajo parcialmente revisado. Un lote con dos problemas no puede quedar reducido a una sola explicación.

La clave persistente de problema la controla la aplicación e incluye máquina y atributos relevantes; el título redactado por el LLM no es su identidad. Conservar apariciones y revisiones de diagnóstico/gravedad sin sobrescribir el historial. Las relaciones entre problemas se pueden proponer, pero no mezclar máquinas o causas distintas solo porque los textos se parezcan. Marcar resuelto no demuestra reparación observada, y la ausencia de nuevos logs no cierra problemas automáticamente; diferenciar feedback de falsa alarma, resuelto por usuario y reaparecido.

Cada trabajo conserva la revisión de modelo (digest/versión cuando exista), prompt, parser/compactador, filtros, presupuesto y configuración usados. Cambiar modelo, sensibilidad o reglas se aplica al trabajo nuevo; reanalizar históricos es una acción explícita con rango/coste estimado y consumo separado. Guardar el nuevo análisis como revisión y evitar volver a anunciar como nuevos todos los problemas antiguos. Resolver precedencia de ajustes con un valor efectivo visible (global → máquina → fuente cuando sea aplicable); no dejar conflictos de filtros a interpretación del LLM.

Reintentos acotados, espera progresiva y suspensión temporal ante proveedor caído. Recuperar trabajos en curso abandonados tras reinicio con ID estable e intentos separados. Persistencia idempotente de resultados no garantiza que el proveedor ejecute exactamente una llamada: tras un timeout/corte una inferencia podría haberse ejecutado sin respuesta; conservar consumo desconocido y contabilizar reintentos sin prometer cero gasto duplicado.

### Dónde se abre el panel y dónde se reciben avisos

El mini-PC puede no tener escritorio. Las notificaciones de escritorio dependen de una sesión y servicio de notificaciones disponible; no aparecen automáticamente en el portátil desde el que se abre la web. Tampoco debe prometerse un clic funcional en todos los servidores de notificaciones.

Primera entrega: panel local accesible también por túnel SSH desde el navegador del administrador; origen/dirección de acceso configurados y enlaces que funcionen para ese acceso. En modo sin escritorio, elegir y probar un canal existente configurado por el usuario para avisos con el navegador cerrado. Un cliente de escritorio remoto o notificaciones web en segundo plano serían capacidades específicas posteriores, no efectos implícitos del panel. Explicar en el alta si solo existe histórico y no hay destino de aviso operativo.

Crear registro de entrega por problema/cambio/canal, persistido antes de intentar enviar. Reintentar con límites y controlar tormentas. Distinguir pendiente, aceptado por canal, fallido y resultado desconocido; aceptado no implica visto por una persona. Usar idempotencia si el destino la admite; tras timeout, no garantizar entrega exactamente una vez en canales que no la soporten. Registrar intentos y evitar duplicados internos al reanudar.

### Canales comprometidos: todos configurables desde el portal

Requisito del usuario: incluir todas las opciones de notificación que podamos implementar de nuestro lado y permitir configurarlas desde el portal, sin editar YAML ni código. Se incluyen Sistema, Telegram, Slack, Discord, Hermes, n8n y Webhook genérico; conservar también salida local a archivo como opción avanzada. Todos los conectores forman parte de la entrega inicial del portal; activarlos y usar n8n/Hermes es opcional. Su funcionamiento externo depende de las credenciales, permisos, conectividad y servicios del usuario. Un fallo de n8n/Hermes no debe detener captura ni análisis.

La UI permite varios destinos: **Sistema** (sesión de escritorio disponible), **Remotos** (Telegram, Slack, Discord, Hermes, n8n o Webhook genérico) y **Archivo local** en opciones avanzadas. Cada destino tiene nombre, alcance por máquina/fuente, umbral/tipos de evento, credenciales ocultas, previsualización y prueba explícita. «No notificar» se evalúa antes de entregar; las reglas y el histórico principales permanecen en LogSentinel aunque un intermediario tenga filtros adicionales.

| Destino | Configuración inicial | Estado del prototipo |
| --- | --- | --- |
| Sistema | Sesión local y umbral | Conector existente; comprobar disponibilidad real y acciones |
| Telegram directo | Token de bot y chat de destino | Conector existente; no necesita n8n ni un endpoint público para enviar |
| Slack directo | Incoming webhook de la app/canal autorizado | Conector existente |
| Discord directo | URL de webhook del canal | Conector existente |
| Hermes Agent de Nous, si es el Hermes del usuario | URL de ruta y secreto de firma; canales configurados en Hermes | Falta adaptar firma y respuesta; no basta el webhook genérico actual |
| n8n | URL de webhook del flujo, autenticación y plantilla de ejemplo importable | Reutiliza transporte webhook; falta asistente y contrato de entrega |
| Webhook genérico | URL, autenticación/cabeceras y política de contenido | POST JSON existente; falta contrato versionado y seguimiento de entregas |
| Archivo local, avanzado | Ruta permitida, formato y retención de la salida | Conector existente; diferenciar de base de datos/histórico y evitar doble ingestión |

#### Gestión completa desde Ajustes → Notificaciones

- Crear, editar, activar/desactivar y eliminar destinos; varias instancias del mismo tipo (por ejemplo dos chats de Telegram). Identificadores estables por destino, no un único bloque fijo por proveedor. Migrar los destinos actuales sin perder configuración y sin enviarlos de nuevo durante la migración.
- Formulario específico por conector con ayuda de configuración externa y campos pertinentes: URL, bot/canal/chat, secreto, autenticación/cabeceras o ruta local. Validación del servidor; las credenciales se guardan del lado del servidor y los envíos se realizan desde allí. Al editar, mostrar que un secreto existe y permitir reemplazarlo o borrarlo sin devolverlo en texto claro al navegador.
- Configurar máquinas/fuentes, severidad mínima, tipos de cambio, agrupación/límites de avisos y contenido permitido. Previsualizar el mensaje sin enviar y realizar **Enviar prueba** de forma explícita, con estado por destino. Guardar o cambiar ajustes no envía una prueba automáticamente.
- Consultar última entrega, errores, resultado desconocido, aceptación por intermediario/destino final cuando sea demostrable e historial de intentos. Reintentar de forma explícita y acotada. Mostrar qué requisito externo falta sin declarar el conector operativo por haber guardado una URL.
- Persistir ajustes entre reinicios y aplicar cambios sin reiniciar el monitor. Mantener auditoría; al desactivar/eliminar un destino cancelar los envíos pendientes que aún no hayan empezado y señalar que un envío ya aceptado o en curso podría completarse. No reenviar históricos al volver a activarlo sin elección explícita.
- Para n8n, ofrecer plantilla de flujo y ejemplo del evento; para Hermes, ejemplo de ruta compatible. Son ayudas para la configuración externa: no instalar, crear bots/apps, conceder permisos ni modificar esos servicios automáticamente. Todas las opciones que pertenecen a LogSentinel sí se gestionan desde el portal.

Hermes se trata aquí como **Hermes Agent de Nous**, pendiente de verificar versión/instancia del usuario. Su documentación ofrece rutas webhook autenticadas y `deliver_only: true` para reenviar a un canal sin ejecutar el agente. Proponer ese modo para avisos. La firma V2 documentada usa timestamp y cuerpo; nuestro adaptador tendrá que generarla en cada intento. Mantener ID de entrega estable para reintentos y comprobar estados de respuesta, no solo HTTP 200. Solicitar análisis a Hermes es otro modo explícito, con presupuesto y capacidades restringidas; no activarlo implícitamente para cada notificación. Verificar compatibilidad con la versión instalada.

Flujo opcional n8n: **evento de LogSentinel → webhook autenticado → selección de destino/transformación → Telegram, Slack o Hermes**. Documentar una plantilla mínima de aviso, sin nodos de remediación automática. Elegir una ruta por destino para evitar enviar la misma alerta directamente y a través del flujo sin intención. Un 2xx del intermediario solo demuestra aceptación según su contrato; sin confirmación posterior no implica entrega final al chat.

Definir payload versionado pequeño: ID de entrega, tipo de cambio, ID/revisión de problema, máquina/fuentes, gravedad, resumen, conteo, fechas y enlace de detalle cuando sea accesible al destinatario. Originales de logs fuera del envío por defecto; muestras solo con política de salida explícita. La configuración actual del webhook incluye muestras crudas y debe ajustarse. Los límites de tamaño/formato y errores/reintentos son específicos de cada proveedor; persistir estado por destino y respetar sus señales de rate limit.

El conector Telegram actual todavía anuncia `dismiss --always`; sustituir ese texto por la acción de «no notificar» en el recorrido nuevo. Enviar avisos y conversar/controlar la app desde Telegram/Slack son capacidades distintas: la primera entra inicialmente; comandos entrantes y botones que cambien reglas requieren identidad/autorización y un contrato posterior. El chat del panel sigue disponible independientemente.

### Privacidad en todas las salidas y procedencia

La ocultación de secretos no debe limitarse a «Copiar prompt». Preparar una política de salida por máquina/fuente/destino para primera y segunda pasada, chat, resúmenes, notificaciones y exportaciones. Mostrar si cada destino es local o remoto; un fallo local nunca activa envío remoto de forma silenciosa. Ocultar credenciales reconocidas antes de construir peticiones/avisos y probarlo con secretos sintéticos; reconocer que una detección genérica no descubre todos los secretos.

Mantener identificadores pseudonimizados consistentes dentro del contexto necesario cuando se solicite anonimización, sin perder correlación. Proteger originales y claves con permisos adecuados y evitar volcarlos en trazas de depuración, configuración visible o respuestas de API. El tratamiento de datos almacenados y el de datos enviados son políticas distintas: no prometer que «no enviado» significa «no guardado» ni lo contrario.

Vincular credencial del emisor a máquinas/fuentes autorizadas; los campos del payload no conceden permiso para escribir como otra máquina. Consultas del chat, búsqueda y exportación aplican el mismo alcance. Logs/prompt injection no crean reglas, destinos de red ni permisos. No seguir automáticamente URLs sugeridas por logs/modelo ni ofrecer consultas SQL arbitrarias como herramienta de investigación.

### Fuentes defectuosas y salud del propio monitor

Distinguir fuente silenciosa de fuente desconectada cuando haya heartbeat/estado del conector; sin esa evidencia, mostrar «no se reciben datos» sin diagnosticar caída del equipo. Registrar cambios de formato, porcentaje no interpretado, reloj adelantado/atrasado y eventos fuera de orden. Ventanas basadas en recepción para admisión y fecha de evento para investigación, con tolerancia temporal explícita y sin forzar cronologías desconocidas.

Límites para una sola línea/evento, acumulación multilínea, número de fuentes abiertas, consultas y reconstrucción de contexto. Un mensaje gigante, un parser fallido o una fuente ruidosa no bloquean el resto; lo limitado queda contado y con estado de evidencia parcial. Un parser que no entiende el formato puede conservar texto crudo con metadatos desconocidos y seguir la política de análisis, nunca declararlo vacío/benigno.

Los fallos operativos (fuente inaccesible, cola saturada, disco bajo, LLM caído) se detectan sin pedir al LLM que los diagnostique y tienen canal/estado propios. Separar eventos internos generados por el monitor de logs de entrada para evitar recursión de alertas; hacerlo por procedencia controlada, no por una palabra que cualquier emisor pueda imitar. Un proceso totalmente caído no puede avisar por sí mismo: supervisor con reinicio y registro de salida; detección desde fuera queda identificada si se añade un supervisor externo.

### Instalación, actualización y recuperación

Paquete e instrucciones sin rutas personales, versiones de dependencias reproducibles y CI en la matriz Python/Linux publicada. Instalación con usuario/propiedad correctos, arranque automático y diagnóstico de permisos; desinstalar conserva datos por defecto y distingue desinstalación de borrado. Definir qué capacidades requieren componentes del sistema o un modelo descargado; el alta no debe acabar en un monitor aparentemente sano sin ellos.

Copia/restauración coherente de configuración, metadatos, reglas, trabajos y segmentos referenciados. SQLite tiene mecanismos de copia consistente, pero la copia de la base no incluye por sí misma los segmentos externos: diseñar un manifiesto/punto coherente o una pausa controlada de captura, manteniendo custodia en el emisor. Separar copia de claves y contenido sensible con elección explícita. Restaurar en un directorio limpio y verificar referencias, cursores, problemas y reglas antes de darlo por probado.

Migraciones versionadas y ensayadas sobre copias, chequeo de espacio, copia recuperable y procedimiento de reversión compatible con cambios de esquema. No basta con reinstalar una versión antigua sobre una base que ya cambió. Impedir dos instancias de captura sobre el mismo estado sin coordinación. Conservación histórica de métricas no debe impedir borrar los datos de una máquina cuando el usuario lo solicite; explicar qué se elimina o anonimiza y qué agregado permanece.

### Decisiones todavía abiertas y alcance de la entrega

| Decisión | Cómo cerrarla |
| --- | --- |
| Hardware/modelo y presupuesto inicial | Benchmark del equipo objetivo y evaluación de utilidad; 5 minutos/32 MiB/60 segundos siguen siendo ejemplos |
| Destino de avisos en el mini-PC sin escritorio | Elegir un canal existente durante el alta y probar recepción; no presuponer escritorio remoto |
| Conector remoto y garantías de custodia | Piloto acotado con versión/configuración identificadas y pruebas de corte/duplicados antes de adoptar un protocolo propio |
| Representación/almacenamiento e índices | Probar escritura, recuperación, lectura de evidencia comprimida y cuota; reutilizar componentes antes de crear un formato/protocolo complejo |
| Defaults de retención y cobertura reducida | Valores conservadores derivados del volumen/espacio medido, visibles y editables; no prometer retención fija sin cuota |

Primera entrega utilizable corresponde a los hitos 0–3; chat/filtros asistidos siguen comprometidos en la entrega ampliada del hito 4. La evaluación y pruebas de fallos acompañan cada hito. No hace falta terminar todos los conectores y gráficos para ensayar un recorrido local e importado real, ni presentar ese ensayo como producto completo.

## Orden de implementación

0. **Validación de utilidad y decisiones técnicas:** corpus y comparación originales/compactados/reglas; benchmark en hardware objetivo; prueba pequeña de captura/segmentos/recuperación y conector remoto candidato. Elegir matriz soportada y objetivos de calidad/cobertura/latencia antes de desarrollar el panel completo.
1. **Fundamentos para varias máquinas:** máquinas/fuentes/identidades, migración revisable, reparación del cierre y diagnóstico, cursor/generaciones duraderos, libro de trabajos y consumo, contrato de múltiples hallazgos y política de salida de datos. Retirar dependencia funcional del perfil SSH conservando recuperables los datos existentes. Definir desde aquí referencias a segmentos y cuotas; no posponer esos contratos hasta llenar una base de texto.
2. **Captura, importación y piloto remoto fiables:** descubrimiento local y asistente de permisos/modelo, archivos y carpetas asignados a máquinas, rotación/reanudación, importaciones estables y gzip; segmentos con compresión interna y retención acotada. Integrar un emisor/receptor continuo con cola duradera, reconexión y contrato de confirmación probado; comprobar cortes y cambio de segmentos con conexión abierta. Métricas de captura/almacenamiento desde el primer recorrido, no como instrumentación posterior.
3. **Primer producto utilizable:** primera pasada compacta y ampliación por referencias, presupuesto fijo con aviso de cobertura reducida y sugerencias de reducción, revisión general por tokens con reparto entre máquinas, problemas persistentes, panel de máquinas/fuentes/histórico/detalle, copiar prompt y avisos de escritorio. Sensibilidad, cadencia, recursos y «no notificar este tipo»; estadísticas de tokens/volumen/cobertura por máquina y fuente. Incluye vistas global y por máquina aunque solo haya una, entrega registrada de avisos para modo con/sin escritorio (Sistema, Telegram, Slack, Discord, Hermes, n8n, Webhook genérico y Archivo local avanzado, todos configurables desde el portal) y recorrido de instalación/actualización/restauración probado.
4. **Filtros y asistente:** filtros estructurados/regex, previsualización real y reglas versionadas; chat sobre problemas/histórico y generación de propuestas de filtro; presupuesto y consumo separados. Incluir esta fase en la primera versión funcional ampliada solicitada, sin venderla como implementada en el prototipo.
5. **Ampliaciones evaluadas:** más formatos comprimidos (`.zst`, `.xz`), investigación/correlación más rica y despliegue gestionado/más conectores remotos a partir del piloto. Evaluar cada capacidad con corpus etiquetado; los perfiles horarios no vuelven como requisito implícito.

## Criterios de aceptación

- Todos los canales comprometidos se pueden crear/configurar/probar/editar/desactivar desde el portal, sin YAML ni reinicio y con múltiples destinos del mismo tipo. Credenciales no reaparecen en respuestas/API/trazas; la migración conserva destinos y no genera envíos.
- Guardar ajustes no manda mensajes; la prueba requiere acción explícita. Un destino desactivado no inicia trabajos nuevos ni pendientes y la UI identifica entregas ya en curso. Fallo de un destino no bloquea otros ni la captura/análisis.
- Conectores y plantillas n8n/Hermes se validan con endpoints simulados y contratos versionados; las pruebas reales requieren destinos y credenciales configurados por el usuario. Distinguir soporte del conector de disponibilidad/autorización del servicio externo.

- Lote con cero, uno y varios problemas: preserva todos los hallazgos soportados y distingue respuesta vacía válida de inválida, incompleta o trabajo parcial. Cambiar modelo/configuración deja trazabilidad y el reanálisis no recrea masivamente problemas antiguos como nuevos.
- Instalar en un entorno limpio y otro sin escritorio, configurar fuentes/modelo, abrir panel por el acceso previsto y recibir un aviso por un destino realmente disponible. Cerrar el navegador no detiene captura ni los canales independientes.
- Claves sintéticas no salen por prompts, chat, segunda pasada, avisos, API visible ni exportación según la política aplicada; credenciales de una máquina no aceptan eventos atribuidos a otra.
- Restaurar copia coherente de base/segmentos/reglas/configuración; fallar durante una actualización y recuperar la versión/estado soportados. No basta con copiar un archivo SQLite abierto ni revertir solo el código.
- Fuente vacía, formato cambiado, evento gigante, reloj desplazado y proceso LLM caído tienen estados diferenciados; errores internos no producen un bucle de autoalertas.
- Notificación con timeout deja resultado desconocido y reintentos acotados; no simular certeza de entrega o ausencia de duplicados externos donde el canal no la ofrece.

- Bajo sobrecarga se respeta el presupuesto de inferencia, se emite aviso operativo sin tormenta de notificaciones y se registra no analizado por capacidad; la cola de recuperación no crece sin límite ni se activan exclusiones sin acción del usuario.
- La compactación mantiene máquina/fuente, conteos, orden/relaciones temporales y variantes relevantes; una ráfaga y eventos separados temporalmente no se vuelven indistinguibles. IDs/grupos resuelven a originales correctos.
- La segunda pasada recupera contexto referenciado dentro del presupuesto y alcance permitido; evidencia caducada o presupuesto agotado quedan explícitos. Evaluar detecciones perdidas frente a la entrada original.
- La selección no se limita siempre al comienzo del archivo y reserva cobertura para mensajes sin palabras clave y fuentes menos ruidosas; métricas no duplican eventos por pasar por dos análisis.

- Mantener conexión remota abierta durante varios sellados/compresiones: todos los eventos completos enviados quedan recuperables en orden por fuente, sin vincular rotación al fin de una llamada LLM.
- Cortar red, matar emisor/receptor y perder una confirmación después de persistir: se reanuda desde la última custodia confirmada, se identifican reenvíos sin borrar apariciones legítimas y se respetan huecos. Incluir prueba de durabilidad según la configuración real del piloto, sin equiparar un cierre limpio con corte eléctrico.
- Con LLM detenido, la captura continúa hasta las cuotas definidas; receptor/emisor llenos activan contrapresión y política visible sin consumir disco ilimitadamente. Tras recuperar capacidad superior a entrada, el pendiente acotado disminuye; los intervalos no analizados por capacidad mantienen su estado salvo reanálisis efectivo.
- Bajo déficit sostenido la UI informa crecimiento/antigüedad y no dice estar al día; cambiar la cadencia no oculta pendientes. Las prioridades reservan capacidad para otras máquinas, revisión general e investigación; la recuperación histórica opcional respeta su cuota.

- Un mensaje relevante sin palabras clave prefijadas llega al análisis y puede generar un hallazgo.
- Dos máquinas con igual hostname/IP/mensaje no se fusionan; todas las vistas, búsquedas, reglas, evidencias y métricas respetan la máquina/fuente asignada. La migración deja procedencia ambigua sin atribución falsa.
- El alta detecta las fuentes realmente disponibles en entornos Linux representativos; sin journal, con archivos convencionales ausentes o con permisos insuficientes, explica qué falta y permite añadir una fuente. El panel no necesita root.
- Se analiza una carpeta de otro equipo, incluidos archivos rotados/gzip. Renombrar, truncar, comprimir, reemplazar o reiniciar durante lectura tiene resultados comprobables y no oculta pérdidas conocidas.
- Reimportar la misma entrega no duplica apariciones, tokens de inferencia ni avisos innecesariamente; mensajes idénticos en dos posiciones legítimas siguen siendo dos eventos. Las relecturas físicas se registran aparte.
- Una entrega parcial/corrupta y una expansión comprimida excesiva no detienen otras fuentes ni consumen recursos ilimitados.
- Comprimir/rotar almacenamiento interno mantiene referencias recuperables; caída durante sellado/publicación y falta de disco se recuperan sin confirmar bytes no duraderos. Purgar el histórico no toca archivos del productor.
- Todos los eventos capturados tienen estado de cobertura; ningún límite oculta silenciosamente trabajo omitido. Cuotas y retención siguen siendo efectivas ante un LLM caído.
- Una importación grande no bloquea el análisis local ni dispara avisos antiguos como nuevos. Una sola inferencia puede fallar/reintentarse sin perder eventos ni duplicar problemas por el mismo trabajo.
- Modelo ausente, fuente inaccesible, cola atrasada, evidencia caducada y salida inválida se muestran explícitamente. Una respuesta vacía o inválida no demuestra que el equipo esté sano.
- Un hallazgo referencia evidencia existente; repeticiones actualizan el mismo problema cuando corresponde y las diferencias relevantes no se fusionan por un título parecido.
- «No notificar» mantiene análisis e histórico; la exclusión de análisis conserva su estado y conteos. Desactivar una regla no promete recuperar eventos ya caducados.
- Regex/IP exacta se prueban con coincidencias y no coincidencias, IPv4/IPv6 según el modo y direcciones similares; vista previa e ingestión usan igual semántica y límites. Un timeout de regex no significa excluir todo.
- El chat presenta contexto y referencias, propone filtros sin activarlos y no puede ser dirigido por instrucciones insertadas en logs. Aplicar/deshacer una regla tiene auditoría.
- Cada intento de inferencia/chat deja consumo medido, estimado o desconocido explícito. Totales por fuentes/máquinas más compartidos cuadran con el libro de peticiones; reanálisis no infla bytes únicos y uso desconocido no aparece como cero.
- Estadísticas de tamaño distinguen entrada comprimida, texto lógico, disco real y datos enviados al LLM. Verificar ratios sobre corpus real sin fijar un ahorro obligatorio del 90%.
- Copiar prompt reúne contexto de la máquina correcta sin incluir claves configuradas ni ejecutar instrucciones de los logs.
- Tests de pipeline/UI sin red ni notificaciones reales por defecto; pruebas de modelo real separadas y reproducibles. Corpus etiquetado de fallos, seguridad y actividad legítima, separado de ejemplos usados para ajustar prompts: medir detecciones, omisiones, falsos positivos, latencia y coste por perfil.

## Fuera del alcance inicial

Remediación automática, ejecución libre de comandos por el modelo, panel público, múltiples usuarios/roles y despliegue de agentes remotos gestionados. **Varias máquinas mediante importación y un piloto de recepción continua fiable sí están dentro del alcance inicial.** El producto analiza la evidencia de logs disponible: no equivale a un escáner activo de puertos, archivos o vulnerabilidades del equipo.

## Referencias técnicas

- [Contexto efectivo en Ollama](https://docs.ollama.com/context-length) y [contexto de modelos cargados](https://docs.ollama.com/api/ps): fundamentan distinguir capacidad del modelo de asignación en ejecución.
- [Respuesta de chat de Ollama](https://docs.ollama.com/api/chat): campos de uso y duración para instrumentación; la atribución por fuente es una decisión propia del plan.
- [Zstandard](https://facebook.github.io/zstd/): candidato de compresión interna a evaluar; no garantiza un ratio fijo sobre los logs del usuario.
- [Manual de logrotate](https://github.com/logrotate/logrotate/blob/main/logrotate.8.in): referencia para comportamiento de rotación; no se propone cambiar la configuración del productor.

- [Reenvío con rsyslog](https://docs.rsyslog.com/doc/tutorials/reliable_forwarding.html) y [colas y durabilidad](https://docs.rsyslog.com/doc/concepts/queues.html): candidatos para recepción remota, con garantías condicionadas a persistencia/configuración; los contratos de IDs, custodia y cobertura anteriores son requisitos de nuestra integración.

- [Notificaciones de escritorio: diseño y sesión](https://specifications.freedesktop.org/notification/latest/basic-design.html): disponibilidad y acciones dependen del servidor de notificaciones.
- [SQLite Online Backup API](https://sqlite.org/backup.html): copia consistente de base; coherencia con segmentos externos es responsabilidad de la aplicación.

- [Slack incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/), [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage), [Hermes webhooks](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/) y [n8n](https://docs.n8n.io/): opciones de integración, con verificación de versión antes de implementar.
