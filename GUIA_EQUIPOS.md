**Enviar logs desde otro equipo al central**

El cliente inicia una conexión HTTPS hacia el central. No necesita un servidor
SSH ni recibe órdenes del central. El panel de administración y la recepción
usan puertos distintos: normalmente 8766 y 8767, respectivamente.

**En el cliente: un comando**

Necesitas Linux con systemd, Python 3.10 o posterior, el repositorio o un paquete
de esta versión y el archivo privado `alta.json` que entrega el central.
Dentro del repositorio, ejecuta:

```bash
sudo ./setup-client.sh --package /ruta/alta.json
```

El instalador prepara un entorno Python aislado, crea la cuenta sin login
`ls-logs`, le permite leer el journal, comprueba el certificado del central,
canjea el alta y activa el servicio emisor. **Por defecto envía solo entradas
nuevas del journal de todos los servicios**, desde la primera captura del
instalador. No importa el historial ni instala un modelo en el cliente.
Root se usa para instalar; el servicio funciona después con la cuenta limitada.
En Debian/Ubuntu puede instalar `python3-venv` si falta; se necesita acceso al
repositorio de paquetes Python durante la primera instalación.

Para ver lo que hará sin cambiar nada:

```bash
./setup-client.sh --package /ruta/alta.json --plan
```

| Qué buscas | Dónde está, con el nombre por defecto |
| --- | --- |
| Estado del emisor | `sudo systemctl status logsentinel-client-logs` |
| Errores recientes | `sudo journalctl -u logsentinel-client-logs -n 30 --no-pager` |
| Configuración | `/etc/logsentinel-clients/logs.json` |
| Cola, cursor, credencial y certificado público | `/var/lib/logsentinel-client/logs/` |
| Programa instalado y copias previas del servicio | `/opt/logsentinel-client/` |
| Logs recibidos y analizados | Histórico del central, seleccionando la máquina |

Si se corta la conexión, el emisor conserva lo capturado en la cola local y
reintenta. El central limita el envío por fuente y analiza según la capacidad
del modelo. Una cola local llena detiene el avance: conserva el journal o los
archivos originales hasta recuperarla. Haber enviado no significa haber analizado;
comprueba por separado recepción y cobertura en el central.

**Un archivo en lugar del journal**

Indica el archivo y su configuración de logrotate, con un único `postrotate`:

```bash
sudo ./setup-client.sh --package /ruta/alta-app.json --name app \
  --file /var/log/miapp/app.log --logrotate-config /etc/logrotate.d/miapp
```

Crea una cuenta y una cola distintas. Concede lectura mediante ACL sin cambiar
el propietario o grupo del archivo y añade una acción al `postrotate` existente
para mantenerla al rotar. No concede lectura a toda la carpeta. Si los directorios
padre impiden recorrer la ruta, detiene la instalación e indica que revises esos
permisos. El journal no requiere configurar logrotate.

Usa `--include-history` solo si quieres importar también el historial en una
instalación nueva. Cada journal o archivo necesita su propia fuente, nombre y
cola. No reutilices una credencial para otro equipo.

**Reintentar, actualizar o detener**

Repite el comando con la misma identidad y los mismos argumentos para reintentar
o instalar una versión nueva. Conserva la cola, el cursor y el token existente;
no vuelve a importar historial ni canjea otra credencial si ya tiene una. El
instalador elimina el JSON de alta al terminar: para actualizar, puedes usar la
copia del paquete original o pedir otro para la misma fuente y receptor.
Rechaza convertir una instalación existente en otra fuente. Guarda la cola al
actualizar; no la borres para resolver un error de conexión.

```bash
sudo systemctl restart logsentinel-client-logs
sudo systemctl disable --now logsentinel-client-logs
```

El segundo comando detiene la captura y el envío conservando los datos.
Windows nativo aún no tiene captura de su registro de eventos con este emisor.

**En el central: preparar HTTPS una vez**

Elige una IP reservada o un nombre DNS estable. Necesitas un certificado válido
para esa IP o nombre, su clave privada y el certificado público de la autoridad
que lo firma. Una autoridad local sirve: el cliente confía en ella solo para
esta conexión. No necesita un dominio público ni desactivar la validación TLS.

Protege la clave privada para que solo la lea el usuario del portal. En la misma
instancia, conservando su directorio de datos:

```bash
logsentinel portal --data-dir /RUTA/DEL/PORTAL --port 8766 \
  --ingest-listen 0.0.0.0:8767 \
  --tls-cert /RUTA/server.pem --tls-key /RUTA/server.key
```

Si funciona como servicio, añade las opciones a su `ExecStart` y reinícialo;
no arranques otro proceso sobre la misma base. Limita el puerto 8767 en el
cortafuegos a los clientes autorizados. El panel permanece en loopback.
El receptor debe tener esta versión para aceptar el journal estructurado:
`GET /ingest-info` anuncia `journal` entre sus formatos.

**En el central: dar de alta cada fuente**

En el portal crea la máquina y una fuente de tipo **Recepción remota**, y actívala.
Como propietario de los datos del portal, usando el ID de esa fuente:

```bash
logsentinel enrollment-package --data-dir /RUTA/DEL/PORTAL \
  --source-id ID_FUENTE --receiver https://CENTRAL:8767 \
  --ca-cert /RUTA/ca.pem --out alta.json
```

Entrega `alta.json` por un canal de confianza. Contiene la dirección, el
certificado público y un código de un solo uso, válido una hora por defecto.
No entregues la clave privada TLS ni la clave del portal. Cada fuente tiene su
credencial revocable; puedes emitir otra alta si caduca la anterior.

Después de instalar el cliente, comprueba eventos de su máquina en Histórico y
el progreso del análisis. Crear la máquina o emitir un alta todavía no significa
que sus logs se estén monitorizando.

**CLI manual**

`logsentinel enroll alta.json --spool /ruta/cola` solo canjea el alta.
`logsentinel forward --journal --new-only --receiver https://CENTRAL:8767
--source-id ID --spool /ruta/cola --token-file /ruta/cola/push-token` envía el
journal; para un archivo, sustituye `--journal` por su ruta. Sin `--new-only`,
un spool nuevo empieza con el historial. `--once` procesa un lote de prueba.
`logsentinel service install` instala un portal, no este servicio emisor.
