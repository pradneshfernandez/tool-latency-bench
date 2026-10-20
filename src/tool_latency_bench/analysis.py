"""Per-run analysis of log-latency differences from the 0-tool condition, and session comparison.

Statistics follow "A statistical approach to model evaluations" (Anthropic, 2024):
paired differences within blocks, standard errors clustered on the user message
(blocks that share a message are not independent), and a power check giving the
smallest effect the run could reliably detect.
"""

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

METRICS = ["actionable_ms", "ttfat_ms"]
Z_95 = 1.96
Z_POWER = Z_95 + 0.84  # two-sided 5% test with 80% power
TARGET_EFFECT = 0.05  # report the blocks needed to detect a 5% change
FEW_CLUSTERS = 10


def load_run(run_dir: Path, conditions: list[str]) -> dict:
    with open(run_dir / "results.csv") as f:
        rows = list(csv.DictReader(f))
    blocks = defaultdict(dict)
    for r in rows:
        blocks[r["block_id"]][r["condition"]] = r
    good = {b: rs for b, rs in blocks.items()
            if set(rs) == set(conditions) and not any(r["error"] for r in rs.values())}
    return {"runtime": json.loads((run_dir / "runtime.json").read_text()),
            "n_blocks": len(blocks), "good": good,
            "requests": Counter(r["condition"] for r in rows),
            "errors": Counter(r["condition"] for r in rows if r["error"])}


def clustered_mean_se(d: list[float], clusters: list[str]):
    """Mean and cluster-robust SE (CR1). Equals std/sqrt(n) when every cluster has one value."""
    n, mean = len(d), statistics.mean(d)
    sums = defaultdict(float)
    for x, g in zip(d, clusters):
        sums[g] += x - mean
    g = len(sums)
    if g < 2:
        return mean, math.nan, g
    return mean, math.sqrt(g / (g - 1) * sum(s * s for s in sums.values())) / n, g


def condition_stats(run: dict, conditions: list[str], metric: str) -> dict:
    good, base = run["good"], conditions[0]
    out = {}
    for cond in conditions:
        rs = [good[b][cond] for b in good]
        st = {"n": len(rs), "requests": run["requests"][cond], "errors": run["errors"][cond]}
        if rs:
            st.update(tool_tokens=statistics.mean(int(r["total_tool_tokens"]) for r in rs),
                      pct_tool=sum(r["outcome"] == "tool" for r in rs) / len(rs),
                      cached=sum(int(r["cached_tokens"] or 0) > 0 for r in rs),
                      median_ms=statistics.median(float(r[metric]) for r in rs))
        if cond != base and len(rs) >= 2:
            d = [math.log(float(good[b][cond][metric])) - math.log(float(good[b][base][metric]))
                 for b in good]
            mean, se, g = clustered_mean_se(d, [good[b][base]["message_id"] for b in good])
            st.update(ratio=math.exp(mean), lo=math.exp(mean - Z_95 * se),
                      hi=math.exp(mean + Z_95 * se), clusters=g,
                      diff_ms=statistics.median(float(good[b][cond][metric]) -
                                                float(good[b][base][metric]) for b in good),
                      mde=math.exp(Z_POWER * se) - 1,
                      blocks_needed=math.ceil(len(d) * (Z_POWER * se / math.log(1 + TARGET_EFFECT)) ** 2))
        out[cond] = st
    return out


def fmt_effect(st: dict) -> str:
    if "ratio" not in st:
        return "n/a"
    return f"{st['ratio']:.3f} [{st['lo']:.3f}, {st['hi']:.3f}], {st['diff_ms']:+.0f} ms"


def warnings(run: dict, conditions: list[str], stats: dict) -> list[str]:
    out = []
    rates = {c: run["errors"][c] / run["requests"][c] for c in conditions if run["requests"][c]}
    if any(rates.values()) and max(rates.values()) - min(rates.values()) > 0:
        out.append("Error rates differ across conditions ("
                   + ", ".join(f"{c} {r:.0%}" for c, r in rates.items())
                   + "). Skipping errored blocks can bias the estimates, e.g. if slow "
                     "requests with many tools time out more often.")
    clusters = min((st["clusters"] for st in stats.values() if "clusters" in st), default=None)
    if clusters is not None and clusters < FEW_CLUSTERS:
        out.append(f"Only {clusters} distinct user messages: clustered standard errors are "
                   "unreliable with this few clusters. Use more messages in user_messages.json.")
    return out


