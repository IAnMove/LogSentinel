"use strict";
// Live logs and the per-machine page. The tail starts with the lines already
// stored and then adds what arrives, by asking the portal every two seconds
// for whatever came after the last line it has. The lines live outside the
// view, so the periodic refresh of the page does not empty the tail.
const LIVE_POLL_MS = 2000,
  LIVE_KEPT = 2000;
const liveTails = {};

function liveLine(event, showMachine) {
  const row = el("div", undefined, "live-line");
  if (event.priority !== null && event.priority !== undefined && event.priority <= 3)
    row.classList.add("live-error");
  else if (event.priority === 4) row.classList.add("live-warning");
  const when = event.timestamp ? new Date(event.timestamp) : new Date(event.received * 1000);
  row.append(
    el(
      "span",
      isNaN(when) ? "" : when.toLocaleTimeString(locale === "es" ? "es-ES" : "en-GB"),
      "live-time",
    ),
  );
  if (showMachine) row.append(el("span", machineName(event.machine_id), "live-machine"));
  row.append(el("span", event.service || "", "live-service"), el("span", event.message || "", "live-message"));
  return row;
}

function mountLiveTail(root, machineId = "", sourceId = "") {
  const key = machineId + "|" + sourceId;
  const state = (liveTails[key] ||= { lines: [], position: null, paused: false, filter: "", error: "" });
  const box = panel(bilingual("Logs en vivo", "Live logs"));
  const status = el("span", "", "hint");
  const filter = field("live-filter", bilingual("Filtrar líneas", "Filter lines"), "text", state.filter);
  const screen = el("div", undefined, "live-tail");
  screen.setAttribute("role", "log");
  screen.setAttribute("aria-label", bilingual("Logs en vivo", "Live logs"));
  screen.tabIndex = 0;
  const matches = (event) =>
    !state.filter ||
    ((event.message || "") + " " + (event.service || "")).toLowerCase().includes(state.filter.toLowerCase());
  const draw = () => {
    screen.replaceChildren(...state.lines.filter(matches).map((e) => liveLine(e, !machineId)));
    screen.scrollTop = screen.scrollHeight;
  };
  const describe = () => {
    status.textContent = state.error
      ? state.error
      : state.paused
        ? bilingual("En pausa; las líneas nuevas se mostrarán al reanudar", "Paused; new lines appear when resumed")
        : state.lines.length
          ? bilingual(`${state.lines.length} líneas · siguiendo`, `${state.lines.length} lines · following`)
          : bilingual("Esperando líneas…", "Waiting for lines…");
  };
  filter.querySelector("input").oninput = (e) => {
    state.filter = e.target.value;
    draw();
  };
  const pause = button("", async () => {
    state.paused = !state.paused;
    pause.textContent = state.paused ? bilingual("Reanudar", "Resume") : bilingual("Pausar", "Pause");
    describe();
    if (!state.paused) draw();
  });
  pause.textContent = state.paused ? bilingual("Reanudar", "Resume") : bilingual("Pausar", "Pause");
  box.append(
    filter,
    actions(
      pause,
      button(bilingual("Vaciar pantalla", "Clear screen"), async () => {
        state.lines = [];
        draw();
        describe();
      }),
    ),
    status,
    screen,
  );
  root.append(box);
  draw();
  describe();
  let busy = false;
  async function poll() {
    if (!box.isConnected) return clearInterval(timer);
    // Signed out: asking again every two seconds would only log refusals.
    if (busy || document.hidden || $("#shell").hidden) return;
    busy = true;
    try {
      const params = new URLSearchParams({ limit: state.position === null ? "200" : "500" });
      if (machineId) params.set("machine_id", machineId);
      if (sourceId) params.set("source_id", sourceId);
      if (state.position !== null) params.set("after", state.position);
      const result = await api("/api/live?" + params);
      state.error = "";
      // Leaving a view and returning can leave two polls asking from the same
      // position; a line already on screen is not added again.
      const last = state.lines.length ? state.lines[state.lines.length - 1].position : -1;
      result.events = result.events.filter((e) => e.position > last);
      state.position = Math.max(state.position ?? 0, result.position);
      if (result.events.length) {
        state.lines.push(...result.events);
        if (state.lines.length > LIVE_KEPT) state.lines.splice(0, state.lines.length - LIVE_KEPT);
        if (!state.paused && box.isConnected) {
          // Follow the end only if the reader is already there; someone who
          // scrolled up to read is not dragged back down.
          const atEnd = screen.scrollHeight - screen.scrollTop - screen.clientHeight < 40;
          const fresh = result.events.filter(matches).map((e) => liveLine(e, !machineId));
          screen.append(...fresh);
          while (screen.childElementCount > LIVE_KEPT) screen.firstChild.remove();
          if (atEnd) screen.scrollTop = screen.scrollHeight;
        }
      }
    } catch (e) {
      state.error = e.message;
    } finally {
      busy = false;
      if (box.isConnected) describe();
    }
  }
  const timer = setInterval(poll, LIVE_POLL_MS);
  poll();
  return box;
}

async function liveView(root) {
  const intro = panel(bilingual("Todos los equipos, según llega", "Every machine, as it arrives"));
  intro.append(
    el(
      "p",
      bilingual(
        "Las últimas líneas guardadas y las que van llegando de todas las fuentes. Elige un equipo en el selector de ámbito para ver solo el suyo. Ver los logs aquí no consume tokens.",
        "The last stored lines and those arriving from every source. Choose a machine in the scope selector to see only its own. Watching logs here uses no tokens.",
      ),
    ),
  );
  root.append(intro);
  mountLiveTail(root, scope || "");
}

