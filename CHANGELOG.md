# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Cada entrada corresponde a un commit; su mensaje explica el porqué.

## Sin publicar

Revisión general de fiabilidad, seguridad y mantenimiento (rama `review/hardening-2026-09`).

### Cambia el comportamiento

- **Avisos.** Un hallazgo HIGH o CRITICAL que el modelo no pudo verificar (la verificación no cabe, falla tres veces o queda incierta) se notifica marcado como *sin verificar* en lugar de quedarse en silencio. Un lote revisado tarde (cola larga, caída del modelo) avisa si los eventos son de las últimas seis horas y el hallazgo es grave; el histórico antiguo sigue en silencio.
- **Caídas del modelo.** Si el servidor del modelo no responde, el lote no gasta sus tres intentos: se reintenta con espera creciente.
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

### Arreglado

- La lectura de una carpeta abortaba en el primer archivo con error; un archivo `.gz`, `.xz` o `.bz2` truncado hacía caer el emisor en bucle.
- Una línea de 256 KB con `authentication failure;` detenía la detección de su máquina.
- El borrado de eventos recorría toda la tabla `signal_hits` por cada evento (35 s para 5 000 eventos con 100 000 aciertos; 0,08 s con el índice).
- Dos portales arrancando a la vez podían fallar con `duplicate column name` al migrar.
- Claves de traducción duplicadas o ausentes; contraste del texto atenuado del tema clásico; sondeos que se solapaban o seguían con la pestaña oculta; regiones `aria-live` que se reconstruían cada pocos segundos.
- La CLI antigua: `audit.*denied` nunca coincidía, el modelo bloqueaba la lectura de logs hasta dos minutos, los archivos de datos eran legibles por todos.
- Una prueba de telemetría fallaba entre las 00:00 y las 00:05 UTC.

### Mantenimiento

- `create_app` (1 300 líneas) se divide en módulos por área en `logsentinel/portal/routes/`; las rutas y su resolución son las mismas.
- Las fixtures compartidas viven en `conftest.py`; las pruebas ya no dependen de la presión de disco del equipo ni de esperas fijas.
- Metadatos del paquete coherentes (versión única, `setuptools>=77`, cotas superiores, dependencias directas declaradas).

### Sin cambiar a propósito

- Las ilustraciones de Tentri (21 MB) siguen en el paquete: la galería «Ver todas las ilustraciones» las usa.
- La CLI antigua (`logsentinel run`) se conserva por compatibilidad, endurecida pero sin las mejoras de flujo del portal.
- Sin salida estructurada por esquema JSON: cada servidor de modelos la implementa distinto y no se puede comprobar aquí sin ellos.
