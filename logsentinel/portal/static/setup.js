"use strict";
let setupStep = 0,
  setupMachine = "",
  setupSource = "",
  helpHistory = [],
  monitorDetailsOpen = false;

function statusLabel(key) {
  if (key === "MEDIUM") return locale === "es" ? "Media" : "Medium";
  const labels = {
    LOW: "Baja",
    MEDIUM: "Media",
    HIGH: "Alta",
    CRITICAL: "Crítica",
    open: "Abierto",
    resolved: "Resuelto",
    done: "Completado",
    failed: "Fallido",
    retry: "Reintento pendiente",
    running: "En curso",
    pending: "Pendientes",
    unknown: "Resultado desconocido",
    delivered: "Entregado",
    cancelled: "Cancelado",
    queued: "En cola",
    completed: "Completado",
    interrupted: "Interrumpido",
    partial: "Parcial",
    ok: "Correcto",
    active: "Activo",
    disabled: "Desactivado",
    degraded: "Requiere atención",
    stale: "Sin datos recientes",
    starting: "Iniciando",
    checking: "Comprobando",
    quarantined: "En cuarentena",
  };
  return labels[key] ? t(labels[key]) : coverageLabel(key);
}

function coverageLabel(key) {
  if (key === "queued") return bilingual("Lote en cola", "Batch queued");
  if (key === "oversized") return bilingual("No cabe en el contexto", "Exceeds input budget");
  if (key === "capacity") return bilingual("Histórico pendiente de recuperar", "Historical backlog to recover");
  return t(
    {
      pending: "Pendientes",
      capacity: "Sin revisar por capacidad",
      sampled: "Sin revisar por política",
      excluded: "Excluidos del LLM",
      compact: "Revisados en resumen",
      reviewed: "Originales revisados",
      error: "Error de análisis",
      measured: "Medido por umbral",
    }[key] || key,
  );
}

function monitorTime(value, now) {
  if (!value) return bilingual("Todavía no", "Not yet");
  const delta = value - now, seconds = Math.abs(delta);
  if (seconds >= 86400) return stamp(value);
  if (seconds < 5) return bilingual("ahora", "now");
  const amount = seconds < 60
    ? Math.round(seconds) + " s"
    : seconds < 3600
      ? Math.floor(seconds / 60) + " min"
      : Math.floor(seconds / 3600) + " h " + Math.floor(seconds % 3600 / 60) + " min";
  return delta > 0
    ? bilingual("dentro de ", "in ") + amount
    : bilingual("hace ", "") + amount + bilingual("", " ago");
}

