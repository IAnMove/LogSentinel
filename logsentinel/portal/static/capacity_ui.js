"use strict";
const coverageNumber = (n, digits = 0) =>
  Number(n || 0).toLocaleString(locale === "es" ? "es-ES" : "en-GB", {
    maximumFractionDigits: digits,
  });
function openCapacity(machine = scope) {
  if ($("#modal").open) $("#modal").close();
  scope = machine;
  $("#machine-scope").value = scope;
  navigate("capacity");
}
function coverageWindow(data, title) {
  const card = panel(title);
  card.append(el("p", stamp(data.start) + " → " + stamp(data.end), "subtle"));
  const grid = el("div", undefined, "coverage-grid"),
    bar = el("div", undefined, "coverage-bar");
  const items = [
    ["reviewed", bilingual("Revisados por el LLM", "Reviewed by the LLM")],
    ["pending", bilingual("Pendientes de revisión", "Waiting for review")],
    ["capacity", bilingual("Histórico en cola", "Historical backlog")],
    ["queued", bilingual("En lote pendiente", "In a queued batch")],
    ["oversized", bilingual("No caben en el contexto", "Exceed input budget")],
    [
      "policy",
      bilingual("No seleccionados por política", "Not selected by policy"),
    ],
    ["excluded", bilingual("Excluidos por reglas", "Excluded by rules")],
    ["error", bilingual("Error de análisis", "Analysis error")],
    ["other", bilingual("Otro estado", "Other status")],
  ];
  for (const [key, label] of items) {
    if (key === "other" && !data[key]) continue;
    const item = el("div", undefined, "coverage-stat " + key);
    item.append(el("strong", coverageNumber(data[key])), el("span", label));
    grid.append(item);
    if (data[key] && data.events) {
      const part = el("span", undefined, key);
      part.style.width = (100 * data[key]) / data.events + "%";
      part.title = label + ": " + coverageNumber(data[key]);
      bar.append(part);
    }
  }
  bar.setAttribute("aria-hidden", "true");
  card.append(
    el(
      "p",
      coverageNumber(data.events) +
        bilingual(" eventos recibidos · ", " events received · ") +
        coverageNumber(data.incoming_per_minute, 1) +
        bilingual(" recibidos/min · ", " received/min · ") +
        coverageNumber(data.covered_per_minute, 1) +
        bilingual(" revisados/min", " reviewed/min"),
    ),
    bar,
    grid,
  );
  card.append(
    el(
      "p",
      bilingual(
        "Revisados incluye grupos de mensajes repetidos; no significa que se haya leído cada original ni garantiza seguridad. Todos los contadores corresponden a eventos recibidos en el periodo indicado y aún retenidos.",
        "Reviewed includes groups of repeated messages; it does not mean every original was read or guarantee safety. All counts refer to events received in the stated period and still retained.",
      ),
      "subtle",
    ),
  );
  return card;
}
function capacityProblemHint(p) {
  const card = panel(
    bilingual(
      "Este aviso habla de cobertura",
      "This finding describes coverage",
    ),
  );
  card.append(
    el(
      "p",
      coverageNumber(p.count) +
        bilingual(
          " es el número de eventos enlazados como evidencia (la muestra inicial está limitada a 100). No indica cuántos logs procesa el modelo. El aviso puede seguir abierto aunque la cobertura actual haya mejorado.",
          " is the number of linked evidence events (the initial sample is limited to 100). It is not the model's processing capacity. This finding can remain open after current coverage improves.",
        ),
    ),
    button(t("Cobertura y capacidad"), () => openCapacity(p.machine_id)),
  );
  return card;
}

