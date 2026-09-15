"use strict";
const $ = (s) => document.querySelector(s),
  el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
let S = {},
  entering = true,
  view = "summary",
  scope = "",
  edit = null,
  offset = 0;
const names = {
  summary: t("Resumen"),
  machine: t("Máquinas"),
  metrics: t("Métricas"),
  health: t("Salud del observador"),
  capacity: t("Cobertura y capacidad"),
  appearance: t("Apariencia"),
  desktop: t("Escritorio"),
  source: t("Fuentes"),
  problems: t("Problemas"),
  events: t("Histórico"),
  destination: t("Notificaciones"),
  rule: t("Reglas"),
  settings: t("Modelo y análisis"),
  chat: t("Asistente"),
  activity: t("Actividad"),
  backup: t("Copias"),
  setup: t("Configuración guiada"),
  about: t("Sobre nosotros"),
};
const channelNames = {
  system: t("Sistema"),
  telegram: "Telegram",
  slack: "Slack",
  discord: "Discord",
  hermes: "Hermes",
  n8n: "n8n",
  webhook: t("Webhook genérico"),
  file: t("Archivo local"),
};
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const stamp = (value) =>
    value
      ? new Date(Number(value) * 1000).toLocaleString(
          locale === "es" ? "es-ES" : "en-GB",
        )
      : "—",
  bytes = (n) =>
    n > 1048576
      ? (n / 1048576).toFixed(1) + " MiB"
      : (n / 1024).toFixed(1) + " KiB";
const machineName = (id) =>
  (S.machine || []).find((m) => m.id === id)?.name || id || "Global";
