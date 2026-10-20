"""Tool loading, token counting and grouping (Step 1), pools and the Experiment 2 budget (Step 2)."""

import csv
import functools
import json
import math
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL_DIR = ROOT / "data" / "tools_pool_v0"
STATS_CSV = ROOT / "data" / "tool_stats.csv"
POOLS_DIR = ROOT / "data" / "pools"
BUDGET_FILE = POOLS_DIR / "exp2_budget.json"

EXP1_MIN_TOOLS = 150
EXP2_SET_SIZE = 20
EXP2_TOLERANCE = 0.05
EXP2_MIN_BAND = 40  # each group needs this many tools near the per-tool target


def compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def load_tool(tool_id: str) -> dict:
    """tool_id is the repo-relative path of the tool file."""
    t = json.loads((ROOT / tool_id).read_text())
    return {"type": "function",
            "function": {"name": t["name"], "description": t["description"],
                         "parameters": t["parameters"]}}


def _is_nested(node) -> bool:
    """True if a property schema contains an object or array anywhere."""
    if isinstance(node, list):
        return any(_is_nested(x) for x in node)
    if not isinstance(node, dict):
        return False
    types = node.get("type")
    types = types if isinstance(types, list) else [types]
    if {"object", "array"} & set(types) or {"properties", "items", "$ref"} & set(node):
        return True
    return any(_is_nested(v) for v in node.values())


def _has_enum(node) -> bool:
    if isinstance(node, list):
        return any(_has_enum(x) for x in node)
    if isinstance(node, dict):
        return "enum" in node or any(_has_enum(v) for v in node.values())
    return False


def group(parameters: dict) -> str:
    props = list((parameters.get("properties") or {}).values())
    if parameters.get("$defs") or _is_nested(props):
        return "complex"
    if len(props) >= 3 or _has_enum(props):
        return "medium"
    return "simple"


def encoder():
    try:
        import tiktoken
        return tiktoken.get_encoding("o200k_base")
    except Exception as e:
        raise SystemExit(f"tiktoken o200k_base could not be loaded: {e!r}")


def tool_tokens() -> dict[str, int]:
    with open(STATS_CSV) as f:
        return {r["tool_id"]: int(r["tokens"]) for r in csv.DictReader(f)}


def load_pool(name: str) -> list[str]:
    return json.loads((POOLS_DIR / f"{name}.json").read_text())


def _quartiles(xs):
    xs = sorted(xs)
    q1, q2, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return [xs[0], q1, q2, q3, xs[-1]]


# ---- Step 1 ---------------------------------------------------------------

