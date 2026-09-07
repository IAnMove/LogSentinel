# Problem context and investigations

Opening **Ask the assistant** from a problem now binds the conversation to that problem and machine. The question names the problem; the page displays its summary, hypothesis, checks, sources and occurrence history. **View more details** exposes retained original evidence and previous revisions. General chat and each problem have separate histories.

The context preview shows the exact payload prepared for the model, including the canonical finding and original evidence. The response saves the actual payload used. Input follows the configured conservative byte budget: large fields and events are explicitly excerpted, and omitted/expired evidence is counted. Opening the chat or preview does not call the LLM.

**Find more details about this problem** queues a persistent read-only investigation. One LLM call proposes bounded literal terms and services. The server searches up to 2,000 retained events in windows around original evidence (default ±30 minutes), on the same machine, honoring exclusions. A second call tests the original hypothesis against the bounded retrieved evidence. It cannot execute commands, apply filters or modify the original diagnosis. Citations must refer to evidence actually supplied. Results and coverage remain available after navigation/restart; interrupted calls are shown explicitly and can be retried as a new investigation.

Investigations share the model lock with scheduled analysis and chat. Capture continues independently. Up to two additional calls per investigation are recorded in usage; search limits are visible. Existing evidence that has expired cannot be reconstructed.

Validation: 254 Python tests; Chromium problem flow with a stubbed model, including Spanish/English, mobile layout, context preview without calls and durable investigation. `scripts/problem_smoke.py` is included in CI.
