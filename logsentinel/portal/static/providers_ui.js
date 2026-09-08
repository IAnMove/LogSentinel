"use strict";

const llmServers = {
  custom: { label: "API compatible / Custom", provider: "openai", url: "" },
  ollama: {
    label: "Ollama",
    provider: "ollama",
    url: "http://127.0.0.1:11434",
  },
  llama_cpp: {
    label: "llama.cpp",
    provider: "openai",
    url: "http://127.0.0.1:8080/v1",
  },
  lm_studio: {
    label: "LM Studio",
    provider: "openai",
    url: "http://127.0.0.1:1234/v1",
  },
  vllm: { label: "vLLM", provider: "openai", url: "http://127.0.0.1:8000/v1" },
  litellm: {
    label: "LiteLLM Proxy",
    provider: "openai",
    url: "http://127.0.0.1:4000/v1",
  },
  balancer: {
    label: "Balanceador / Load balancer",
    provider: "openai",
    url: "",
  },
};

function llmFormSettings(form, cfg) {
  const d = formData(form),
    context = d.context_tokens ?? cfg.context_tokens;
  const maxTokens = d.max_tokens ?? cfg.llm.max_tokens;
  return {
    llm: {
      provider: d.provider,
      server_type: d.server_type,
      base_url: d.base_url.trim(),
      model: d.model.trim(),
      api_key: d.api_key || "",
      max_tokens: maxTokens,
      timeout_seconds: d.timeout_seconds ?? cfg.llm.timeout_seconds,
      enable_thinking:
        d.enable_thinking == null
          ? d.base_url.trim() === cfg.llm.base_url &&
            d.provider === cfg.llm.provider
            ? cfg.llm.enable_thinking
            : null
          : d.enable_thinking === "auto"
            ? null
            : d.enable_thinking === "true",
    },
    context_tokens: context,
    input_budget:
      d.input_budget ??
      Math.max(512, Math.min(cfg.input_budget, context - maxTokens - 2048)),
    remote_allowed: d.remote_allowed ?? cfg.remote_allowed,
    clear_api_key: d.clear_api_key || false,
  };
}

