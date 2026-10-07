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

### Arreglado tras la tercera revisión (octubre)

- **Los patrones de los detectores se compilan una vez.** Se pasaban como texto en cada línea; medido sobre 100 000 líneas, las señales bajan de 25 a 12 µs por línea, el detector de instrucciones de 87 a 36 y la clave de agrupación de 14 a 3.
- **Las fuentes de archivo también tienen prioridad.** Solo el journal traía prioridad de syslog, así que la vía urgente (prioridad 0-3, hasta tres cuartos de cada lote) nunca se usaba con archivos: un OOM del kernel en `kern.log` esperaba detrás de todo lo anterior. Una línea de archivo sin prioridad recibe 2 si el kernel mata, entra en pánico o falla el disco, 2 si lleva un nivel CRITICAL/FATAL/EMERG/ALERT/PANIC escrito como nivel, y 3 si lleva ERROR; el resto queda sin prioridad. **Cambia el comportamiento** del modo «prioridad» en fuentes de archivo: esas líneas pasan a seleccionarse por nivel, como promete el modo, y no solo por palabras.
- **El emisor entrega diez veces más deprisa y lo urgente primero.** Enviaba 100 eventos cada 2 s (50 por segundo, una décima parte de lo que captura), así que cualquier ritmo sostenido superior llenaba la cola; ahora envía hasta 500 por petición, el máximo que admite el receptor, y mientras la cola va atrasada encadena las peticiones sin la pausa de reposo. La cola era estrictamente FIFO: ahora las líneas urgentes (prioridad 0-3) salen antes que la rutina pendiente.
- **Las unidades de systemd acotan CPU y memoria.** El emisor: 25 % de una CPU, 192/256 MiB y candidato preferente del OOM; el central: `Nice=5`, E/S de prioridad baja, aviso de memoria a 768 MiB sin tope duro y `--cpu-quota` opcional. `OPERACION.md` explica qué hace cada límite y que `IOWeight`/`idle` requieren `bfq`.
- **Ningún evento guardado o enviado supera los 256 KB, se mida como se mida.** El corte de ayer solo actuaba sobre líneas largas en disco; una traza multilínea unida o una línea con bytes inválidos (cada uno pasa a tres al decodificar) podían llegar a 300 KB, y el receptor rechazaba con 400 el lote entero. El límite se aplica ahora al texto ya decodificado y unido, en el colector y en el receptor, que recorta en vez de rechazar (hasta cuatro veces el límite; más allá no es una línea de log). El tamaño de captura del emisor baja de 262 144 a 256 000 por la misma razón.

- **Un registro del journal mayor que el lote ya no para la fuente.** Igual que ayer con los archivos: lanzaba error en cada sondeo sin avanzar el cursor. Ahora se relee con margen para un registro (hasta 8 MiB), se recorta a 256 KB con la nota de corte y el cursor sigue.

- **Un evento que el receptor rechaza ya no bloquea la cola del emisor.** Ante un 400 o 422 el emisor reenviaba el mismo lote cada minuto para siempre, con todo lo posterior esperando y el latido en «ok». Ahora reduce el lote a un evento hasta dar con el rechazado, lo aparta con estado `rejected` (visible en `spool-status`) y continúa. Los 401/403/409/429 y los errores del servidor se tratan como antes.

- **Una entrega atascada se ve en el central.** El latido del emisor solo reflejaba la captura, así que una cola bloqueada aparecía en «ok». Ahora, si la entrega lleva más de diez minutos fallando, el latido marca la fuente en error con el código `delivery_blocked` y comunica cuántos eventos se apartaron como rechazados; la ficha de la fuente lo muestra. Los emisores antiguos siguen aceptados.

- **Un token de métricas ya no puede abrir problemas sin límite.** Cualquier clave `disk_pct:/ruta` contaba como disco y disparaba al 99 %: 100 claves inventadas abrían 100 problemas y 100 avisos en dos segundos. Ahora una muestra admite como máximo 16 montajes y, si declara `disks`, solo esos; cada máquina puede abrir 20 problemas de recursos por hora (el resto se anota como error de telemetría de la máquina); `/ingest-metrics` cobra la misma cuota horaria que los logs; y la tabla de estados de alerta se poda con las muestras. Una muestra que no encaja en su modelo recibe 422 del receptor, no un 500.

- **Un aviso ya no lleva las credenciales de otro destino.** El texto saliente se ocultaba solo con el token y el secreto del destino que lo recibía; la URL del webhook del destino B, citada en un log, llegaba al archivo de avisos del destino A. Ahora se ocultan todos los secretos protegidos, y `/api/state` sanea también las entregas en cola (ayer solo los problemas).

- **`restore` copia también lo que aún está en el WAL y da una clave nueva.** Copiaba solo el archivo principal, así que restaurar desde la base de datos de un portal en marcha perdía las últimas filas confirmadas (las copias de «Copias» no se veían afectadas). Usa la copia en línea de SQLite, rota la clave de acceso en vez de escribir la antigua, y un archivo que no es una base de datos recibe un mensaje claro en lugar de una traza.

