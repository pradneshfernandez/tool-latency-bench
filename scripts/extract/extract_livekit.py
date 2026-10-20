"""LiveKit Agents examples: @function_tool functions and methods; schema via
llm.utils.build_legacy_openai_schema, raw_schema tools as declared.

usage: extract_livekit.py <repo_dir> <out_jsonl>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_examples import run  # noqa: E402

run("livekit", sys.argv[1], sys.argv[2])
