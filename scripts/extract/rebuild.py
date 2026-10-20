"""Rebuild data/tools_pool_v0/ from fresh clones at the commits in sources.json.

usage: python scripts/extract/rebuild.py [--out DIR] [--work DIR]
       python scripts/extract/rebuild.py --check   # rebuild into a temp dir, diff against the pool

Steps: sparse, blob-less clone of each source at its pinned commit (only the Python files the
extractors need); two uv venvs from the frozen requirements (pipecat-flows needs pipecat-ai 1.4.x,
the rest use pipecat/livekit source from the clones); run each extractor; write the pool.
Requires git and uv. The output dir must not exist yet: files are never overwritten.
"""

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PYTHON = "3.12"

# source -> (script, extra args after <repo_dir> <out_jsonl>)
EXTRACTORS = {
    "tau-bench": ("extract_tau_bench.py", []),
    "tau2-bench": ("extract_tau2_bench.py", []),
    "aiewf-eval": ("extract_aiewf_eval.py", ["{repos}/pipecat/src"]),
    "eva": ("extract_eva.py", []),
    "pipecat": ("extract_pipecat.py", []),
    "pipecat-flows": ("extract_pipecat_flows.py", []),
    "livekit": ("extract_livekit.py", []),
}


def sh(*cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def clone(name, spec, dest):
    sh("git", "init", "-q", dest)
    sh("git", "-C", dest, "remote", "add", "origin", spec["repo"])
    sh("git", "-C", dest, "sparse-checkout", "set", "--no-cone", *spec["sparse"])
    sh("git", "-C", dest, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", spec["commit"])
    sh("git", "-C", dest, "checkout", "-q", "FETCH_HEAD")


def make_venv(name, path):
    sh("uv", "venv", "-q", "-p", PYTHON, path)
    sh("uv", "pip", "install", "-q", "--no-deps", "-r", os.path.join(HERE, f"requirements-{name}.txt"),
       env={**os.environ, "VIRTUAL_ENV": path})


def diff_trees(a, b, rel=""):
    """Paths that differ between two directory trees (missing on either side or different bytes)."""
    c = filecmp.dircmp(a, b)
    out = [os.path.join(rel, n) for n in c.left_only + c.right_only + c.funny_files]
    _, mismatch, errors = filecmp.cmpfiles(a, b, c.common_files, shallow=False)
    out += [os.path.join(rel, n) for n in mismatch + errors]
    for d in c.common_dirs:
        out += diff_trees(os.path.join(a, d), os.path.join(b, d), os.path.join(rel, d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "data/tools_pool_v0"))
    ap.add_argument("--work", help="where clones/venvs go (default: a temp dir, deleted afterwards)")
    ap.add_argument("--check", action="store_true", help="rebuild into a temp dir and diff against --out")
    args = ap.parse_args()
    if args.check:
        tmp = tempfile.mkdtemp(prefix="tools_pool_check_")
        build(os.path.join(tmp, "pool"), args.work)
        bad = diff_trees(os.path.join(tmp, "pool"), args.out)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"{len(bad)} differing paths" + "".join(f"\n  {p}" for p in bad))
        sys.exit(1 if bad else 0)
    if os.path.exists(args.out):
        sys.exit(f"{args.out} already exists; pass a new --out (files are never overwritten)")
    build(args.out, args.work)


def build(out, work_dir):
    sources = json.load(open(os.path.join(HERE, "sources.json")))
    work = work_dir or tempfile.mkdtemp(prefix="tools_pool_build_")
    repos, venvs, jsonl = (os.path.join(work, d) for d in ("repos", "venvs", "jsonl"))
    for d in (repos, venvs, jsonl):
        os.makedirs(d, exist_ok=True)
    try:
        for name, spec in sources.items():
            if not os.path.exists(os.path.join(repos, name)):
                print(f"clone {name} @ {spec['commit'][:7]}", flush=True)
                clone(name, spec, os.path.join(repos, name))
        for v in sorted({s["venv"] for s in sources.values()}):
            if not os.path.exists(os.path.join(venvs, v)):
                print(f"venv {v}", flush=True)
                make_venv(v, os.path.join(venvs, v))
        for name, (script, extra) in EXTRACTORS.items():
            print(f"extract {name}", flush=True)
            py = os.path.join(venvs, sources[name]["venv"], "bin", "python")
            # -I: don't let the cwd or env shadow modules; scripts add their own dir to sys.path
            sh(py, "-I", os.path.join(HERE, script), os.path.join(repos, name),
               os.path.join(jsonl, f"{name}.jsonl"), *[e.format(repos=repos) for e in extra], cwd=work)
        sh(sys.executable, os.path.join(HERE, "write_pool.py"), jsonl, out)
    finally:
        if not work_dir:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
