# LogSentinel

Interfaz disponible en español e inglés · [English summary](README.en.md)

Portal local para revisar logs de Linux con un LLM, detectar problemas de funcionamiento y seguridad y conservar la evidencia. Cada fuente pertenece a una máquina. El modelo propone hallazgos y filtros; no ejecuta comandos ni cambia reglas por su cuenta.

Solo lee y explica: no cambia la configuración de tus equipos ni bloquea direcciones. Se instala en un equipo Linux con Python 3.10 o superior y necesita un servidor de modelos (Ollama, llama.cpp, LM Studio, vLLM u otro compatible con la API `/v1`), que se instala por separado.

## Instalar y abrir

Linux y Python 3.10 o superior. El wrapper crea el entorno, instala el paquete y arranca el portal:

```bash
git clone https://github.com/IAnMove/LogSentinel.git
cd LogSentinel
chmod +x portal
./portal
```

Equivale a `python3 -m venv .venv`, `pip install -e .` y `logsentinel portal`. Pasa opciones del portal, por ejemplo `./portal --port 8766`. Si falta el módulo `venv`: en Debian/Ubuntu `sudo apt install python3 python3-venv python3-pip`; en Arch/Omarchy `python` ya suele estar.

Para dejarlo como servicio de usuario: `.venv/bin/logsentinel service install` y `systemctl --user enable --now logsentinel`.

Abre `http://127.0.0.1:8765` e introduce la clave guardada en `~/.local/share/logsentinel/portal/access-key.txt` (solo accesible por su propietario). La terminal muestra la ruta, nunca la clave. Los datos se guardan en ese mismo directorio. Usa `--data-dir /ruta` para otra instancia. El portal escucha exclusivamente en loopback, requiere sesión y comprueba origen y CSRF.

1. Abre **Configuración guiada**: primero guarda y prueba el LLM. El servicio del modelo se instala por separado.
2. Crea o reutiliza una **Máquina** y conecta una **Fuente**: journal sin ruta, archivo/carpeta con ruta absoluta, o recepción remota con emisor. La prueba de lectura comprueba permisos; importar histórico puede incorporar todos los registros disponibles.
3. Termina el asistente para activar el análisis automático al intervalo elegido. Las fuentes activas se leen continuamente (sondeos aproximadamente cada 2 segundos más lectura), incluso con el análisis pausado. El estado superior muestra próxima ejecución, última recepción, resultado y cobertura. El navegador puede cerrarse. **Modelo y análisis** ofrece los ajustes avanzados y el idioma de nuevos hallazgos.
4. Consulta **Problemas**, su evidencia y **Copiar prompt**. **No notificar** mantiene el análisis; una regla de exclusión evita enviar las líneas coincidentes al modelo.
5. Configura destinos en **Notificaciones**. Guardar no envía mensajes; **Enviar prueba** sí. Revisa los resultados en **Actividad**.
6. En **Resumen → Recursos de los equipos** encontrarás CPU, RAM y discos con barras y cantidades en GiB. Abre una máquina para activar la captura opcional y ver gráficos de 1/6/24 horas, umbrales y mínimos/máximos diarios. Capturar y alertar no usa tokens; las tendencias con el LLM se activan por separado.

**Servidores LLM:** el portal ofrece presets para Ollama, llama.cpp, LM Studio, vLLM, LiteLLM y balanceadores compatibles. Consulta modelos y prueba los ajustes del formulario antes de guardarlos.

Desde un problema, **Preguntar al asistente** muestra el hallazgo y envía su contexto y evidencias; puedes revisar el contenido exacto antes y después de consultar. **Ver más detalles** muestra originales y revisiones. **Buscar más detalles del problema** guarda una investigación ampliada sobre logs relacionados.

Los servidores LLM fuera de loopback requieren activar la autorización de envío remoto. Las claves de API y destinos son de escritura: el portal no las devuelve al navegador. Se almacenan en la base local con permisos de propietario, sin cifrado de aplicación. Los backups también contienen estas credenciales. La ocultación de secretos reconocibles no garantiza detectar todo dato sensible dentro de un log.

## Lo que incluye

