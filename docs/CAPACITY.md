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
