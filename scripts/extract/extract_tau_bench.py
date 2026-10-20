"""τ-bench: each tool class's get_info() returns its OpenAI-format schema; ALL_TOOLS lists them.

usage: extract_tau_bench.py <repo_dir> <out_jsonl>
"""

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_common import emit, head_commit, import_with_autostub, stub_modules  # noqa: E402

REPO, OUT = os.path.abspath(sys.argv[1]), sys.argv[2]
sys.path.insert(0, REPO)
stub_modules("litellm")  # imported at package level, not needed for schemas

with open(OUT, "w") as out:
    for domain in ("retail", "airline"):
        mod = import_with_autostub(f"tau_bench.envs.{domain}.tools")
        for cls in mod.ALL_TOOLS:
            fn = cls.get_info()["function"]
            emit(out, source="tau-bench", commit=head_commit(REPO),
                 file_path=os.path.relpath(inspect.getfile(cls), REPO), domain=domain,
                 name=fn["name"], description=fn.get("description"), parameters=fn.get("parameters"))
