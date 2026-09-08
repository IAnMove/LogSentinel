# Operación del portal

## Conservación y capacidad

El portal separa captura continua y análisis periódico. Las fuentes activadas se sondean aproximadamente cada dos segundos más el tiempo de lectura; el LLM se ejecuta según `interval_seconds` si `enabled` está activado. El navegador puede cerrarse. El estado superior muestra última recepción, próxima ejecución, resultado del ciclo y cobertura; el modelo y la captura pueden fallar por separado. La ayuda LLM comparte el turno con el análisis. El asistente inicial prueba el modelo antes de permitir completar el alta automática.

La unidad de almacenamiento es un segmento gzip inmutable dentro de SQLite, no un archivo que deba esperar al cierre del escritor. Ingestión, cursor y referencias se confirman en una transacción con `synchronous=FULL`. El escritor de logs externo sigue siendo responsable de su propia rotación.

El análisis consume ventanas acotadas. Las repeticiones conservan cuenta, primera/última fecha e IDs originales. Los estados `compact` y `reviewed` distinguen revisión compactada de originales aportados a la segunda pasada; no certifican ausencia de fallos. `capacity`, `excluded` y `error` identifican falta de cobertura, exclusión o análisis fallido. Se conserva el original aunque no quepa en la ventana.

La cuota controla el ledger SQLite con margen conservador para una transacción. Los backups y archivos de notificación están fuera de esa cuota: hay que gestionarlos también a nivel de disco. La retención por días elimina originales, incluso sin revisar, y registra segmentos caducados. Los problemas permanecen, pero su evidencia puede caducar. No confundas retención con una cola infinita. Una cuota llena rechaza recepción con HTTP 507 y el emisor retiene el lote.

Sin tokenizer específico se usan bytes UTF-8 como estimación conservadora y se reserva espacio para instrucciones y salida. Debes configurar el contexto que realmente ofrece tu servidor, no el máximo teórico de la familia del modelo. La prueba sintética valida conectividad/formato, no calidad ni capacidad sostenida. La cadencia es un objetivo de inicio: un modelo lento alarga el ciclo y no genera ejecuciones simultáneas.

## Fuentes

### Selección de contexto para el LLM

Cada fuente conserva sus originales conforme a retención aunque se active un filtro. `Todas las líneas` envía los eventos pendientes al compactador actual, sujeto al presupuesto. `Prioridad + palabras` selecciona prioridades journald numéricas hasta el límite configurado **o** términos case-insensitive. `Solo palabras disparadoras` usa únicamente esos términos. Los tres modos selectivos añaden contexto ya retenido alrededor del disparador; `Adaptativa` es actualmente un alias de prioridad + palabras, no un control automático de capacidad. Los disparadores tienen preferencia sobre sus vecinos cuando no cabe todo.

La ventana no espera a que lleguen los minutos futuros ni reabre automáticamente la investigación cuando llegan. Está limitada a 100 disparadores y vecinos acotados por lado, con un máximo total de 5.000 eventos candidatos y el presupuesto final de la llamada. La consulta usa fecha del evento cuando existe y hora de recepción como alternativa. El chat de logs utiliza una muestra reciente; el chat de ayuda de configuración no recibe evidencia ni credenciales.

La prioridad es el campo estructurado `PRIORITY` de journald, no una palabra buscada en `MESSAGE`: 0 es emergente y 7 debug. En archivos planos normalmente no existe ese campo y se usan los términos disparadores. Los términos reducen el volumen y nunca convierten una coincidencia en un hallazgo; el LLM sigue teniendo que justificarlo con evidencia. Los eventos seleccionados como contexto pueden haber sido marcados `sampled`, pero se conservan y se vuelven a consultar alrededor de un disparador posterior.

La prioridad la declara el productor: no prueba que un registro sea benigno ni que no pueda falsificarse. El filtrado por prioridad también reduce cobertura; la UI distingue eventos sin revisar por política de eventos sin revisar por capacidad.

Para un uso inicial equilibrado, configura `Adaptativa`, prioridad máxima `4` (warning), contexto `5` minutos y términos como `error`, `critical`, `failed`, `panic`, `permission denied`, `out of memory` y `no space left on device`. Si eliges solo crítico, usa modo `Prioridad + palabras`, límite `2` y conserva términos de error como red de seguridad. No uses `grep -v info` sobre el archivo original.

Los cursores contienen identidad del archivo, offset y comprobación de cola para detectar reemplazos/truncados. Las líneas sin salto final se esperan. Una carpeta puede incluir archivos rotados y archivos comprimidos estables; se procesan hasta 100 archivos por sondeo, 1.000 entradas por lote y 256 KB por línea. Los archivos comprimidos se limitan a 64 MiB comprimidos y 128 MiB expandidos. Archivos zip, tar y zst se rechazan. Un error de fuente aparece en su estado; no se interpreta como silencio saludable.

La agrupación de continuaciones con sangría es heurística y se limita al lote. Para evidencia multilinea sin ambigüedad, usa JSON por evento. Los timestamps sin zona o año conservan la indicación `timestamp_inferred` en metadata; la zona de la máquina aporta contexto, no reescribe el timestamp original.

