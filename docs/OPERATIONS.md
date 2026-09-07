# Operación del portal

## Conservación y capacidad

La unidad de almacenamiento es un segmento gzip inmutable dentro de SQLite, no un archivo que deba esperar al cierre del escritor. Ingestión, cursor y referencias se confirman en una transacción con `synchronous=FULL`. El escritor de logs externo sigue siendo responsable de su propia rotación.

El análisis consume ventanas acotadas. Las repeticiones conservan cuenta, primera/última fecha e IDs originales. Los estados `compact` y `reviewed` distinguen revisión compactada de originales aportados a la segunda pasada; no certifican ausencia de fallos. `capacity`, `excluded` y `error` identifican falta de cobertura, exclusión o análisis fallido. Se conserva el original aunque no quepa en la ventana.

La cuota controla el ledger SQLite con margen conservador para una transacción. Los backups y archivos de notificación están fuera de esa cuota: hay que gestionarlos también a nivel de disco. La retención por días elimina originales, incluso sin revisar, y registra segmentos caducados. Los problemas permanecen, pero su evidencia puede caducar. No confundas retención con una cola infinita. Una cuota llena rechaza recepción con HTTP 507 y el emisor retiene el lote.

Sin tokenizer específico se usan bytes UTF-8 como estimación conservadora y se reserva espacio para instrucciones y salida. Debes configurar el contexto que realmente ofrece tu servidor, no el máximo teórico de la familia del modelo. La prueba sintética valida conectividad/formato, no calidad ni capacidad sostenida. La cadencia es un objetivo de inicio: un modelo lento alarga el ciclo y no genera ejecuciones simultáneas.

## Fuentes

### Selección de contexto para el LLM

Cada fuente conserva sus originales aunque se active un filtro. `Todas las líneas` envía los eventos pendientes al compactador actual. `Prioridad + palabras` selecciona prioridades journald numéricas hasta el límite configurado y términos case-insensitive. `Solo palabras disparadoras` usa únicamente esos términos. `Adaptativa` combina ambas cosas y añade eventos de la misma fuente dentro de la ventana de contexto configurada antes y después del disparador.

La prioridad es el campo estructurado `PRIORITY` de journald, no una palabra buscada en `MESSAGE`: 0 es emergente y 7 debug. En archivos planos normalmente no existe ese campo y se usan los términos disparadores. Los términos reducen el volumen y nunca convierten una coincidencia en un hallazgo; el LLM sigue teniendo que justificarlo con evidencia. Los eventos seleccionados como contexto pueden haber sido marcados `sampled`, pero se conservan y se vuelven a consultar alrededor de un disparador posterior.

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
