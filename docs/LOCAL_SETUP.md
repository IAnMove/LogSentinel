# Instalación local, túnel SSH y LLM llama.cpp

## Portal en este equipo

El portal está instalado en `/home/ina/security-agent/.venv` y escucha en `127.0.0.1:8766`. El puerto `8765` ya lo usa `journal-server` y `8080` lo usa `bigpapi`.

Para lanzarlo manualmente:

```bash
cd /home/ina/security-agent
.venv/bin/logsentinel portal \
  --data-dir /home/ina/.local/share/logsentinel/portal \
  --port 8766
```

La clave aparece una vez en la terminal. La URL local es `http://127.0.0.1:8766`.

Para ejecutarlo con systemd de usuario:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/logsentinel-portal.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now logsentinel-portal.service
systemctl --user status logsentinel-portal.service
```

Si se ejecuta como servicio, la clave inicial se puede consultar en el journal de ese servicio. Protege el directorio de datos: contiene credenciales de destinos y del LLM.

## Acceso desde fuera mediante túnel inverso

El portal no se expone directamente a Internet. Si este equipo está detrás de NAT, necesita un servidor SSH accesible, por ejemplo `usuario@vps`. Desde este equipo abre un túnel inverso:

```bash
ssh -NT \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:18766:127.0.0.1:8766 \
  usuario@vps
```

El puerto remoto queda ligado al loopback del VPS; no queda público. Desde el portátil que uses para navegar, crea un segundo túnel hacia el VPS:

```bash
ssh -NT -L 8766:127.0.0.1:18766 usuario@vps
```

Abre entonces `http://127.0.0.1:8766` en ese portátil. Mantén ambas sesiones SSH abiertas. Para que sobreviva a cortes, usa `autossh` o una unidad systemd de usuario con `Restart=always`; el servidor SSH debe permitir `AllowTcpForwarding remote`.

No uses `-R 0.0.0.0:18766` salvo que quieras publicar deliberadamente un panel administrativo. El portal tiene autenticación, pero el túnel de loopback reduce la superficie expuesta.

## LLM local Qwen3

El modelo es `Qwen3-8B-Q4_K_M.gguf`. En este equipo `llama-node` no podía iniciar porque el puerto 8080 estaba ocupado por `bigpapi`. Se ha aplicado un drop-in de systemd que lo mueve a `127.0.0.1:8081` y desactiva las capas GPU (`-ngl 0`), porque los logs indican que no hay una GPU Vulkan utilizable.

Comprobaciones:

```bash
systemctl status llama-node
curl http://127.0.0.1:8081/health
curl http://127.0.0.1:8081/v1/models
journalctl -u llama-node -f
```

El modelo publica el identificador completo:

```text
/opt/llm-node/models/Qwen3-8B-Q4_K_M.gguf
```

En **Modelo y análisis** del portal se ha guardado esta configuración local:

```text
Proveedor: API compatible
URL:      http://127.0.0.1:8081/v1
Modelo:   /opt/llm-node/models/Qwen3-8B-Q4_K_M.gguf
Pensamiento Qwen3: desactivado
```

Qwen3 puede consumir el límite de salida razonando antes de producir JSON. El portal envía `chat_template_kwargs.enable_thinking=false` cuando esta opción está desactivada. Se puede activar desde el formulario si se quiere razonamiento prolongado, pero habrá que aumentar el presupuesto de salida y aceptar menor rendimiento.

## Rendimiento y seguridad

La petición OpenAI compatible funciona y devuelve JSON. La inferencia observada es CPU; el modelo pesa aproximadamente 5 GB. Antes de activar fuentes reales, comprueba la velocidad con `Probar modelo` y ejecuta un lote pequeño. El portal conserva los logs localmente y solo permite enviar contexto a un endpoint remoto si se autoriza explícitamente en sus ajustes.
