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
uv run tool-latency-bench run exp1_tool_count --model <model> --service groq --session morning \
    --tool-choice none --reasoning-effort <lowest the model accepts>
uv run tool-latency-bench analyze runs/exp1_tool_count/<timestamp>_<model>_morning   # analysis.md + .png
uv run tool-latency-bench compare exp1_tool_count    # runs side by side -> runs/<benchmark>/comparison.md + .png
```

- **Benchmarks.** `exp1_tool_count`: 0 / 10 / 30 / 60 tools of similar size (nested random
  subsets). `exp2_complexity`: 0 tools vs 20 simple / 20 medium / 10+10 mixed tools with the
  same total tiktoken count (±5%).
- **Services** (`--service`): `openai`, `google`, `groq`, `cerebras`, each an OpenAI-compatible
  base URL plus an API key read from the environment or `.env`; and `fake`, a local streaming
  server with simulated delay for dry runs without a key.
- **Requests** are built from `benchmarks/_shared/request_parts/` (system prompt, history, 30
  user messages, settings); a benchmark can override any of these files in its own
  `request_parts/`. A random nonce is prepended to the system prompt at send time. Tool sets
  never contain two tools with the same name (some APIs reject that).
- **Two modes** (`--tool-choice`):
  - `none` (**primary**): the tools are in the prompt but the model always answers in text, so
    the time to first answer text isolates the cost of the model reading the tool definitions.
  - `auto` (secondary, realistic): the model may call a tool. Then `actionable_ms` also
    includes generating the call's arguments (longer for tools with more parameters), and
    whether it calls one depends on whether the drawn set has a relevant tool.
- **Metrics.** `actionable_ms`: tool call complete if the model calls a tool, else first answer
  text. `ttfat_ms`: first answer text or first tool-call output. Answer text skips whitespace and
  a leading `<think>...</think>` block, which some open-weight models put in `content`.
- `--reasoning-effort` is sent as `reasoning_effort`; use the lowest value the model accepts
  (e.g. `minimal` for `gemini-3.5-flash-lite`, `none` for `gemini-3.8-flash`).
- Each run writes `runs/<benchmark>/<timestamp>_<model>_<session>/` with `results.csv`,
  `runtime.json` (model, settings, seed, versions, counts), `run.log`, the `request_parts/` it
  used, and `analysis.md` + `analysis.png` after `analyze`.

### Statistics

Following [A statistical approach to model evaluations](https://www.anthropic.com/research/statistical-approach-to-model-evals):

- **Paired differences.** Each block sends one user message under every condition in random
  order, so effects are within-block differences in log latency, reported as ratios.
- **Direct contrasts.** Experiment 2 reports medium vs simple and mixed vs simple as paired
  contrasts within each block, not by comparing two intervals vs 0 tools. Experiment 1 reports a
  dose-response slope (per-block regression on tool tokens) as well as each condition vs 0.
- **Provider tokens.** Providers render tool schemas differently, so tiktoken counts are only an
  approximation (in a Gemini smoke test, medium tools cost 1.22× their tiktoken count and simple
  tools 1.13×). Tool tokens are therefore also measured as the provider's input tokens minus the
  same block's 0-tool request, and effects are reported per 1000 of those tokens. A warning is
  shown when contrasted sets differ by more than 5% in provider tokens; then compare the
  per-token rates rather than the plain ratio.
- **Clustered standard errors and t intervals.** SEs are clustered on the user message (30
  distinct messages, so the default 30 blocks use each once); 95% intervals use the t
  distribution with (clusters − 1) degrees of freedom. A warning is shown with fewer than 10
  clusters.
- **Robust estimates.** Next to each mean, the median with a cluster bootstrap interval, since one
  latency spike can move a mean. The ms differences also get bootstrap intervals.
- **Power.** Each effect reports the smallest change the run could detect with 80% power, and the
  blocks needed to detect a 5% change at the observed spread. A "no difference" result only rules
  out effects larger than the detectable size.
- **Errors per condition.** Blocks with an errored request are skipped; errors are counted per
  condition and a warning is shown if they are uneven, since skipping them can bias the result.
- **Sessions are reported side by side, not pooled.** Each time-of-day session is its own
  cluster; with three of them they are a replication check, not extra precision.

### Known limitations

- **Experiment 1 varies count and tokens together** (10 tools ≈ 740 tokens, 60 ≈ 4,400), so it
  measures latency vs tool-definition load; it cannot separate "more tools" from "more tokens".
- **Experiment 2's simple sets are not typical simple tools.** To share a token budget with
  medium tools they come from the 125–185-token band (the top ~15% of simple tools, i.e. with
  long descriptions), so the contrast is closer to "description-heavy vs schema-heavy" tools of
  about 150 tokens each.
- **Prompt caching** is prevented by a nonce at the start of the system prompt and by random tool
  order. It can only be verified on providers that report `cached_tokens` (Gemini's endpoint
  does not).
- **TTFAT on tool calls** depends on how the provider streams them: some send the whole call in
  one chunk, so TTFAT equals the completed call. Compare `ttfat_ms` across providers with care;
  `tool_choice none` avoids this.

### Status

Both benchmarks have been run end to end against the `fake` service, and a 1-block smoke run
against Gemini's free tier completed without errors. No full real-provider sessions have been
run yet: free-tier Gemini latency (8-34 s per request in testing) is dominated by queueing, so
it cannot measure tool overhead. Results from contributors with paid or fast-provider access
are very welcome.

### Contributing results

1. Put your key in `.env` (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY` or
   `CEREBRAS_API_KEY`) and run `uv sync`.
