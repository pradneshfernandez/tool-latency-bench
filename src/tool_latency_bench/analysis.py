"""Per-run analysis of log-latency differences from the 0-tool condition, and session comparison."""

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

METRICS = ["actionable_ms", "ttfat_ms"]


def load_blocks(run_dir: Path, conditions: list[str]):
    """Returns (number of blocks, complete error-free blocks as {block_id: {condition: row}})."""
    with open(run_dir / "results.csv") as f:
        rows = list(csv.DictReader(f))
    blocks = defaultdict(dict)
    for r in rows:
        blocks[r["block_id"]][r["condition"]] = r
    good = {b: rs for b, rs in blocks.items()
            if set(rs) == set(conditions) and not any(r["error"] for r in rs.values())}
    return len(blocks), good


def condition_stats(good: dict, conditions: list[str], metric: str) -> dict:
    """Per condition: descriptive stats, and for non-baseline conditions the mean block
    difference in log(metric) vs the baseline with a 95% CI (as ratios) and the median
    difference in ms."""
    base = conditions[0]
    out = {}
    for cond in conditions:
        rs = [good[b][cond] for b in good]
        st = {"n": len(rs)}
        if rs:
            st.update(tool_tokens=statistics.mean(int(r["total_tool_tokens"]) for r in rs),
                      pct_tool=sum(r["outcome"] == "tool" for r in rs) / len(rs),
                      cached=sum(int(r["cached_tokens"] or 0) > 0 for r in rs),
                      median_ms=statistics.median(float(r[metric]) for r in rs))
        if cond != base and len(rs) >= 2:
            d = [math.log(float(good[b][cond][metric])) - math.log(float(good[b][base][metric]))
                 for b in good]
            mean, se = statistics.mean(d), statistics.stdev(d) / math.sqrt(len(d))
            st.update(ratio=math.exp(mean), lo=math.exp(mean - 1.96 * se),
                      hi=math.exp(mean + 1.96 * se),
                      diff_ms=statistics.median(float(good[b][cond][metric]) -
                                                float(good[b][base][metric]) for b in good))
        out[cond] = st
    return out


def fmt_effect(st: dict) -> str:
    if "ratio" not in st:
        return "n/a"
    return f"{st['ratio']:.3f} [{st['lo']:.3f}, {st['hi']:.3f}], {st['diff_ms']:+.0f} ms"


def analyze(run_dir: Path, conditions: list[str]) -> str:
    runtime = json.loads((run_dir / "runtime.json").read_text())
    total, good = load_blocks(run_dir, conditions)
    lines = [f"# {runtime['benchmark']}: {runtime['session']}", "",
             f"- model: `{runtime['model']}` via `{runtime['service']}` ({runtime['base_url']})",
             f"- started {runtime['started']}, ended {runtime['ended']}",
             f"- blocks used: {len(good)} of {total} ({total - len(good)} skipped for errors); "
             f"requests: {runtime['n_requests']}, errors: {runtime['n_errors']}", "",
             "Effect = exp(mean of per-block log differences vs the 0-tool condition) "
             "[95% CI: mean ± 1.96 × SE], then the median per-block difference in ms.", ""]
    for metric in METRICS:
        stats = condition_stats(good, conditions, metric)
        lines += [f"## {metric}", "",
                  "| condition | tool tokens | % tool calls | cached | median ms | ratio vs 0 tools [95% CI], median diff |",
                  "|---|---:|---:|---:|---:|---|"]
        for c in conditions:
            st = stats[c]
            if not st["n"]:
                lines.append(f"| {c} | | | | | no data |")
                continue
            effect = "baseline" if c == conditions[0] else fmt_effect(st)
            lines.append(f"| {c} | {st['tool_tokens']:.0f} | {st['pct_tool']:.0%} | {st['cached']} | "
                         f"{st['median_ms']:.0f} | {effect} |")
        lines.append("")
    return "\n".join(lines)


def compare(run_dirs: list[Path], conditions: list[str]) -> str:
    runs = []
    for d in run_dirs:
        rt = json.loads((d / "runtime.json").read_text())
        _, good = load_blocks(d, conditions)
        runs.append((f"{rt['session']} ({rt['model']}, {rt['started'][:16]}, {len(good)} blocks)", good))
    lines = []
    for metric in METRICS:
        lines += [f"## {metric}: ratio vs 0 tools [95% CI], median diff", "",
                  "| condition | " + " | ".join(label for label, _ in runs) + " |",
                  "|---|" + "---|" * len(runs)]
        for c in conditions[1:]:
            cells = [fmt_effect(condition_stats(good, conditions, metric)[c]) for _, good in runs]
            lines.append(f"| {c} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)
