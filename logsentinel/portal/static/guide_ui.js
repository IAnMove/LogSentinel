"use strict";

function guideDetails(title, ...children) {
  const details = el("details", undefined, "guide-details wide");
  details.append(el("summary", title), ...children);
  return details;
}

function guideFields(form, title, names) {
  const contents = el("div", undefined, "form-grid");
  const details = guideDetails(title, contents);
  details.dataset.guideFields = names.join(",");
  for (const name of names) {
    const control = form.elements.namedItem(name);
    if (control)
      contents.append(
        control.closest(".model-picker") || control.closest("label"),
      );
  }
  form.append(details);
  return details;
}

function fieldHelp(form, name, text) {
  const control = form.elements.namedItem(name);
  if (!control) return;
  const hint = el("small", text, "field-help");
  hint.id = "hint-" + name;
  control.setAttribute("aria-describedby", hint.id);
  control.closest("label").append(hint);
}

function howTo(title, steps) {
  const box = el("section", undefined, "howto"),
    list = el("ol");
  box.append(el("h3", title), list);
  for (const step of steps) list.append(el("li", step));
  return box;
}

function modelConnectionGuide(form) {
  const box = guideDetails(
    bilingual("Dónde encuentro estos datos", "Where to find these details"),
  );
  box.open = true;
  const content = el("div");
  box.append(content);
  const update = () => {
    const type = form.elements.namedItem("server_type").value;
    const ollama = type === "ollama",
      studio = type === "lm_studio";
    content.replaceChildren(
      howTo(bilingual("Tres pasos", "Three steps"), [
        ollama
          ? bilingual(
              "Abre Ollama en el equipo que ejecuta el modelo. Si lo usas desde terminal, «ollama list» muestra los modelos instalados.",
              "Open Ollama on the computer running your model. In a terminal, “ollama list” shows installed models.",
            )
          : studio
            ? bilingual(
                "En LM Studio, abre Developer y activa el servidor. Copia su dirección; en este formulario la URL compatible termina en /v1.",
                "In LM Studio, open Developer and start the server. Copy its address; the compatible URL in this form ends in /v1.",
              )
            : bilingual(
                "Abre el programa o proxy que sirve tu modelo y copia su URL de API. Para una API compatible, suele terminar en /v1.",
                "Open the program or proxy serving your model and copy its API URL. A compatible API URL usually ends in /v1.",
              ),
        bilingual(
          "Pega la URL abajo. 127.0.0.1 significa el equipo donde corre LogSentinel, no el navegador. Para otro equipo, usa su dirección de red y autoriza el servidor remoto.",
          "Paste the URL below. 127.0.0.1 means the computer running LogSentinel, not your browser. For another computer, use its network address and allow the remote server.",
        ),
        bilingual(
          "Pulsa «Actualizar modelos», elige uno instalado y continúa con la prueba. Si el servidor pide clave API, usa la de ese servidor; no la clave con la que entras a LogSentinel.",
          "Select “Refresh models”, choose an installed model and continue with the test. If the server requires an API key, use its key, not your LogSentinel sign-in key.",
        ),
      ]),
    );
    if (ollama || studio) {
      const link = el(
        "a",
        bilingual("Guía oficial del servidor", "Official server guide"),
      );
      link.href = ollama
        ? "https://docs.ollama.com/quickstart"
        : "https://lmstudio.ai/docs/developer/rest/quickstart";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      content.append(link);
    }
  };
  form.addEventListener("change", (event) => {
    if (["server_type", "provider"].includes(event.target.name)) update();
  });
  update();
  form.refreshConnectionGuide = update;
  return box;
}