function openMachine(id) {
  scope = id;
  $("#machine-scope").value = id;
  navigate("machine_detail");
}

async function machineDetailView(root) {
  if (!scope) {
    const choose = panel(bilingual("Elige un equipo", "Choose a machine"));
    choose.append(
      table(
        [bilingual("Equipo", "Machine"), bilingual("Dirección", "Address"), bilingual("Sistema", "System"), ""],
        (S.machine || []).map((m) => [
          m.name,
          m.hostname || "—",
          m.os || "—",
          button(bilingual("Abrir ficha", "Open machine page"), () => openMachine(m.id), "primary"),
        ]),
      ),
    );
    root.append(choose);
    return;
  }
  const machine = (S.machine || []).find((m) => m.id === scope);
  if (!machine) return;
  const [problems, brain, projects] = await Promise.all([
    api("/api/problems?machine_id=" + encodeURIComponent(scope) + "&limit=100"),
    api("/api/brain"),
    api("/api/brain/projects?days=30&machine=" + encodeURIComponent(scope)),
  ]);
  if (!root.isConnected) return;
  const memory = brain.machines.find((m) => m.machine_id === scope);

  const identity = panel(machine.name);
  identity.append(badge(machine.monitoring_paused ? "paused" : "ok"));
  const facts = [
    [bilingual("Dirección", "Address"), machine.hostname],
    [bilingual("Sistema", "System"), (memory && memory.system.os) || machine.os],
    ["Kernel", memory && memory.system.kernel],
    [bilingual("Tipo", "Kind"), machine.kind === "local" ? bilingual("Este equipo (central)", "This machine (central)") : bilingual("Remoto", "Remote")],
    [bilingual("Notas", "Notes"), machine.notes],
  ].filter(([, value]) => value);
  identity.append(table([bilingual("Dato", "Fact"), bilingual("Valor", "Value")], facts));
  identity.append(
    actions(
      button(bilingual("Ver métricas", "See metrics"), () => navigate("metrics")),
      button(bilingual("Ver memoria", "See memory"), () => navigate("brain")),
      button(bilingual("Ver histórico", "See history"), () => navigate("events")),
    ),
  );
  root.append(identity);

  const sources = panel(bilingual("Fuentes de logs", "Log sources"));
  sources.append(
    table(
      [
        bilingual("Fuente", "Source"),
        bilingual("Tipo", "Kind"),
        bilingual("Estado", "State"),
        bilingual("Última señal", "Last signal"),
        bilingual("Emisor", "Sender"),
      ],
      (S.source || [])
        .filter((s) => s.machine_id === scope && !["metrics", "health"].includes(s.kind))
        .map((s) => {
          const health = (S.health || {})[s.id] || {};
          const last = health.heartbeat || health.checked;
          return [
            s.name,
            s.kind,
            !s.enabled
              ? bilingual("Desactivada", "Disabled")
              : !last
                ? bilingual("Nunca se ha conectado", "Never connected")
                : health.status === "error"
                  ? health.error || "error"
                  : bilingual("Correcto", "OK"),
            stamp(last),
            (health.sender && health.sender.build) || "—",
          ];
        }),
    ),
  );
  root.append(sources);

  const resources = el("div");
  root.append(resources);
  mountResourceOverview(resources, scope).catch(() => {});

  const open = problems.filter((p) => p.status === "open");
  const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
  open.sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9) || b.last_seen - a.last_seen);
  const trouble = panel(bilingual("Problemas abiertos recientes", "Recent open problems"));
  trouble.append(
    table(
      [bilingual("Gravedad", "Severity"), bilingual("Problema", "Problem"), bilingual("Veces", "Times"), bilingual("Última vez", "Last seen")],
      open.slice(0, 10).map((p) => [badge(p.severity), p.title, String(p.count), stamp(p.last_seen)]),
    ),
    actions(button(bilingual("Ver todos los problemas", "See all problems"), () => navigate("problems"))),
  );
  root.append(trouble);

  const work = panel(bilingual("En qué se ha trabajado (30 días)", "What was worked on (30 days)"));
  if (memory && memory.config.enabled) {
    work.append(
      el(
        "p",
        bilingual(
          `Último inventario: ${stamp(memory.inventory_observed)} · ${memory.counts.packages} paquetes · ${memory.changes_week} cambios en 7 días · ${memory.commands_week} órdenes en 7 días`,
          `Last inventory: ${stamp(memory.inventory_observed)} · ${memory.counts.packages} packages · ${memory.changes_week} changes in 7 days · ${memory.commands_week} commands in 7 days`,
        ),
      ),
      table(
        [bilingual("Proyecto o directorio", "Project or directory"), bilingual("Órdenes", "Commands"), bilingual("Última", "Last")],
        projects.projects.slice(0, 10).map((p) => [p.label, String(p.commands), stamp(p.last)]),
      ),
    );
  } else {
    work.append(
      el(
        "p",
        bilingual(
          "El cerebro no está activado para este equipo. Actívalo en Cerebro para ver inventario y actividad.",
          "The brain is not enabled for this machine. Turn it on in Brain to see inventory and activity.",
        ),
      ),
    );
  }
  root.append(work);

  mountLiveTail(root, scope);
}
