# LLM servers and safe connection testing

Open **Model and analysis** (or the first setup step). Choose a server preset, edit its URL, find available models and select the exact installed model ID or proxy alias. **Test these settings without saving** sends synthetic data using the current form, reports time and reported input/output tokens, and preserves the active analysis configuration. **Save settings** activates it. The active endpoint and model are displayed separately. A successful test proves a complete, valid JSON response, not detection quality.

**Model** is now a dropdown in both forms. It automatically lists Ollama's `/api/tags` or compatible `/v1/models` after connection details change; **Refresh models** reloads it. Remote discovery requires the remote-access checkbox. Listing does not load a model or run inference and works even while context/output fields are being edited. Choose **Enter model ID manually…** for unpublished aliases or unavailable discovery. A missing saved model stays editable with an explicit notice; no other model is selected automatically. Late replies from a previous server cannot replace the current list.

| Preset | Protocol | Suggested URL |
| --- | --- | --- |
| Ollama | Native `/api/chat` | `http://127.0.0.1:11434` |
| llama.cpp | Compatible chat completions | `http://127.0.0.1:8080/v1` |
| LM Studio | Compatible chat completions | `http://127.0.0.1:1234/v1` |
| vLLM | Compatible chat completions | `http://127.0.0.1:8000/v1` |
| LiteLLM Proxy | Compatible chat completions | `http://127.0.0.1:4000/v1` |
| Compatible load balancer / custom API | Compatible chat completions | Enter the actual URL |

Suggested ports are editable and may already belong to another application. Presets do not install servers or models. One endpoint/model is active for analysis, assistant chat, investigations and trends; this does not introduce saved multi-provider profiles, per-machine routing or concurrent model voting. A compatible proxy can implement balancing/failover behind that endpoint.

Compatible servers must support system/user messages, `max_tokens`, JSON output through `response_format: {"type":"json_object"}`, and non-streaming `POST /v1/chat/completions`. `GET /v1/models` provides discovery when available; IDs can also be entered manually. Ollama uses native JSON mode and `num_ctx`/`num_predict`, and respects the optional `think` setting. A model's support for structured output/reasoning still depends on that model and server version. Invalid/truncated replies remain errors, never successful empty reviews.

The extended-reasoning selector defaults to the server's behavior. For compatible llama.cpp/vLLM deployments it can send `chat_template_kwargs.enable_thinking`; leave it at the default for servers without that extension. Changing a server preset resets that extension in the form. Ollama uses its own `think` parameter.

**Credentials are scoped to the endpoint and protocol.** A blank key preserves the existing secret only when both remain identical. Changing either requires entering the new key, and never forwards the old one implicitly, including during discovery or draft tests. There is also an explicit clear-key checkbox. Remote discovery and inference require the transmission opt-in. A proxy on localhost can itself route to remote providers: review its routes and privacy settings before using real logs.

Use the context actually loaded by the server. Ollama's budget suggestion is bounded by both its declared maximum and its reported running context. Model discovery still works when the previous model ID is not installed. Generic compatible APIs may publish only model names, so their context must be configured manually. Input estimates remain conservative UTF-8 byte bounds, not a model-specific tokenizer.

At this stage, HTTP-contract and Chromium tests exercise all presets using isolated mock servers. The development host additionally uses a real llama.cpp/Qwen3-8B endpoint. These tests do not claim live integration with an installed Ollama, LM Studio, vLLM, LiteLLM or the user's still-unidentified balancer.

Protocol references: [Ollama chat and reasoning](https://docs.ollama.com/api/chat), [LM Studio compatible endpoints](https://lmstudio.ai/docs/developer/openai-compat), [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), [vLLM serving](https://docs.vllm.ai/en/latest/serving/), [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start).
