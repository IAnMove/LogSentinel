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