- **Detector de instrucciones en los logs, afinado en tres puntos.** «Ignore all instructions…», el propio caso inglés del corpus, no se detectaba (el patrón exigía *previous/prior/above*); «Mensaje del sistema:», prefijo habitual de aplicaciones en español, disparaba un HIGH y ahora necesita «nuevo» o «actualizado», como el patrón inglés; las reglas de exclusión se respetan también en este detector, que las ignoraba; y un hallazgo de inyección resuelto a mano ya no se reabre ni vuelve a avisar con la siguiente línea parecida (los demás hallazgos sí reabren, porque un OOM que se repite es noticia). El caso del corpus lleva ahora su expectativa, que antes no tenía.

- **Un problema que va y viene ya no avisa en cada vuelta.** El enfriamiento comparaba solo con la última entrega, fuera del tipo que fuera, así que alternar «recuperado» y «actualizado» lo saltaba siempre (lo producen los chequeos de salud y de recursos). Ahora compara con la última entrega del mismo tipo, y la primera recuperación de la ventana reinicia el aviso (una recurrencia real sigue saliendo): como mucho aviso, recuperación y recurrencia por ventana, salvo subida de gravedad.

- **Otra expresión cuadrática, en la compactación.** El reconocimiento de líneas de apscheduler (`Running job "…" (scheduled at …)`) tardaba 1,5 s con una línea hostil de 256 KB; el nombre del trabajo ya no admite comillas y la prueba de texto hostil cubre ahora también las líneas de unidades de systemd, que ayer no alcanzaba.

- **`service install --system` avisa si la cuenta no puede llegar al intérprete** (la instalación documentada es un venv en el home del instalador, normalmente 0700, y la unidad fallaba al arrancar con `--run-as`), y admite `--port`, `--ingest-listen`, `--tls-cert` y `--tls-key`, que antes exigían editar `ExecStart` a mano.

- **`prepare-host --account` se valida.** El nombre llegaba tal cual a `useradd`, `usermod` y `setfacl` (`--help` o `a:b` los hacían comportarse de forma rara); ahora debe tener forma de nombre de cuenta, y una cuenta existente no puede ser root ni una cuenta con shell de login, igual que exige el instalador de clientes.

- **`enroll` no liga una cola a otra fuente.** Canjear un paquete de otra fuente o receptor sobre una cola ya en uso sobrescribía el token y `forward` rechazaba después la cola; ahora se rechaza antes de canjear nada. Volver a dar de alta la misma fuente (para rotar el token) sigue permitido.

- **`metrics-forward` confía en la CA fijada del central** si la cola contiene `receiver-ca.pem` (lo deja el alta), como hace ya el emisor de logs; antes solo probaba las autoridades del sistema y un central con CA propia era inalcanzable.

- **El instalador dice cuándo no canjea un paquete.** Repetir `setup-client` con un paquete nuevo sobre una instalación existente actualizaba el programa y conservaba la credencial antigua sin decirlo; ahora avisa de que el paquete no se canjea y da el comando de rotación (`logsentinel enroll` como la cuenta del emisor y reinicio de la unidad).

- **Un fallo al registrar una condición de salud no aborta el chequeo.** Solo se capturaba `OSError`; cualquier otro error (base de datos ocupada) interrumpía el ciclo, la instantánea dejaba de refrescarse y al minuto `/healthz` daba 503 por «stale». Ahora la condición queda visible con el error anotado y se reintenta en el siguiente ciclo.

- **Reintentar a mano una entrega ya entregada responde 409** en vez de enviar el aviso por segunda vez; las fallidas, desconocidas y silenciadas se reintentan como antes.

- **Los avisos de escritorio escapan el marcado.** `notify-send` interpreta el cuerpo como marcado Pango en casi todos los demonios: un `<b>` o un `&` de una línea de log cambiaba o rompía el aviso.

- **Un lote rechazado por el presupuesto antes de enviarse ya no cuenta.** Se contaba como una de las llamadas del ciclo (gastándolas sin petición) y dejaba una fila de consumo en error que la autoajuste del presupuesto leía como fallo del modelo, encogiendo los lotes siguientes hacia el mínimo.

- **Un emisor vuelve a enviar las líneas de un registro de acceso.** Regresión del 4 de octubre: al marcar las peticiones web como «muestreadas» al ingerir, también se marcaban en la cola del emisor, que solo envía las pendientes; un emisor que reenviaba nginx o Apache no entregaba ninguna de ellas y acababa parado por cola llena. La decisión se toma solo en el central; una cola que quedó así se repara sola al arrancar el emisor.

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

- **Un destino de archivo con una ruta que no es un nombre simple se rechaza al guardarlo** (`../../x`, `sub/x`, `..`), no en el primer aviso. La comprobación al enviar se mantiene para los destinos guardados antes.

