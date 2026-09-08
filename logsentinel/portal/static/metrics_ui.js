"use strict";
function metricName(key) {
  if (key.startsWith("cpu_thread_pct:"))
    return bilingual("Hilo ", "Thread ") + key.split(":")[1];
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
  if (key.split(":")[0].endsWith("_bytes")) return resourceBytes(value);
  if (value === undefined || value === null) return "—";
  if (key.includes("bytes")) return resourceBytes(value);
  if (key === "uptime_seconds")
    return (value / 86400).toFixed(1) + " " + t("días");
  return (
    Number(value).toFixed(1) + (key.split(":")[0].endsWith("_pct") ? " %" : "")
  );
}
function metricState(state) {
  if (state === "paused")
    return bilingual(
      "Monitorización de la máquina pausada",
      "Machine monitoring paused",
    );
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
  const end = Date.now() / 1000;
  return recentMetricChart(key, {
    start: end - 86400,
    end,
    step_seconds: 3600,
    rows: rows.map((r) => ({ ...r, observed: Date.parse(r.bucket) / 1000 })),
  });
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
    await mountResourceOverview(root);
    return;
  }
  const machineId = scope,
    machine = S.machine.find((m) => m.id === machineId);
  const initial = await api("/api/telemetry/" + machineId);
  const live = el("div"),
    reports = panel(t("Análisis de tendencias guardados"));
  const hours = field(
    "chart_hours",
    bilingual("Gráficos recientes", "Recent charts"),
    "select",
    1,
    [
      [1, bilingual("Última hora", "Last hour")],
      [6, bilingual("Últimas 6 horas", "Last 6 hours")],
      [24, t("Últimas 24 horas")],
    ],
  );
  hours.querySelector("select").onchange = () =>
    update().catch((error) => notice(error.message, true));
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
    field(
      "discover_disks",
      bilingual(
        "Detectar discos locales montados",
        "Discover mounted local disks",
      ),
      "checkbox",
      cfg.discover_disks ?? true,
    ),
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
      "critical_threshold",
      t("Umbral crítico (%)"),
      "number",
      cfg.critical_threshold,
    ),
    field(
      "cpu_critical_samples",
      t("Muestras sostenidas para CPU crítica"),
      "number",
      cfg.cpu_critical_samples,
    ),
    field(
      "stale_intervals",
      t("Intervalos sin mediciones antes de avisar"),
      "number",
      cfg.stale_intervals,
    ),
    field(
      "notify_recovery",
      t("Notificar recuperación"),
      "checkbox",
      cfg.notify_recovery,
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
  const modeField = (form) => form.querySelector('[name="mode"]');
  const updateLocalFields = () => {
    const local = modeField(grid).value === "local";
    for (const name of ["disk_paths", "discover_disks"])
      grid.querySelector('[name="' + name + '"]').closest("label").hidden =
        !local;
  };
  modeField(grid).addEventListener("change", updateLocalFields);
  updateLocalFields();
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
      bilingual(
        "La captura es opcional y no usa tokens. RAM, swap y discos pueden alertar inmediatamente al superar el umbral crítico; CPU requiere muestras sostenidas. Los avisos se recuperan 5 puntos por debajo del umbral. El LLM de tendencias se activa por separado.",
        "Collection is optional and uses no tokens. RAM, swap and disks can alert immediately above the critical threshold; CPU requires sustained samples. Alerts recover 5 points below their threshold. LLM trend analysis is enabled separately.",
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
  const configDisclosure = disclosure(
    t("Configurar captura y alertas"),
    configPanel,
  );
  const inspection = el("p", "", "subtle");
  if (!cfg.enabled) configDisclosure.open = true;
  root.append(
    el(
      "p",
      bilingual(
        "Mediciones opcionales · Captura y alertas sin LLM · Actualización automática",
        "Optional measurements · Collection and alerts without an LLM · Automatic refresh",
      ),
      "subtle",
    ),
    button(t("Configurar captura y alertas"), () => {
      configDisclosure.open = true;
      configDisclosure.scrollIntoView({ block: "start" });
    }),
    hours,
    historyDays,
    inspection,
    live,
    controls,
    reports,
    configDisclosure,
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
          historyDays.querySelector("select").value +
          "&hours=" +
          hours.querySelector("select").value,
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
          bilingual(
            "Se ha superado el plazo configurado sin mediciones. Estos valores están desactualizados.",
            "The configured measurement deadline has passed. These values are out of date.",
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
    const primary = keys.filter(
      (k) =>
        ["cpu_pct", "ram_pct", "swap_pct"].includes(k) ||
        k.startsWith("disk_pct:"),
    );
    for (const key of primary) {
      tiles.append(resourceCard(key, data));
    }
    if (data.latest) live.append(tiles);
    if (data.latest) live.append(cpuThreadPanel(data));
    const extra = el("div", undefined, "metric-grid");
    for (const key of keys.filter((k) => !primary.includes(k)))
      extra.append(resourceCard(key, data));
    if (data.recent?.rows.length) {
      live.append(el("h2", bilingual("Evolución reciente", "Recent history")));
      const charts = el("div", undefined, "resource-charts");
      for (const key of primary.filter(
        (k) => k.includes("_pct") && data.recent.rows.some((r) => r.key === k),
      ))
        charts.append(
          recentMetricChart(
            key,
            data.recent,
            resourceThreshold(key, data.config),
          ),
        );
      live.append(
        charts,
        el(
          "p",
          bilingual(
            "Picos conservados al agrupar muestras. Horas en tu zona local; el resumen diario usa UTC. La línea discontinua marca el umbral de aviso. No se interpolan periodos sin muestras.",
            "Grouped samples preserve peaks. Times use your local zone; daily summaries use UTC. The dashed line marks the warning threshold. Periods without samples are not interpolated.",
          ),
          "subtle",
        ),
      );
      if (data.recent.truncated)
        live.append(
          el(
            "p",
            bilingual(
              "Gráfico limitado a las 10.000 muestras más recientes del periodo. Consulta también los resúmenes por hora.",
              "Chart limited to the latest 10,000 samples in this period. Also check the hourly summaries.",
            ),
            "monitor-warning",
          ),
        );
    }
    if (data.latest)
      live.append(
        disclosure(
          bilingual(
            "Más contadores: E/S, carga, inodos y tiempo encendido",
            "More counters: I/O wait, load, inodes and uptime",
          ),
          extra,
        ),
      );
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
      const charts = el("div", undefined, "metric-grid");
      for (const key of keys.filter(
        (k) => k.includes("_pct") && data.hourly.some((r) => r.key === k),
      ))
        charts.append(metricChart(key, data.hourly));
      live.append(
        disclosure(t("Máximos y medias por hora, últimas 24 h"), charts),
      );
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
      // Keep the keyboard position while someone inspects a chart or history.
      const inspecting = live.contains(document.activeElement);
      inspection.textContent = inspecting
        ? bilingual(
            "Actualización visual en pausa mientras inspeccionas los datos. Haz clic fuera del gráfico o del historial para reanudarla; la captura continúa.",
            "Display refresh paused while you inspect the data. Click outside the chart or history to resume; collection continues.",
          )
        : "";
      if (!inspecting) await update();
    } catch (error) {
      notice(error.message, true);
    }
    setTimeout(poll, 15000);
  };
  setTimeout(poll, 15000);
}
