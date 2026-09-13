**Texto para configurar un cliente Linux con Codex**

Entrega a Codex un paquete de alta nuevo para ese cliente (`alta.json`), la rueda
de Python validada (`logsentinel-*.whl`), su SHA-256, `GUIA_EQUIPOS.md` y, si se
quiere empezar al final del archivo, el helper revisado `init-new-only.py`.
El central debe preparar primero una dirección HTTPS alcanzable desde el cliente.
Un paquete de otro equipo no sirve: cada fuente necesita su propia credencial.

Copia este encargo y sustituye los dos valores iniciales:

```text
Configura este Linux como emisor de LogSentinel contra el central indicado
en alta.json.

Directorio con los archivos entregados: /RUTA/DEL/KIT
Archivo que quiero monitorizar: /RUTA/DEL/LOG
Empieza solo por entradas nuevas.

1. Lee GUIA_EQUIPOS.md y el manifiesto entregado. Comprueba el sistema operativo,
   Python, la ruta del log y si existe una instalación o spool anteriores.
   Conserva cualquier cola, cursor, credencial y servicio existentes.
2. Instala la rueda entregada en /opt/logsentinel/.venv y comprueba su SHA-256
   contra el valor recibido por el canal de confianza. Usa las constraints de
   Python 3.12 solo si ese es el Python instalado. No sustituyas este paquete
   por GitHub main: puede contener una versión distinta de la validada.
3. Prepara la cuenta sin login logsentinel-agent y el grupo logsentinel-read
   con prepare-host. Concede lectura mediante ACL únicamente al archivo elegido
   y acceso de búsqueda a los directorios necesarios. Conserva sus propietarios
   y grupos. Mantén esa ACL tras rotar el archivo, conservando y validando la
   configuración de rotación existente. El emisor debe ejecutarse sin root.
4. Comprueba HTTPS con la CA del paquete. Si la dirección es 127.0.0.1, confirma
   que existe el túnel acordado; esa dirección solo funciona en ese cliente.
   La dirección del servidor LLM es independiente de la dirección del receptor.
5. Crea un spool privado por archivo y canjea alta.json con enroll como la cuenta
   del emisor. No imprimas códigos ni tokens. Elimina las copias del paquete
   una vez canjeado. No necesitas la clave de administración del portal.
6. Para un spool nuevo, ejecuta el helper entregado init-new-only.py como la
   cuenta del emisor, indicando --spool y --source, antes de arrancar forward.
   El helper debe rechazar una fuente ya inicializada. No reinicialices cursores
   existentes. El comando forward sin esta preparación empieza con el historial;
   no inventes un argumento --from-end, porque esta versión no lo tiene.
7. Instala un servicio systemd emisor independiente, según GUIA_EQUIPOS.md,
   usando forward, --token-file y el spool preparado. Actívalo al arrancar.
   service install instala un portal y no corresponde a este cliente.
8. Comprueba lectura con esa cuenta, validación TLS, heartbeat y entrega de
   entradas nuevas. Verifica que la cola conserva datos si el central no está
   disponible y progresa al volver. Reiniciar el emisor debe conservar el cursor.
   Una comprobación local solo demuestra envío/ACK: pide al operador del central
   la confirmación de recepción y análisis si no tienes acceso a esos datos.

Devuélveme: versión y SHA-256 instalados, nombre del servicio, archivo vigilado,
ruta del spool, cómo ver su estado y sus errores, permisos concedidos, cambios
en rotación y resultado de las comprobaciones. No incluyas secretos.

Si este equipo es Windows nativo, detente y explica esa limitación: este emisor
utiliza interfaces Linux y no captura el registro de eventos de Windows.
```

**Lo que prepara el operador del central para cada equipo**

Crea la máquina y una fuente de recepción remota, acuerda un archivo concreto y
prepara su conectividad. Genera un paquete nuevo con `enrollment-package`, según
`GUIA_EQUIPOS.md`, y entrégalo por un canal de confianza. El código tiene una hora
de validez por defecto; si caduca, hay que emitir otro. Conserva la CA privada y
la clave del portal exclusivamente en el central.

Si se utiliza un túnel SSH inverso, el central puede iniciarlo hacia un equipo al
que ya tenga acceso SSH. El receptor y el extremo remoto pueden permanecer en
loopback. HTTPS sigue verificando el certificado dentro del túnel. En una LAN
también se puede exponer únicamente el receptor HTTPS en una IP reservada, con
el certificado correspondiente y reglas de cortafuegos limitadas a los clientes.

La conexión no está terminada hasta ver eventos de ese cliente en el Histórico,
su estado de recepción y el progreso de su análisis. Un alta emitida, una máquina
creada o un túnel activo todavía no significan que se estén monitorizando sus logs.
