# LogSentinel

Monitor experimental de logs Linux con clasificación LLM local, memoria de supresiones y un primer perfil temporal de accesos SSH. **No es un SOC autónomo ni una garantía de detección.** Las recomendaciones del LLM no se ejecutan.

## Instalación y pruebas

```bash
cd security-agent
uv venv --python 3.11 .venv  # solo si todavía no existe
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/logsentinel --help
```

Los tests usan datos sintéticos y temporales. No requieren Ollama ni notificaciones reales.

## Demostración de hábitos sin efectos externos

```bash
.venv/bin/python scripts/behavior_demo.py
```

Crea una base temporal, observa 20 accesos de diario a las 09:00 UTC, reinicia el motor y evalúa un sábado a las 03:00 UTC. Imprime evidencia calculada: `unseen_day_type`, `unusual_hour`, referencias y tamaño del historial. No lee tus logs ni modifica tu configuración.

Para consultar además el modelo local con esos mismos datos sintéticos:

```bash
.venv/bin/python scripts/behavior_demo.py --llm
```

Esta opción usa Ollama en localhost:11434 y deepseek-r1:8b; necesita el modelo instalado, consume recursos de inferencia y muestra explícitamente si se ha usado fallback. Un fallback no demuestra capacidad de análisis del modelo.

## Configuración y uso real

```bash
.venv/bin/logsentinel config init --path /ruta/nueva/config.yaml
.venv/bin/logsentinel config show --config /ruta/nueva/config.yaml
.venv/bin/logsentinel run --config /ruta/nueva/config.yaml
.venv/bin/logsentinel scan /ruta/auth.log --lines 1000 --config /ruta/nueva/config.yaml
.venv/bin/logsentinel alerts list --config /ruta/nueva/config.yaml
```

No sobrescribas una configuración existente con `config init` sin copia previa. `run`, `scan`, `simulate` y `test` pueden usar el LLM y los canales configurados; no son comandos de prueba sin efectos externos. No ejecutes como root para solventar permisos: concede solo lectura de los logs necesarios. El modo proveedor `openai` puede enviar contenido a un servidor remoto: revisa privacidad antes de activarlo.

Configuración relevante (fragmento que se combina con los valores por defecto):

```yaml
sources:
  journald:
    enabled: true
    priority: info
    units: []
behavior:
  enabled: true
  timezone: Europe/Madrid
  min_events: 20
  min_days: 5
  min_span_days: 14
  hour_tolerance: 1
  retention_days: 90
  max_events: 100000
```

El valor de prioridad `info` recoge INFO y niveles más graves; los accesos SSH aceptados suelen ser INFO. Las configuraciones antiguas con `warning..emerg` no se migran automáticamente: no permiten construir estos hábitos desde journald. Las unidades y rutas deben corresponder a tus servicios reales. UTC es la zona de perfil por defecto; establece tu zona IANA para horarios civiles y cambios de hora.

Una configuración explícita inexistente o inválida produce error: no se sustituye silenciosamente por una configuración que pueda activar destinos o rutas diferentes.

## Arquitectura

1. Collectors: journald JSON y lectura/tailing de archivos.
2. Normalización: evento, host, servicio, timestamp, mensaje.
3. Perfil temporal: observa accesos SSH aceptados antes del filtro de ruido.
4. Prefiltro y agregador: candidatos por señales explícitas o desviación temporal; agrupa ráfagas por host/servicio/firma.
5. Memoria de reglas: supresiones explícitas del administrador. No equivale al historial de comportamiento.
6. LLM: recibe incidente y evidencia histórica; emite un JSON validado. Una respuesta inválida no debe silenciar el incidente.
7. Persistencia y notificación: SQLite almacena alertas; los canales son independientes. NEW no significa entregada; NOTIFIED requiere algún canal confirmado.

SQLite se ubica por defecto en `~/.local/share/logsentinel/memory.db`. Allí conviven reglas, alertas y la tabla `behavior_events`; no es la memoria de Hermes ni de Gemini. Los logs pueden contener datos sensibles. Limita permisos, acceso y retención; no compartas la base indiscriminadamente.

## Qué aprende y qué no

La primera implementación perfila éxitos SSH por host + servicio SSH + usuario + IP (IPv4/IPv6). Compara el evento con observaciones estrictamente anteriores, separa diario/fin de semana y comprueba distancia circular entre horas. Requiere volumen, días distintos y extensión temporal mínimos. Conserva una ventana acotada y deduplica coincidencias exactas de entidad, instante y mensaje.

- `insufficient_history`: no hay evidencia suficiente para describir normalidad.
- `observed_schedule`: encaja en horarios observados; **no significa acceso autorizado**.
- `unusual`: día u hora no observados con soporte suficiente; **no significa ataque**.

Las desviaciones se envían al análisis LLM y no entrenan automáticamente el perfil. Las reglas rápidas de supresión no ocultan la categoría ANOMALY. El arranque del perfil sigue siendo no verificado: un atacante presente durante el aprendizaje puede contaminarlo. La cuarentena no soluciona todo el envenenamiento ni adapta automáticamente cambios legítimos de horario.

No se aprende con timestamps inferidos/ambiguos ni excesivamente futuros. La deduplicación exacta no resuelve diferencias de precisión entre fuentes. Los IDs de muestra identifican observaciones compactas; no son enlaces a un archivo forense completo. Días con accesos no equivalen a días con recolección continua. Una IP detrás de NAT/VPN/DHCP no es una identidad.

## Próximos pasos de producto

Para superar de verdad las reglas con redacción LLM hace falta un ciclo de investigación controlado:

- Registro normalizado duradero y consultable; cursor de journald, offsets de archivo y recuperación tras caídas.
- Cobertura de sensores, huecos de recolección y evidencia original verificable.
- Perfiles por identidad/dispositivo, frecuencia, destinos, comandos y sesiones; correlación SSH → sudo → proceso → conexión saliente.
- LLM con herramientas de consulta de solo lectura, presupuesto, consultas parametrizadas y referencias exigidas.
- Casos persistentes con hipótesis, evidencia a favor/en contra, explicaciones benignas y siguientes comprobaciones.
- Feedback diferenciado: falsa alarma, cambio legítimo de hábito y autorización temporal; no convertir todo en “ignorar para siempre”.
- Evaluación con datasets etiquetados: falsos positivos, detecciones perdidas, latencia, coste y resistencia a prompt injection.
- Cualquier bloqueo, aislamiento o cambio de permisos requiere aprobación humana, auditoría y reversión.

Consulta `plan.md` para el registro de revisión, correcciones, pruebas reales y handoff a Gemini.
