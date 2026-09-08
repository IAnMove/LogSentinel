"use strict";

// Provider instructions checked against the official links below on this date.
// Keep examples static: documentation must never receive saved credentials.
const notificationDocsChecked = "2026-09-08";

function notificationGuide(kind, slackMode = "webhook") {
  const b = bilingual;
  const guides = {
    telegram: {
      name: "Telegram",
      fields: b(
        "Token de Telegram y Chat ID de Telegram",
        "Telegram token and Telegram chat ID",
      ),
      steps: [
        b(
          "Abre @BotFather en Telegram, envía /newbot y copia el token del bot en «Token de Telegram».",
          "Open @BotFather in Telegram, send /newbot and paste the bot token into “Telegram token”.",
        ),
        b(
          "Abre un chat con tu nuevo bot y envíale /start. Para un grupo, añade el bot y envía /start@NombreDelBot en ese grupo.",
          "Open a chat with your new bot and send /start. For a group, add the bot and send /start@YourBotName in that group.",
        ),
        b(
          "Abre la URL de ejemplo sustituyendo REPLACE_TOKEN. Busca message.chat.id en el resultado y cópialo en «Chat ID de Telegram», incluido el signo negativo si aparece.",
          "Open the example URL after replacing REPLACE_TOKEN. Find message.chat.id in the result and paste it into “Telegram chat ID”, including its minus sign if present.",
        ),
      ],
      example: "https://api.telegram.org/botREPLACE_TOKEN/getUpdates",
      note: b(
        "Si result está vacío, manda otro mensaje. Usa preferiblemente un bot dedicado: getUpdates no funciona con un webhook activo y otro programa puede haber consumido los mensajes.",
        "If result is empty, send another message. Prefer a dedicated bot: getUpdates cannot run with an active webhook, and another program may have consumed the messages.",
      ),
      links: [
        ["BotFather", "https://t.me/BotFather"],
        ["Telegram · Bot tutorial", "https://core.telegram.org/bots/tutorial"],
        [
          "Telegram · getUpdates",
          "https://core.telegram.org/bots/api#getupdates",
        ],
      ],
    },
    slack: {
      name: "Slack",
      fields: b("URL webhook", "Webhook URL"),
      steps: [
        b(
          "En Slack API, crea una app para tu espacio de trabajo; puedes llamarla LogSentinel.",
          "In Slack API, create an app for your workspace; you can name it LogSentinel.",
        ),
        b(
          "En la configuración de la app, abre Incoming Webhooks y activa Activate Incoming Webhooks.",
          "In the app settings, open Incoming Webhooks and enable Activate Incoming Webhooks.",
        ),
        b(
          "Pulsa Add New Webhook to Workspace, elige el canal y autoriza. Copia la Webhook URL en el campo «URL webhook» de este formulario.",
          "Choose Add New Webhook to Workspace, select the channel and authorize. Paste the Webhook URL into this form’s “Webhook URL” field.",
        ),
      ],
      note: b(
        "Para un canal privado debes pertenecer a él. Si tienes un token que empieza por xoxb-, cambia «Conexión de Slack» a «Token de bot + canal».",
        "For a private channel, you must be a member. If you have a token starting with xoxb-, change “Slack connection” to “Bot token + channel”.",
      ),
      links: [
        [
          "Slack · Incoming webhooks",
          "https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/",
        ],
      ],
    },
    slack_bot: {
      name: bilingual("Slack con token de bot", "Slack with a bot token"),
      fields: b(
        "Token de bot de Slack e ID del canal de Slack",
        "Slack bot token and Slack channel ID",
      ),
      steps: [
        b(
          "En la configuración de tu app de Slack, abre OAuth & Permissions. Añade chat:write en Bot Token Scopes e instala o reinstala la app en tu espacio de trabajo.",
          "In your Slack app settings, open OAuth & Permissions. Add chat:write under Bot Token Scopes and install or reinstall the app in your workspace.",
        ),
        b(
          "Copia el Bot User OAuth Token, que empieza por xoxb-, en «Token de bot de Slack».",
          "Paste the Bot User OAuth Token, starting with xoxb-, into “Slack bot token”.",
        ),
        b(
          "Invita la app al canal donde quieres los avisos, por ejemplo con /invite @TuApp.",
          "Invite the app to the notification channel, for example with /invite @YourApp.",
        ),
        b(
          "Haz clic derecho en el canal → Ver detalles del canal. Copia el ID que aparece abajo (por ejemplo C0123456789) y pégalo en «ID del canal de Slack».",
          "Right-click the channel → View channel details. Copy the ID at the bottom (for example C0123456789) and paste it into “Slack channel ID”.",
        ),
      ],
      note: b(
        "Este modo envía directamente con chat.postMessage. Un token xapp-, un Client Secret o un Signing Secret no sirve aquí. No necesitas una URL webhook.",
        "This mode sends directly through chat.postMessage. An xapp- token, Client Secret or Signing Secret will not work here. No webhook URL is needed.",
      ),
      links: [
        [
          "Slack · App setup",
          "https://docs.slack.dev/app-management/quickstart-app-settings/",
        ],
        [
          "Slack · chat.postMessage",
          "https://docs.slack.dev/reference/methods/chat.postMessage/",
        ],
        ["Slack · Tokens", "https://docs.slack.dev/authentication/tokens/"],
      ],
    },
    discord: {
      name: "Discord",
      fields: b("URL webhook", "Webhook URL"),
      steps: [
        b(
          "En Discord, abre Ajustes del servidor → Integraciones → Webhooks y crea un webhook.",
          "In Discord, open Server Settings → Integrations → Webhooks and create a webhook.",
        ),
        b(
          "Elige el canal de texto y un nombre, por ejemplo LogSentinel. Guarda los cambios.",
          "Choose the text channel and a name, such as LogSentinel. Save the changes.",
        ),
        b(
          "Pulsa Copiar URL de webhook y pégala en «URL webhook» de este formulario.",
          "Choose Copy Webhook URL and paste it into this form’s “Webhook URL” field.",
        ),
      ],
      note: b(
        "Si no puedes crear webhooks, pide a quien administra el servidor que lo configure. No hace falta crear un bot para este destino.",
        "If you cannot create webhooks, ask your server administrator to configure one. This destination does not require a bot.",
      ),
      links: [
        [
          "Discord · Webhooks",
          "https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks",
        ],
      ],
    },
    hermes: {
      name: "Hermes",
      fields: b(
        "URL webhook y Secreto de firma Hermes",
        "Webhook URL and Hermes signing secret",
      ),
      steps: [
        b(
          "En la máquina de Hermes Agent, ejecuta hermes gateway setup y habilita Webhooks. Configura también el servicio de salida, por ejemplo Telegram, y arranca el gateway.",
          "On the Hermes Agent machine, run hermes gateway setup and enable Webhooks. Also configure the delivery service, such as Telegram, and start the gateway.",
        ),
        b(
          "Ejecuta el ejemplo en Hermes sustituyendo REPLACE_CHAT por tu chat ID. Crea la ruta logsentinel con entrega directa, sin otra llamada al LLM.",
          "Run the example in Hermes after replacing REPLACE_CHAT with your chat ID. It creates the logsentinel route with direct delivery, without another LLM call.",
        ),
        b(
          "Copia la URL y el secreto que devuelve Hermes en «URL webhook» y «Secreto de firma Hermes». La URL debe ser accesible desde el servidor de LogSentinel; ajusta el host si apunta a localhost.",
          "Paste the URL and secret returned by Hermes into “Webhook URL” and “Hermes signing secret”. The URL must be reachable from the LogSentinel server; adjust the host if it points to localhost.",
        ),
      ],
      example:
        'hermes webhook subscribe logsentinel --deliver telegram --deliver-chat-id "REPLACE_CHAT" --deliver-only --prompt "[{severity}] {machine}: {title} — {summary}"',
      note: b(
        "También puedes usar la plantilla de abajo para configurar la ruta manualmente. El puerto predeterminado es 8644 y la ruta /webhooks/logsentinel. LogSentinel firma los envíos automáticamente.",
        "Alternatively, use the template below to configure the route manually. The default port is 8644 and the path is /webhooks/logsentinel. LogSentinel signs requests automatically.",
      ),
      template: "hermes",
      links: [
        [
          "Hermes Agent · Webhooks",
          "https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/",
        ],
      ],
    },
    n8n: {
      name: "n8n",
      fields: b("URL webhook y Cabeceras JSON", "Webhook URL and JSON headers"),
      steps: [
        b(
          "Importa la plantilla de abajo en n8n, o crea un flujo con un nodo Webhook: método POST y respuesta Immediately.",
          "Import the template below into n8n, or create a workflow with a Webhook node: POST method and Immediately response.",
        ),
        b(
          "Configura Header Auth en el Webhook con un nombre y un valor secreto. En «Cabeceras JSON» introduce la misma pareja, como en el ejemplo, sustituyendo REPLACE_ME.",
          "Configure Header Auth on the Webhook with a header name and secret value. Put the same pair in “JSON headers”, as in the example, replacing REPLACE_ME.",
        ),
        b(
          "Conecta el Webhook al nodo que enviará el aviso y configura sus credenciales. En la plantilla, sustituye «Configure destination», que por sí solo no envía nada.",
          "Connect the Webhook to the node that will send the notification and configure its credentials. In the template, replace “Configure destination”, which does not send anything itself.",
        ),
        b(
          "Publica el flujo y copia su Production URL en «URL webhook». La Test URL solo escucha durante las pruebas de n8n.",
          "Publish the workflow and paste its Production URL into “Webhook URL”. The Test URL only listens during n8n tests.",
        ),
      ],
      example: '{"X-LogSentinel-Key": "REPLACE_ME"}',
      note: b(
        "Un resultado accepted confirma que n8n recibió el aviso. Comprueba Executions en n8n y el destino final para confirmar el resto del flujo.",
        "An accepted result confirms that n8n received the notification. Check Executions in n8n and the final destination to confirm the rest of the workflow.",
      ),
      template: "n8n",
      links: [
        [
          "n8n · Webhook",
          "https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/",
        ],
        [
          "n8n · Header Auth",
          "https://docs.n8n.io/integrations/builtin/credentials/webhook/",
        ],
      ],
    },
    system: {
      name: b("notificaciones del sistema", "system notifications"),
      fields: b(
        "Sin URL ni credenciales; solo los ajustes comunes del destino",
        "No URL or credentials; only the common destination settings",
      ),
      steps: [
        b(
          "Instala notify-send con el gestor de paquetes de tu distribución en la máquina donde corre LogSentinel.",
          "Install notify-send using your distribution’s package manager on the machine running LogSentinel.",
        ),
        b(
          "Ejecuta el portal con acceso a la sesión gráfica y al bus de sesión del usuario. Un servicio sin ese entorno no puede mostrar notificaciones de escritorio.",
          "Run the portal with access to the user’s graphical session and session bus. A service without that environment cannot display desktop notifications.",
        ),
        b(
          "Selecciona Sistema y configura la gravedad y el ámbito de los avisos.",
          "Select System and configure notification severity and scope.",
        ),
      ],
      note: b(
        "El aviso aparece en el escritorio de la máquina que ejecuta el portal, no en el navegador ni en el ordenador desde el que entras por SSH.",
        "The notification appears on the desktop of the machine running the portal, not in the browser or on the computer you use to connect over SSH.",
      ),
      links: [
        [
          "freedesktop.org · Desktop notifications",
          "https://specifications.freedesktop.org/notification/latest/",
        ],
      ],
    },
    webhook: {
      name: b("un webhook genérico", "a generic webhook"),
      fields: b(
        "URL webhook y, si el receptor lo necesita, Cabeceras JSON",
        "Webhook URL and, if required by the receiver, JSON headers",
      ),
      steps: [
        b(
          "Prepara una URL HTTP(S) accesible desde el servidor de LogSentinel que reciba peticiones POST con JSON.",
          "Prepare an HTTP(S) URL reachable from the LogSentinel server that accepts POST requests with JSON.",
        ),
        b(
          "Pégala en «URL webhook». Si el receptor necesita autenticación por cabecera, añádela en «Cabeceras JSON», sustituyendo REPLACE_ME en el ejemplo.",
          "Paste it into “Webhook URL”. If the receiver requires header authentication, add it in “JSON headers”, replacing REPLACE_ME in the example.",
        ),
        b(
          "Adapta el receptor al JSON de LogSentinel: incluye title, summary, severity, machine, problem_id y delivery_id. Devuelve un estado HTTP 2xx antes de 15 segundos.",
          "Adapt the receiver to LogSentinel’s JSON: it includes title, summary, severity, machine, problem_id and delivery_id. Return an HTTP 2xx status within 15 seconds.",
        ),
      ],
      example: '{"Authorization": "Bearer REPLACE_ME"}',
      note: b(
        "accepted significa que el receptor aceptó la petición. Si otro servicio exige un formato distinto, transfórmalo en el receptor o mediante n8n.",
        "accepted means the receiver accepted the request. If another service needs a different format, transform it in the receiver or through n8n.",
      ),
      links: [],
    },
    file: {
      name: b("un archivo local", "a local file"),
      fields: b(
        "Nombre del archivo local, Rotar archivo de avisos y Copias comprimidas",
        "Local file name, notification rotation size and compressed archives",
      ),
      steps: [
        b(
          "Introduce solo un nombre, por ejemplo alerts.jsonl. Vacío usa ese nombre; no se admiten rutas absolutas ni subcarpetas.",
          "Enter a filename only, such as alerts.jsonl. Leaving it blank uses that name; absolute paths and subdirectories are not accepted.",
        ),
        b(
          "El archivo se guarda en notifications/ dentro del directorio de datos del portal, en el servidor. Cada línea contiene un aviso JSON.",
          "The file is stored in notifications/ inside the portal’s data directory, on the server. Each line contains a JSON notification.",
        ),
        b(
          "Elige el tamaño de rotación en MiB y cuántas copias comprimidas conservar. Los archivos rotados se comprimen con gzip.",
          "Choose the rotation size in MiB and how many compressed archives to keep. Rotated files are compressed with gzip.",
        ),
      ],
      note: b(
        "Este destino registra los avisos; la retención y compresión de los logs originales se configura por separado.",
        "This destination records notifications; retention and compression of the original logs are configured separately.",
      ),
      links: [],
    },
  };
  return guides[kind === "slack" && slackMode === "bot" ? "slack_bot" : kind];
}

