"""EVA: tools are declared in configs/agents/<domain>_agent.yaml; AgentConfig.build_tools_for_agent()
turns them into OpenAI format.

usage: extract_eva.py <repo_dir> <out_jsonl>
"""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_common import emit, head_commit  # noqa: E402

REPO, OUT = os.path.abspath(sys.argv[1]), sys.argv[2]

# load the module by path: the eva package __init__ pulls in heavy runtime deps
spec = importlib.util.spec_from_file_location("eva_agents", os.path.join(REPO, "src/eva/models/agents.py"))
agents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agents)

with open(OUT, "w") as out:
    for domain in ("airline", "itsm", "medical_hr"):
        path = os.path.join(REPO, f"configs/agents/{domain}_agent.yaml")
        for t in agents.AgentConfig.from_yaml(path).build_tools_for_agent():
            fn = t["function"]
            emit(out, source="eva", commit=head_commit(REPO), file_path=os.path.relpath(path, REPO), domain=domain,
                 name=fn["name"], description=fn["description"], parameters=fn["parameters"])
