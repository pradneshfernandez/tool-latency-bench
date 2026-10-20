"""Pipecat Flows examples: FlowsFunctionSchema(...) objects, direct flow functions (first param
`flow_manager: FlowManager`, via FlowsDirectFunctionWrapper), and OpenAI-style tool dicts.

usage: extract_pipecat_flows.py <repo_dir> <out_jsonl>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_examples import run  # noqa: E402

run("pipecat-flows", sys.argv[1], sys.argv[2])
