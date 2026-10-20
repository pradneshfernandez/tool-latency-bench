"""Experiment 1: latency vs number of tools (nested random subsets of near-equal-size tools)."""

from tool_latency_bench.tools import load_pool, sample_unique


class BenchmarkConfig:
    """Configuration for the tool-count benchmark."""

    name = "exp1_tool_count"
    description = "0 / 10 / 30 / 60 simple tools of similar size, nested subsets"

    # Condition names in display order; the first is the 0-tool baseline.
    conditions = ["0", "10", "30", "60"]
    default_blocks = 30
    # Count and tokens grow together here, so the slope is reported per 1000 tool tokens.
    dose_response = True
    contrasts = []

    def __init__(self):
        self.pool = load_pool("exp1")

    def info(self) -> dict:
        return {"pool": "data/pools/exp1.json", "pool_size": len(self.pool)}

    def make_block(self, rng) -> dict[str, list[str]]:
        """Draw 60 (distinct names), take 30 of those, then 10 of those 30."""
        s60 = sample_unique(rng, self.pool, 60)
        s30 = rng.sample(s60, 30)
        s10 = rng.sample(s30, 10)
        return {"0": [], "10": s10, "30": s30, "60": s60}
