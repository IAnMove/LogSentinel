"use strict";
let chatProblemId = "",
  chatDraft = "",
  detailsProblemId = "";

function openProblemChat(p) {
  if ($("#modal").open) $("#modal").close();
  chatProblemId = p.id;
  chatDraft = t(
    "Ayúdame a entender este problema: {title}. Contrasta la hipótesis con sus evidencias y explica qué comprobar a continuación.",
    { title: p.title },
  );
  scope = p.machine_id;
  view = "chat";
  $("#machine-scope").value = scope;
  render();
}

async function openProblemPage(id) {
  if ($("#modal").open) $("#modal").close();
  detailsProblemId = id;
  view = "problem_detail";
  await render();
}

function disclosure(title, content) {
  const d = el("details"),
    s = el("summary", title);
  d.append(s, content);
  return d;
}

function problemContextCard(p) {
  const card = panel(p.title);
  card.classList.add("problem-context");
  card.append(
    actions(badge(p.severity), badge(p.status)),
    el("p", p.data.summary),
  );
  const detail = el("div");
  detail.append(
    table(
      [t("Detalle"), t("Valor")],
      [
        [t("Máquina"), p.machine?.name || machineName(p.machine_id)],
        [t("Categoría"), p.data.category],
        [t("Primera detección"), stamp(p.first_seen)],
        [t("Última detección"), stamp(p.last_seen)],
        [t("Eventos de evidencia"), p.count],
        [
          t("Fuentes de la evidencia"),
          (p.sources || []).map((s) => s.name).join(", ") || "—",
        ],
        [t("ID de problema"), p.id],
      ],
    ),
    el("h3", t("Hipótesis e incertidumbre")),
    el("p", p.data.reasoning || t("Sin ampliación")),
    el("h3", t("Siguientes comprobaciones")),
    el("p", p.data.next_steps || t("Revisar evidencia original")),
  );
  card.append(disclosure(t("Ver todos los datos del hallazgo"), detail));
  return card;
}

function contextDisclosure(context, sent = false) {
  const box = el("div"),
    c = context.coverage;
  box.append(
    el(
      "p",
      t(
        "{sent} eventos incluidos · {omitted} omitidos · {expired} evidencias caducadas · {bytes}/{budget} bytes de entrada.",
        {
          sent: c.events_sent,
          omitted: c.omitted_events,
          expired: c.expired_evidence,
          bytes: c.input_bytes,
          budget: c.budget_bytes,
        },
      ),
    ),
  );
  if (
    c.excluded_events ||
    c.truncated_fields.length ||
    c.excerpted_events.length ||
    c.history_omitted
  )
    box.append(
      el(
        "p",
        t(
          "Se han aplicado exclusiones o recortes. Consulta el desglose; los originales retenidos siguen disponibles.",
        ),
        "monitor-warning",
      ),
    );
  box.append(
    disclosure(
      t("Desglose de cobertura"),
      el("pre", JSON.stringify(c, null, 2)),
    ),
  );
  box.append(
    disclosure(
      sent
        ? t("Contexto enviado en esta consulta")
        : t("Vista previa del contexto que se enviará"),
      el("pre", JSON.stringify(context.payload, null, 2)),
    ),
  );
  return box;
}

function chatReply(reply) {
  const box = el("div", reply.answer, "message");
  const events = reply.context?.payload?.events || [];
  box.append(el("h3", t("Evidencias citadas")));
  for (const id of reply.evidence_ids || []) {
    const event = events.find((e) => e.id === id);
    box.append(
      button(id, () =>
        modal(
          t("Fragmento enviado al modelo"),
          el("pre", event ? JSON.stringify(event, null, 2) : id),
        ),
      ),
    );
  }
  if (!reply.evidence_ids?.length)
    box.append(el("p", t("La respuesta no cita eventos concretos."), "subtle"));
  if (reply.context)
    box.append(
      disclosure(
        t("Ver qué recibió el asistente"),
        contextDisclosure(reply.context, true),
      ),
    );
  if (reply.filter)
    box.append(
      button(t("Revisar filtro propuesto"), () => {
        view = "rule";
        edit = reply.filter;
        render();
      }),
    );
  return box;
}

async function startInvestigation(p, minutes = 30) {
  const job = await api("/api/problems/" + p.id + "/investigations", {
    language: locale,
    window_minutes: minutes,
  });
  notice(
    t(
      "Investigación guardada. Esperará su turno si el modelo está ocupado; puedes cerrar esta vista.",
    ),
  );
  return job;
}

