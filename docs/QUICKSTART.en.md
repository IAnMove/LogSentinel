# LogSentinel quick start

LogSentinel is a local Linux log observatory. It captures logs, asks a configured LLM to identify reliability and security problems, and retains the original evidence. It does not execute the model's suggested commands.

## Install and open

Requires Linux and Python 3.10 or later. The LLM server is installed separately.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/logsentinel portal
```

Open `http://127.0.0.1:8765` and enter the key printed by the process. Data defaults to `~/.local/share/logsentinel/portal`. Use `--port` and `--data-dir` to change those defaults. Run the portal as a user with permission to read the intended logs.

Use the language selector to choose English or Spanish. It remembers your browser preference; new browsers use their preferred language, falling back to English. Original evidence, saved user content and existing findings are not translated. The language for new model findings is a separate setting.

## Setup wizard

1. **Connect the LLM:** save an Ollama or compatible API URL, model ID and optional API key. Test the saved configuration with synthetic data. A successful test proves connectivity and JSON format, not detection quality. Use the server's loaded context size, not a model family's theoretical maximum. Remote servers require explicit permission to transmit context.
2. **Choose a machine:** create or reuse a profile. Keep separate identities for each machine, including imported logs.
3. **Connect logs:** local journal needs no path; it uses `journalctl`. Files and folders need an absolute path on the portal server. Importing history can read all available records. Remote ingestion requires a configured sender and its source key. Reusing a source keeps its existing selection policy.
4. **Enable and learn:** choose the analysis interval and language for new findings, then finish. Notifications can be configured separately; saving a destination does not send a test message.

**Continuous capture and scheduled analysis are separate.** Enabled sources are polled approximately every two seconds plus read time. The model reviews a bounded batch per machine at the selected interval (default five minutes). The portal displays next run, last received event, errors and coverage. You can close the browser; keep the portal process or systemd service running. Pausing analysis keeps capture running. Long model calls delay subsequent analyses; calls never overlap within the portal.

The floating **Ask the LLM** window answers configuration questions using a built-in guide and a nonsecret configuration summary. It receives no logs and cannot change settings. The separate **Log assistant** uses a bounded recent sample from the selected machine and can propose filters for you to review. Both share the model with the monitor and may ask you to wait while analysis is running.

## Coverage, evidence and alerts

Open **Problems** for evidence, investigation prompts, resolution and notification muting. Muting a problem keeps analysis running. Exclusion rules keep retained originals but omit matching events from model input. Preview matches before saving.

Coverage distinguishes pending, compact review, original review, policy selection, exclusion, capacity gaps and errors. Unreviewed data is not a clean security result. With too much incoming data, reduce repetitive application logging, preview narrowly scoped filters, tune the budget, or provide more model capacity. A small local model may not keep up with all system logs.

Priority selection uses numeric syslog priority OR configured case-insensitive keywords. Priority is sender supplied and is not a security guarantee. Context is a bounded sample of already captured nearby events; later arrivals do not automatically trigger a second look at an earlier finding.

Originals are compressed in immutable SQLite segments. Capture does not wait for the LLM or for an SSH connection to close. LogSentinel does not rotate other programs' source files. Retention can expire even unreviewed originals; storage is finite. Backups and notification files are outside the database quota. Protect them: credentials and originals are stored locally with owner-only permissions, without application-level encryption.

## Access through SSH

From your client, with the portal running on port 8765 on the server:

```bash
ssh -NT -L 8766:127.0.0.1:8765 user@server
```

Open `http://127.0.0.1:8766` on your client. Change the **last** port if your portal runs on a different server port. The portal binds only to loopback and expects access through a loopback tunnel.

For detailed source rotation, sender spooling, ACK semantics and notification contracts, see [operations](OPERATIONS.md). For the measured local review and remaining limitations, see [the review](REVIEW_2026-09-07.md).
