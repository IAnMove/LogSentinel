"use strict";
const bilingual = (es, en) => (locale === "es" ? es : en);
async function healthView(root) {
  const intro = panel(t("Salud del observador"));
  intro.append(
    el(
      "p",
      bilingual(
        "Estas comprobaciones no consumen tokens. La captura, las métricas y los avisos se supervisan aunque el modelo esté ocupado. Para detectar una caída completa del portal, supervisa /healthz desde otro proceso o equipo.",
        "These checks use no tokens. Capture, measurements and notifications are supervised while the model is busy. Monitor /healthz from another process or machine to detect a complete portal outage.",
      ),
    ),
  );
  const live = el("div");
  root.append(intro, live);
  async function update() {
    const health = await api("/api/health");
    if (!root.isConnected) return;
    const head = panel(
      bilingual("Última comprobación", "Last check") +
        ": " +
        stamp(health.checked),
    );
    head.append(badge(health.state));
    if (health.error) head.append(el("p", health.error, "monitor-warning"));
    head.append(
      el(
        "p",
        bilingual(
          "Un log sin líneas nuevas puede estar sano: se comprueba la conexión, no el volumen. Las mediciones antiguas indican falta de datos, no demuestran que la máquina esté apagada.",
          "A quiet log can be healthy: availability uses connection checks, not volume. Old measurements indicate missing data; they do not prove the machine is down.",
        ),
      ),
    );
    const cards = el("div", undefined, "metric-grid");
    for (const check of health.checks.filter(
      (c) => !scope || !c.machine_id || c.machine_id === scope,
    )) {
      const title =
        {
          "Machine measurements stopped": bilingual(
            "Continuidad de métricas",
            "Measurement continuity",
          ),
          "Log source needs attention": bilingual(
            "Captura de logs",
            "Log capture",
          ),
          "Observer storage is approaching capacity": bilingual(
            "Almacenamiento",
            "Storage",
          ),
          "Observer worker needs attention": bilingual(
            "Proceso del observador",
            "Observer worker",
          ),
          "Recent model requests failed": bilingual(
            "Consultas al modelo",
            "Model requests",
          ),
          "Log review is behind incoming volume": bilingual(
            "Cobertura del análisis",
            "Analysis coverage",
          ),
        }[check.title] || check.title;
      const item = panel(title);
      item.append(
        el("p", machineName(check.machine_id) + " · " + check.key),
        badge(check.bad ? (check.active ? "degraded" : "checking") : "ok"),
      );
      if (check.problem_id)
        item.append(
          button(t("Ver detalles"), () => openProblemPage(check.problem_id)),
        );
      const details = el("details");
      details.append(
        el("summary", t("Detalle")),
        el("pre", JSON.stringify(check.detail, null, 2)),
      );
      if (check.persistence_error)
        item.append(el("p", check.persistence_error, "monitor-warning"));
      item.append(details);
      cards.append(item);
    }
    live.replaceChildren(head, cards);
  }
  await update();
  const throughput = el("div");
  root.append(throughput);
  await mountCapacitySummary(throughput, scope);
  const config = panel(
      bilingual("Supervisión automática", "Automatic supervision"),
    ),
    form = el("form", undefined, "form-grid");
  form.append(
    field(
      "health_alerts",
      bilingual(
        "Crear problemas y avisar de fallos y recuperaciones",
        "Create findings and notify on failures and recoveries",
      ),
      "checkbox",
      S.settings.health_alerts,
    ),
    field(
      "health_grace_seconds",
      bilingual(
        "Persistencia del fallo antes de alertar (segundos)",
        "Fault duration before alerting (seconds)",
      ),
      "number",
      S.settings.health_grace_seconds,
    ),
    field(
      "storage_warning_percent",
      bilingual(
        "Avisar al alcanzar esta parte de la cuota (%)",
        "Warn at this storage quota usage (%)",
      ),
      "number",
      S.settings.storage_warning_percent,
    ),
  );
  const save = el("button", t("Guardar"));
  form.append(save);
  form.onsubmit = async (event) => {
    event.preventDefault();
    save.disabled = true;
    try {
      await api("/api/settings", formData(form));
      await refresh();
    } catch (error) {
      notice(error.message, true);
    } finally {
      save.disabled = false;
    }
  };
  config.append(form);
  root.append(config);
  const poll = setInterval(() => {
    if (!root.isConnected || view !== "health") return clearInterval(poll);
    update().catch((error) => notice(error.message, true));
  }, 5000);
}
