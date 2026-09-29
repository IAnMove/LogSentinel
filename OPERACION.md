# Operación: montar el modelo, medir, acceder y vigilar

Notas de operación reunidas de uso real. Los números salen de un equipo concreto
(un modelo de 8 000 M de parámetros cuantizado a 4 bits, solo CPU) y sirven como
orden de magnitud, no como garantía: mide los tuyos en **Cobertura y capacidad**.

## 1. El servidor de modelos local

Comprueba el servidor antes de configurarlo en el portal:

```bash
curl http://127.0.0.1:PUERTO/health          # llama.cpp
curl http://127.0.0.1:PUERTO/v1/models       # debe devolver JSON con el modelo
curl http://127.0.0.1:11434/api/tags         # Ollama
```

- **Puerto ocupado por otro servicio.** llama.cpp usa el 8080 por defecto. Si otro
  programa lo tiene, muévelo a otro puerto (por ejemplo 8081). Un servicio que
  contesta HTML en `/v1/models` no es un servidor de modelos: el portal solo
  reconoce como tal una respuesta JSON, y el asistente de configuración no lo
  ofrecerá.
- **El identificador del modelo** es el que publica el servidor en `/v1/models`,
  que en llama.cpp suele ser la ruta completa del archivo `.gguf`. Cópialo tal cual.
- **Modelos que razonan (Qwen3 y similares).** Pueden gastar todo el límite de
  salida pensando antes de escribir el JSON. Deja desactivado el *pensamiento* en
  **Modelo y análisis**: el portal envía `enable_thinking=false` a llama.cpp/vLLM y
  el parámetro `think` a Ollama. Si lo activas, sube el límite de salida y acepta
  menos rendimiento.
- **Contexto.** El contexto configurado en el portal debe ser el que el servidor
  cargó de verdad. Con varios *slots* paralelos, cada petición recibe el contexto
  dividido entre ellos.
- **Sin GPU útil**, arranca llama.cpp con `-ngl 0`: la inferencia va por CPU y
  ocupa RAM (unos 12 GiB en el equipo medido, para un archivo de 5 GB).

## 2. Cuánto tarda una llamada y qué timeout poner

En el equipo medido: unos **8 tokens/s** generando y **60 s** leyendo la entrada.
Con el timeout por defecto (120 s) cinco de 35 llamadas se cortaron, y una tarea
que en 60 s de lectura más 483 tokens de respuesta pasaba de los 120 s terminó bien
con **240 s**. Una respuesta de solo 1 024 tokens a 8 tokens/s ya son unos 2 minutos.

- En CPU, sube **Tiempo de espera del LLM** a 240 s o más y usa el perfil de
  *lotes pequeños* de **Modelo y análisis**.
- Un timeout de lectura cuenta como intento fallido; al tercero el lote pasa a
  *fallido*. Un servidor caído no cuenta (véase «Garantías y límites» del README).
- Mira la media real en **Cobertura y capacidad** antes de tocar nada: mide
  llamadas, tokens y segundos de tu instalación.

## 3. Volumen y cobertura

Un journal activo produce mucho más de lo que un modelo lento revisa. En el equipo
medido, con «todas las líneas», **el 96 % de 25 107 eventos retenidos quedó fuera
de revisión por capacidad**, y un solo servicio (`python`) aportaba el 84 %. Un
servicio activo y bien configurado no demuestra que se esté revisando.

- Para modelos lentos, usa en la fuente el modo **prioridad + palabras** con
  prioridad ≤ 4, palabras de disparo y 5 minutos de contexto. Es menos cobertura, y
  el portal lo dice.
- Previsualiza cualquier regla de exclusión antes de guardarla. No excluyas un
  servicio entero, `INFO` o una IP por una coincidencia amplia: la prioridad del
  journal la elige el productor y no es una frontera de confianza.
- Los detectores deterministas (OOM, disco, `sudo`, SSH) funcionan sobre los
  originales aunque el modelo no llegue.

## 4. Acceder al panel desde otro equipo

El panel solo escucha en loopback (`127.0.0.1:8765`). Se accede por túnel SSH:

```bash
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -L 8765:127.0.0.1:8765 usuario@equipo-del-portal
```

y se abre `http://127.0.0.1:8765` en tu navegador.

**Si el equipo del portal está tras NAT**, ábrele un túnel inverso hacia un servidor
que sí alcances, y desde tu portátil otro hacia ese servidor:

