# Problem context and investigations

Opening **Ask the assistant** from a problem now binds the conversation to that problem and machine. The question names the problem; the page displays its summary, hypothesis, checks, sources and occurrence history. **View more details** exposes retained original evidence and previous revisions. General chat and each problem have separate histories.

The context preview shows the exact payload prepared for the model, including the canonical finding and original evidence. The response saves the actual payload used. Input follows the configured conservative byte budget: large fields and events are explicitly excerpted, and omitted/expired evidence is counted. Opening the chat or preview does not call the LLM.

**Find more details about this problem** queues a persistent read-only investigation. One LLM call proposes bounded literal terms and services. The server searches up to 2,000 retained events in windows around original evidence (default ±30 minutes), on the same machine, honoring exclusions. A second call tests the original hypothesis against the bounded retrieved evidence. It cannot execute commands, apply filters or modify the original diagnosis. Citations must refer to evidence actually supplied. Results and coverage remain available after navigation/restart; interrupted calls are shown explicitly and can be retried as a new investigation.

Investigations share the model lock with scheduled analysis and chat. Capture continues independently. Up to two additional calls per investigation are recorded in usage; search limits are visible. Existing evidence that has expired cannot be reconstructed.

Validation: 254 Python tests; Chromium problem flow with a stubbed model, including Spanish/English, mobile layout, context preview without calls and durable investigation. `scripts/problem_smoke.py` is included in CI.
# Observable chat requests

The log assistant queues a submitted question when another operation owns the
model. The UI distinguishes queued (not yet sent), running, completed, failed,
cancelled and interrupted requests. Questions and outcomes are persisted; return
to the same machine/finding conversation to recover the state after reloading.
Queued questions can be cancelled. Failed or interrupted inference is never
automatically resent. A client request ID prevents duplicate submissions while
its status record is retained (the latest 200 terminal requests).

An estimate and countdown use recent successful calls to the same provider/model
and, for newer records, the same server. With at least three chat observations,
chat timings are preferred; otherwise the last twelve matching model calls are
used. Failed calls are not interpreted as successful runtimes. The queue estimate
includes the active call, earlier chat requests and the automatic cycle's remaining
call allowance. It is approximate: input size, generation length, cold starts and
other clients of the model server change latency. Passing zero means “taking
longer than estimated”, not completion. Without history the UI shows no invented
ETA. Inference has the configured transport timeout and a five-second grace for
the total operation; an interrupted response is not reported as an answer.

LogSentinel serializes automatic analysis and log chat through the same fair
model lock. Chat waits for the current analysis cycle, which can use several
calls. Capture continues independently. Queueing changes when the question is
served; it does not increase the model's throughput. Up to ten chat requests,
and one active request per machine/finding conversation, can wait at once.
