**Configurar LogSentinel y comprobar que está trabajando**

Abre **Configurar → Configuración guiada** en el portal. Cada paso se guarda al continuar; puedes volver al anterior. Las opciones avanzadas están plegadas para empezar con lo necesario.

1. **Conectar el LLM.** Elige el programa que sirve tu modelo, pega su URL y pulsa «Actualizar modelos». Selecciona uno instalado y continúa con la prueba. `127.0.0.1` significa el equipo donde corre LogSentinel, aunque abras el navegador desde otro. Para otro equipo de la red, utiliza su dirección y autoriza el servidor remoto. Si requiere clave API, es la del servidor del modelo, no la clave de acceso al portal. El propio paso enlaza las guías oficiales de [Ollama](https://docs.ollama.com/quickstart) y [LM Studio](https://lmstudio.ai/docs/developer/rest/quickstart).
2. **Elegir máquina.** Reutiliza su ficha si ya existe. Para este equipo, «Detectar este equipo» rellena los datos; para otro, crea una ficha con un nombre reconocible. Hostname y distribución son opcionales.
3. **Conectar logs.** Journal lee el registro del sistema local y no necesita ruta. Archivo y carpeta necesitan una ruta absoluta en el equipo que ejecuta LogSentinel y permisos de lectura para el usuario del servicio. Empieza con todas las líneas y sin importar histórico; así verás primero las nuevas llegadas. Puedes importar el histórico después. Las fuentes de métricas no sustituyen a una fuente de logs.
4. **Activar.** Revisa el modelo, la máquina y la fuente elegidos. Empieza con un intervalo de 30–60 segundos y termina el asistente. La captura y el análisis trabajan aunque cierres el navegador. Una fuente remota requiere además configurar su emisor; el último paso explica cómo generar e importar su paquete de alta.

Si la lectura falla por permisos, comprueba qué usuario ejecuta el servicio. El comando `logsentinel prepare-host --account USUARIO --journal` muestra un plan para darle acceso al journal. Para archivos, usa `--source /ruta/del/log` en lugar de `--journal`. Sustituye USUARIO por la cuenta del servicio. El comando muestra el plan sin aplicarlo; consulta su ayuda antes de usar `--apply`. El usuario al que se concede acceso debe coincidir con el del proceso que leerá los logs.

**Comprobar la primera lectura**

Ve a **Observar → Cobertura y capacidad** y selecciona la máquina arriba. La tarjeta «Qué está pasando y qué hacer» indica el estado y el siguiente paso. También puedes abrir **Histórico** para ver un mensaje recibido.

| Dato | Qué significa |
| --- | --- |
| Logs retenidos | Originales que siguen almacenados, dentro de la retención y cuota. |
| Analizados | Originales cubiertos por la revisión, también mediante grupos de repeticiones. No significa que el LLM haya leído individualmente cada original. |
| Sin analizar | Incluye la cola, errores y mensajes apartados por filtros o selección. |
| Esperando lote | Parte del total sin analizar que espera revisión automática. No se suma otra vez al total. |
| Cola histórica | Se recupera automáticamente mientras el análisis y la máquina estén activos. |

El estado global muestra el último evento, el último lote y la próxima revisión o espera. Los tiempos recientes se expresan en segundos, minutos u horas. «Sin alertas» y «sin analizar» son situaciones distintas.

**Ajustar el análisis sin ir a ciegas**

En **Configurar → Modelo y análisis** hay tres perfiles: automático, lotes pequeños para un modelo lento y verificación de todos los candidatos. Seleccionar un perfil muestra la comparación. «Preparar este perfil sin guardar» rellena el formulario; **Guardar ajustes** lo aplica a todas las máquinas. También puedes descartar el borrador. Los perfiles conservan tu servidor y modelo.

Cambia una cosa y observa varios lotes completos en Cobertura y capacidad. La tarjeta explica si el programa reduce, mantiene o amplía los lotes. Cuando el servidor informa de sus tiempos, puedes separar carga del modelo, lectura de entrada y generación. Si domina la carga, comprueba si otras aplicaciones están cambiando de modelo o consumiendo su memoria. Reducir el intervalo o aumentar el timeout no acelera la inferencia.

**Aplicar y desactivar los filtros incluidos**

En **Configurar → Reglas** hay tres filtros predefinidos: temporizadores systemd, desactivaciones correctas de unidades y arranque/parada de watchdog. Son opcionales; la compactación de repeticiones ya funciona sin activarlos.

Selecciona el ámbito arriba, pulsa «Ver ejemplos antes de aplicar» y revisa los mensajes que se apartarían del LLM. La vista previa examina hasta 500 logs recientes. Aplica el filtro solo si sus coincidencias son adecuadas. Puedes desactivarlo desde esa misma tarjeta. Desactivarlo no vuelve a analizar automáticamente lo ya apartado: después usa **Fuentes → Recuperar retenidos sin analizar** si quieres recuperar esas líneas.

Estos filtros y perfiles ajustan la revisión de logs. No ejecutan reparaciones en las máquinas vigiladas.

**Configurar avisos**

Ve a **Notificaciones**, añade un destino y sigue la guía del proveedor para encontrar cada dato. Guardar no envía una prueba. Usa «Enviar prueba» y comprueba el resultado. En cada problema puedes abrir «Por qué se notificó o no» para distinguir severidad insuficiente, silencio, espera, fallo y entrega.
