# Protección y recuperación del cliente de logs

Desde 1.0.1, pausar una máquina en el portal comunica al cliente una pausa de
captura y entrega. El cliente conserva su cola y cursor y sigue enviando estado.
Desactivar el análisis del LLM es diferente: por sí solo no detiene la recepción
ni la captura. No se reanuda una pausa manual sin reactivar la máquina en el portal.

## Actualizar una instalación existente

Primero actualiza el central. En un cliente antiguo con problemas de disco,
detén el servicio antes de actualizar: la versión 1.0.0 no obedece la pausa remota.
Espera a que el disco se estabilice antes de hacer la copia o instalar paquetes.

Desde el repositorio del cliente:

```bash
sudo systemctl stop logsentinel-client-logs
git pull --ff-only
sudo ./setup-client.sh --upgrade --name logs
```

No necesitas otra alta. El actualizador conserva configuración, identidad,
credencial, CA, eventos y cursores. Guarda una copia SQLite coherente y la unidad
anterior en el directorio de copia que imprime. Comprueba espacio para la copia y
el índice; la operación de copia y adaptación de la cola tiene prioridad baja.
La adaptación añade un índice y un contador; no elimina evidencia ni reinicia el
cursor. El runtime anterior queda disponible.

**Un servicio detenido permanece detenido.** Cuando termines la investigación,
puedes arrancar el cliente; seguirá pausado mientras lo esté la máquina del portal:

```bash
sudo systemctl start logsentinel-client-logs
sudo systemctl status logsentinel-client-logs --no-pager
sudo journalctl -u logsentinel-client-logs -n 30 --no-pager
```

En Fuentes, comprueba versión, tamaño y motivo de pausa comunicados por el cliente.
Para detectar también la ausencia de contacto, configura en esa fuente un timeout
de heartbeat, por ejemplo 180 segundos. El valor cero desactiva la detección por
ausencia; los errores explícitos del cliente sí se supervisan.
Si falla una actualización, el cliente queda detenido y se restaura su unidad
anterior. No se sobrescribe automáticamente la cola con la copia: podría contener
eventos nuevos. Conserva ambas para decidir la recuperación. No borres el spool
para resolver errores de espacio o E/S.

## Límites predeterminados

- Cola: cuota SQLite existente (1 GiB por defecto); pausa de captura al 85 % de
  espacio ocupado útil o al alcanzar 100.000 pendientes. Un lote ya empezado puede
  superar ligeramente el umbral de eventos.
- Reanudación automática por capacidad: por debajo del 60 % de cuota y de 60.000
  pendientes. Esta recuperación no anula una pausa manual del portal.
- Reserva de disco: 256 MiB para captura. La entrega puede liberar bloques
  confirmados mientras quede una reserva de 16 MiB.
- Si la presión completa de E/S de Linux (`full avg10` de `/proc/pressure/io`)
  alcanza el 25 %, se pausa el trabajo de captura y entrega. Se permite recuperar
  cuando baja del 12,5 %. No equivale al porcentaje de actividad del dispositivo;
  mide tiempo de bloqueo. Si PSI no está disponible, siguen aplicándose los
  límites de cola y espacio.
- Lotes de captura de hasta 256 KiB. La comprobación del cursor reserva otra
  cantidad acotada para el registro anterior. No se vuelca el journal en temporales.
- Entrega de hasta 100 eventos por petición, con espera mínima de 2 segundos y
  reducción del ritmo si una operación tarda. Se respeta `Retry-After` de cuotas.
- Control cada 30 segundos. Sin una autorización reciente, se suspende la captura
  y la entrega en un máximo de 90 segundos, además del trabajo que ya esté en curso.
- Errores de captura: esperas de 30 a 300 segundos; SQLite y errores operativos
  tienen códigos visibles. Los cambios de estado se guardan inmediatamente; los
  refrescos repetidos se limitan a uno por 30 segundos y fase.

Los límites del cliente se pueden ajustar en el objeto opcional `limits` de
`/etc/logsentinel-clients/logs.json`, conservando el resto de su configuración:

```json
{
  "max_pending_events": 100000,
  "min_free_mb": 256,
  "high_water_percent": 85,
  "resume_percent": 60,
  "io_pressure_percent": 25,
  "capture_batch_bytes": 262144
}
```

Ese fragmento es el contenido de `limits`, no un reemplazo del archivo completo.
Reinicia el servicio para cargar un cambio. Los límites evitan acumulación sin
control; no garantizan conservar indefinidamente un flujo mayor que la capacidad.

## Evidencia y límites de recuperación

Solo se borran de la cola segmentos completamente confirmados como durables por
el central. Un ACK perdido se reenvía con los mismos IDs, sin duplicados lógicos.
La limpieza reutiliza páginas libres de SQLite: ya no ejecuta VACUUM por lote.
Por ello el archivo puede seguir ocupando espacio aunque la cola se haya vaciado;
la cuota tiene en cuenta el espacio reutilizable. No hay compactación automática
durante el envío.

Si el journal rota y desaparece el cursor guardado, se muestra
`journal_retention_gap` y no se avanza silenciosamente. Conserva la cola y busca el
journal archivado; empezar desde otro punto exige aceptar explícitamente ese hueco.
Un registro mayor que el presupuesto produce `journal_record_too_large`, sin
descartarlo ni marcarlo entregado.

Un disco bloqueado en el kernel puede impedir completar operaciones ya iniciadas.
Los límites no reparan fallos del dispositivo, cable, controlador o sistema de
archivos. Investiga esa causa además de reducir el trabajo del cliente.
