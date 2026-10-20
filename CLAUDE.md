# CLAUDE.md

## Running benchmarks

A 30-block run is 120 requests plus 3 warm-ups, about 5-10 minutes with the default 1 s pause.
Run it as a background task and check progress in its output ("block N/30", "done:").

```
uv run tool-latency-bench run <benchmark> --model <model> --service <service> \
    --session <label> --tool-choice none --reasoning-effort <lowest the model accepts>
```

- **Never run two benchmark runs at the same time.** Concurrent requests change each other's
  latency; runs must be strictly one after another.
- **Run both modes:** `--tool-choice none` is the primary measurement (cost of reading the
  tools); `--tool-choice auto` is the secondary, realistic one. Record which is which.
- **Smoke run first** with `--blocks 2` for every new model/service. Check `results.csv`: no
  errors, `input_tokens` grows with `n_tools`, `cached_tokens` 0 or empty. Then delete the
  smoke run folder so `compare` does not include it.
- **Reasoning on the lowest setting the model accepts** (`none` or `minimal`; some models
  reject one of them with HTTP 400). Record the value used.
- **Do not change** `benchmarks/_shared/request_parts/`, `data/pools/` or `data/tool_stats.csv`
  between sessions of the same campaign; results across sessions are only comparable if the
  requests are built the same way.
- If a provider returns many 429/503 errors or first tokens take several seconds, stop and
  report it rather than continuing: the run would measure queueing, not tool overhead.
- `.env` holds API keys; never commit it or print its contents. `runs/` is gitignored.

After each run: `uv run tool-latency-bench analyze <run_dir>`. After all sessions of a
benchmark: `uv run tool-latency-bench compare <benchmark>`.