async function problemPage(root) {
  const id = detailsProblemId,
    p = await api("/api/problems/" + id);
  root.append(problemContextCard(p));
  if (p.data.category === "monitor.capacity")
    root.append(capacityProblemHint(p));
  const controls = panel(t("Investigar este problema")),
    f = el("form", undefined, "toolbar");
  const window = field(
    "window_minutes",
    t("Minutos antes y después de la evidencia"),
    "number",
    30,
  );
  window.querySelector("input").min = 1;
  window.querySelector("input").max = 1440;
  const run = el("button", t("Buscar más detalles del problema"));
  run.type = "submit";
  const feedback = el("p");
  feedback.setAttribute("role", "status");
  f.append(window, run);
  controls.append(
    el(
      "p",
      t(
        "El LLM propone términos; se buscan coincidencias en los logs retenidos de esta máquina y el LLM redacta un análisis más profundo. Hasta 2 llamadas, con presupuesto y una búsqueda de hasta 2.000 eventos. La captura continúa.",
      ),
    ),
    button(t("Preguntar al asistente"), () => openProblemChat(p)),
    f,
    feedback,
  );
  root.append(controls);
  const reports = panel(t("Investigaciones guardadas"));
  root.append(reports);
  f.onsubmit = async (e) => {
    e.preventDefault();
    run.disabled = true;
    try {
      await startInvestigation(p, Number(window.querySelector("input").value));
      await updateReports();
    } catch (error) {
      feedback.textContent = error.message;
      run.disabled = false;
    }
  };
  let timer;
  async function updateReports() {
    clearTimeout(timer);
    if (!root.isConnected) return;
    try {
      const jobs = await api("/api/problems/" + id + "/investigations");
      if (!root.isConnected) return;
      reports.replaceChildren(el("h2", t("Investigaciones guardadas")));
      run.disabled = jobs.some((j) => ["queued", "running"].includes(j.status));
      if (!jobs.length)
        reports.append(
          el("p", t("Todavía no has solicitado una investigación profunda.")),
        );
      for (const job of jobs.slice().reverse()) {
        const item = el("article", undefined, "research-report");
        const stages = {
          queued: "En cola",
          planning: "El LLM prepara la búsqueda",
          searching: "Buscando en originales retenidos",
          reviewing: "El LLM analiza las coincidencias",
          completed: "Completado",
          error: "Error de análisis",
          interrupted: "Interrumpido",
        };
        item.append(
          el("h3", t(stages[job.stage] || job.status)),
          el(
            "p",
            stamp(job.created) +
              " · " +
              (job.model || "—") +
              " · " +
              job.calls +
              t(" llamadas al modelo"),
          ),
        );
        if (job.search) {
          item.append(
            el(
              "p",
              t(
                "{scanned} eventos examinados · {matched} coincidencias · ventana ±{minutes} minutos.",
                {
                  scanned: job.search.scanned,
                  matched: job.search.matched,
                  minutes: job.window_minutes,
                },
              ),
            ),
          );
          if (job.search.scan_limited)
            item.append(
              el(
                "p",
                t(
                  "La búsqueda alcanzó su límite; no se examinó toda la ventana.",
                ),
                "monitor-warning",
              ),
            );
          item.append(
            disclosure(
              t("Ver términos y alcance de búsqueda"),
              el("pre", JSON.stringify(job.search, null, 2)),
            ),
          );
        }
        if (job.error) item.append(el("p", job.error, "monitor-warning"));
        if (job.result)
          item.append(chatReply({ ...job.result, context: job.context }));
        reports.append(item);
      }
    } catch (error) {
      feedback.textContent = error.message;
    }
    if (root.isConnected) timer = setTimeout(updateReports, 5000);
  }
  await updateReports();
  const evidence = panel(t("Evidencia retenida"));
  evidence.append(
    el(
      "p",
      t(
        "Se muestran {shown} originales de {retained} retenidos; {expired} han caducado.",
        {
          shown: p.evidence.length,
          retained: p.retained_evidence,
          expired: p.expired_evidence,
        },
      ),
    ),
  );
  for (const event of p.evidence) {
    const content = el("div");
    content.append(
      el("pre", JSON.stringify(event, null, 2)),
      button(t("Copiar evento"), () =>
        navigator.clipboard.writeText(JSON.stringify(event, null, 2)),
      ),
    );
    evidence.append(
      disclosure(
        (event.timestamp || t("fecha desconocida")) +
          " · " +
          event.service +
          " · " +
          event.message.slice(0, 160),
        content,
      ),
    );
  }
  root.append(evidence);
  if (p.machine)
    root.append(
      disclosure(
        t("Ficha de la máquina"),
        el("pre", JSON.stringify(p.machine, null, 2)),
      ),
    );
  const revisions = panel(t("Evolución del hallazgo"));
  revisions.append(
    el(
      "p",
      t(
        "Últimas 20 revisiones guardadas. Las investigaciones profundas se conservan aparte y no cambian el hallazgo automáticamente.",
      ),
    ),
  );
  for (const revision of p.revisions || [])
    revisions.append(
      disclosure(
        stamp(revision.created),
        el("pre", JSON.stringify(JSON.parse(revision.data), null, 2)),
      ),
    );
  root.append(revisions);
}