function notificationChannelKey(form) {
  const kind = form.elements.kind.value;
  return kind === "slack" ? "slack_" + form.elements.slack_mode.value : kind;
}

function addNotificationConfiguration(form, saved) {
  const b = bilingual,
    originalKey =
      saved.kind === "slack"
        ? "slack_" + (saved.slack_mode || "webhook")
        : saved.kind,
    mode = field(
      "slack_mode",
      b("Conexión de Slack", "Slack connection"),
      "select",
      saved.slack_mode || "webhook",
      [
        ["webhook", b("URL webhook", "Webhook URL")],
        ["bot", b("Token de bot + canal", "Bot token + channel")],
      ],
    );
  mode.classList.add("notification-slack-mode");
  form.append(mode);
  addNotificationGuide(form);

  const url = ["url", b("URL webhook", "Webhook URL"), "password"],
    headers = [
      "headers",
      b("Cabeceras JSON (opcional)", "JSON headers (optional)"),
      "textarea",
    ],
    configs = {
      system: [],
      telegram: [
        ["token", b("Token de Telegram", "Telegram token"), "password"],
        ["chat_id", t("Chat ID de Telegram"), "text"],
      ],
      slack_webhook: [url],
      slack_bot: [
        [
          "token",
          b("Token de bot de Slack", "Slack bot token"),
          "password",
          "xoxb-…",
        ],
        [
          "slack_channel",
          b("ID del canal de Slack", "Slack channel ID"),
          "text",
          "C0123456789",
        ],
      ],
      discord: [url],
      hermes: [
        url,
        [
          "secret",
          b("Secreto de firma Hermes", "Hermes signing secret"),
          "password",
        ],
        headers,
      ],
      n8n: [url, headers],
      webhook: [url, headers],
      file: [
        [
          "path",
          t("Nombre del archivo local (opcional)"),
          "text",
          "alerts.jsonl",
        ],
        ["rotation_mb", t("Rotar archivo de avisos a (MiB)"), "number"],
        ["keep_archives", t("Copias comprimidas de avisos"), "number"],
      ],
    },
    secrets = ["url", "token", "secret", "headers"];

  for (const [key, fields] of Object.entries(configs)) {
    const group = el("div", undefined, "notification-fields form-grid wide");
    group.dataset.notificationChannel = key;
    const stored = key === originalKey ? saved.configured_fields || [] : [];
    for (const [name, label, type, placeholder] of fields) {
      const value = secrets.includes(name)
        ? ""
        : ((key === originalKey ? saved[name] : undefined) ??
          { rotation_mb: 10, keep_archives: 3 }[name] ??
          "");
      const control = field("notify_" + key + "_" + name, label, type, value),
        input = control.querySelector("input,textarea");
      input.dataset.notificationField = name;
      if (placeholder) input.placeholder = placeholder;
      if (secrets.includes(name)) input.autocomplete = "off";
      if (stored.includes(name)) {
        input.placeholder = b(
          "Guardado; vacío conserva el valor",
          "Saved; blank keeps the value",
        );
        control.append(
          el(
            "small",
            b(
              "Configurado. Déjalo vacío para conservarlo.",
              "Configured. Leave blank to keep it.",
            ),
            "subtle",
          ),
        );
      }
      if (name === "headers") control.classList.add("wide");
      if (name === "rotation_mb") {
        input.min = "1";
        input.max = "1024";
      }
      if (name === "keep_archives") {
        input.min = "1";
        input.max = "50";
      }
      group.append(control);
    }
    if (
      stored.some((name) => fields.some(([fieldName]) => name === fieldName))
    ) {
      const clear = field(
        "notify_" + key + "_clear",
        t("Borrar secretos guardados al guardar"),
        "checkbox",
        false,
      );
      clear.querySelector("input").dataset.notificationField = "clear";
      clear.classList.add("wide");
      group.append(clear);
    }
    if (!fields.length)
      group.append(
        el(
          "p",
          b(
            "Este destino usa la sesión de escritorio del servidor. No requiere credenciales.",
            "This destination uses the server’s desktop session. No credentials are required.",
          ),
          "wide subtle",
        ),
      );
    form.append(group);
  }
  mode
    .querySelector("select")
    .addEventListener("change", () => syncNotificationForm(form));
  syncNotificationForm(form);
}

