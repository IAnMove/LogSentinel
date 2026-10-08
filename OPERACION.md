# Operación: montar el modelo, medir, acceder y vigilar

Notas de operación reunidas de uso real. Los números salen de un equipo concreto
(un modelo de 8 000 M de parámetros cuantizado a 4 bits, solo CPU) y sirven como
orden de magnitud, no como garantía: mide los tuyos en **Cobertura y capacidad**.

## 1. El servidor de modelos local

Comprueba el servidor antes de configurarlo en el portal:

```bash
curl http://127.0.0.1:PUERTO/health          # llama.cpp
curl http://127.0.0.1:PUERTO/v1/models       # debe devolver JSON con el modelo
curl http://127.0.0.1:11434/api/tags         # Ollama
```

- **Puerto ocupado por otro servicio.** llama.cpp usa el 8080 por defecto. Si otro
  programa lo tiene, muévelo a otro puerto (por ejemplo 8081). Un servicio que
  contesta HTML en `/v1/models` no es un servidor de modelos: el portal solo
  reconoce como tal una respuesta JSON, y el asistente de configuración no lo
  ofrecerá.
- **El identificador del modelo** es el que publica el servidor en `/v1/models`,
  que en llama.cpp suele ser la ruta completa del archivo `.gguf`. Cópialo tal cual.
- **Modelos que razonan (Qwen3 y similares).** Pueden gastar todo el límite de
  salida pensando antes de escribir el JSON. Deja desactivado el *pensamiento* en
  **Modelo y análisis**: el portal envía `enable_thinking=false` a llama.cpp/vLLM y
  el parámetro `think` a Ollama. Si lo activas, sube el límite de salida y acepta
  menos rendimiento.
- **Contexto.** El contexto configurado en el portal debe ser el que el servidor
  cargó de verdad. Con varios *slots* paralelos, cada petición recibe el contexto
  dividido entre ellos.
- **Sin GPU útil**, arranca llama.cpp con `-ngl 0`: la inferencia va por CPU y
  ocupa RAM (unos 12 GiB en el equipo medido, para un archivo de 5 GB).

## 2. Cuánto tarda una llamada y qué timeout poner

En el equipo medido: unos **8 tokens/s** generando y **60 s** leyendo la entrada.
Con el timeout por defecto (120 s) cinco de 35 llamadas se cortaron, y una tarea
que en 60 s de lectura más 483 tokens de respuesta pasaba de los 120 s terminó bien
con **240 s**. Una respuesta de solo 1 024 tokens a 8 tokens/s ya son unos 2 minutos.

- En CPU, sube **Tiempo de espera del LLM** a 240 s o más y usa el perfil de
  *lotes pequeños* de **Modelo y análisis**.
- Un timeout de lectura cuenta como intento fallido; al tercero el lote pasa a
  *fallido*. Un servidor caído no cuenta (véase «Garantías y límites» del README).
- Mira la media real en **Cobertura y capacidad** antes de tocar nada: mide
  llamadas, tokens y segundos de tu instalación.

## 3. Volumen y cobertura

Un journal activo produce mucho más de lo que un modelo lento revisa. En el equipo
medido, con «todas las líneas», **el 96 % de 25 107 eventos retenidos quedó fuera
de revisión por capacidad**, y un solo servicio (`python`) aportaba el 84 %. Un
servicio activo y bien configurado no demuestra que se esté revisando.

- Para modelos lentos, usa en la fuente el modo **prioridad + palabras** con
  prioridad ≤ 4, palabras de disparo y 5 minutos de contexto. Es menos cobertura, y
  el portal lo dice.
- Previsualiza cualquier regla de exclusión antes de guardarla. No excluyas un
  servicio entero, `INFO` o una IP por una coincidencia amplia: la prioridad del
  journal la elige el productor y no es una frontera de confianza.
- Los detectores deterministas (OOM, disco, `sudo`, SSH) funcionan sobre los
  originales aunque el modelo no llegue.

## 4. Acceder al panel desde otro equipo

El panel solo escucha en loopback (`127.0.0.1:8765`). Se accede por túnel SSH:

```bash
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -L 8765:127.0.0.1:8765 usuario@equipo-del-portal
```

y se abre `http://127.0.0.1:8765` en tu navegador.

**Si el equipo del portal está tras NAT**, ábrele un túnel inverso hacia un servidor
que sí alcances, y desde tu portátil otro hacia ese servidor:

```bash
# En el equipo del portal
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:18765:127.0.0.1:8765 usuario@servidor
# En tu portátil
ssh -NT -L 8765:127.0.0.1:18765 usuario@servidor
```

