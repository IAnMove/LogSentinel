# Seguimiento de implementación

## Actualización operativa · 7 de septiembre de 2026

Nueva etapa: [contexto por problema e investigaciones persistentes](PROBLEM_INVESTIGATIONS.md), y [monitorización de recursos por máquina](METRICS.md), con captura independiente, agregados diarios, umbrales/picos, portal ES/EN y emisor remoto con confirmaciones duraderas. La referencia técnica describe lo implementado y sus límites; los resultados de validación de la revisión anterior se conservan más abajo.

Validación de la nueva etapa: cuatro recorridos de Chromium y análisis real de tendencias con Qwen3-8B. La prueba real detectó y permitió corregir una incompatibilidad de campos adicionales del modelo. Mediciones locales activadas cada 60 segundos; el análisis de logs continúa cada 300 segundos. No hay destinos de notificación configurados ni se han enviado avisos externos. El análisis de tendencias automático se activa por máquina de forma independiente.

La instancia local ya tiene journald y Qwen3-8B activos, con captura continua y análisis cada 300 segundos. El [informe de revisión actual](REVIEW_2026-09-07.md) sustituye las afirmaciones de ausencia de servicio o fuentes reales del cierre histórico que sigue más abajo.

Se han añadido estado verificable del monitor, asistente de configuración que empieza por el LLM, ayuda de configuración sin logs, interfaz español/inglés y elección del idioma de nuevos hallazgos. Se corrigieron fallos reales de formato del modelo, selección de contexto antiguo, contabilidad de errores y muestra antigua del chat. La prueba real de conexión y un ciclo automático pasan; la capacidad observada sigue dejando muchos registros sin revisar. El piloto de calidad y las entregas externas siguen pendientes.

Validación de esta revisión: **250 tests aprobados**, dos recorridos de Chromium y prueba real del modelo. Los recorridos usan temporales y un modelo simulado; el nuevo comprueba dos ciclos automáticos, captura independiente, ES/EN y privacidad del chat de ayuda. Los dos avisos de deprecación de TestClient siguen pendientes de la evolución de sus dependencias. Commits iniciales de esta revisión: `2dfd02a` y `bdccf7b`; los ajustes finales y el informe se registran en una etapa posterior.

El resto de este documento conserva el registro del cierre inicial y debe leerse como histórico.

El plan completo está en PRODUCT_DIRECTION.md. Este registro distingue capacidades implementadas de propuestas y validaciones externas pendientes.

## Etapas de la primera versión y commits

- [x] 0. Corpus de evaluación, diagnóstico reproducible y registro de alcance.
- [x] 1. Base fiable y compatibilidad del prototipo; experimentos SSH desactivados por defecto.
- [x] 2. Máquinas, fuentes, eventos comprimidos, cursores, recepción remota y recuperación.
- [x] 3. Análisis en dos pasadas, presupuesto, problemas, filtros y contabilidad.
- [x] 4. Destinos configurables, secretos, reintentos y plantillas Hermes/n8n.
- [x] 5. Portal local, configuración, histórico, chat, reglas y exportación.
- [x] 6. Empaquetado, backup/restauración, documentación y pruebas de integración.

Cada etapa se confirma en Git después de sus comprobaciones. Los commits son locales; no se publica ni activa un monitor de logs reales durante el desarrollo.

## Validaciones externas

- Calidad y rendimiento con el modelo/hardware objetivo: se reportará el resultado real o la ausencia de servicio; no se sustituye por mocks.
- Canales de notificación reales y Hermes/n8n: requieren destinos del usuario. Los contratos se prueban localmente sin enviar mensajes.
- Durabilidad física ante corte eléctrico y distribuciones adicionales: no equivalen a pruebas unitarias o cierre limpio.

Etapa 1: 206 tests aprobados. Perfil SSH opt-in; corregidos los tres fallos de sus regresiones, persistencia antes de inferencia y protección de config init. El portal usa una nueva cola duradera para reanudar trabajo, sin depender de este motor legacy.

Etapa 2a: ledger comprimido en SQLite, importación archivo/gzip y cursores transaccionales. Cinco pruebas de almacenamiento verifican reinicio, duplicados, rollback por cuota y backup con evidencia. Piloto remoto integrado en la etapa de API; `forward` mantiene un spool por archivo.

