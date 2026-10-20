"""Per-run analysis of tool-induced latency, and session comparison.

Statistics follow "A statistical approach to model evaluations" (Anthropic, 2024):
- paired differences within blocks (each block = one user message under every condition);
- standard errors clustered on the user message (blocks sharing a message are not
  independent), with t intervals on (clusters - 1) degrees of freedom;
- a power check: the smallest effect the run could detect, and blocks needed for 5%;
- robust estimates (median, cluster bootstrap CI) next to the means, since one latency
  spike can move a mean of log differences;
- effects per 1000 provider-reported tool tokens, since providers render tool schemas
  differently and tiktoken counts are only an approximation of what the model reads.
"""

import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from scipy import stats as sps

METRICS = ["actionable_ms", "ttfat_ms"]
POWER = 0.80
TARGET_EFFECT = 0.05  # report the blocks needed to detect a 5% change
FEW_CLUSTERS = 10
N_BOOT = 2000
TOKEN_IMBALANCE = 0.05  # warn if contrasted sets differ by more provider tokens than this


# ---- Loading -------------------------------------------------------------

def load_run(run_dir: Path, conditions: list[str]) -> dict:
    with open(run_dir / "results.csv") as f:
        rows = list(csv.DictReader(f))
    blocks = defaultdict(dict)
    for r in rows:
        blocks[r["block_id"]][r["condition"]] = r
    good = {b: rs for b, rs in blocks.items()
            if set(rs) == set(conditions) and not any(r["error"] for r in rs.values())}
    return {"runtime": json.loads((run_dir / "runtime.json").read_text()),
            "rows": rows, "n_blocks": len(blocks), "good": good,
            "requests": Counter(r["condition"] for r in rows),
            "errors": Counter(r["condition"] for r in rows if r["error"])}


def provider_tokens_available(run: dict) -> bool:
    return bool(run["good"]) and all(r["input_tokens"] for rs in run["good"].values()
                                     for r in rs.values())


def tool_tokens(run: dict, rs: dict, cond: str, base: str) -> float:
    """Tool tokens of one request: provider-reported (input tokens minus the same block's
    0-tool request) when available, else the tiktoken estimate."""
    if provider_tokens_available(run):
        return int(rs[cond]["input_tokens"]) - int(rs[base]["input_tokens"])
    return int(rs[cond]["total_tool_tokens"])


# ---- Estimation ----------------------------------------------------------

def estimate(values: list[float], clusters: list[str]) -> dict | None:
    """Mean with cluster-robust (CR1) SE and t interval, plus median with a cluster
    bootstrap interval. With one value per cluster the SE is std/sqrt(n)."""
    n = len(values)
    if n < 2:
        return None
    mean = statistics.mean(values)
    groups = defaultdict(list)
    for v, g in zip(values, clusters):
        groups[g].append(v)
    g = len(groups)
    if g < 2:
        return None
    se = math.sqrt(g / (g - 1) * sum((sum(vs) - len(vs) * mean) ** 2 for vs in groups.values())) / n
    df = g - 1
    t = sps.t.ppf(0.975, df)
    rng = random.Random(0)
    keys = list(groups)
    meds = sorted(statistics.median(v for k in rng.choices(keys, k=g) for v in groups[k])
                  for _ in range(N_BOOT))
    return {"n": n, "clusters": g, "mean": mean, "se": se, "lo": mean - t * se, "hi": mean + t * se,
            "detectable": (t + sps.t.ppf(POWER, df)) * se,
            "median": statistics.median(values),
            "med_lo": meds[int(0.025 * N_BOOT)], "med_hi": meds[int(0.975 * N_BOOT) - 1]}