El colector conserva descriptores rotados durante cinco minutos sin crecimiento y continúa leyendo escrituras tardías, incluso si se elimina el nombre del archivo. Hay un límite de 128 descriptores por colector. Un reinicio o una escritura posterior a ese margen puede hacer irrecuperables los datos de un inode ya borrado. Para rotación local prefiere una carpeta que incluya los nombres rotados, o journal con cursor. `copytruncate` puede perder escrituras por diseño del productor. Un archivo comprimido importado tiene identidad propia: no se deduplica contra otra copia sin identidad compartida, pues podría borrar repeticiones legítimas. Nunca borres el original basándote únicamente en que el LLM terminó.

En recepción remota los segmentos se cierran por lote, independientemente del túnel. El emisor borra segmentos de su spool únicamente cuando todos sus eventos tienen ACK duradero. La deduplicación del receptor dura mientras retiene esos eventos; no hay garantía perpetua tras caducidad de originales. Una pausa superior a la rotación/retención del productor requiere almacenamiento durable en origen suficiente.

## Avisos y filtros

`mute` controla avisos; `exclude` controla el contexto enviado al modelo. Una exclusión no borra originales. Las reglas se pueden desactivar o borrar. Las expresiones se ejecutan con timeout y las fallidas no excluyen silenciosamente datos. La vista previa analiza una muestra, no prueba que el patrón sea seguro para toda entrada futura.

Las entregas se guardan antes de enviar. HTTP 5xx/429 permite hasta tres intentos; los timeouts quedan como `unknown` para evitar duplicados automáticos. Un reintento manual de `unknown` podría duplicar un aviso. HTTP 2xx en webhook/n8n significa aceptación, no confirmación de lectura humana. Las reglas de silencio y ámbito se vuelven a comprobar antes de enviar un aviso pendiente.

El destino de escritorio necesita una sesión de usuario y `notify-send`. Un servidor sin escritorio debe usar otro destino. Los destinos de archivo se limitan a nombres dentro de `notifications/`, con tamaño de rotación y número de copias gzip configurables desde el portal. Las URLs y credenciales se configuran localmente; ningún canal se ha validado con cuentas reales durante el desarrollo.

## Backup, recuperación y servicio

Crea una copia desde **Copias** y restaura con:

```bash
logsentinel restore /ruta/backup.db --data-dir /ruta/nueva
logsentinel portal --data-dir /ruta/nueva
```

La restauración exige destino inexistente, integridad SQLite y esquema compatible. Un trabajo interrumpido se reanuda; una entrega en curso pasa a resultado desconocido. Solo una instancia puede usar un directorio. Copiar únicamente `sentinel.db` mientras está activo no sustituye la API de backup por la posible existencia de WAL.

`systemd/logsentinel-portal.service` es una plantilla para `systemctl --user`: adapta `ExecStart` a tu instalación y copia la unidad a `~/.config/systemd/user/`. No se instala ni activa por ejecutar las pruebas. El token de acceso se imprime al arrancar; protege también el journal del servicio y el directorio de datos. Ejecuta como usuario con permiso de lectura sobre los logs necesarios; no hace falta ejecutar el portal como root.

El esquema actual es v1. Se rechazan versiones incompatibles. La base legacy se conserva separada; esta versión no transforma automáticamente alertas y supresiones antiguas en eventos nuevos.


## Consulta de capacidad del modelo