- Máquinas, fuentes, histórico de originales, problemas con apariciones y revisiones; resolver, silenciar avisos y copiar contexto.
- Archivo, carpeta, journal y receptor HTTP autenticado por fuente; importación de gzip, xz y bz2 estables. No modifica ni rota los archivos de otros programas.
- Segmentos inmutables comprimidos dentro de SQLite: datos, índices y cursores se confirman juntos. La recepción no espera al LLM ni al cierre de una conexión SSH.
- Cola persistente con varios lotes por máquina, recuperación del histórico y reintentos con la petición conservada. Las repeticiones reconocidas mantienen cantidad, fechas, frecuencia, ejemplos y referencias a originales; no se excluye todo INFO ni todo Python.
- Primera revisión breve y verificación independiente de los candidatos importantes con originales. Referencias ajenas se rechazan; las verificaciones incompletas conservan los candidatos visibles y se reintentan.
- Lotes ajustados al tiempo medido y espera máxima inicial de 60 segundos. Se registran por separado carga del modelo, evaluación de entrada y generación de salida. Para evaluar clasificación con datos sintéticos: `python scripts/evaluate_review.py --settings-db /ruta/sentinel.db --output /ruta/evaluation.json --variants pipeline --held-out`.
- Presupuesto por ciclo, reparto entre máquinas/fuentes, reintentos acotados y aviso de cobertura reducida. **Sin revisar** nunca significa **sin problemas**.
- Filtros regex con tiempo limitado, IP/CIDR y problema concreto; previsualización de una muestra antes de aplicar. Chat acotado al histórico de una máquina, con historial y propuestas de filtros que requieren guardar.
- Sistema, archivo local, Telegram, Slack, Discord, Hermes, n8n y webhook genérico. Cola persistente, alcance por máquina/fuente, umbral, enfriamiento, reintentos y resultado desconocido ante interrupción.
- Volumen original/comprimido, cobertura y tokens por máquina; atribución estimada por fuente cuando se comparten llamadas. El uso no reportado se muestra como desconocido.
- Backup coherente y restauración en un directorio nuevo.
- Asistente de inicio, selector español/inglés persistente y ayuda LLM disponible desde cualquier pantalla. La ayuda de configuración no recibe logs ni credenciales; el asistente de logs usa una muestra reciente de la máquina seleccionada.

## Garantías y límites

Lo que esta versión asegura y lo que no, para que no haya que descubrirlo en un incidente.

- **Avisos graves.** Un hallazgo HIGH o CRITICAL que el modelo no ha podido verificar (la verificación no cabe, falla tres veces o queda «incierta») se notifica igualmente, marcado como **sin verificar** en el mensaje y en el payload. Los MEDIUM y LOW sin verificar (solo ocurren con la verificación de todos los candidatos) no se notifican, pero quedan visibles en Problemas. Los eventos recibidos con retraso (cola larga o caída del modelo) avisan si ocurrieron en las últimas seis horas y son HIGH o CRITICAL; el histórico más antiguo no.
- **Caídas del modelo.** Si el servidor del modelo no responde, el lote no gasta sus intentos: se reintenta con espera creciente hasta que vuelve. Un tiempo de espera de lectura o un error 500 sí cuentan, porque pueden deberse al propio lote.
- **Detectores sin modelo.** OOM, disco lleno o de solo lectura, rechazos de `sudo` y ráfagas de fallos SSH (incluido `sshd-session` de OpenSSH 9.8 o posterior) se detectan sobre los originales, sin esperar al LLM ni a que haya cupo.
- **Orden de revisión.** Con más cola que un lote, se revisan antes los originales con prioridad de syslog 0–3 (emergencia a error), hasta tres cuartas partes del lote; el resto va por orden de llegada.
- **Retención.** `retention_days` (30 por defecto) rige los originales, los trabajos terminados y el historial de entregas. Los consumos de tokens y la auditoría se conservan al menos un año. Los problemas y sus revisiones se conservan. Las copias de seguridad guardan las cinco más recientes.
- **Disco.** El espacio liberado se reutiliza y cuenta como libre en la cuota. `VACUUM` solo se ejecuta si hay al menos 256 MiB y la mitad del archivo reutilizables y el disco puede alojar una copia; nunca en un equipo con poco espacio. La copia de seguridad se rechaza si no cabe.
- **Ocultación de secretos.** Antes de enviar texto al modelo o a un destino se ocultan credenciales reconocibles: pares `clave=valor` y JSON, `Authorization`, `Bearer`, credenciales en URL, `--password`, cookies, claves PEM y prefijos de token conocidos. Es una lista, no una garantía: un secreto con otra forma pasa. Los originales se guardan sin redactar.
- **Registro del servidor.** Los fallos de los procesos internos se escriben con su traza en stderr (el journal, si corre como servicio), con los secretos ocultos y un mismo fallo como máximo cada cinco minutos.
- **Lo que no hace.** No garantiza detectar ataques nuevos ni resiste toda inyección de instrucciones en los logs: la detecta por frases, la marca como hallazgo y no deja que decida por sí sola silenciar un problema. «Sin revisar» nunca significa «sin problemas».

## Enviar desde otro equipo

