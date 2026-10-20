"""Write extracted tools as one pretty-printed JSON file per tool. Never overwrites.

usage: write_pool.py <jsonl_dir> <pool_dir>

Duplicates dropped (exact: same name, description and parameters):
- within pipecat: its per-provider examples copy the same tools; the first copy by file path stays.
- across sources, the copy outside the project the tool originates from:
  1. pipecat tools from examples/flows/ that match a pipecat-flows tool (pipecat bundles copies of
     the Pipecat Flows examples);
  2. pipecat-flows tools that match a pipecat tool from elsewhere in pipecat (Flows examples
     reusing Pipecat's demo tools, e.g. get_current_weather).
File names are assigned before dropping, so removing a duplicate never renames another file.
"""

import json
import os
import re
import sys

SRC, POOL = sys.argv[1], sys.argv[2]
ORDER = ["tau-bench", "tau2-bench", "aiewf-eval", "eva", "pipecat", "pipecat-flows", "livekit"]
KEYS = ["source", "commit", "file_path", "domain", "name", "description", "parameters"]
DEDUP = {"pipecat"}


def key(rec):
    return json.dumps([rec["name"], rec["description"], rec["parameters"]], sort_keys=True)


# pass 1: records in output order, with their file paths and within-source dedup
recs, taken, within = [], set(), {}
for source in ORDER:
    seen = set()
    for line in sorted(open(os.path.join(SRC, f"{source}.jsonl"), encoding="utf-8"),
                       key=lambda l: json.loads(l)["file_path"]):
        rec = json.loads(line)
        rec = {k: rec[k] for k in KEYS}
        if source in DEDUP:
            if key(rec) in seen:
                within[source] = within.get(source, 0) + 1
                continue
            seen.add(key(rec))
        d = os.path.join(*([POOL, source] + ([] if source == "aiewf-eval" else [rec["domain"]])))
        stem = re.sub(r"[^\w.-]", "_", rec["name"])
        path, n = os.path.join(d, f"{stem}.json"), 1
        while path in taken:
            n += 1
            path = os.path.join(d, f"{stem}_{n}.json")
        taken.add(path)
        recs.append((path, rec))

# pass 2: cross-source duplicates between pipecat and pipecat-flows
flows_keys = {key(r) for _, r in recs if r["source"] == "pipecat-flows"}
drop = {p for p, r in recs if r["source"] == "pipecat" and r["file_path"].startswith("examples/flows/")
        and key(r) in flows_keys}
pipecat_keys = {key(r) for p, r in recs if r["source"] == "pipecat" and p not in drop}
drop |= {p for p, r in recs if r["source"] == "pipecat-flows" and key(r) in pipecat_keys}
kept_keys = {}
for p, r in recs:
    if p not in drop:
        kept_keys.setdefault(key(r), set()).add(r["source"])
left = [k for k, s in kept_keys.items() if len(s) > 1]
if left:
    sys.exit(f"cross-source duplicates with no rule: {left}")

counts, cross = {}, {}
for path, rec in recs:
    if path in drop:
        cross[rec["source"]] = cross.get(rec["source"], 0) + 1
        print(f"dropped cross-source duplicate: {os.path.relpath(path, POOL)} ({rec['file_path']})")
        continue
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    counts[rec["source"]] = counts.get(rec["source"], 0) + 1

for s in ORDER:
    notes = [f"{within[s]} duplicates dropped"] if s in within else []
    notes += [f"{cross[s]} cross-source duplicates dropped"] if s in cross else []
    print(f"{s:14} {counts.get(s, 0)}" + (f"  ({', '.join(notes)})" if notes else ""))
print(f"{'total':14} {sum(counts.values())}")
