"use strict";
// Only interface strings go through t(). Log evidence and user content remain verbatim.
const translations = {
  "Ya hay una fuente activa capturando este journal local. Reutilízala o desactívala antes de activar otra.":
    "An enabled source already captures this local journal. Reuse it or disable it before enabling another.",
  "Cobertura y capacidad": "Coverage and capacity",
  "Eventos de evidencia": "Evidence events",
  "Salud del observador": "Observer health",
  "Plazo sin señal del emisor remoto (segundos, 0 desactiva)":
    "Remote heartbeat timeout (seconds, 0 disables)",
  "Umbral crítico (%)": "Critical threshold (%)",
  "Muestras sostenidas para CPU crítica": "Sustained samples for critical CPU",
  "Intervalos sin mediciones antes de avisar":
    "Missing measurement intervals before alerting",
  "Notificar recuperación": "Notify on recovery",
  Apariencia: "Appearance",
  Escritorio: "Desktop",
  Parcial: "Partial",
  Correcto: "Healthy",
  Desactivado: "Disabled",
  "Requiere atención": "Needs attention",
  "Sin datos recientes": "No recent data",
  Iniciando: "Starting",
  Comprobando: "Checking",
  "En cuarentena": "Quarantined",
  "Ayúdame a entender este problema: {title}. Contrasta la hipótesis con sus evidencias y explica qué comprobar a continuación.":
    "Help me understand this problem: {title}. Check the hypothesis against its evidence and explain what to investigate next.",
  Detalle: "Detail",
  Valor: "Value",
  Categoría: "Category",
  "Primera detección": "First detected",
  "Última detección": "Last detected",
  "Fuentes de la evidencia": "Evidence sources",
  "Ver todos los datos del hallazgo": "Show all finding details",
  "{sent} eventos incluidos · {omitted} omitidos · {expired} evidencias caducadas · {bytes}/{budget} bytes de entrada.":
    "{sent} events included · {omitted} omitted · {expired} expired evidence events · {bytes}/{budget} input bytes.",
  "Se han aplicado exclusiones o recortes. Consulta el desglose; los originales retenidos siguen disponibles.":
    "Exclusions or excerpts were applied. Check the breakdown; retained originals remain available.",
  "Desglose de cobertura": "Coverage breakdown",
  "Contexto enviado en esta consulta": "Context sent with this request",
  "Vista previa del contexto que se enviará":
    "Preview of the context to be sent",
  "Evidencias citadas": "Cited evidence",
  "Fragmento enviado al modelo": "Excerpt sent to the model",
  "La respuesta no cita eventos concretos.":
    "The response cites no specific events.",
  "Ver qué recibió el asistente": "See what the assistant received",
  "Investigación guardada. Esperará su turno si el modelo está ocupado; puedes cerrar esta vista.":
    "Investigation saved. It will wait if the model is busy; you can close this view.",
  "Investigar este problema": "Investigate this problem",
  "Minutos antes y después de la evidencia":
    "Minutes before and after the evidence",
  "Buscar más detalles del problema": "Investigate further",
  "El LLM propone términos; se buscan coincidencias en los logs retenidos de esta máquina y el LLM redacta un análisis más profundo. Hasta 2 llamadas, con presupuesto y una búsqueda de hasta 2.000 eventos. La captura continúa.":
    "The LLM suggests terms, the app searches this machine's retained logs, and the LLM writes a deeper analysis. Up to 2 calls with a bounded budget and a search of up to 2,000 events. Capture continues.",
  "Investigaciones guardadas": "Saved investigations",
  "Todavía no has solicitado una investigación profunda.":
    "No deep investigation has been requested yet.",
  "En cola": "Queued",
  "El LLM prepara la búsqueda": "The LLM is planning the search",
  "Buscando en originales retenidos": "Searching retained originals",
  "El LLM analiza las coincidencias": "The LLM is reviewing matches",
  " llamadas al modelo": " model calls",
  "{scanned} eventos examinados · {matched} coincidencias · ventana ±{minutes} minutos.":
    "{scanned} events examined · {matched} matches · window ±{minutes} minutes.",
  "La búsqueda alcanzó su límite; no se examinó toda la ventana.":
    "The search reached its limit; the entire window was not examined.",
  "Ver términos y alcance de búsqueda": "Show search terms and scope",
  "Se muestran {shown} originales de {retained} retenidos; {expired} han caducado.":
    "Showing {shown} of {retained} retained originals; {expired} have expired.",
  "Copiar evento": "Copy event",
  "Ficha de la máquina": "Machine profile",
  "Evolución del hallazgo": "Finding history",
  "Últimas 20 revisiones guardadas. Las investigaciones profundas se conservan aparte y no cambian el hallazgo automáticamente.":
    "Latest 20 saved revisions. Deep investigations are stored separately and do not automatically change the finding.",
  "Detalles del problema": "Problem details",
  "Ver más detalles": "View more details",
  "La búsqueda profunda usa hasta 2 llamadas y una ventana inicial de ±30 minutos. Puedes ajustar la ventana en Ver más detalles.":
    "Deep investigation uses up to 2 calls and an initial ±30 minute window. Adjust the window in View more details.",
  "Preguntar sobre este problema": "Ask about this problem",
  "Ver contexto antes de enviar": "Preview context before sending",
  "Esta conversación incluye el hallazgo seleccionado, la máquina y una muestra de sus evidencias. El contexto se ajusta al modelo y los recortes se muestran.":
    "This conversation includes the selected finding, the machine and a sample of its evidence. Context is fitted to the model and omissions are shown.",
  "El problema no pertenece a esta máquina":
    "Problem does not belong to machine",
  "La pregunta y el problema superan el presupuesto de entrada; acorta la pregunta o aumenta el presupuesto":
    "The question and problem exceed the input budget; shorten the question or increase the budget",
  "La evidencia original ha caducado; no se puede anclar la búsqueda":
    "Original evidence has expired; the search cannot be anchored",
  Idioma: "Language",
  "Tiempo de espera del LLM (segundos)": "LLM timeout (seconds)",
  "Iniciando captura…": "Starting capture…",
  "Captura sin confirmación reciente; revisa las fuentes":
    "Capture has no recent heartbeat; check sources",
  "Último evento recibido: ": "Last event received: ",
  Baja: "Low",
  Media: "Medium",
  Alta: "High",
  Crítica: "Critical",
  Abierto: "Open",
  Resuelto: "Resolved",
  Fallido: "Failed",
  "Reintento pendiente": "Retry pending",
  "En curso": "Running",
  "Resultado desconocido": "Unknown outcome",
  Entregado: "Delivered",
  Cancelado: "Cancelled",
  "Tu observatorio de logs.": "Your log observatory.",
  "Accede con la clave que aparece al iniciar el portal en este equipo.":
    "Use the access key printed when the portal starts on this machine.",
  "Clave de acceso": "Access key",
  "Entrar al portal": "Sign in",
  "OBSERVATORIO LOCAL": "LOCAL OBSERVATORY",
  "Evidencia antes que conclusiones": "Evidence before conclusions",
  "Cerrar sesión": "Sign out",
  Cerrar: "Close",
  "Navegación principal": "Main navigation",
  "MÁQUINAS · LOGS · HALLAZGOS": "MACHINES · LOGS · FINDINGS",
  Ámbito: "Scope",
  "Ayuda con el LLM": "Ask the LLM",
  "Ayuda con el programa": "Help with LogSentinel",
  "Tu pregunta": "Your question",
  "Este chat recibe tu pregunta y un resumen de configuración, sin logs ni credenciales. No cambia ajustes.":
    "This chat receives your question and a configuration summary, without logs or credentials. It cannot change settings.",
  Resumen: "Overview",
  Máquinas: "Machines",
  Fuentes: "Sources",
  Problemas: "Problems",
  Histórico: "History",
  Notificaciones: "Notifications",
  Reglas: "Rules",
  "Modelo y análisis": "Model and analysis",
  Asistente: "Log assistant",
  Actividad: "Activity",
  Copias: "Backups",
  "Configuración guiada": "Setup wizard",
  Sistema: "System",
  "Webhook genérico": "Generic webhook",
  "Archivo local": "Local file",
  "Introduce la clave de acceso": "Enter your access key",
  "Todavía no hay registros": "No records yet",
  "Los datos aparecerán aquí cuando configures fuentes y ejecutes el análisis.":
    "Data will appear when you configure sources and enable analysis.",
  "Todas las máquinas": "All machines",
  "Eventos retenidos": "Retained events",
  "Originales recuperables": "Recoverable originals",
  "Problemas abiertos": "Open problems",
  "Basados en evidencia": "Based on evidence",
  "Sin revisar por capacidad": "Unreviewed: capacity limit",
  "Cobertura reducida explícita": "Coverage gaps are recorded",
  "Tokens reportados": "Reported tokens",
  " llamadas con uso desconocido": " calls with unknown usage",
  "Estado del observatorio": "Observatory status",
  "La captura y el análisis funcionan aunque cierres el navegador. Consulta arriba la próxima ejecución y el estado real de las fuentes.":
    "Capture and analysis keep running when you close the browser. Check the next run and source health above.",
  "Analizar ahora": "Analyze now",
  "Analizando los eventos admitidos por el presupuesto…":
    "Analyzing events within the configured budget…",
  "Ciclo terminado: ": "Cycle finished: ",
  " llamadas. Consulta cobertura y actividad.":
    " calls. Check coverage and activity.",
  "Probar conexión del LLM": "Test LLM connection",
  "Probando el LLM con una petición sintética…":
    "Testing the LLM with a synthetic request…",
  "tokens no reportados": "tokens not reported",
  "LLM conectado: {model} · {seconds} s · {tokens}.":
    "LLM connected: {model} · {seconds} s · {tokens}.",
  "Detectar fuentes locales": "Detect local sources",
  "Almacenamiento y cobertura": "Storage and coverage",
  " en disco · ": " on disk · ",
  " en bloques lógicos · ": " in logical blocks · ",
  " comprimidos": " compressed",
  "Estado de eventos": "Event status",
  Cantidad: "Count",
  "Uso por fuente": "Usage by source",
  "Tokens repartidos proporcionalmente al tamaño del contexto enviado; son una atribución estimada, no mediciones separadas del proveedor.":
    "Tokens are allocated in proportion to the context size sent per source. This is an estimate, not separate provider measurements.",
  Fuente: "Source",
  "Eventos recibidos": "Received events",
  "Volumen original": "Original volume",
  "Tokens atribuidos": "Allocated tokens",
  "Llamadas sin uso completo": "Calls with incomplete usage data",
  "Empieza con este equipo": "Start with this machine",
  "Detecta el sistema y crea su ficha. También puedes añadir una máquina cuyos logs se reciben en una carpeta.":
    "Detect this system and create its machine profile. You can also add a machine whose logs arrive in a folder.",
  "Detectar este equipo": "Detect this machine",
  "Detectado: ": "Detected: ",
  ". Archivos: ": ". Files: ",
  disponible: "available",
  ausente: "unavailable",
  " (sin permiso)": " (permission denied)",
  "Identidad y contexto de cada equipo.":
    "Identity and context for each machine.",
  "Archivos, carpetas, journal y recepción continua.":
    "Files, folders, journal and continuous remote ingestion.",
  "Avisos directos y servicios externos. Guardar no envía mensajes.":
    "Direct alerts and external services. Saving does not send a message.",
  "No notificar mantiene el análisis. Excluir evita enviar esas coincidencias al modelo.":
    "Muting keeps analysis enabled. Excluding prevents matching events from being sent to the model.",
  Añadir: "Add",
  Nombre: "Name",
  Tipo: "Type",
  Acciones: "Actions",
  Máquina: "Machine",
  Estado: "Status",
  Editar: "Edit",
  "Leer ahora": "Read now",
  " eventos nuevos. ": " new events. ",
  "Clave de emisor": "Sender key",
  "Guarda esta clave: se muestra una vez": "Save this key: shown once",
  "Reanalizar retenidos": "Reanalyze retained events",
  " eventos programados (máximo ": " events queued (maximum ",
  "Enviar prueba": "Send test",
  Eliminar: "Delete",
  "¿Eliminar esta configuración?": "Delete this configuration?",
  "Sin especificar": "Not specified",
  Activo: "Active",
  Pausado: "Paused",
  "Editar configuración": "Edit configuration",
  "Nueva configuración": "New configuration",
  "Seleccionar máquina": "Select a machine",
  "Este equipo": "This machine",
  "Otro equipo": "Another machine",
  "Hostname declarado": "Declared hostname",
  "Sistema / distribución": "System / distribution",
  "Zona horaria IANA": "IANA timezone",
  "Contexto de la máquina": "Machine context",
  "Tipo de fuente": "Source type",
  Archivo: "File",
  Carpeta: "Folder",
  "Journal local": "Local journal",
  "Recepción remota": "Remote ingestion",
  "Ruta (archivo o carpeta)": "Path (file or folder)",
  "Patrón de archivos en carpeta": "Folder filename pattern",
  "Importar histórico al iniciar": "Import existing history on first read",
  "Agrupar continuaciones con sangría": "Group indented continuation lines",
  "Máximo de bytes por lote de lectura": "Maximum bytes per read batch",
  "Selección para el análisis LLM": "Event selection for LLM analysis",
  "Todas las líneas": "All lines",
  "Prioridad + palabras": "Priority + keywords",
  "Solo palabras disparadoras": "Trigger keywords only",
  "Adaptativa: prioridad + contexto":
    "Priority + keywords (legacy adaptive alias)",
  "Prioridad máxima (0 emergente · 7 debug)":
    "Maximum priority (0 emergency · 7 debug)",
  "Contexto antes/después (minutos)": "Context before/after (minutes)",
  "Palabras disparadoras, una por línea (ignora mayúsculas)":
    "Trigger keywords, one per line (case insensitive)",
  "Los originales se conservan hasta que caducan por retención o cuota. La prioridad es declarada por el emisor, no garantiza seguridad. El contexto usa eventos ya capturados, puede recortarse y no se amplía automáticamente con llegadas futuras.":
    "Originals are retained until retention or quota expires them. Priority is declared by the sender and is not a security guarantee. Context uses already captured events, may be truncated, and is not automatically extended with future arrivals.",
  "Captura activa": "Capture enabled",
  Canal: "Channel",
  "Ámbito de máquina": "Machine scope",
  "Ámbito de fuente": "Source scope",
  Todas: "All",
  "Gravedad mínima": "Minimum severity",
  "URL webhook (vacío conserva la guardada)":
    "Webhook URL (blank keeps saved value)",
  "Token de Telegram (vacío conserva)":
    "Telegram token (blank keeps saved value)",
  "Chat ID de Telegram": "Telegram chat ID",
  "Secreto de firma Hermes (vacío conserva)":
    "Hermes signing secret (blank keeps saved value)",
  "Cabeceras JSON (vacío conserva)": "JSON headers (blank keeps saved value)",
  "Nombre del archivo local (opcional)": "Local filename (optional)",
  "Agrupar avisos durante (segundos)": "Group alerts for (seconds)",
  "Rotar archivo de avisos a (MiB)": "Rotate notification file at (MiB)",
  "Copias comprimidas de avisos": "Compressed notification archives",
  "Destino activo": "Destination enabled",
  "Borrar secretos guardados al guardar": "Clear stored secrets on save",
  "Configura solo los campos de tu canal. Hermes necesita ruta y firma; n8n, URL y autenticación. Claves existentes: ":
    "Configure the fields for your channel. Hermes needs a route and signature; n8n needs a URL and authentication. Configured secrets: ",
  "Plantilla Hermes": "Hermes template",
  "Plantilla n8n": "n8n template",
  Acción: "Action",
  "No notificar": "Mute notifications",
  "Excluir del análisis": "Exclude from analysis",
  Coincidencia: "Match type",
  "Expresión regular": "Regular expression",
  "IP exacta / CIDR": "Exact IP / CIDR",
  "ID de problema": "Problem ID",
  "Expresión / IP / ID": "Expression / IP / ID",
  "Regla activa": "Rule enabled",
  "Caducidad opcional (hora local)": "Optional expiry (local time)",
  "Vista previa de coincidencias": "Preview matches",
  "Vista previa · muestra de ": "Preview · sample of ",
  " eventos, ": " events, ",
  " coincidencias": " matches",
  Guardar: "Save",
  Cancelar: "Cancel",
  "Configuración guardada.": "Configuration saved.",
  "Plantilla para configurar tu servicio externo. Sustituye credenciales y destino; la aplicación no lo activa automáticamente.":
    "Template for your external service. Replace the credentials and destination; the application does not activate it automatically.",
  "Copiar JSON": "Copy JSON",
  "Plantilla ": "Template ",
  "Proveedor, capacidad y política de revisión":
    "Provider, capacity and review policy",
  Proveedor: "Provider",
  "API compatible": "Compatible API",
  "URL del servidor": "Server URL",
  Modelo: "Model",
  "Clave API (vacío conserva)": "API key (blank keeps saved value)",
  "Contexto efectivo configurado": "Configured effective context",
  "Presupuesto de entrada (cota conservadora)":
    "Input budget (conservative bound)",
  "Máximo de salida": "Maximum output tokens",
  "Activar razonamiento prolongado del modelo": "Model reasoning mode",
  "Predeterminado del proveedor": "Provider default",
  "Desactivar (llama.cpp / Qwen)": "Disable (llama.cpp / Qwen)",
  "Activar (servidor compatible)": "Enable (compatible server)",
  "Máximo de llamadas por ciclo": "Maximum calls per cycle",
  "Intervalo entre ciclos (segundos)": "Interval between cycles (seconds)",
  "Eventos admitidos por máquina/ciclo": "Events admitted per machine/cycle",
  Sensibilidad: "Sensitivity",
  Ligera: "Light",
  Equilibrada: "Balanced",
  Exhaustiva: "Thorough",
  "Retención de originales (días)": "Original retention (days)",
  "Cuota de almacenamiento (MiB)": "Storage quota (MiB)",
  "Autorizar enviar contexto al servidor remoto configurado":
    "Allow sending context to the configured remote server",
  "Análisis periódico activo": "Scheduled analysis enabled",
  "Idioma de nuevos hallazgos": "Language for new findings",
  "Consultar modelos y presupuesto": "Check models and budget",
  "Modelo guardado: ": "Saved model: ",
  "Máximo declarado: ": "Reported maximum: ",
  desconocido: "unknown",
  " · Contexto cargado: ": " · Loaded context: ",
  "Modelos disponibles: ": "Available models: ",
  "Usar presupuesto sugerido en el formulario": "Use suggested budget in form",
  "Revisa y guarda los ajustes para aplicarlos.":
    "Review and save the settings to apply them.",
  "Capacidad del modelo": "Model capacity",
  "Guardar ajustes": "Save settings",
  "Probar modelo con datos sintéticos": "Test model with synthetic data",
  "Comprobando modelo…": "Testing model…",
  "Ajustes aplicados.": "Settings applied.",
  "Se reserva espacio para instrucciones y salida. Sin tokenizer compatible, el presupuesto usa bytes UTF-8 como cota conservadora. La prueba de conexión no mide calidad de detección.":
    "Space is reserved for instructions and output. Without a compatible tokenizer, the budget uses UTF-8 bytes as a conservative bound. The connection test does not measure detection quality.",
  "Problemas recientes": "Recent problems",
  Gravedad: "Severity",
  Problema: "Problem",
  Apariciones: "Occurrences",
  "Última vez": "Last seen",
  "Ver evidencia": "View evidence",
  "Qué se ha observado": "What was observed",
  "Hipótesis e incertidumbre": "Hypotheses and uncertainty",
  "Sin ampliación": "No further detail",
  "Siguientes comprobaciones": "Next checks",
  "Revisar evidencia original": "Review original evidence",
  "Copiar prompt": "Copy prompt",
  "Revisa el contexto antes de copiarlo. Los campos de secretos reconocidos se ocultan.":
    "Review the context before copying it. Recognized secret fields are redacted.",
  "Copiar al portapapeles": "Copy to clipboard",
  "Prompt copiado.": "Prompt copied.",
  "Prompt de investigación": "Investigation prompt",
  "Marcar resuelto": "Mark resolved",
  "No notificar este problema": "Mute this problem",
  "Preguntar al asistente": "Ask the assistant",
  "Evidencia retenida": "Retained evidence",
  "fecha desconocida": "unknown date",
  "La evidencia original ha caducado.": "Original evidence has expired.",
  "Buscar en originales retenidos": "Search retained originals",
  "Buscar logs": "Search logs",
  Buscar: "Search",
  Anterior: "Previous",
  Siguiente: "Next",
  "Búsqueda progresiva sobre originales comprimidos, hasta 5.000 eventos por paso. Siguiente continúa desde el punto examinado.":
    "Progressive search through compressed originals, up to 5,000 events per step. Next continues from the last examined event.",
  " eventos examinados en este paso": " events examined in this step",
  " · Fin del histórico": " · End of history",
  Hora: "Time",
  Servicio: "Service",
  Mensaje: "Message",
  Cobertura: "Coverage",
  Inferida: "Inferred",
  "Evento ": "Event ",
  "Preguntar sobre los logs": "Ask about logs",
  "Pregunta o petición de filtro": "Question or filter request",
  Consultar: "Ask",
  "Consulta una muestra acotada del histórico de la máquina. Las propuestas de filtros se revisan antes de aplicarlas.":
    "Ask about a bounded sample of the machine's history. Review proposed filters before applying them.",
  "Evidencias: ": "Evidence: ",
  " eventos aportados": " events supplied",
  "Revisar filtro propuesto": "Review proposed filter",
  Análisis: "Analysis",
  Creado: "Created",
  Intentos: "Attempts",
  Diagnóstico: "Diagnostic",
  "Reintentar análisis": "Retry analysis",
  "Análisis en cola para el próximo ciclo automático.":
    "Analysis queued for the next automatic cycle.",
  Entregas: "Deliveries",
  Destino: "Destination",
  Fecha: "Date",
  Resultado: "Result",
  Reintentar: "Retry",
  "Reintento programado; podría duplicar una entrega de resultado desconocido.":
    "Retry scheduled; this could duplicate a delivery with an unknown outcome.",
  "Copia coherente del observatorio": "Consistent observatory backup",
  "Incluye originales comprimidos, máquinas, reglas y credenciales. Se guarda en la carpeta local de datos, con permisos exclusivos del propietario.":
    "Includes compressed originals, machines, rules and credentials. Stored in the local data folder with owner-only permissions.",
  "Crear copia local": "Create local backup",
  "Copia guardada: backups/": "Backup saved: backups/",
  "Restaurar en una carpeta nueva": "Restore into a new folder",
  Pendientes: "Pending",
  "Sin revisar por política": "Unreviewed: selection policy",
  "Excluidos del LLM": "Excluded from the LLM",
  "Revisados en resumen": "Reviewed as compact groups",
  "Originales revisados": "Originals reviewed",
  "Error de análisis": "Analysis error",
  "Captura continua activa": "Continuous capture active",
  "Captura inactiva": "Capture inactive",
  " fuentes habilitadas": " enabled sources",
  "Hay fuentes sin verificar o con errores. Revisa Fuentes.":
    "Some sources are unverified or have errors. Check Sources.",
  "El LLM está analizando ahora": "The LLM is analyzing now",
  "Análisis pausado; la captura continúa en las fuentes activas":
    "Analysis paused; enabled sources keep capturing logs",
  "Procesos automáticos desactivados en esta instancia":
    "Background workers are disabled in this instance",
  "LLM ocupado; el análisis espera su turno":
    "LLM busy; analysis is waiting for its turn",
  "Próximo análisis: ": "Next analysis: ",
  "Intervalo: ": "Interval: ",
  " segundos · Pendientes: ": " seconds · Pending: ",
  "Último ciclo: ": "Last cycle: ",
  Completado: "Completed",
  "Sin nuevos eventos seleccionados": "No new selected events",
  "Con errores": "With errors",
  Interrumpido: "Interrupted",
  " análisis con errores · ": " analyses with errors · ",
  " eventos sin revisar por capacidad": " events unreviewed due to capacity",
  "Pausar análisis": "Pause analysis",
  "Activar análisis automático": "Enable automatic analysis",
  "Análisis automático activado.": "Automatic analysis enabled.",
  "Los próximos análisis quedan pausados. El ciclo en curso puede terminar.":
    "Future analyses are paused. The current cycle may finish.",
  "Sin conexión con el portal. No se puede confirmar el estado del monitor.":
    "Disconnected from the portal. Monitor status cannot be confirmed.",
  "Conectar el LLM": "Connect the LLM",
  "Elegir máquina": "Choose a machine",
  "Conectar logs": "Connect logs",
  "Activar y aprender": "Enable and learn",
  "Cada paso se guarda al continuar. Puedes volver a este asistente desde el menú.":
    "Each step is saved when you continue. You can return to this wizard from the menu.",
  "Empieza por el modelo que leerá los logs y responderá tus preguntas. La prueba usa datos sintéticos y no envía logs.":
    "Start with the model that will read logs and answer your questions. The test uses synthetic data and sends no logs.",
  "Usa el contexto cargado en el servidor. Se reserva espacio para instrucciones y salida; el presupuesto de entrada es conservador. Los ajustes avanzados están en Modelo y análisis.":
    "Use the context loaded on the server. Space is reserved for instructions and output; the input budget is conservative. Advanced settings are in Model and analysis.",
  "La configuración guardada ya pasó la prueba de conexión.":
    "The saved configuration has already passed the connection test.",
  "Guardar, probar y continuar": "Save, test and continue",
  "Guardando y probando el LLM… Puede tardar hasta el tiempo de espera configurado.":
    "Saving and testing the LLM… This may take up to the configured timeout.",
  "Conexión verificada en ": "Connection verified in ",
  "Crear una máquina": "Create a machine",
  "Usa una ficha por máquina, también si los logs llegan desde una carpeta o un emisor remoto. Los campos de creación solo se usan al elegir Crear una máquina.":
    "Use one profile per machine, including logs from a folder or remote sender. Creation fields are only used when Create a machine is selected.",
  "Guardar y continuar": "Save and continue",
  "Crea una máquina en el paso anterior.":
    "Create a machine in the previous step.",
  "Crear una fuente": "Create a source",
  "Journal no necesita ruta: se consulta con journalctl y los permisos del servicio. Para archivos y carpetas usa una ruta absoluta en el servidor. Importar histórico puede traer todos los registros disponibles, no solo los últimos minutos.":
    "Journal needs no path: it uses journalctl with the service's permissions. Use an absolute server path for files and folders. Importing history can bring in all available records, not just recent minutes.",
  "La captura conserva también los INFO. Prioridad + palabras reduce lo enviado al LLM, con menor cobertura. La fuente existente conserva su política. Los campos de creación solo se usan al elegir Crear una fuente.":
    "Capture also retains INFO events. Priority + keywords sends less data to the LLM, reducing coverage. Existing sources keep their policy. Creation fields are only used when Create a source is selected.",
  "Activar fuente y comprobar lectura": "Enable source and test reading",
  "Comprobando lectura…": "Testing log reading…",
  "No se pudo leer la fuente.": "Could not read the source.",
  "Las fuentes activas se leen continuamente, aproximadamente cada 2 segundos más el tiempo de lectura. El LLM revisa lotes en el intervalo elegido. No necesitas pulsar Analizar ahora ni dejar abierto el portal.":
    "Enabled sources are read continuously, approximately every 2 seconds plus read time. The LLM reviews batches at the selected interval. You do not need to click Analyze now or leave the portal open.",
  "Si llegan más logs de los que admite el modelo, los originales se guardan según la retención y se muestra la cobertura perdida. Aumentar el contexto sin comprobar el modelo no garantiza más capacidad.":
    "If logs arrive faster than the model can handle, originals are stored according to retention and coverage gaps are shown. Increasing context without checking the model does not guarantee more capacity.",
  "En Problemas puedes ver evidencia, copiar un prompt y silenciar notificaciones. En Reglas puedes previsualizar filtros. En Notificaciones configura y prueba el destino que prefieras.":
    "In Problems you can view evidence, copy a prompt and mute notifications. Preview filters in Rules. Configure and test your preferred destination in Notifications.",
  "Las fuentes remotas necesitan configurar su emisor y clave desde Fuentes. Una fuente habilitada no confirma que estén llegando logs.":
    "Remote sources need a sender and a key configured from Sources. An enabled source does not confirm logs are arriving.",
  "No hay notificaciones activas. Los hallazgos aparecerán en el portal; puedes configurar avisos después.":
    "No notifications are enabled. Findings will appear in the portal; you can configure alerts later.",
  "Terminar y activar análisis automático":
    "Finish and enable automatic analysis",
  "Configuración terminada. La captura y el análisis automático están activados.":
    "Setup complete. Capture and automatic analysis are enabled.",
  "Configura y prueba el LLM en el primer paso del asistente. Si el monitor está analizando, espera a que termine para consultar.":
    "Configure and test the LLM in the first wizard step. If the monitor is analyzing, wait for it to finish before asking.",
  "Consultando el LLM…": "Asking the LLM…",
  "Conexión correcta: el modelo devolvió JSON válido. Esta prueba no mide la calidad de detección.":
    "Connection successful: the model returned valid JSON. This test does not measure detection quality.",
  "La sugerencia reserva instrucciones y salida; no mide rendimiento ni garantiza capacidad de RAM. Una API compatible puede no publicar el contexto.":
    "The suggestion reserves instructions and output; it does not measure performance or guarantee sufficient RAM. A compatible API may not report context size.",
  "No se pudieron consultar los metadatos del modelo configurado; revisa servicio, nombre y credenciales":
    "Could not fetch model metadata; check the service, model name and credentials",
  "Clave de acceso incorrecta": "Invalid access key",
  "Espera a que termine la petición actual antes de cambiar el modelo":
    "Wait for the current model request before changing model settings",
  "El monitor está analizando; vuelve a consultar en unos instantes":
    "Monitor is analyzing; try chat shortly",
  "Ya hay un análisis en curso": "Analysis already running",
  "Hay un análisis en curso; prueba el modelo cuando termine":
    "Analysis already running; try the model test shortly",
  "Prueba primero la configuración guardada del modelo":
    "Test the saved model configuration first",
  "Activa al menos una fuente de logs": "Enable at least one log source first",
  "El envío al modelo remoto está desactivado en los ajustes":
    "Remote model transmission is disabled in settings",
  "La entrada supera el presupuesto conservador de contexto":
    "Input exceeds conservative context budget",
  "La respuesta del modelo está incompleta": "Incomplete model response",
  "Selecciona una máquina": "Select a machine",
  "El modelo citó evidencia no disponible": "Model cited unavailable evidence",
};
Object.assign(translations, {
  Métricas: "Metrics",
  comprimidos: "compressed",
  "El modelo indica que la cobertura es incompleta.":
    "The model reports incomplete coverage.",
  "No hay destinos de notificación activos para estas métricas. Las alertas se guardan en Problemas; configura los avisos en Notificaciones.":
    "No notification destinations are enabled for these metrics. Alerts are saved in Problems; configure delivery in Notifications.",
  "Días de historial diario": "Daily history (days)",
  "Mínimos y máximos diarios (UTC)": "Daily minima and maxima (UTC)",
  "Espera de E/S": "I/O wait",
  Disco: "Disk",
  Inodos: "Inodes",
  "Carga 1 minuto": "1-minute load",
  "Carga 5 minutos": "5-minute load",
  "Carga 15 minutos": "15-minute load",
  "Tiempo encendido": "Uptime",
  días: "days",
  muestras: "samples",
  Muestras: "Samples",
  "muestras retenidas": "retained samples",
  "Mediciones activas": "Measurements active",
  "Mediciones desactivadas": "Measurements disabled",
  "Esperando primera muestra": "Waiting for the first sample",
  "Sin datos recientes": "No recent measurements",
  "Medición parcial": "Partial measurement",
  "Máximos y medias por hora, últimas 24 h":
    "Hourly peaks and averages, last 24 hours",
  "Naranja: máximo · Azul: media · Huecos: sin muestras":
    "Orange: maximum · Blue: average · Gaps: no samples",
  Mínimo: "Minimum",
  Máximo: "Maximum",
  Media: "Average",
  Día: "Day",
  Métrica: "Metric",
  "Añade una máquina antes de configurar las métricas.":
    "Add a machine before configuring metrics.",
  "Mediciones y alertas por máquina. Abre un equipo para configurar captura, umbrales e historial.":
    "Measurements and alerts per machine. Open a machine to configure collection, thresholds and history.",
  "Última muestra": "Last sample",
  "Ver métricas y configurar": "View metrics and configure",
  "Análisis de tendencias guardados": "Saved trend analyses",
  "Interpretar la evolución con el LLM": "Interpret trends with the LLM",
  Periodo: "Period",
  "Últimas 24 horas": "Last 24 hours",
  "Últimos 7 días": "Last 7 days",
  "Últimos 30 días": "Last 30 days",
  "Analizar tendencias": "Analyze trends",
  "Análisis de tendencias en cola; puedes cerrar esta vista.":
    "Trend analysis queued; you can leave this page.",
  "Una llamada con resúmenes de todo el periodo, ajustados al contexto. No modifica la máquina. Las alertas por umbral funcionan sin LLM.":
    "One call with summaries spanning the period, sized to fit the context. It cannot change the machine. Threshold alerts work without an LLM.",
  "Activar mediciones": "Enable measurements",
  "Origen de las métricas": "Metrics source",
  "Emisor remoto": "Remote sender",
  "Este equipo (servidor del portal)": "This host (portal server)",
  "Intervalo de medición (segundos)": "Measurement interval (seconds)",
  "Rutas de discos locales (una por línea)": "Local disk paths (one per line)",
  "Días de muestras comprimidas": "Compressed sample retention (days)",
  "Días de resúmenes diarios": "Daily summary retention (days)",
  "Umbral de aviso (%)": "Warning threshold (%)",
  "Muestras consecutivas para alertar": "Consecutive samples before alerting",
  "Subida brusca (puntos porcentuales)": "Sudden increase (percentage points)",
  "Separación entre avisos (segundos)": "Notification cooldown (seconds)",
  "Analizar tendencias automáticamente con el LLM":
    "Analyze trends automatically with the LLM",
  "Intervalo del análisis de tendencias (segundos)":
    "Trend analysis interval (seconds)",
  "Guardar configuración de métricas": "Save metrics configuration",
  "Configuración de métricas": "Metrics configuration",
  "El 98 % dispara una alerta crítica inmediata. Los demás umbrales requieren muestras consecutivas; se recuperan 5 puntos por debajo. Un pico compara con hasta 10 muestras anteriores. Las alertas usan los canales configurados y permanecen en Problemas hasta su revisión.":
    "98% triggers an immediate critical alert. Other thresholds require consecutive samples and clear 5 points below the threshold. Spikes compare against up to 10 preceding samples. Alerts use configured notification channels and remain in Problems until reviewed.",
  "Conectar un emisor remoto": "Connect a remote sender",
  "Activa el modo remoto y genera una clave exclusiva para esta máquina. Usa un túnel SSH o HTTPS. Configura el mismo intervalo y los discos en el emisor.":
    "Enable remote mode and generate a token dedicated to this machine. Use an SSH tunnel or HTTPS. Configure the same interval and the disks on the sender.",
  "Generar clave de métricas": "Generate metrics token",
  "Configurar captura y alertas": "Configure collection and alerts",
  "Conectar otro equipo": "Connect another machine",
  "Han pasado más de tres intervalos sin mediciones. Estos valores están desactualizados.":
    "More than three measurement intervals have elapsed. These readings are stale.",
  "RAM basada en memoria disponible. Swap sin configurar aparece como —. La primera muestra aún no tiene porcentaje de CPU. Mínimos y máximos observados, no continuos.":
    "RAM uses available memory. Unconfigured swap is shown as —. CPU percentage needs a second sample. Minima and maxima are sampled, not continuous.",
  "Ver alerta": "View alert",
  "Mínimos y máximos diarios (UTC), últimos 7 días":
    "Daily minima and maxima (UTC), last 7 days",
  "Contexto enviado al modelo": "Context sent to the model",
  "Medido por umbral": "Measured by threshold",
});
const reverseTranslations = Object.fromEntries(
  Object.entries(translations).map(([es, en]) => [en, es]),
);
let locale = "en";
try {
  locale = localStorage.getItem("logsentinel-language") || "en";
} catch {
  /* Browser storage can be disabled. */
}
if (!["en", "es"].includes(locale)) locale = "en";
function t(key, params = {}) {
  const original = reverseTranslations[key] || key;
  let value = locale === "es" ? original : translations[original] || key;
  for (const [name, replacement] of Object.entries(params))
    value = value.replaceAll("{" + name + "}", String(replacement));
  return value;
}
function staticLanguage() {
  document.documentElement.lang = locale;
  document.title = "LogSentinel · " + t("Resumen");
  document.querySelectorAll("[data-i18n]").forEach((n) => {
    n.textContent = t(n.dataset.i18n);
  });
  document.querySelector("#language").value = locale;
  const allMachines = document.querySelector('#machine-scope option[value=""]');
  if (allMachines) allMachines.textContent = t("Todas las máquinas");
  document
    .querySelector("#nav")
    .setAttribute("aria-label", t("Navegación principal"));
  document
    .querySelector("#close-modal")
    .setAttribute("aria-label", t("Cerrar"));
}
function initLanguage() {
  staticLanguage();
  $("#language").onchange = async (e) => {
    // Keep unsaved form edits in memory while replacing only interface text.
    const values = [
      ...$("#content").querySelectorAll(
        "input[name],select[name],textarea[name]",
      ),
    ].map((n) => [n.name, n.type === "checkbox" ? n.checked : n.value]);
    locale = e.target.value;
    try {
      localStorage.setItem("logsentinel-language", locale);
    } catch {
      /* preference is session-only */
    }
    staticLanguage();
    $("#nav").replaceChildren(
      ...Object.entries(names).map(([key, label]) =>
        button(t(label), () => navigate(key)),
      ),
    );
    if (!$("#shell").hidden) {
      await render();
      for (const [name, value] of values) {
        const input = [...$("#content").querySelectorAll("[name]")].find(
          (n) => n.name === name,
        );
        if (input) {
          if (input.type === "checkbox") input.checked = value;
          else input.value = value;
        }
      }
      drawMonitor(S.monitor);
    }
  };
}