function quickStartMap() {
  const box = panel(bilingual("Dónde está cada cosa", "Where to find things"));
  const grid = el("div", undefined, "guide-grid");
  for (const [page, title, description] of [
    [
      "capacity",
      bilingual("¿Está leyendo mis logs?", "Is it reading my logs?"),
      bilingual(
        "Mira qué entra, qué se analiza y qué espera. Empieza aquí si va lento.",
        "See incoming, reviewed and waiting logs. Start here if it feels slow.",
      ),
    ],
    [
      "source",
      bilingual("Cambiar los logs que llegan", "Change the incoming logs"),
      bilingual(
        "Activa fuentes, cambia rutas o comprueba la lectura.",
        "Enable sources, change paths or test reading.",
      ),
    ],
    [
      "settings",
      bilingual("Ajustar el modelo", "Tune the model"),
      bilingual(
        "Conexión, perfiles de análisis y límites avanzados.",
        "Connection, analysis profiles and advanced limits.",
      ),
    ],
    [
      "rule",
      bilingual("Reducir ruido repetitivo", "Reduce repetitive noise"),
      bilingual(
        "Prueba un filtro predefinido con tus logs antes de aplicarlo.",
        "Preview a built-in filter against your logs before applying it.",
      ),
    ],
    [
      "destination",
      bilingual("Recibir avisos", "Receive alerts"),
      bilingual(
        "Configura Slack u otro destino siguiendo su guía y envía una prueba.",
        "Follow the guide for Slack or another destination, then send a test.",
      ),
    ],
    [
      "problems",
      bilingual("Entender una alerta", "Understand an alert"),
      bilingual(
        "Abre su evidencia y comprueba por qué se notificó o se silenció.",
        "Open its evidence and check why it was sent or muted.",
      ),
    ],
  ]) {
    const card = el("div", undefined, "guide-card");
    card.append(
      button(title, () => navigate(page)),
      el("p", description, "subtle"),
    );
    grid.append(card);
  }
  box.append(grid);
  return box;
}

function refreshSetupGuides() {
  for (const form of document.querySelectorAll("#content form")) {
    form.refreshConnectionGuide?.();
    form.refreshSetupFields?.();
    form.refreshSettingsDraft?.();
  }
  document.querySelector('#content [name="analysis_profile"]')?.onchange?.();
}