function llmModelPicker(form, cfg) {
  const group = el("div", undefined, "model-picker"),
    choiceField = field("", t("Modelo"), "select", "manual"),
    choice = choiceField.querySelector("select"),
    manualField = field(
      "model",
      bilingual("ID de modelo (manual)", "Model ID (manual)"),
      "text",
      cfg.llm.model,
    ),
    input = manualField.querySelector("input"),
    status = el("p", "", "subtle");
  status.setAttribute("role", "status");
  let models = [],
    revision = 0,
    timer;
  const manualLabel = () =>
    bilingual("Escribir ID de modelo manualmente…", "Enter model ID manually…");
  function populate() {
    choice.replaceChildren();
    const manual = el("option", manualLabel());
    manual.value = "manual";
    choice.append(manual);
    models.forEach((id, index) => {
      const option = el("option", id);
      option.value = "model:" + index;
      choice.append(option);
    });
    const selected = models.indexOf(input.value);
    choice.value = selected >= 0 ? "model:" + selected : "manual";
    manualField.hidden = selected >= 0;
  }
  choice.onchange = () => {
    const manual = choice.value === "manual";
    manualField.hidden = !manual;
    if (manual) input.focus();
    else {
      input.value = models[Number(choice.value.slice(6))];
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  };
  const connection = () => {
    const value = (name) => form.elements.namedItem(name);
    return {
      llm: {
        provider: value("provider").value,
        base_url: value("base_url").value.trim(),
        api_key: value("api_key").value,
      },
      clear_api_key: value("clear_api_key").checked,
      remote_allowed: value("remote_allowed")?.checked ?? cfg.remote_allowed,
    };
  };
  async function refreshModels() {
    clearTimeout(timer);
    const requestId = ++revision;
    if (!form.isConnected) return;
    const request = connection();
    let url;
    try {
      url = new URL(request.llm.base_url);
      if (!["http:", "https:"].includes(url.protocol)) throw Error();
    } catch {
      status.textContent = bilingual(
        "Introduce una URL de servidor válida para consultar sus modelos.",
        "Enter a valid server URL to list its models.",
      );
      return;
    }
    if (
      !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) &&
      !request.remote_allowed
    ) {
      status.textContent = bilingual(
        "Activa la autorización de servidor remoto para consultar sus modelos.",
        "Allow access to the configured remote server to list its models.",
      );
      return;
    }
    status.textContent = bilingual("Consultando modelos…", "Loading models…");
    try {
      const info = await api("/api/model/info?models_only=true", request);
      if (requestId !== revision || !form.isConnected) return;
      models = [
        ...new Set(
          info.models.filter((m) => typeof m === "string" && m.trim()),
        ),
      ];
      populate();
      status.textContent = models.length
        ? models.length +
          bilingual(
            " modelos disponibles. Seleccionar no guarda ni carga el modelo.",
            " models available. Selecting does not save or load the model.",
          )
        : bilingual(
            "El servidor no publica modelos. Puedes introducir el ID manualmente.",
            "The server publishes no models. You can enter the ID manually.",
          );
      if (models.length && choice.value === "manual" && input.value)
        status.textContent +=
          " " +
          bilingual(
            "El ID actual no aparece en esta lista.",
            "The current ID is not in this list.",
          );
    } catch (error) {
      if (requestId !== revision || !form.isConnected) return;
      models = [];
      populate();
      status.textContent =
        bilingual(
          "No se pudo cargar la lista. Puedes usar un ID manual o volver a intentarlo. ",
          "Could not load the list. You can enter an ID manually or retry. ",
        ) + error.message;
    }
  }
  function changed(load = true) {
    clearTimeout(timer);
    revision++;
    models = [];
    populate();
    status.textContent = bilingual(
      "Actualiza la lista para este servidor.",
      "Refresh the list for this server.",
    );
    if (load) timer = setTimeout(refreshModels, 500);
  }
  form.addEventListener("input", (event) => {
    if (["base_url", "api_key"].includes(event.target.name))
      changed(event.target.name === "base_url");
  });
  form.addEventListener("change", (event) => {
    if (
      [
        "server_type",
        "provider",
        "base_url",
        "api_key",
        "clear_api_key",
        "remote_allowed",
      ].includes(event.target.name)
    )
      changed();
  });
  populate();
  group.append(
    choiceField,
    manualField,
    button(bilingual("Actualizar modelos", "Refresh models"), refreshModels),
    status,
  );
  timer = setTimeout(refreshModels, 500);
  return group;
}