function drawMonitor(m) {
  if (!m) return;
  const root = $("#monitor-status"),
    details = el("div"),
    capture = el("strong");
  const when = (value) => monitorTime(value, m.server_time || Date.now() / 1000);
  const timed = (label, value, className = "subtle") => {
    const line = el("div", label + when(value), className);
    if (value) line.title = stamp(value);
    return line;
  };
  if (m.build) details.append(el("div", "LogSentinel " + m.build.version +
    (m.build.commit ? " · " + m.build.commit.slice(0, 10) : "") +
    (m.build.dirty ? bilingual(" · cambios locales al arrancar", " · local changes at startup") : "") +
    " · " + bilingual("arrancó ", "started ") + when(m.build.started), "subtle"));
  if (!m.enabled_sources) details.append(el("p", bilingual(
    "No hay fuentes de logs activas. Las métricas y comprobaciones de salud no sustituyen la captura de logs.",
    "No log sources are active. Metrics and health checks do not replace log capture."), "monitor-warning"));
  for (const [machine, error] of Object.entries(m.preparation_errors || {})) details.append(el("p", machineName(machine) + ": " + error, "monitor-warning"));
  if (m.detector_error) details.append(el("p", bilingual("Error del detector: ", "Detector error: ") + m.detector_error, "monitor-warning"));
  capture.textContent =
    m.capture === "active"
      ? t("Captura continua activa")
      : m.capture === "starting"
        ? t("Iniciando captura…")
        : m.capture === "delayed"
          ? t("Captura sin confirmación reciente; revisa las fuentes")
          : t("Captura inactiva");
  details.append(
    el(
      "div",
      bilingual("Logs · estado global", "Logs · global status"),
      "subtle",
    ),
    timed(t("Último evento recibido: "), m.last_event),
  );
  const failedSources = Object.values(m.source_health || {}).filter(
    (h) => h.status !== "ok",
  ).length;
  const unknownSources = Object.values(m.source_health || {}).filter(
    (h) => !h.checked,
  ).length;
  details.append(
    capture,
    el("span", " · " + m.enabled_sources + t(" fuentes habilitadas")),
  );
  if (!m.enabled_sources) details.append(el("div", bilingual(
    "No están entrando logs nuevos. El histórico retenido puede seguir analizándose.",
    "No new logs are being captured. Retained history can still be reviewed.",
  ), "subtle"));
  if (failedSources || unknownSources || m.collector_error)
    details.append(
      el(
        "p",
        t("Hay fuentes sin verificar o con errores. Revisa Fuentes."),
        "monitor-warning",
      ),
    );
  const line = m.active_call?.kind === "analysis" || m.active_call?.kind === "investigation"
    ? bilingual("El modelo está revisando logs ahora", "The model is reviewing logs now")
    : !m.analysis_enabled
      ? t("Análisis pausado; la captura continúa en las fuentes activas")
      : !m.background
        ? t("Procesos automáticos desactivados en esta instancia")
        : m.model_busy
          ? t("LLM ocupado; el análisis espera su turno")
          : m.next_analysis
            ? t("Próximo análisis: ") + when(m.next_analysis)
            : m.coverage?.queued
              ? bilingual("La cola espera a que se reanude la monitorización de sus máquinas", "The queue is waiting for its machines to resume monitoring")
              : bilingual("Sin trabajo en cola", "No work queued");
  details.append(el("div", line));
  const coverage = m.coverage;
  if (coverage) {
    const grid = el("div", undefined, "monitor-coverage");
    for (const [key, label] of [
      ["total", bilingual("Logs retenidos", "Retained logs")],
      ["covered", bilingual("Analizados", "Reviewed")],
      ["unreviewed", bilingual("Sin analizar", "Unreviewed")],
      ["queued", bilingual("En cola de análisis", "Queued for analysis")],
    ]) {
      const item = el("div");
      item.append(el("strong", Number(coverage[key] || 0).toLocaleString()), el("span", label));
      grid.append(item);
    }
    details.append(grid, el("div",
      coverage.represented + bilingual(" representados en grupos · ", " represented in groups · ") +
      coverage.originals + bilingual(" originales citados en verificación", " originals cited in verification"), "subtle"));
    if (coverage.fragments?.originals) details.append(el("div",
      coverage.fragments.originals + bilingual(" entradas largas en proceso · ", " long entries in progress · ") +
      coverage.fragments.completed + "/" + coverage.fragments.total + bilingual(" fragmentos analizados; el original cuenta como pendiente hasta completarlos todos", " fragments reviewed; each original remains pending until all its fragments are reviewed")));
    if (coverage.history_remaining || coverage.history_recovered) details.append(el("div",
      bilingual("Recuperación del histórico: ", "History recovery: ") +
      coverage.history_recovered + bilingual(" analizados · ", " reviewed · ") +
      coverage.history_remaining + bilingual(" pendientes", " remaining")));
    const outside = coverage.excluded + coverage.policy + coverage.oversized + Math.max(0, coverage.errors - coverage.retrying);
    if (outside) details.append(el("div",
      bilingual("Sin analizar fuera de la cola: ", "Unreviewed outside the queue: ") +
      coverage.excluded + bilingual(" excluidos por reglas · ", " excluded by rules · ") +
      coverage.policy + bilingual(" por selección de fuente · ", " by source selection · ") +
      coverage.oversized + bilingual(" demasiado grandes · ", " too large · ") +
      Math.max(0, coverage.errors - coverage.retrying) + bilingual(" con reintentos agotados", " with exhausted retries"), "monitor-warning"));
    if (coverage.queued) details.append(el("div", bilingual(
      "La cola forma parte de los logs sin analizar; se procesa por lotes mientras el análisis esté activo.",
      "Queued logs are part of the unreviewed total; batches run while analysis is enabled.",
    ), "subtle"));
  }
  details.append(timed(bilingual("Última llamada al modelo: ", "Last model call: "), m.last_scan_finished));
  if (m.last_scan_status === "error") details.append(el("div", bilingual(
    "La última llamada falló; no cuenta como revisión completada.", "The last call failed; it does not count as a completed review.",
  ), "monitor-warning"));
  if (m.last_review?.finished) details.append(timed(
    bilingual("Último lote analizado: ", "Last reviewed batch: "), m.last_review.finished));
  if (m.next_check && !m.next_analysis) details.append(timed(
    bilingual("Próxima comprobación de cola: ", "Next queue check: "), m.next_check));
  if (m.last_finished && m.last_outcome === "no_events") details.append(timed(
    bilingual("Última comprobación sin trabajo, sin llamar al modelo: ", "Last check with no work and no model call: "), m.last_finished));
  const interval = m.interval_seconds < 60 ? m.interval_seconds + " s" : Math.round(m.interval_seconds / 60) + " min";
  details.append(el("div", (m.adaptive_batching
    ? bilingual("Espera máxima entre lotes: ", "Maximum wait between batches: ")
    : t("Intervalo: ")) + interval, "subtle"));
  if (m.retry_after)
    details.append(
      el(
        "div",
        (locale === "es"
          ? "Reintento tras errores del modelo: "
          : "Retry after model errors: ") + when(m.retry_after),
        "monitor-warning",
      ),
    );
  if (m.failed_jobs)
    details.append(
      el(
        "div",
        m.failed_jobs +
          bilingual(" trabajos pendientes de reintento o verificación, o con errores", " jobs awaiting retry or verification, or with errors"),
        "monitor-warning",
      ),
    );
  if (m.worker_error)
    details.append(el("div", m.worker_error, "monitor-warning"));
  if (m.last_model_error)
    details.append(
      el(
        "div",
        bilingual(
          "Último error registrado del modelo: ",
          "Last recorded model error: ",
        ) +
          (m.last_model_error.error.includes("Timeout")
            ? bilingual(
                "sin respuesta completa dentro de ",
                "no complete response within ",
              ) +
              m.model_timeout_seconds +
              " s"
            : m.last_model_error.error) +
          " · " +
          when(m.last_model_error.updated),
        "subtle",
      ),
    );
  const toggle = button(
    m.analysis_enabled
      ? bilingual("Pausar análisis global", "Pause global analysis")
      : bilingual("Activar análisis global", "Enable global analysis"),
    async () => {
      await api("/api/settings", { enabled: !m.analysis_enabled });
      S = await api("/api/state");
      drawMonitor(S.monitor);
      notice(
        t(
          S.settings.enabled
            ? "Análisis automático activado."
            : "Los próximos análisis quedan pausados. El ciclo en curso puede terminar.",
        ),
      );
    },
  );
  const brief = el("div"),
    more = guideDetails(
      bilingual("Ver detalles del estado global", "Show global status details"),
      details,
    );
  more.open = monitorDetailsOpen;
  more.addEventListener("toggle", () => {
    if (more.isConnected) monitorDetailsOpen = more.open;
  });
  brief.append(
    el(
      "div",
      bilingual(
        "Estado global · todas las máquinas",
        "Global status · all machines",
      ),
      "subtle",
    ),
    capture,
    el("span", " · " + m.enabled_sources + t(" fuentes habilitadas")),
    el("div", line),
  );
  const grid = details.querySelector(".monitor-coverage");
  if (grid) brief.append(grid);
  brief.append(
    timed(t("Último evento recibido: "), m.last_event),
    timed(
      bilingual("Último lote analizado: ", "Last reviewed batch: "),
      m.last_review?.finished,
    ),
  );
  if (m.coverage?.oldest_pending)
    brief.append(
      timed(
        bilingual(
          "El log más antiguo en cola llegó ",
          "Oldest queued log arrived ",
        ),
        m.coverage.oldest_pending,
      ),
    );
  for (const warning of [...details.querySelectorAll(".monitor-warning")])
    brief.append(warning);
  brief.append(more);
  root.replaceChildren(brief, toggle);
  const selectedMachine = S.machine.find((machine) => machine.id === scope);
  if (selectedMachine?.monitoring_paused)
    brief.prepend(
      el(
        "p",
        selectedMachine.name +
          " · " +
          bilingual(
            "monitorización de esta máquina pausada",
            "monitoring for this machine is paused",
          ),
        "monitor-warning",
      ),
    );
}

