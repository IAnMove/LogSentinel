# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Cada entrada corresponde a un commit; su mensaje explica el porqué.

## Sin publicar

Revisión general de fiabilidad, seguridad y mantenimiento (rama `review/hardening-2026-09`).

### Cambia el comportamiento

- **Avisos.** Un hallazgo HIGH o CRITICAL que el modelo no pudo verificar (la verificación no cabe, falla tres veces o queda incierta) se notifica marcado como *sin verificar* en lugar de quedarse en silencio. Un lote revisado tarde (cola larga, caída del modelo) avisa si los eventos son de las últimas seis horas y el hallazgo es grave; el histórico antiguo sigue en silencio.
- **Caídas del modelo.** Si el servidor del modelo no responde, el lote no gasta sus tres intentos: se reintenta con espera creciente.
- **Registros web.** Una línea de `access.log` de Apache o nginx ya no se trata como texto libre: se reconoce, se fecha con la hora del servidor y no entra en la revisión automática del modelo, tampoco como contexto de otra línea ni como vecina en la verificación; solo el asistente la ve, cuando preguntas por un problema web. Quien ya alimentaba registros de acceso verá esas peticiones como «muestreadas» en la cobertura y los hallazgos de los nuevos detectores en lugar de lotes para el modelo. Los `error.log` no cambian.
- **Alta de emisores.** El instalador y `logsentinel enroll` exigen la huella SHA-256 del certificado del central (`--ca-fingerprint`, o pegarla en un terminal). Los scripts que instalaban un emisor sin ella dejan de funcionar hasta que la reciben; véase `GUIA_EQUIPOS.md`.
- **Base de datos.** Migraciones numeradas (versión 3): índices que faltaban, marca de urgencia por evento. Los trabajos terminados, el historial de entregas, el consumo de tokens y la auditoría dejan de crecer sin límite. `VACUUM` solo se ejecuta cuando compensa y hay disco para una copia. Las copias de seguridad se hacen de forma atómica, se rechazan si no caben y solo se conservan las cinco últimas.
- **Orden de revisión.** Con cola mayor que un lote se revisan antes los originales con prioridad de syslog 0–3.
- **Interfaz.** Los archivos estáticos públicos se revalidan o cachean en lugar de `no-store`; las respuestas de rechazo llevan también las cabeceras de seguridad. El nombre «Media» del promedio de métricas pasa a «Promedio» para no chocar con la severidad Media.
- **Ajuste `sensitivity`.** El prompt de triaje ahora explica qué significa cada nivel (antes no tenía efecto).
- **Fuentes.** Una carpeta con un archivo ilegible sigue leyendo los demás y lo dice; lee los 100 más recientes (antes los 100 primeros por nombre); los comprimidos respetan «importar histórico»; los archivos borrados liberan su descriptor; `journalctl` se invoca con `--all`. Las fechas syslog sin año nunca caen en el futuro y las que carecen de zona usan la de la máquina.
- **Rutas prohibidas como fuente.** Directorios de credenciales (`.ssh`, `.aws`…), claves, `.env`, `/proc`, `/dev`, los directorios personales y las carpetas que contengan credenciales.
- **Reinicio de `./portal`.** Ya no actualiza pip ni consulta el índice en cada arranque.

### Seguridad

- Redacción de secretos ampliada (JSON, `Authorization: Basic/Token`, credenciales en URL, `--password`, cookies, prefijos de token conocidos). La CLI antigua recibe la misma redacción, el transporte comprobado y notificadores sin menciones ni markup activo.
- La autenticación del receptor precede a la lectura del cuerpo; el límite de tamaño se aplica mientras se lee. El receptor de red limita las conexiones simultáneas. Los intentos fallidos de alta se cuentan por dirección.
- El detector de inyección exige forma de instrucción (menos falsos positivos con `llama-server`) y no se evade con espacios, caracteres invisibles ni español; el verificador no puede descartar un hallazgo causado por un log hostil.
- Un `TimeoutError` de una línea hostil ya no bloquea la detección de la máquina. El detector SSH reconoce `sshd-session` (OpenSSH 9.8).
- Unidad systemd del emisor más confinada; copia de seguridad de la actualización del cliente realizable por la cuenta sin privilegios; un emisor con CA fijada no vuelve a las públicas; un archivo `.xz` no puede exigir memoria ilimitada; blocklist SSRF ampliada; permisos 0600 en el paquete de alta y en los archivos de la CLI antigua.
- `hmac.compare_digest` con caracteres no ASCII ya no produce un 500; solo los inicios de sesión fallidos gastan el límite.

