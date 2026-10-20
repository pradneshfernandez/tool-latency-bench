"""Pipecat examples: FunctionSchema(...) objects, direct functions (first param
`params: FunctionCallParams`, schema from signature + docstring via DirectFunctionWrapper), the
bundled pipecat.flows examples, and OpenAI-style tool dicts.

usage: extract_pipecat.py <repo_dir> <out_jsonl>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_examples import run  # noqa: E402

run("pipecat", sys.argv[1], sys.argv[2])