Para el recorrido por HTTPS con certificado local, cuenta limitada, paquete de
alta y servicio emisor, sigue la [guía de equipos remotos](GUIA_EQUIPOS.md).
Con el repositorio y el alta entregada por el central, en un Linux con systemd:

```bash
sudo ./setup-client.sh --package /ruta/alta.json --ca-fingerprint sha256:HUELLA
```

Instala el emisor con una cuenta sin login. Por defecto envía el journal desde
las entradas nuevas; no instala un modelo ni importa todo el historial.
También hay un [encargo listo para otro Codex](CODEX_CLIENTE.md), con los archivos
que debe entregar el central y las comprobaciones que debe realizar el cliente.
El emisor utiliza el receptor separado del panel. Puede alcanzarlo directamente
por HTTPS en la LAN o mediante un túnel SSH, manteniendo la validación TLS.

El emisor mantiene IDs y cola locales. El receptor confirma solo después de persistir; un ACK perdido se puede reintentar sin duplicar eventos retenidos. Cada archivo o journal necesita su propio spool. `--once` envía un lote para pruebas. No reutilices un spool para otra fuente. La cuota llena impide avanzar el cursor; conserva los archivos originales hasta resolverla. El emisor no configura SSH ni un proxy TLS automáticamente.

## Notificaciones externas

Hermes recibe un webhook firmado V2 y un identificador de entrega estable. La plantilla del portal propone una ruta `deliver_only`; requiere configurar el gateway externo. n8n es opcional: la plantilla crea una entrada autenticada y un punto para conectar el destino elegido. No despliega ni activa n8n. Los proveedores externos requieren sus credenciales.

## Widget para Omarchy

La integración de Omarchy Quattro está disponible como prueba en este equipo. `omarchy plugin add` y `./plugin` solo instalan el widget en tu escritorio; no lo publican en el marketplace. Falta completar la validación en un escritorio Omarchy real. El widget necesita un portal en ejecución y no instala un LLM ni empieza a enviar logs por sí solo.

En Omarchy, el widget de la barra es otro comando y se queda en esta máquina:

```bash
./plugin
```

Si no detecta Omarchy Quattro con `omarchy plugin`, sale sin instalar nada. No envía el proyecto a [plugins.omarchy.org](https://plugins.omarchy.org). Después hay que emparejar la clave en **Escritorio** del portal.

## Documentos

- [Guía rápida](GUIA_RAPIDA.md): configuración guiada, primeros pasos y comprobaciones.
- [Equipos remotos](GUIA_EQUIPOS.md) y [encargo para otro Codex](CODEX_CLIENTE.md): cómo enviar logs desde otro Linux.
- [Protección y recuperación del cliente](CLIENTES_RECUPERACION.md): límites del emisor, actualización y qué hacer con un disco con problemas.
- [Dirección de producto](PRODUCT_DIRECTION.md): el plan original y sus propuestas; no describe garantías de esta versión.
- [Seguridad](SECURITY.md), [contribuir](CONTRIBUTING.md) y [cambios](CHANGELOG.md).

## Desarrollo y verificación

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q            # unitarias y de contrato
.venv/bin/ruff check .                   # defectos: nombres, patrones de error, bloqueos en async
.venv/bin/mypy                           # tipos del paquete
.venv/bin/python scripts/evaluate_portal.py
# Evaluación real: necesita el modelo disponible
.venv/bin/python scripts/evaluate_portal.py --live --model MODELO_INSTALADO
```

Los recorridos de interfaz usan un navegador real y un modelo simulado, sin avisos remotos:

```bash
.venv/bin/python -m pip install -c constraints-tested-py312.txt playwright
.venv/bin/python -m playwright install chromium
for s in portal setup problem metrics providers capacity review_state chat machines_resources guidance themes; do
  .venv/bin/python scripts/${s}_smoke.py
done
node scripts/omarchy_smoke.mjs
```

`constraints-tested-py312.txt` registra las versiones con las que pasan; úsalo como constraints en Python 3.12. La CI ejecuta las pruebas en Python 3.10, 3.12, 3.13 y 3.14, el linter, los tipos, los once recorridos de navegador y comprueba el contenido del wheel (`scripts/check_wheel.py`).

La CLI anterior (`logsentinel run`) se conserva como compatibilidad; usa otra base y no es el motor del portal. Recibe la misma redacción de secretos y el mismo transporte seguro, pero no las mejoras de flujo del portal. El experimento de horarios SSH queda desactivado por defecto.

## About us

[@THEINAOG · x.com](https://x.com/THEINAOG) · [ianmove/LogSentinel · GitHub](https://github.com/IAnMove/LogSentinel)
