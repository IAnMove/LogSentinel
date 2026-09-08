"use strict";

function chatDuration(seconds) {
  const value = Math.max(0, Math.ceil(seconds));
  return (
    Math.floor(value / 60) + "m " + String(value % 60).padStart(2, "0") + "s"
  );
}

async function chatView(root) {
  const b = bilingual,
    problemId = chatProblemId;
  const problem = problemId ? await api("/api/problems/" + problemId) : null;
  const machineId = problem?.machine_id || scope || S.machine[0]?.id || "";
  if (problem) {
    const card = problemContextCard(problem);
    card.append(
      button(t("Ver más detalles"), () => openProblemPage(problem.id)),
    );
    root.append(card);
  }
  const panelBox = panel(
      t(problem ? "Preguntar sobre este problema" : "Preguntar sobre los logs"),
    ),
    form = el("form"),
    machine = field(
      "machine_id",
      t("Máquina"),
      "select",
      machineId,
      S.machine.map((x) => [x.id, x.name]),
    ),
    question = field(
      "message",
      t("Pregunta o petición de filtro"),
      "textarea",
      chatDraft,
    ),
    input = question.querySelector("textarea"),
    send = el("button", t("Consultar")),
    status = el("div", undefined, "chat-request-status"),
    stateLine = el("strong"),
    timerLine = el("p", "", "chat-countdown"),
    explanation = el("p"),
    diagnostic = el("p", "", "subtle"),
    pendingQuestion = el("p", "", "chat-pending-question"),
    preview = el("div"),
    conversation = el("div");
  stateLine.setAttribute("role", "status");
  conversation.setAttribute("role", "log");
  timerLine.setAttribute("aria-live", "off");
  input.required = true;
  input.maxLength = 4000;
  input.oninput = () => {
    chatDraft = input.value;
  };
  machine.querySelector("select").disabled = !!problem;
  machine.querySelector("select").onchange = () => {
    scope = machine.querySelector("select").value;
    render();
  };
  send.type = "submit";
  let job = null,
    receivedAt = Date.now(),
    connectionError = "",
    submitting = false,
    pendingSubmission = null,
    model = {},
    displayed = new Set(),
    submitError = "";
  const active = () => job && ["queued", "running"].includes(job.status);
  const request = () => ({
    ...formData(form),
    problem_id: problemId,
    language: locale,
  });

  const cancel = button(
    b("Cancelar pregunta en cola", "Cancel queued question"),
    async () => {
      try {
        accept(await api("/api/chat/requests/" + job.id + "/cancel", {}));
      } catch (error) {
        connectionError = error.message;
        draw();
      }
    },
  );
  const retry = button(
    b("Reintentar esta pregunta", "Retry this question"),
    async () => {
      if (job && !active()) {
        input.value = job.request.message;
        chatDraft = input.value;
        pendingSubmission = null;
      }
      await submit();
    },
  );
  const check = button(b("Comprobar estado", "Check status"), async () => {
    await poll();
  });
  status.append(
    stateLine,
    pendingQuestion,
    timerLine,
    explanation,
    diagnostic,
    actions(cancel, retry, check),
  );

  function draw() {
    const busy = active();
    send.disabled = submitting || busy || !!pendingSubmission;
    input.disabled = submitting || busy;
    if (!problem) machine.querySelector("select").disabled = submitting || busy;
    send.textContent = submitting
      ? b("Registrando…", "Submitting…")
      : busy
        ? b("Pregunta pendiente", "Question pending")
        : model.busy
          ? b("Poner pregunta en cola", "Queue question")
          : t("Consultar");
    cancel.hidden = job?.status !== "queued";
    retry.hidden =
      !pendingSubmission &&
      (!job || !["failed", "interrupted", "cancelled"].includes(job.status));
    retry.textContent = pendingSubmission
      ? b("Confirmar envío", "Confirm submission")
      : b("Reintentar esta pregunta", "Retry this question");
    check.hidden = !connectionError;
    pendingQuestion.hidden = !job;
    pendingQuestion.textContent = job
      ? b("Pregunta: ", "Question: ") + job.request.message
      : "";
    status.dataset.state = connectionError
      ? "unknown"
      : submitting
        ? "submitting"
        : job?.status || "ready";
    diagnostic.textContent = connectionError || submitError || job?.error || "";
    const estimate = job?.estimate || model,
      expected = estimate.expected_seconds;
    const now = job?.server_time
      ? job.server_time + (Date.now() - receivedAt) / 1000
      : Date.now() / 1000;
    let remaining = null;
    if (job?.status === "running" && expected != null)
      remaining = expected - (now - job.started);
    if (job?.status === "queued" && job.estimated_wait_seconds != null)
      remaining = job.estimated_wait_seconds - (Date.now() - receivedAt) / 1000;
    const clock =
      remaining == null
        ? ""
        : remaining > 0
          ? b("Cuenta atrás estimada: ~", "Estimated countdown: ~") +
            chatDuration(remaining)
          : b(
              "Superando la estimación; sigue pendiente.",
              "Taking longer than estimated; still pending.",
            );
    const elapsed = active()
      ? b("Transcurrido: ", "Elapsed: ") +
        chatDuration(now - (job.started || job.created))
      : "";
    timerLine.textContent = [clock, elapsed].filter(Boolean).join(" · ");
    if (connectionError) {
      stateLine.textContent = b(
        "Estado sin confirmar: no hay comunicación con el portal",
        "Status unconfirmed: cannot reach the portal",
      );
      explanation.textContent = b(
        "La consulta podría seguir en curso. Comprobaremos su estado sin volver a enviarla.",
        "The request may still be in progress. We will check its status without resending it.",
      );
    } else if (submitError) {
      stateLine.textContent = b("Pregunta no enviada", "Question not sent");
      explanation.textContent = b(
        "Corrige el problema indicado. Tu pregunta sigue en el formulario.",
        "Correct the reported problem. Your question is still in the form.",
      );
    } else if (submitting) {
      stateLine.textContent = b(
        "Registrando la pregunta…",
        "Submitting the question…",
      );
      explanation.textContent = b(
        "Esperando confirmación del portal.",
        "Waiting for the portal to confirm receipt.",
      );
    } else if (job?.status === "queued") {
      stateLine.textContent = b(
        "En cola · todavía no se ha enviado al modelo",
        "Queued · not sent to the model yet",
      );
      explanation.textContent =
        b(
          "Se enviará automáticamente cuando termine el turno actual. Posición: ",
          "It will be sent automatically after the current turn. Queue position: ",
        ) +
        job.queue_position +
        b(
          ". La captura de logs continúa. Puedes salir y volver a esta conversación.",
          ". Log capture continues. You can leave and return to this conversation.",
        );
    } else if (job?.status === "running") {
      stateLine.textContent = b(
        "Consultando el modelo · esperando su respuesta",
        "Querying the model · waiting for its response",
      );
      explanation.textContent =
        job.model +
        " · " +
        b("Límite de espera: ", "Response timeout: ") +
        chatDuration(job.timeout_seconds) +
        b(
          ". La respuesta aparecerá completa al terminar.",
          ". The complete response will appear when ready.",
        );
    } else if (job?.status === "completed") {
      stateLine.textContent = b("Respuesta recibida", "Response received");
      explanation.textContent = b(
        "La respuesta está guardada en esta conversación.",
        "The answer is saved in this conversation.",
      );
      timerLine.textContent =
        b("Tiempo de consulta: ", "Query time: ") +
        chatDuration(job.finished - job.started);
    } else if (job?.status === "failed") {
      stateLine.textContent =
        job.error_code === "model_timeout"
          ? b("Tiempo de espera agotado", "Model response timed out")
          : b("La consulta ha fallado", "The request failed");
      explanation.textContent =
        (job.error_code === "model_timeout"
          ? b(
              "No llegó una respuesta completa en ",
              "No complete answer arrived within ",
            ) +
            chatDuration(job.timeout_seconds) +
            ". "
          : "") +
        b(
          "La pregunta se conserva. No se reintentará automáticamente; revisa el modelo o pulsa Reintentar.",
          "Your question is kept. There is no automatic resend; check the model or click Retry.",
        );
    } else if (job?.status === "interrupted") {
      stateLine.textContent = b("Consulta interrumpida", "Request interrupted");
      explanation.textContent = b(
        "El portal se reinició durante la consulta. La pregunta se conserva; puedes reintentarla.",
        "The portal restarted during this request. Your question is kept; you can retry it.",
      );
    } else if (job?.status === "cancelled") {
      stateLine.textContent = b(
        "Pregunta cancelada antes del envío",
        "Question cancelled before sending",
      );
      explanation.textContent = b(
        "Esta pregunta no llegó al modelo.",
        "This question was not sent to the model.",
      );
    } else {
      stateLine.textContent = model.busy
        ? b(
            "Modelo ocupado · puedes poner tu pregunta en cola",
            "Model busy · you can queue your question",
          )
        : b("Listo para recibir tu pregunta", "Ready for your question");
      explanation.textContent = b(
        "Ver el contexto no envía una consulta. Pulsa Consultar o Poner pregunta en cola para enviarla.",
        "Previewing context does not submit a question. Click Ask or Queue question to send it.",
      );
    }
    if (expected != null && !connectionError && (!job || active())) {
      explanation.textContent +=
        " " +
        b("Tiempo habitual del modelo: ~", "Typical model time: ~") +
        chatDuration(expected) +
        " (" +
        estimate.samples +
        b(
          " llamadas recientes). Es orientativo; la cola, el contexto y otras cargas pueden alargarlo.",
          " recent calls). This is an estimate; the queue, context and other workloads can increase it.",
        );
    } else if (expected == null && (!job || active())) {
      explanation.textContent += b(
        " Aún no hay suficientes llamadas correctas para estimar el tiempo.",
        " There are no successful calls yet to estimate duration.",
      );
    }
  }

  function accept(next) {
    if (!root.isConnected) return;
    job = next;
    receivedAt = Date.now();
    connectionError = "";
    pendingSubmission = null;
    submitError = "";
    if (active()) {
      input.value = job.request.message;
      chatDraft = input.value;
    }
    if (job.status === "completed" && !displayed.has(job.id)) {
      conversation.append(
        el("div", job.request.message, "message"),
        chatReply(job.result),
      );
      displayed.add(job.id);
      if (input.value === job.request.message) {
        input.value = "";
        chatDraft = "";
      }
      preview.replaceChildren();
    }
    draw();
  }

  async function poll() {
    if (!root.isConnected || submitting) return;
    try {
      if (pendingSubmission) {
        const all = await api(
          "/api/chat/requests?machine_id=" +
            encodeURIComponent(machineId) +
            "&problem_id=" +
            encodeURIComponent(problemId),
        );
        const found = all.find(
          (j) => j.client_request_id === pendingSubmission.request_id,
        );
        if (found) accept(found);
        else {
          connectionError = b(
            "El portal no confirma haber registrado la pregunta. Puedes comprobar de nuevo su estado.",
            "The portal has not confirmed this question was recorded. You can check its status again.",
          );
          draw();
        }
      } else if (active()) accept(await api("/api/chat/requests/" + job.id));
      else {
        model = await api("/api/chat/model-status");
        connectionError = "";
        draw();
      }
    } catch (error) {
      connectionError = error.message;
      draw();
    }
  }

  async function submit() {
    if (active() || submitting) return;
    if (!input.value.trim()) return;
    pendingSubmission ||= { ...request(), request_id: crypto.randomUUID() };
    submitting = true;
    connectionError = "";
    submitError = "";
    draw();
    try {
      accept(await api("/api/chat/requests", pendingSubmission));
    } catch (error) {
      if (error.status && error.status < 500) {
        pendingSubmission = null;
        submitError = error.message;
      } else connectionError = error.message;
    } finally {
      submitting = false;
      draw();
    }
  }
  form.onsubmit = async (event) => {
    event.preventDefault();
    await submit();
  };
  async function previewContext() {
    try {
      const context = await api("/api/chat/context", request());
      if (root.isConnected) preview.replaceChildren(contextDisclosure(context));
    } catch (error) {
      diagnostic.textContent = error.message;
    }
  }
  form.append(
    machine,
    question,
    actions(send, button(t("Ver contexto antes de enviar"), previewContext)),
  );
  panelBox.append(
    el(
      "p",
      t(
        problem
          ? "Esta conversación incluye el hallazgo seleccionado, la máquina y una muestra de sus evidencias. El contexto se ajusta al modelo y los recortes se muestran."
          : "Consulta una muestra acotada del histórico de la máquina. Las propuestas de filtros se revisan antes de aplicarlas.",
      ),
    ),
    form,
    status,
    preview,
  );
  root.append(panelBox, conversation);
  try {
    const params =
      "?machine_id=" +
      encodeURIComponent(machineId) +
      "&problem_id=" +
      encodeURIComponent(problemId);
    const [history, jobs, info] = await Promise.all([
      api("/api/chat/history" + params),
      api("/api/chat/requests" + params),
      api("/api/chat/model-status"),
    ]);
    model = info;
    for (const c of history) {
      conversation.append(
        el("div", c.question, "message"),
        chatReply(c.response),
      );
      if (c.request_id) displayed.add(c.request_id);
    }
    if (jobs.length)
      accept(
        jobs.find((j) => ["queued", "running"].includes(j.status)) ||
          jobs.at(-1),
      );
    else draw();
  } catch (error) {
    connectionError = error.message;
    draw();
  }
  if (problem && chatDraft && !active()) await previewContext();
  const clock = setInterval(() => {
    if (!root.isConnected) clearInterval(clock);
    else if (active()) draw();
  }, 1000);
  async function repeat() {
    if (!root.isConnected) return;
    await poll();
    if (root.isConnected) setTimeout(repeat, 2000);
  }
  setTimeout(repeat, 2000);
}
