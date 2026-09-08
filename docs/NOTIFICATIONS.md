# Notification setup guides

Open **Notifications → Add** (or **Edit**) and select a channel. The expandable
**How to add [service]** section shows the setup steps, relevant form fields,
examples, and documentation for that channel. It follows the portal language
(English or Spanish). Changing the channel or language preserves the form draft.
Hermes and n8n templates are available inside their respective guides.

Each channel displays only its connection fields. Telegram asks for a token and
chat ID; Discord for its webhook URL; Hermes for its webhook and signing secret;
n8n and generic webhooks for a URL and optional headers. System notifications
need no credentials. File destinations show only filename and rotation controls.
Name, scope, severity, grouping and enabled state are shared by all destinations.

## Slack connection methods

- **Webhook URL** keeps compatibility with existing Slack destinations. Paste
  the Incoming Webhook URL; Slack already associates it with its channel.
- **Bot token + channel** asks for the **Bot User OAuth Token** (`xoxb-…`) and
  channel ID. Grant `chat:write` under **OAuth & Permissions → Bot Token Scopes**,
  install or reinstall the Slack app, and invite it to the destination channel.
  This uses `https://slack.com/api/chat.postMessage`; it does not use a custom URL
  or an app-level `xapp-` token. See [Slack's setup instructions](https://docs.slack.dev/app-management/quickstart-app-settings/)
  and [token types](https://docs.slack.dev/authentication/tokens/).

The API's `ok` value is checked even on HTTP 200, so missing permissions, invalid
tokens and inaccessible channels cannot appear as successful deliveries. Known
errors have actionable messages; arbitrary response bodies are not displayed.
Token renewal is manual; this integration does not run an OAuth refresh flow.

Drafts for each provider and Slack method are separate, retained in the current
form across language changes, and only the selected fields are submitted. When
editing the same method, blank secret fields keep the saved credentials. Changing
provider or Slack method requires that method's own credentials; previous
connection fields are cleared on save and queued pending/retry deliveries are
cancelled. Dispatched notifications cannot be recalled. Existing destinations
are not changed just by opening a form.

Choose the destination's scope and minimum severity, enable it for automatic
notifications, and save. **Send test** explicitly sends a test to that saved
destination; **Activity** records its outcome. Reading a guide or opening a
template does not send notifications or configure the external service.

## Sources checked on 2026-09-08

The date records when the instructions were checked, not a provider release date.

| Channel                      | Reference                                                                                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Telegram                     | [Bot tutorial](https://core.telegram.org/bots/tutorial), [getUpdates](https://core.telegram.org/bots/api#getupdates)                                                                  |
| Slack                        | [Incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/), [chat.postMessage](https://docs.slack.dev/reference/methods/chat.postMessage/)       |
| Discord                      | [Intro to Webhooks](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)                                                                                        |
| Hermes Agent                 | [Webhooks and direct delivery](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/)                                                                             |
| n8n                          | [Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/), [Header Auth credentials](https://docs.n8n.io/integrations/builtin/credentials/webhook/) |
| System                       | [Desktop Notifications Specification](https://specifications.freedesktop.org/notification/latest/) and the local `notify-send` adapter                                                |
| Generic webhook / local file | LogSentinel's [destination model](../logsentinel/portal/models.py) and [delivery adapters](../logsentinel/portal/notify.py)                                                           |

System notifications appear on the portal host's desktop and require its user
session. Files go inside the portal data directory's `notifications/` folder;
only a filename is accepted, with configurable rotation and gzip archives.
Generic webhooks receive LogSentinel's JSON payload. A successful HTTP response
from a webhook or n8n confirms acceptance by the receiver; check the downstream
service to verify final delivery. See [Operations](OPERATIONS.md#avisos-y-filtros)
for queue, retry, and retention behavior.