```bash
# En el equipo del portal
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:18765:127.0.0.1:8765 usuario@servidor
# En tu portátil
ssh -NT -L 8765:127.0.0.1:18765 usuario@servidor
```

- El puerto remoto queda ligado al loopback del servidor. **No uses
  `-R 0.0.0.0:…`** salvo que quieras publicar deliberadamente un panel
  administrativo.
- El servidor debe permitir `AllowTcpForwarding` (al menos `remote`).
- Para que sobreviva a cortes, usa `autossh` o una unidad systemd con
  `Restart=always`.

## 5. Servicio de usuario o de sistema

`logsentinel service install` instala una unidad **de usuario**
(`systemctl --user`). Necesita una sesión con bus de usuario; si no la hay
(`systemctl --user` responde que no puede conectar), tienes dos caminos:

- `sudo loginctl enable-linger USUARIO` para que el servicio de usuario viva sin
  sesión abierta, o
- `sudo logsentinel service install --system --run-as USUARIO`: unidad de sistema
  que ejecuta el proceso con esa cuenta, sin privilegios de root. (`--allow-root`
  existe pero no se recomienda.)

Ambas unidades usan el puerto 8765; para otro puerto o para el receptor de red,
edita `ExecStart` (véase `GUIA_EQUIPOS.md`) y reinicia, sin lanzar otro proceso
sobre la misma base.

## 6. Vigilar el propio portal

Un portal parado no puede avisar de que está parado. `GET /healthz` responde **200**
si todo va bien y **503** si algún componente está degradado; no requiere sesión.
Vigílalo desde fuera, por ejemplo con un temporizador o una tarea programada:

```bash
curl -fsS http://127.0.0.1:8765/healthz > /dev/null || echo "LogSentinel no responde" | mail -s aviso tu@correo
```

(o cualquier otro aviso que uses). La pestaña **Salud del observador** detalla
qué componente falla mientras el portal está en marcha.

## 7. Emisores remotos: cuotas, códigos y permisos

- Cada fuente remota tiene una cuota (por defecto **256 MiB/h y 200 000 eventos/h**,
  editable en **Modelo y análisis**). Si se agota, el receptor responde **429** con
  `Retry-After` y el emisor espera y reintenta sin perder nada.
- Con la cuota de almacenamiento llena responde **507**: el emisor conserva su cola
  y su cursor y reintenta. Conserva los archivos originales hasta resolverlo.
- `logsentinel spool-status --spool RUTA` muestra el estado de la cola de un emisor.
- Para detectar un emisor que se calló, pon en la fuente un **Plazo sin señal del emisor remoto**
  de 180 s (por defecto es 0: no vigila la ausencia).
- Tres permisos distintos, que no deben mezclarse: **leer los logs del cliente**
  (la cuenta sin login del emisor, solo lectura de esas rutas), el **token de
  fuente** (solo escribir eventos de esa fuente) y la **clave del panel** (todo).

## 8. Métricas de otros equipos

`logsentinel metrics-forward --receiver URL --machine-id ID --interval 60` envía
CPU, RAM, disco y carga de un Linux con cola durable. El token va en la variable
de entorno `LOGSENTINEL_METRICS_TOKEN`; el intervalo mínimo es de 10 s. Actualiza
primero el central y después los emisores, y usa el mismo intervalo en ambos.

Coste medido por muestra: unos **330 bytes** comprimidos, 12 ms de reloj y 3 ms de
CPU; a 60 s, unos **0,45 MiB al día por máquina**. Se conservan 30 días de muestras
y 365 de resúmenes diarios (mínimos y máximos). La ventana de 10 000 muestras cubre
24 horas con intervalos de 10 s o más.

## 9. Copias de seguridad

**Copias** en el portal crea una copia coherente y conserva las cinco últimas.
Contiene los logs originales y todas las credenciales. Para restaurar:

```bash
logsentinel restore /ruta/copia.db --data-dir /ruta/nueva
```

El destino debe no existir. Después rota la clave del panel, los tokens de fuente y
las credenciales de los destinos.

## 10. Sobre las ilustraciones

Las imágenes de Tentri (`logsentinel/portal/static/tentri-*.png`) son arte
generado para este proyecto. No son una marca oficial de Omarchy ni de ningún otro
proyecto.
