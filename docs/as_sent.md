# As-sent tool definitions

`data/tools_as_sent/` holds every tool exactly as a framework puts it in the request body it sends
to a provider. The benchmark measures the cost of what is actually sent, and frameworks rewrite
tool definitions before sending them, differently per provider. So the extracted definitions in
`data/tools_pool_v0/` are not always what reaches the model.

- `data/tools_pool_v0/` is the canonical source: each framework's own output, before any
  provider-specific conversion.
- `data/tools_as_sent/` is derived from it by `scripts/as_sent/build.py`. Never edit these files
  by hand; if anything changes, rerun the harness.

Layout: `data/tools_as_sent/<provider>/<tool_id>`, where `<tool_id>` is the tool's path in the
pool and `<provider>` is one of `openai-chat`, `openai-responses`, `anthropic`, `gemini`. Each
file:

```json
{
  "tool_id": "livekit/avatar/wave.json",
  "provider": "openai-chat",
  "framework": "livekit-agents + plugins 5b49888",
  "endpoint": "/v1/chat/completions",
  "payload": { "...": "the tool element from the request body's `tools` array, untouched" }
}
```

Covered sources: τ²-bench, Pipecat, Pipecat Flows and LiveKit (70 + 49 + 106 + 67 = 292 tools,
1,168 files). Not covered yet: τ-bench, aiewf-eval and EVA, whose send paths haven't been traced.

## How the files are generated

The tools aren't converted with re-implemented logic. Each one is sent through the framework's
real request code, pointed at a fake API server on the local machine, and the request body is
recorded. No provider is contacted.

### 1. The capture server

`scripts/as_sent/capture.py` starts an HTTP server on `127.0.0.1` (random port). It records the
JSON body of every POST and answers `400` with an error body. The client sees the error and stops,
but the full request has already been sent and recorded. Retries are turned off, so each tool
produces exactly one request; `record()` fails if it captures zero or more than one, or a body
without exactly one tool.

### 2. Sending each tool through the framework

Each probe loads every tool from `data/tools_pool_v0/<source>/` and sends it through the
framework's normal LLM call, with the client's base URL pointed at the capture server, a dummy API
key, a realistic model name and one `"hi"` user message:

| Source | How the tool is rebuilt | What sends it |
|---|---|---|
| τ²-bench (`probe_litellm.py`) | The pool file as `{"type":"function","function":{...}}`, exactly what τ²'s `Tool.openai_schema` produces | `litellm.completion(...)`, the call τ² makes (`src/tau2/utils/llm_utils.py:680`), with litellm at τ²'s locked version (1.81.11). `openai-responses` uses the `openai/responses/...` model route τ² uses for gpt-5* models (`llm_utils.py:638`), with the `allowed_openai_params` τ² adds |
| Pipecat (`probe_pipecat.py`) | `FunctionSchema(name, description, properties, required)` from the pool file. Lossless: those are the only top-level keys in these tools' parameters (the probe asserts it) | Pipecat's real services, `OpenAILLMService`, `OpenAIResponsesHttpLLMService`, `AnthropicLLMService` and `GoogleLLMService`, via `_process_context()`, the method a running bot calls each turn |
| Pipecat Flows (`probe_pipecat.py`) | Same as Pipecat, run with pipecat-ai 1.4.0, the version pipecat-flows pins | The same services. Flows turns every node function into a plain `FunctionSchema` (`pipecat_flows/manager.py:587-594`) and hands it to the LLM through `ToolsSchema` / `LLMSetToolsFrame` (`manager.py:679`, `:847`), so this is the same path |
| LiveKit (`probe_livekit.py`) | Real `@function_tool` objects, rebuilt by re-running the committed extractor on the example files. LiveKit's strict schema is generated from the Python signature, not from the stored JSON | The LiveKit plugins' `llm.chat(...)` with default settings: `openai.LLM`, `openai.responses.LLM`, `anthropic.LLM`, `google.LLM` |

### 3. Saving the result

From each recorded body the probe keeps the single element of `tools` as `payload`, unchanged, and
`build.py` writes it to `data/tools_as_sent/<provider>/<tool_id>`. The output directory must not
exist yet, so files are never overwritten.

### 4. Pinned versions

- Framework commits (pipecat, livekit) come from `scripts/extract/sources.json`, the same pins the
  extractor uses. `build.py` makes sparse clones of only the Python source it needs.
- Package versions are frozen in `scripts/as_sent/requirements-*.txt`, one per environment:
  `frameworks` (pipecat source + LiveKit + provider SDKs), `flows` (pipecat-ai 1.4.0) and
  `litellm` (litellm 1.81.11). pydantic is 2.14.1 everywhere, matching the extractor.

A framework or SDK update can change what gets sent, so updating any of these means rerunning the
harness and committing the new files.

## Rebuilding and checking

Needs `git` and `uv`.

```
python scripts/as_sent/build.py --check   # rebuild in a temp dir, diff against data/tools_as_sent
python scripts/as_sent/build.py --out DIR # write a fresh copy to DIR
python scripts/as_sent/report.py          # per framework x provider: what changes vs the pool
```

`--check` reported 0 differing files both for the original 1,312 files and after deduplication
(1,168 files).

## What each framework sends

Counts from `report.py` for the current pool. "Identical" compares parameters and description with
the pool file; provider wrapper keys (`input_schema`, `functionDeclarations`, ...) always differ.
Size is the compact JSON of the sent tool element vs the pool tool in OpenAI format, in characters
(not tokens).