El formulario puede consultar los modelos disponibles y sugerir un presupuesto sin guardarlo automáticamente. En Ollama diferencia el máximo declarado de la ventana cargada; usa [los metadatos de `/api/show`](https://docs.ollama.com/api-reference/show-model-details) y [la información de modelos en ejecución](https://docs.ollama.com/api/ps). La sugerencia es una política conservadora de LogSentinel, no un benchmark de RAM o rendimiento. Una API compatible que solo publica nombres de modelos no permite deducir su contexto con fiabilidad.


## Unattended operation

The **Observer health** page checks capture, remote heartbeats (when configured),
measurement freshness, storage, recent model failures and background workers.
These checks run every five seconds without the LLM. A sustained failure creates
an evidence-backed `monitor.health` finding; a recovery resolves the same finding.
Existing notification destinations, minimum severity, machine scopes and mute
rules apply. Configure notification destinations to receive alerts outside the UI.

Health checks have a configurable grace period (30 seconds by default). Missing
measurements mean missing data, not proof a host is powered off. A quiet local log
remains healthy while collection checks succeed. Remote log heartbeat expiry is
opt-in (Sources → Remote heartbeat timeout); leave it disabled for older senders.
Disabling collection is not proof of recovery and does not close an incident.

Resource warnings require consecutive samples spaced at the configured collection
interval. Replayed or rapidly submitted samples cannot simulate sustained CPU
pressure. Critical CPU needs three sustained samples by default; memory, disk,
inode and swap exhaustion can still alert immediately at the critical threshold.
Recoveries use hysteresis and are recorded against the existing resource finding;
recovery notifications are configurable per machine.

`GET /healthz` is an unauthenticated **minimal readiness check** on the loopback
listener: HTTP 200 for healthy, 503 for starting/degraded/stale. It reveals no
configuration or log data. `/api/health` requires the normal portal session and
provides diagnostic details. A dead portal cannot report its own death: monitor
the endpoint independently (for example from a systemd timer or an external
uptime monitor through an SSH tunnel). The portal service should use `Restart=on-failure`.

When the model is slower than incoming logs, capture continues. The portal reports
unreviewed capacity explicitly; retained originals remain available until retention
or quota expiry. Increase model throughput or use the source's structured priority,
keyword and context selection with the filter preview. An unchecked line is never
reported as safe. Neither the model's severity assessment nor a declared syslog
priority is a guarantee of security.

## Sender recovery

`forward` and `metrics-forward` keep capture independent of HTTP delivery and retry
failed connections with a 4–60 second backoff. They bind each spool to its receiver
and source/machine and hold a single-writer lock. Stop older sender processes before
upgrading. Never reuse a spool for another destination.
Legacy senders that used a relative file path must be upgraded from their original
working directory; the new sender then persists the absolute path and binding.

Updated log senders emit an authenticated heartbeat every 30 seconds, including
capture health and the queue size. Configure a receiver timeout of at least 120
seconds to allow for connection retries. The receiver uses its own clock. Historical
backlog arrival cannot mask a sender that reports failed capture.

Expired metrics receive an explicit rejection, are retained locally with status
`quarantined`, and stop blocking fresh samples. Only acknowledged samples are
reclaimed. Quarantine takes space and is never automatically deleted: copy the spool
with the sender stopped before inspecting or archiving these measurements. Future
timestamps remain pending for retry; correct the sender clock if necessary.

```sh
logsentinel spool-status --spool ~/.local/share/logsentinel/metrics-spool
```

The command reports pending/quarantined counts and the latest capture/delivery
status without printing credentials. Sender transitions also go to stderr, visible
in the sender service journal. Run senders under a service manager with automatic
restart; a stopped sender cannot report its own outage without receiver heartbeats.

## Throughput and partial analysis

Observer health also shows arrival and covered-event rates, recent first-pass LLM
latency, and the busiest services with separate capacity and policy gaps. These
figures use retained events from the last hour, exclude synthetic measurements,
and obey the machine scope. They do not include expired originals and are not a
model detection benchmark.

Within the admitted batch, context is shared between services as well as sources;
the first service rotates across cycles. Trigger events still precede context.
This prevents a noisy admitted service from taking every prompt slot, but does not
provide unlimited ingestion or guarantee that every service fits in a small model.

If original-evidence verification fails after a valid first pass, its findings are
saved as preliminary and the job is marked `partial`, with the error retained.
Coverage remains `compact`; the app does not claim originals were reviewed. Open
the finding to request an investigation when the model is available. Repeated
automatic-cycle failures back off to at most one hour; a successful manual test or
scan clears the backoff. Capture continues throughout.


## Pausa y borrado de máquinas

En **Máquinas** hay controles independientes **Pausar esta máquina**, **Reanudar esta máquina**, **Optimizar** y **Borrar máquina**. La pausa detiene captura, nuevos análisis automáticos, mediciones y avisos de ese equipo. Conserva fuentes, cursores e historial; una llamada ya enviada puede acabar y los avisos pendientes esperan a la reanudación. El chat manual puede seguir consultando el historial. El botón superior **Pausar análisis global** solo controla el planificador LLM de todas las máquinas, sin detener su captura; el encabezado indica que su estado es global.

Los emisores remotos reciben HTTP 409 mientras una máquina está pausada y deben conservar su spool. Pausar el receptor no detiene los procesos externos ni su generación de logs: el origen necesita espacio y retención para recuperarse después. Reanudar conserva la configuración anterior y respeta la pausa global del análisis.

**Borrar máquina** abre un diálogo con recuentos y confirmación explícita. Se detiene la máquina y se crea un trabajo duradero: espera las operaciones en curso, borra en una transacción sus fuentes, eventos/segmentos, hallazgos/evidencias/revisiones, análisis, conversaciones, consumo, métricas, filtros y canales de ámbito exclusivo. Las claves de sus emisores dejan de ser válidas. Los controles e historial de otras máquinas y los canales globales permanecen. El borrado sobrevive a cerrar la ventana o reiniciar el portal; un fallo permite reintentar desde su estado de borrado. La compactación recupera espacio SQLite y se informa si queda pendiente.

Los archivos originales y journal del sistema, backups existentes y notificaciones ya enviadas/exportadas se conservan. No se revocan mensajes en Slack/Telegram ni se editan archivos exportados que puedan mezclar varias máquinas. Hay que detener o reconfigurar los emisores externos tras borrar su identidad. El portal conserva solo una constancia mínima de la operación y del ID retirado para impedir escrituras tardías; no es un borrado seguro de soportes o copias externas.
