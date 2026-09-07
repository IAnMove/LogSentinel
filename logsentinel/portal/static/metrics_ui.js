"use strict";
function metricName(key) {
  const [base, ...path] = key.split(":");
  return (
    ({
      cpu_pct: "CPU",
      ram_pct: "RAM",
      swap_pct: "Swap",
      iowait_pct: t("Espera de E/S"),
      disk_pct: t("Disco"),
      inode_pct: t("Inodos"),
      load1: t("Carga 1 minuto"),
      load5: t("Carga 5 minutos"),
      load15: t("Carga 15 minutos"),
      uptime_seconds: t("Tiempo encendido"),
    }[base] || base) + (path.length ? " · " + path.join(":") : "")
  );
}
function metricValue(key, value) {
  if (value === undefined || value === null) return "—";
  if (key.includes("bytes")) return bytes(value);
  if (key === "uptime_seconds")
    return (value / 86400).toFixed(1) + " " + t("días");
  return (
    Number(value).toFixed(1) + (key.split(":")[0].endsWith("_pct") ? " %" : "")
  );
}
function metricState(state) {
  return t(
    {
      active: "Mediciones activas",
      disabled: "Mediciones desactivadas",
      waiting: "Esperando primera muestra",
      stale: "Sin datos recientes",
      partial: "Medición parcial",
    }[state] || state,
  );
}
function metricChart(key, rows) {
  const card = panel(metricName(key)),
    ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 480 120");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    metricName(key) + " · " + t("Máximos y medias por hora, últimas 24 h"),
  );
  svg.classList.add("metric-chart");
  const selected = rows.filter((r) => r.key === key);
  const end = Date.now(),
    start = end - 86400000;
  const scale = key.split(":")[0].endsWith("_pct")
    ? 100
    : Math.max(1, ...selected.map((r) => r.maximum));
  for (const type of ["maximum", "average"]) {
    let points = [],
      previous = null;
    function draw() {
      if (!points.length) return;
      const line = document.createElementNS(ns, "polyline");
      line.setAttribute("points", points.join(" "));
      line.setAttribute("class", "metric-" + type);
      svg.append(line);
    }
    for (const row of selected) {
      const stamp = Date.parse(row.bucket);
      if (previous !== null && stamp - previous > 3600000) {
        draw();
        points = [];
      }
      const x = Math.max(
          5,
          Math.min(475, 5 + (470 * (stamp - start)) / (end - start)),
        ),
        y = 110 - (100 * row[type]) / scale;
      points.push(x + "," + y);
      const dot = document.createElementNS(ns, "circle"),
        title = document.createElementNS(ns, "title");
      dot.setAttribute("cx", x);
      dot.setAttribute("cy", y);
      dot.setAttribute("r", 2);
      dot.setAttribute("class", "metric-" + type);
      title.textContent =
        row.bucket +
        " · " +
        t(type === "maximum" ? "Máximo" : "Media") +
        ": " +
        metricValue(key, row[type]) +
        " · " +
        row.n +
        " " +
        t("muestras");
      dot.append(title);
      svg.append(dot);
      previous = stamp;
    }
    draw();
  }
  card.append(
    svg,
    el(
      "p",
      t("Naranja: máximo · Azul: media · Huecos: sin muestras"),
      "subtle",
    ),
  );
  return card;
}

