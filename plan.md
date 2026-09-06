# Revisión y evolución de LogSentinel — handoff para Gemini

## Alcance y coordinación

Solicitud: revisar el proyecto completo, identificar aciertos/carencias, corregir errores demostrables y construir una base para análisis contextual de hábitos (por ejemplo SSH fuera de horario habitual). No equivale a certificar que no existan más vulnerabilidades.

Inspección inicial: no hay repositorio Git. `agy` PID 6786 está abierto en este directorio; no se observaron procesos de tests ni monitor LogSentinel activos. No se interrumpirá ni reiniciará Gemini. Antes de editar se ha copiado el código original (32 archivos, excluyendo entorno virtual y cachés) a `/home/ina/security-project-backups/20260906T022758Z`, con manifest SHA-256. No modificar datos/configuración real, enviar notificaciones, activar monitor ni ejecutar acciones defensivas reales.

## Plan de ejecución

- [x] Inventario, comprobación de procesos, copia recuperable y tests base.
- [ ] Auditoría por áreas: core/config/models; collectors/CLI/notifiers/simulator; memoria/LLM.
- [x] Reparar infraestructura de tests (pytest-asyncio: base 12/12); regresiones de prefiltrado y timestamps corregidas. Agrupación revisada en paralelo; ver resultados finales.
- [ ] Corregir supresiones peligrosas y manejo de errores/contratos LLM demostrados por tests.
- [ ] Implementar un primer perfil temporal persistente, acotado y explicable para accesos SSH aceptados; estudiar antes de incorporar el evento actual al histórico y evitar concluir anomalías con historial insuficiente.
- [ ] Integrar evidencia histórica en el análisis LLM sin convertir logs en instrucciones ni ejecutar sus recomendaciones.
- [ ] Pruebas de regresión completas, smoke tests CLI aislados y revisión independiente.
- [ ] Documentar resultados, cambios, límites y siguientes fases para Gemini.

## Evidencia inicial

Comando: `.venv/bin/python -m pytest -q`
Resultado real: 2 fallos, 10 aprobados, 2 warnings. Los dos tests async no se ejecutan porque falta pytest-asyncio en dependencias dev.

Hallazgos iniciales pendientes de regresión: el prefiltrado y la prioridad de journald descartan accesos SSH exitosos; la memoria actual contiene reglas de supresión, no hábitos. La agrupación usa tiempo de proceso en lugar de tiempo del evento y puede mezclar hosts. El callback de análisis se espera bajo el lock al alcanzar max_batch_size. README.md está vacío.

## Criterio de inteligencia útil

Separar observaciones verificables de interpretación: eventos normalizados → historial por entidad → desviaciones y cobertura → LLM que formule hipótesis, alternativas benignas, incertidumbre y comprobaciones siguientes. Una desviación no demuestra un ataque. Una IP no identifica de forma estable a una persona (NAT/VPN/DHCP). El LLM no debe inventar frecuencias ni ejecutar bloqueo/cambios. Mantener revisión humana para medidas con impacto.

## Registro de cambios y resultados

### Avance verificado (antes de revisión final)

- `uv pip install --python .venv/bin/python -e '.[dev]'`: añadido pytest-asyncio y baseline 12/12.
- Regresiones propias RED→GREEN: configuración inválida no hace fallback peligroso; valores operativos positivos/provider/severity/timezone validados; journald por defecto incluye INFO; timestamps UTC y límites por tiempo de evento; palabras de ruido no anulan evidencia explícita de seguridad y se analiza MESSAGE decodificado.
- Motor: `memory.enabled` respetado; anomalías no pasan por supresión rápida genérica; alertas se persisten antes de entrega; sin canales entregados el estado queda NEW; tareas de fuente fallidas observables y cierre con join.
- Perfil SSH persistente + pruebas: 20 eventos previos, 5 días distintos y 14 días de intervalo mínimo; 90 días de retención y límite global de 100000 eventos. Entidad host+servicio SSH+usuario+IP (IPv4/IPv6). Hora local configurable IANA (UTC por defecto), tolerancia circular de 1h y separación diario/fin de semana. Eventos futuros (>5 minutos) o timestamp inferido excluidos. Duplicados exactos no aumentan votos. Se comparan solo observaciones anteriores al evento actual. Anomalías no entrenan automáticamente el perfil.
- `.venv/bin/python scripts/behavior_demo.py`: ejecución real offline con datos sintéticos. Resultado: 20 accesos previos, 20 días observados, 25 días de intervalo, hora previa 09 UTC; sábado 03 UTC produce `unseen_day_type` y `unusual_hour`; `learned=false`. Reinicio de engine conservó historial. No se envió ninguna notificación.
- `curl http://localhost:11434/api/tags` confirmó servicio local con deepseek-r1:8b disponible. No equivale todavía a validar calidad del análisis del modelo.

Revisión independiente y pruebas finales en curso; no usar conteos intermedios como resultado final.