2. Smoke run first and check `results.csv`: no errors, `input_tokens` grows with `n_tools`
   (with `--tool-choice none` too, which confirms the provider keeps the tools in the prompt):
   `uv run tool-latency-bench run exp1_tool_count --model <model> --service <service> --session smoke --blocks 2 --tool-choice none --reasoning-effort <lowest>`
   Then delete the smoke run folder.
3. Run both benchmarks in both modes (`--tool-choice none`, then `--tool-choice auto`), 30
   blocks each, one run at a time. Ideally repeat at three times of day with session labels such
   as `morning`, `afternoon`, `night`.
4. Run `analyze` on each run folder.
5. Share the run folders: open a PR adding them under `results/<service>/<model>/`, or zip them
   and post them. A run folder holds `results.csv`, `runtime.json`, `run.log`, the request parts
   and `analysis.md`; API keys are never written to it.

### Claude Code prompt

To run a full campaign with [Claude Code](https://claude.com/claude-code), paste this prompt
(fill in the placeholders). `CLAUDE.md` holds the standing rules it follows.

```
Run the tool latency benchmarks for model <model> on service <service>, with
reasoning_effort <lowest setting the model accepts>, session label <label>.

1. Check that the API key for <service> is set in .env (do not print it).
2. Smoke run exp1_tool_count with --blocks 2 --tool-choice none. Confirm no errors,
   input_tokens grows with n_tools, and cached_tokens is 0 or empty. If first tokens take
   more than a few seconds or there are 429/503 errors, stop and tell me. Delete the
   smoke run folder.
3. Run, one after the other (never in parallel), in the background, 30 blocks each:
   exp1_tool_count --tool-choice none, exp2_complexity --tool-choice none,
   exp1_tool_count --tool-choice auto, exp2_complexity --tool-choice auto.
4. Run analyze on every run folder, then compare for both benchmarks.
5. Report the comparison tables, the charts (comparison.png), every warning, the
   exp2 contrasts (medium vs simple, per 1000 provider tokens), the exp1 slope, and the
   detectable effect sizes. Do not change the request parts, pools or tool stats.
```

Repeat with a different session label (e.g. `morning`, `afternoon`, `night`) at other times
of day.

## License

MIT, see [LICENSE](LICENSE). The tool definitions in `data/tools_pool_v0/` keep their original
licenses, listed in the table above.
