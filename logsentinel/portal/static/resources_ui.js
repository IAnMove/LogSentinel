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
  if (
    key.split(":")[0].endsWith("_pct") &&
    !key.startsWith("disk_pct:") &&
    value != null
  ) {
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
  if (key === "ram_pct") {
    const breakdown = el("dl", undefined, "resource-breakdown");
    for (const [label, amount] of [
      [bilingual("Total", "Total"), total],
      [bilingual("Usada", "Used"), values.ram_used_bytes ?? used],
      [bilingual("Libre", "Free"), values.ram_free_bytes],
      [bilingual("Compartida", "Shared"), values.ram_shared_bytes],
      ["Buffers", values.ram_buffers_bytes],
      [bilingual("Caché", "Cache"), values.ram_cached_bytes],
      ["Buff/cache", values.ram_buff_cache_bytes],
      [bilingual("Disponible", "Available"), available],
    ])
      breakdown.append(el("dt", label), el("dd", resourceBytes(amount)));
    card.append(
      breakdown,
      el(
        "p",
        bilingual(
          "Disponible incluye memoria recuperable. Estos campos se solapan; no se suman.",
          "Available includes reclaimable memory. These fields overlap; do not add them together.",
        ),
        "subtle",
      ),
    );
  }
  if (key.startsWith("disk_pct:") && total > 0) {
    const path = key.slice(9),
      free = values["disk_free_bytes:" + path] ?? available,
      occupied = values["disk_used_bytes:" + path] ?? Math.max(0, total - free),
      reserved = Math.max(0, free - available),
      bar = el("div", undefined, "disk-space-bar"),
      legend = el("div", undefined, "disk-space-legend");
    bar.setAttribute("role", "img");
    const parts = [
      [bilingual("Ocupado", "Used"), occupied, "used"],
      [bilingual("Reservado", "Reserved"), reserved, "reserved"],
      [bilingual("Disponible", "Available"), available, "available"],
    ];
    bar.setAttribute(
      "aria-label",
      parts
        .map(([label, amount]) => label + ": " + resourceBytes(amount))
        .join(" · "),
    );
    for (const [label, amount, cls] of parts) {
      if (amount == null || (amount === 0 && cls === "reserved")) continue;
      const segment = el("span", undefined, "disk-space-" + cls);
      segment.style.width =
        Math.max(0, Math.min(100, (amount * 100) / total)) + "%";
      segment.title = label + ": " + resourceBytes(amount);
      bar.append(segment);
      legend.append(
        el("span", label + ": " + resourceBytes(amount), "disk-label-" + cls),
      );
    }
    card.append(bar, legend);
    const disk = data.latest?.disks?.find((d) => d.mount === path);
    if (disk)
      card.append(
        el(
          "p",
          [disk.device, disk.filesystem].filter(Boolean).join(" · "),
          "subtle",
        ),
      );
    card.append(
      el(
        "p",
        bilingual(
          "El porcentaje incluye el espacio reservado no disponible para este usuario.",
          "The percentage includes reserved space unavailable to this user.",
        ),
        "subtle",
      ),
    );
    if (data.config.mode === "local")
      card.append(
        button(bilingual("Más información del disco", "More disk info"), () =>
          openDiskInfo(data.machine_id, path),
        ),
      );
  }
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
  const rows = history.rows
    .filter(
      (r) =>
        r.key === key &&
        Number.isFinite(r.observed) &&
        r.observed >= history.start &&
        r.observed <= history.end &&
        Number.isFinite(r.average) &&
        Number.isFinite(r.maximum),
    )
    .sort((a, b) => a.observed - b.observed);
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
    70 + (440 * (stamp - history.start)) / (history.end - history.start);
  const percent = key.split(":")[0].endsWith("_pct"),
    peak = Math.max(1, ...rows.map((r) => r.maximum)),
    scale = percent
      ? 100
      : Math.ceil(peak / 10 ** Math.floor(Math.log10(peak))) *
        10 ** Math.floor(Math.log10(peak));
  const y = (value) =>
    145 - (130 * Math.max(0, Math.min(scale, value))) / scale;
  for (const value of [0, scale / 2, scale]) {
    node("line", {
      x1: 70,
      x2: 510,
      y1: y(value),
      y2: y(value),
      class: "resource-gridline",
    });
    node(
      "text",
      { x: 64, y: y(value) + 4, "text-anchor": "end", class: "resource-axis" },
      metricValue(key, value),
    );
  }
  const timeLabel = (at) =>
    new Date(at * 1000).toLocaleTimeString(
      locale === "es" ? "es-ES" : "en-GB",
      { hour: "2-digit", minute: "2-digit" },
    );
  node(
    "text",
    { x: 70, y: 170, class: "resource-axis" },
    timeLabel(history.start),
  );
  node(
    "text",
    { x: 510, y: 170, "text-anchor": "end", class: "resource-axis" },
    timeLabel(history.end),
  );
  node(
    "text",
    { x: 290, y: 170, "text-anchor": "middle", class: "resource-axis" },
    timeLabel((history.start + history.end) / 2),
  );
  if (threshold != null)
    node("line", {
      x1: 70,
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
      const dot = node("circle", {
        cx: x(row.observed),
        cy: y(row[type]),
        r: 2,
        class: "metric-" + type,
      });
      const tip = document.createElementNS(ns, "title");
      tip.textContent =
        stamp(row.observed) + " · " + metricValue(key, row[type]);
      dot.append(tip);
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
  if (!rows.length)
    card.append(
      el(
        "p",
        bilingual(
          "Sin muestras en este periodo.",
          "No samples in this period.",
        ),
        "subtle",
      ),
    );
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
    const cursor = node("line", {
      x1: 70,
      x2: 40,
      y1: 15,
      y2: 145,
      class: "resource-cursor",
    });
    const show = (index) => {
      const row = rows[index];
      cursor.setAttribute("x1", x(row.observed));
      cursor.setAttribute("x2", x(row.observed));
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
          ((((e.clientX - box.left) / box.width) * 520 - 70) / 440) *
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

function cpuThreadPanel(data) {
  const box = el("div"),
    grid = el("div", undefined, "cpu-thread-grid"),
    values = data.latest?.values || {},
    keys = Object.keys(values)
      .filter((k) => k.startsWith("cpu_thread_pct:"))
      .sort((a, b) => Number(a.split(":")[1]) - Number(b.split(":")[1]));
  for (const key of keys) {
    const tile = el("div", undefined, "cpu-thread"),
      percent = values[key],
      meter = el("div", undefined, "resource-meter"),
      fill = el("span");
    tile.append(
      el("span", metricName(key)),
      el("strong", metricValue(key, percent)),
    );
    fill.style.width = Math.max(0, Math.min(100, percent)) + "%";
    meter.append(fill);
    meter.setAttribute("role", "meter");
    meter.setAttribute("aria-label", metricName(key));
    meter.setAttribute("aria-valuemin", "0");
    meter.setAttribute("aria-valuemax", "100");
    meter.setAttribute("aria-valuenow", percent.toFixed(1));
    tile.append(meter);
    grid.append(tile);
  }
  box.append(
    grid,
    el(
      "p",
      keys.length
        ? bilingual(
            "Uso por CPU lógica entre dos muestras; cada hilo tiene su propia escala de 0 a 100 %.",
            "Usage per logical CPU between two samples; each thread has its own 0–100% scale.",
          )
        : bilingual(
            "Se necesitan dos muestras del emisor actualizado para mostrar cada hilo.",
            "Two samples from an updated sender are needed to show individual threads.",
          ),
      "subtle",
    ),
  );
  const details = disclosure(
    bilingual("CPU por hilos", "CPU threads") +
      " · " +
      (values.cpu_count ?? "—"),
    box,
  );
  details.open = keys.length > 0 && keys.length <= 64;
  return details;
}

function openDiskInfo(machineId, path) {
  const box = el("div"),
    status = el("p"),
    results = el("div");
  const start = button(
    bilingual("Calcular carpetas más grandes", "Calculate largest folders"),
    async () => {
      start.disabled = true;
      start.hidden = true;
      try {
        const job = await api("/api/telemetry/" + machineId + "/disk-info", {
          path,
        });
        await update(job);
      } catch (e) {
        status.textContent = e.message;
        start.disabled = false;
        start.hidden = false;
      }
    },
  );
  box.append(
    el("p", path),
    el(
      "p",
      bilingual(
        "Consulta opcional de hasta 15 segundos, sin LLM. Lee tamaños con los permisos del portal, sin seguir enlaces ni cruzar a otros sistemas de archivos. Puede generar actividad de disco. Solo disponible en el equipo del portal.",
        "Optional inspection of up to 15 seconds, without an LLM. Reads sizes with portal permissions, without following links or crossing filesystems. May generate disk activity. Available only on the portal host.",
      ),
      "subtle",
    ),
    start,
    status,
    results,
  );
  modal(bilingual("Carpetas que más ocupan", "Largest folders"), box);
  async function update(job) {
    if (!box.isConnected || !$("#modal").open) return;
    status.textContent =
      job.status === "running"
        ? bilingual(
            "Calculando… límite de 15 segundos.",
            "Calculating… 15-second limit.",
          )
        : (job.partial
            ? bilingual("Resultado parcial", "Partial result")
            : bilingual("Consulta completada", "Inspection completed")) +
          " · " +
          stamp(job.finished);
    const reasons = {
      time_limit: bilingual(
        "Se alcanzó el límite de tiempo; pueden faltar carpetas grandes.",
        "Time limit reached; large folders may be missing.",
      ),
      output_limit: bilingual(
        "Se alcanzó el límite de resultados.",
        "Output limit reached.",
      ),
      unreadable: bilingual(
        "Algunas rutas no son accesibles o cambiaron durante la consulta.",
        "Some paths are inaccessible or changed during inspection.",
      ),
      du_unavailable: bilingual(
        "La herramienta du no está instalada.",
        "The du utility is not installed.",
      ),
      interrupted: bilingual(
        "Consulta interrumpida. Puedes repetirla.",
        "Inspection interrupted. You can run it again.",
      ),
    };
    results.replaceChildren();
    if (job.reason) results.append(el("p", reasons[job.reason] || job.reason));
    if (job.total_bytes != null)
      results.append(
        el(
          "p",
          bilingual("Total accesible: ", "Accessible total: ") +
            resourceBytes(job.total_bytes),
        ),
      );
    if (job.folders.length)
      results.append(
        table(
          [
            bilingual("Carpeta", "Folder"),
            bilingual("Espacio en disco", "Disk space"),
          ],
          job.folders.map((r) => [r.path, resourceBytes(r.bytes)]),
        ),
      );
    if (job.status !== "running") {
      start.disabled = false;
      start.hidden = false;
      results.append(
        el(
          "p",
          bilingual(
            "Hasta 30 carpetas del primer nivel. Se mide espacio asignado; archivos sueltos, instantáneas y datos sin permiso pueden explicar diferencias con el gráfico del disco.",
            "Up to 30 top-level folders. Measures allocated space; loose files, snapshots and inaccessible data can explain differences from the disk chart.",
          ),
          "subtle",
        ),
      );
      return;
    }
    setTimeout(async () => {
      if (!box.isConnected || !$("#modal").open) return;
      try {
        await update(
          await api("/api/telemetry/" + machineId + "/disk-info/" + job.id),
        );
      } catch (e) {
        status.textContent = e.message;
        start.disabled = false;
        start.hidden = false;
      }
    }, 1000);
  }
}
