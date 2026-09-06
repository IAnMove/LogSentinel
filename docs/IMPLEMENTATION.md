# Seguimiento de implementación

El plan completo está en PRODUCT_DIRECTION.md. Este registro distingue capacidades implementadas de propuestas y validaciones externas pendientes.

## Etapas y commits

- [ ] 0. Corpus de evaluación, diagnóstico reproducible y registro de alcance.
- [x] 1. Base fiable y compatibilidad del prototipo; experimentos SSH desactivados por defecto.
- [ ] 2. Máquinas, fuentes, eventos comprimidos, cursores, recepción remota y recuperación.
- [ ] 3. Análisis en dos pasadas, presupuesto, problemas, filtros y contabilidad.
- [ ] 4. Destinos configurables, secretos, reintentos y plantillas Hermes/n8n.
- [ ] 5. Portal local, configuración, histórico, chat, reglas y exportación.
- [ ] 6. Empaquetado, backup/restauración, documentación y pruebas de integración.

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
