"""Build data/tools_as_sent/ from data/tools_pool_v0/: each tool exactly as its framework puts it
in a provider request, captured from the framework's real request code at a local HTTP server
(no provider is contacted).

usage: python scripts/as_sent/build.py [--pool DIR] [--out DIR] [--work DIR]
       python scripts/as_sent/build.py --check   # rebuild into a temp dir, diff against --out

Output: <out>/<provider>/<tool_id>, provider in openai-chat, openai-responses, anthropic, gemini.
Covers the sources whose framework rewrites tools per provider: tau2-bench (litellm), pipecat,
pipecat-flows, livekit. Framework commits come from scripts/extract/sources.json, package versions
from requirements-*.txt here. Derived files: never edit them by hand, rerun this instead.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts/extract"))
from rebuild import clone, diff_trees, sh  # noqa: E402

PYTHON = "3.12"
SPARSE = {
    "pipecat": ["/src/**/*.py"],
    "livekit": ["/examples/**/*.py", "/livekit-agents/**/*.py"]
    + [f"/livekit-plugins/livekit-plugins-{p}/**/*.py" for p in ("openai", "anthropic", "google")],
}
# source -> (venv, probe script, args after the script; {pool}/{repos}/{out} are filled in)
PROBES = {
    "tau2-bench": ("litellm", "probe_litellm.py", ["{pool}/tau2-bench", "{out}"]),
    "pipecat": ("frameworks", "probe_pipecat.py", ["{pool}/pipecat", "{out}", "{repos}/pipecat/src"]),
    "pipecat-flows": ("flows", "probe_pipecat.py", ["{pool}/pipecat-flows", "{out}"]),
    "livekit": ("frameworks", "probe_livekit.py", ["{repos}/livekit", "{pool}/livekit", "{out}"]),
}


def pinned(venv, package):
    for line in open(os.path.join(HERE, f"requirements-{venv}.txt")):
        if line.lower().startswith(package + "=="):
            return line.strip().split("==")[1]
    raise KeyError(package)


def framework_label(source, sources):
    if source == "tau2-bench":
        return f"litellm {pinned('litellm', 'litellm')} (tau2-bench {sources['tau2-bench']['commit'][:7]})"
    if source == "pipecat-flows":
        return f"pipecat-ai {pinned('flows', 'pipecat-ai')} (pipecat-flows {sources['pipecat-flows']['commit'][:7]})"
    if source == "pipecat":
        return f"pipecat {sources['pipecat']['commit'][:7]}"
    return f"livekit-agents + plugins {sources['livekit']['commit'][:7]}"


def build(pool, out, work_dir):
    sources = json.load(open(os.path.join(ROOT, "scripts/extract/sources.json")))
    work = work_dir or tempfile.mkdtemp(prefix="tools_as_sent_build_")
    repos, venvs, caps = (os.path.join(work, d) for d in ("repos", "venvs", "captures"))
    for d in (repos, venvs, caps):
        os.makedirs(d, exist_ok=True)
    try:
        for name, sparse in SPARSE.items():
            if not os.path.exists(os.path.join(repos, name)):
                print(f"clone {name} @ {sources[name]['commit'][:7]}", flush=True)
                clone(name, {**sources[name], "sparse": sparse}, os.path.join(repos, name))
        for v in sorted({p[0] for p in PROBES.values()}):
            path = os.path.join(venvs, v)
            if not os.path.exists(path):
                print(f"venv {v}", flush=True)
                sh("uv", "venv", "-q", "-p", PYTHON, path)
                sh("uv", "pip", "install", "-q", "--no-deps", "-r", os.path.join(HERE, f"requirements-{v}.txt"),
                   env={**os.environ, "VIRTUAL_ENV": path})
        for source, (venv, script, args) in PROBES.items():
            print(f"capture {source}", flush=True)
            cap = os.path.join(caps, f"{source}.jsonl")
            fill = {"pool": os.path.abspath(pool), "repos": repos, "out": cap}
            # -I: don't let the cwd or env shadow modules; probes add their own dir to sys.path
            sh(os.path.join(venvs, venv, "bin", "python"), "-I", os.path.join(HERE, script),
               *[re.sub(r"\{(\w+)\}", lambda m: fill[m.group(1)], a) for a in args],
               cwd=work, stdout=open(os.path.join(caps, f"{source}.log"), "w"), stderr=-2)
        write(caps, out, sources)
    finally:
        if not work_dir:
            shutil.rmtree(work, ignore_errors=True)


def write(caps, out, sources):
    counts = {}
    for source in PROBES:
        label = framework_label(source, sources)
        for line in open(os.path.join(caps, f"{source}.jsonl"), encoding="utf-8"):
            r = json.loads(line)
            path = os.path.join(out, r["provider"], r["tool_id"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "x", encoding="utf-8") as f:
                json.dump({"tool_id": r["tool_id"], "provider": r["provider"], "framework": label,
                           "endpoint": r["endpoint"], "payload": r["payload"]}, f, indent=2, ensure_ascii=False)
                f.write("\n")
            counts[(source, r["provider"])] = counts.get((source, r["provider"]), 0) + 1
    for (source, provider), n in sorted(counts.items()):
        print(f"{source:14} {provider:17} {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=os.path.join(ROOT, "data/tools_pool_v0"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data/tools_as_sent"))
    ap.add_argument("--work", help="where clones/venvs go (default: a temp dir, deleted afterwards)")
    ap.add_argument("--check", action="store_true", help="rebuild into a temp dir and diff against --out")
    args = ap.parse_args()
    if args.check:
        tmp = tempfile.mkdtemp(prefix="tools_as_sent_check_")
        build(args.pool, os.path.join(tmp, "out"), args.work)
        bad = diff_trees(os.path.join(tmp, "out"), args.out)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"{len(bad)} differing paths" + "".join(f"\n  {p}" for p in bad))
        sys.exit(1 if bad else 0)
    if os.path.exists(args.out):
        sys.exit(f"{args.out} already exists; pass a new --out (files are never overwritten)")
    build(args.pool, args.out, args.work)


if __name__ == "__main__":
    main()