def analyze(run_dir: Path, conditions: list[str]) -> str:
    run = load_run(run_dir, conditions)
    rt, total, good = run["runtime"], run["n_blocks"], run["good"]
    lines = [f"# {rt['benchmark']}: {rt['session']}", "",
             f"- model: `{rt['model']}` via `{rt['service']}` ({rt['base_url']})"
             + (f", reasoning_effort `{rt['reasoning_effort']}`" if rt.get("reasoning_effort") else ""),
             f"- started {rt['started']}, ended {rt['ended']}",
             f"- blocks used: {len(good)} of {total} ({total - len(good)} skipped for errors); "
             f"requests: {rt['n_requests']}, errors: {rt['n_errors']}", "",
             "Effect = exp(mean of per-block log differences vs the 0-tool condition) "
             f"[95% CI: mean ± {Z_95} × SE, SE clustered on user message], then the median "
             "per-block difference in ms. *Detectable* is the smallest change this run could "
             f"detect with 80% power (± {Z_POWER:.2f} × SE); *blocks for 5%* is the number of "
             "blocks needed to detect a 5% change at the observed spread.", ""]
    for metric in METRICS:
        stats = condition_stats(run, conditions, metric)
        lines += [f"## {metric}", ""]
        lines += [f"> **Warning:** {w}" for w in warnings(run, conditions, stats)]
        lines += ["", "| condition | tool tokens | % tool calls | errors | cached | median ms "
                      "| ratio vs 0 tools [95% CI], median diff | detectable | blocks for 5% |",
                  "|---|---:|---:|---:|---:|---:|---|---:|---:|"]
        for c in conditions:
            st = stats[c]
            err = f"{st['errors']}/{st['requests']}"
            if not st["n"]:
                lines.append(f"| {c} | | | {err} | | | no data | | |")
                continue
            if c == conditions[0]:
                effect, mde, need = "baseline", "", ""
            else:
                effect = fmt_effect(st)
                mde = f"±{st['mde']:.1%}" if "mde" in st else ""
                need = str(st["blocks_needed"]) if "blocks_needed" in st else ""
            lines.append(f"| {c} | {st['tool_tokens']:.0f} | {st['pct_tool']:.0%} | {err} | "
                         f"{st['cached']} | {st['median_ms']:.0f} | {effect} | {mde} | {need} |")
        lines.append("")
    return "\n".join(lines)


def run_label(rt: dict) -> str:
    return f"{rt['session']} ({rt['model']}, {rt['started'][:16]})"


def compare(run_dirs: list[Path], conditions: list[str]) -> str:
    runs = [load_run(d, conditions) for d in run_dirs]
    lines = []
    for metric in METRICS:
        all_stats = [condition_stats(r, conditions, metric) for r in runs]
        lines += [f"## {metric}: ratio vs 0 tools [95% CI], median diff", "",
                  "| condition | " + " | ".join(f"{run_label(r['runtime'])}, {len(r['good'])} blocks"
                                                for r in runs) + " |",
                  "|---|" + "---|" * len(runs)]
        for c in conditions[1:]:
            lines.append(f"| {c} | " + " | ".join(fmt_effect(s[c]) for s in all_stats) + " |")
        lines.append("")
        for r, s in zip(runs, all_stats):
            lines += [f"> **Warning ({r['runtime']['session']}):** {w}"
                      for w in warnings(r, conditions, s)]
        lines.append("")
    return "\n".join(lines)


# Categorical slots 1-3 of the dataviz reference palette (validated all-pairs for CVD).
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE, TEXT, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def plot(run_dirs: list[Path], conditions: list[str], title: str, out: Path):
    """Dot + 95% CI per condition and session, ratio vs 0 tools, one panel per metric."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Independent of any local matplotlibrc (e.g. text.usetex treats "%" as a comment).
    plt.rcParams.update({"text.usetex": False, "font.family": "sans-serif"})
    runs = [load_run(d, conditions) for d in run_dirs]
    conds = conditions[1:]
    fig, axes = plt.subplots(1, len(METRICS), figsize=(5 * len(METRICS), 4), sharey=True,
                             facecolor=SURFACE)
    width = 0.6 / max(len(runs), 1)
    for ax, metric in zip(axes, METRICS):
        ax.set_facecolor(SURFACE)
        ax.axhline(1.0, color=MUTED, linewidth=1, linestyle="--", zorder=1)
        for k, run in enumerate(runs):
            stats = condition_stats(run, conditions, metric)
            color = SERIES_COLORS[k % len(SERIES_COLORS)] if len(runs) <= 3 else MUTED
            for j, c in enumerate(conds):
                st = stats[c]
                if "ratio" not in st:
                    continue
                x = j + (k - (len(runs) - 1) / 2) * width
                ax.errorbar(x, st["ratio"], yerr=[[st["ratio"] - st["lo"]], [st["hi"] - st["ratio"]]],
                            fmt="o", markersize=7, color=color, ecolor=color, elinewidth=2,
                            capsize=0, markeredgecolor=SURFACE, markeredgewidth=2, zorder=3,
                            label=run["runtime"]["session"] if j == 0 else None)
        ax.set_xticks(range(len(conds)), conds)
        ax.set_title(metric, color=TEXT, fontsize=11, loc="left")
        ax.grid(axis="y", color=GRID, linewidth=1)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=9)
    axes[0].set_ylabel("latency ratio vs 0 tools (95% CI)", color=MUTED, fontsize=9)
    fig.suptitle(title, color=TEXT, fontsize=12, x=0.01, ha="left")
    if len(runs) >= 2:
        axes[-1].legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
