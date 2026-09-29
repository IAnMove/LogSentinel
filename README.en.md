# LogSentinel

A local portal that reviews Linux logs with an LLM, finds reliability and
security problems, and keeps the evidence. The full documentation is in
Spanish ([README.md](README.md)); this is the short version.

It only reads and explains. It does not run commands on your machines, change
their configuration or block addresses. It runs on Linux with Python 3.10 or
newer and needs a model server installed separately (Ollama, llama.cpp,
LM Studio, vLLM, or anything that speaks the `/v1` API).

## Run it

```bash
git clone https://github.com/IAnMove/LogSentinel.git
cd LogSentinel
./portal            # creates .venv, installs the package, starts the portal
```

Open `http://127.0.0.1:8765` and sign in with the key in
`~/.local/share/logsentinel/portal/access-key.txt`. The panel listens on
loopback only. The interface is available in English and Spanish (selector in
the top bar).

1. Open **Guided setup**: save and test the model first.
2. Create a **Machine** and connect a **Source**: the local journal, a file or
   folder, or a remote sender.
3. Finish the wizard to turn on automatic review. Capture keeps running even
   while analysis is paused.
4. Read **Problems**, their evidence, and copy the prompt to ask another LLM.

## What you can rely on

- Every source belongs to a machine; originals are kept compressed inside
  SQLite and expire after `retention_days` (30 by default).
- A HIGH or CRITICAL finding that could not be verified is still notified,
  marked **unverified**. "Not reviewed" never means "no problems".
- OOM, full or read-only disks, `sudo` rejections and SSH bursts are detected
  on the originals without waiting for the model.
- Credentials the code recognises (key=value, JSON, `Authorization`, URL
  passwords, cookies, PEM keys, known token prefixes) are hidden before text
  goes to the model or to a notification destination. That is a list, not a
  guarantee, and stored originals are not redacted.
- The model proposes findings and filters; nothing it says is executed.

## Remote machines

A small sender installs with one command from an enrollment package and sends
the journal over HTTPS to the central portal. The installer asks you to
confirm the certificate fingerprint printed on the central, because the
package itself cannot vouch for its own certificate. See
[GUIA_EQUIPOS.md](GUIA_EQUIPOS.md) (Spanish).

## Develop

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/mypy
```

Browser walkthroughs need Playwright; see [README.md](README.md#desarrollo-y-verificación).
Report vulnerabilities as described in [SECURITY.md](SECURITY.md).
