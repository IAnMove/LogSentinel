**Enviar logs desde otro equipo al central**

El cliente inicia la conexión HTTPS hacia el central. No necesita un servidor SSH
ni acepta órdenes del central. El panel y el receptor usan puertos distintos:

| Uso | Dirección de ejemplo | Credencial |
| --- | --- | --- |
| Panel de administración | `http://127.0.0.1:8766` en el central | Clave del portal |
| Recepción desde clientes | `https://CENTRAL:8767` | Token de una fuente |

Los nombres y rutas en mayúsculas son valores que debes sustituir. El emisor de
este recorrido envía **un archivo de logs por spool**. `enroll` realiza el alta;
no instala automáticamente un servicio ni empieza a leer el journal.

**1. Preparar el receptor una vez, en el central**

Elige una IP reservada o un nombre DNS estable. Necesitas un certificado de
servidor válido para esa IP o nombre, su clave privada y el certificado público
de la autoridad que lo firma. Una autoridad local sirve: los clientes confiarán
en ella para esta conexión, sin desactivar la validación TLS ni instalarla como
autoridad de confianza global. No hace falta un dominio público.

Protege la clave privada y permite su lectura solo al usuario que ejecuta el
portal. Arranca la misma instancia, conservando su directorio de datos:

```bash
logsentinel portal --data-dir /RUTA/DEL/PORTAL --port 8766 \
  --ingest-listen 0.0.0.0:8767 \
  --tls-cert /RUTA/server.pem --tls-key /RUTA/server.key
```

Si ya funciona como servicio, añade esas opciones a su `ExecStart` y reinicia
ese servicio; no arranques otro proceso sobre la misma base. Permite el puerto
8767 en el cortafuegos solo desde los equipos o la subred que deban enviar.
El panel permanece en loopback. No abras el puerto del panel a la LAN.

**2. Crear el alta de un cliente, en el central**

En el portal crea la máquina y una fuente de tipo **Recepción remota**, y actívala.
Copia el ID de esa fuente. Cada fuente tiene su propia credencial revocable.
Después, como el usuario propietario de los datos del portal:

```bash
logsentinel enrollment-package --data-dir /RUTA/DEL/PORTAL \
  --source-id ID_FUENTE --receiver https://CENTRAL:8767 \
  --ca-cert /RUTA/ca.pem --out cliente.json
```

Transfiere `cliente.json` por un canal de confianza. Contiene la dirección,
el certificado público y un código de un solo uso que caduca en una hora por
defecto. Quien tenga el archivo antes de utilizarlo puede canjear ese código.
No entregues la clave privada del certificado ni la clave de acceso al portal.

**3. Preparar permisos y canjear el alta, en el cliente**

Instala LogSentinel en una ruta legible por la cuenta del emisor. Los siguientes
ejemplos suponen que su ejecutable está en `/opt/logsentinel/.venv/bin/logsentinel`.
Comprueba el plan de permisos y aplícalo para el archivo elegido:

```bash
sudo /opt/logsentinel/.venv/bin/logsentinel prepare-host \
  --account logsentinel-agent --source /var/log/miapp/app.log
sudo /opt/logsentinel/.venv/bin/logsentinel prepare-host \
  --account logsentinel-agent --source /var/log/miapp/app.log --apply
```

Esto crea una cuenta sin login y añade lectura mediante ACL sin cambiar el
propietario o grupo del archivo. Para un archivo rotado debes mantener ese permiso
en la configuración de rotación. Conceder una carpeta permite leer también los
archivos que hereden sus ACL: revisa ese alcance antes de aprobarlo.

Crea un directorio privado para este emisor y copia ahí el paquete:

```bash
sudo install -d -m 700 -o logsentinel-agent -g logsentinel-read /var/lib/logsentinel/app
sudo install -m 600 -o logsentinel-agent -g logsentinel-read cliente.json /var/lib/logsentinel/app/alta.json
sudo -u logsentinel-agent /opt/logsentinel/.venv/bin/logsentinel enroll \
  /var/lib/logsentinel/app/alta.json --spool /var/lib/logsentinel/app
```

Una vez canjeado, elimina ambas copias del paquete. Quedan `push-token` y
`receiver-ca.pem` en el spool. El token solo debe ser legible por esa cuenta.

**4. Comprobar una entrega antes de dejar el emisor permanente**

Usa el comando que imprime `enroll`, con la ruta real de tu archivo. Por ejemplo:

```bash
sudo -u logsentinel-agent /opt/logsentinel/.venv/bin/logsentinel forward \
  /var/log/miapp/app.log --receiver https://CENTRAL:8767 \
  --source-id ID_FUENTE --spool /var/lib/logsentinel/app \
  --token-file /var/lib/logsentinel/app/push-token --once
```

El emisor usa automáticamente `receiver-ca.pem` para verificar el certificado y
el nombre del central. No hay que copiar el token a la línea de comandos.
Comprueba el evento en **Histórico**, seleccionando la máquina del cliente.
`--once` procesa un lote, no garantiza vaciar un archivo completo. Este emisor
empieza por el contenido existente del archivo; conserva los originales hasta
que termine el envío. Para el resto, ejecútalo continuamente.

**5. Dejar el emisor como servicio**

`logsentinel service install` instala un **portal**, no un emisor. Para este último
crea `/etc/systemd/system/logsentinel-sender-app.service` con los valores elegidos:

```ini
[Unit]
Description=LogSentinel sender for app logs
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=logsentinel-agent
Group=logsentinel-read
ExecStart=/opt/logsentinel/.venv/bin/logsentinel forward /var/log/miapp/app.log --receiver https://CENTRAL:8767 --source-id ID_FUENTE --spool /var/lib/logsentinel/app --token-file /var/lib/logsentinel/app/push-token
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=/var/lib/logsentinel/app

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now logsentinel-sender-app
sudo systemctl status logsentinel-sender-app
sudo journalctl -u logsentinel-sender-app -n 30 --no-pager
```

**Dónde ver límites, errores y progreso**

El central aplica a cada fuente las cuotas por hora configuradas en **Modelo y
análisis → Límites de recepción remota**. No hay captura ilimitada: al agotarse la cuota,
el cliente conserva el lote y reintenta cuando corresponda. Si se llena su spool,
debes conservar también el archivo original; su rotación externa puede eliminar
datos que el emisor todavía no haya leído.

En el cliente, `logsentinel spool-status --spool /var/lib/logsentinel/app` muestra
la cola y el estado de los trabajadores. En el central, **Histórico** confirma
recepción y **Cobertura y capacidad** distingue lo recibido de lo analizado.
Los ACK confirman almacenamiento; no son el resultado del LLM. El cliente no
recibe comandos de reparación ni tiene acceso a los problemas de otras máquinas.
