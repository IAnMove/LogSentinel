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
    ["capacity", bilingual("Omitidos por capacidad", "Skipped for capacity")],
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
async function mountCapacitySummary(root, machine = scope) {
  async function update() {
    const r = await api(
      "/api/capacity" +
        (machine ? "?machine_id=" + encodeURIComponent(machine) : ""),
    );
    if (!root.isConnected) return;
    const p = panel(t("Cobertura y capacidad"));
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
          bilingual(" omitidos por capacidad", " skipped for capacity"),
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
              "Eventos candidatos por máquina y ciclo",
              "Candidate events per machine per cycle",
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
          "El presupuesto usa bytes UTF-8 como cota conservadora, no tokens reales ni un número fijo de líneas. Las instrucciones y la salida ocupan espacio. El límite de eventos solo admite candidatos: no garantiza que quepan. Actualmente se prepara como máximo un lote nuevo por máquina y ciclo; las verificaciones también consumen llamadas.",
          "The budget uses UTF-8 bytes as a conservative bound, not actual tokens or a fixed line count. Instructions and output take space. The event limit only admits candidates: it does not guarantee they fit. Currently at most one new batch is prepared per machine per cycle; verification also consumes calls.",
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
            " eventos retenidos omitidos por capacidad en todo el histórico de este ámbito. No están en la cola automática de pendientes. Los originales siguen disponibles hasta su caducidad; un cambio de configuración mejora los próximos ciclos, no revisa automáticamente ese histórico.",
            " retained events skipped for capacity across this scope's entire history. They are not in the automatic pending queue. Originals remain available until retention expires; configuration changes improve future cycles, not automatically review this history.",
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
    live.replaceChildren(
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
