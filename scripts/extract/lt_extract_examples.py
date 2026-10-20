"""Shared extractor for framework examples (pipecat, pipecat-flows, livekit), using each
framework's own schema generator.

Each example file is executed statement by statement (missing deps become stubs) to get its
namespace; tool objects/functions found via AST are then rebuilt in that namespace and passed to
the framework's schema code.
"""

import ast
import copy
import os
import re
import sys
import traceback
import types

from lt_extract_common import (
    call_name, emit, eval_node, exec_def, head_commit, is_openai_tool_dict, load_namespace)

SOURCE = REPO = None


def _configure(source, repo):
    """Import the framework from the clone; schema classes become module globals."""
    global SOURCE, REPO, lk_utils, FunctionTool, RawFunctionTool
    global DirectFunctionWrapper, FlowsDirectFunctionWrapper, FlowsFunctionSchema
    SOURCE, REPO = source, os.path.abspath(repo)
    sys.path.insert(0, os.path.join(REPO, {"pipecat": "src", "pipecat-flows": "src", "livekit": "livekit-agents"}[source]))
    if source == "livekit":
        from livekit.agents.llm import utils as lk_utils
        from livekit.agents.llm.tool_context import FunctionTool, RawFunctionTool
    else:
        from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper
        if source == "pipecat-flows":
            from pipecat_flows.types import FlowsDirectFunctionWrapper, FlowsFunctionSchema
        else:
            from pipecat.flows.types import FlowsDirectFunctionWrapper, FlowsFunctionSchema


LK_DECORATOR = re.compile(r"(^|\.)function_tool(\(|$)")
ENTRY_POINTS = ("agent.py", "bot.py", "main.py")


def example_name(rel):
    """File stem for single-file examples; the project dir for multi-file ones."""
    parts = rel.split("/")
    for i in range(len(parts) - 1, 1, -1):  # deepest dir under examples/ with an entry point
        d = os.path.join(REPO, *parts[:i])
        if any(os.path.exists(os.path.join(d, e)) for e in ENTRY_POINTS):
            return parts[i - 1]
    stem = parts[-1][:-3]
    return parts[-2] if stem == "__init__" else stem


def bind_if_method(fn, node):
    args = node.args.args
    if args and args[0].arg in ("self", "cls"):
        return types.MethodType(fn, object()) if not hasattr(fn, "__get__") else fn.__get__(object())
    return fn


def first_real_arg(node):
    args = [a for a in node.args.args if a.arg not in ("self", "cls")]
    return args[0] if args else None


def referenced_tool_names(tree):
    """Names appearing inside tools=[...] / standard_tools=[...] lists or LLMSetToolsFrame."""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.keyword) and n.arg in ("tools", "standard_tools", "functions") \
                and isinstance(n.value, (ast.List, ast.Tuple)):
            names |= {e.id for e in n.value.elts if isinstance(e, ast.Name)}
            names |= {e.attr for e in n.value.elts if isinstance(e, ast.Attribute)}
    return names


def from_pipecat_like(node, ns, path, refs):
    """Return (definition dict, kind) if node defines a pipecat / pipecat-flows tool."""
    if isinstance(node, ast.Call) and call_name(node) in ("FunctionSchema", "FlowsFunctionSchema"):
        # only these args feed the LLM-facing schema; handlers etc. may not be resolvable
        node = copy.deepcopy(node)
        for k in node.keywords:
            if k.arg not in ("name", "description", "properties", "required"):
                k.value = ast.Constant(None)
        obj = eval_node(node, ns)
        if isinstance(obj, FlowsFunctionSchema):
            obj = obj.to_function_schema()
        return obj.to_default_dict(), call_name(node)
    if is_openai_tool_dict(node):
        d = eval_node(node, ns)["function"]
        return {k: d.get(k) for k in ("name", "description", "parameters")}, "dict"
    if isinstance(node, ast.AsyncFunctionDef):  # direct functions must be async
        a = first_real_arg(node)
        if a is None or a.annotation is None:
            return None
        ann = ast.unparse(a.annotation)
        if a.arg == "params" and ann.endswith("FunctionCallParams"):
            # handlers registered for a FunctionSchema have no docstring and no extra args
            if not ast.get_docstring(node) and node.name not in refs and len(node.args.args) == 1:
                return None
            wrapper = DirectFunctionWrapper
        elif a.arg == "flow_manager" and ann.endswith("FlowManager"):
            if not ast.get_docstring(node) and node.name not in refs:
                return None
            wrapper = FlowsDirectFunctionWrapper
        else:
            return None
        fn = bind_if_method(exec_def(node, ns, path, keep_decorators=False), node)
        return wrapper(fn).to_function_schema().to_default_dict(), "direct"
    return None


def from_livekit(node, ns, path, refs):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    if not any(LK_DECORATOR.search(ast.unparse(d)) for d in node.decorator_list):
        return None
    ns.setdefault("function_tool", __import__("livekit.agents", fromlist=["x"]).function_tool)
    tool = bind_if_method(exec_def(node, ns, path, keep_decorators=True), node)
    if isinstance(tool, RawFunctionTool):
        raw = tool.info.raw_schema
        return {"name": raw["name"], "description": raw.get("description"),
                "parameters": raw.get("parameters")}, "raw_schema"
    if isinstance(tool, FunctionTool):
        return lk_utils.build_legacy_openai_schema(tool)["function"], "function_tool"
    raise TypeError(f"decorator produced {type(tool)}")


def candidate_files():
    pat = {"livekit": "function_tool", "pipecat": None, "pipecat-flows": None}[SOURCE]
    for root, _, files in os.walk(os.path.join(REPO, "examples")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            txt = open(p, encoding="utf-8").read()
            if pat and pat not in txt:
                continue
            if not pat and not re.search(r"FunctionSchema\(|FunctionCallParams|FlowManager|[\"']type[\"']\s*:\s*[\"']function", txt):
                continue
            yield p


def run(source, repo, out_path):
    _configure(source, repo)
    commit = head_commit(REPO)
    extract = from_livekit if SOURCE == "livekit" else from_pipecat_like
    failures = []
    with open(out_path, "w") as out:
        for path in sorted(candidate_files()):
            rel = os.path.relpath(path, REPO)
            try:
                tree, ns = load_namespace(path)
            except Exception:
                failures.append((rel, "load", traceback.format_exc(limit=1)))
                continue
            refs = referenced_tool_names(tree)
            for node in ast.walk(tree):
                try:
                    r = extract(node, ns, path, refs)
                except Exception as e:
                    name = getattr(node, "name", None) or ast.unparse(node)[:60]
                    failures.append((rel, name, f"{type(e).__name__}: {e}"[:300]))
                    continue
                if r is None:
                    continue
                d, kind = r
                emit(out, source=SOURCE, commit=commit, file_path=rel, domain=example_name(rel),
                     name=d["name"], description=d.get("description"), parameters=d.get("parameters"))
    for f in failures:
        print("FAIL", *f, sep="\t", file=sys.stderr)