function syncNotificationForm(form) {
  const slack = form.elements.kind.value === "slack";
  form.querySelector(".notification-slack-mode").hidden = !slack;
  form.elements.slack_mode.disabled = !slack;
  const key = notificationChannelKey(form);
  for (const group of form.querySelectorAll("[data-notification-channel]")) {
    group.hidden = group.dataset.notificationChannel !== key;
    for (const input of group.querySelectorAll("input,textarea"))
      input.disabled = group.hidden;
  }
  updateNotificationGuide(form);
}

function notificationFormData(form) {
  const data = formData(form);
  // Hidden drafts stay in this form only; send just this provider's fields.
  for (const name of Object.keys(data))
    if (name.startsWith("notify_")) delete data[name];
  if (data.kind !== "slack") delete data.slack_mode;
  const group = form.querySelector(
    '[data-notification-channel="' + notificationChannelKey(form) + '"]',
  );
  for (const input of group.querySelectorAll("[data-notification-field]")) {
    const name = input.dataset.notificationField;
    if (name === "clear") {
      if (input.checked)
        data.clear_secrets = ["url", "token", "secret", "headers"];
    } else if (name === "headers")
      data.headers = input.value ? JSON.parse(input.value) : {};
    else
      data[name] =
        input.type === "number" ? Number(input.value) : input.value.trim();
  }
  return data;
}