- El puerto remoto queda ligado al loopback del servidor. **No uses
  `-R 0.0.0.0:…`** salvo que quieras publicar deliberadamente un panel
  administrativo.
- El servidor debe permitir `AllowTcpForwarding` (al menos `remote`).
- Para que sobreviva a cortes, usa `autossh` o una unidad systemd con
  `Restart=always`.

## 5. Servicio de usuario o de sistema

`logsentinel service install` instala una unidad **de usuario**
(`systemctl --user`). Necesita una sesión con bus de usuario; si no la hay
(`systemctl --user` responde que no puede conectar), tienes dos caminos:

- `sudo loginctl enable-linger USUARIO` para que el servicio de usuario viva sin
  sesión abierta, o
- `sudo logsentinel service install --system --run-as USUARIO`: unidad de sistema
  que ejecuta el proceso con esa cuenta, sin privilegios de root. (`--allow-root`
  existe pero no se recomienda.)

Ambas unidades usan el puerto 8765; para otro puerto o para el receptor de red,
edita `ExecStart` (véase `GUIA_EQUIPOS.md`) y reinicia, sin lanzar otro proceso
sobre la misma base.

## 6. Vigilar el propio portal

Un portal parado no puede avisar de que está parado. `GET /healthz` responde **200**
si todo va bien y **503** si algún componente está degradado; no requiere sesión.
Vigílalo desde fuera, por ejemplo con un temporizador o una tarea programada:

```bash
curl -fsS http://127.0.0.1:8765/healthz > /dev/null || echo "LogSentinel no responde" | mail -s aviso tu@correo
```

(o cualquier otro aviso que uses). La pestaña **Salud del observador** detalla
qué componente falla mientras el portal está en marcha.

## 7. Emisores remotos: cuotas, códigos y permisos

- Cada fuente remota tiene una cuota (por defecto **256 MiB/h y 200 000 eventos/h**,
  editable en **Modelo y análisis**). Si se agota, el receptor responde **429** con
  `Retry-After` y el emisor espera y reintenta sin perder nada.
- Con la cuota de almacenamiento llena responde **507**: el emisor conserva su cola
  y su cursor y reintenta. Conserva los archivos originales hasta resolverlo.
- `logsentinel spool-status --spool RUTA` muestra el estado de la cola de un emisor, incluidos los eventos **rechazados**: si el receptor contesta 400 o 422 a un
  lote, el emisor pasa a enviar de uno en uno, aparta el evento rechazado con estado `rejected` (queda en la cola para inspeccionarlo) y sigue con los demás.
- Para detectar un emisor que se calló, pon en la fuente un **Plazo sin señal del emisor remoto**
  de 180 s (por defecto es 0: no vigila la ausencia).
- Tres permisos distintos, que no deben mezclarse: **leer los logs del cliente**
  (la cuenta sin login del emisor, solo lectura de esas rutas), el **token de
  fuente** (solo escribir eventos de esa fuente) y la **clave del panel** (todo).

## 8. Métricas de otros equipos

`logsentinel metrics-forward --receiver URL --machine-id ID --interval 60` envía
CPU, RAM, disco y carga de un Linux con cola durable. El token va en la variable
de entorno `LOGSENTINEL_METRICS_TOKEN`; el intervalo mínimo es de 10 s. Actualiza
primero el central y después los emisores, y usa el mismo intervalo en ambos.

Coste medido por muestra: unos **330 bytes** comprimidos, 12 ms de reloj y 3 ms de
CPU; a 60 s, unos **0,45 MiB al día por máquina**. Se conservan 30 días de muestras
y 365 de resúmenes diarios (mínimos y máximos). La ventana de 10 000 muestras cubre
24 horas con intervalos de 10 s o más.

## 9. Copias de seguridad

**Copias** en el portal crea una copia coherente y conserva las cinco últimas.
Contiene los logs originales y todas las credenciales. Para restaurar:

```bash
logsentinel restore /ruta/copia.db --data-dir /ruta/nueva
```

El destino debe no existir. Después rota la clave del panel, los tokens de fuente y
las credenciales de los destinos.

## 10. Registros de Apache y nginx

Una fuente de **archivo** o **carpeta** apuntada a `/var/log/nginx/` o `/var/log/apache2/` con el patrón `access.log*` basta: las líneas en formato común o
combinado, que es el de por defecto de ambos servidores, se reconocen solas, sin campo de formato. Sin **Importar histórico al iniciar**, una fuente de archivo o carpeta empieza por el final de cada archivo y salta los rotados (`.gz`, `.xz`, `.bz2`); con esa opción se leen enteros y los rotados se importan también. Las
líneas que llegan por un emisor remoto, o reenviadas por syslog, se reconocen igual. Un formato personalizado que no encaje se lee como texto normal. La cuenta que
lee necesita permiso sobre esos archivos (por ejemplo, el grupo `adm` en Debian y Ubuntu).