### Añadido

- `scripts/check_publishable.py`: busca rutas personales, secretos y nombres internos en el árbol y en todo el historial (`--history`), y dice qué ramas alcanzan cada hallazgo. Una prueba lo ejecuta.
- `scripts/check_wheel.py`, `scripts/check_i18n.js`, ruff y mypy en la CI, los once recorridos de navegador y Python 3.14.
- Registro del servidor con traza, redactado y sin repeticiones (`logsentinel.portal.logs`).
- `SECURITY.md`, `CONTRIBUTING.md`, `README.en.md` y este archivo; el README empieza por el producto e incluye «Garantías y límites».
- Más casos en el corpus de evaluación (español, traza multilínea, secretos, OpenSSH 9.8, inyección en español, ruido de servidores de modelos).

- Vista de seguridad web (`logsentinel/portal/web_access.py`, `web_signals.py`): lector estricto del formato común y combinado, y seis detectores deterministas (errores 5xx, intentos de login, secretos servidos, sondeos, enumeración de rutas y cargas de ataque) con un resumen de clientes, códigos y rutas en cada problema. Las señales admiten ahora `match`, `digest` y `confirm`. Ver `OPERACION.md`.

### Arreglado

- La lectura de una carpeta abortaba en el primer archivo con error; un archivo `.gz`, `.xz` o `.bz2` truncado hacía caer el emisor en bucle.
- Una línea de 256 KB con `authentication failure;` detenía la detección de su máquina.
- El borrado de eventos recorría toda la tabla `signal_hits` por cada evento (35 s para 5 000 eventos con 100 000 aciertos; 0,08 s con el índice).
- Dos portales arrancando a la vez podían fallar con `duplicate column name` al migrar.
- Claves de traducción duplicadas o ausentes; contraste del texto atenuado del tema clásico; sondeos que se solapaban o seguían con la pestaña oculta; regiones `aria-live` que se reconstruían cada pocos segundos.
- La CLI antigua: `audit.*denied` nunca coincidía, el modelo bloqueaba la lectura de logs hasta dos minutos, los archivos de datos eran legibles por todos.
- Una prueba de telemetría fallaba entre las 00:00 y las 00:05 UTC.

### Arreglado tras la segunda revisión (octubre)

- **Registros web y modelo.** Las peticiones de un registro de acceso ya no llegan al modelo como vecinas de una línea en la verificación, ni en la muestra del asistente sin problema elegido, ni en la búsqueda de la investigación. El asistente las sigue viendo cuando preguntas por un problema web, porque son su evidencia.
- **Una línea larga ya no cuelga el portal.** `grouping_key` quitaba los contadores finales con una expresión cuadrática: 8 KB de « 1» tardaban unos diez segundos y 256 KB, horas, bloqueando también la recepción. Ahora se hace por palabras, en tiempo lineal.
- **Una línea de más de 256 KB ya no para la fuente.** Antes lanzaba un error sin avanzar el cursor y la fuente se quedaba leyendo la misma línea para siempre; el emisor reintentaba sin fin. Ahora se conserva su principio con una nota visible («line cut: about N more bytes were not stored»), se anota `cut_bytes` en el evento y se sigue con la siguiente.