async function setupView(root) {
  const steps = [
    "Conectar el LLM",
    "Elegir máquina",
    "Conectar logs",
    "Activar y aprender",
  ];
  const stepsNav = el("div", undefined, "setup-steps");
  steps.forEach((label, i) => {
    const b = button(
      `${i + 1}. ${t(label)}`,
      () => {
        setupStep = i;
        render();
      },
      i === setupStep ? "" : "quiet",
    );
    b.setAttribute("aria-current", i === setupStep ? "step" : "false");
    stepsNav.append(b);
  });
  root.append(
    el(
      "p",
      bilingual("Paso ", "Step ") +
        (setupStep + 1) +
        bilingual(
          " de 4 · Primero conectamos el modelo, después los logs y al final comprobamos el resultado.",
          " of 4 · Connect the model, then your logs, then check the result.",
        ),
      "guide-summary",
    ),
    stepsNav,
    el(
      "p",
      t(
        "Cada paso se guarda al continuar. Puedes volver a este asistente desde el menú.",
      ),
    ),
  );
  const p = panel(t(steps[setupStep])),
    f = el("form", undefined, "form-grid"),
    feedback = el("p", "", "wide");
  feedback.setAttribute("role", "status");
  root.append(p);
  const add = (...args) => f.append(field(...args));
  const next = (label, fn) => {
    const submit = el("button", t(label));
    submit.type = "submit";
    f.append(submit, feedback);
    f.onsubmit = async (e) => {
      e.preventDefault();
      submit.disabled = true;
      try {
        await fn(formData(f));
      } catch (error) {
        feedback.textContent = error.message;
        if (setupStep === 0)
          feedback.textContent += bilingual(
            " Comprueba que el servidor está arrancado, la URL es accesible desde LogSentinel y el modelo está instalado. Tus datos siguen en el formulario.",
            " Check that the server is running, its URL is reachable from LogSentinel and the model is installed. Your entries remain in the form.",
          );
        if (setupStep === 2)
          feedback.textContent += bilingual(
            " Comprueba la ruta y los permisos del usuario que ejecuta LogSentinel. Puedes reintentar sin crear otra fuente.",
            " Check the path and permissions of the user running LogSentinel. You can retry without creating another source.",
          );
        feedback.className = "wide monitor-warning";
      } finally {
        submit.disabled = false;
      }
    };
  };
  const advance = async () => {
    S = await api("/api/state");
    setupStep++;
    await render();
    drawMonitor(S.monitor);
  };
  if (setupStep === 0) {
    const c = S.settings;
    p.append(
      el(
        "p",
        t(
          "Empieza por el modelo que leerá los logs y responderá tus preguntas. La prueba usa datos sintéticos y no envía logs.",
        ),
      ),
    );
    const found = el(
      "p",
      t("Buscando servidores LLM en este equipo…"),
      "subtle",
    );
    p.append(found);
    api("/api/discovery")
      .then((d) => {
        if (!found.isConnected) return;
        if (!d.llm?.length) {
          found.textContent = t(
            "No se ha detectado un servidor LLM JSON en 11434, 8081 ni 8080. Configúralo abajo.",
          );
          return;
        }
        found.textContent =
          t("Detectado en este equipo: ") +
          d.llm.map((s) => s.provider + " " + s.base_url).join(", ");
      })
      .catch(() => {
        found.textContent = "";
      });
    llmServerFields(f, c);
    f.elements.namedItem("base_url").required = true;
    f.elements.namedItem("model").required = true;
    p.append(modelConnectionGuide(f));
    add(
      "context_tokens",
      t("Contexto efectivo configurado"),
      "number",
      c.context_tokens,
    );
    add("max_tokens", t("Máximo de salida"), "number", c.llm.max_tokens);
    add(
      "remote_allowed",
      t("Autorizar enviar contexto al servidor remoto configurado"),
      "checkbox",
      c.remote_allowed,
    );
    fieldHelp(
      f,
      "remote_allowed",
      bilingual(
        "Necesario también para otro equipo de tu red local. Los logs seleccionados se enviarán a esa dirección.",
        "Also needed for another computer on your local network. Selected logs will be sent to that address.",
      ),
    );
    fieldHelp(
      f,
      "context_tokens",
      bilingual(
        "Es el tamaño de contexto cargado en el servidor. Si no lo conoces, conserva el valor inicial y compruébalo en Modelo y análisis.",
        "This is the context size loaded on the server. If unsure, keep the initial value and check it in Model and analysis.",
      ),
    );
    const advancedConnection = guideFields(
      f,
      bilingual(
        "Opciones avanzadas de conexión y contexto",
        "Advanced connection and context options",
      ),
      ["provider", "clear_api_key", "context_tokens", "max_tokens"],
    );
    for (const node of [...f.querySelectorAll(".provider-help,.provider-tools,.provider-result")]) advancedConnection.append(node);
    p.append(
      el(
        "p",
        t(
          "Usa el contexto cargado en el servidor. Se reserva espacio para instrucciones y salida; el presupuesto de entrada es conservador. Los ajustes avanzados están en Modelo y análisis.",
        ),
        "subtle",
      ),
    );
    if (S.setup.model_tested)
      p.append(
        el("p", t("La configuración guardada ya pasó la prueba de conexión.")),
      );
    next("Guardar, probar y continuar", async (d) => {
      feedback.textContent = t(
        "Guardando y probando el LLM… Puede tardar hasta el tiempo de espera configurado.",
      );
      await api("/api/settings", llmFormSettings(f, c));
      const r = await api("/api/model/test", {});
      notice(
        t("Conexión verificada en ") + Number(r.seconds).toFixed(1) + " s.",
      );
      await advance();
    });
  } else if (setupStep === 1) {
    setupMachine = setupMachine || S.machine[0]?.id || "";
    add("existing", t("Máquina"), "select", setupMachine, [
      ["", t("Crear una máquina")],
      ...S.machine.map((m) => [m.id, m.name]),
    ]);
    add("name", t("Nombre"), "text", "");
    add("kind", t("Tipo"), "select", "local", [
      ["local", t("Este equipo")],
      ["imported", t("Otro equipo")],
    ]);
    add("hostname", t("Hostname declarado"), "text", "");
    add("os", t("Sistema / distribución"), "text", "");
    const createMachine = el("div", undefined, "form-grid wide");
    for (const name of ["name", "kind", "hostname", "os"])
      createMachine.append(f.elements.namedItem(name).closest("label"));
    f.append(createMachine);
    const optionalMachine = guideFields(
      f,
      bilingual("Datos opcionales del equipo", "Optional computer details"),
      ["hostname", "os"],
    );
    createMachine.append(optionalMachine);
    createMachine.prepend(
      button(t("Detectar este equipo"), async () => {
        const d = await api("/api/discovery");
        for (const [key, value] of Object.entries({
          existing:
            S.machine.find(
              (m) => m.kind === "local" && m.hostname === d.hostname,
            )?.id || "",
          name: d.hostname,
          hostname: d.hostname,
          os: d.os,
          kind: "local",
        }))
          f.elements.namedItem(key).value = value;
        f.refreshSetupFields();
      }),
    );
    const selectedMachine = el("p", "", "wide guide-summary");
    f.insertBefore(selectedMachine, createMachine);
    f.refreshSetupFields = () => {
      const existing = f.elements.namedItem("existing").value;
      createMachine.hidden = !!existing;
      const machine = S.machine.find((m) => m.id === existing);
      selectedMachine.hidden = !machine;
      selectedMachine.textContent = machine
        ? bilingual("Usaremos: ", "Using: ") +
          machine.name +
          " · " +
          (machine.hostname ||
            bilingual("sin hostname declarado", "no hostname declared"))
        : "";
      f.elements.namedItem("name").required = !existing;
    };
    f.elements.namedItem("existing").onchange = f.refreshSetupFields;
    f.refreshSetupFields();
    p.append(
      el(
        "p",
        t(
          "Usa una ficha por máquina, también si los logs llegan desde una carpeta o un emisor remoto. Los campos de creación solo se usan al elegir Crear una máquina.",
        ),
      ),
    );
    next("Guardar y continuar", async (d) => {
      setupMachine =
        d.existing ||
        (
          await api("/api/objects/machine", {
            name: d.name,
            kind: d.kind,
            hostname: d.hostname,
            os: d.os,
            timezone: "UTC",
          })
        ).id;
      await advance();
    });
  } else if (setupStep === 2) {
    setupMachine = setupMachine || S.machine[0]?.id || "";
    if (!setupMachine) {
      p.append(el("p", t("Crea una máquina en el paso anterior.")));
      return;
    }
    const sources = S.source.filter(
      (s) =>
        s.machine_id === setupMachine &&
        !["metrics", "health"].includes(s.kind),
    );
    const current = sources.find((s) => s.id === setupSource) || sources[0];
    setupSource = current?.id || "";
    add("existing", t("Fuente"), "select", setupSource, [
      ["", t("Crear una fuente")],
      ...sources.map((s) => [s.id, s.name]),
    ]);
    add("name", t("Nombre"), "text", "System logs");
    const local =
      S.machine.find((m) => m.id === setupMachine)?.kind === "local";
    add("kind", t("Tipo de fuente"), "select", local ? "journald" : "push", [
      ...(local ? [["journald", t("Journal local")]] : []),
      ["file", t("Archivo")],
      ["folder", t("Carpeta")],
      ["push", t("Recepción remota")],
    ]);
    add("path", t("Ruta (archivo o carpeta)"), "text", "");
    add("pattern", t("Patrón de archivos en carpeta"), "text", "*.log*");
    add("history", t("Importar histórico al iniciar"), "checkbox", false);
    add("analysis_mode", t("Selección para el análisis LLM"), "select", "all", [
      ["all", t("Todas las líneas")],
      ["priority", t("Prioridad + palabras")],
      ["keywords", t("Solo palabras disparadoras")],
    ]);
    const createSource = el("div", undefined, "form-grid wide"),
      sourceGuide = el("div", undefined, "wide");
    for (const name of [
      "name",
      "kind",
      "path",
      "pattern",
      "history",
      "analysis_mode",
    ])
      createSource.append(f.elements.namedItem(name).closest("label"));
    f.append(createSource);
    const sourceOptions = guideFields(
      f,
      bilingual(
        "Histórico y selección de líneas (opcional)",
        "History and line selection (optional)",
      ),
      ["history", "analysis_mode"],
    );
    createSource.append(sourceOptions);
    f.append(sourceGuide);
    fieldHelp(
      f,
      "history",
      bilingual(
        "Desactivado: empieza con las nuevas llegadas. Activado: añade también el histórico disponible; puede llenar la cola al principio.",
        "Off: start with new arrivals. On: also import available history; this can create an initial backlog.",
      ),
    );
    fieldHelp(
      f,
      "analysis_mode",
      bilingual(
        "Empieza con todas las líneas. La compactación ya agrupa repeticiones sin excluir todo INFO o Python. Los otros modos dejan líneas sin revisión LLM.",
        "Start with all lines. Compaction already groups repetitions without excluding all INFO or Python. Other modes leave lines without LLM review.",
      ),
    );
    const path = f.elements.namedItem("path");
    f.refreshSetupFields = () => {
      const existing = sources.find(
        (s) => s.id === f.elements.namedItem("existing").value,
      );
      createSource.hidden = !!f.elements.namedItem("existing").value;
      const kind = existing?.kind || f.elements.namedItem("kind").value;
      path.disabled = !!existing || !["file", "folder"].includes(kind);
      path.required = !path.disabled;
      path.closest("label").hidden = path.disabled;
      f.elements.namedItem("name").required = !createSource.hidden;
      f.elements.namedItem("pattern").closest("label").hidden =
        kind !== "folder";
      sourceGuide.replaceChildren();
      if (existing)
        sourceGuide.append(
          el(
            "p",
            bilingual(
              "Se activará la fuente guardada: ",
              "The saved source will be enabled: ",
            ) +
              existing.name +
              " · " +
              (existing.path || existing.kind),
            "guide-summary",
          ),
        );
      const steps =
        kind === "journald"
          ? [
              bilingual(
                "Journal es el registro del sistema de este equipo. No necesita una ruta.",
                "Journal is this computer’s system log. It needs no path.",
              ),
              bilingual(
                "Pulsa «Activar fuente y comprobar lectura». Si faltan permisos, el usuario del servicio necesita acceso al journal; no es necesario ejecutar todo el portal como root.",
                "Select “Enable source and test reading”. If permission is denied, the service user needs journal access; the whole portal does not need to run as root.",
              ),
            ]
          : kind === "push"
            ? [
                bilingual(
                  "Esta fuente recibirá logs enviados por otro equipo. Crear la ficha no instala el emisor ni confirma recepción.",
                  "This source will receive logs sent by another computer. Creating it does not install a sender or confirm reception.",
                ),
                bilingual(
                  "Continúa para guardar la fuente. En el último paso encontrarás las instrucciones de alta del emisor y dónde comprobar que llega su primer log.",
                  "Continue to save the source. The last step explains sender enrollment and where to check for its first log.",
                ),
              ]
            : [
                bilingual(
                  "La ruta pertenece al equipo donde corre LogSentinel, aunque abras el navegador en otro ordenador.",
                  "The path belongs to the computer running LogSentinel, even if your browser is on another computer.",
                ),
                kind === "folder"
                  ? bilingual(
                      "Escribe una carpeta, por ejemplo /var/log/mi-app, y el patrón de sus archivos, por ejemplo *.log. Comprueba que el usuario del servicio puede leerlos.",
                      "Enter a folder, such as /var/log/my-app, and its filename pattern, such as *.log. Check that the service user can read them.",
                    )
                  : bilingual(
                      "Escribe la ruta completa de un log, por ejemplo /var/log/mi-app/app.log. Debe ser legible por el usuario del servicio.",
                      "Enter a log’s full path, such as /var/log/my-app/app.log. The service user must be able to read it.",
                    ),
              ];
      sourceGuide.append(
        howTo(
          bilingual("Cómo conectar esta fuente", "How to connect this source"),
          steps,
        ),
      );
    };
    f.elements.namedItem("kind").onchange = f.refreshSetupFields;
    f.elements.namedItem("existing").onchange = f.refreshSetupFields;
    f.refreshSetupFields();
    next("Activar fuente y comprobar lectura", async (d) => {
      if (!d.existing && ["file", "folder"].includes(d.kind) && !d.path.startsWith("/"))
        throw Error(bilingual("Escribe una ruta absoluta que empiece por /, en el equipo donde corre LogSentinel.", "Enter an absolute path starting with /, on the computer running LogSentinel."));
      feedback.textContent = t("Comprobando lectura…");
      const source = await api(
        "/api/objects/source",
        d.existing
          ? { id: d.existing, enabled: true }
          : {
              machine_id: setupMachine,
              name: d.name,
              kind: d.kind,
              path: ["file", "folder"].includes(d.kind) ? d.path : "",
              pattern: d.pattern,
              history: d.history,
              analysis_mode: d.analysis_mode,
              enabled: true,
            },
      );
      setupSource = source.id;
      if (!sources.some((s) => s.id === source.id)) sources.push(source);
      // Remember the created source before testing; retries don't duplicate it.
      const opt = el("option", source.name);
      opt.value = source.id;
      f.elements.namedItem("existing").append(opt);
      f.elements.namedItem("existing").value = source.id;
      f.refreshSetupFields();
      if (source.kind !== "push") {
        const r = await api("/api/source/" + source.id + "/poll", {});
        if (r.health.status !== "ok")
          throw Error(r.health.error || t("No se pudo leer la fuente."));
      }
      await advance();
    });
  } else {
    const review = el("div", undefined, "guide-summary");
    const selected = S.source.find((s) => s.id === setupSource);
    const sourceHealth = selected ? S.health[selected.id] : null;
    review.append(
      el(
        "p",
        bilingual("Modelo: ", "Model: ") +
          S.settings.llm.model +
          (S.setup.model_tested
            ? bilingual(" · conexión comprobada", " · connection checked")
            : bilingual(
                " · falta probar la conexión",
                " · connection test needed",
              )),
      ),
      el("p", bilingual("Equipo: ", "Computer: ") + machineName(setupMachine)),
      el(
        "p",
        bilingual("Logs: ", "Logs: ") +
          (selected?.name ||
            bilingual(
              "revisa tus fuentes activas",
              "check your active sources",
            )) +
          (sourceHealth?.status === "ok"
            ? bilingual(" · lectura comprobada", " · reading checked")
            : ""),
      ),
    );
    p.append(review);
    add(
      "interval_seconds",
      t("Intervalo entre ciclos (segundos)"),
      "number",
      S.settings.interval_seconds,
    );
    add(
      "language",
      t("Idioma de nuevos hallazgos"),
      "select",
      S.setup.completed ? S.settings.language : locale,
      [
        ["en", "English"],
        ["es", "Español"],
      ],
    );
    fieldHelp(
      f,
      "interval_seconds",
      bilingual(
        "Empieza con 30–60 segundos. La captura continúa entre análisis. Con el ajuste automático, los lotes se adaptan al tiempo medido.",
        "Start with 30–60 seconds. Capture continues between reviews. Automatic tuning adapts batches to measured time.",
      ),
    );
    p.append(
      el(
        "p",
        t(
          "Las fuentes activas se leen continuamente, aproximadamente cada 2 segundos más el tiempo de lectura. El LLM revisa lotes en el intervalo elegido. No necesitas pulsar Analizar ahora ni dejar abierto el portal.",
        ),
      ),
    );
    p.append(
      el(
        "p",
        t(
          "Si llegan más logs de los que admite el modelo, los originales se guardan según la retención y se muestra la cobertura perdida. Aumentar el contexto sin comprobar el modelo no garantiza más capacidad.",
        ),
      ),
    );
    if (S.source.some((s) => s.enabled && s.kind === "push"))
      p.append(
        el(
          "p",
          t(
            "Las fuentes remotas necesitan configurar su emisor y clave desde Fuentes. Una fuente habilitada no confirma que estén llegando logs.",
          ),
          "monitor-warning",
        ),
      );
    if (!S.destination.some((d) => d.enabled))
      p.append(
        el(
          "p",
          t(
            "No hay notificaciones activas. Los hallazgos aparecerán en el portal; puedes configurar avisos después.",
          ),
        ),
      );
    if (selected?.kind === "push") p.append(senderSetupGuide(selected));
    next("Terminar y activar análisis automático", async (d) => {
      await api("/api/settings", d);
      await api("/api/setup/complete", {});
      sessionStorage.setItem("setup-dismissed", "1");
      view = "summary";
      await refresh();
      notice(
        bilingual(
          "Configuración guardada y análisis activado. Comprueba la primera llegada y el primer lote en Cobertura y capacidad.",
          "Configuration saved and analysis enabled. Check the first arrival and first batch in Coverage and capacity.",
        ),
      );
    });
    root.append(quickStartMap());
  }
  if (setupStep > 0)
    f.append(
      button(
        bilingual("Volver al paso anterior", "Back to previous step"),
        async () => {
          setupStep--;
          await render();
        },
      ),
    );
  p.append(f);
}

