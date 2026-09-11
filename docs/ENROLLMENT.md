# Enrolling a sender over HTTPS

This is the path that replaces the SSH tunnel: the client reaches the central over
HTTPS, the panel stays on loopback, and the agent runs without root. The SSH flow in
the README still works and is unchanged.

Three permissions stay separate throughout, and none of them implies another:

| Permission | What it allows |
| --- | --- |
| Read logs on the client | Read the files the operating system authorises for that account. Not root. |
| Source token | Deliver events to one source. Not the panel, not other machines. |
| Panel access key | Read and change everything the portal holds. Loopback only. |

## 1. On the central: a certificate for the LAN

There is no public domain here, so the certificate comes from an authority you run.
Any local CA works — `caddy`, `step-ca`, or `openssl` by hand. What matters is that
senders trust that authority for LogSentinel only, and that its private key never
leaves the central.

The reception listener needs the server certificate and its key. Senders need the
CA certificate, which is public.

## 2. On the central: split reception from the panel

    logsentinel portal \
      --data-dir ~/.local/share/logsentinel/portal \
      --port 8766 \
      --ingest-listen 0.0.0.0:8767 \
      --tls-cert /etc/logsentinel/server.pem \
      --tls-key /etc/logsentinel/server.key

The panel keeps listening on `127.0.0.1:8766` and still requires the access key,
origin and CSRF checks. The listener on `8767` carries `/ingest`, `/heartbeat`,
`/enroll` and `/ingest-metrics`; it exposes nothing that reads or changes the
portal's contents. Remote CPU/RAM senders use that same listener, not the panel.

A listener outside loopback is refused without TLS. Keeping `--ingest-listen` on
`127.0.0.1` is allowed and is how the SSH tunnel path behaves today.

## 3. On the central: issue the package

Create the push source in the panel, then:

    logsentinel enrollment-package \
      --source-id <source id from the panel> \
      --receiver https://central.lan:8767 \
      --ca-cert /etc/logsentinel/ca.pem \
      --out /tmp/machine-a.json

The package holds the receiver address, the CA certificate, its SHA-256 fingerprint,
and a single-use code that expires in an hour by default (`--validity`). It does not
hold the credential. A copy that leaks after the code is redeemed or expired is
worthless, and the command prints the fingerprint so you can confirm it out of band.

Deliver the file over a channel you trust. This first handover is the one step that
cannot be secured by the protocol itself — the same is true of accepting an unknown
SSH host key.

## 4. On the client: prepare the host

Once, as root:

    sudo logsentinel prepare-host \
      --account logsentinel-agent \
      --source /var/log/myapp/ \
      --journal

Without `--apply` it changes nothing and prints the full plan: the group, the
login-less account, the group memberships, and every `setfacl` it would run, each
with the reason. Re-run with `--apply` when the plan looks right.

Notes on what it does and does not do:

- It never changes a file's owner or group. Access is added through a named-user ACL
  next to the permissions the owning program already relies on.
- `--journal` adds the account to `systemd-journal`. That is read access to the whole
  journal, including other services and other users; the plan says so before applying.
- A single file grant does not survive rotation. The command says so instead of
  setting a default ACL on the parent directory, which would silently grant every
  other file that later lands there. Grant the directory if reading all of it is
  acceptable, or add the `setfacl` line to a logrotate `postrotate` step.
- After applying, it reads each source back as the account itself with `runuser` and
  fails loudly if anything is still unreachable. A granted permission is not a proven
  one.

## 5. On the client: redeem the package

    logsentinel enroll /tmp/machine-a.json --spool /var/lib/logsentinel/spool

The sender validates the package before any of it reaches the network: version,
address, and that the stated fingerprint matches the certificate actually enclosed.
Plain `http` to a non-loopback address is refused outright, since the credential
would cross the network in the clear. The pinned CA is written to the spool and used
to verify the receiver, so a machine answering at that address without the matching
key gets nothing.

On success the credential lands in `<spool>/push-token`, owner-readable only. Delete
the package file; it is spent.

## 6. On the client: install the service

    sudo logsentinel service install --system --run-as logsentinel-agent

A system unit without `User=` runs as root, so the command refuses to write one
unless you pass `--allow-root` deliberately. Every generated unit drops capabilities
and write access: `NoNewPrivileges`, an empty `CapabilityBoundingSet`,
`ProtectSystem=strict`, `ProtectHome=read-only` and a `@system-service` syscall
filter.

## Per-sender limits

The central bounds each sender separately, so one noisy or compromised machine
cannot spend the shared disk quota and the review budget on its own. Two settings
in the panel, per source and per hour:

- `sender_mb_per_hour` — 256 MB by default
- `sender_events_per_hour` — 200,000 by default

When a sender spends its allowance, reception answers `429` with `Retry-After`. The
sender keeps its queue, waits exactly that long, and retries; nothing is dropped and
no event is acknowledged. Every accepted delivery reports what is left.

Authenticating a sender establishes who it is. It does not establish that what it
sent is true, or that its volume is reasonable — those are separate, and the limits
above cover the second.

## What this does not add

Reception accepts logs, metrics and heartbeats, and answers with acknowledgements.
There is still no route by which the central instructs a client to do anything, and
the model has no tool that reaches a client machine. Analysis stays separate from
execution.