| Framework | Provider | `title` | `$ref` / `$defs` | Other changes | Identical | Size |
|---|---|---|---|---|---|---|
| LiveKit | openai-chat | all removed (260 → 0) | none in pool | strict mode: `additionalProperties: false` on every object, all properties required, defaults removed, optional fields become `["T","null"]`; adds `"strict": true` | 0 / 106 | −2.9% |
| LiveKit | openai-responses | kept | none in pool | none | 106 / 106 | −2.2% |
| LiveKit | anthropic | all removed | none in pool | same strict rewrite; adds `"strict": true` | 0 / 106 | −7.8% |
| LiveKit | gemini | kept (sent as `parameters_json_schema`) | none in pool | the 40 zero-parameter tools are sent with no parameters at all | 66 / 106 | −4.3% |
| τ²-bench | openai-chat | kept | kept | none | 67 / 67 | 0.0% |
| τ²-bench | openai-responses | kept | kept | adds `"strict": null` | 67 / 67 | +0.2% |
| τ²-bench | anthropic | top-level removed (67), nested kept (156) | kept | none | 0 / 67 | −7.8% |
| τ²-bench | gemini | kept, and copied in where refs are inlined | inlined and removed (3 tools) | empty `properties: {}` dropped (8), `additionalProperties` dropped (4) | 55 / 67 | −1.7% |
| Pipecat | openai-chat | none in pool | none in pool | none | 70 / 70 | 0.0% |
| Pipecat | openai-responses | – | – | adds `"strict": null` | 70 / 70 | +0.3% |
| Pipecat | anthropic | – | – | same schema under `input_schema` | 70 / 70 | −8.0% |
| Pipecat | gemini | – | – | google-genai SDK uppercases types (`"STRING"`), sends `anyOf` as `any_of` (3 tools), camelCases and reorders keys | 0 / 70 | −1.1% |
| Pipecat Flows | openai-chat | none in pool | none in pool | none | 49 / 49 | 0.0% |
| Pipecat Flows | openai-responses | – | – | adds `"strict": null` | 49 / 49 | +0.4% |
| Pipecat Flows | anthropic | – | – | same schema under `input_schema` | 49 / 49 | −10.8% |
| Pipecat Flows | gemini | – | – | types uppercased, keys camelCased | 0 / 49 | −1.5% |

LiveKit and τ²-bench send Pydantic-generated `title` fields (e.g. `"title": "TransferToKellyArgs"`)
on most routes. These are tokens the developer never wrote, which makes "with titles vs. without"
a natural mini-experiment.

### Code that produces each behaviour

LiveKit (commit `5b49888`):
- `livekit-plugins-openai/livekit/plugins/openai/llm.py:124`: `_strict_tool_schema: bool = True`
  is the default.
- `livekit-agents/livekit/agents/llm/_provider_format/openai.py:278-296`: strict uses
  `build_strict_openai_schema`.
- `livekit-agents/livekit/agents/llm/_strict.py:171` removes `title` (`json_schema.pop("title", None)`);
  `:175` removes `default`.
- Anthropic: `livekit-plugins-anthropic/.../anthropic/llm.py:89` (strict default) and `:200-201`,
  then `_provider_format/anthropic.py:137-150`.
- Responses: `livekit-plugins-openai/.../openai/responses/llm.py:533-539` calls
  `_provider_format/openai.py:300` (`to_responses_fnc_ctx`), which always uses the non-strict
  `build_legacy_openai_schema`.
- Gemini: `_provider_format/google.py:146-153` passes the non-strict schema as
  `parameters_json_schema`, or nothing when there are no properties.
- The OpenAI-compatible constructors (`with_cerebras`, `with_sambanova`, ...) set
  `_strict_tool_schema=False` (`openai/llm.py:332`, `:377`), so they send the pool version.

τ²-bench (commit `989d328`) and litellm 1.81.11:
- `src/tau2/utils/llm_utils.py:648` and `:680` pass `tool.openai_schema` unchanged to
  `litellm.completion`.
- litellm `llms/anthropic/chat/transformation.py:330-344` keeps only the allowed top-level keys of
  the parameters, which drops the top-level `title`.
- litellm `llms/vertex_ai/common_utils.py:468-489` (`_build_vertex_schema`) pops `$defs` and inlines
  references with `unpack_defs`.

Pipecat (commit `5558d26`) and pipecat-ai 1.4.0 (Flows):
- OpenAI: `adapters/services/open_ai_adapter.py:199-215` passes `to_default_dict()` through
  (1.4.0: `:156-171`).
- Anthropic: `anthropic_adapter.py:577-596` builds `input_schema` from `properties` and `required`
  (1.4.0: `:431-450`).
- Gemini: `gemini_adapter.py:102-170` adapts the schema (`_adapt_schema`; 1.4.0: `:84-128`), then
  the google-genai SDK validates the dict into its `Schema` type, whose `Type` enum is uppercase
  (`google/genai/types.py:226`).

## Caveats

- LiveKit's `openai.responses.LLM` normally uses a WebSocket. The probe sets `use_websocket=False`
  to capture it over HTTP; the plugin builds the tool list with the same code either way
  (`responses/llm.py:533-539`).
- Pipecat's WebSocket `OpenAIResponsesLLMService` isn't captured directly. The probe uses
  `OpenAIResponsesHttpLLMService`, which shares its adapter.
- Each request carries one tool. Real requests send all of an agent's tools together. Every route
  converts tools one at a time, so each tool's payload is the same either way; what changes is the
  surrounding JSON (array separators, and Gemini's single `functionDeclarations` wrapper).
- Default plugin and service settings are used. Options such as LiveKit's `_strict_tool_schema`
  change what is sent.
