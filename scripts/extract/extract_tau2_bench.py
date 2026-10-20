"""τ²-bench: ToolKitBase.get_tools() wraps each @is_tool method with as_tool(); Tool.openai_schema
is the schema the agent sends. Skips the mock domain and discoverable tools (never in `tools`).

usage: extract_tau2_bench.py <repo_dir> <out_jsonl>
"""

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_common import emit, head_commit, import_with_autostub, stub_modules  # noqa: E402

REPO, OUT = os.path.abspath(sys.argv[1]), sys.argv[2]
sys.path.insert(0, os.path.join(REPO, "src"))
stub_modules("litellm")  # imported by tau2/__init__ for running agents, not needed for schemas

from tau2.environment.toolkit import DISCOVERABLE_ATTR, ToolKitBase  # noqa: E402

domains_dir = os.path.join(REPO, "src/tau2/domains")
with open(OUT, "w") as out:
    for domain in sorted(os.listdir(domains_dir)):
        if domain == "mock" or not os.path.exists(os.path.join(domains_dir, domain, "tools.py")):
            continue
        mod = import_with_autostub(f"tau2.domains.{domain}.tools")
        kits = [c for c in vars(mod).values()
                if inspect.isclass(c) and issubclass(c, ToolKitBase) and c.__module__ == mod.__name__]
        for cls in kits:
            # schemas don't depend on the DB; default (non-regional) settings
            inst = cls.__new__(cls)
            inst.db = None
            inst.regional_settings = None
            n_disc = sum(1 for t in inst.tools.values() if getattr(t, DISCOVERABLE_ATTR, False))
            if n_disc:
                print(f"NOTE: {domain}.{cls.__name__}: skipped {n_disc} discoverable tools", file=sys.stderr)
            for name, tool in cls.get_tools(inst).items():
                fn = tool.openai_schema["function"]
                src = inspect.getsourcefile(inst._func_tools[name])
                emit(out, source="tau2-bench", commit=head_commit(REPO), file_path=os.path.relpath(src, REPO),
                     domain=domain, name=fn["name"], description=fn["description"],
                     parameters=fn["parameters"])
