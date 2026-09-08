"use strict";
async function desktopView(root) {
  const state = await api("/api/widget");
  if (!root.isConnected) return;
  const intro = panel("LogSentinel × Omarchy");
  intro.append(
    el(
      "p",
      bilingual(
        "Un vistazo desde la barra: problemas abiertos, captura, análisis y recursos de tus máquinas. El widget sigue los colores de Omarchy y abre este portal para investigar.",
        "A glance from your bar: open findings, capture, analysis and machine resources. The widget follows Omarchy's colors and opens this portal for investigation.",
      ),
    ),
  );
  intro.append(
    el(
      "p",
      bilingual(
        "Necesita Omarchy Quattro con soporte de plugins y curl en el escritorio. El portal y el modelo se instalan por separado. En un equipo Ubuntu sin Omarchy puedes usar todos los temas y funciones del portal.",
        "Requires Omarchy Quattro with plugin support and curl on the desktop. Install the portal and model separately. On Ubuntu without Omarchy, all portal themes and features remain available.",
      ),
    ),
  );
  const install = panel(
    bilingual(
      "1. Instalar el widget en Omarchy",
      "1. Install the widget on Omarchy",
    ),
  );
  install.append(
    el(
      "p",
      bilingual(
        "Desde una copia publicada del repositorio que contenga manifest.json en su raíz:",
        "From a published copy of the repository that contains manifest.json at its root:",
      ),
    ),
    el(
      "pre",
      "omarchy plugin add https://github.com/IAnMove/LogSentinel.git --enable",
    ),
  );
  install.append(
    el(
      "p",
      bilingual(
        "La integración está preparada en el repositorio local. Antes de publicarla, valida el widget en una sesión real de Omarchy; consulta docs/OMARCHY.md.",
        "The integration is prepared in the local repository. Validate the widget in a real Omarchy session before publishing; see docs/OMARCHY.md.",
      ),
      "subtle",
    ),
  );
  const pair = panel(
    bilingual(
      "2. Vincular con permiso de solo lectura",
      "2. Pair with read-only access",
    ),
  );
  pair.append(
    el(
      "p",
      bilingual(
        "La credencial del widget permite ver nombres de máquinas, cifras de recursos y contadores. No permite leer logs, usar el LLM, cambiar ajustes ni iniciar sesión. Crear otra clave revoca la anterior.",
        "The widget credential exposes machine names, resource values and counters. It cannot read logs, use the LLM, change settings or sign in. Creating another key revokes the previous one.",
      ),
    ),
  );
  pair.append(badge(state.paired ? "active" : "disabled"));
  pair.append(
    actions(
      button(
        bilingual("Crear clave del widget", "Create widget key"),
        async () => {
          const result = await api("/api/widget/token", {});
          const config = JSON.stringify(
            { url: location.origin, token: result.token },
            null,
            2,
          );
          const box = el("div");
          box.append(
            el(
              "p",
              bilingual(
                "Guarda este JSON como ~/.config/logsentinel/widget.json en el escritorio Omarchy. Si el portal está en otro equipo, usa en url el puerto local de su túnel SSH. Esta clave solo se muestra ahora.",
                "Save this JSON as ~/.config/logsentinel/widget.json on the Omarchy desktop. If the portal runs elsewhere, set url to the local port of its SSH tunnel. This key is shown only now.",
              ),
            ),
            el("pre", config),
            button(
              bilingual("Copiar configuración", "Copy configuration"),
              async () => {
                await navigator.clipboard.writeText(config);
                notice(t("Copiado"));
              },
            ),
            el(
              "pre",
              "mkdir -p ~/.config/logsentinel\nchmod 700 ~/.config/logsentinel\n# Save widget.json inside this directory\nchmod 600 ~/.config/logsentinel/widget.json",
            ),
          );
          modal(
            bilingual(
              "Configuración privada del widget",
              "Private widget configuration",
            ),
            box,
          );
          await desktopViewRefresh();
        },
        "",
      ),
      button(
        bilingual("Revocar acceso del widget", "Revoke widget access"),
        async () => {
          await api("/api/widget/token", undefined, "DELETE");
          await desktopViewRefresh();
        },
        "danger",
      ),
    ),
  );
  const use = panel(bilingual("3. Abrir y comprobar", "3. Open and check"));
  use.append(
    el(
      "p",
      bilingual(
        "Pulsa LS en la barra. El panel se actualiza cada 30 segundos. Usa flechas y Enter para abrir el portal o actualizar; Escape cierra y Tab cambia de panel. LS ? indica falta de conexión; LS ! señala supervisión degradada o análisis pausado.",
        "Click LS in the bar. The panel refreshes every 30 seconds. Use arrows and Enter to open the portal or refresh; Escape closes and Tab switches panels. LS ? indicates no connection; LS ! means degraded supervision or paused analysis.",
      ),
    ),
    el(
      "pre",
      "omarchy-shell shell summon io.github.ianmove.logsentinel '{}'\nomarchy-shell shell hide io.github.ianmove.logsentinel",
    ),
  );
  root.append(intro, install, pair, use);
  async function desktopViewRefresh() {
    if (view === "desktop") await render();
  }
}