function capacityDiagnosis(r) {
  const b = bilingual,
    capture = r.capture;
  if (capture && !capture.active_sources)
    return {
      level: "warn",
      title: capture.enabled_sources
        ? b(
            "La máquina tiene la monitorización pausada",
            "Machine monitoring is paused",
          )
        : b("No hay fuentes de logs activas", "No log sources are active"),
      detail: b(
        "Las métricas no son logs. Activa una fuente o reanuda la máquina y comprueba la primera llegada.",
        "Metrics are not logs. Enable a source or resume the machine, then check the first arrival.",
      ),
      page: capture.enabled_sources ? "machine" : "source",
      action: b("Revisar la captura", "Check capture"),
    };
  if (!r.limits.enabled)
    return {
      level: "warn",
      title: b("El análisis está pausado", "Analysis is paused"),
      detail: b(
        "Los logs pueden seguir llegando. Activa el análisis para que la cola avance.",
        "Logs can keep arriving. Enable analysis to process the queue.",
      ),
      page: "settings",
      action: b("Activar desde los ajustes", "Enable in settings"),
    };
  if (r.signal.reason === "review_blocked" || r.analysis.errors)
    return {
      level: "warn",
      title: b(
        "Hay análisis que necesitan atención",
        "Some reviews need attention",
      ),
      detail: b(
        "Comprueba el último error y los reintentos antes de aumentar los lotes. Los eventos sin completar siguen sin analizar.",
        "Check the latest error and retries before increasing batches. Unfinished events remain unreviewed.",
      ),
      page: "activity",
      action: b("Ver errores y reintentos", "See errors and retries"),
    };
  if (r.latency?.loading_dominates)
    return {
      level: "warn",
      title: b(
        "El servidor dedica más tiempo a cargar el modelo",
        "The server spends more time loading the model",
      ),
      detail: b(
        "La carga supera la mitad del tiempo de las llamadas medidas. Comprueba si otra aplicación cambia de modelo o consume su memoria. Reducir el intervalo no elimina esa espera.",
        "Loading exceeds half the measured call time. Check whether another application switches models or consumes memory. A shorter interval does not remove this wait.",
      ),
      page: "settings",
      action: b("Revisar el servidor y modelo", "Check server and model"),
    };
  if (r.signal.level !== "ok")
    return {
      level: r.signal.level,
      title: b(
        "Se acumulan logs sin analizar",
        "Unreviewed logs are building up",
      ),
      detail: b(
        "Mira los servicios con más volumen. Prueba primero el ajuste automático y los filtros concretos; compara varios lotes antes de cambiar otra cosa.",
        "Check the busiest services. Try automatic tuning and specific filters first; compare several batches before changing anything else.",
      ),
      page: "settings",
      action: b("Ver perfiles de ajuste", "See tuning profiles"),
    };
  if (!r.events)
    return {
      level: "warn",
      title: b(
        "Todavía no hay logs recientes para medir",
        "No recent logs to measure yet",
      ),
      detail: b(
        "Una fuente activada no demuestra que esté enviando. Comprueba su lectura y la fecha del último evento. El histórico puede seguir procesándose.",
        "An enabled source does not prove delivery. Check its reading and last event time. History can still be processed.",
      ),
      page: "source",
      action: b("Comprobar fuentes", "Check sources"),
    };
  if (!r.planning.ready)
    return {
      level: "neutral",
      title: b(
        "Estamos midiendo esta configuración",
        "Measuring these settings",
      ),
      detail: b(
        "Hay logs, pero faltan lotes completos para estimar capacidad. Deja terminar varios antes de ajustar. Una prueba de conexión solo comprueba que el modelo responde.",
        "Logs are available, but more completed batches are needed to estimate capacity. Let several finish before tuning. A connection test only checks that the model responds.",
      ),
      page: "events",
      action: b("Ver los logs recibidos", "See received logs"),
    };
  return {
    level: "ok",
    title: b("La cola reciente va al día", "The recent queue is keeping up"),
    detail: b(
      "Esto describe los logs seleccionados. Los apartados por reglas o selección siguen sin análisis LLM; revísalos en los contadores.",
      "This describes selected logs. Logs left out by rules or selection remain unreviewed by the LLM; check their counters.",
    ),
    page: "rule",
    action: b("Revisar filtros activos", "Check active filters"),
  };
}