function notice(text, error = false) {
  $("#notice").hidden = false;
  $("#notice").className = error ? "error" : "";
  $("#notice").textContent = text;
}
async function api(path, body, method) {
  const options = {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: { "X-LogSentinel": "portal" },
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const r = await fetch(path, options);
  if (r.status === 401) {
    $("#login").hidden = false;
    $("#shell").hidden = true;
    throw Error(t("Introduce la clave de acceso"));
  }
  let data = r.headers.get("content-type")?.includes("json")
    ? await r.json()
    : await r.text();
  if (!r.ok) {
    const error = Error(
      t(
        typeof data === "string"
          ? data
          : typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail),
      ),
    );
    error.status = r.status;
    throw error;
  }
  return data;
}
function button(label, fn, cls = "quiet") {
  const b = el("button", label, cls);
  b.type = "button";
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await fn();
    } catch (e) {
      notice(e.message, true);
    } finally {
      b.disabled = false;
    }
  });
  return b;
}
function badge(text) {
  return el("span", statusLabel(text), "badge " + text);
}
function panel(title) {
  const n = el("section", undefined, "panel");
  if (title) n.append(el("h2", title));
  return n;
}
function table(headers, rows) {
  if (!rows.length) {
    const e = el("div", undefined, "empty");
    e.append(
      el("h2", t("Todavía no hay registros")),
      el(
        "p",
        t(
          "Los datos aparecerán aquí cuando configures fuentes y ejecutes el análisis.",
        ),
      ),
    );
    return e;
  }
  const w = el("div", undefined, "table-wrap"),
    tableNode = el("table"),
    h = el("tr");
  headers.forEach((v) => h.append(el("th", v)));
  const head = el("thead");
  head.append(h);
  tableNode.append(head);
  const body = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    row.forEach((v) => {
      const td = el("td");
      td.append(v instanceof Node ? v : el("span", v));
      tr.append(td);
    });
    body.append(tr);
  });
  tableNode.append(body);
  w.append(tableNode);
  return w;
}
function actions(...buttons) {
  const n = el("div", undefined, "actions");
  n.append(...buttons);
  return n;
}
function modal(title, content) {
  const n = $("#modal-content");
  n.replaceChildren(el("h2", title), content);
  $("#modal").showModal();
}
$("#close-modal").onclick = () => $("#modal").close();
function field(name, label, type = "text", value = "", options = []) {
  const wrap = el("label", undefined, type === "checkbox" ? "check" : "");
  const input =
    type === "textarea"
      ? el("textarea")
      : type === "select"
        ? el("select")
        : el("input");
  input.name = name;
  input.setAttribute("aria-label", label);
  if (type === "select") {
    options.forEach(([v, t]) => {
      const o = el("option", t);
      o.value = v;
      o.selected = String(value) === String(v);
      input.append(o);
    });
  } else if (type === "checkbox") {
    input.type = "checkbox";
    input.checked = !!value;
  } else {
    if (type !== "textarea") input.type = type;
    input.value = value ?? "";
  }
  wrap.append(el("span", label), input);
  return wrap;
}
function formData(form) {
  const result = {};
  for (const input of form.elements) {
    if (!input.name) continue;
    result[input.name] =
      input.type === "checkbox"
        ? input.checked
        : input.type === "number"
          ? Number(input.value)
          : input.type === "datetime-local"
            ? input.value
              ? new Date(input.value).getTime() / 1000
              : null
            : input.value;
  }
  return result;
}
async function refresh() {
  S = await api("/api/state");
  if (
    !S.machine.length &&
    !S.setup?.completed &&
    !sessionStorage.getItem("setup-dismissed")
  )
    view = "setup";
  $("#login").hidden = true;
  $("#shell").hidden = false;
  const sel = $("#machine-scope");
  sel.replaceChildren();
  [
    ["", t("Todas las máquinas")],
    ...S.machine.map((m) => [m.id, m.name]),
  ].forEach(([v, t]) => {
    let o = el("option", t);
    o.value = v;
    o.selected = v === scope;
    sel.append(o);
  });
  drawMonitor(S.monitor);
  await render();
}
function navigate(v) {
  // Only a navigation animates the content in. A background refresh rebuilds
  // the same view and must not flash.
  entering = true;
  if (v === "chat") {
    chatProblemId = "";
    chatDraft = "";
  }
  if (view === "setup" && v !== "setup")
    sessionStorage.setItem("setup-dismissed", "1");
  view = v;
  edit = null;
  offset = 0;
  $("#notice").hidden = true;
  render();
}
// Eighteen flat entries made the rail a list to read rather than a place to
// aim at, and it scrolled on a laptop. Grouping puts what you check daily at
// the top and the things you set once further down. `names` still holds every
// label, so page titles are unaffected by this order.
const navGroups = [
  {
    label: ["Observar", "Watch"],
    keys: ["summary", "problems", "events", "metrics", "capacity", "health", "activity"],
  },
  {
    label: ["Configurar", "Configure"],
    keys: ["machine", "source", "destination", "rule", "settings", "setup"],
  },
  {
    label: ["Herramientas", "Tools"],
    keys: ["chat", "backup", "appearance", "desktop", "about"],
  },
];
// The rail is rebuilt when the language changes, so it is built in one place
// and the group headings are translated at build time rather than at load.
function buildNav() {
  const rail = $("#nav");
  rail.replaceChildren();
  for (const group of navGroups) {
    rail.append(el("p", bilingual(group.label[0], group.label[1]), "nav-group"));
    for (const key of group.keys) rail.append(tentriNavButton(key, names[key]));
  }
}
buildNav();
$("#machine-scope").onchange = () => {
  if (view === "chat") {
    chatProblemId = "";
    chatDraft = "";
  }
  scope = $("#machine-scope").value;
  offset = 0;
  drawMonitor(S.monitor);
  render();
};
$("#logout").onclick = async () => {
  await api("/api/logout", {});
  location.reload();
};
$("#login-form").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/login", { token: $("#access-key").value });
    $("#access-key").value = "";
    await refresh();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
};
async function render() {
  const root = el("div");
  if (entering) root.className = "view-enter";
  entering = false;
  $("#content").replaceChildren(root);
  $("#monitor-status").hidden = ["about", "setup"].includes(view);
  $(".scope").hidden = view === "about";
  $("#page-title").textContent =
    view === "problem_detail" ? t("Detalles del problema") : t(names[view]);
  updateTentriSection(view, $("#page-title").textContent);
  // Matched by view rather than by position, so the group headings between the
  // buttons cannot shift which one reads as active.
  $("#nav")
    .querySelectorAll("button[data-view]")
    .forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  if (["machine", "source", "destination", "rule"].includes(view))
    return objectView(root);
  if (view === "summary") return summary(root);
  if (view === "settings") return settingsView(root);
  if (view === "problems") return problemList(root);
  if (view === "problem_detail") return problemPage(root);
  if (view === "metrics") return metricsView(root);
  if (view === "health") return healthView(root);
  if (view === "capacity") return capacityView(root);
  if (view === "appearance") return appearanceView(root);
  if (view === "desktop") return desktopView(root);
  if (view === "events") return eventsView(root);
  if (view === "chat") return chatView(root);
  if (view === "activity") return activity(root);
  if (view === "backup") return backupView(root);
  if (view === "setup") return setupView(root);
  if (view === "about") {
    const profile = el("a", "@THEINAOG · x.com");
    profile.href = "https://x.com/THEINAOG";
    profile.target = "_blank";
    profile.rel = "noopener noreferrer";
    const repository = el("a", "ianmove/LogSentinel · GitHub");
    repository.href = "https://github.com/IAnMove/LogSentinel";
    repository.target = "_blank";
    repository.rel = "noopener noreferrer";
    root.append(actions(profile, repository));
  }
}
async function summary(root) {
  const stats = scope
      ? await api("/api/stats?machine_id=" + encodeURIComponent(scope))
      : S.stats,
    c = stats.coverage,
    all = Object.values(c).reduce((a, b) => a + b, 0),
    cards = el("div", undefined, "cards");
  [
    [t("Eventos retenidos"), all, t("Originales recuperables")],
    [
      t("Problemas abiertos"),
      stats.open_problems || 0,
      t("Basados en evidencia"),
    ],
    [
      t("Sin revisar por capacidad"),
      c.capacity || 0,
      bilingual("Total histórico retenido", "Retained historical total"),
    ],
    [
      t("Tokens reportados"),
      (stats.usage.input_tokens || 0) + (stats.usage.output_tokens || 0),
      (stats.usage.unknown_calls || 0) + t(" llamadas con uso desconocido"),
    ],
  ].forEach(([title, value, sub]) => {
    const p = el("section", undefined, "card");
    p.append(
      el("div", title, "caption"),
      el("div", String(value), "metric"),
      el("div", sub, "caption"),
    );
    cards.append(p);
  });
  root.append(cards);
  const coverage = el("div");
  root.append(coverage);
  mountCapacitySummary(coverage, scope).catch((error) =>
    notice(error.message, true),
  );
  if (S.machine.length) {
    const resources = el("section", undefined, "resource-overview");
    root.append(resources);
    mountResourceOverview(resources, scope);
  }
  const status = panel(t("Estado del observatorio"));
  status.append(
    el(
      "p",
      t(
        "La captura y el análisis funcionan aunque cierres el navegador. Consulta arriba la próxima ejecución y el estado real de las fuentes.",
      ),
    ),
  );
  if (S.worker_error) status.append(el("p", S.worker_error));
  status.append(
    actions(
      button(
        t("Analizar ahora"),
        async () => {
          notice(t("Analizando los eventos admitidos por el presupuesto…"));
          const r = await api("/api/scan", {});
          await refresh();
          notice(
            t("Ciclo terminado: ") +
              r.calls +
              t(" llamadas. Consulta cobertura y actividad."),
          );
        },
        "",
      ),
      button(
        t("Probar conexión del LLM"),
        async () => {
          notice(t("Probando el LLM con una petición sintética…"));
          const result = await api("/api/model/test", {});
          const tokens =
            result.input_tokens == null || result.output_tokens == null
              ? t("tokens no reportados")
              : `${result.input_tokens + result.output_tokens} tokens`;
          notice(
            t("LLM conectado: {model} · {seconds} s · {tokens}.", {
              model: result.model,
              seconds: Number(result.seconds).toFixed(1),
              tokens,
            }),
          );
        },
        "",
      ),
      button(t("Detectar fuentes locales"), discover),
      button(t("Configuración guiada"), () => navigate("setup")),
    ),
  );
  root.append(status);
  const p = panel(t("Almacenamiento y cobertura"));
  p.append(
    el(
      "p",
      bytes(stats.disk_bytes) +
        t(" en disco · ") +
        bytes(stats.segments.original) +
        t(" en bloques lógicos · ") +
        bytes(stats.segments.compressed) +
        t(" comprimidos"),
    ),
    table(
      [t("Estado de eventos"), t("Cantidad")],
      Object.entries(c).map(([key, value]) => [coverageLabel(key), value]),
    ),
  );
  p.append(
    el("h3", t("Uso por fuente")),
    el(
      "p",
      t(
        "Tokens repartidos proporcionalmente al tamaño del contexto enviado; son una atribución estimada, no mediciones separadas del proveedor.",
      ),
      "subtle",
    ),
    table(
      [
        t("Fuente"),
        t("Eventos recibidos"),
        t("Volumen original"),
        t("Tokens atribuidos"),
        t("Llamadas sin uso completo"),
      ],
      (stats.sources || []).map((s) => [
        s.name,
        s.events_ingested,
        bytes(s.logical_bytes),
        Math.round(s.allocated_tokens),
        s.unknown_calls,
      ]),
    ),
  );
  root.append(p);
  if (!S.machine.length) {
    const n = panel(t("Empieza con este equipo"));
    n.append(
      el(
        "p",
        t(
          "Detecta el sistema y crea su ficha. También puedes añadir una máquina cuyos logs se reciben en una carpeta.",
        ),
      ),
      button(t("Detectar este equipo"), discover, ""),
    );
    root.append(n);
  }
  problemList(root, true);
}
async function discover() {
  const d = await api("/api/discovery");
  view = "machine";
  edit = {
    name: d.hostname,
    hostname: d.hostname,
    os: d.os,
    kind: "local",
    timezone: "UTC",
  };
  await render();
  notice(
    t("Detectado: ") +
      d.os +
      ". Journal: " +
      (d.journalctl ? t("disponible") : t("ausente")) +
      t(". Archivos: ") +
      d.files
        .map((f) => f.path + (f.readable ? "" : t(" (sin permiso)")))
        .join(", "),
  );
}
function objectView(root) {
  const kind = view,
    items = (S[kind] || []).filter(
      (x) =>
        !scope ||
        (kind === "machine" && x.id === scope) ||
        (kind !== "machine" && (!x.machine_id || x.machine_id === scope)),
    );
  const bar = el("div", undefined, "toolbar");
  bar.append(
    el(
      "p",
      {
        machine: t("Identidad y contexto de cada equipo."),
        source: t("Archivos, carpetas, journal y recepción continua."),
        destination: t(
          "Avisos directos y servicios externos. Guardar no envía mensajes.",
        ),
        rule: t(
          "No notificar mantiene el análisis. Excluir evita enviar esas coincidencias al modelo. Los presets de ruido se previsualizan y se aplican a mano.",
        ),
      }[kind],
    ),
    button(
      t("Añadir"),
      () => {
        edit = {};
        render();
      },
      "",
    ),
  );
  root.append(bar);
  if (kind === "rule") root.append(rulePresetPanel());
  root.append(
    table(
      kind === "machine"
        ? [t("Nombre"), t("Sistema"), t("Tipo"), t("Estado"), t("Acciones")]
        : [t("Nombre"), t("Máquina"), t("Tipo"), t("Estado"), t("Acciones")],
      items.map((obj) => {
        const b = [
          button(t("Editar"), () => {
            edit = obj;
            render();
          }),
        ];
        if (kind === "machine") {
          if (obj.deletion_pending) b.length = 0;
          b.push(...machineActions(obj));
        }
        if (
          kind === "machine" ||
          (kind === "source" && obj.kind === "metrics")
        ) {
          if (kind === "source") b.length = 0;
          b.push(
            button(t("Métricas"), () => {
              scope = kind === "machine" ? obj.id : obj.machine_id;
              $("#machine-scope").value = scope;
              navigate("metrics");
            }),
          );
        }
        if (kind === "source" && obj.kind === "health") {
          b.length = 0;
          b.push(button(t("Salud del observador"), () => navigate("health")));
        }
        if (kind === "source" && !["metrics", "health"].includes(obj.kind)) {
          b.push(
            button(t("Leer ahora"), async () => {
              const r = await api("/api/source/" + obj.id + "/poll", {});
              await refresh();
              notice(
                r.events + t(" eventos nuevos. ") + (r.health.error || ""),
              );
            }),
          );
          if (obj.kind === "push")
            b.push(
              button(t("Clave de emisor"), async () => {
                const r = await api("/api/sources/" + obj.id + "/token", {});
                const p = el("pre", JSON.stringify(r, null, 2));
                modal(t("Guarda esta clave: se muestra una vez"), p);
              }),
            );
          b.push(
            button(bilingual("Recuperar retenidos sin analizar", "Recover unreviewed retained logs"), async () => {
              const r = await api("/api/reanalyze", { source_id: obj.id });
              notice(
                r.scheduled +
                  bilingual(" logs añadidos a la cola. Se procesarán por lotes; los ya analizados conservan su estado.", " logs added to the queue. They will run in batches; previously reviewed logs keep their status."),
              );
            }),
          );
        }
        if (kind === "destination")
          b.push(
            button(t("Enviar prueba"), async () => {
              const r = await api("/api/destinations/" + obj.id + "/test", {});
              await refresh();
              notice(
                r.status + (r.error ? ": " + r.error : ""),
                r.status === "failed",
              );
            }),
          );
        if (["destination", "rule"].includes(kind))
          b.push(
            button(
              t("Eliminar"),
              async () => {
                if (confirm(t("¿Eliminar esta configuración?"))) {
                  await api(
                    "/api/objects/" + kind + "/" + obj.id,
                    undefined,
                    "DELETE",
                  );
                  await refresh();
                }
              },
              "danger",
            ),
          );
        return kind === "machine"
          ? [
              obj.name,
              obj.os || t("Sin especificar"),
              obj.kind,
              machineMonitoringState(obj),
              actions(...b),
            ]
          : [
              obj.name,
              machineName(obj.machine_id),
              channelNames[obj.kind] ? t(channelNames[obj.kind]) : obj.kind,
              el(
                "span",
                (obj.machine_id &&
                S.machine.find((m) => m.id === obj.machine_id)
                  ?.monitoring_paused
                  ? bilingual("Máquina pausada", "Machine paused")
                  : obj.enabled
                    ? t("Activo")
                    : t("Pausado")) +
                  (S.health[obj.id]?.error
                    ? " · " + S.health[obj.id].error
                    : "") + senderHealthSummary(S.health[obj.id]),
              ),
              actions(...b),
            ];
      }),
    ),
  );
  if (edit !== null) root.append(objectForm(kind, edit));
}
function senderHealthSummary(health) {
  if (!health || health.sender_pending === undefined) return "";
  const sender = health.sender || {};
  const labels = {
    machine_paused: ["Captura pausada por el central", "Capture paused by receiver"],
    source_disabled: ["Fuente desactivada", "Source disabled"],
    queue_high_water: ["Captura frenada: cola saturada", "Capture held: queue high water"],
    queue_full: ["Cola sin capacidad", "Queue capacity reached"],
    disk_io_pressure: ["Pausa para proteger el disco", "Paused to protect disk I/O"],
    disk_free_reserve: ["Pausa por espacio libre insuficiente", "Paused: low free disk space"],
    journal_retention_gap: ["Hueco de cobertura: cursor del journal no disponible", "Coverage gap: journal cursor unavailable"],
    control_unavailable: ["Sin autorización reciente del receptor", "Receiver control lease unavailable"],
  };
  const code = sender.capture_code || sender.delivery_code;
  const label = labels[code];
  let text = " · " + bilingual("Cola del cliente: ", "Client queue: ") + health.sender_pending;
  if (sender.quota_bytes)
    text += " · " + Math.round(sender.used_bytes / 1048576) + "/" + Math.round(sender.quota_bytes / 1048576) + " MiB";
  if (code) text += " · " + (label ? bilingual(...label) : code);
  if (sender.build) text += " · v" + sender.build;
  if (health.heartbeat) text += " · " + bilingual("Último estado: ", "Last status: ") + stamp(health.heartbeat);
  return text;
}
function objectForm(kind, o) {
  const p = panel(o.id ? t("Editar configuración") : t("Nueva configuración")),
    f = el("form", undefined, "form-grid");
  const add = (...a) => f.append(field(...a));
  add("name", t("Nombre"), "text", o.name);
  const machines = [
    ["", t("Seleccionar máquina")],
    ...S.machine.map((m) => [m.id, m.name]),
  ];
  if (kind === "machine") {
    add("kind", t("Tipo"), "select", o.kind || "imported", [
      ["local", t("Este equipo")],
      ["imported", t("Otro equipo")],
    ]);
    add("hostname", t("Hostname declarado"), "text", o.hostname);
    add("os", t("Sistema / distribución"), "text", o.os);
    add("timezone", t("Zona horaria IANA"), "text", o.timezone || "UTC");
    add("notes", t("Contexto de la máquina"), "textarea", o.notes);
  }
  if (kind === "source") {
    add("machine_id", t("Máquina"), "select", o.machine_id || scope, machines);
    add("kind", t("Tipo de fuente"), "select", o.kind || "file", [
      ["file", t("Archivo")],
      ["folder", t("Carpeta")],
      ["journald", t("Journal local")],
      ["push", t("Recepción remota")],
    ]);
    add("path", t("Ruta (archivo o carpeta)"), "text", o.path);
    add(
      "pattern",
      t("Patrón de archivos en carpeta"),
      "text",
      o.pattern || "*.log*",
    );
    add("history", t("Importar histórico al iniciar"), "checkbox", o.history);
    add(
      "heartbeat_timeout_seconds",
      t("Plazo sin señal del emisor remoto (segundos, 0 desactiva)"),
      "number",
      o.heartbeat_timeout_seconds ?? 0,
    );
    add(
      "multiline",
      t("Agrupar continuaciones con sangría"),
      "checkbox",
      o.multiline,
    );
    add(
      "ssh_rejection_notify_seconds",
      bilingual("Intervalo compartido para avisos de rechazos SSH (segundos; 0 desactiva)", "Shared interval for SSH rejection notifications (seconds; 0 disables)"),
      "number",
      o.ssh_rejection_notify_seconds ?? 0,
    );
    f.append(el("p", bilingual(
      "Por fuente y destino, aunque cambien la IP, el usuario o el problema. Conserva los logs y el análisis; permite aumentos de gravedad y otros mensajes SSH. No implica que fail2ban haya bloqueado al origen.",
      "Per source and destination, even when IP, user or problem changes. Keeps logs and analysis; allows severity increases and other SSH messages. Does not imply a fail2ban block."
    ), "wide subtle"));
    add(
      "max_batch_bytes",
      t("Máximo de bytes por lote de lectura"),
      "number",
      o.max_batch_bytes ?? 2000000,
    );
    add(
      "analysis_mode",
      t("Selección para el análisis LLM"),
      "select",
      o.analysis_mode || "all",
      [
        ["all", t("Todas las líneas")],
        ["priority", t("Prioridad + palabras")],
        ["keywords", t("Solo palabras disparadoras")],
        ["adaptive", t("Adaptativa: prioridad + contexto")],
      ],
    );
    add(
      "priority_ceiling",
      t("Prioridad máxima (0 emergente · 7 debug)"),
      "number",
      o.priority_ceiling ?? 4,
    );
    add(
      "context_minutes",
      t("Contexto antes/después (minutos)"),
      "number",
      o.context_minutes ?? 5,
    );
    add(
      "trigger_terms",
      t("Palabras disparadoras, una por línea (ignora mayúsculas)"),
      "textarea",
      o.trigger_terms ?? S.defaults.source.trigger_terms,
    );
    f.append(
      el(
        "p",
        t(
          "Los originales se conservan hasta que caducan por retención o cuota. La prioridad es declarada por el emisor, no garantiza seguridad. El contexto usa eventos ya capturados, puede recortarse y no se amplía automáticamente con llegadas futuras.",
        ),
        "wide subtle",
      ),
    );
    add("enabled", t("Captura activa"), "checkbox", o.enabled);
  }
  if (kind === "destination") {
    add(
      "kind",
      t("Canal"),
      "select",
      o.kind || "telegram",
      Object.entries(channelNames).map(([key, label]) => [key, t(label)]),
    );
    addNotificationConfiguration(f, o);
    add("machine_id", t("Ámbito de máquina"), "select", o.machine_id || "", [
      ["", t("Todas")],
      ...machines.slice(1),
    ]);
    add("source_id", t("Ámbito de fuente"), "select", o.source_id || "", [
      ["", t("Todas")],
      ...S.source.map((x) => [x.id, x.name]),
    ]);
    add(
      "min_severity",
      t("Gravedad mínima"),
      "select",
      o.min_severity || "MEDIUM",
      ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((x) => [x, x]),
    );
    add(
      "cooldown_seconds",
      t("Agrupar avisos durante (segundos)"),
      "number",
      o.cooldown_seconds ?? 300,
    );
    add("enabled", t("Destino activo"), "checkbox", o.enabled);
  }
  if (kind === "rule") {
    add("machine_id", t("Máquina"), "select", o.machine_id || scope, [
      ["", t("Todas")],
      ...machines.slice(1),
    ]);
    add("source_id", t("Fuente"), "select", o.source_id || "", [
      ["", t("Todas")],
      ...S.source.map((x) => [x.id, x.name]),
    ]);
    add("action", t("Acción"), "select", o.action || "mute", [
      ["mute", t("No notificar")],
      ["exclude", t("Excluir del análisis")],
    ]);
    add("kind", t("Coincidencia"), "select", o.kind || "regex", [
      ["regex", t("Expresión regular")],
      ["ip", t("IP exacta / CIDR")],
      ["service", t("Servicio / unidad")],
      ["problem", t("ID de problema")],
    ]);
    add("pattern", t("Expresión / IP / ID"), "textarea", o.pattern);
    add("enabled", t("Regla activa"), "checkbox", o.enabled ?? true);
    add(
      "expires_at",
      t("Caducidad opcional (hora local)"),
      "datetime-local",
      o.expires_at
        ? new Date(o.expires_at * 1000 - new Date().getTimezoneOffset() * 60000)
            .toISOString()
            .slice(0, 16)
        : "",
    );
    f.append(
      button(t("Vista previa de coincidencias"), async () => {
        const data = formData(f);
        const r = await api("/api/rules/preview", data);
        modal(
          t("Vista previa · muestra de ") +
            r.tested +
            t(" eventos, ") +
            r.matched +
            t(" coincidencias"),
          el("pre", JSON.stringify(r, null, 2)),
        );
      }),
    );
  }
  const tools = el("div", undefined, "toolbar wide"),
    submit = el("button", t("Guardar"));
  submit.type = "submit";
  tools.append(
    submit,
    button(t("Cancelar"), () => {
      edit = null;
      render();
    }),
  );
  f.append(tools);
  f.onsubmit = async (ev) => {
    ev.preventDefault();
    submit.disabled = true;
    try {
      const data =
        kind === "destination" ? notificationFormData(f) : formData(f);
      if (o.id) data.id = o.id;
      const saved = await api("/api/objects/" + kind, data);
      edit = null;
      await refresh();
      notice(
        saved.warning
          ? t("Configuración guardada. ") + t(saved.warning)
          : t("Configuración guardada."),
      );
    } catch (e) {
      notice(e.message, true);
    } finally {
      submit.disabled = false;
    }
  };
  p.append(f);
  return p;
}
async function showTemplate(kind) {
  const result = await api("/api/templates/" + kind);
  const p = el("div");
  p.append(
    el(
      "p",
      t(
        "Plantilla para configurar tu servicio externo. Sustituye credenciales y destino; la aplicación no lo activa automáticamente.",
      ),
    ),
    el("pre", JSON.stringify(result, null, 2)),
    button(t("Copiar JSON"), () =>
      navigator.clipboard.writeText(JSON.stringify(result, null, 2)),
    ),
  );
  modal(t("Plantilla ") + kind, p);
}
function settingsView(root) {
  const c = S.settings,
    p = panel(t("Proveedor, capacidad y política de revisión")),
    f = el("form", undefined, "form-grid");
  const add = (...a) => f.append(field(...a));
  llmServerFields(f, c);
  add(
    "context_tokens",
    t("Contexto efectivo configurado"),
    "number",
    c.context_tokens,
  );
  add(
    "input_budget",
    t("Presupuesto de entrada (cota conservadora)"),
    "number",
    c.input_budget,
  );
  add("max_tokens", t("Máximo de salida"), "number", c.llm.max_tokens);
  add(
    "timeout_seconds",
    t("Tiempo de espera del LLM (segundos)"),
    "number",
    c.llm.timeout_seconds,
  );
  add(
    "enable_thinking",
    t("Activar razonamiento prolongado del modelo"),
    "select",
    c.llm.enable_thinking == null ? "auto" : String(c.llm.enable_thinking),
    [
      ["auto", t("Predeterminado del proveedor")],
      [
        "false",
        bilingual(
          "Desactivar (Ollama / llama.cpp / vLLM compatibles)",
          "Disable (compatible Ollama / llama.cpp / vLLM)",
        ),
      ],
      ["true", t("Activar (servidor compatible)")],
    ],
  );
  add("max_calls", t("Máximo de llamadas por ciclo"), "number", c.max_calls);
  add(
    "adaptive_batching",
    bilingual(
      "Ajustar lotes y espera al tiempo medido",
      "Adapt batches and waiting to measured time",
    ),
    "checkbox",
    c.adaptive_batching,
  );
  add(
    "target_batch_seconds",
    bilingual("Objetivo por llamada (segundos)", "Target per call (seconds)"),
    "number",
    c.target_batch_seconds,
  );
  add(
    "cycle_budget_seconds",
    bilingual(
      "Tiempo para despachar llamadas por ciclo (segundos)",
      "Call dispatch window per cycle (seconds)",
    ),
    "number",
    c.cycle_budget_seconds,
  );
  add(
    "triage_thinking",
    bilingual(
      "Razonamiento prolongado en la primera revisión",
      "Extended thinking in the first review",
    ),
    "checkbox",
    c.triage_thinking,
  );
  add(
    "verification",
    bilingual(
      "Verificar candidatos con originales",
      "Verify candidates against originals",
    ),
    "select",
    c.verification,
    [
      [
        "important",
        bilingual(
          "Lotes con alertas altas o críticas",
          "Batches with high or critical alerts",
        ),
      ],
      ["all", bilingual("Todos los candidatos", "All candidates")],
      ["manual", bilingual("Solo bajo petición", "Only on request")],
    ],
  );
  add(
    "interval_seconds",
    bilingual(
      "Espera máxima entre ciclos (segundos)",
      "Maximum wait between cycles (seconds)",
    ),
    "number",
    c.interval_seconds,
  );
  add(
    "max_events",
    bilingual(
      "Originales candidatos por lote",
      "Candidate originals per batch",
    ),
    "number",
    c.max_events,
  );
  add("sensitivity", t("Sensibilidad"), "select", c.sensitivity, [
    ["light", t("Ligera")],
    ["balanced", t("Equilibrada")],
    ["thorough", t("Exhaustiva")],
  ]);
  add(
    "retention_days",
    t("Retención de originales (días)"),
    "number",
    c.retention_days,
  );
  add(
    "disk_limit_mb",
    t("Cuota de almacenamiento (MiB)"),
    "number",
    c.disk_limit_mb,
  );
  add("sender_mb_per_hour", bilingual("MiB por fuente y hora", "MiB per source per hour"), "number", c.sender_mb_per_hour);
  add("sender_events_per_hour", bilingual("Eventos por fuente y hora", "Events per source per hour"), "number", c.sender_events_per_hour);
  add(
    "remote_allowed",
    t("Autorizar enviar contexto al servidor remoto configurado"),
    "checkbox",
    c.remote_allowed,
  );
  add("enabled", t("Análisis periódico activo"), "checkbox", c.enabled);
  add("language", t("Idioma de nuevos hallazgos"), "select", c.language, [
    ["en", "English"],
    ["es", "Español"],
  ]);
  f.append(
    button(t("Consultar modelos y presupuesto"), async () => {
      const r = await api("/api/model/info", llmFormSettings(f, c)),
        box = el("div");
      box.append(
        el("p", t("Modelo") + ": " + r.model + " · " + r.base_url),
        el(
          "p",
          t("Máximo declarado: ") +
            (r.reported_maximum ?? t("desconocido")) +
            t(" · Contexto cargado: ") +
            (r.running_context ?? t("desconocido")),
        ),
        el("p", t("Modelos disponibles: ") + r.models.join(", ")),
        el("p", t(r.note)),
      );
      if (r.suggested_input_budget >= 512)
        box.append(
          button(t("Usar presupuesto sugerido en el formulario"), () => {
            f.elements.namedItem("context_tokens").value = r.suggested_context;
            f.elements.namedItem("input_budget").value =
              r.suggested_input_budget;
            f.elements.namedItem("context_tokens").closest("details").open =
              true;
            f.elements
              .namedItem("input_budget")
              .dispatchEvent(new Event("input", { bubbles: true }));
            $("#modal").close();
            notice(t("Revisa y guarda los ajustes para aplicarlos."));
          }),
        );
      modal(t("Capacidad del modelo"), box);
    }),
  );
  fieldHelp(
    f,
    "input_budget",
    bilingual(
      "Limita el texto de cada lote, medido en bytes, no el número de logs. La compactación puede representar muchos originales con poco texto.",
      "Limits each batch’s text in bytes, not the number of logs. Compaction can represent many originals with little text.",
    ),
  );
  fieldHelp(
    f,
    "context_tokens",
    bilingual(
      "Debe coincidir con el contexto cargado en el servidor. Consulta el modelo antes de ampliarlo; este número no identifica tu GPU.",
      "Must match the context loaded on the server. Query the model before increasing it; this number does not identify your GPU.",
    ),
  );
  fieldHelp(
    f,
    "interval_seconds",
    bilingual(
      "Reducirlo ayuda si el modelo acaba y queda esperando. Si está ocupado, primero revisa sus tiempos en Cobertura y capacidad.",
      "Reducing this helps when the model finishes and then waits. If busy, first check its timings in Coverage and capacity.",
    ),
  );
  fieldHelp(
    f,
    "timeout_seconds",
    bilingual(
      "Es cuánto esperamos una respuesta, no cuánto tardará. Aumentarlo evita algunos timeouts, pero no acelera el modelo.",
      "How long to wait for a response, not how long it will take. Increasing it can avoid some timeouts but does not speed up the model.",
    ),
  );
  const connection = guideFields(
    f,
    bilingual("Cambiar conexión o modelo", "Change connection or model"),
    [
      "server_type",
      "provider",
      "base_url",
      "model",
      "api_key",
      "clear_api_key",
      "remote_allowed",
    ],
  );
  for (const node of [
    ...f.querySelectorAll(".provider-help,.provider-tools,.provider-result"),
  ])
    connection.append(node);
  guideFields(
    f,
    bilingual("Límites y tiempos avanzados", "Advanced limits and timing"),
    [
      "context_tokens",
      "input_budget",
      "max_tokens",
      "max_events",
      "max_calls",
      "target_batch_seconds",
      "cycle_budget_seconds",
      "timeout_seconds",
      "triage_thinking",
      "enable_thinking",
      "sensitivity",
    ],
  );
  guideFields(
    f,
    bilingual("Cuánto histórico guardar", "How much history to keep"),
    ["retention_days", "disk_limit_mb"],
  );
  const senderLimits = guideFields(
    f,
    bilingual("Límites de recepción remota", "Remote reception limits"),
    ["sender_mb_per_hour", "sender_events_per_hour"],
  );
  senderLimits.append(el("p", bilingual(
    "Cada fuente tiene su propio contador; estos límites se aplican a todas las fuentes remotas. Si se agotan, el emisor conserva el lote y espera. La cuota de disco del central sigue siendo compartida.",
    "Each source has its own counter; these limits apply to all remote sources. When exhausted, the sender retains its batch and waits. The central disk quota is still shared.",
  ), "field-help"));
  const submit = el("button", t("Guardar ajustes"));
  const savedDraft = JSON.stringify(formData(f)),
    savedConnection = JSON.stringify(llmFormSettings(f, c).llm),
    draftNotice = el("p", "", "wide");
  draftNotice.setAttribute("role", "status");
  f.refreshSettingsDraft = () => {
    draftNotice.textContent =
      JSON.stringify(formData(f)) === savedDraft
        ? ""
        : bilingual(
            "Hay cambios en el formulario sin guardar.",
            "The form contains unsaved changes.",
          );
  };
  f.addEventListener("input", f.refreshSettingsDraft);
  f.addEventListener("change", f.refreshSettingsDraft);
  submit.type = "submit";
  f.append(draftNotice, submit);
  f.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const d = formData(f);
      Object.assign(d, llmFormSettings(f, c));
      if (JSON.stringify(d.llm) === savedConnection) delete d.llm;
      [
        "provider",
        "server_type",
        "base_url",
        "model",
        "api_key",
        "max_tokens",
        "timeout_seconds",
        "enable_thinking",
      ].forEach((k) => delete d[k]);
      await api("/api/settings", d);
      await refresh();
      notice(t("Ajustes aplicados."));
    } catch (err) {
      notice(err.message, true);
    }
  };
  p.append(
    el(
      "p",
      bilingual("Conexión activa: ", "Active connection: ") +
        c.llm.base_url +
        " · " +
        c.llm.model,
      "provider-active",
    ),
    el(
      "p",
      bilingual(
        "Guarda un cambio y comprueba varios lotes completos en Cobertura y capacidad. Allí verás si mejora la espera o solo cambia el tamaño de entrada. Los límites avanzados quedan abajo.",
        "Save one change and check several completed batches in Coverage and capacity. There you can see whether waiting improves or only input size changes. Advanced limits are below.",
      ),
    ),
    f,
  );
  root.append(
    analysisProfiles(f, c),
    p,
    actions(
      button(
        bilingual(
          "Comprobar rendimiento y cola",
          "Check performance and queue",
        ),
        () => openCapacity(scope),
      ),
    ),
  );
}
async function problemList(root, short = false) {
  const rows = short
    ? S.problems.filter((p) => !scope || p.machine_id === scope)
    : await api(
        "/api/problems?machine_id=" +
          encodeURIComponent(scope) +
          "&offset=" +
          offset,
      );
  if (!short)
    root.append(
      actions(
        button(t("Anterior"), () => {
          offset = Math.max(0, offset - 100);
          render();
        }),
        button(t("Siguiente"), () => {
          offset += 100;
          render();
        }),
      ),
    );
  if (short) root.append(el("h2", t("Problemas recientes")));
  root.append(
    table(
      [
        t("Gravedad"),
        t("Problema"),
        t("Máquina"),
        t("Eventos de evidencia"),
        t("Estado"),
        "",
      ],
      rows.slice(0, short ? 5 : 100).map((p) => [
        badge(p.severity),
        p.title,
        machineName(p.machine_id),
        p.count,
        badge(p.status),
        actions(
          button(t("Ver evidencia"), () => problemDetail(p.id)),
          button(t("Ver más detalles"), () => openProblemPage(p.id)),
        ),
      ]),
    ),
  );
}
async function problemDetail(id) {
  const p = await api("/api/problems/" + id),
    box = el("div");
  box.append(
    badge(p.severity),
    el(
      "p",
      machineName(p.machine_id) +
        " · " +
        stamp(p.first_seen) +
        " → " +
        stamp(p.last_seen),
    ),
    el("h3", t("Qué se ha observado")),
    el("p", p.data.summary),
    el("h3", t("Hipótesis e incertidumbre")),
    el("p", p.data.reasoning || t("Sin ampliación")),
    el("h3", t("Siguientes comprobaciones")),
    el("p", p.data.next_steps || t("Revisar evidencia original")),
  );
  if (p.data.category === "monitor.capacity")
    box.append(capacityProblemHint(p));
  box.append(
    actions(
      button(t("Copiar prompt"), async () => {
        const text = await api("/api/problems/" + id + "/prompt");
        const preview = el("div");
        preview.append(
          el(
            "p",
            t(
              "Revisa el contexto antes de copiarlo. Los campos de secretos reconocidos se ocultan.",
            ),
          ),
          el("pre", text),
          button(t("Copiar al portapapeles"), async () => {
            await navigator.clipboard.writeText(text);
            notice(t("Prompt copiado."));
          }),
        );
        $("#modal").close();
        modal(t("Prompt de investigación"), preview);
      }),
      button(t("Marcar resuelto"), async () => {
        await api("/api/problems/" + id + "/resolve", {});
        $("#modal").close();
        await refresh();
      }),
      button(t("No notificar este problema"), () => {
        $("#modal").close();
        view = "rule";
        edit = {
          name: p.title,
          kind: "problem",
          pattern: id,
          action: "mute",
          machine_id: p.machine_id,
          enabled: true,
        };
        render();
      }),
      button(t("Preguntar al asistente"), () => {
        openProblemChat(p);
      }),
      button(t("Ver más detalles"), () => openProblemPage(p.id)),
      button(t("Buscar más detalles del problema"), async () => {
        await startInvestigation(p);
        await openProblemPage(p.id);
      }),
    ),
  );
  box.append(
    el("h3", t("Evidencia retenida")),
    el(
      "p",
      t(
        "La búsqueda profunda usa hasta 2 llamadas y una ventana inicial de ±30 minutos. Puedes ajustar la ventana en Ver más detalles.",
      ),
      "subtle",
    ),
    el(
      "pre",
      p.evidence
        .map(
          (e) =>
            "[" +
            (e.timestamp || t("fecha desconocida")) +
            "] " +
            e.id +
            "\n" +
            e.message,
        )
        .join("\n\n") || t("La evidencia original ha caducado."),
    ),
  );
  modal(p.title, box);
}
async function eventsView(root) {
  const bar = el("div", undefined, "toolbar"),
    q = el("input");
  q.placeholder = t("Buscar en originales retenidos");
  q.setAttribute("aria-label", t("Buscar logs"));
  const source = field("source_id", t("Fuente"), "select", "", [
    ["", t("Todas")],
    ...S.source
      .filter((x) => !scope || x.machine_id === scope)
      .map((x) => [x.id, x.name]),
  ]);
  let next = offset,
    previous = [];
  bar.append(
    q,
    source,
    button(t("Buscar"), () => {
      offset = 0;
      previous = [];
      return load();
    }),
    button(t("Anterior"), () => {
      offset = previous.pop() ?? 0;
      return load();
    }),
    button(t("Siguiente"), () => {
      previous.push(offset);
      offset = next;
      return load();
    }),
  );
  root.append(
    bar,
    el(
      "p",
      t(
        "Búsqueda progresiva sobre originales comprimidos, hasta 5.000 eventos por paso. Siguiente continúa desde el punto examinado.",
      ),
      "subtle",
    ),
  );
  const dest = el("div"),
    progress = el("p");
  root.append(progress, dest);
  async function load() {
    const r = await api(
      "/api/events?machine_id=" +
        encodeURIComponent(scope) +
        "&source_id=" +
        encodeURIComponent(source.querySelector("select").value) +
        "&offset=" +
        offset +
        "&q=" +
        encodeURIComponent(q.value),
    );
    next = r.next_offset;
    progress.textContent =
      r.scanned +
      t(" eventos examinados en este paso") +
      (r.exhausted ? t(" · Fin del histórico") : "");
    dest.replaceChildren(
      table(
        [t("Hora"), t("Máquina"), t("Servicio"), t("Mensaje"), t("Cobertura")],
        r.events.map((e) => [
          e.timestamp || t("Inferida"),
          machineName(e.machine_id),
          e.service,
          button(e.message.slice(0, 180), () =>
            modal(t("Evento ") + e.id, el("pre", JSON.stringify(e, null, 2))),
          ),
          badge(e.status),
        ]),
      ),
    );
  }
  await load();
}
function activity(root) {
  root.append(
    el("h2", t("Análisis")),
    table(
      [
        t("Estado"),
        t("Máquina"),
        t("Creado"),
        t("Intentos"),
        t("Diagnóstico"),
        t("Acciones"),
      ],
      S.jobs.map((j) => [
        badge(j.status),
        machineName(j.machine_id),
        stamp(j.created),
        j.attempts,
        j.error || "—",
        j.status === "failed"
          ? button(t("Reintentar análisis"), async () => {
              await api("/api/jobs/" + j.id + "/retry", {});
              await refresh();
              notice(t("Análisis en cola para el próximo ciclo automático."));
            })
          : "—",
      ]),
    ),
    el("h2", t("Entregas")),
    table(
      [t("Estado"), t("Destino"), t("Fecha"), t("Resultado"), ""],
      S.deliveries.map((d) => [
        badge(d.status),
        (S.destination.find((x) => x.id === d.destination_id) || {}).name ||
          d.destination_id,
        stamp(d.created),
        d.error || "—",
        button(t("Reintentar"), async () => {
          await api("/api/deliveries/" + d.id + "/retry", {});
          notice(
            t(
              "Reintento programado; podría duplicar una entrega de resultado desconocido.",
            ),
          );
        }),
      ]),
    ),
  );
}
function rulePresetPanel() {
  const b = bilingual,
    machine = scope;
  const box = panel(
    b(
      "Filtros predefinidos: probar y aplicar",
      "Built-in filters: preview and apply",
    ),
  );
  box.append(
    el(
      "p",
      b(
        "Ya hay tres filtros incluidos. Están desactivados hasta que los añadas. Apartan coincidencias del LLM, pero los originales se conservan según la retención. La compactación de repeticiones ya funciona sin activar estos filtros.",
        "Three filters are included. They stay off until you add them. Matches are left out of LLM review, while originals follow retention settings. Repetition compaction already works without these filters.",
      ),
    ),
    el(
      "p",
      b("Ámbito de los cambios: ", "Changes apply to: ") +
        (machine
          ? machineName(machine)
          : b("todas las máquinas", "all machines")),
      "guide-summary",
    ),
    howTo(b("Cómo aplicar un filtro", "How to apply a filter"), [
      b(
        "Elige la máquina en el selector superior; dejar Todas las máquinas lo hace global.",
        "Choose a machine in the top selector; leaving All machines makes it global.",
      ),
      b(
        "Abre la vista previa y comprueba ejemplos de lo que se apartaría y de lo que seguiría analizándose.",
        "Open the preview and check examples of what would be left out and what would still be reviewed.",
      ),
      b(
        "Aplica solo si el resultado te sirve. Puedes desactivarlo aquí. Para volver a analizar coincidencias retenidas, ve a Fuentes → Recuperar retenidos sin analizar.",
        "Apply only if the result suits you. You can disable it here. To review retained matches again, use Sources → Recover unreviewed retained logs.",
      ),
    ]),
  );
  const list = el("div", undefined, "guide-grid");
  box.append(list);
  api("/api/rule-presets")
    .then((presets) => {
      if (!box.isConnected) return;
      for (const preset of presets) {
        const row = el("section", undefined, "guide-card"),
          existing = S.rule.find(
            (r) => r.name === preset.name && (r.machine_id || "") === machine,
          );
        row.append(
          el("h3", t(preset.name)),
          el("p", t(preset.note)),
          guideDetails(
            b("Ver patrón técnico", "Show technical pattern"),
            el("pre", preset.pattern),
          ),
        );
        if (existing) {
          const same =
            existing.pattern === preset.pattern &&
            existing.kind === preset.kind &&
            existing.action === preset.action &&
            !existing.source_id &&
            !existing.expires_at;
          row.append(
            el(
              "strong",
              same
                ? existing.enabled
                  ? b("Filtro activado", "Filter enabled")
                  : b(
                      "Filtro guardado y desactivado",
                      "Filter saved and disabled",
                    )
                : b(
                    "Hay una regla guardada con otra configuración",
                    "A rule with different settings is saved",
                  ),
            ),
          );
          row.append(
            button(b("Revisar regla guardada", "Review saved rule"), () => {
              edit = existing;
              render();
            }),
          );
          if (existing.enabled)
            row.append(
              button(
                b("Desactivar este filtro", "Disable this filter"),
                async () => {
                  await api("/api/objects/rule", {
                    id: existing.id,
                    enabled: false,
                  });
                  await refresh();
                  notice(
                    b(
                      "Filtro desactivado. Los retenidos apartados no se reanalizan hasta que recuperes la fuente.",
                      "Filter disabled. Retained excluded logs are not reviewed again until you recover the source.",
                    ),
                  );
                },
              ),
            );
        }
        row.append(
          button(
            b(
              "Ver ejemplos antes de aplicar",
              "Preview examples before applying",
            ),
            async () => {
              const r = await api("/api/rules/preview", {
                name: preset.name,
                action: preset.action,
                kind: preset.kind,
                pattern: preset.pattern,
                machine_id: machine,
                enabled: true,
              });
              const preview = el("div");
              preview.append(
                el(
                  "p",
                  b("Ámbito: ", "Scope: ") +
                    (machine
                      ? machineName(machine)
                      : b("todas las máquinas", "all machines")),
                ),
                el(
                  "p",
                  r.matched +
                    b(" coincidencias entre ", " matches among ") +
                    r.tested +
                    b(
                      " logs de muestra (hasta 500 recientes). Es una muestra, no una garantía sobre futuros mensajes.",
                      " sampled logs (up to 500 recent entries). This is a sample, not a guarantee about future messages.",
                    ),
                ),
              );
              for (const [title, entries] of [
                [
                  b("Se apartarían del LLM", "Would be left out of LLM review"),
                  r.matches,
                ],
                [
                  b(
                    "Este filtro dejaría pasar",
                    "This filter would let through",
                  ),
                  r.nonmatches,
                ],
              ]) {
                preview.append(el("h3", title));
                if (!entries.length)
                  preview.append(
                    el(
                      "p",
                      b(
                        "Sin ejemplos en esta muestra.",
                        "No examples in this sample.",
                      ),
                    ),
                  );
                else
                  for (const entry of entries)
                    preview.append(
                      el(
                        "p",
                        entry.service ||
                          b("Sin servicio declarado", "No declared service"),
                        "subtle",
                      ),
                      el("pre", entry.message),
                    );
              }
              const canApply =
                !existing ||
                (!existing.enabled &&
                  existing.pattern === preset.pattern &&
                  existing.action === preset.action &&
                  existing.kind === preset.kind &&
                  !existing.source_id &&
                  !existing.expires_at);
              if (canApply) {
                const apply = button(
                  b(
                    "Aplicar filtro a este ámbito",
                    "Apply filter to this scope",
                  ),
                  async () => {
                    if (existing)
                      await api("/api/objects/rule", {
                        id: existing.id,
                        enabled: true,
                      });
                    else
                      await api("/api/rule-presets/" + preset.id, {
                        machine_id: machine,
                      });
                    $("#modal").close();
                    await refresh();
                    notice(
                      b(
                        "Filtro aplicado. Comprueba la cobertura tras varios lotes; puedes desactivarlo desde Reglas.",
                        "Filter applied. Check coverage after several batches; you can disable it in Rules.",
                      ),
                    );
                  },
                );
                apply.disabled = r.matched === 0;
                preview.append(apply);
                if (!r.matched)
                  preview.append(
                    el(
                      "p",
                      b(
                        "No hay coincidencias que revisar. Espera a capturar logs de este tipo antes de aplicar el filtro.",
                        "There are no matches to inspect. Capture logs of this type before applying the filter.",
                      ),
                    ),
                  );
              }
              modal(
                t(preset.name) + b(" · vista previa", " · preview"),
                preview,
              );
            },
          ),
        );
        list.append(row);
      }
    })
    .catch((error) => {
      if (box.isConnected)
        list.replaceChildren(el("p", error.message, "error"));
    });
  return box;
}