def _slope(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else None


def run_estimates(run: dict, cfg, metric: str) -> dict:
    """All estimates of one run for one metric."""
    good, conds, base = run["good"], cfg.conditions, cfg.conditions[0]
    blocks = sorted(good)
    cl = [good[b][base]["message_id"] for b in blocks]

    def ms(b, c):
        return float(good[b][c][metric])

    def tok(b, c):
        return tool_tokens(run, good[b], c, base)

    def rate(b, c):  # added ms per 1000 tool tokens
        t = tok(b, c)
        return (ms(b, c) - ms(b, base)) / t * 1000 if t > 0 else None

    out = {"vs_base": {}, "rates": {}, "contrasts": {}, "slope": None}
    for c in conds[1:]:
        out["vs_base"][c] = {
            "log": estimate([math.log(ms(b, c) / ms(b, base)) for b in blocks], cl),
            "ms": estimate([ms(b, c) - ms(b, base) for b in blocks], cl)}
        rates = [rate(b, c) for b in blocks]
        if all(r is not None for r in rates):
            out["rates"][c] = estimate(rates, cl)
    for a, b_ in cfg.contrasts:
        rd = [(rate(b, a), rate(b, b_)) for b in blocks]
        out["contrasts"][(a, b_)] = {
            "log": estimate([math.log(ms(b, a) / ms(b, b_)) for b in blocks], cl),
            "rate": estimate([x - y for x, y in rd], cl) if all(None not in p for p in rd) else None,
            "token_diff": (statistics.mean(tok(b, a) - tok(b, b_) for b in blocks)
                           / statistics.mean(tok(b, b_) for b in blocks)) if blocks else None}
    if cfg.dose_response:
        log_s, ms_s = [], []
        for b in blocks:
            xs = [tok(b, c) / 1000 for c in conds]
            log_s.append(_slope(xs, [math.log(ms(b, c)) for c in conds]))
            ms_s.append(_slope(xs, [ms(b, c) for c in conds]))
        if None not in log_s:
            out["slope"] = {"log": estimate(log_s, cl), "ms": estimate(ms_s, cl)}
    return out


# ---- Formatting ----------------------------------------------------------

def _pct(x):
    return f"{math.exp(x) - 1:+.1%}"


def fmt_ratio(e):
    return "n/a" if not e else f"{math.exp(e['mean']):.3f} [{math.exp(e['lo']):.3f}, {math.exp(e['hi']):.3f}]"


def fmt_ratio_median(e):
    return "n/a" if not e else f"{math.exp(e['median']):.3f} [{math.exp(e['med_lo']):.3f}, {math.exp(e['med_hi']):.3f}]"


def fmt_ms_median(e):
    return "n/a" if not e else f"{e['median']:+.0f} [{e['med_lo']:+.0f}, {e['med_hi']:+.0f}]"


def fmt_mean(e, unit=""):
    return "n/a" if not e else f"{e['mean']:+.1f}{unit} [{e['lo']:+.1f}, {e['hi']:+.1f}]"


def fmt_pct_mean(e):
    return "n/a" if not e else f"{_pct(e['mean'])} [{_pct(e['lo'])}, {_pct(e['hi'])}]"


def warnings(run: dict, cfg, est: dict | None = None) -> list[str]:
    conds = cfg.conditions
    out = []
    rates = {c: run["errors"][c] / run["requests"][c] for c in conds if run["requests"][c]}
    if any(rates.values()) and max(rates.values()) > min(rates.values()):
        out.append("Error rates differ across conditions ("
                   + ", ".join(f"{c} {r:.0%}" for c, r in rates.items())
                   + "). Skipping errored blocks can bias the estimates, e.g. if slow "
                     "requests with many tools time out more often.")
    n_msgs = len({rs[conds[0]]["message_id"] for rs in run["good"].values()})
    if run["good"] and n_msgs < FEW_CLUSTERS:
        out.append(f"Only {n_msgs} distinct user messages: clustered standard errors are "
                   "unreliable with this few clusters. Use more messages in user_messages.json.")
    ok_rows = [r for r in run["rows"] if not r["error"]]
    if ok_rows and all(r["cached_tokens"] == "" for r in ok_rows):
        out.append("The provider does not report cached tokens, so the absence of prompt "
                   "caching cannot be verified.")
    elif any(int(r["cached_tokens"] or 0) > 0 for r in ok_rows):
        out.append("Some requests had cached tokens: prompt caching may have lowered latency.")
    if run["good"] and not provider_tokens_available(run):
        out.append("The provider does not report input tokens: per-token estimates use "
                   "tiktoken counts, which can differ from what the model reads.")
    for (a, b), e in (est or {}).get("contrasts", {}).items():
        if e["token_diff"] is not None and abs(e["token_diff"]) > TOKEN_IMBALANCE:
            out.append(f"{a} sets had {e['token_diff']:+.0%} provider tool tokens vs {b}: the "
                       "plain ratio mixes complexity with size, so read the per-token rate "
                       "difference instead.")
    return out


def run_header(rt: dict) -> list[str]:
    extras = [f"{k} `{rt[k]}`" for k in ("tool_choice", "reasoning_effort") if rt.get(k)]
    return [f"- model: `{rt['model']}` via `{rt['service']}` ({rt['base_url']})"
            + (", " + ", ".join(extras) if extras else ""),
            f"- started {rt['started']}, ended {rt['ended']}"]


def analyze(run_dir: Path, cfg) -> str:
    run = load_run(run_dir, cfg.conditions)
    rt, conds, base = run["runtime"], cfg.conditions, cfg.conditions[0]
    good = run["good"]
    tok_label = "provider" if provider_tokens_available(run) else "tiktoken"
    lines = [f"# {rt['benchmark']}: {rt['session']}", "", *run_header(rt),
             f"- blocks used: {len(good)} of {run['n_blocks']} "
             f"({run['n_blocks'] - len(good)} skipped for errors); "
             f"requests: {rt['n_requests']}, errors: {rt['n_errors']}", ""]
    if rt.get("tool_choice") == "none":
        lines += ["`tool_choice` is `none`: the model always answers in text, so both metrics "
                  "are the time to the first answer text and isolate the cost of reading the tools.", ""]
    lines += ["Ratios are vs the 0-tool request of the same block. *Mean* = exp(mean of log "
              "differences) with a t interval on clustered SEs; *median* = exp(median) with a "
              "cluster bootstrap interval. *Detectable* is the smallest change this run could "
              "detect with 80% power; *blocks for 5%* is the number of blocks needed to detect a "
              "5% change at the observed spread. All intervals are 95%.", ""]
    lines += [f"> **Warning:** {w}" for w in warnings(run, cfg, run_estimates(run, cfg, METRICS[0]))]

    lines += ["", "## Tool tokens and outcomes", "",
              "| condition | tiktoken tool tokens | provider tool tokens | % tool calls | errors | cached |",
              "|---|---:|---:|---:|---:|---:|"]
    for c in conds:
        rs = [good[b] for b in good]
        prov = (f"{statistics.mean(tool_tokens(run, r, c, base) for r in rs):.0f}"
                if rs and provider_tokens_available(run) else "n/a")
        est_tok = f"{statistics.mean(int(r[c]['total_tool_tokens']) for r in rs):.0f}" if rs else ""
        pct = f"{sum(r[c]['outcome'] == 'tool' for r in rs) / len(rs):.0%}" if rs else ""
        cached = sum(int(r[c]["cached_tokens"] or 0) > 0 for r in rs)
        lines.append(f"| {c} | {est_tok} | {prov} | {pct} | "
                     f"{run['errors'][c]}/{run['requests'][c]} | {cached} |")

    for metric in METRICS:
        est = run_estimates(run, cfg, metric)
        lines += ["", f"## {metric}", "",
                  "| condition | median ms | ratio, mean [95% CI] | ratio, median [95% CI] "
                  "| diff ms, median [95% CI] | detectable | blocks for 5% |",
                  "|---|---:|---|---|---|---:|---:|"]
        for c in conds:
            med = f"{statistics.median(float(good[b][c][metric]) for b in good):.0f}" if good else ""
            if c == base:
                lines.append(f"| {c} | {med} | baseline | | | | |")
                continue
            e = est["vs_base"][c]
            lg = e["log"]
            det = f"±{math.exp(lg['detectable']) - 1:.1%}" if lg else ""
            need = (str(math.ceil(lg["n"] * (lg["detectable"] / math.log(1 + TARGET_EFFECT)) ** 2))
                    if lg else "")
            lines.append(f"| {c} | {med} | {fmt_ratio(lg)} | {fmt_ratio_median(lg)} | "
                         f"{fmt_ms_median(e['ms'])} | {det} | {need} |")
        if est["rates"]:
            lines += ["", f"Added latency per 1000 {tok_label} tool tokens (ms, mean [95% CI]): "
                      + "; ".join(f"{c} {fmt_mean(e)}" for c, e in est["rates"].items())]
        if est["contrasts"]:
            lines += ["", "| contrast | ratio, mean [95% CI] | ratio, median [95% CI] "
                          f"| rate difference, ms per 1000 {tok_label} tokens [95% CI] "
                          f"| {tok_label} token difference |",
                      "|---|---|---|---|---:|"]
            for (a, b), e in est["contrasts"].items():
                td = f"{e['token_diff']:+.1%}" if e["token_diff"] is not None else "n/a"
                lines.append(f"| {a} vs {b} | {fmt_ratio(e['log'])} | {fmt_ratio_median(e['log'])} | "
                             f"{fmt_mean(e['rate'])} | {td} |")
        if est["slope"]:
            s = est["slope"]
            lines += ["", f"Dose-response (per-block regression on {tok_label} tool tokens): "
                          f"{fmt_pct_mean(s['log'])} latency and {fmt_mean(s['ms'], ' ms')} "
                          f"per 1000 tool tokens."]
    return "\n".join(lines)


def run_label(rt: dict) -> str:
    tc = f", tool_choice {rt['tool_choice']}" if rt.get("tool_choice") else ""
    return f"{rt['session']} ({rt['model']}{tc}, {rt['started'][:16]})"


def headline(run: dict, cfg, metric: str) -> dict[str, str]:
    est = run_estimates(run, cfg, metric)
    out = {f"{c} vs {cfg.conditions[0]}": fmt_ratio(e["log"]) for c, e in est["vs_base"].items()}
    for (a, b), e in est["contrasts"].items():
        out[f"{a} vs {b}"] = fmt_ratio(e["log"])
        out[f"{a} vs {b}, ms per 1000 tokens"] = fmt_mean(e["rate"])
    if est["slope"]:
        out["slope per 1000 tool tokens"] = fmt_pct_mean(est["slope"]["log"])
    return out


def compare(run_dirs: list[Path], cfg) -> str:
    runs = [load_run(d, cfg.conditions) for d in run_dirs]
    lines = ["Ratios are mean [95% CI]; sessions are separate clusters and are not pooled.", ""]
    for metric in METRICS:
        heads = [headline(r, cfg, metric) for r in runs]
        lines += [f"## {metric}", "",
                  "| estimate | " + " | ".join(f"{run_label(r['runtime'])}, {len(r['good'])} blocks"
                                               for r in runs) + " |",
                  "|---|" + "---|" * len(runs)]
        for key in heads[0]:
            lines.append(f"| {key} | " + " | ".join(h.get(key, "n/a") for h in heads) + " |")
        lines.append("")
    for r in runs:
        lines += [f"> **Warning ({r['runtime']['session']}):** {w}"
                  for w in warnings(r, cfg, run_estimates(r, cfg, METRICS[0]))]
    return "\n".join(lines)


# ---- Chart ---------------------------------------------------------------

# Categorical slots 1-3 of the dataviz reference palette (validated all-pairs for CVD).
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
SURFACE, TEXT, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def plot(run_dirs: list[Path], cfg, title: str, out: Path):
    """Dot + 95% CI per condition and session, ratio vs 0 tools, one panel per metric."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Independent of any local matplotlibrc (e.g. text.usetex treats "%" as a comment).
    plt.rcParams.update({"text.usetex": False, "font.family": "sans-serif"})
    runs = [load_run(d, cfg.conditions) for d in run_dirs]
    conds = cfg.conditions[1:]
    fig, axes = plt.subplots(1, len(METRICS), figsize=(5 * len(METRICS), 4), sharey=True,
                             facecolor=SURFACE)
    width = 0.6 / max(len(runs), 1)
    for ax, metric in zip(axes, METRICS):
        ax.set_facecolor(SURFACE)
        ax.axhline(1.0, color=MUTED, linewidth=1, linestyle="--", zorder=1)
        for k, run in enumerate(runs):
            est = run_estimates(run, cfg, metric)
            color = SERIES_COLORS[k % len(SERIES_COLORS)] if len(runs) <= 3 else MUTED
            for j, c in enumerate(conds):
                e = est["vs_base"][c]["log"]
                if not e:
                    continue
                r, lo, hi = math.exp(e["mean"]), math.exp(e["lo"]), math.exp(e["hi"])
                x = j + (k - (len(runs) - 1) / 2) * width
                ax.errorbar(x, r, yerr=[[r - lo], [hi - r]],
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
