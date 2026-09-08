# Coverage and capacity

Open **Coverage and capacity**, or **Understand and improve coverage** on the overview. These diagnostics read the local ledger; they do not call an LLM or consume tokens. They refresh every ten seconds and respect the selected machine.

The current-configuration window and the last-hour window are separate. Each window counts retained events received during that period: reviewed as groups/originals, waiting, skipped for capacity, not selected by policy, excluded by rules, and analysis errors. Their counts add up to received events. Expired records and threshold measurements are excluded. A reviewed group can represent repeated messages; it is not proof that every original was read or that the machine is safe.

The historical capacity total is **not a queue**. Those originals remain available until retention expires, but changing settings does not automatically replay them. A capacity finding's evidence count (initial sample at most 100) is not a throughput limit. Existing findings can stay open after coverage improves; fresh overload warnings require omissions in the current analysis.

The planning estimate uses the current configuration, excludes the newest collecting tail, and requires at least two successful/partial batches and two scan intervals. It resets on source, rule or settings changes. Retried batches are excluded from successful timing samples. It compares observed covered events/minute with eligible incoming events/minute. It is not a benchmark or a theoretical maximum: line lengths, duplicate grouping, filters, model speed, verification, chat and other machines affect it. Paused analysis has no continuous-rate projection. The volume slider only simulates a change; it never filters logs or saves settings.

Review these limits together:

- The configured context includes instructions, input and output. Input uses UTF-8 bytes as a conservative bound, not actual token counts or a fixed number of lines.
- A larger context does not automatically raise the saved input budget. **Prepare larger input budget** fills a draft within the current context; review and save it explicitly. More input can require more memory and time.
- The event limit admits candidates per machine and cycle, not guaranteed coverage. At present the analyzer prepares at most one new batch per machine per cycle. The global call limit is also shared with second-pass verification.
- A shorter interval helps only if the model has time available. For a busy model, compare a faster model, more resources, or a smaller selected log volume.
- Inspect high-volume services, then configure source priority/keyword selection with context. Use Rules to preview exclusion filters. Exclusions and unselected messages remain visibly unreviewed.

All local journald sources capture the same host journal. The portal rejects a second enabled journald source, even on another machine card; the diagnostic also identifies legacy duplicates. The setup wizard reuses a matching local hostname when detecting this machine. Remote journals should arrive through push/file/folder sources associated with the remote machine.


## Reviewed optimization

Use **Machines → Optimize**, or select a machine in **Coverage and capacity → Optimize this machine**. The diagnostic reads at most 2,000 recent retained events from its enabled log sources in the last hour, applies existing exclusions, and compares several source policies. It does not call a model. Truncation, sampled counts, selection rates and coverage loss are shown. Rates extrapolated from a partial sample may not represent the whole window.

The proposal compares three numeric-priority ceilings (warnings 4, errors 3, critical 2), each OR-ed with an explicit list of case-insensitive literal keywords. The preview exposes those exact terms. These policies retain originals, set automatic surrounding context to zero minutes and leave excluded/unselected records visibly unreviewed. Investigations can retrieve retained context later. A producer's priority is not authenticated proof of severity; critical-only selection cannot guarantee detection of all security issues.

An indicative throughput estimate requires at least three successful, non-retried batches with the current model/budget/cadence since the latest source, rule or settings change. It uses median covered events, full-batch model time including verification, shared machine/call budgets and 25% headroom. Frequent recent errors with that model invalidate the estimate. The selected machine is counted even if paused, to account for its share when resumed. This remains an estimate, not a promised processing rate or a projection for larger unseen payloads.

When possible, additional proposals allow a larger input budget within the already configured context, or a shorter interval when measured model work leaves time free. Global proposals require a separate acknowledgement because they affect other machines. The optimizer does not raise the model server's loaded context, download models or enable paused monitoring. A larger budget requires new measurements; a longer interval does not increase processing speed.

**Apply this proposal** requires review of coverage loss. Plans expire after 15 minutes and become invalid if settings, source/rule configuration or machine state changes. Applying is transactional and audited. Old historical capacity omissions are not silently replayed. Compare at least three subsequent completed cycles and regenerate the diagnostic; if critical events still exceed capacity, reduce producer volume or use faster inference.