function analysisProfiles(form, cfg) {
  const b = bilingual,
    box = panel(
      b("Perfiles de análisis: empieza aquí", "Analysis profiles: start here"),
    );
  const profiles = [
    {
      id: "automatic",
      name: b(
        "Automático (recomendado para empezar)",
        "Automatic (recommended starting point)",
      ),
      note: b(
        "Adapta los lotes a los tiempos medidos y verifica las alertas importantes. Mantiene tu límite de entrada.",
        "Adapts batches to measured times and verifies important alerts. Keeps your input limit.",
      ),
      patch: {
        adaptive_batching: true,
        interval_seconds: 30,
        target_batch_seconds: 30,
        cycle_budget_seconds: 90,
        max_calls: 3,
        triage_thinking: false,
        verification: "important",
      },
    },
    {
      id: "small",
      name: b(
        "Lotes pequeños para un modelo lento",
        "Small batches for a slow model",
      ),
      note: b(
        "Prueba menos entrada por llamada y una llamada por ciclo. Puede aumentar la espera de la cola; mide antes de seguir reduciendo.",
        "Tries less input per call and one call per cycle. Queue waiting can increase; measure before reducing further.",
      ),
      patch: {
        adaptive_batching: true,
        input_budget: Math.min(cfg.input_budget, 3000),
        interval_seconds: 60,
        target_batch_seconds: 30,
        cycle_budget_seconds: 60,
        max_calls: 1,
        triage_thinking: false,
        verification: "important",
      },
    },
    {
      id: "verify",
      name: b("Verificar todos los candidatos", "Verify every candidate"),
      note: b(
        "Reserva una segunda lectura para todos los candidatos. Consume más tiempo; tampoco garantiza que el modelo encuentre todos los problemas.",
        "Reserves a second reading for every candidate. Uses more time; still does not guarantee the model finds every problem.",
      ),
      patch: {
        adaptive_batching: true,
        interval_seconds: 30,
        target_batch_seconds: 30,
        cycle_budget_seconds: 90,
        max_calls: 3,
        triage_thinking: false,
        verification: "all",
      },
    },
  ];
  const labels = {
    adaptive_batching: b("Ajuste automático", "Automatic tuning"),
    interval_seconds: b(
      "Espera máxima entre ciclos (s)",
      "Maximum wait between cycles (s)",
    ),
    target_batch_seconds: b("Objetivo por llamada (s)", "Target per call (s)"),
    cycle_budget_seconds: b(
      "Ventana para iniciar llamadas (s)",
      "Call dispatch window (s)",
    ),
    max_calls: b("Llamadas por ciclo", "Calls per cycle"),
    triage_thinking: b(
      "Razonamiento largo en primera lectura",
      "Extended thinking in first reading",
    ),
    verification: b("Segunda lectura", "Second reading"),
    input_budget: b(
      "Entrada máxima por lote (bytes)",
      "Maximum batch input (bytes)",
    ),
  };
  const valueLabel = (value) =>
    value === true
      ? b("Sí", "Yes")
      : value === false
        ? b("No", "No")
        : value === "important"
          ? b(
              "Candidatos de lotes con alertas altas",
              "Candidates in batches with high alerts",
            )
          : value === "all"
            ? b("Todos los candidatos", "Every candidate")
            : value === "manual"
              ? b("Bajo petición", "On request")
              : String(value);
  const selectorField = field(
    "analysis_profile",
    b("Perfil a preparar", "Profile to prepare"),
    "select",
    "automatic",
    profiles.map((p) => [p.id, p.name]),
  );
  const selector = selectorField.querySelector("select"),
    preview = el("div"),
    result = el("p", "", "profile-feedback");
  result.setAttribute("role", "status");
  const update = () => {
    const selected = profiles.find((p) => p.id === selector.value);
    preview.replaceChildren(
      el("p", selected.note),
      table(
        [
          b("Ajuste", "Setting"),
          b("Guardado", "Saved"),
          b("Propuesto", "Proposed"),
        ],
        Object.entries(selected.patch).map(([key, value]) => [
          labels[key],
          valueLabel(cfg[key]),
          valueLabel(value),
        ]),
      ),
    );
  };
  selector.onchange = update;
  box.append(
    el(
      "p",
      b(
        "Son ajustes del programa, no cambios al modelo ni reparaciones del equipo. Se aplican a todas las máquinas. Elige uno, revisa la comparación y prepáralo en el formulario; después pulsa Guardar ajustes.",
        "These tune the program; they do not change your model or repair the computer. They apply to every machine. Choose one, review the comparison and prepare it in the form; then select Save settings.",
      ),
    ),
    selectorField,
    preview,
    actions(
      button(
        b(
          "Preparar este perfil sin guardar",
          "Prepare this profile without saving",
        ),
        () => {
          const selected = profiles.find((p) => p.id === selector.value);
          for (const [name, value] of Object.entries(selected.patch)) {
            const input = form.elements.namedItem(name);
            if (input.type === "checkbox") input.checked = value;
            else input.value = value;
            input.dispatchEvent(new Event("input", { bubbles: true }));
          }
          result.textContent =
            b(
              "Perfil preparado, aún sin guardar: ",
              "Profile prepared, not saved yet: ",
            ) +
            selected.name +
            b(
              ". Revisa el formulario y pulsa Guardar ajustes.",
              ". Review the form and select Save settings.",
            );
        },
      ),
      button(
        b("Descartar cambios del formulario", "Discard form changes"),
        () => settingsViewReset(),
      ),
    ),
    result,
  );
  update();
  return box;
}

function settingsViewReset() {
  // Restore from the last state loaded by the portal; never POST a preset here.
  render();
}
