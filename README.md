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

## Tool definition pool

`data/tools_pool_v0/` holds 485 real tool definitions (name, description, parameters JSON
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
| Pipecat (examples) | [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | `5558d26` | BSD 2-Clause, © 2024–2026 Daily | 105 |
| Pipecat Flows (examples) | [pipecat-ai/pipecat-flows](https://github.com/pipecat-ai/pipecat-flows) | `96223f4` | BSD 2-Clause, © 2024–2026 Daily | 50 |
| LiveKit Agents (examples) | [livekit/agents](https://github.com/livekit/agents) | `5b49888` | Apache 2.0, © 2023 LiveKit, Inc. | 106 |

The definitions remain under their original licenses. All three licenses permit
redistribution provided the copyright and license notices are kept (Apache 2.0 also asks
that modifications be stated; definitions here are unmodified apart from conversion to JSON).

Pipecat's per-provider examples (`function-calling-openai`, `-anthropic`, `-groq`, …) copy
the same tools, so exact duplicates (same name, description and parameters) were dropped,
keeping the first copy by file path: 280 extracted, 105 kept. Other sources keep every tool.


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
provider SDKs) are pinned in `scripts/as_sent/requirements-*.txt`.

## License

MIT, see [LICENSE](LICENSE). The tool definitions in `data/tools_pool_v0/` keep their original
licenses, listed in the table above.
