"use strict";
async function openOptimizer(machineId) {
  const box = el("div"),
    status = el(
      "p",
      bilingual(
        "Inspeccionando una muestra de logs y el rendimiento guardado… No consume tokens.",
        "Inspecting a log sample and recorded performance… No tokens are used.",
      ),
    ),
    content = el("div");
  box.append(status, content);
  modal(bilingual("Optimizar · ", "Optimize · ") + machineName(machineId), box);
  try {
    const plan = await api("/api/machines/" + machineId + "/optimize", {});
    if (!box.isConnected) return;
    status.textContent = bilingual(
      "Propuesta preparada. No se ha cambiado la configuración.",
      "Proposal prepared. Configuration has not changed.",
    );
    renderOptimization(plan, content);
  } catch (e) {
    status.textContent = e.message;
  }
}
function renderOptimization(plan, root) {
  const n = coverageNumber,
    cap = plan.capacity;
  const names = {
    current: bilingual("Configuración actual", "Current configuration"),
    warnings: bilingual(
      "Avisos y niveles más graves + palabras",
      "Warnings and higher priorities + keywords",
    ),
    errors: bilingual(
      "Errores y niveles más graves + palabras",
      "Errors and higher priorities + keywords",
    ),
    critical: bilingual(
      "Críticos y niveles más graves + palabras",
      "Critical and higher priorities + keywords",
    ),
    larger_batch: bilingual(
      "Probar un lote mayor (global)",
      "Try a larger batch (global)",
    ),
    more_frequent: bilingual(
      "Analizar con más frecuencia (global)",
      "Analyze more frequently (global)",
    ),
  };
  root.append(
    el(
      "p",
      plan.model +
        " · " +
        bilingual("Entrada: ", "Incoming: ") +
        n(plan.incoming_per_minute, 1) +
        bilingual(" eventos/min", " events/min"),
    ),
    el(
      "p",
      bilingual("Muestra: ", "Sample: ") +
        n(plan.sample_size) +
        " / " +
        n(plan.events_in_window) +
        bilingual(" eventos retenidos en ", " retained events over ") +
        n(plan.window_seconds / 60, 1) +
        " min · " +
        n(plan.excluded) +
        bilingual(" excluidos por tus reglas", " excluded by your rules"),
      "subtle",
    ),
  );
  if (plan.sample_truncated)
    root.append(
      el(
        "p",
        bilingual(
          "Se han muestreado los 2000 eventos más recientes. Su distribución puede ser diferente del resto del periodo; las tasas seleccionadas son extrapolaciones.",
          "Sampled the latest 2,000 events. Their distribution may differ from the rest of the period; selected rates are extrapolations.",
        ),
        "monitor-warning",
      ),
    );
  root.append(
    el(
      "p",
      cap.reliable
        ? bilingual(
            "Capacidad orientativa por máquina: ",
            "Indicative capacity per machine: ",
          ) +
            n(cap.events_per_minute, 1) +
            bilingual(
              " eventos/min, con un margen del 25 %.",
              " events/min, with 25% headroom.",
            )
        : bilingual(
            "Aún no hay una estimación fiable de capacidad: hacen falta al menos 3 lotes completos con esta configuración y pocos errores recientes.",
            "No reliable capacity estimate yet: at least 3 completed batches with these settings and few recent errors are needed.",
          ),
      cap.reliable ? "" : "monitor-warning",
    ),
  );
  root.append(
    el(
      "p",
      n(cap.batches) +
        bilingual(" lotes medidos · ", " measured batches · ") +
        (cap.batch_seconds == null ? "—" : n(cap.batch_seconds, 1) + " s") +
        bilingual(" por lote · ", " per batch · ") +
        n(cap.active_machines) +
        bilingual(
          " máquinas consideradas al compartir el modelo",
          " machines considered when sharing the model",
        ),
      "subtle",
    ),
  );
  if (cap.error_rate > 0)
    root.append(
      el(
        "p",
        bilingual(
          "Errores en las llamadas recientes: ",
          "Recent calls with errors: ",
        ) +
          n(cap.error_rate * 100) +
          " %. " +
          bilingual(
            "Comprueba los timeouts o la conexión antes de confiar en una previsión.",
            "Check timeouts or connectivity before relying on a projection.",
          ),
      ),
    );
  const verdict = (o) =>
    o.fits_estimate === true
      ? bilingual("Cabe en la estimación", "Within estimate")
      : o.fits_estimate === false
        ? bilingual("Supera la estimación", "Above estimate")
        : bilingual("Por medir", "Needs measurement");
  root.append(
    table(
      [
        bilingual("Propuesta", "Proposal"),
        bilingual("Seleccionados", "Selected"),
        bilingual("Eventos/min estimados", "Estimated events/min"),
        bilingual("Capacidad", "Capacity"),
      ],
      plan.choices.map((o) => [
        names[o.id],
        n(o.triggers) + " / " + n(plan.sample_size),
        n(o.selected_per_minute, 1),
        verdict(o),
      ]),
    ),
  );
  root.append(
    el(
      "p",
      bilingual(
        "Las tasas cuentan disparadores, no todo el contexto. El texto se compacta antes de enviarse. Los tiempos pueden variar por longitud, respuesta y otras aplicaciones que usen el servidor. Aumentar el intervalo acumula más logs; no acelera el modelo.",
        "Rates count triggers, not all surrounding context. Text is compacted before sending. Timing varies with input, output and other applications using the server. Increasing the interval accumulates more logs; it does not speed up the model.",
      ),
      "subtle",
    ),
  );
  if (!plan.sample_size || !plan.sources.length) {
    root.append(
      el(
        "p",
        bilingual(
          "Activa una fuente y captura logs antes de preparar cambios.",
          "Enable a source and capture logs before preparing changes.",
        ),
      ),
    );
    return;
  }
  if (!plan.recommended)
    root.append(
      el(
        "p",
        bilingual(
          "No hay una propuesta cuya cobertura podamos recomendar con estos datos. Puedes probar un filtro y medir varios ciclos; si ni los críticos caben, necesitarás menos volumen o un modelo/servidor más rápido.",
          "These data do not support a capacity recommendation. You can try a filter and measure several cycles; if even critical events exceed capacity, reduce volume or use a faster model/server.",
        ),
        "monitor-warning",
      ),
    );
  else
    root.append(
      el(
        "p",
        bilingual(
          "Opción menos restrictiva dentro de la estimación: ",
          "Least restrictive option within estimate: ",
        ) + names[plan.recommended],
      ),
    );
  const selector = el("select"),
    detail = el("div"),
    ack = field(
      "ack_coverage",
      bilingual(
        "He revisado los cambios y la pérdida de cobertura",
        "I have reviewed the changes and coverage loss",
      ),
      "checkbox",
      false,
    ),
    globalAck = field(
      "ack_global",
      bilingual(
        "Acepto los cambios globales para todas las máquinas",
        "I accept global changes for all machines",
      ),
      "checkbox",
      false,
    ),
    label = el(
      "label",
      bilingual("Configuración a probar", "Configuration to try"),
    );
  selector.setAttribute(
    "aria-label",
    bilingual("Propuesta a aplicar", "Proposal to apply"),
  );
  for (const o of plan.choices.filter((o) => o.id !== "current")) {
    const opt = el("option", names[o.id]);
    opt.value = o.id;
    selector.append(opt);
  }
  selector.value =
    plan.recommended && plan.recommended !== "current"
      ? plan.recommended
      : "warnings";
  label.append(selector);
  const apply = button(
    bilingual("Aplicar esta propuesta", "Apply this proposal"),
    async () => {
      const choice = plan.choices.find((o) => o.id === selector.value);
      await api("/api/machines/" + plan.machine_id + "/optimize/apply", {
        plan_id: plan.id,
        choice: choice.id,
        acknowledge_coverage: ack.querySelector("input").checked,
        acknowledge_global: globalAck.querySelector("input").checked,
      });
      root.replaceChildren(
        el(
          "p",
          bilingual(
            "Propuesta aplicada. Comprueba la cobertura y los errores durante al menos 3 ciclos completos. Puedes regenerar el diagnóstico en Optimizar.",
            "Proposal applied. Check coverage and errors over at least 3 completed cycles. Run Optimize again to reassess.",
          ),
        ),
        button(bilingual("Ver cobertura", "View coverage"), () =>
          openCapacity(plan.machine_id),
        ),
      );
      await refresh();
    },
  );
  function update() {
    const choice = plan.choices.find((o) => o.id === selector.value),
      global = Object.keys(choice.global_patch).length > 0;
    detail.replaceChildren();
    if (global) {
      detail.append(
        el(
          "p",
          bilingual(
            "Estos cambios afectan al planificador o al presupuesto de todas las máquinas:",
            "These changes affect the scheduler or budget for all machines:",
          ),
        ),
        table(
          [
            bilingual("Parámetro", "Setting"),
            bilingual("Actual", "Current"),
            bilingual("Propuesto", "Proposed"),
          ],
          Object.entries(choice.global_patch).map(([k, v]) => [
            k,
            String(plan.current[k]),
            String(v),
          ]),
        ),
        el(
          "p",
          bilingual(
            "Cambiar el presupuesto invalida la estimación anterior. El contexto del servidor y el modelo no se modificarán; hay que comprobar el nuevo rendimiento.",
            "Changing the budget invalidates the previous estimate. The server context and model remain unchanged; measure the new performance.",
          ),
          "subtle",
        ),
      );
    } else {
      detail.append(
        el(
          "p",
          bilingual("Fuentes de esta máquina: ", "Sources on this machine: ") +
            plan.sources.map((s) => s.name).join(", "),
        ),
      );
      const patch = Object.values(choice.source_patches)[0];
      detail.append(
        el(
          "p",
          bilingual("Prioridad numérica 0–", "Numeric priority 0–") +
            patch.priority_ceiling +
            bilingual(
              " O cualquiera de estas palabras (sin distinguir mayúsculas):",
              " OR any of these keywords (case insensitive):",
            ),
        ),
        el("pre", patch.trigger_terms),
        el(
          "p",
          bilingual(
            "Contexto automático: 0 minutos. Se conservan los originales para ampliar un hallazgo después. La prioridad la proporciona el emisor; no demuestra por sí sola la gravedad ni la autenticidad.",
            "Automatic surrounding context: 0 minutes. Originals remain available to expand a finding later. Priority is supplied by the producer; it does not prove severity or authenticity.",
          ),
        ),
        el(
          "p",
          n(choice.omitted_by_policy) +
            bilingual(
              " eventos de la muestra dejarían de seleccionarse. Tus exclusiones existentes se mantienen.",
              " sample events would no longer be selected. Your existing exclusions are preserved.",
            ),
        ),
      );
    }
    globalAck.hidden = !global;
    apply.disabled =
      !ack.querySelector("input").checked ||
      (global && !globalAck.querySelector("input").checked);
  }
  selector.onchange = () => {
    ack.querySelector("input").checked = false;
    globalAck.querySelector("input").checked = false;
    update();
  };
  ack.querySelector("input").onchange = update;
  globalAck.querySelector("input").onchange = update;
  root.append(
    label,
    detail,
    ack,
    globalAck,
    el(
      "p",
      bilingual(
        "No se activará una máquina pausada ni el análisis global. Los originales retenidos no se borran. La propuesta caduca a los 15 minutos o si cambia la configuración.",
        "Paused machines and global analysis are not enabled. Retained originals are not deleted. This proposal expires after 15 minutes or if configuration changes.",
      ),
      "subtle",
    ),
    apply,
  );
  update();
}
