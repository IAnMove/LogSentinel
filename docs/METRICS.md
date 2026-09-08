# Machine metrics

**Overview → Machine resources** now shows CPU, RAM, swap and every measured disk, with bars, used/total GiB, available space and last-sample status. Use **View metrics and configure** to open a machine, or enter through **Metrics**. Open **Configure collection and alerts**, enable measurements and choose **This host** for the portal's Linux host, or **Remote sender** for another machine. Collection is optional and defaults off; log analysis works independently. Only one local profile can collect this host's measurements. Imported logs alone cannot reveal another host's RAM, CPU or disk use.

Default collection is every **60 seconds**, independent of log analysis, chat, browser sessions and model availability. Resource views refresh every 15 seconds and mark readings stale after the configured deadline (three intervals by default). Keyboard inspection temporarily pauses visual replacement, with a visible notice; collection continues. **Observer health** detects missing measurements and can use the configured notification channels. Disabled or stale machines display their last stored values explicitly.

The collector reads CPU utilization and I/O wait, RAM availability, swap occupancy, 1/5/15-minute load, uptime, free disk space and free inodes. Disk paths default to `/`; add other **local** mount paths explicitly. CPU percentage requires two counter reads, excludes I/O wait and does not double-count guest CPU time. RAM uses `MemAvailable`, not `MemFree`; unconfigured swap and unavailable readings are omitted rather than invented as zero. Disk usage includes reserved space unavailable to the portal user. Source definitions follow the [Linux kernel `/proc` documentation](https://docs.kernel.org/filesystems/proc.html). Container readings may describe the host rather than container limits; cgroup-specific monitoring is not implemented.

Samples are gzip-compressed in SQLite and acknowledged only after persistence. Each sample has a stable ID bound to a machine. Exact replays do not inflate statistics, while reuse of an ID with different data is rejected. Hourly and UTC daily aggregates retain minimum, maximum, average and count. Defaults: **30 days** of samples/hourly aggregates and **365 days** of daily aggregates. Retention runs hourly; database backups include telemetry. The portal's database quota also applies to metrics. Displayed compressed bytes cover sample payloads, not indexes or daily aggregate rows.

Minima/maxima are extrema of **observed samples**, not guaranteed continuous peaks. Recent charts offer **1, 6 and 24 hours**, axes, warning thresholds and pointer/keyboard inspection of min/max/mean/count. They group at most 240 time buckets per metric, retaining peaks and leaving empty buckets unconnected. Reads are bounded to the newest 10,000 samples in the window, with an explicit truncation warning; a 10-second cadence over 24 hours fits this limit. Hourly charts and daily history remain available separately. Daily history can show 7, 30, 90 or 365 days. Means weight samples equally; irregular sampling is visible through counts, not corrected by invented measurements. There is no historical backfill before collection starts.

## Cost and permissions

Basic collection, storage, charts and threshold alerts do **not** call the LLM. The Linux sampler reads system-wide `/proc` counters and `statvfs` for the configured paths; it does not read process memory, install kernel probes, enumerate processes or need root under a normal host configuration. Restricted `/proc` mounts and inaccessible paths can produce partial measurements. System journal access commonly needs a journal-reading group; metrics do not add that requirement. Remote metrics need the separate sender and machine-bound token described below.

On the development host on 2026-09-08, 100 synthetic-store measurements of **sample + compressed persistence** under UID 1000 gave a median of **12.3 ms wall / 2.9 ms CPU**, p95 wall **17.3 ms**, and a compressed payload around **330 bytes** per sample. At one sample per minute that payload alone is roughly **0.45 MiB/day/machine**; SQLite indexes, rollups, alert evidence and the portal process are additional. This microbenchmark is not a guarantee for other storage or a measurement of the entire portal's RAM/CPU. LLM trends are a separate, much more expensive opt-in task when inference runs locally.

## Alerts

CPU/RAM/disk/inode warning defaults are 90%; swap defaults to 80%. An alert normally requires three consecutive samples at or above its threshold. The critical threshold defaults to 98% and is configurable. Critical CPU requires three sustained samples by default, so a brief LLM workload peak is not immediately classified as critical. Other monitored percentages may alert immediately at the critical threshold. Rapid replays cannot substitute for the configured sample cadence. Active threshold conditions clear five percentage points below the warning threshold. A spike is a rise of 30 percentage points against the mean of up to ten previous samples, requiring at least three baseline samples within fifteen configured intervals. Thresholds, consecutive counts, spike size and cooldown are configurable.

The default cooldown is 30 minutes per resource and detector. Escalation to critical and a new occurrence after recovery bypass that cooldown. Alerts retain measured values, threshold/baseline and original sample as evidence, are grouped by machine/resource/detector, and use **Problems**, notification channels and notification-muting rules. Evidence is marked **Measured by threshold**, not LLM-reviewed coverage. Recovery adds evidence and resolves the same problem; recovery notifications can be disabled per machine. Delayed uploads older than the configured freshness window (three intervals by default) contribute to history but do not trigger current alerts. **Observer health** detects missing measurements independently of the LLM.

High utilization may be expected, including while a local LLM is working. A capacity warning is a measurement, not proof of an attack or a faulty process. Occupied swap does not prove active swapping. Use expected workload and trends to tune warnings.

## LLM trends

**Analyze trends** queues one durable model request for the last 24 hours, 7 days or 30 days. The payload includes latest readings and bounded hourly/daily aggregates. When the context budget is small, adjacent windows are merged while preserving extrema and sample counts. If necessary, omitted metric names are reported explicitly. The saved result exposes the exact input and coverage report. Metric references in the response must exist in that input. Calls and tokens are attributed to the machine's metrics source.

Automatic trend analysis is optional, defaults off and has a separate configurable interval (default one hour). It shares the model lock with log scans and investigations; collection and threshold alerts continue independently. Failed and interrupted analyses are visible. It cannot run commands, automatically change settings or create a diagnosis unsupported by supplied measurements. Its interpretation is advisory; long-term quality and forecasting require real history and calibration.

## Another machine through SSH

On the portal create/select that machine, enable remote metrics and generate its dedicated metrics token. Log-source tokens are separate. Keep the token out of command-line arguments and shell history. For a portal listening on port 8766, run on the remote sender:

```bash
ssh -NT -L 18766:127.0.0.1:8766 user@portal-server
```

In another terminal on the sender, with LogSentinel installed:

```bash
read -rsp 'Metrics token: ' LOGSENTINEL_METRICS_TOKEN
export LOGSENTINEL_METRICS_TOKEN
logsentinel metrics-forward --receiver http://127.0.0.1:18766 \
  --machine-id MACHINE_ID --interval 60 --disk / --disk /srv
```

Use the same interval on the sender and portal; `--disk` is repeatable and identifies local paths on the sender. The sender stores compressed pending samples in `~/.local/share/logsentinel/metrics-spool`, retries with the same IDs and reclaims acknowledged segments. A spool is bound to a receiver and machine and has a single-writer lock. `--once` is useful for connection tests; it takes one new sample and attempts one batch, so it may leave older queued batches for subsequent runs. Transport requires HTTPS or loopback (for SSH), validates TLS, and does not follow redirects.

Keep the sender process and tunnel running using your service manager. No SSH keys, firewall rules or remote services are installed automatically. Disk exhaustion stops sender capture rather than silently deleting queued samples. Clocks must be reasonably synchronized: samples over 60 seconds in the future or older than receiver retention are rejected. Permanent authorization/retention errors require operator intervention; the queue is retained for inspection.

## Limits and possible next additions

CPU temperatures, GPU utilization, SMART/NVMe health, network throughput, per-process attribution, cgroup limits and disk-pressure stall metrics are not included. They need specific data sources and, in some cases, additional permissions. **Observer health** now covers stale measurements, capture/worker failures, remote log heartbeats and storage pressure; detecting a completely stopped portal requires an independent uptime check. These readings are machine-level health signals, not a security audit or guaranteed prediction of exhaustion.

## Local validation, 7 September 2026

At the initial metrics milestone, **270 Python tests** and four Chromium journeys passed, covering problem context, deeper investigations, setup, automatic log capture, metrics settings, charts, English/Spanish and mobile layouts. Subsequent supervision and theme work reached **285 Python tests** and five browser journeys. Telemetry regressions cover missing swap, CPU warm-up, retained CPU history across a restart, extrema/averages, replay, machine authentication, sustained thresholds, spikes, hysteresis, expired-sample quarantine, retained queues after a lost acknowledgment, shared model locking and retention. Packaging uses an isolated build; `pip check` passes. Two dependency deprecation warnings remain in TestClient.

Real measurements were enabled on the local `flipi` profile every 60 seconds, alongside the existing 300-second log analysis. Initial readings were approximately 53% RAM, 0.01% swap and 63% root disk utilization; collection continued during model requests. Automatic LLM trend calls remain opt-in. There are no notification destinations configured on this installation, so warnings remain visible in Problems until delivery is configured.

The real Qwen3-8B initially returned additional `next_checks` and `incomplete_coverage` fields. They are now explicitly validated, bounded, persisted and rendered; malformed references are still rejected. The subsequent real trend call completed, with recommendations and an explicit warning that only a short history existed. That demonstrates integration, not long-term detection quality. No external notifications were sent. A coherent SQLite backup was made before the update.
