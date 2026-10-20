"""Write extracted tools as one pretty-printed JSON file per tool. Never overwrites.

usage: write_pool.py <jsonl_dir> <pool_dir>
"""

import json
import os
import re
import sys

SRC, POOL = sys.argv[1], sys.argv[2]
ORDER = ["tau-bench", "tau2-bench", "aiewf-eval", "eva", "pipecat", "pipecat-flows", "livekit"]
KEYS = ["source", "commit", "file_path", "domain", "name", "description", "parameters"]
# pipecat's per-provider examples copy the same tools; keep the first copy (by file path) only
DEDUP = {"pipecat"}

counts, dropped = {}, {}
for source in ORDER:
    seen = set()
    for line in sorted(open(os.path.join(SRC, f"{source}.jsonl"), encoding="utf-8"),
                       key=lambda l: json.loads(l)["file_path"]):
        rec = json.loads(line)
        rec = {k: rec[k] for k in KEYS}
        if source in DEDUP:
            key = json.dumps([rec["name"], rec["description"], rec["parameters"]], sort_keys=True)
            if key in seen:
                dropped[source] = dropped.get(source, 0) + 1
                continue
            seen.add(key)
        parts = [POOL, source] + ([] if source == "aiewf-eval" else [rec["domain"]])
        d = os.path.join(*parts)
        os.makedirs(d, exist_ok=True)
        stem = re.sub(r"[^\w.-]", "_", rec["name"])
        path, n = os.path.join(d, f"{stem}.json"), 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(d, f"{stem}_{n}.json")
        with open(path, "x", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
            f.write("\n")
        counts[source] = counts.get(source, 0) + 1

for s in ORDER:
    print(f"{s:14} {counts.get(s, 0)}" + (f"  ({dropped[s]} duplicates dropped)" if s in dropped else ""))
print(f"{'total':14} {sum(counts.values())}")
