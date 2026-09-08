# LogSentinel

Interfaz disponible en español e inglés.

La integración de Omarchy Quattro está disponible como prueba: instala el widget con `omarchy plugin add https://github.com/IAnMove/LogSentinel.git --enable` y vincúlalo desde **Escritorio** en el portal. Falta completar la validación en un escritorio Omarchy real; todavía no está en el marketplace. El widget necesita un portal en ejecución y no instala un LLM ni empieza a enviar logs por sí solo.

Portal local para revisar logs de Linux con un LLM, detectar problemas de funcionamiento y seguridad y conservar la evidencia. Cada fuente pertenece a una máquina. El modelo propone hallazgos y filtros; no ejecuta comandos ni cambia reglas por su cuenta.

## Instalar y abrir

Linux y Python 3.10 o superior. El wrapper crea el entorno, instala el paquete y arranca el portal:

```bash
git clone https://github.com/IAnMove/LogSentinel.git
cd LogSentinel
chmod +x portal
./portal
```

Equivale a `python3 -m venv .venv`, `pip install -e .` y `logsentinel portal`. Pasa opciones del portal, por ejemplo `./portal --port 8766`. Si falta el módulo `venv`: en Debian/Ubuntu `sudo apt install python3 python3-venv python3-pip`; en Arch/Omarchy `python` ya suele estar.

Abre `http://127.0.0.1:8765` e introduce la clave que muestra la terminal. Los datos se guardan en `~/.local/share/logsentinel/portal`. Usa `--data-dir /ruta` para otra instancia. El portal escucha exclusivamente en loopback, requiere sesión y comprueba origen y CSRF.

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
- Revisión general sin depender de palabras clave, compactación de repeticiones y segunda pasada de evidencia con líneas vecinas. Referencias fuera del contexto se rechazan.
- Presupuesto por ciclo, reparto entre máquinas/fuentes, reintentos acotados y aviso de cobertura reducida. **Sin revisar** nunca significa **sin problemas**.
- Filtros regex con tiempo limitado, IP/CIDR y problema concreto; previsualización de una muestra antes de aplicar. Chat acotado al histórico de una máquina, con historial y propuestas de filtros que requieren guardar.
- Sistema, archivo local, Telegram, Slack, Discord, Hermes, n8n y webhook genérico. Cola persistente, alcance por máquina/fuente, umbral, enfriamiento, reintentos y resultado desconocido ante interrupción.
- Volumen original/comprimido, cobertura y tokens por máquina; atribución estimada por fuente cuando se comparten llamadas. El uso no reportado se muestra como desconocido.
- Backup coherente y restauración en un directorio nuevo.
- Asistente de inicio, selector español/inglés persistente y ayuda LLM disponible desde cualquier pantalla. La ayuda de configuración no recibe logs ni credenciales; el asistente de logs usa una muestra reciente de la máquina seleccionada.

## Enviar desde otro equipo

En el portal crea una fuente **Recepción remota**, actívala y genera su token. Para mantener el receptor privado, en el emisor abre un túnel hacia el servidor:

```bash
ssh -N -L 9876:127.0.0.1:8765 usuario@servidor
```

En otra terminal del emisor, instala LogSentinel y ejecuta:

```bash
read -rs LOGSENTINEL_PUSH_TOKEN
export LOGSENTINEL_PUSH_TOKEN
logsentinel forward /ruta/app.log --receiver http://127.0.0.1:9876 \
  --source-id ID_DEL_PORTAL --spool ~/.local/share/logsentinel/emisor-app
```

El emisor mantiene IDs y cola locales. El receptor confirma solo después de persistir; un ACK perdido se puede reintentar sin duplicar eventos retenidos. Cada archivo necesita su propio spool. `--once` envía un lote para pruebas. No reutilices un spool para otra ruta. La cuota llena impide avanzar el cursor; conserva los archivos originales hasta resolverla. El emisor no configura SSH ni un proxy TLS automáticamente.

## Rotación, límites y notificaciones

El [plan completo](PRODUCT_DIRECTION.md) conserva propuestas de producto que no deben confundirse con garantías de esta versión.

Hermes recibe un webhook firmado V2 y un identificador de entrega estable. La plantilla del portal propone una ruta `deliver_only`; requiere configurar el gateway externo. n8n es opcional: la plantilla crea una entrada autenticada y un punto para conectar el destino elegido. No despliega ni activa n8n. Los proveedores externos requieren sus credenciales.

## Verificar

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/evaluate_portal.py
# Evaluación real: necesita el modelo disponible
.venv/bin/python scripts/evaluate_portal.py --live --model MODELO_INSTALADO
# Recorrido real de interfaz con modelo simulado, sin avisos remotos
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/portal_smoke.py
.venv/bin/python scripts/setup_smoke.py
.venv/bin/python scripts/problem_smoke.py
.venv/bin/python scripts/metrics_smoke.py
```

`constraints-tested-py312.txt` registra las versiones del entorno comprobado; úsalo como constraints de instalación en Python 3.12. La CI añade una matriz de versiones de Python; sus resultados en GitHub aún deben ejecutarse tras publicar los commits.

La CLI anterior se conserva como compatibilidad; usa otra base y no es el motor del portal. El experimento de horarios SSH queda desactivado por defecto.

## About us

[@THEINAOG · x.com](https://x.com/THEINAOG) · [ianmove/LogSentinel · GitHub](https://github.com/IAnMove/LogSentinel)
