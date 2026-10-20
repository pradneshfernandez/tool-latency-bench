"""Summarize how each framework x provider route changes the pool definitions when sending them.

usage: python scripts/as_sent/report.py [pool_dir] [as_sent_dir]
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data/tools_pool_v0")
SENT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data/tools_as_sent")


def sent_parts(t):
    """(name, description, parameters, extra top-level keys) from one sent tool payload."""
    if "function_declarations" in t or "functionDeclarations" in t:
        f = (t.get("function_declarations") or t.get("functionDeclarations"))[0]
        params = f.get("parameters") or f.get("parametersJsonSchema") or f.get("parameters_json_schema")
        extra = sorted(k for k in f if k not in ("name", "description"))
        return f["name"], f.get("description"), params, extra
    if "function" in t:  # chat completions
        f = t["function"]
        return f["name"], f.get("description"), f.get("parameters"), sorted(k for k in f if k not in ("name", "description", "parameters"))
    if "input_schema" in t:  # anthropic
        return t["name"], t.get("description"), t["input_schema"], sorted(k for k in t if k not in ("name", "description", "input_schema"))
    # responses
    return t["name"], t.get("description"), t.get("parameters"), sorted(k for k in t if k not in ("name", "description", "parameters", "type"))


def count_keys(x, key):
    n = 0
    if isinstance(x, dict):
        for k, v in x.items():
            if k == key:
                n += 1
            if k == "properties" and isinstance(v, dict):
                n += sum(count_keys(vv, key) for vv in v.values())
            else:
                n += count_keys(v, key)
    elif isinstance(x, list):
        n += sum(count_keys(i, key) for i in x)
    return n


def diff(a, b, path, out):
    """Record differences between pool schema a and sent schema b as category strings."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() - b.keys():
            out.add(f"removed '{k}'")
        for k in b.keys() - a.keys():
            v = b[k]
            out.add(f"added '{k}'" + (f"={json.dumps(v)}" if not isinstance(v, (dict, list)) else ""))
        for k in a.keys() & b.keys():
            if k == "properties" and isinstance(a[k], dict) and isinstance(b[k], dict):
                if list(a[k]) != list(b[k]) and set(a[k]) == set(b[k]):
                    out.add("reordered properties")
                for p in a[k].keys() & b[k].keys():
                    diff(a[k][p], b[k][p], path + [p], out)
            elif k == "type" and a[k] != b[k]:
                if isinstance(a[k], str) and isinstance(b[k], str) and a[k].upper() == b[k]:
                    out.add("type uppercased")
                else:
                    out.add(f"type {json.dumps(a[k])} -> {json.dumps(b[k])}")
            elif k == "required" and a[k] != b[k]:
                out.add("required changed (all properties required)" if b[k] and set(b[k]) >= set(a[k]) else "required changed")
            else:
                diff(a[k], b[k], path + [k], out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.add(f"list length changed at {path[-1] if path else ''}")
        for x, y in zip(a, b):
            diff(x, y, path, out)
    elif a != b:
        out.add(f"value changed at '{path[-1] if path else ''}'")


groups = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(SENT, "*/**/*.json"), recursive=True)):
    d = json.load(open(f))
    groups[(d["tool_id"].split("/")[0], d["provider"])].append(d)

rows = []
for (source, prov), sent in sorted(groups.items()):
    stats, cats, extras = collections.Counter(), collections.Counter(), collections.Counter()
    chars_pool = chars_sent = 0
    for c in sent:
        t = json.load(open(os.path.join(POOL, c["tool_id"])))
        name, desc, params, extra = sent_parts(c["payload"])
        stats["n"] += 1
        stats["identical"] += params == t["parameters"] and desc == t["description"] and name == t["name"]
        stats["desc_changed"] += desc != t["description"]
        for k in ("title", "$ref", "$defs"):
            stats[f"pool_{k}"] += count_keys(t["parameters"], k)
            stats[f"sent_{k}"] += count_keys(params, k)
        extras.update(extra)
        d = set()
        diff(t["parameters"], params, [], d)
        cats.update(d)
        chars_pool += len(json.dumps({"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}},
                                     separators=(",", ":"), ensure_ascii=False))
        chars_sent += len(json.dumps(c["payload"], separators=(",", ":"), ensure_ascii=False))
    rows.append((source, prov, sent[0]["endpoint"], stats, cats, extras, chars_pool, chars_sent))

for source, prov, path, s, cats, extras, cp, cs in rows:
    print(f"\n## {source} x {prov}   (POST {path})")
    print(f"  tools {s['n']}, parameters+description identical to pool: {s['identical']}, description changed: {s['desc_changed']}")
    print(f"  title: pool {s['pool_title']} -> sent {s['sent_title']};  $defs: {s['pool_$defs']} -> {s['sent_$defs']};  $ref: {s['pool_$ref']} -> {s['sent_$ref']}")
    print(f"  extra top-level tool keys: {dict(extras)}")
    print(f"  compact chars: pool(OpenAI format) {cp} vs sent payload {cs} ({(cs - cp) / cp:+.1%})")
    for k, v in cats.most_common():
        print(f"    {v:4} tools: {k}")