**Qué se guarda y qué ve el modelo.** Cada petición es un evento con la hora que escribió el servidor, el cliente, el método, la ruta con su consulta, el estado, el
tamaño, el origen y el agente; la línea original sigue intacta. **Ninguna entra en la revisión automática del modelo**, sea cual sea el modo de análisis de la fuente: se marcan como
«muestreadas» y los detectores trabajan sobre todas. En una carpeta que mezcla `access.log` y `error.log`, el error sí sigue el flujo normal, sin las peticiones como contexto, como vecinas en la verificación ni en la búsqueda de la investigación. La única excepción es el asistente: si le preguntas por un problema web, esas peticiones son su evidencia y se le envían (con los secretos ocultos y respetando `remote_allowed`).

**Qué detecta.** Cada detector abre un problema por fuente que se va actualizando, con un resumen de cuántas peticiones fueron, de cuántos clientes, entre qué horas,
con qué códigos y a qué rutas (sin la consulta, donde acaban los tokens).

| Detector | Umbral | Gravedad |
|---|---|---|
| Ráfaga de errores del servidor | 10 respuestas 5xx en 5 minutos | HIGH |
| Intentos repetidos de login | 20 POST a páginas de login en 5 minutos, y un mismo cliente con 15 | HIGH |
| Ruta sensible servida | un `GET` a `.env`, `.git`, claves, volcados o copias con respuesta 200 o 206 | MEDIUM |
| Cargas de ataque | 5 peticiones con SQL, XSS, recorrido de rutas, JNDI o comandos en 10 minutos | LOW |
| Sondeo de rutas sensibles | 10 peticiones a secretos o paneles de administración en 10 minutos | LOW |
| Enumeración de rutas | 60 respuestas 404 en 5 minutos, un cliente con 40 y 30 rutas distintas | LOW |

Los umbrales están fijados en el código en esta versión. Los destinos avisan por defecto desde MEDIUM, así que los LOW (sondeos, escaneo de rutas y cargas de ataque) no avisan: en un servidor público llegan todo el día y existen para ver quién lo hace y qué respondió el servidor. Si quieres avisos de ellos, baja el umbral del destino a LOW. Un 200 o un 500 ante una carga de ataque merece mirar la aplicación aunque el problema sea LOW.
Las rutas y los fragmentos se comparan tras decodificar la URL dos veces y pasar a minúsculas, de modo que `%2e%65nv` y `.ENV` son `.env`.

**Qué hay que saber.**

- **En la cobertura aparecen aparte.** El monitor y «Cobertura y capacidad» cuentan las peticiones web como «peticiones web: las vigilan los detectores y el modelo
  no las lee, como está previsto», en tono neutro y sin sumarlas a lo que una fuente deja fuera por su selección, que sigue siendo un aviso. «Recuperar retenidos sin
  analizar» no las vuelve a poner en la cola.
- **El cliente es la dirección que vio el servidor.** Detrás de un proxy inverso o un CDN será la del proxy y los resúmenes serán inútiles. Haz que el servidor la
  reescriba antes de registrar: en nginx `set_real_ip_from` y `real_ip_header X-Forwarded-For`; en Apache `mod_remoteip` con `RemoteIPHeader`. El portal no usa la
  cabecera `X-Forwarded-For` de la línea porque cualquiera puede enviarla falsificada.
- **Un 200 en `/.env` no prueba una fuga.** Muchas aplicaciones de una sola página responden 200 con su página de inicio a cualquier ruta. El problema lo dice y pide
  comprobar el contenido.
- **Varios usuarios tras una misma IP** (una oficina, una red móvil) pueden sumar intentos de login. Por eso un solo cliente debe concentrar al menos 15.
- **Importar histórico puede avisar de ráfagas pasadas.** Que un evento sea «en vivo» se decide por cuándo se recibe, no por cuándo ocurrió, igual que con SSH. Las
  ráfagas pasadas se juntan en un problema por detector y fuente.
- **Las direcciones de quien visita son datos personales** en la UE. Los originales se conservan `retention_days` (30 por defecto) comprimidos; redúcelo si no hace falta
  más. Las notificaciones incluyen direcciones y rutas.
- **Lo que no es.** No es un panel de visitas ni mide visitantes únicos, y no bloquea nada: «No bloquees direcciones automáticamente» sigue valiendo.