function backupView(root) {
  const p = panel(t("Copia coherente del observatorio"));
  p.append(
    el(
      "p",
      t(
        "Incluye originales comprimidos, máquinas, reglas y credenciales. Se guarda en la carpeta local de datos, con permisos exclusivos del propietario.",
      ),
    ),
    button(
      t("Crear copia local"),
      async () => {
        const r = await api("/api/backup", {});
        notice(t("Copia guardada: backups/") + r.filename);
      },
      "",
    ),
    el("h3", t("Restaurar en una carpeta nueva")),
    el("pre", "logsentinel restore /ruta/backup.db --data-dir /ruta/nueva"),
    el(
      "p",
      t(
        "Tras restaurar, rota la clave de acceso, los tokens de emisor y las credenciales de notificación: la copia las incluye.",
      ),
    ),
    el("h3", t("Clave de acceso del panel")),
    el(
      "p",
      t(
        "La clave vive en access-key.txt del directorio de datos. Rotarla cierra las sesiones y deja de aceptar la clave anterior.",
      ),
    ),
    button(t("Rotar clave de acceso"), async () => {
      if (
        !confirm(
          t(
            "Las sesiones abiertas se cerrarán. La clave anterior deja de funcionar.",
          ),
        )
      )
        return;
      const r = await api("/api/access-key/rotate", {});
      notice(
        t("Nueva clave (cópiala ahora; no se volverá a mostrar): ") + r.token,
      );
    }),
  );
  root.append(p);
}
initLanguage();
initHelp();
refresh().catch(() => {});
setInterval(async () => {
  if (!$("#shell").hidden) {
    try {
      S.monitor = await api("/api/monitor");
      drawMonitor(S.monitor);
    } catch {
      $("#monitor-status").textContent = t(
        "Sin conexión con el portal. No se puede confirmar el estado del monitor.",
      );
    }
  }
}, 5000);
setInterval(() => {
  if ($("#shell").hidden || view !== "summary" || $("#modal").open) return;
  // This rebuilds the whole content section every 15 seconds. Keeping the data
  // live is worth it; losing the reader's place is not. Stay out of the way
  // while something inside is focused or text is selected, and put the page
  // back where it was afterwards.
  const active = document.activeElement;
  if (active && active !== document.body && $("#content").contains(active)) return;
  const selection = document.getSelection();
  if (selection && !selection.isCollapsed) return;
  const top = window.scrollY;
  refresh()
    .then(() => {
      if (window.scrollY !== top) window.scrollTo(0, top);
    })
    .catch((e) => notice(e.message, true));
}, 15000);
