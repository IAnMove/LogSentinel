"use strict";
// The brain: where work was done, what was typed, what is installed and what
// changed. Everything shown is read from the central's own tables; the model
// is used only when a question is asked, and what it would receive can be read
// first.
// Kept outside the view: searching or saving redraws the page, and a question
// half written, or its answer, must not go with it.
let brainFilter = { project: "", query: "", days: 30, question: "", answer: null };

function brainText(node, text) {
  const code = el("code", text);
  node.append(code);
  return node;
}

async function brainView(root) {
  const days = brainFilter.days;
  const machine = scope || "";
  const query = (extra) =>
    "?" +
    new URLSearchParams(
      Object.fromEntries(
        Object.entries({ machine, days, ...extra }).filter(([, v]) => v !== ""),
      ),
    );
  const [overview, projects, changes, diary] = await Promise.all([
    api("/api/brain"),
    api("/api/brain/projects" + query({})),
    api("/api/brain/changes" + query({})),
    api("/api/brain/notes" + query({ project: brainFilter.project, q: brainFilter.query })),
  ]);
  if (!root.isConnected) return;
  const machines = overview.machines.filter((m) => !machine || m.machine_id === machine);
  const reporting = machines.filter((m) => m.config.enabled);

  const intro = panel(bilingual("Memoria de los equipos", "Machine memory"));
  intro.append(
    el(
      "p",
      bilingual(
        "Qué hay instalado en cada equipo, qué ha cambiado y en qué se ha trabajado. Nada de esto entra en la revisión automática: solo llega al modelo cuando haces una pregunta aquí, y antes puedes ver exactamente qué se enviaría.",
        "What each machine has installed, what changed and what was worked on. None of it enters the automatic review: it reaches the model only when you ask a question here, and you can read exactly what would be sent first.",
      ),
    ),
  );
  const window_ = field(
    "days",
    bilingual("Periodo", "Period"),
    "select",
    days,
    [
      [1, bilingual("Último día", "Last day")],
      [7, bilingual("7 días", "7 days")],
      [30, bilingual("30 días", "30 days")],
      [90, bilingual("90 días", "90 days")],
      [365, bilingual("Un año", "One year")],
    ],
  );
  window_.querySelector("select").onchange = (e) => {
    brainFilter.days = Number(e.target.value);
    render();
  };
  intro.append(window_);
  root.append(intro);

  if (!reporting.length) {
    const empty = panel(bilingual("Aún no hay equipos informando", "No machine is reporting yet"));
    empty.append(
      el(
        "p",
        bilingual(
          "Activa el cerebro en un equipo más abajo. En el equipo central basta con activarlo; en los demás hay que instalar el emisor con el token que se genera aquí.",
          "Turn the brain on for a machine below. On the central's own machine that is enough; the others need the sender installed with the token generated here.",
        ),
      ),
    );
    root.append(empty);
  }

  // --- ask ---------------------------------------------------------------
  const ask = panel(bilingual("Preguntar", "Ask"));
  const form = el("form", undefined, "form-grid");
  const question = field(
    "message",
    bilingual("Pregunta sobre tus equipos", "Question about your machines"),
    "textarea",
    brainFilter.question,
  );
  question.classList.add("wide");
  question.querySelector("textarea").oninput = (e) => {
    brainFilter.question = e.target.value;
  };
  question.querySelector("textarea").placeholder = bilingual(
    "¿En qué equipo trabajé con el proyecto X la semana pasada?",
    "Which machine did I work on project X last week?",
  );
  const answer = el("div", undefined, "brain-answer");
  answer.setAttribute("aria-live", "polite");
  if (brainFilter.answer) answer.append(...brainFilter.answer);
  const body = () => ({
    message: question.querySelector("textarea").value.trim(),
    machine_id: machine,
    project: brainFilter.project,
    days,
    language: locale === "es" ? "es" : "en",
  });
  const need = () => {
    if (!body().message)
      throw Error(bilingual("Escribe una pregunta", "Write a question"));
  };
  form.append(
    question,
    actions(
      button(
        bilingual("Preguntar", "Ask"),
        async () => {
          need();
          answer.replaceChildren(el("p", bilingual("Consultando al modelo…", "Asking the model…")));
          try {
            const result = await api("/api/brain/ask", body(), "POST", 300000);
            const text = el("pre", result.answer);
            const used = el(
              "p",
              bilingual("Registros enviados: ", "Records sent: ") +
                Object.entries(result.records)
                  .filter(([, n]) => n)
                  .map(([k, n]) => n + " " + k.replace(/_/g, " "))
                  .join(", ") +
                (result.truncated
                  ? bilingual(" (recortado al límite)", " (cut to the limit)")
                  : ""),
              "hint",
            );
            brainFilter.answer = [text, used];
            answer.replaceChildren(text, used);
          } catch (e) {
            brainFilter.answer = null;
            answer.replaceChildren();
            throw e;
          }
        },
        "primary",
      ),
      button(bilingual("Ver qué se enviaría", "See what would be sent"), async () => {
        need();
        const preview = await api("/api/brain/context", body());
        const box = el("div");
        box.append(
          el(
            "p",
            bilingual(
              `Esto es todo lo que recibiría el modelo ${preview.model} (${preview.bytes} bytes):`,
              `This is everything the model ${preview.model} would receive (${preview.bytes} bytes):`,
            ),
          ),
          el("pre", JSON.stringify(preview.payload, null, 2)),
        );
        modal(bilingual("Contenido de la consulta", "Question content"), box);
      }),
    ),
  );
  form.onsubmit = (e) => e.preventDefault();
  ask.append(form, answer);
  root.append(ask);

  // --- where work happened -------------------------------------------------
  const where = panel(bilingual("Dónde se ha trabajado", "Where work happened"));
  where.append(
    el(
      "p",
      bilingual(
        "Una fila por proyecto y equipo. El proyecto es el repositorio git donde se ejecutó la orden; fuera de un repositorio se muestra el directorio.",
        "One row per project and machine. The project is the git repository the command ran in; outside a repository the directory is shown.",
      ),
    ),
  );
  where.append(
    table(
      [
        bilingual("Proyecto o directorio", "Project or directory"),
        bilingual("Equipo", "Machine"),
        bilingual("Órdenes", "Commands"),
        bilingual("Primera", "First"),
        bilingual("Última", "Last"),
      ],
      projects.projects.map((p) => [
        button(p.label, () => {
          brainFilter.project = p.label;
          brainFilter.query = "";
          render();
        }),
        machineName(p.machine_id),
        String(p.commands),
        stamp(p.first),
        stamp(p.last),
      ]),
    ),
  );
  root.append(where);

  // --- agent diary -----------------------------------------------------------
  const notes = panel(bilingual("Diario de agentes", "Agent diary"));
  notes.append(
    el(
      "p",
      bilingual(
        "Una nota por sesión de Claude, Codex u otro agente: qué se pidió y cómo acabó. Se actualiza en cada turno, así que una sesión cortada conserva la última. Sigue los mismos filtros que las órdenes.",
        "One note per session of Claude, Codex or another agent: what was asked and how it ended. It is updated at every turn, so a session cut short keeps its last one. It follows the same filters as the commands.",
      ),
    ),
    table(
      [
        bilingual("Cuándo", "When"),
        bilingual("Equipo", "Machine"),
        bilingual("Agente", "Agent"),
        bilingual("Proyecto o directorio", "Project or directory"),
        bilingual("Nota", "Note"),
      ],
      diary.notes.map((n) => [
        stamp(n.observed),
        machineName(n.machine_id),
        n.agent,
        n.project || n.cwd,
        n.text,
      ]),
    ),
  );
  root.append(notes);

  // --- activity --------------------------------------------------------------
  const activity = panel(bilingual("Órdenes ejecutadas", "Commands run"));
  const search = el("form", undefined, "form-grid");
  const text = field("q", bilingual("Buscar en órdenes y directorios", "Search commands and directories"), "text", brainFilter.query);
  search.append(
    text,
    actions(
      button(bilingual("Buscar", "Search"), async () => {
        brainFilter.query = text.querySelector("input").value.trim();
        render();
      }),
      button(bilingual("Quitar filtros", "Clear filters"), async () => {
        brainFilter.query = brainFilter.project = "";
        render();
      }),
    ),
  );
  search.onsubmit = (e) => {
    e.preventDefault();
    brainFilter.query = text.querySelector("input").value.trim();
    render();
  };
  activity.append(search);
  if (brainFilter.project)
    activity.append(
      el("p", bilingual("Proyecto: ", "Project: ") + brainFilter.project, "hint"),
    );
  const commands = await api(
    "/api/brain/activity" + query({ project: brainFilter.project, q: brainFilter.query, limit: 300 }),
  );
  if (!root.isConnected) return;
  activity.append(
    table(
      [
        bilingual("Cuándo", "When"),
        bilingual("Equipo", "Machine"),
        bilingual("Usuario", "User"),
        bilingual("Directorio", "Directory"),
        bilingual("Orden", "Command"),
      ],
      commands.commands.map((c) => [
        stamp(c.observed),
        machineName(c.machine_id),
        c.user,
        c.cwd,
        brainText(el("span"), c.command),
      ]),
    ),
  );
  root.append(activity);

  // --- inventory ---------------------------------------------------------------
  const changed = panel(bilingual("Cambios en lo instalado", "Changes in what is installed"));
  const actionName = {
    added: bilingual("Añadido", "Added"),
    removed: bilingual("Eliminado", "Removed"),
    changed: bilingual("Cambiado", "Changed"),
  };
  const categoryName = {
    system: bilingual("Sistema", "System"),
    packages: bilingual("Paquetes", "Packages"),
    services: bilingual("Servicios", "Services"),
    ports: bilingual("Puertos", "Ports"),
    users: bilingual("Usuarios", "Users"),
  };
  changed.append(
    table(
      [
        bilingual("Cuándo", "When"),
        bilingual("Equipo", "Machine"),
        bilingual("Tipo", "Kind"),
        bilingual("Cambio", "Change"),
        bilingual("Elemento", "Item"),
        bilingual("Antes → después", "Before → after"),
      ],
      changes.changes.map((c) => [
        stamp(c.observed),
        machineName(c.machine_id),
        categoryName[c.category] || c.category,
        actionName[c.action] || c.action,
        c.item,
        [c.before, c.after].filter(Boolean).join(" → "),
      ]),
    ),
  );
  root.append(changed);

  const cards = el("div", undefined, "metric-grid");
  for (const m of machines) {
    const card = panel(m.name);
    card.append(badge(m.config.enabled ? "ok" : "disabled"));
    if (m.error) card.append(el("p", m.error, "monitor-warning"));
    if (m.system.os)
      card.append(el("p", m.system.os + " · " + m.system.kernel));
    card.append(
      el(
        "p",
        bilingual("Último inventario: ", "Last inventory: ") + stamp(m.inventory_observed),
      ),
      el(
        "p",
        Object.entries(m.counts)
          .map(([k, n]) => n + " " + (categoryName[k] || k).toLowerCase())
          .join(" · "),
      ),
      el(
        "p",
        bilingual(
          `Órdenes: ${m.commands_day} hoy, ${m.commands_week} en 7 días · Cambios en 7 días: ${m.changes_week}`,
          `Commands: ${m.commands_day} today, ${m.commands_week} in 7 days · Changes in 7 days: ${m.changes_week}`,
        ),
      ),
    );
    if (m.inventory_errors.length)
      card.append(
        el(
          "p",
          bilingual("No se pudo leer: ", "Could not read: ") + m.inventory_errors.join(", "),
          "monitor-warning",
        ),
      );
    const settings = el("form", undefined, "form-grid");
    const local = m.kind === "local";
    settings.append(
      field("enabled", bilingual("Cerebro activado", "Brain enabled"), "checkbox", m.config.enabled),
      field("activity", bilingual("Guardar órdenes ejecutadas", "Keep commands run"), "checkbox", m.config.activity),
      field("retention_days", bilingual("Conservar (días)", "Keep for (days)"), "number", m.config.retention_days),
    );
    settings.onsubmit = (e) => e.preventDefault();
    const find = field("find", bilingual("Buscar en lo instalado", "Search what is installed"), "text", "");
    const found = el("div");
    card.append(
      settings,
      actions(
        button(bilingual("Guardar", "Save"), async () => {
          const data = formData(settings);
          await api("/api/brain/" + m.machine_id + "/config", {
            enabled: data.enabled,
            activity: data.activity,
            retention_days: data.retention_days,
            mode: local ? "local" : "remote",
          });
          notice(bilingual("Guardado", "Saved"));
          render();
        }, "primary"),
        ...(local
          ? []
          : [
              button(bilingual("Generar token del emisor", "Generate sender token"), async () => {
                if (
                  m.token_configured &&
                  !confirm(
                    bilingual(
                      "El token anterior dejará de funcionar. ¿Continuar?",
                      "The previous token will stop working. Continue?",
                    ),
                  )
                )
                  return;
                const issued = await api("/api/brain/" + m.machine_id + "/token", {});
                const box = el("div");
                box.append(
                  el(
                    "p",
                    bilingual(
                      "Se muestra una sola vez. En el equipo, con el receptor que ya usa su emisor de logs:",
                      "Shown once. On the machine, with the receiver its log sender already uses:",
                    ),
                  ),
                  el(
                    "pre",
                    "LOGSENTINEL_BRAIN_TOKEN=" +
                      issued.token +
                      " logsentinel brain-forward --receiver https://RECEPTOR:8767 --machine-id " +
                      issued.machine_id,
                  ),
                  el(
                    "p",
                    bilingual(
                      "Para guardar también las órdenes, instala el gancho de shell como root: logsentinel brain-hook --install. El README explica los requisitos en la sección Cerebro.",
                      "To keep commands too, install the shell hook as root: logsentinel brain-hook --install. The README lists the requirements under Cerebro.",
                    ),
                  ),
                );
                modal(bilingual("Token del cerebro", "Brain token"), box);
              }),
            ]),
      ),
      find,
      actions(
        button(bilingual("Buscar", "Search"), async () => {
          const result = await api(
            "/api/brain/" + m.machine_id + "/inventory?" +
              new URLSearchParams({ q: find.querySelector("input").value.trim() }),
          );
          found.replaceChildren(
            el(
              "p",
              bilingual(
                `${result.total} coincidencias (se muestran ${result.items.length})`,
                `${result.total} matches (${result.items.length} shown)`,
              ),
              "hint",
            ),
            table(
              [bilingual("Tipo", "Kind"), bilingual("Elemento", "Item"), bilingual("Valor", "Value")],
              result.items.map((i) => [categoryName[i.category] || i.category, i.item, i.value]),
            ),
          );
        }),
      ),
      found,
    );
    cards.append(card);
  }
  const fleet = panel(bilingual("Equipos", "Machines"));
  fleet.append(cards);
  root.append(fleet);
}
