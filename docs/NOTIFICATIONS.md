# Notification setup guides

Open **Notifications → Add** (or **Edit**) and select a channel. The expandable
**How to add [service]** section shows the setup steps, relevant form fields,
examples, and documentation for that channel. It follows the portal language
(English or Spanish). Changing the channel or language preserves the form draft.
Hermes and n8n templates are available inside their respective guides.

Choose the destination's scope and minimum severity, enable it for automatic
notifications, and save. **Send test** explicitly sends a test to that saved
destination; **Activity** records its outcome. Reading a guide or opening a
template does not send notifications or configure the external service.

## Sources checked on 2026-09-08

The date records when the instructions were checked, not a provider release date.

| Channel                      | Reference                                                                                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Telegram                     | [Bot tutorial](https://core.telegram.org/bots/tutorial), [getUpdates](https://core.telegram.org/bots/api#getupdates)                                                                  |
| Slack                        | [Incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/)                                                                                       |
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