function updateNotificationGuide(form) {
  const host = form.querySelector(".notification-howto"),
    guide = notificationGuide(
      form.elements.kind.value,
      form.elements.slack_mode?.value,
    );
  if (!host || !guide) return;
  host.dataset.channel = form.elements.kind.value;
  const title = el(
      "summary",
      bilingual("Cómo añadir ", "How to add ") + guide.name,
    ),
    body = el("div"),
    fields = el("p", undefined, "notification-howto-fields"),
    steps = el("ol");
  fields.append(el("strong", bilingual("Campos: ", "Fields: ")), guide.fields);
  guide.steps.forEach((step) => steps.append(el("li", step)));
  body.append(fields, steps);
  if (guide.example) {
    const example = el("pre", undefined, "notification-howto-example");
    example.append(el("code", guide.example));
    body.append(example);
  }
  if (guide.note) body.append(el("p", guide.note, "subtle"));
  if (guide.template) {
    body.append(
      button(
        t(guide.template === "hermes" ? "Plantilla Hermes" : "Plantilla n8n"),
        () => showTemplate(guide.template),
      ),
    );
  }
  body.append(
    el(
      "p",
      bilingual(
        "Para terminar: pon un nombre, elige gravedad y ámbito, activa «Destino activo» si quieres avisos automáticos y guarda. Después pulsa «Enviar prueba» en la fila del destino y revisa el resultado en «Actividad».",
        "To finish: enter a name, choose severity and scope, enable “Destination enabled” for automatic alerts, and save. Then click “Send test” in the destination’s row and check the result in “Activity”.",
      ),
      "notification-howto-finish",
    ),
  );
  const references = el("div", undefined, "notification-howto-references");
  if (guide.links.length) {
    references.append(
      el(
        "span",
        bilingual("Documentación oficial: ", "Official documentation: "),
      ),
    );
    for (const [label, url] of guide.links) {
      const link = el("a", label);
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      references.append(link);
    }
  } else {
    references.append(
      el(
        "span",
        bilingual(
          "Configuración propia de LogSentinel.",
          "LogSentinel’s built-in configuration.",
        ),
      ),
    );
  }
  references.append(
    el("span", bilingual("Revisado: ", "Checked: ") + notificationDocsChecked),
  );
  body.append(references);
  host.replaceChildren(title, body);
}

function addNotificationGuide(form) {
  form.dataset.notificationForm = "";
  const host = el("details", undefined, "notification-howto wide");
  host.open = true;
  form.append(host);
  form.elements.kind.addEventListener("change", () =>
    syncNotificationForm(form),
  );
  updateNotificationGuide(form);
}

function refreshNotificationGuides() {
  document
    .querySelectorAll("form[data-notification-form]")
    .forEach(syncNotificationForm);
}