Etapas 3–4: revisión acotada en dos pasadas, referencias validadas, recuperación de trabajos, filtros con timeout, problemas y revisiones, aviso de capacidad y reparto entre fuentes. Outbox persistente para ocho canales (sistema, archivo, Telegram, Slack, Discord, Hermes, n8n y webhook), sin enviar al guardar, y estados de resultado desconocido. Contratos HTTP comprobados con transporte simulado; no certifican el servicio externo.

Etapa 5: portal loopback con sesión/CSRF, formularios de configuración, histórico, evidencia, prompt copiable, reglas previsualizables, chat e historial, recepción autenticada y copias. Chromium completa creación de máquina/fuente, ingestión, análisis de dos pasadas con modelo simulado, evidencia, silencio y destino local; también comprueba ancho móvil. Tests de recepción reproducen ACK perdido después de persistir y reenvío sin duplicar.

Robustez adicional: descriptores de archivos rotados conservados durante cinco minutos sin crecimiento, prueba con escritura tardía tras unlink; limpieza de spool confirmado; rotación gzip acotada del destino de archivo; filtros con caducidad editable. Los límites exactos y casos que no admiten garantía de no pérdida están documentados en OPERATIONS.md.


## Cierre de la primera implementación

La lista anterior cubre una primera versión operativa del producto, con los límites descritos en OPERATIONS.md. No significa que se hayan certificado todas las garantías y ampliaciones del documento de propuesta.

- Corpus sintético con seis escenarios y ejecutor reproducible. `docs/evaluation-local.json` mide ingestión y compactación. El intento con modelo real falló por ausencia de servicio en localhost:11434; los análisis fallidos no se contabilizan como detecciones negativas.
- Instalación limpia en `.venv` como `ina`, permisos del repositorio corregidos, versiones de validación registradas, construcción de wheel y CI para Python 3.10/3.12/3.13 más Chromium. La CI remota aún no se ha ejecutado con estos commits locales.
- Backup/restauración comprobados incluyendo rutas especiales, sin sobrescritura del destino.
- Histórico paginado y búsqueda progresiva sobre originales comprimidos; contadores de problemas completos. Consulta de modelos/contexto Ollama y sugerencia conservadora de presupuesto, sin aplicar cambios automáticamente.

## Qué sigue pendiente del plan completo

1. **Piloto con el LLM elegido:** medir falsos positivos, omisiones, tokens, latencia y velocidad sostenible con logs representativos. El corpus sintético pequeño y los dobles de prueba no sustituyen ese piloto.
2. **Verificar servicios externos reales:** entrega final Telegram/Slack/Discord/Hermes/n8n, escritorio del usuario y túnel SSH entre equipos. El protocolo y recuperación de ACK sí tienen pruebas locales. La plantilla n8n necesita conectar el destino externo elegido.
3. **Endurecimiento para producción:** ensayos de corte eléctrico, saturación prolongada y otras distribuciones; calibración por modelo/tokenizer. El perfil actual usa cotas conservadoras y límites explícitos.
4. **Ampliaciones de la propuesta:** migración automática de la base legacy, índice de búsqueda sobre todo el archivo frío y políticas avanzadas de retención/archivos. Hay compatibilidad legacy separada, búsqueda progresiva y retención por días; no se presentan como esas ampliaciones.

No se ha hecho push, desplegado servicios externos, activado fuentes reales ni enviado notificaciones remotas.

## Resultado de las comprobaciones locales

- **240 tests aprobados** con Python 3.12.3, ejecutados como `ina`; dos avisos de deprecación en dependencias de TestClient.
- Recorrido de Chromium aprobado, incluida vista móvil; modelo simulado y destino de archivo temporal.
- `pip check` sin conflictos; wheel construido, instalado fuera del repositorio y comprobado sirviendo HTML/JS.
- Corpus sin modelo ejecutado y registrado. Evaluación real no disponible por conexión rechazada al servidor Ollama.
- Commits de funcionalidad: `3c847bf` (base), `7188bfc` (ledger), `3b5ca4e` (revisión/avisos), `e496113` (portal/receptor), `696408a` (rotación) y `2c0b6b0` (histórico/capacidad). Documentación inicial en `7b0255f`; empaquetado y evaluación se cierran en el siguiente commit.