## 11. Carga sobre los equipos

Las unidades que generan `service install` y `setup-client` limitan lo que el programa puede consumir:

- **Emisor:** `Nice=10`, 25 % de una CPU, 192 MiB de memoria con aviso y 256 MiB de tope, y es el primer candidato si el sistema se queda sin memoria
  (`OOMScoreAdjust=500`). Lee a lo sumo 1000 líneas o 256 KB por archivo cada 2 s, y se detiene si la presión de E/S del kernel (`/proc/pressure/io`)
  supera el 25 %, si quedan menos de 256 MiB libres o si su cola llega al tope.
- **Central:** `Nice=5`, E/S de prioridad baja, aviso de memoria a 768 MiB sin tope duro (una importación grande debe terminar, aunque sea despacio).
  Sin límite de CPU por defecto porque los detectores la necesitan; en un equipo compartido, `service install --cpu-quota 50`.
- `IOWeight` e `IOSchedulingClass=idle` solo actúan con el planificador de E/S `bfq`; con `none` o `mq-deadline` (lo habitual en NVMe) no hacen nada.
  Compruébalo con `cat /sys/block/DISPOSITIVO/queue/scheduler`.
- **Exceso de líneas en un emisor.** La cola admite 100 000 eventos o 1 GiB. Por encima del 60 % de cualquiera de los dos, el emisor deja de guardar las
  **repeticiones rutinarias** (una forma de línea vista más de cien veces en esa fuente y sin gravedad) y las cuenta; las líneas raras, nuevas o con
  prioridad 0-3 se guardan y se envían primero. Al bajar del 60 % guarda una línea de resumen por forma («N routine lines like this were not stored
  between … and …») que el central revisa como cualquier otra. Al 100 % se para la captura, como antes. Se desactiva con `"shed_routine": false` en los
  `limits` del emisor; sin ello, el tope se alcanza antes y lo que se pierde por rotación son las líneas más nuevas.
- **El servidor del modelo no lo controla LogSentinel.** Un modelo que no cabe en RAM es lo que más puede colgar un equipo: ponle `MemoryMax` en su
  unidad, usa `-ngl 0` sin GPU, o sírvelo desde otra máquina.

## 12. Qué lee cada sondeo de archivos y carpetas

Una fuente de archivo o carpeta se sondea cada unos 2 segundos. En cada sondeo se lee, **por archivo**, como máximo **1000 líneas o `max_batch_bytes`**
(2 MB en el portal, 256 KB en un emisor), lo que ocurra antes. Los archivos de una carpeta no se quitan el turno unos a otros, pero las fuentes se sondean en
secuencia. Con líneas de unos 100 bytes eso son unas 500 líneas por segundo y archivo: un histórico de 100 MB tarda en torno a media hora en entrar (estimación,
no medida). Al ver «pendientes» durante un rato tras activar una fuente grande, es lo normal.

- **Archivos nuevos y «Importar histórico al iniciar».** Sin la opción, una fuente empieza por el final de cada archivo que encuentra y salta los rotados
  (`.gz`, `.xz`, `.bz2`). Activarla después **sí importa** lo que se saltó, sin duplicar lo ya leído.
- **Archivos comprimidos.** Se importan cuando su tamaño y fecha no han cambiado durante un sondeo entero, así que llegan uno o dos sondeos después del archivo
  normal. Se descomprimen desde el principio en cada sondeo hasta su posición, de modo que un archivo muy grande tarda cuadráticamente más (esto sale de leer
  el código, no está medido).
- **Líneas de más de 256 KB.** Se corta el final: se guarda el principio, con una nota en el texto («line cut: about N more bytes were not stored») y `cut_bytes`
  en el evento, y se sigue con la línea siguiente. Una línea que aún se está escribiendo, sin salto de línea, espera a su final.
- **Rotación.** El cursor sigue al archivo, no al nombre, así que `app.log` → `app.log.1` → `app.log.2` no repite líneas. Dos casos sí releen cuando el histórico
  está activado, porque el archivo resultante es nuevo y no se puede saber que su contenido ya se leyó: `copytruncate` (la copia es un archivo nuevo) y la
  compresión retrasada (`app.log.2.gz` es un archivo nuevo con lo que antes se leyó como texto). Sin «Importar histórico» no ocurre.
- **Un archivo borrado** se sigue drenando mientras alguien escriba en él y se suelta a los cinco minutos sin actividad.

## 13. Sobre las ilustraciones

Las imágenes de Tentri (`logsentinel/portal/static/tentri-*.png`) son arte
generado para este proyecto. No son una marca oficial de Omarchy ni de ningún otro
proyecto.
