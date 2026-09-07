"use strict";
let setupStep = 0,
  setupMachine = "",
  setupSource = "",
  helpHistory = [];

function statusLabel(key) {
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
  };
  return labels[key] ? t(labels[key]) : coverageLabel(key);
}

function coverageLabel(key) {
  return t(
    {
      pending: "Pendientes",
      capacity: "Sin revisar por capacidad",
      sampled: "Sin revisar por política",
      excluded: "Excluidos del LLM",
      compact: "Revisados en resumen",
      reviewed: "Originales revisados",
      error: "Error de análisis",
    }[key] || key,
  );
}

function drawMonitor(m) {
  if (!m) return;
  const root = $("#monitor-status"),
    details = el("div"),
    capture = el("strong");
  capture.textContent =
    m.capture === "active"
      ? t("Captura continua activa")
      : m.capture === "starting"
        ? t("Iniciando captura…")
        : m.capture === "delayed"
          ? t("Captura sin confirmación reciente; revisa las fuentes")
          : t("Captura inactiva");
  details.append(
    el("div", t("Último evento recibido: ") + stamp(m.last_event), "subtle"),
  );
  const failedSources = Object.values(m.source_health).filter(
    (h) => h.status !== "ok",
  ).length;
  const unknownSources = Object.values(m.source_health).filter(
    (h) => !h.checked,
  ).length;
  details.append(
    capture,
    el("span", " · " + m.enabled_sources + t(" fuentes habilitadas")),
  );
  if (failedSources || unknownSources || m.collector_error)
    details.append(
      el(
        "p",
        t("Hay fuentes sin verificar o con errores. Revisa Fuentes."),
        "monitor-warning",
      ),
    );
  const line = m.analysis_running
    ? t("El LLM está analizando ahora")
    : !m.analysis_enabled
      ? t("Análisis pausado; la captura continúa en las fuentes activas")
      : !m.background
        ? t("Procesos automáticos desactivados en esta instancia")
        : m.model_busy
          ? t("LLM ocupado; el análisis espera su turno")
          : t("Próximo análisis: ") + stamp(m.next_analysis);
  details.append(
    el("div", line),
    el(
      "div",
      t("Intervalo: ") +
        m.interval_seconds +
        t(" segundos · Pendientes: ") +
        m.pending,
    ),
  );
  if (m.last_finished)
    details.append(
      el(
        "div",
        t("Último ciclo: ") +
          stamp(m.last_finished) +
          " · " +
          t(
            {
              completed: "Completado",
              no_events: "Sin nuevos eventos seleccionados",
              errors: "Con errores",
              interrupted: "Interrumpido",
            }[m.last_outcome] || "—",
          ),
        "subtle",
      ),
    );
  if (m.failed_jobs || m.capacity)
    details.append(
      el(
        "div",
        m.failed_jobs +
          t(" análisis con errores · ") +
          m.capacity +
          t(" eventos sin revisar por capacidad"),
        "monitor-warning",
      ),
    );
  if (m.worker_error)
    details.append(el("div", m.worker_error, "monitor-warning"));
  const toggle = button(
    m.analysis_enabled
      ? t("Pausar análisis")
      : t("Activar análisis automático"),
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
  root.replaceChildren(details, toggle);
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
    add("provider", t("Proveedor"), "select", c.llm.provider, [
      ["ollama", "Ollama"],
      ["openai", t("API compatible")],
    ]);
    add("base_url", t("URL del servidor"), "url", c.llm.base_url);
    add("model", t("Modelo"), "text", c.llm.model);
    add("api_key", t("Clave API (vacío conserva)"), "password");
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
      await api("/api/settings", {
        llm: {
          provider: d.provider,
          base_url: d.base_url,
          model: d.model,
          api_key: d.api_key,
          max_tokens: d.max_tokens,
        },
        context_tokens: d.context_tokens,
        input_budget: Math.max(
          512,
          Math.min(c.input_budget, d.context_tokens - d.max_tokens - 2048),
        ),
        remote_allowed: d.remote_allowed,
      });
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
    f.append(
      button(t("Detectar este equipo"), async () => {
        const d = await api("/api/discovery");
        for (const [key, value] of Object.entries({
          existing: "",
          name: d.hostname,
          hostname: d.hostname,
          os: d.os,
          kind: "local",
        }))
          f.elements.namedItem(key).value = value;
      }),
    );
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
    const sources = S.source.filter((s) => s.machine_id === setupMachine);
    const current = sources.find((s) => s.id === setupSource) || sources[0];
    setupSource = current?.id || "";
    add("existing", t("Fuente"), "select", setupSource, [
      ["", t("Crear una fuente")],
      ...sources.map((s) => [s.id, s.name]),
    ]);
    add("name", t("Nombre"), "text", "System logs");
    const local =
      S.machine.find((m) => m.id === setupMachine)?.kind === "local";
    add("kind", t("Tipo de fuente"), "select", local ? "journald" : "folder", [
      ["journald", t("Journal local")],
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
    p.append(
      el(
        "p",
        t(
          "Journal no necesita ruta: se consulta con journalctl y los permisos del servicio. Para archivos y carpetas usa una ruta absoluta en el servidor. Importar histórico puede traer todos los registros disponibles, no solo los últimos minutos.",
        ),
      ),
    );
    p.append(
      el(
        "p",
        t(
          "La captura conserva también los INFO. Prioridad + palabras reduce lo enviado al LLM, con menor cobertura. La fuente existente conserva su política. Los campos de creación solo se usan al elegir Crear una fuente.",
        ),
        "subtle",
      ),
    );
    const path = f.elements.namedItem("path");
    const updatePath = () => {
      path.disabled = !["file", "folder"].includes(
        f.elements.namedItem("kind").value,
      );
    };
    f.elements.namedItem("kind").onchange = updatePath;
    updatePath();
    next("Activar fuente y comprobar lectura", async (d) => {
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
      // Remember the created source before testing; retries don't duplicate it.
      const opt = el("option", source.name);
      opt.value = source.id;
      f.elements.namedItem("existing").append(opt);
      f.elements.namedItem("existing").value = source.id;
      if (source.kind !== "push") {
        const r = await api("/api/source/" + source.id + "/poll", {});
        if (r.health.status !== "ok")
          throw Error(r.health.error || t("No se pudo leer la fuente."));
      }
      await advance();
    });
  } else {
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
    p.append(
      el(
        "p",
        t(
          "En Problemas puedes ver evidencia, copiar un prompt y silenciar notificaciones. En Reglas puedes previsualizar filtros. En Notificaciones configura y prueba el destino que prefieras.",
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
    next("Terminar y activar análisis automático", async (d) => {
      await api("/api/settings", d);
      await api("/api/setup/complete", {});
      sessionStorage.setItem("setup-dismissed", "1");
      view = "summary";
      await refresh();
      notice(
        t(
          "Configuración terminada. La captura y el análisis automático están activados.",
        ),
      );
    });
  }
  p.append(f);
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
