"""Experiment 2: latency vs tool complexity at equal tool count and equal total tokens."""

import json

from tool_latency_bench.tools import BUDGET_FILE, draw_within_budget, tool_tokens


class BenchmarkConfig:
    """Configuration for the complexity benchmark."""

    name = "exp2_complexity"
    description = "0 tools vs 20 simple / 20 medium / 10+10 mixed tools at the same total tokens"

    # Condition names in display order; the first is the 0-tool baseline.
    conditions = ["none", "simple", "medium", "mixed"]
    default_blocks = 30
    dose_response = False
    # The question of this benchmark: direct paired comparisons between tool types.
    contrasts = [("medium", "simple"), ("mixed", "simple")]

    def __init__(self):
        if not BUDGET_FILE.exists():
            raise SystemExit("data/pools/exp2_budget.json missing; run `tool-latency-bench build-pools`")
        b = json.loads(BUDGET_FILE.read_text())
        self.budget, self.n = b["budget"], b["set_size"]
        self.simple, self.medium = b["simple"], b["medium"]
        self.band, self.tolerance = b["band"], b["tolerance"]
        self.tokens = tool_tokens()

    def info(self) -> dict:
        return {"budget": self.budget, "tolerance": self.tolerance, "set_size": self.n,
                "band": self.band, "simple_pool_size": len(self.simple),
                "medium_pool_size": len(self.medium)}

    def make_block(self, rng) -> dict[str, list[str]]:
        n, t, b = self.n, self.tokens, self.budget
        return {"none": [],
                "simple": draw_within_budget(rng, t, b, [(self.simple, n)]),
                "medium": draw_within_budget(rng, t, b, [(self.medium, n)]),
                "mixed": draw_within_budget(rng, t, b, [(self.simple, n // 2),
                                                        (self.medium, n - n // 2)])}
