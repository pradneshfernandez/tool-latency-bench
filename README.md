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


## License

MIT, see [LICENSE](LICENSE). The tool definitions in `data/tools_pool_v0/` keep their original
licenses, listed in the table above.