- **La rotación numerada ya no repite líneas.** Con la rotación por defecto de logrotate (`app.log` pasa a `app.log.1`, éste a `app.log.2`), el nombre `app.log.1` conservaba el cursor del archivo del ciclo anterior y el archivo recién llegado se leía de cero con un origen nuevo: cada línea contaba una vez más en cada ciclo (cuatro veces tras cinco ciclos, lo que además inflaba los contadores de ráfagas). El cursor se busca ahora por archivo y no solo por nombre.

- **«Importar histórico» activado después ahora importa.** En un archivo normal que ya se estaba leyendo, el cursor quedaba al final y la opción no hacía nada, aunque la guía rápida y el asistente prometían lo contrario (con los archivos comprimidos sí funcionaba). El cursor recuerda que nació saltándose lo existente y, si luego se activa el histórico, relee desde el principio con la misma generación: los orígenes son posiciones y lo ya leído no se duplica.

- **Cancelar una verificación ya no deja un hallazgo grave en silencio.** El triaje guarda los candidatos HIGH y CRITICAL sin avisar, a la espera de la verificación. Si el trabajo se cancelaba antes (porque cambió el modelo, caducó la evidencia o una regla de exclusión la cubre), el problema quedaba abierto y sin notificación. Ahora se avisa como «sin verificar», igual que cuando la verificación falla.

- **El portal ya no se queda en blanco con el almacenamiento del navegador bloqueado.** `sessionStorage` se leía y escribía sin protección en tres sitios (a diferencia de `localStorage`), y al lanzar una excepción `refresh()` fallaba antes de mostrar nada tras iniciar sesión. Ahora pasa por dos ayudantes que ignoran el error. No lo he probado en un navegador real (solo sintaxis, el chequeo de traducciones y la batería de Python).

- **El receptor responde 400, no 500, a un cuerpo que no es JSON.** `/enroll`, `/ingest` y `/heartbeat` lanzaban una excepción sin manejar, con traza en el journal, ante `{{` o bytes inválidos. `/enroll` no pide autenticación, así que cualquiera con acceso al puerto podía llenar el registro de trazas. Una petición con token malo sigue recibiendo 401 antes de que se lea el cuerpo.

- **Dos lecturas ocultaban menos secretos que el resto.** `/api/state` devolvía los problemas tal como se guardaron, de modo que un secreto añadido después (un destino nuevo cuya URL ya aparecía en un problema) volvía a la pantalla; `/api/problems` sí lo saneaba. Y el prompt para pegar en otro servicio solo ocultaba la clave del modelo, no los tokens y URLs de los destinos ni las claves de acceso retiradas. Ambos usan ya `protected_secrets`.

- **Una petición mayor que la cuota horaria ya no se rechaza para siempre.** Con una cuota de 1 MiB/h y lotes de 2 MiB, el emisor recibía 429 una y otra vez, también con la ventana vacía, y no avanzaba nunca. Una ventana vacía admite ahora una petición (acotada por el límite de cuerpo); la siguiente espera.

- **Una fuente de archivo suelta el descriptor de un archivo borrado.** Se quedaba abierto mientras el portal siguiera en marcha (las carpetas ya lo hacían bien); ahora pasa a la vigilancia de rotación, que lo cierra tras cinco minutos en silencio.

- **El colector documenta sus límites reales** (`OPERACION.md`, sección 11): 1000 líneas o `max_batch_bytes` por archivo y sondeo, qué hace «Importar histórico» al activarse después, los archivos comprimidos, las líneas cortadas y los dos casos de rotación que releen con el histórico activado (`copytruncate` y compresión retrasada).

### Mantenimiento

- `httpx` deja de aceptar una ruta en `verify=` en su próxima versión mayor. El emisor y el alta con CA propia pasan ahora un contexto TLS que solo confía en esa CA (`network.private_authority`), y una regla de pytest convierte esa obsolescencia en error para que no vuelva.
- `create_app` (1 300 líneas) se divide en módulos por área en `logsentinel/portal/routes/`; las rutas y su resolución son las mismas.
- Las fixtures compartidas viven en `conftest.py`; las pruebas ya no dependen de la presión de disco del equipo ni de esperas fijas.
- Metadatos del paquete coherentes (versión única, `setuptools>=77`, cotas superiores, dependencias directas declaradas).

