# tool-latency-bench

A benchmark measuring how adding tool (function) definitions to a prompt affects LLM response latency.

## Motivation

The [Voice AI & Voice Agents primer](https://voiceaiandvoiceagents.com/) notes that adding
function definitions to a prompt can increase latency, and that it would be good to develop
latency-oriented evals to measure this. This benchmark is an attempt to do that.

## Resources

- [Voice AI & Voice Agents: An Illustrated Primer](https://voiceaiandvoiceagents.com/)
  ([source on GitHub](https://github.com/pipecat-ai/voice-ai-primer-web)), CC0.
  The motivation for this benchmark comes from its section on function calling.
- [Pipecat](https://github.com/pipecat-ai/pipecat), BSD 2-Clause.
  Tool-definition formats and the function-calling flow are based on its examples and adapters.
- [pipecat-ai/stt-benchmark](https://github.com/pipecat-ai/stt-benchmark).
  Methodology conventions (tail latency reporting, contributor workflow) follow this benchmark.
- [kwindla/aiewf-eval](https://github.com/kwindla/aiewf-eval), MIT.
  Project layout, CLI and the TTFAT (time to first answer token) definition follow this benchmark.

## Tool definition pool

`data/tools_pool_v0/` holds 449 real tool definitions (name, description, parameters JSON
schema, i.e. what is sent to the LLM in the `tools` field), one JSON file per tool. They were
extracted with each project's own schema code, with wording kept exactly as in the source.
Each file records the source repo, commit and file path it came from.

The extraction code is in `scripts/extract/` (one `extract_<source>.py` per source). To rebuild
the pool from fresh clones at the pinned commits (needs `git` and `uv`):

```
python scripts/extract/rebuild.py --check                  # rebuild in a temp dir, diff against the pool
python scripts/extract/rebuild.py --out /tmp/tools_pool_v0 # or write a fresh copy
```

`sources.json` pins the full commit SHAs and the files fetched from each repo;
`requirements-*.txt` pin the package versions, since the Pydantic version affects generated schemas.

| Source | Repository | Commit | License | Tools |
|---|---|---|---|---|
| τ-bench | [sierra-research/tau-bench](https://github.com/sierra-research/tau-bench) | `59a200c` | MIT, © 2024 Sierra | 30 |
| τ²-bench | [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench) | `989d328` | MIT, © 2025 Sierra Research | 67 |
| aiewf-eval | [kwindla/aiewf-eval](https://github.com/kwindla/aiewf-eval) | `ff1e9fa` | MIT (stated in README; no LICENSE file in repo) | 5 |
| EVA | [ServiceNow/eva](https://github.com/ServiceNow/eva) | `2918ca6` | MIT, © 2026 ServiceNow | 122 |
| Pipecat (examples) | [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | `5558d26` | BSD 2-Clause, © 2024–2026 Daily | 70 |
| Pipecat Flows (examples) | [pipecat-ai/pipecat-flows](https://github.com/pipecat-ai/pipecat-flows) | `96223f4` | BSD 2-Clause, © 2024–2026 Daily | 49 |
| LiveKit Agents (examples) | [livekit/agents](https://github.com/livekit/agents) | `5b49888` | Apache 2.0, © 2023 LiveKit, Inc. | 106 |

The definitions remain under their original licenses. All three licenses permit
redistribution provided the copyright and license notices are kept (Apache 2.0 also asks
that modifications be stated; definitions here are unmodified apart from conversion to JSON).

### Deduplication

Only exact duplicates (same name, description and parameters) are removed, by rules in
`scripts/extract/write_pool.py`, so the rebuild reproduces them. 660 extracted, 449 kept:

- **Within Pipecat (−175):** its per-provider examples (`function-calling-openai`, `-anthropic`,
  `-groq`, …) copy the same tools; the first copy by file path is kept.
- **Pipecat copies of Pipecat Flows examples (−35):** Pipecat bundles the Flows examples under
  `examples/flows/`; those tools are kept only under `pipecat-flows/`, where they originate.
  Removed from `pipecat/`: `food_ordering/` choose_pizza, choose_sushi, complete_order,
  get_delivery_estimate, revise_order, select_pizza_order, select_sushi_order;
  `food_ordering_advanced_functionschema/` complete_order, get_delivery_estimate, revise_order,
  select_pizza_order, select_sushi_order; `hello_world/` record_favorite_color;
  `insurance_quote/` calculate_quote, collect_age, update_coverage; `llm_switching/`
  summarize_conversation, switch_llm; `multi_worker_handoff/` end_conversation,
  transfer_to_reservation, transfer_to_router; `patient_intake/` record_allergies,
  record_conditions, record_prescriptions, record_visit_reasons, verify_birthday;
  `podcast_interview/` proceed_to_topic, start_interview; `restaurant_reservation/`
  check_availability, collect_party_size; `warm_transfer/`
  check_store_location_and_hours_of_operation, connect_human_agent_and_customer,
  end_customer_conversation, start_human_agent_interaction, start_order.
- **Pipecat Flows reusing a Pipecat tool (−1):** `pipecat-flows/llm_switching/get_current_weather`
  is identical to Pipecat's standard demo tool, kept as
  `pipecat/context-summarization-dedicated-llm/get_current_weather`.

Pipecat `examples/flows/` tools that differ from their Pipecat Flows version are kept (4).
Exact duplicates within other sources are kept, e.g. τ-bench's `calculate` in both domains.


## As-sent definitions

Frameworks rewrite tool definitions before sending them, differently per provider, so
`data/tools_as_sent/<provider>/<tool_id>` stores each tool exactly as it appears in the request
body (`payload`), for `openai-chat`, `openai-responses`, `anthropic` and `gemini`. Covered: the
τ²-bench (via litellm), Pipecat, Pipecat Flows and LiveKit tools. Examples of what changes:

- LiveKit's default OpenAI and Anthropic paths use strict mode: every `title` is removed,
  `additionalProperties: false` is added and all properties become required.
- τ²-bench (litellm) keeps nested `title` fields for every provider except the top-level one for
  Anthropic; for Gemini it inlines `$defs`/`$ref`.
- For Gemini, the google-genai SDK used by Pipecat uppercases types and camelCases keys.

These files are derived from `data/tools_pool_v0/` by capturing each framework's real request at a
local HTTP server (no provider is contacted). Never edit them by hand; rerun the harness:

```
python scripts/as_sent/build.py --check   # rebuild in a temp dir, diff against data/tools_as_sent
python scripts/as_sent/report.py          # per framework x provider: what changes vs the pool
```

Framework commits come from `scripts/extract/sources.json`; package versions (litellm, pipecat-ai,
provider SDKs) are pinned in `scripts/as_sent/requirements-*.txt`. See
[docs/as_sent.md](docs/as_sent.md) for how the capture works, what each framework sends to each
provider (with the code that does it), and the caveats.

## Latency experiments

Requests are sent directly to OpenAI-compatible endpoints (no framework in the loop).

```bash
uv sync
uv run tool-latency-bench tool-stats       # tokens (tiktoken o200k_base) + group per tool -> data/tool_stats.csv
uv run tool-latency-bench build-pools      # data/pools/: exp1, exp2_simple, exp2_medium, exp2_budget
uv run tool-latency-bench list-benchmarks
uv run tool-latency-bench show-request exp1_tool_count          # one assembled request, nothing sent
uv run tool-latency-bench run exp1_tool_count --model <model> --service groq --session morning
uv run tool-latency-bench analyze runs/exp1_tool_count/<timestamp>_<model>_morning
uv run tool-latency-bench compare exp1_tool_count               # all sessions side by side
```

- Benchmarks: `benchmarks/exp1_tool_count/` (0/10/30/60 tools) and `benchmarks/exp2_complexity/`
  (0 tools vs 20 simple / 20 medium / 10+10 mixed at the same total tokens).
- Services (`--service`): `openai`, `google`, `groq`, `cerebras`, each an OpenAI-compatible
  base URL plus an API key read from the environment or `.env`; and `fake`, a local streaming
  server with simulated delay for dry runs without a key.
- Requests are built from `benchmarks/_shared/request_parts/` (system prompt, history, user
  messages, settings); a benchmark can override any of these files in its own `request_parts/`.
  A random nonce is prepended to the system prompt at send time.
- Each run writes `runs/<benchmark>/<timestamp>_<model>_<session>/` with `results.csv`,
  `runtime.json`, `run.log`, the `request_parts/` it used, and `analysis.md` after `analyze`.
- `actionable_ms`: tool call complete if the model calls a tool, else first text token.
  `ttfat_ms`: time to first answer token, i.e. first text or tool-call output.

## License

MIT, see [LICENSE](LICENSE). The tool definitions in `data/tools_pool_v0/` keep their original
licenses, listed in the table above.
