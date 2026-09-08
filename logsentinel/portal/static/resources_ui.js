"use strict";

function resourceBytes(value) {
  if (value == null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return value.toFixed(unit ? 1 : 0) + " " + units[unit];
}

function resourceThreshold(key, cfg) {
  return cfg[
    {
      cpu_pct: "cpu_threshold",
      ram_pct: "ram_threshold",
      swap_pct: "swap_threshold",
      disk_pct: "disk_threshold",
      inode_pct: "inode_threshold",
    }[key.split(":")[0]]
  ];
}

function resourceCard(key, data) {
  const values = data.latest?.values || {},
    value = values[key];
  const card = panel(metricName(key));
  card.classList.add("resource-card");
  const current = ["active", "partial"].includes(data.state);
  const threshold = resourceThreshold(key, data.config);
  card.append(el("strong", metricValue(key, value), "metric-value"));
  if (key.split(":")[0].endsWith("_pct") && value != null) {
    const meter = el("div", undefined, "resource-meter"),
      fill = el("span");
    meter.setAttribute("role", "meter");
    meter.setAttribute("aria-label", metricName(key));
    meter.setAttribute("aria-valuemin", "0");
    meter.setAttribute("aria-valuemax", "100");
    meter.setAttribute("aria-valuenow", value.toFixed(1));
    fill.style.width = Math.max(0, Math.min(100, value)) + "%";
    meter.append(fill);
    if (threshold != null) {
      const marker = el("i");
      marker.style.left = threshold + "%";
      marker.title =
        bilingual("Umbral de aviso: ", "Warning threshold: ") + threshold + "%";
      meter.append(marker);
    }
    card.classList.toggle(
      "resource-warning",
      current && threshold != null && value >= threshold,
    );
    card.classList.toggle("resource-old", !current);
    card.append(meter);
  }
  let total, used, available;
  if (key === "ram_pct") {
    total = values.ram_total_bytes;
    available = values.ram_available_bytes;
    if (total != null && available != null)
      used = Math.max(0, total - available);
  } else if (key === "swap_pct") {
    total = values.swap_total_bytes;
    used = values.swap_used_bytes;
    if (total === 0)
      card.append(
        el(
          "p",
          bilingual("Sin swap configurada", "Swap not configured"),
          "subtle",
        ),
      );
  } else if (key.startsWith("disk_pct:")) {
    const path = key.slice(9);
    total = values["disk_total_bytes:" + path];
    available = values["disk_available_bytes:" + path];
    if (total != null && available != null)
      used = Math.max(0, total - available);
  }
  if (total > 0 && used != null)
    card.append(
      el(
        "p",
        resourceBytes(used) + " / " + resourceBytes(total),
        "resource-detail",
      ),
    );
  if (available != null)
    card.append(
      el(
        "p",
        resourceBytes(available) + bilingual(" disponibles", " available"),
        "subtle",
      ),
    );
  if (key === "cpu_pct")
    card.append(
      el(
        "p",
        (values.cpu_count == null
          ? ""
          : values.cpu_count +
            bilingual(" CPU lógicas · ", " logical CPUs · ")) +
          bilingual("media entre muestras", "average between samples"),
        "subtle",
      ),
    );
  if (!current && data.latest)
    card.append(
      el(
        "p",
        bilingual("Último valor guardado", "Last stored value"),
        "subtle",
      ),
    );
  else if (value != null && threshold != null && value >= threshold)
    card.append(
      el(
        "p",
        bilingual("Sobre el umbral de aviso", "Above warning threshold"),
        "subtle",
      ),
    );
  return card;
}

function openMachineMetrics(id) {
  scope = id;
  $("#machine-scope").value = id;
  navigate("metrics");
}

async function mountResourceOverview(root, machineId = "") {
  root.append(
    el("h2", bilingual("Recursos de los equipos", "Machine resources")),
    el(
      "p",
      bilingual(
        "CPU, RAM y discos: captura opcional por máquina, sin tokens. Los gráficos y las alertas por umbral funcionan sin LLM.",
        "CPU, RAM and disks: optional collection per machine, with no tokens. Charts and threshold alerts work without an LLM.",
      ),
      "subtle",
    ),
  );
  const grid = el("div", undefined, "resource-fleet"),
    errorBox = el("p", "", "error");
  root.append(errorBox, grid);
  const entries = new Map();
  async function update() {
    try {
      const result = await api("/api/telemetry");
      if (!root.isConnected) return;
      errorBox.textContent = result.error || "";
      const machines = result.machines.filter(
        (m) => !machineId || m.machine_id === machineId,
      );
      for (const data of machines) {
        if (!entries.has(data.machine_id)) {
          const card = panel(machineName(data.machine_id)),
            live = el("div");
          card.append(
            live,
            button(t("Ver métricas y configurar"), () =>
              openMachineMetrics(data.machine_id),
            ),
          );
          grid.append(card);
          entries.set(data.machine_id, { card, live });
        }
        const { live } = entries.get(data.machine_id);
        live.replaceChildren(
          el("p", metricState(data.state), "resource-state"),
        );
        if (data.latest) {
          live.append(
            el(
              "p",
              t("Última muestra") + ": " + stamp(data.latest.observed),
              "subtle",
            ),
          );
          const tiles = el("div", undefined, "resource-strip");
          const disks = Object.keys(data.latest.values).filter((k) =>
            k.startsWith("disk_pct:"),
          );
          for (const key of ["cpu_pct", "ram_pct", "swap_pct", ...disks])
            tiles.append(resourceCard(key, data));
          live.append(tiles);
        } else {
          live.append(
            el(
              "p",
              bilingual(
                "Activa las mediciones para ver este equipo aquí. Para otro PC, conecta su emisor de métricas; sus archivos de log no contienen estos contadores.",
                "Enable measurements to see this machine here. For another PC, connect its metrics sender; log files do not provide these counters.",
              ),
              "subtle",
            ),
          );
        }
      }
      for (const [id, item] of entries)
        if (!machines.some((m) => m.machine_id === id)) {
          item.card.remove();
          entries.delete(id);
        }
    } catch (error) {
      if (root.isConnected) errorBox.textContent = error.message;
    }
    if (root.isConnected) setTimeout(update, 15000);
  }
  await update();
}

function recentMetricChart(key, history, threshold) {
  const card = panel(metricName(key)),
    ns = "http://www.w3.org/2000/svg";
  const rows = history.rows.filter((r) => r.key === key);
  const title =
    metricName(key) + " · " + bilingual("Evolución reciente", "Recent history");
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 520 180");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", title);
  svg.classList.add("metric-chart", "resource-chart");
  const node = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    svg.append(n);
    return n;
  };
  const x = (stamp) =>
    40 + (470 * (stamp - history.start)) / (history.end - history.start);
  const y = (value) => 145 - 1.3 * value;
  for (const value of [0, 50, 100]) {
    node("line", {
      x1: 40,
      x2: 510,
      y1: y(value),
      y2: y(value),
      class: "resource-gridline",
    });
    node(
      "text",
      { x: 34, y: y(value) + 4, "text-anchor": "end", class: "resource-axis" },
      value + "%",
    );
  }
  const timeLabel = (at) =>
    new Date(at * 1000).toLocaleTimeString(
      locale === "es" ? "es-ES" : "en-GB",
      { hour: "2-digit", minute: "2-digit" },
    );
  node(
    "text",
    { x: 40, y: 170, class: "resource-axis" },
    timeLabel(history.start),
  );
  node(
    "text",
    { x: 510, y: 170, "text-anchor": "end", class: "resource-axis" },
    timeLabel(history.end),
  );
  if (threshold != null)
    node("line", {
      x1: 40,
      x2: 510,
      y1: y(threshold),
      y2: y(threshold),
      class: "resource-threshold",
    });
  for (const type of ["maximum", "average"]) {
    let points = [],
      previous;
    const draw = () => {
      if (points.length)
        node("polyline", { points: points.join(" "), class: "metric-" + type });
    };
    for (const row of rows) {
      if (
        previous != null &&
        row.observed - previous > history.step_seconds * 1.01
      ) {
        draw();
        points = [];
      }
      points.push(x(row.observed) + "," + y(row[type]));
      node("circle", {
        cx: x(row.observed),
        cy: y(row[type]),
        r: 2,
        class: "metric-" + type,
      });
      previous = row.observed;
    }
    draw();
  }
  const legend = el("p", undefined, "resource-legend subtle");
  legend.append(
    el("span", t("Máximo"), "legend-maximum"),
    el("span", t("Media"), "legend-average"),
    el("span", bilingual("Huecos: sin muestras", "Gaps: no samples")),
  );
  card.append(svg, legend);
  if (rows.length) {
    const readout = el("p", "", "resource-readout"),
      control = el(
        "label",
        bilingual("Inspeccionar muestra", "Inspect sample"),
      );
    const slider = el("input");
    slider.type = "range";
    slider.min = 0;
    slider.max = rows.length - 1;
    slider.value = rows.length - 1;
    slider.setAttribute(
      "aria-label",
      title + " · " + bilingual("Inspeccionar muestra", "Inspect sample"),
    );
    const show = (index) => {
      const row = rows[index];
      slider.value = index;
      const text =
        stamp(row.observed) +
        " · " +
        t("Mínimo") +
        ": " +
        metricValue(key, row.minimum) +
        " · " +
        t("Máximo") +
        ": " +
        metricValue(key, row.maximum) +
        " · " +
        t("Media") +
        ": " +
        metricValue(key, row.average) +
        " · " +
        row.n +
        " " +
        t("muestras");
      readout.textContent = text;
      slider.setAttribute("aria-valuetext", text);
    };
    slider.oninput = () => show(Number(slider.value));
    svg.onpointermove = (e) => {
      if (e.pointerType === "touch") return;
      const box = svg.getBoundingClientRect(),
        target =
          history.start +
          ((((e.clientX - box.left) / box.width) * 520 - 40) / 470) *
            (history.end - history.start);
      let nearest = 0;
      for (let i = 1; i < rows.length; i++)
        if (
          Math.abs(rows[i].observed - target) <
          Math.abs(rows[nearest].observed - target)
        )
          nearest = i;
      show(nearest);
    };
    control.append(slider);
    card.append(readout, control);
    show(rows.length - 1);
  }
  return card;
}