async function metricsView(root) {
  if (!S.machine.length) {
    root.append(
      el("p", t("Añade una máquina antes de configurar las métricas.")),
      button(t("Máquinas"), () => navigate("machine")),
    );
    return;
  }
  if (!scope) {
    const overview = await api("/api/telemetry");
    if (!root.isConnected) return;
    root.replaceChildren();
    root.append(
      el(
        "p",
        t(
          "Mediciones y alertas por máquina. Abre un equipo para configurar captura, umbrales e historial.",
        ),
      ),
    );
    if (overview.error) root.append(el("p", overview.error, "error"));
    const cards = el("div", undefined, "metric-grid");
    for (const state of overview.machines) {
      const p = panel(machineName(state.machine_id));
      p.append(
        el("p", metricState(state.state)),
        el("p", t("Última muestra") + ": " + stamp(state.latest?.observed)),
      );
      for (const key of ["cpu_pct", "ram_pct", "swap_pct", "disk_pct:/"])
        p.append(
          el(
            "p",
            metricName(key) +
              ": " +
              metricValue(key, state.latest?.values[key]),
          ),
        );
      p.append(
        button(t("Ver métricas y configurar"), () => {
          scope = state.machine_id;
          $("#machine-scope").value = scope;
          render();
        }),
      );
      cards.append(p);
    }
    root.append(cards);
    setTimeout(() => {
      if (root.isConnected && !scope)
        metricsView(root).catch((error) => notice(error.message, true));
    }, 5000);
    return;
  }
  const machineId = scope,
    machine = S.machine.find((m) => m.id === machineId);
  const initial = await api("/api/telemetry/" + machineId);
  const live = el("div"),
    reports = panel(t("Análisis de tendencias guardados"));
  const historyDays = field(
    "history_days",
    t("Días de historial diario"),
    "select",
    7,
    [7, 30, 90, 365].map((n) => [n, String(n)]),
  );
  historyDays.querySelector("select").onchange = () =>
    update().catch((error) => notice(error.message, true));
  const controls = panel(t("Interpretar la evolución con el LLM"));
  const days = field("trend_days", t("Periodo"), "select", 1, [
    [1, t("Últimas 24 horas")],
    [7, t("Últimos 7 días")],
    [30, t("Últimos 30 días")],
  ]);
  const analyze = button(t("Analizar tendencias"), async () => {
    await api("/api/telemetry/" + machineId + "/analyze", {
      language: locale,
      days: Number(days.querySelector("select").value),
    });
    notice(t("Análisis de tendencias en cola; puedes cerrar esta vista."));
    await update();
  });
  controls.append(
    el(
      "p",
      t(
        "Una llamada con resúmenes de todo el periodo, ajustados al contexto. No modifica la máquina. Las alertas por umbral funcionan sin LLM.",
      ),
    ),
    days,
    analyze,
  );
  const form = el("form"),
    cfg = initial.config;
  const fields = [
    field("enabled", t("Activar mediciones"), "checkbox", cfg.enabled),
    field("mode", t("Origen de las métricas"), "select", cfg.mode, [
      ["remote", t("Emisor remoto")],
      ...(machine.kind === "local"
        ? [["local", t("Este equipo (servidor del portal)")]]
        : []),
    ]),
    field(
      "interval_seconds",
      t("Intervalo de medición (segundos)"),
      "number",
      cfg.interval_seconds,
    ),
    field(
      "disk_paths",
      t("Rutas de discos locales (una por línea)"),
      "textarea",
      cfg.disk_paths.join("\n"),
    ),
    field(
      "retention_days",
      t("Días de muestras comprimidas"),
      "number",
      cfg.retention_days,
    ),
    field(
      "daily_retention_days",
      t("Días de resúmenes diarios"),
      "number",
      cfg.daily_retention_days,
    ),
    ...[
      ["cpu_threshold", "CPU"],
      ["ram_threshold", "RAM"],
      ["swap_threshold", "Swap"],
      ["disk_threshold", t("Disco")],
      ["inode_threshold", t("Inodos")],
    ].map(([key, label]) =>
      field(key, t("Umbral de aviso (%)") + " · " + label, "number", cfg[key]),
    ),
    field(
      "consecutive_samples",
      t("Muestras consecutivas para alertar"),
      "number",
      cfg.consecutive_samples,
    ),
    field(
      "spike_points",
      t("Subida brusca (puntos porcentuales)"),
      "number",
      cfg.spike_points,
    ),
    field(
      "cooldown_seconds",
      t("Separación entre avisos (segundos)"),
      "number",
      cfg.cooldown_seconds,
    ),
    field(
      "llm_enabled",
      t("Analizar tendencias automáticamente con el LLM"),
      "checkbox",
      cfg.llm_enabled,
    ),
    field(
      "llm_interval_seconds",
      t("Intervalo del análisis de tendencias (segundos)"),
      "number",
      cfg.llm_interval_seconds,
    ),
  ];
  const grid = el("div", undefined, "form-grid");
  grid.append(...fields);
  const save = el("button", t("Guardar configuración de métricas"));
  save.type = "submit";
  form.append(grid, save);
  form.onsubmit = async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const data = formData(form);
      data.disk_paths = data.disk_paths
        .split("\n")
        .map((p) => p.trim())
        .filter(Boolean);
      await api("/api/telemetry/" + machineId + "/config", data);
      await refresh();
      notice(t("Configuración guardada."));
    } catch (error) {
      notice(error.message, true);
    } finally {
      save.disabled = false;
    }
  };
  const configPanel = panel(t("Configuración de métricas"));
  configPanel.append(
    el(
      "p",
      t(
        "El 98 % dispara una alerta crítica inmediata. Los demás umbrales requieren muestras consecutivas; se recuperan 5 puntos por debajo. Un pico compara con hasta 10 muestras anteriores. Las alertas usan los canales configurados y permanecen en Problemas hasta su revisión.",
      ),
    ),
    form,
  );
  const remote = panel(t("Conectar un emisor remoto"));
  remote.append(
    el(
      "p",
      t(
        "Activa el modo remoto y genera una clave exclusiva para esta máquina. Usa un túnel SSH o HTTPS. Configura el mismo intervalo y los discos en el emisor.",
      ),
    ),
    button(t("Generar clave de métricas"), async () => {
      const result = await api("/api/telemetry/" + machineId + "/token", {});
      modal(
        t("Guarda esta clave: se muestra una vez"),
        el("pre", result.token),
      );
    }),
    el(
      "pre",
      "read -rsp 'Metrics token: ' LOGSENTINEL_METRICS_TOKEN\nexport LOGSENTINEL_METRICS_TOKEN\nlogsentinel metrics-forward --receiver http://127.0.0.1:8766 --machine-id " +
        machineId +
        " --interval " +
        cfg.interval_seconds +
        " --disk /",
    ),
  );
  root.append(
    historyDays,
    live,
    controls,
    reports,
    disclosure(t("Configurar captura y alertas"), configPanel),
    disclosure(t("Conectar otro equipo"), remote),
  );
  async function update(data) {
    if (!root.isConnected) return;
    data =
      data ||
      (await api(
        "/api/telemetry/" +
          machineId +
          "?days=" +
          historyDays.querySelector("select").value,
      ));
    if (!root.isConnected) return;
    live.replaceChildren();
    reports.replaceChildren(el("h2", t("Análisis de tendencias guardados")));
    const status = panel(metricState(data.state));
    if (
      !(S.destination || []).some(
        (d) =>
          d.enabled &&
          (!d.machine_id || d.machine_id === machineId) &&
          (!d.source_id || d.source_id === "metrics:" + machineId),
      )
    ) {
      status.append(
        el(
          "p",
          t(
            "No hay destinos de notificación activos para estas métricas. Las alertas se guardan en Problemas; configura los avisos en Notificaciones.",
          ),
          "monitor-warning",
        ),
      );
    }
    status.append(
      el(
        "p",
        t("Última muestra") +
          ": " +
          stamp(data.latest?.observed) +
          " · " +
          t("Intervalo") +
          ": " +
          data.config.interval_seconds +
          " s · " +
          data.retained_samples +
          " " +
          t("muestras retenidas") +
          " · " +
          bytes(data.compressed_bytes) +
          " " +
          t("comprimidos"),
      ),
    );
    if (data.state === "stale")
      status.append(
        el(
          "p",
          t(
            "Han pasado más de tres intervalos sin mediciones. Estos valores están desactualizados.",
          ),
          "monitor-warning",
        ),
      );
    if (data.error) status.append(el("p", data.error, "error"));
    for (const error of data.latest?.errors || [])
      status.append(el("p", error, "monitor-warning"));
    status.append(
      el(
        "p",
        t(
          "RAM basada en memoria disponible. Swap sin configurar aparece como —. La primera muestra aún no tiene porcentaje de CPU. Mínimos y máximos observados, no continuos.",
        ),
        "subtle",
      ),
    );
    live.append(status);
    const values = data.latest?.values || {},
      tiles = el("div", undefined, "metric-grid");
    const keys = [
      "cpu_pct",
      "ram_pct",
      "swap_pct",
      "iowait_pct",
      ...[
        ...new Set([...Object.keys(values), ...data.daily.map((r) => r.key)]),
      ].filter((k) => k.startsWith("disk_pct:") || k.startsWith("inode_pct:")),
      "load1",
      "load5",
      "load15",
      "uptime_seconds",
    ];
    for (const key of keys) {
      const card = panel(metricName(key));
      card.append(el("strong", metricValue(key, values[key]), "metric-value"));
      tiles.append(card);
    }
    live.append(tiles);
    for (const alert of data.active_alerts)
      live.append(
        button(
          t("Ver alerta") +
            ": " +
            metricName(alert.key.replace(/:(capacity|spike)$/, "")),
          () => openProblemPage(alert.problem_id),
        ),
      );
    if (data.hourly.length) {
      live.append(el("h2", t("Máximos y medias por hora, últimas 24 h")));
      const charts = el("div", undefined, "metric-grid");
      for (const key of keys.filter(
        (k) => k.includes("_pct") && data.hourly.some((r) => r.key === k),
      ))
        charts.append(metricChart(key, data.hourly));
      live.append(charts);
    }
    if (data.daily.length) {
      live.append(
        disclosure(
          t("Mínimos y máximos diarios (UTC)"),
          table(
            [
              t("Día"),
              t("Métrica"),
              t("Mínimo"),
              t("Máximo"),
              t("Media"),
              t("Muestras"),
            ],
            data.daily
              .filter((r) => keys.includes(r.key))
              .map((r) => [
                r.bucket,
                metricName(r.key),
                metricValue(r.key, r.minimum),
                metricValue(r.key, r.maximum),
                metricValue(r.key, r.average),
                r.n,
              ]),
          ),
        ),
      );
    }
    analyze.disabled =
      !data.latest ||
      data.analyses.some((j) => ["queued", "running"].includes(j.status));
    for (const job of [...data.analyses].reverse()) {
      const box = panel(stamp(job.created) + " · " + statusLabel(job.status));
      if (job.error) box.append(el("p", job.error, "error"));
      if (job.result)
        box.append(
          el("p", job.result.answer),
          el("p", job.result.metrics.map(metricName).join(", ")),
        );
      if (job.result?.next_checks)
        box.append(
          el("h3", t("Siguientes comprobaciones")),
          el("p", job.result.next_checks),
        );
      if (job.result?.incomplete_coverage)
        box.append(
          el(
            "p",
            typeof job.result.incomplete_coverage === "string"
              ? job.result.incomplete_coverage
              : t("El modelo indica que la cobertura es incompleta."),
            "monitor-warning",
          ),
        );
      if (job.context)
        box.append(
          disclosure(
            t("Contexto enviado al modelo"),
            el(
              "pre",
              JSON.stringify(
                { coverage: job.coverage, payload: job.context },
                null,
                2,
              ),
            ),
          ),
        );
      reports.append(box);
    }
  }
  await update(initial);
  const poll = async () => {
    if (!root.isConnected) return;
    try {
      await update();
    } catch (error) {
      notice(error.message, true);
    }
    setTimeout(poll, 5000);
  };
  setTimeout(poll, 5000);
}