function llmServerFields(form, cfg) {
  const currentType =
    cfg.llm.provider === "ollama" ? "ollama" : cfg.llm.server_type || "custom";
  const server = field(
    "server_type",
    bilingual("Servidor LLM", "LLM server"),
    "select",
    currentType,
    Object.entries(llmServers).map(([id, spec]) => [
      id,
      id === "custom"
        ? bilingual("API compatible personalizada", "Custom compatible API")
        : id === "balancer"
          ? bilingual("Balanceador compatible", "Compatible load balancer")
          : spec.label,
    ]),
  );
  form.append(
    server,
    field(
      "provider",
      bilingual("Protocolo API", "API protocol"),
      "select",
      cfg.llm.provider,
      [
        ["ollama", "Ollama /api/chat"],
        ["openai", "OpenAI-compatible /v1/chat/completions"],
      ],
    ),
    field("base_url", t("URL del servidor"), "url", cfg.llm.base_url),
    llmModelPicker(form, cfg),
    field("api_key", t("Clave API (vacío conserva)"), "password", ""),
    field(
      "clear_api_key",
      bilingual("Eliminar clave API guardada", "Clear saved API key"),
      "checkbox",
      false,
    ),
  );
  const help = el("p", "", "subtle provider-help");
  const explain = () => {
    const type = form.elements.namedItem("server_type").value;
    help.textContent =
      (type === "balancer" || type === "litellm"
        ? bilingual(
            "Usa la URL y el alias de modelo publicados por tu proxy. El balanceador debe admitir chat/completions, mensajes de sistema y salida JSON. Un proxy local también puede reenviar datos a proveedores remotos; comprueba sus rutas.",
            "Use the URL and model alias published by your proxy. The balancer must support chat/completions, system messages and JSON output. A local proxy can also forward data to remote providers; check its routes.",
          )
        : bilingual(
            "La URL es editable: los puertos sugeridos pueden estar ocupados. Elige un modelo instalado y consulta su contexto cargado. No se instala ni descarga ningún modelo desde este formulario.",
            "The URL is editable: suggested ports may be in use. Choose an installed model and check its loaded context. This form does not install or download models.",
          )) +
      " " +
      bilingual(
        "Una clave vacía solo conserva la anterior si el servidor y el protocolo son los mismos.",
        "A blank key only keeps the previous key when the server and protocol are unchanged.",
      );
  };
  server.querySelector("select").onchange = () => {
    const spec = llmServers[server.querySelector("select").value];
    form.elements.namedItem("provider").value = spec.provider;
    form.elements.namedItem("base_url").value = spec.url;
    form.elements.namedItem("api_key").value = "";
    const thinking = form.elements.namedItem("enable_thinking");
    if (thinking) thinking.value = "auto";
    explain();
  };
  form.elements.namedItem("provider").onchange = () => {
    server.querySelector("select").value =
      form.elements.namedItem("provider").value === "ollama"
        ? "ollama"
        : "custom";
    explain();
  };
  explain();
  form.append(help);
  const result = el("div", undefined, "provider-result"),
    tools = actions(
      button(
        bilingual(
          "Probar estos ajustes sin guardar",
          "Test these settings without saving",
        ),
        async () => {
          result.replaceChildren(el("p", t("Comprobando modelo…")));
          try {
            const tested = llmFormSettings(form, cfg);
            const data = await api("/api/model/test", tested);
            if (
              JSON.stringify(tested) !==
              JSON.stringify(llmFormSettings(form, cfg))
            ) {
              result.replaceChildren(
                el(
                  "p",
                  bilingual(
                    "Los ajustes cambiaron durante la prueba. Vuelve a probar la configuración actual.",
                    "Settings changed during the test. Test the current configuration again.",
                  ),
                ),
              );
              return;
            }
            result.replaceChildren(
              el(
                "strong",
                bilingual("Conexión verificada", "Connection verified"),
              ),
              el(
                "p",
                data.base_url +
                  " · " +
                  data.model +
                  " · " +
                  Number(data.seconds).toFixed(1) +
                  " s",
              ),
              el(
                "p",
                bilingual("Entrada / salida: ", "Input / output: ") +
                  (data.input_tokens ?? "?") +
                  " / " +
                  (data.output_tokens ?? "?") +
                  " tokens",
              ),
              el(
                "p",
                data.saved_config
                  ? bilingual(
                      "Coincide con la configuración activa.",
                      "Matches the active configuration.",
                    )
                  : bilingual(
                      "Prueba del formulario. Guarda para usar estos ajustes en el análisis.",
                      "Form test only. Save to use these settings for analysis.",
                    ),
              ),
              el(
                "p",
                bilingual(
                  "La prueba de conexión no mide calidad de detección.",
                  "The connection test does not measure detection quality.",
                ),
                "subtle",
              ),
            );
          } catch (error) {
            result.replaceChildren(el("p", error.message, "error"));
          }
        },
      ),
    );
  tools.classList.add("provider-tools");
  form.append(tools, result);
  form.addEventListener("input", () => result.replaceChildren());
  form.addEventListener("change", () => result.replaceChildren());
}