- **El filtro de metadatos de la nube reconoce NAT64 y 6to4.** `http://[64:ff9b::a9fe:a9fe]/` y `http://[2002:a9fe:a9fe::1]/` llevan la IPv4 169.254.169.254 dentro de una IPv6 y pasaban; el nombre corto `metadata` tampoco estaba. Las direcciones de la LAN y las públicas, también vía NAT64, siguen permitidas.
- **Más rutas que una fuente no puede leer:** históricos de shell y de clientes (`.bash_history`, `.mysql_history`...), `.my.cnf`, `.htpasswd`, `/etc/wireguard`, `/etc/ssl/private` y las conexiones guardadas de NetworkManager.

- **Un `refresh()` lento ya no borra lo que estás escribiendo.** El sondeo de 15 segundos decide si redibujar antes de pedir el estado; si la respuesta tarda y entretanto has abierto un formulario o cambiado de vista, la página se reconstruía y el campo quedaba vacío (reproducido en Chromium con una respuesta retrasada). Ahora se actualizan los datos y la barra de estado y se deja la pantalla como está. Nuevo recorrido de navegador `scripts/refresh_race_smoke.py`, que falla sin el cambio y entra en la CI.

- **Pausar una máquina justo mientras llegan sus eventos da 409, no 500.** Si la pausa cae entre la comprobación del emisor y el guardado, `store.ingest` lanzaba un `ValueError` sin manejar. El emisor ya conservaba su cola con cualquier error; ahora recibe la respuesta que dice que debe reintentar.

- **La reserva del presupuesto de contexto coincide con lo que añade la llamada.** El techo de bytes de un lote reservaba 128 bytes fijos, pero la llamada al modelo añade la cláusula de datos no fiables y la frase de idioma (unos 174), así que un lote empaquetado al máximo podía pasarse del presupuesto comprobado y cancelarse antes de llegar al modelo. La reserva se calcula ahora con las mismas constantes que usa la llamada.

- **Las cabeceras JSON mal escritas de un destino se explican.** Al guardar, el mensaje era el del propio navegador («Expected property name or '}' in JSON at position 1»), en inglés y sin decir de qué campo. Ahora dice, en el idioma del portal, que deben ser un objeto JSON válido y da un ejemplo; también rechaza JSON válido que no sea un objeto (`[1, 2]`, `42`, `null`). Nuevo recorrido `scripts/headers_smoke.py`.

- **Un sondeo que falla se anuncia una vez.** El aviso de error del sondeo de 15 segundos reescribía el mismo texto en la región `role="status"` en cada intento, de modo que un lector de pantalla lo repetía cada 15 segundos mientras durara el fallo. Ahora lo dice una vez y calla hasta que el sondeo vuelve a funcionar. Se comprueba en `scripts/refresh_race_smoke.py`.

- **Una fuente web sana ya no parece un hueco de cobertura.** El monitor y «Cobertura y capacidad» contaban sus peticiones entre lo «apartado por selección de fuente», con estilo de aviso, aunque la fuente funcione como debe. Ahora las cuentan aparte, en tono neutro (`coverage.web` en el monitor y `retained.web` en el informe de capacidad) y dejan el aviso para lo que una selección deja fuera de verdad. Nuevo recorrido `scripts/web_coverage_smoke.py`.

- **Al abrir o cerrar un formulario el foco ya no cae en `body`.** Pulsar Añadir, Editar o Cancelar reconstruye la página y el botón pulsado desaparece con ella, de modo que quien usa teclado o lector de pantalla volvía a empezar desde arriba. Abrir lleva el foco al primer campo; cancelar, al encabezado de la página, como ya hacía cambiar de vista. Comprobado en `scripts/refresh_race_smoke.py`.

### Mantenimiento

- `scripts/portal_smoke.py` registra quién llama a `render()` y `refresh()` desde el paso del destino y, si el clic en «Guardar» agota el tiempo, vuelca esas llamadas con su pila. Ese clic ha fallado de forma intermitente en CI con «element was detached from the DOM» y leyendo el código no se explica; la próxima vez el fallo dirá qué reconstruyó la página.
- CI: Python 3.11 entra en la matriz (el proyecto declara `>=3.10`, pero se probaban 3.10, 3.12, 3.13 y 3.14) y `pip` usa caché. Se probó 3.11 en local con la batería completa y los doce recorridos de navegador.
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
- **Umbrales de los detectores web** configurables, y un panel por fuente web. Un panel de visitas es otro producto y queda fuera.

### Sin cambiar a propósito

- Las ilustraciones de Tentri (21 MB) siguen en el paquete: la galería «Ver todas las ilustraciones» las usa.
- La CLI antigua (`logsentinel run`) se conserva por compatibilidad, endurecida pero sin las mejoras de flujo del portal.
- Sin salida estructurada por esquema JSON: cada servidor de modelos la implementa distinto y no se puede comprobar aquí sin ellos.
