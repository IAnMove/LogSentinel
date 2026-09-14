**Encargo para configurar otro equipo con Codex**

Entrega al Codex del cliente el repositorio de esta versión (incluye
`setup-client.sh`), el archivo privado `alta.json` del central y este encargo:

```text
Configura este Linux como cliente de LogSentinel usando el repositorio entregado
y alta.json. Por defecto queremos el journal de todos los servicios y solo
entradas nuevas. No necesitamos un modelo ni un portal en este cliente.

1. Lee GUIA_EQUIPOS.md. Comprueba Linux, systemd y Python 3.10 o posterior.
2. Ejecuta ./setup-client.sh --package /ruta/alta.json --plan. Comprueba que
   el receptor coincide con el central acordado; es distinto del servidor LLM.
3. Ejecuta sudo ./setup-client.sh --package /ruta/alta.json. El script instala
   el entorno aislado, crea la cuenta limitada, prepara permisos, canjea el
   alta HTTPS y activa el servicio. No imprimas códigos ni tokens y no
   desactives la validación del certificado.
4. Si se pidió un archivo concreto en lugar del journal, usa --file y el
   --logrotate-config correspondiente, según la guía. Usa otro --name para
   otra fuente; no cambies la identidad ni reinicialices una cola existente.
5. Comprueba el servicio, sus errores, lectura con su cuenta y heartbeat.
   Reiniciar debe conservar el cursor y la cola. Un ACK local acredita envío;
   pide al operador del central confirmación de recepción y cobertura si no
   tienes acceso a esos datos. No inventes una comprobación con el LLM.

Devuélveme la versión instalada, servicio, fuente, permisos concedidos, cola,
cómo ver estado/errores y resultado de las comprobaciones. No incluyas secretos.
Si es Windows nativo, explica que este emisor aún no captura sus eventos.
```

El operador del central prepara la conectividad HTTPS, crea una máquina y una
fuente de recepción remota por emisor y genera el alta según
[GUIA_EQUIPOS.md](GUIA_EQUIPOS.md). El código caduca en una hora por defecto.
La CA privada y la clave del portal se quedan en el central.

En una LAN se expone únicamente el receptor HTTPS, con certificado para su
IP o nombre y acceso limitado a los clientes. También puede circular por un
túnel SSH, conservando la comprobación HTTPS. El instalador no configura el
router ni necesita un servidor SSH en el cliente.