def write_stats():
    enc = encoder()
    rows = []
    for path in sorted(POOL_DIR.rglob("*.json")):
        tool_id = str(path.relative_to(ROOT))
        raw = json.loads(path.read_text())
        rows.append({"tool_id": tool_id, "source": raw["source"], "name": raw["name"],
                     "tokens": len(enc.encode(compact(load_tool(tool_id)))),
                     "group": group(raw["parameters"])})
    with open(STATS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {STATS_CSV.relative_to(ROOT)} ({len(rows)} tools)\n")
    print(f"{'group':8} {'n':>4} {'min':>6} {'q1':>6} {'median':>6} {'q3':>6} {'max':>6}")
    for g in ["simple", "medium", "complex", "all"]:
        toks = [r["tokens"] for r in rows if g == "all" or r["group"] == g]
        print(f"{g:8} {len(toks):4} " + " ".join(f"{q:6.0f}" for q in _quartiles(toks)))


# ---- Step 2 ---------------------------------------------------------------

def _narrowest_range(tokens, k):
    """Smallest [lo, hi] containing at least k of the token counts."""
    t = sorted(tokens)
    i = min(range(len(t) - k + 1), key=lambda i: t[i + k - 1] - t[i])
    return t[i], t[i + k - 1]


def _write_json(path, obj):
    path.write_text(json.dumps(obj, indent=1) + "\n")


def write_pools():
    with open(STATS_CSV) as f:
        rows = [{**r, "tokens": int(r["tokens"])} for r in csv.DictReader(f)]
    simple = [r for r in rows if r["group"] == "simple"]
    medium = [r for r in rows if r["group"] == "medium"]

    lo, hi = _narrowest_range([r["tokens"] for r in simple], EXP1_MIN_TOOLS)
    exp1 = [r["tool_id"] for r in simple if lo <= r["tokens"] <= hi]
    POOLS_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(POOLS_DIR / "exp1.json", sorted(exp1))
    _write_json(POOLS_DIR / "exp2_simple.json", sorted(r["tool_id"] for r in simple))
    _write_json(POOLS_DIR / "exp2_medium.json", sorted(r["tool_id"] for r in medium))

    print(f"exp1:        {len(exp1)} simple tools, tokens {lo}-{hi} "
          f"(narrowest range with >= {EXP1_MIN_TOOLS})")
    print(f"exp2_simple: {len(simple)} tools")
    print(f"exp2_medium: {len(medium)} tools")
    print(f"saved to {POOLS_DIR.relative_to(ROOT)}/\n")
    write_budget()


# ---- Experiment 2 budget --------------------------------------------------

@functools.cache
def _names() -> dict[str, str]:
    with open(STATS_CSV) as f:
        return {r["tool_id"]: r["name"] for r in csv.DictReader(f)}


def tool_name(tool_id: str) -> str:
    return _names()[tool_id]


def unique_names(ids) -> bool:
    """APIs such as Gemini reject a request with two tools of the same name."""
    names = [tool_name(i) for i in ids]
    return len(names) == len(set(names))


def sample_unique(rng, pool, k) -> list[str]:
    """k tools in random order with no repeated name: shuffle, keep first of each name."""
    seen, out = set(), []
    for i in rng.sample(pool, len(pool)):
        if tool_name(i) not in seen:
            seen.add(tool_name(i))
            out.append(i)
            if len(out) == k:
                return out
    raise RuntimeError(f"pool has fewer than {k} distinct tool names")


def within_budget(ids, tokens, budget) -> bool:
    return (unique_names(ids)
            and abs(sum(tokens[i] for i in ids) - budget) <= EXP2_TOLERANCE * budget)


def draw_within_budget(rng, tokens, budget, groups):
    """groups: list of (pool, k). Redraw until the total lands within the budget."""
    for _ in range(1_000_000):
        ids = [i for pool, k in groups for i in rng.sample(pool, k)]
        if within_budget(ids, tokens, budget):
            rng.shuffle(ids)
            return ids
    raise RuntimeError(f"could not draw a set within budget {budget}")


def _acceptance(rng, tokens, budget, groups, trials):
    hits = sum(within_budget([i for pool, k in groups for i in rng.sample(pool, k)], tokens, budget)
               for _ in range(trials))
    return hits / trials


def write_budget():
    """Find the narrowest per-tool token band holding enough simple and medium tools, then
    the budget inside it that random draws hit most often. Writes data/pools/exp2_budget.json."""
    tokens = tool_tokens()
    simple, medium = load_pool("exp2_simple"), load_pool("exp2_medium")
    n = EXP2_SET_SIZE

    def band(pool, c, w):
        return [i for i in pool if abs(tokens[i] - c) <= w]

    best = None
    for w in range(1, 500):
        for c in range(1, 1000):
            k = min(len(band(simple, c, w)), len(band(medium, c, w)))
            if k >= EXP2_MIN_BAND and (best is None or k > best[0]):
                best = (k, c, w)
        if best:
            break
    _, c, w = best
    s_band, m_band = band(simple, c, w), band(medium, c, w)

    rng = random.Random(0)
    sets = {"simple": [(s_band, n)], "medium": [(m_band, n)],
            "mixed": [(s_band, n // 2), (m_band, n - n // 2)]}
    budget, worst = None, -1
    for b in range(n * (c - w), n * (c + w) + 1, 10):
        r = min(_acceptance(rng, tokens, b, g, 500) for g in sets.values())
        if r > worst:
            budget, worst = b, r
    rates = {k: _acceptance(rng, tokens, budget, g, 4000) for k, g in sets.items()}

    _write_json(BUDGET_FILE, {
        "budget": budget, "tolerance": EXP2_TOLERANCE, "set_size": n,
        "band": [c - w, c + w], "acceptance": rates,
        "simple": sorted(s_band), "medium": sorted(m_band)})

    print(f"exp2 per-tool band: {c - w}-{c + w} tokens "
          f"(narrowest with >= {EXP2_MIN_BAND} tools in each group)")
    print(f"  simple in band: {len(s_band)} of {len(simple)}, "
          f"C({len(s_band)},{n}) = {math.comb(len(s_band), n):.1e} combinations")
    print(f"  medium in band: {len(m_band)} of {len(medium)}, "
          f"C({len(m_band)},{n}) = {math.comb(len(m_band), n):.1e} combinations")
    print(f"exp2 budget: {budget} tokens per set of {n}, +/-{EXP2_TOLERANCE:.0%} "
          f"({budget * (1 - EXP2_TOLERANCE):.0f}-{budget * (1 + EXP2_TOLERANCE):.0f})")
    print("  random draws landing in budget: "
          + ", ".join(f"{k} {v:.0%}" for k, v in rates.items()))
    print(f"saved to {BUDGET_FILE.relative_to(ROOT)}")
