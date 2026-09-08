# LogSentinel for Omarchy Quattro

A bar widget showing observer health, automatic-analysis status, open findings,
pending and unreviewed counts, and CPU/RAM/disk readings for up to four machines.
It polls every 30 seconds and opens the full portal for evidence and investigations.
English is the default; set the widget's `language` setting to `es` for Spanish.

## Compatibility and scope

Requires **Omarchy Quattro with the plugin API**, Quickshell and `curl` on the
desktop. It shares Omarchy's existing shell process. There are no installation
hooks, package installations, systemd modifications or elevated commands in the
plugin. Install/run the LogSentinel portal and an LLM separately; see
[the quick start](QUICKSTART.en.md). The portal can run on another Linux machine
accessed through a local SSH tunnel.

If you install the portal on the desktop too, use a separate checkout outside
`~/.config/omarchy/plugins/`. Python virtual environments contain symlinks, which
Omarchy rejects inside a plugin directory, including when validating updates.

This implementation follows the [development guide](https://plugins.omarchy.org/develop.html)
and [official shell contract](https://github.com/omacom/omarchy/blob/quattro/shell/README.md)
reviewed again on 8 September 2026. This is a preview for installation testing. The development
host is Ubuntu without an Omarchy desktop; real bar placement and shell lifecycle
validation must be completed on Omarchy before calling it a supported release.

The plugin author is **ianmove**. [@THEINAOG · x.com](https://x.com/THEINAOG) ·
[ianmove/LogSentinel · GitHub](https://github.com/IAnMove/LogSentinel).

## First test on your Omarchy desktop

1. Run `omarchy plugin list`. If your installation has no `plugin` command, it
   does not provide the Quattro plugin interface needed by this widget. The web
   portal can still be used through your browser; this plugin does not upgrade
   or replace the desktop.
2. Install the widget with the command below. You can use your existing portal
   on another machine, so there is no need to install a second LLM or portal just
   to try the widget.
3. Open a loopback SSH tunnel to that portal, then open its local URL in the
   browser. Use **Desktop → Create widget key** and save its JSON on the Omarchy
   desktop as described below. Do not use the administrator login key.
4. Click `LS` in the bar and check **Open portal**, **Refresh**, Escape and reopening.
   `LS ?` before pairing is expected. Refresh retries reading the configuration;
   creating the file after installation does not require restarting the shell.

The widget displays machines known to the connected portal. Installing it does
not automatically register the Omarchy computer or send its logs. To monitor
that computer too, configure a machine and remote sender in the portal; see
[remote log forwarding](https://github.com/IAnMove/LogSentinel#enviar-desde-otro-equipo) and
[resource collection](METRICS.md).

## Install from a published repository

The public revision must contain the root `manifest.json` and the files under
`integrations/omarchy/`. Local commits do not update the public repository.

```sh
omarchy plugin add https://github.com/IAnMove/LogSentinel.git --enable
```

Alternatively build the small standalone bundle from this checkout:

```sh
python scripts/package_omarchy.py --output /tmp/logsentinel-omarchy.tar.gz
mkdir -p ~/.config/omarchy/plugins
tar -xzf /tmp/logsentinel-omarchy.tar.gz -C ~/.config/omarchy/plugins
omarchy-shell shell rescanPlugins
omarchy plugin enable io.github.ianmove.logsentinel
```

Use an empty target plugin directory when extracting; do not mix a release bundle
with an existing Git-managed installation. Bundle installations are updated by
replacing that directory; Git installations use `omarchy plugin update`.

## Pair in the portal

1. Open **Desktop**, then **Create widget key**. This revokes the previous widget
   key and shows a new one once. The normal portal access key is not accepted by
   the widget endpoint.
2. On the Omarchy desktop, create `~/.config/logsentinel/` with mode 0700 and save
   the displayed JSON as `widget.json`, mode 0600. Set `url` to the portal's actual
   loopback address/port, such as `http://127.0.0.1:8765` (or `8766` if configured).
   The file is on the **desktop**, which may differ from the portal server.
   Create the directory with `install -d -m 700 ~/.config/logsentinel`, paste the
   JSON into `~/.config/logsentinel/widget.json` using your editor, and run
   `chmod 600 ~/.config/logsentinel/widget.json`.
3. The widget watches the file. Click `LS` to inspect the panel, or use the shell
   command below. For another file location set `configPath` to its absolute path
   in the widget's settings. Never store the token in the shared shell settings.

```sh
omarchy-shell shell summon io.github.ianmove.logsentinel '{}'
omarchy-shell shell hide io.github.ianmove.logsentinel
```

For a remote portal, establish a tunnel from the Omarchy desktop. This example
maps the desktop's 8766 to the server's 8766:

```sh
ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 8766:127.0.0.1:8766 user@server
```

Configure the widget URL as `http://127.0.0.1:8766`. Only `localhost`, `127.0.0.1`
and `::1` HTTP(S) addresses are allowed. DNS names for remote hosts are intentionally
not accepted; use the tunnel. Curl ignores user curlrc/proxies, does not follow
redirects, has a 10-second timeout and bounds responses to 64 KiB. The token goes
through stdin, not command arguments. No log text is interpreted as QML or HTML.

## Controls and status

Click toggles the panel. Escape closes it; Tab switches shell panels. Arrow keys
select Open/Refresh and Enter activates; `r` refreshes. `LS ?` means unpaired or
unavailable. `LS !` means degraded observer health or paused automatic analysis.
The panel labels stale/disabled measurements and reports the latest connection
check. Missing measurements do not prove a host is powered off. More than four
machines are available in the full portal.

The separate `widget:read` credential reveals machine names, aggregate counts and
resource percentages. It cannot read original logs, configure the app, call the
model, ingest data or create a login session. Revoke it in **Desktop**. The plugin
runs with ordinary user permissions, like other Omarchy plugins; the credential
limits portal access, not the plugin process's OS permissions.

## Validate the desktop preview

```sh
PLUGIN_DIR=~/.config/omarchy/plugins/io.github.ianmove.logsentinel
omarchy plugin validate "$PLUGIN_DIR"
qmllint -I "$OMARCHY_PATH/shell" \
  "$PLUGIN_DIR/integrations/omarchy/SentinelWidget.qml" \
  "$PLUGIN_DIR/integrations/omarchy/SentinelPanel.qml"
```

Check click, keyboard, summon/hide, bar placement, vertical/multiple-monitor bars,
theme change, disable/re-enable, shell restart, missing/invalid credentials, stopped
portal, token rotation and removal. Automated tests cover the API permission
boundary, parsing, portal pairing flow and manifest bundle. On the Ubuntu development
host QML can be syntax checked; installed-shell import/lifecycle checks need Omarchy.

The release preparation checks the clean source tree and the standalone bundle
with Omarchy's official manifest validator. The parser/credential checks and
portal permission tests also run locally. These checks do not substitute for
`qmllint` against the installed Quattro imports or the desktop interactions above.

If the widget does not appear, inspect the shell log on the desktop:

```sh
qs log -p "$OMARCHY_PATH/shell" --tail 100
```

For a test report, include the Omarchy version, validator output and relevant QML
errors. Do not include `widget.json`, access keys or actual log evidence.

The [publishing guide](https://plugins.omarchy.org/publish.html) describes the public
GitHub repository and marketplace submission. Nothing is published or submitted by
the packaging script. Installing directly from GitHub does not require a
marketplace listing. After successful desktop testing, a marketplace listing
requires submitting the repository and waiting for the maintainers' review.
Keep the permanent plugin ID when releasing updates.

## Remove

```sh
omarchy plugin remove io.github.ianmove.logsentinel
```

Revoke the widget key in the portal and remove the private `widget.json` when no
longer needed. Removing the widget does not remove portal data, stop the portal
service, or uninstall the LLM.