function tuningSummary(r) {
  const box = panel(
      bilingual(
        "Qué está pasando y qué hacer",
        "What is happening and what to do",
      ),
    ),
    diagnosis = capacityDiagnosis(r);
  box.classList.add("tuning-summary");
  box.append(
    el("strong", diagnosis.title, "coverage-signal " + diagnosis.level),
    el("p", diagnosis.detail),
    button(diagnosis.action, () => navigate(diagnosis.page)),
  );
  const history = r.retained;
  if (history) {
    const grid = el("div", undefined, "monitor-coverage");
    for (const [label, value] of [
      [bilingual("Logs retenidos", "Retained logs"), history.events],
      [bilingual("Analizados", "Reviewed"), history.reviewed],
      [
        bilingual("Sin analizar", "Unreviewed"),
        history.events - history.reviewed,
      ],
      [
        bilingual("Esperando lote", "Waiting for a batch"),
        history.pending + history.queued + history.capacity,
      ],
    ]) {
      const item = el("div");
      item.append(el("strong", coverageNumber(value)), el("span", label));
      grid.append(item);
    }
    box.append(
      grid,
      el(
        "p",
        bilingual(
          "Todo el histórico retenido de ",
          "All retained history for ",
        ) +
          machineName(scope) +
          bilingual(
            ". Analizados incluye originales representados en grupos; no implica lectura individual de todos ellos.",
            ". Reviewed includes originals represented in groups; it does not imply every original was read individually.",
          ),
        "subtle",
      ),
    );
    if (history.excluded || history.policy)
      box.append(
        el(
          "p",
          coverageNumber(history.excluded + history.policy) +
            bilingual(
              " apartados por filtros o selección: no están en la cola del LLM. Desactivar el filtro afecta a nuevas revisiones; para recuperar los retenidos usa Fuentes → Recuperar retenidos sin analizar.",
              " left out by filters or selection: these are outside the LLM queue. Disabling a filter affects new reviews; recover retained logs using Sources → Recover unreviewed retained logs.",
            ),
        ),
      );
  }
  if (r.capture)
    box.append(
      el(
        "p",
        bilingual("Último log recibido: ", "Last log received: ") +
          monitorTime(r.capture.last_event, r.generated),
        "subtle",
      ),
    );
  const tuning = r.tuning;
  if (tuning) {
    const reasons = {
      warming_up: bilingual(
        "Empieza con lotes pequeños mientras aprende sus tiempos.",
        "Starts with small batches while measuring their duration.",
      ),
      recent_error: bilingual(
        "Ha reducido la entrada tras un error reciente.",
        "Reduced input after a recent error.",
      ),
      slow_batch: bilingual(
        "Ha reducido la entrada porque el último lote tardó demasiado.",
        "Reduced input because the last batch took too long.",
      ),
      spare_time: bilingual(
        "Puede ampliar la entrada porque los últimos lotes terminaron con margen.",
        "Can expand input because recent batches finished with time to spare.",
      ),
      within_target: bilingual(
        "Mantiene el tamaño porque está cerca del tiempo objetivo.",
        "Keeps the size because it is near the target time.",
      ),
      fixed_limit: bilingual(
        "El ajuste automático está desactivado: usa el límite fijo.",
        "Automatic tuning is off: uses the fixed limit.",
      ),
    };
    box.append(
      el("h3", bilingual("Cómo se ajusta el LLM", "How the LLM is tuned")),
      el("p", reasons[tuning.reason] || ""),
      el(
        "p",
        bilingual("Entrada prevista: ", "Planned input: ") +
          bytes(tuning.input_bytes) +
          bilingual(" de un máximo de ", " out of a maximum of ") +
          bytes(tuning.maximum_bytes) +
          " · " +
          bilingual("Objetivo: ", "Target: ") +
          tuning.target_seconds +
          " s · " +
          tuning.samples +
          bilingual(" llamadas de muestra", " sampled calls"),
      ),
      el(
        "p",
        bilingual(
          "El objetivo no es una cuenta atrás. La cola espera su turno y los originales largos pueden necesitar varios fragmentos. Más eventos por lote no siempre significa más velocidad.",
          "The target is not a countdown. Queued work waits its turn and long originals can need multiple fragments. More events per batch does not always mean more speed.",
        ),
        "subtle",
      ),
    );
  }
  if (r.latency?.samples)
    box.append(
      guideDetails(
        bilingual("Dónde se va el tiempo del modelo", "Where model time goes"),
        el(
          "p",
          r.latency.samples +
            bilingual(
              " llamadas correctas con desglose del servidor, incluida verificación. Medianas; no son una medición de tu GPU.",
              " successful calls with server timings, including verification. Medians; these do not identify or benchmark your GPU.",
            ),
          "subtle",
        ),
        table(
          [bilingual("Trabajo", "Work"), bilingual("Tiempo", "Time")],
          [
            [
              bilingual("Llamada completa", "Complete call"),
              r.latency.total_seconds,
            ],
            [bilingual("Cargar modelo", "Load model"), r.latency.load_seconds],
            [bilingual("Leer entrada", "Read input"), r.latency.input_seconds],
            [
              bilingual("Generar respuesta", "Generate response"),
              r.latency.output_seconds,
            ],
          ].map(([label, value]) => [label, coverageNumber(value, 1) + " s"]),
        ),
      ),
    );
  return box;
}
async function mountCapacitySummary(root, machine = scope) {
  async function update() {
    const r = await api(
      "/api/capacity" +
        (machine ? "?machine_id=" + encodeURIComponent(machine) : ""),
    );
    if (!root.isConnected) return;
    const p = panel(t("Cobertura y capacidad"));
    const signal = r.signal || {};
    const diagnosis = capacityDiagnosis(r);
    const banner = el(
      "p",
      (r.capture && !r.capture.active_sources) || !r.limits.enabled || !r.events
        ? diagnosis.title + ". " + diagnosis.detail
        : signal.reason === "review_blocked"
          ? bilingual(
              "La revisión está incompleta: hay eventos con errores de análisis o que no caben en el contexto. Revisa Actividad y el presupuesto de entrada.",
              "Review is incomplete: some events have analysis errors or exceed the input budget. Check Activity and the input budget.",
            )
          : signal.level === "critical"
            ? bilingual(
                "La revisión va muy por detrás de lo que entra. Lo no revisado no es un resultado limpio.",
                "Review is far behind incoming logs. Unreviewed is not a clean result.",
              )
            : signal.level === "warn"
              ? bilingual(
                  "El modelo no cubre todo el volumen de la última hora. Revisa filtros o capacidad.",
                  "The model is not covering last hour's volume. Check filters or capacity.",
                )
              : bilingual(
                  "La última hora está al ritmo del modelo, o el volumen es bajo. Sigue sin ser una prueba de seguridad.",
                  "Last hour is keeping up with the model, or volume is low. That is still not a security proof.",
                ),
      "coverage-signal " + diagnosis.level,
    );
    p.append(banner);
    p.append(
      el(
        "p",
        bilingual("Última hora: ", "Last hour: ") +
          coverageNumber(r.events) +
          bilingual(" recibidos · ", " received · ") +
          coverageNumber(r.reviewed) +
          bilingual(" revisados · ", " reviewed · ") +
          coverageNumber(r.pending) +
          bilingual(" pendientes · ", " waiting · ") +
          coverageNumber(r.capacity) +
          bilingual(" en la cola histórica · ", " in the historical queue · ") +
          coverageNumber(r.error) +
          bilingual(" con error · ", " with errors · ") +
          coverageNumber(r.oversized) +
          bilingual(" no caben en el contexto", " exceed the input budget"),
      ),
    );
    p.append(
      el(
        "p",
        bilingual("Modelo actual: ", "Current model: ") +
          r.limits.model +
          " · " +
          (r.limits.enabled
            ? bilingual(
                "análisis automático activado",
                "automatic analysis enabled",
              )
            : bilingual("análisis pausado", "analysis paused")),
      ),
      button(
        bilingual(
          "Entender y mejorar la cobertura",
          "Understand and improve coverage",
        ),
        () => openCapacity(machine),
      ),
    );
    root.replaceChildren(p);
  }
  await update();
  const poll = setInterval(() => {
    if (!root.isConnected) return clearInterval(poll);
    update().catch(() => {});
  }, 10000);
}
async function capacityView(root) {
  const live = el("div"),
    extra = el("div"),
    actionsPanel = panel(
      bilingual("Cómo aumentar la cobertura", "How to increase coverage"),
    );
  root.append(live, actionsPanel);
  const machine = scope;
  if (machine)
    actionsPanel.append(
      button(bilingual("Optimizar esta máquina", "Optimize this machine"), () =>
        openOptimizer(machine),
      ),
    );
  else
    actionsPanel.append(
      el(
        "p",
        bilingual(
          "Selecciona una máquina para preparar una optimización con sus logs.",
          "Select a machine to prepare an optimization from its logs.",
        ),
        "subtle",
      ),
    );
  let report;
  actionsPanel.append(el("ol"));
  const steps = [
    bilingual(
      "Revisa las fuentes duplicadas y los servicios que más volumen generan. En Fuentes puedes configurar selección por prioridad o palabras con contexto; en Reglas puedes previsualizar filtros de exclusión. Los mensajes no seleccionados seguirán contando como no revisados.",
      "Check duplicate sources and the services producing most volume. Sources lets you configure selection by priority or keywords with context; Rules lets you preview exclusion filters. Unselected messages still count as unreviewed.",
    ),
    bilingual(
      "Si limita el presupuesto de entrada, prueba ampliarlo dentro del contexto ya configurado. Más contexto también puede aumentar memoria y tiempo de respuesta. Guarda el cambio y compara varios ciclos.",
      "If the input budget is limiting coverage, try increasing it within the configured context. More context can also increase memory and response time. Save the change and compare several cycles.",
    ),
    bilingual(
      "Si el ciclo termina pronto, un intervalo menor puede ayudar. Si el modelo está ocupado casi todo el tiempo, prueba un modelo más rápido o más recursos; reducir el intervalo no acelera al modelo. Las investigaciones y el chat comparten su turno.",
      "If cycles finish early, a shorter interval may help. If the model is busy most of the time, try a faster model or more resources; a shorter interval does not speed up the model. Investigations and chat share its turn.",
    ),
  ];
  for (const step of steps)
    actionsPanel.querySelector("ol").append(el("li", step));
  actionsPanel.append(
    actions(
      button(t("Fuentes"), () => navigate("source")),
      button(t("Modelo y análisis"), () => navigate("settings")),
      button(bilingual("Filtros predefinidos", "Built-in filters"), () =>
        navigate("rule"),
      ),
      button(
        bilingual(
          "Preparar ampliación de entrada",
          "Prepare larger input budget",
        ),
        async () => {
          const latest = await api("/api/capacity");
          S = await api("/api/state");
          navigate("settings");
          const input = $("#content [name=input_budget]");
          if (
            input &&
            latest.limits.suggested_input_bytes > S.settings.input_budget
          ) {
            input.closest("details")?.setAttribute("open", "");
            input.value = latest.limits.suggested_input_bytes;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
            notice(
              bilingual(
                "Propuesta preparada sin guardar. Revisa el presupuesto y pulsa Guardar para aplicarlo.",
                "Draft prepared without saving. Review the budget and select Save to apply it.",
              ),
            );
          } else
            notice(
              bilingual(
                "La entrada ya alcanza el margen del contexto actual. Revisa fuentes, velocidad e intervalo.",
                "Input already reaches the available context allowance. Review sources, speed and interval.",
              ),
            );
        },
      ),
    ),
  );
  const simulation = panel(
    bilingual(
      "Estimar cuánto volumen cabría",
      "Estimate how much volume would fit",
    ),
  );
  const slider = field(
    "",
    bilingual(
      "Volumen seleccionado para el LLM (%)",
      "Volume selected for the LLM (%)",
    ),
    "range",
    100,
  );
  const input = slider.querySelector("input");
  input.min = 1;
  input.max = 100;
  input.step = 1;
  const estimate = el("p");
  simulation.append(
    el(
      "p",
      bilingual(
        "Simulación: conserva la tasa de revisión observada y cambia solo el volumen. No aplica filtros ni cambia ajustes. El tamaño y la repetición de los mensajes, el modelo y las investigaciones pueden cambiar el resultado.",
        "Simulation: keeps the observed review rate and changes only volume. It does not apply filters or change settings. Message size and repetition, the model and investigations can change the outcome.",
      ),
    ),
    slider,
    estimate,
  );
  root.insertBefore(simulation, actionsPanel);
  root.append(extra);
  function simulate() {
    const p = report.planning;
    input.disabled = !p.ready;
    if (!p.ready) {
      estimate.textContent = bilingual(
        "Todavía midiendo: hacen falta al menos dos lotes terminados y dos intervalos con esta configuración. Una prueba de conexión no mide capacidad.",
        "Still measuring: at least two completed batches and two intervals with this configuration are needed. A connection test does not measure capacity.",
      );
      return;
    }
    const rate = (p.target_per_minute * Number(input.value)) / 100;
    const factor = p.covered_per_minute > 0 ? rate / p.covered_per_minute : 0;
    estimate.textContent =
      input.value +
      "% → " +
      coverageNumber(rate, 1) +
      bilingual(
        " eventos/min a revisar, frente a ",
        " events/min to review, against ",
      ) +
      coverageNumber(p.covered_per_minute, 1) +
      bilingual(" revisados/min observados. ", " observed reviewed/min. ") +
      (factor > 1
        ? bilingual("Harían falta aproximadamente ", "Approximately ") +
          coverageNumber(factor, 1) +
          bilingual(
            " veces esa tasa para este volumen.",
            " times that rate would be needed for this volume.",
          )
        : bilingual(
            "Ese volumen estaría dentro de la tasa observada; compruébalo durante varios ciclos.",
            "That volume would be within the observed rate; verify over several cycles.",
          ));
  }
  input.oninput = simulate;
  async function update() {
    const r = await api(
      "/api/capacity" +
        (machine ? "?machine_id=" + encodeURIComponent(machine) : ""),
    );
    if (!root.isConnected) return;
    report = r;
    const l = r.limits,
      c = r.current,
      p = r.planning;
    const status = panel(
      bilingual(
        "Configuración activa y rendimiento medido",
        "Active configuration and measured performance",
      ),
    );
    status.append(
      el(
        "p",
        l.provider +
          " · " +
          l.model +
          " · " +
          (l.enabled
            ? bilingual("automático", "automatic")
            : bilingual("pausado", "paused")),
      ),
    );
    status.append(
      el(
        "p",
        bilingual(
          "Mediciones de esta configuración desde ",
          "Measurements for this configuration since ",
        ) +
          stamp(c.start) +
          ". " +
          c.completed_batches +
          bilingual(" lotes terminados. ", " completed batches. ") +
          (c.average_batch_seconds == null
            ? ""
            : bilingual(
                "Duración media del lote, incluida verificación: ",
                "Average batch duration, including verification: ",
              ) +
              coverageNumber(c.average_batch_seconds, 1) +
              " s."),
      ),
    );
    if (!l.enabled)
      status.append(
        el(
          "p",
          bilingual(
            "El análisis automático está pausado; la captura puede seguir activa. Actívalo en Modelo y análisis para medir un ritmo continuo.",
            "Automatic analysis is paused; capture can remain active. Enable it in Model and analysis to measure a continuous rate.",
          ),
          "monitor-warning",
        ),
      );
    const limitsDetail = el("div");
    limitsDetail.append(
      table(
        [
          bilingual("Límite", "Limit"),
          bilingual("Valor actual", "Current value"),
        ],
        [
          [
            bilingual("Intervalo solicitado", "Requested interval"),
            l.interval_seconds + " s",
          ],
          [
            bilingual(
              "Contexto configurado / reserva de salida",
              "Configured context / output reserve",
            ),
            coverageNumber(l.context_tokens) +
              " / " +
              coverageNumber(l.output_tokens) +
              " tokens",
          ],
          [
            bilingual(
              "Entrada efectiva para grupos de logs",
              "Effective input for log groups",
            ),
            coverageNumber(l.effective_input_bytes) +
              bilingual(" bytes por lote", " bytes per batch"),
          ],
          [
            bilingual(
              "Máximo de entrada dentro del contexto actual",
              "Maximum input within the current context",
            ),
            coverageNumber(l.input_ceiling_bytes) + " bytes",
          ],
          [
            bilingual(
              "Originales candidatos por lote",
              "Candidate originals per batch",
            ),
            l.max_events_per_machine,
          ],
          [
            bilingual(
              "Llamadas compartidas / máquinas con fuentes activas",
              "Shared calls / machines with active sources",
            ),
            l.max_calls_per_cycle + " / " + l.active_machines,
          ],
        ],
      ),
    );
    limitsDetail.append(
      el(
        "p",
        bilingual(
          "El presupuesto limita el tamaño de la entrada. Las repeticiones comprobadas se agrupan conservando cantidad, fechas, variaciones de frecuencia, ejemplos y referencias. Una máquina puede procesar varios lotes por ciclo; las verificaciones comparten el límite de llamadas. Los excedentes quedan en cola y los reintentos conservan el lote enviado.",
          "The budget bounds input size. Recognized repetitions are grouped with counts, times, frequency changes, examples and references. A machine can process multiple batches per cycle; verification shares the call limit. Overflow stays queued and retries preserve the submitted batch.",
        ),
        "subtle",
      ),
    );
    if (l.effective_input_bytes < l.input_ceiling_bytes)
      status.append(
        el(
          "p",
          bilingual(
            "Hay margen de contexto sin usar para la entrada: ",
            "Unused context allowance for input: ",
          ) +
            coverageNumber(l.input_ceiling_bytes - l.effective_input_bytes) +
            bilingual(
              " bytes. Puedes preparar una ampliación abajo; no garantiza cubrir todo el volumen.",
              " bytes. You can prepare an increase below; it does not guarantee covering all volume.",
            ),
        ),
      );
    if (p.required_multiplier > 1)
      status.append(
        el(
          "p",
          bilingual(
            "En el periodo medido sin la cola más reciente llegan ",
            "In the measured period excluding the newest collecting tail, ",
          ) +
            coverageNumber(p.target_per_minute, 1) +
            bilingual(
              " eventos/min seleccionables y se han cubierto ",
              " eligible events/min arrive and ",
            ) +
            coverageNumber(p.covered_per_minute, 1) +
            bilingual(
              "/min: haría falta aproximadamente ",
              "/min have been covered: approximately ",
            ) +
            coverageNumber(p.required_multiplier, 1) +
            bilingual(
              " veces esa tasa. Es una observación, no el máximo teórico del modelo.",
              " times that rate would be needed. This is an observation, not the model's theoretical maximum.",
            ),
          "monitor-warning",
        ),
      );
    if (r.analysis.errors)
      status.append(
        el(
          "p",
          r.analysis.errors +
            bilingual(
              " llamadas fallidas con esta configuración. Revisa Actividad: los errores también reducen cobertura.",
              " failed calls with this configuration. Check Activity: errors also reduce coverage.",
            ),
          "monitor-warning",
        ),
      );
    if (r.duplicate_journals.length)
      status.append(
        el(
          "p",
          bilingual(
            "Fuentes duplicadas del journal local: ",
            "Duplicate local journal sources: ",
          ) +
            r.duplicate_journals
              .map((s) => s.name + " (" + machineName(s.machine_id) + ")")
              .join(", ") +
            bilingual(
              ". Capturan el mismo journal; desactiva las copias en Fuentes.",
              ". They capture the same journal; disable copies in Sources.",
            ),
          "monitor-warning",
        ),
      );
    const history = panel(
      bilingual(
        "Qué significa el histórico sin revisar",
        "What the unreviewed history means",
      ),
    );
    history.append(
      el(
        "p",
        coverageNumber(r.retained_capacity) +
          bilingual(
            " eventos en la cola histórica de este ámbito. Se recuperan automáticamente por lotes mientras el análisis y la máquina estén activos. Los excluidos por reglas o selección requieren recuperar la fuente después de cambiar su filtro. Los originales se conservan hasta el límite de retención o espacio.",
            " events in this scope’s historical queue. They are recovered automatically in batches while analysis and machine monitoring are active. Logs excluded by rules or selection need source recovery after changing the filter. Originals remain until retention or storage limits apply.",
          ),
      ),
    );
    const services = panel(
      bilingual(
        "Qué genera más volumen · última hora",
        "What generates most volume · last hour",
      ),
    );
    services.append(
      table(
        [
          t("Máquina"),
          t("Fuente"),
          t("Servicio"),
          bilingual("Recibidos", "Received"),
          bilingual("Revisados", "Reviewed"),
          bilingual("Por capacidad", "Capacity gap"),
        ],
        r.services.map((s) => [
          machineName(s.machine_id),
          (S.source || []).find((x) => x.id === s.source_id)?.name ||
            s.source_id,
          s.service || "—",
          s.events,
          s.reviewed,
          s.capacity,
        ]),
      ),
    );
    const limitsBox = disclosure(
      bilingual(
        "Ver límites de entrada y llamadas",
        "Show input and call limits",
      ),
      limitsDetail,
    );
    limitsBox.open = root.querySelector(".capacity-limits")?.open || false;
    limitsBox.className = "capacity-limits";
    status.append(limitsBox);
    const guidance = tuningSummary(r);
    if (live.querySelector(".tuning-summary details")?.open)
      guidance.querySelector("details")?.setAttribute("open", "");
    live.replaceChildren(
      guidance,
      coverageWindow(
        c,
        bilingual(
          "Con la configuración actual",
          "With the current configuration",
        ) +
          " · " +
          l.model,
      ),
      status,
    );
    extra.replaceChildren(
      coverageWindow(
        r,
        bilingual(
          "Última hora · puede incluir modelos anteriores",
          "Last hour · may include previous models",
        ),
      ),
      history,
      services,
    );
    simulate();
  }
  await update();
  const poll = setInterval(() => {
    if (!root.isConnected) return clearInterval(poll);
    update().catch((error) => notice(error.message, true));
  }, 10000);
}