### Pendiente (candidatos rescatados de notas de trabajo antiguas)

Cada uno está comprobado contra el código actual y no se ha hecho todavía:

- **Emisor de métricas remoto.** `metrics-forward` no fija la CA del central (no valida un certificado local), el token solo entra por variable de entorno y no hay unidad systemd ni opción en `setup-client.sh`. Propuesta: `--ca-cert` reutilizando `receiver-ca.pem`, `--token-file` y `setup-client.sh --metrics`.
- **`service install` sin opciones.** Fija el puerto 8765 y no admite `--port`, `--ingest-listen` ni TLS, así que el receptor de red exige editar `ExecStart` a mano. `portal` imprime la URL antes de comprobar que puede enlazar el puerto y no explica que falte el bus de usuario de systemd.
- **Timeout por defecto de 120 s** frente a modelos lentos en CPU (medido: unos 8 tokens/s, media de 75 s por llamada). Propuesta: avisar en «Cobertura y capacidad» cuando la mediana supere la mitad del timeout, y valorar 240 s para servidores locales.
- **Estimación de tokens con llama.cpp.** Solo se aplica la relación medida tokens/byte con Ollama; con llama.cpp se asume un token por byte y se desperdicia contexto. `/props` daría el contexto real.
- **Emisor caído sin detectar por defecto.** El plazo sin señal de una fuente remota es 0; propuesta: 180 s al emitir el alta.
- **Modo «Adaptativa».** Es un alias exacto de «prioridad + palabras» pero la interfaz sugiere otra cosa.
- **Métricas.** Días hasta llenar el disco (regresión lineal sobre los resúmenes diarios), presión PSI, límites de cgroup, temperaturas y SMART.
- **Evaluación.** Caso «aguja en pajar» (un fallo entre cientos de líneas rutinarias), control negativo de 24 h, y que `evaluate_review.py` distinga una caída de infraestructura (código de salida propio) de un fallo de calidad.
- **Feedback de la CLI antigua.** Diferenciar falsa alarma, cambio legítimo de hábito y autorización temporal; correlación SSH, `sudo`, proceso y conexión saliente.

### Pendiente (ideas surgidas al trabajar en los registros web)

- **Resumen de los fallos SSH.** `ssh_auth_failures` dice «varios fallos» sin cuántos, desde cuántas direcciones, qué usuarios probaron ni si hubo un acceso aceptado. Los detectores web ya resumen así; falta el equivalente, con la lista de usuarios acotada y sin enviarla a los destinos externos sin decidirlo (a veces se escribe la contraseña en el campo de usuario).
- **GeoIP.** País y proveedor por dirección, con una base local (DB-IP Lite no pide cuenta; GeoLite2 sí) descargada de forma explícita y verificada, nunca automática.
- **`reasoning_effort`** hacia Ollama por `/v1`, para que el razonamiento no consuma el presupuesto de salida del JSON.
- **Cobertura de las fuentes web.** Una fuente de acceso sana aparece con el 100 % «por selección de fuente», con estilo de aviso en el monitor y en «Cobertura y capacidad». Falta un contador propio para las peticiones web y un texto que diga que es lo esperado.
- **Umbrales de los detectores web** configurables, y un panel por fuente web. Un panel de visitas es otro producto y queda fuera.

### Sin cambiar a propósito

- Las ilustraciones de Tentri (21 MB) siguen en el paquete: la galería «Ver todas las ilustraciones» las usa.
- La CLI antigua (`logsentinel run`) se conserva por compatibilidad, endurecida pero sin las mejoras de flujo del portal.
- Sin salida estructurada por esquema JSON: cada servidor de modelos la implementa distinto y no se puede comprobar aquí sin ellos.