function senderSetupGuide(source) {
  const details = guideDetails(
    bilingual(
      "Conectar el emisor remoto: pasos pendientes",
      "Connect the remote sender: remaining steps",
    ),
  );
  details.append(
    howTo(
      bilingual(
        "En el central y en el cliente",
        "On the central and client computers",
      ),
      [
        bilingual(
          "En el central, comprueba que el listener de recepción está arrancado y que el cliente puede alcanzar su dirección HTTPS. Es una dirección distinta de la del portal.",
          "On the central, check that the ingest listener is running and that the client can reach its HTTPS address. This is separate from the portal address.",
        ),
        bilingual(
          "Genera el paquete de alta en la terminal del central. Sustituye las rutas y CENTRAL por tus valores; --data-dir debe señalar los datos de este portal. El paquete HTTPS necesita el certificado de confianza con --ca-cert, nunca la clave privada.",
          "Generate the enrollment package in the central’s terminal. Replace paths and CENTRAL with your values; --data-dir must point to this portal’s data. The HTTPS package needs its trusted certificate with --ca-cert, never the private key.",
        ),
      ],
    ),
    el(
      "pre",
      "logsentinel enrollment-package --source-id " +
        source.id +
        " --receiver https://CENTRAL:8767 --ca-cert /RUTA/ca.pem --data-dir /RUTA/DEL/PORTAL --out cliente.json",
    ),
    howTo(bilingual("Después", "Then"), [
      bilingual(
        "Lleva cliente.json al cliente por un canal de confianza. Allí, con LogSentinel instalado, ejecuta el comando de alta y sigue la instrucción que imprime para enviar el archivo de logs.",
        "Transfer cliente.json to the client through a trusted channel. With LogSentinel installed there, run enrollment and follow its printed instruction to forward your log file.",
      ),
      bilingual(
        "Vuelve a Histórico y selecciona esta máquina. El primer evento recibido confirma el envío. En Cobertura y capacidad podrás seguir su análisis.",
        "Return to History and select this computer. The first received event confirms delivery. Follow its review in Coverage and capacity.",
      ),
    ]),
    el(
      "pre",
      "logsentinel enroll cliente.json --spool ~/.local/share/logsentinel/sender",
    ),
  );
  return details;
}

