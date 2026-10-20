"""aiewf-eval: the benchmark tools are pipecat FunctionSchema objects in benchmarks/_shared/tools.py.

usage: extract_aiewf_eval.py <repo_dir> <out_jsonl> <pipecat_src_dir>
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lt_extract_common import emit, head_commit, import_with_autostub  # noqa: E402

REPO, OUT, PIPECAT_SRC = os.path.abspath(sys.argv[1]), sys.argv[2], os.path.abspath(sys.argv[3])
sys.path[:0] = [REPO, PIPECAT_SRC]

from pipecat.adapters.schemas.function_schema import FunctionSchema  # noqa: E402

mod = import_with_autostub("benchmarks._shared.tools")
with open(OUT, "w") as out:
    for obj in vars(mod).values():
        if isinstance(obj, FunctionSchema):
            d = obj.to_default_dict()
            emit(out, source="aiewf-eval", commit=head_commit(REPO), file_path=os.path.relpath(mod.__file__, REPO),
                 domain="_shared", name=d["name"], description=d["description"], parameters=d["parameters"])
