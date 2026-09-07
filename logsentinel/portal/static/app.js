"use strict";
const $ = (s) => document.querySelector(s),
  el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
let S = {},
  view = "summary",
  scope = "",
  edit = null,
  offset = 0;
const names = {
  summary: "Resumen",
  machine: "Máquinas",
  source: "Fuentes",
  problems: "Problemas",
  events: "Histórico",
  destination: "Notificaciones",
  rule: "Reglas",
  settings: "Modelo y análisis",
  chat: "Asistente",
  activity: "Actividad",
  backup: "Copias",
};
const channelNames = {
  system: "Sistema",
  telegram: "Telegram",
  slack: "Slack",
  discord: "Discord",
  hermes: "Hermes",
  n8n: "n8n",
  webhook: "Webhook genérico",
  file: "Archivo local",
};
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const stamp = (t) => (t ? new Date(Number(t) * 1000).toLocaleString() : "—"),
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
    throw Error("Introduce la clave de acceso");
  }
  let data = r.headers.get("content-type")?.includes("json")
    ? await r.json()
    : await r.text();
  if (!r.ok)
    throw Error(
      typeof data === "string"
        ? data
        : typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail),
    );
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
  return el("span", text, "badge " + text);
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
      el("h2", "Todavía no hay registros"),
      el(
        "p",
        "Los datos aparecerán aquí cuando configures fuentes y ejecutes el análisis.",
      ),
    );
    return e;
  }
  const w = el("div", undefined, "table-wrap"),
    t = el("table"),
    h = el("tr");
  headers.forEach((v) => h.append(el("th", v)));
  const head = el("thead");
  head.append(h);
  t.append(head);
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
  t.append(body);
  w.append(t);
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
  $("#login").hidden = true;
  $("#shell").hidden = false;
  const sel = $("#machine-scope");
  sel.replaceChildren();
  [["", "Todas las máquinas"], ...S.machine.map((m) => [m.id, m.name])].forEach(
    ([v, t]) => {
      let o = el("option", t);
      o.value = v;
      o.selected = v === scope;
      sel.append(o);
    },
  );
  await render();
}
function navigate(v) {
  view = v;
  edit = null;
  offset = 0;
  $("#notice").hidden = true;
  render();
}
Object.entries(names).forEach(([key, label]) =>
  $("#nav").append(button(label, () => navigate(key))),
);
$("#machine-scope").onchange = () => {
  scope = $("#machine-scope").value;
  offset = 0;
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
  $("#content").replaceChildren(root);
  $("#page-title").textContent = names[view];
  [...$("#nav").children].forEach((n, i) =>
    n.classList.toggle("active", Object.keys(names)[i] === view),
  );
  if (["machine", "source", "destination", "rule"].includes(view))
    return objectView(root);
  if (view === "summary") return summary(root);
  if (view === "settings") return settingsView(root);
  if (view === "problems") return problemList(root);
  if (view === "events") return eventsView(root);
  if (view === "chat") return chatView(root);
  if (view === "activity") return activity(root);
  if (view === "backup") return backupView(root);
}
async function summary(root) {
  const stats = scope
      ? await api("/api/stats?machine_id=" + encodeURIComponent(scope))
      : S.stats,
    c = stats.coverage,
    all = Object.values(c).reduce((a, b) => a + b, 0),
    cards = el("div", undefined, "cards");
  [
    ["Eventos retenidos", all, "Originales recuperables"],
    ["Problemas abiertos", stats.open_problems || 0, "Basados en evidencia"],
    [
      "Sin revisar por capacidad",
      c.capacity || 0,
      "Cobertura reducida explícita",
    ],
    [
      "Tokens reportados",
      (stats.usage.input_tokens || 0) + (stats.usage.output_tokens || 0),
      (stats.usage.unknown_calls || 0) + " llamadas con uso desconocido",
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
  const status = panel("Estado del observatorio");
  status.append(
    el(
      "p",
      S.settings.enabled
        ? "Análisis periódico activado. Último ciclo: " + stamp(S.last_analysis)
        : "El análisis automático está pausado. Configura fuentes y modelo antes de activarlo.",
    ),
  );
  if (S.worker_error) status.append(el("p", S.worker_error));
  status.append(
    actions(
      button(
        "Analizar ahora",
        async () => {
          notice("Analizando los eventos admitidos por el presupuesto…");
          const r = await api("/api/scan", {});
          await refresh();
          notice(
            "Ciclo terminado: " +
              r.calls +
              " llamadas. Consulta cobertura y actividad.",
          );
        },
        "",
      ),
      button("Detectar fuentes locales", discover),
    ),
  );
  root.append(status);
  const p = panel("Almacenamiento y cobertura");
  p.append(
    el(
      "p",
      bytes(stats.disk_bytes) +
        " en disco · " +
        bytes(stats.segments.original) +
        " en bloques lógicos · " +
        bytes(stats.segments.compressed) +
        " comprimidos",
    ),
    table(["Estado de eventos", "Cantidad"], Object.entries(c)),
  );
  p.append(
    el("h3", "Uso por fuente"),
    el(
      "p",
      "Tokens repartidos proporcionalmente al tamaño del contexto enviado; son una atribución estimada, no mediciones separadas del proveedor.",
      "subtle",
    ),
    table(
      [
        "Fuente",
        "Eventos recibidos",
        "Volumen original",
        "Tokens atribuidos",
        "Llamadas sin uso completo",
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
    const n = panel("Empieza con este equipo");
    n.append(
      el(
        "p",
        "Detecta el sistema y crea su ficha. También puedes añadir una máquina cuyos logs se reciben en una carpeta.",
      ),
      button("Detectar este equipo", discover, ""),
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
    "Detectado: " +
      d.os +
      ". Journal: " +
      (d.journalctl ? "disponible" : "ausente") +
      ". Archivos: " +
      d.files
        .map((f) => f.path + (f.readable ? "" : " (sin permiso)"))
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
        machine: "Identidad y contexto de cada equipo.",
        source: "Archivos, carpetas, journal y recepción continua.",
        destination:
          "Avisos directos y servicios externos. Guardar no envía mensajes.",
        rule: "No notificar mantiene el análisis. Excluir evita enviar esas coincidencias al modelo.",
      }[kind],
    ),
    button(
      "Añadir",
      () => {
        edit = {};
        render();
      },
      "",
    ),
  );
  root.append(bar);
  root.append(
    table(
      kind === "machine"
        ? ["Nombre", "Sistema", "Tipo", "Acciones"]
        : ["Nombre", "Máquina", "Tipo", "Estado", "Acciones"],
      items.map((obj) => {
        const b = [
          button("Editar", () => {
            edit = obj;
            render();
          }),
        ];
        if (kind === "source") {
          b.push(
            button("Leer ahora", async () => {
              const r = await api("/api/source/" + obj.id + "/poll", {});
              await refresh();
              notice(r.events + " eventos nuevos. " + (r.health.error || ""));
            }),
          );
          if (obj.kind === "push")
            b.push(
              button("Clave de emisor", async () => {
                const r = await api("/api/sources/" + obj.id + "/token", {});
                const p = el("pre", JSON.stringify(r, null, 2));
                modal("Guarda esta clave: se muestra una vez", p);
              }),
            );
          b.push(
            button("Reanalizar retenidos", async () => {
              const r = await api("/api/reanalyze", { source_id: obj.id });
              notice(
                r.scheduled + " eventos programados (máximo " + r.limit + ").",
              );
            }),
          );
        }
        if (kind === "destination")
          b.push(
            button("Enviar prueba", async () => {
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
              "Eliminar",
              async () => {
                if (confirm("¿Eliminar esta configuración?")) {
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
          ? [obj.name, obj.os || "Sin especificar", obj.kind, actions(...b)]
          : [
              obj.name,
              machineName(obj.machine_id),
              channelNames[obj.kind] || obj.kind,
              el(
                "span",
                (obj.enabled ? "Activo" : "Pausado") +
                  (S.health[obj.id]?.error
                    ? " · " + S.health[obj.id].error
                    : ""),
              ),
              actions(...b),
            ];
      }),
    ),
  );
  if (edit !== null) root.append(objectForm(kind, edit));
}
function objectForm(kind, o) {
  const p = panel(o.id ? "Editar configuración" : "Nueva configuración"),
    f = el("form", undefined, "form-grid");
  const add = (...a) => f.append(field(...a));
  add("name", "Nombre", "text", o.name);
  const machines = [
    ["", "Seleccionar máquina"],
    ...S.machine.map((m) => [m.id, m.name]),
  ];
  if (kind === "machine") {
    add("kind", "Tipo", "select", o.kind || "imported", [
      ["local", "Este equipo"],
      ["imported", "Otro equipo"],
    ]);
    add("hostname", "Hostname declarado", "text", o.hostname);
    add("os", "Sistema / distribución", "text", o.os);
    add("timezone", "Zona horaria IANA", "text", o.timezone || "UTC");
    add("notes", "Contexto de la máquina", "textarea", o.notes);
  }
  if (kind === "source") {
    add("machine_id", "Máquina", "select", o.machine_id || scope, machines);
    add("kind", "Tipo de fuente", "select", o.kind || "file", [
      ["file", "Archivo"],
      ["folder", "Carpeta"],
      ["journald", "Journal local"],
      ["push", "Recepción remota"],
    ]);
    add("path", "Ruta (archivo o carpeta)", "text", o.path);
    add(
      "pattern",
      "Patrón de archivos en carpeta",
      "text",
      o.pattern || "*.log*",
    );
    add("history", "Importar histórico al iniciar", "checkbox", o.history);
    add(
      "multiline",
      "Agrupar continuaciones con sangría",
      "checkbox",
      o.multiline,
    );
    add(
      "max_batch_bytes",
      "Máximo de bytes por lote de lectura",
      "number",
      o.max_batch_bytes ?? 2000000,
    );
    add("enabled", "Captura activa", "checkbox", o.enabled);
  }
  if (kind === "destination") {
    add(
      "kind",
      "Canal",
      "select",
      o.kind || "telegram",
      Object.entries(channelNames),
    );
    add("machine_id", "Ámbito de máquina", "select", o.machine_id || "", [
      ["", "Todas"],
      ...machines.slice(1),
    ]);
    add("source_id", "Ámbito de fuente", "select", o.source_id || "", [
      ["", "Todas"],
      ...S.source.map((x) => [x.id, x.name]),
    ]);
    add(
      "min_severity",
      "Gravedad mínima",
      "select",
      o.min_severity || "MEDIUM",
      ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((x) => [x, x]),
    );
    add("url", "URL webhook (vacío conserva la guardada)", "password", "");
    add("token", "Token de Telegram (vacío conserva)", "password", "");
    add("chat_id", "Chat ID de Telegram", "text", o.chat_id);
    add("secret", "Secreto de firma Hermes (vacío conserva)", "password", "");
    add("headers", "Cabeceras JSON (vacío conserva)", "textarea", "");
    add("path", "Nombre del archivo local (opcional)", "text", o.path);
    add(
      "cooldown_seconds",
      "Agrupar avisos durante (segundos)",
      "number",
      o.cooldown_seconds ?? 300,
    );
    add(
      "rotation_mb",
      "Rotar archivo de avisos a (MiB)",
      "number",
      o.rotation_mb ?? 10,
    );
    add(
      "keep_archives",
      "Copias comprimidas de avisos",
      "number",
      o.keep_archives ?? 3,
    );
    add("enabled", "Destino activo", "checkbox", o.enabled);
    add("clear", "Borrar secretos guardados al guardar", "checkbox", false);
    const help = el(
      "p",
      "Configura solo los campos de tu canal. Hermes necesita ruta y firma; n8n, URL y autenticación. Claves existentes: " +
        (o.configured_fields || []).join(", "),
      "wide subtle",
    );
    f.append(help);
    f.append(
      actions(
        button("Plantilla Hermes", () => showTemplate("hermes")),
        button("Plantilla n8n", () => showTemplate("n8n")),
      ),
    );
  }
  if (kind === "rule") {
    add("machine_id", "Máquina", "select", o.machine_id || scope, [
      ["", "Todas"],
      ...machines.slice(1),
    ]);
    add("source_id", "Fuente", "select", o.source_id || "", [
      ["", "Todas"],
      ...S.source.map((x) => [x.id, x.name]),
    ]);
    add("action", "Acción", "select", o.action || "mute", [
      ["mute", "No notificar"],
      ["exclude", "Excluir del análisis"],
    ]);
    add("kind", "Coincidencia", "select", o.kind || "regex", [
      ["regex", "Expresión regular"],
      ["ip", "IP exacta / CIDR"],
      ["problem", "ID de problema"],
    ]);
    add("pattern", "Expresión / IP / ID", "textarea", o.pattern);
    add("enabled", "Regla activa", "checkbox", o.enabled ?? true);
    add(
      "expires_at",
      "Caducidad opcional (hora local)",
      "datetime-local",
      o.expires_at
        ? new Date(o.expires_at * 1000 - new Date().getTimezoneOffset() * 60000)
            .toISOString()
            .slice(0, 16)
        : "",
    );
    f.append(
      button("Vista previa de coincidencias", async () => {
        const data = formData(f);
        const r = await api("/api/rules/preview", data);
        modal(
          "Vista previa · muestra de " +
            r.tested +
            " eventos, " +
            r.matched +
            " coincidencias",
          el("pre", JSON.stringify(r, null, 2)),
        );
      }),
    );
  }
  const tools = el("div", undefined, "toolbar wide"),
    submit = el("button", "Guardar");
  submit.type = "submit";
  tools.append(
    submit,
    button("Cancelar", () => {
      edit = null;
      render();
    }),
  );
  f.append(tools);
  f.onsubmit = async (ev) => {
    ev.preventDefault();
    submit.disabled = true;
    try {
      const data = formData(f);
      if (kind === "destination") {
        data.headers = data.headers ? JSON.parse(data.headers) : {};
        if (data.clear)
          data.clear_secrets = ["url", "token", "secret", "headers"];
        delete data.clear;
      }
      if (o.id) data.id = o.id;
      await api("/api/objects/" + kind, data);
      edit = null;
      await refresh();
      notice("Configuración guardada.");
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
      "Plantilla para configurar tu servicio externo. Sustituye credenciales y destino; la aplicación no lo activa automáticamente.",
    ),
    el("pre", JSON.stringify(result, null, 2)),
    button("Copiar JSON", () =>
      navigator.clipboard.writeText(JSON.stringify(result, null, 2)),
    ),
  );
  modal("Plantilla " + kind, p);
}
function settingsView(root) {
  const c = S.settings,
    p = panel("Proveedor, capacidad y política de revisión"),
    f = el("form", undefined, "form-grid");
  const add = (...a) => f.append(field(...a));
  add("provider", "Proveedor", "select", c.llm.provider, [
    ["ollama", "Ollama"],
    ["openai", "API compatible"],
  ]);
  add("base_url", "URL del servidor", "text", c.llm.base_url);
  add("model", "Modelo", "text", c.llm.model);
  add("api_key", "Clave API (vacío conserva)", "password", "");
  add(
    "context_tokens",
    "Contexto efectivo configurado",
    "number",
    c.context_tokens,
  );
  add(
    "input_budget",
    "Presupuesto de entrada (cota conservadora)",
    "number",
    c.input_budget,
  );
  add("max_tokens", "Máximo de salida", "number", c.llm.max_tokens);
  add(
    "enable_thinking",
    "Activar razonamiento prolongado del modelo",
    "checkbox",
    c.llm.enable_thinking,
  );
  add("max_calls", "Máximo de llamadas por ciclo", "number", c.max_calls);
  add(
    "interval_seconds",
    "Intervalo entre ciclos (segundos)",
    "number",
    c.interval_seconds,
  );
  add(
    "max_events",
    "Eventos admitidos por máquina/ciclo",
    "number",
    c.max_events,
  );
  add("sensitivity", "Sensibilidad", "select", c.sensitivity, [
    ["light", "Ligera"],
    ["balanced", "Equilibrada"],
    ["thorough", "Exhaustiva"],
  ]);
  add(
    "retention_days",
    "Retención de originales (días)",
    "number",
    c.retention_days,
  );
  add(
    "disk_limit_mb",
    "Cuota de almacenamiento (MiB)",
    "number",
    c.disk_limit_mb,
  );
  add(
    "remote_allowed",
    "Autorizar enviar contexto al servidor remoto configurado",
    "checkbox",
    c.remote_allowed,
  );
  add("enabled", "Análisis periódico activo", "checkbox", c.enabled);
  f.append(
    button("Consultar modelos y presupuesto", async () => {
      const r = await api("/api/model/info", {}),
        box = el("div");
      box.append(
        el("p", "Modelo guardado: " + r.model),
        el(
          "p",
          "Máximo declarado: " +
            (r.reported_maximum ?? "desconocido") +
            " · Contexto cargado: " +
            (r.running_context ?? "desconocido"),
        ),
        el("p", "Modelos disponibles: " + r.models.join(", ")),
        el("p", r.note),
      );
      if (r.suggested_input_budget >= 512)
        box.append(
          button("Usar presupuesto sugerido en el formulario", () => {
            f.elements.namedItem("context_tokens").value = r.suggested_context;
            f.elements.namedItem("input_budget").value =
              r.suggested_input_budget;
            $("#modal").close();
            notice("Revisa y guarda los ajustes para aplicarlos.");
          }),
        );
      modal("Capacidad del modelo", box);
    }),
  );
  const submit = el("button", "Guardar ajustes");
  submit.type = "submit";
  f.append(
    submit,
    button("Probar modelo con datos sintéticos", async () => {
      notice("Comprobando modelo…");
      const r = await api("/api/model/test", {});
      notice(r.message);
    }),
  );
  f.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const d = formData(f);
      d.llm = {
        ...c.llm,
        provider: d.provider,
        base_url: d.base_url,
        model: d.model,
        api_key: d.api_key,
        max_tokens: d.max_tokens,
        enable_thinking: d.enable_thinking,
      };
      delete d.llm.api_key_set;
      [
        "provider",
        "base_url",
        "model",
        "api_key",
        "max_tokens",
        "enable_thinking",
      ].forEach(
        (k) => delete d[k],
      );
      await api("/api/settings", d);
      await refresh();
      notice("Ajustes aplicados.");
    } catch (err) {
      notice(err.message, true);
    }
  };
  p.append(
    el(
      "p",
      "Se reserva espacio para instrucciones y salida. Sin tokenizer compatible, el presupuesto usa bytes UTF-8 como cota conservadora. La prueba de conexión no mide calidad de detección.",
    ),
    f,
  );
  root.append(p);
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
        button("Anterior", () => {
          offset = Math.max(0, offset - 100);
          render();
        }),
        button("Siguiente", () => {
          offset += 100;
          render();
        }),
      ),
    );
  if (short) root.append(el("h2", "Problemas recientes"));
  root.append(
    table(
      ["Gravedad", "Problema", "Máquina", "Apariciones", "Estado", ""],
      rows
        .slice(0, short ? 5 : 100)
        .map((p) => [
          badge(p.severity),
          p.title,
          machineName(p.machine_id),
          p.count,
          p.status,
          button("Ver evidencia", () => problemDetail(p.id)),
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
    el("h3", "Qué se ha observado"),
    el("p", p.data.summary),
    el("h3", "Hipótesis e incertidumbre"),
    el("p", p.data.reasoning || "Sin ampliación"),
    el("h3", "Siguientes comprobaciones"),
    el("p", p.data.next_steps || "Revisar evidencia original"),
  );
  box.append(
    actions(
      button("Copiar prompt", async () => {
        const text = await api("/api/problems/" + id + "/prompt");
        const preview = el("div");
        preview.append(
          el(
            "p",
            "Revisa el contexto antes de copiarlo. Los campos de secretos reconocidos se ocultan.",
          ),
          el("pre", text),
          button("Copiar al portapapeles", async () => {
            await navigator.clipboard.writeText(text);
            notice("Prompt copiado.");
          }),
        );
        $("#modal").close();
        modal("Prompt de investigación", preview);
      }),
      button("Marcar resuelto", async () => {
        await api("/api/problems/" + id + "/resolve", {});
        $("#modal").close();
        await refresh();
      }),
      button("No notificar este problema", () => {
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
      button("Preguntar al asistente", () => {
        $("#modal").close();
        scope = p.machine_id;
        view = "chat";
        render();
      }),
    ),
  );
  box.append(
    el("h3", "Evidencia retenida"),
    el(
      "pre",
      p.evidence
        .map(
          (e) =>
            "[" +
            (e.timestamp || "fecha desconocida") +
            "] " +
            e.id +
            "\n" +
            e.message,
        )
        .join("\n\n") || "La evidencia original ha caducado.",
    ),
  );
  modal(p.title, box);
}
async function eventsView(root) {
  const bar = el("div", undefined, "toolbar"),
    q = el("input");
  q.placeholder = "Buscar en originales retenidos";
  q.setAttribute("aria-label", "Buscar logs");
  const source = field("source_id", "Fuente", "select", "", [
    ["", "Todas"],
    ...S.source
      .filter((x) => !scope || x.machine_id === scope)
      .map((x) => [x.id, x.name]),
  ]);
  let next = offset,
    previous = [];
  bar.append(
    q,
    source,
    button("Buscar", () => {
      offset = 0;
      previous = [];
      return load();
    }),
    button("Anterior", () => {
      offset = previous.pop() ?? 0;
      return load();
    }),
    button("Siguiente", () => {
      previous.push(offset);
      offset = next;
      return load();
    }),
  );
  root.append(
    bar,
    el(
      "p",
      "Búsqueda progresiva sobre originales comprimidos, hasta 5.000 eventos por paso. Siguiente continúa desde el punto examinado.",
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
      " eventos examinados en este paso" +
      (r.exhausted ? " · Fin del histórico" : "");
    dest.replaceChildren(
      table(
        ["Hora", "Máquina", "Servicio", "Mensaje", "Cobertura"],
        r.events.map((e) => [
          e.timestamp || "Inferida",
          machineName(e.machine_id),
          e.service,
          button(e.message.slice(0, 180), () =>
            modal("Evento " + e.id, el("pre", JSON.stringify(e, null, 2))),
          ),
          badge(e.status),
        ]),
      ),
    );
  }
  await load();
}
async function chatView(root) {
  const p = panel("Preguntar sobre los logs"),
    f = el("form");
  const m = field(
    "machine_id",
    "Máquina",
    "select",
    scope || S.machine[0]?.id,
    S.machine.map((x) => [x.id, x.name]),
  );
  const q = field("message", "Pregunta o petición de filtro", "textarea", "");
  f.append(m, q);
  const send = el("button", "Consultar");
  send.type = "submit";
  f.append(send);
  p.append(
    el(
      "p",
      "Consulta una muestra acotada del histórico de la máquina. Las propuestas de filtros se revisan antes de aplicarlas.",
    ),
    f,
  );
  const conversation = el("div");
  root.append(p, conversation);
  const history = await api(
    "/api/chat/history?machine_id=" +
      encodeURIComponent(scope || S.machine[0]?.id || ""),
  );
  history.forEach((c) => {
    conversation.append(
      el("div", c.question, "message"),
      el("div", c.response.answer, "message"),
    );
  });
  f.onsubmit = async (e) => {
    e.preventDefault();
    send.disabled = true;
    try {
      const d = formData(f);
      conversation.append(el("div", d.message, "message"));
      const r = await api("/api/chat", d);
      const a = el("div", r.answer, "message");
      a.append(
        el(
          "p",
          "Evidencias: " +
            r.evidence_ids.join(", ") +
            " · " +
            r.sample_events +
            " eventos aportados",
          "subtle",
        ),
      );
      if (r.filter)
        a.append(
          button("Revisar filtro propuesto", () => {
            view = "rule";
            edit = r.filter;
            render();
          }),
        );
      conversation.append(a);
    } catch (err) {
      notice(err.message, true);
    } finally {
      send.disabled = false;
    }
  };
}
function activity(root) {
  root.append(
    el("h2", "Análisis"),
    table(
      ["Estado", "Máquina", "Creado", "Intentos", "Diagnóstico"],
      S.jobs.map((j) => [
        badge(j.status),
        machineName(j.machine_id),
        stamp(j.created),
        j.attempts,
        j.error || "—",
      ]),
    ),
    el("h2", "Entregas"),
    table(
      ["Estado", "Destino", "Fecha", "Resultado", ""],
      S.deliveries.map((d) => [
        badge(d.status),
        (S.destination.find((x) => x.id === d.destination_id) || {}).name ||
          d.destination_id,
        stamp(d.created),
        d.error || "—",
        button("Reintentar", async () => {
          await api("/api/deliveries/" + d.id + "/retry", {});
          notice(
            "Reintento programado; podría duplicar una entrega de resultado desconocido.",
          );
        }),
      ]),
    ),
  );
}
function backupView(root) {
  const p = panel("Copia coherente del observatorio");
  p.append(
    el(
      "p",
      "Incluye originales comprimidos, máquinas, reglas y credenciales. Se guarda en la carpeta local de datos, con permisos exclusivos del propietario.",
    ),
    button(
      "Crear copia local",
      async () => {
        const r = await api("/api/backup", {});
        notice("Copia guardada: backups/" + r.filename);
      },
      "",
    ),
    el("h3", "Restaurar en una carpeta nueva"),
    el("pre", "logsentinel restore /ruta/backup.db --data-dir /ruta/nueva"),
  );
  root.append(p);
}
refresh().catch(() => {});
setInterval(() => {
  if (!$("#shell").hidden && view === "summary" && !$("#modal").open)
    refresh().catch((e) => notice(e.message, true));
}, 15000);