function initHelp() {
  $("#help-toggle").onclick = () => {
    $("#help-status").textContent = S.setup?.model_tested
      ? ""
      : t(
          "Configura y prueba el LLM en el primer paso del asistente. Si el monitor está analizando, espera a que termine para consultar.",
        );
    $("#help-dialog").showModal();
    $("#help-question").focus();
  };
  $("#help-close").onclick = () => $("#help-dialog").close();
  $("#help-form").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#help-question").value.trim();
    if (!q) return;
    $("#help-send").disabled = true;
    $("#help-status").textContent = t("Consultando el LLM…");
    try {
      const r = await api("/api/help", {
        message: q,
        language: locale,
        history: helpHistory.slice(-2),
      });
      $("#help-conversation").append(
        el("div", q, "message"),
        el("div", r.answer, "message"),
      );
      helpHistory.push({
        question: q.slice(0, 1000),
        answer: r.answer.slice(0, 1000),
      });
      helpHistory = helpHistory.slice(-2);
      $("#help-question").value = "";
      $("#help-status").textContent = "";
      $("#help-conversation").lastElementChild.scrollIntoView({
        block: "nearest",
      });
    } catch (error) {
      $("#help-status").textContent = error.message;
    } finally {
      $("#help-send").disabled = false;
    }
  };
}
