"""Shared helpers for the extractors: stubs for missing deps, per-statement module loading.

Named lt_extract_common (not common) so it can't shadow example modules called common.py.
"""

import ast
import copy
import importlib.abc
import importlib.machinery
import json
import os
import signal
import subprocess
import sys
import textwrap
import types


class _StubMeta(type):
    def __getattr__(cls, n):
        if n.startswith("__") and n.endswith("__"):
            raise AttributeError(n)
        return Stub

    def __call__(cls, *a, **k):
        return Stub

    def __getitem__(cls, k):
        return Stub

    def __or__(cls, o):
        return Stub

    def __ror__(cls, o):
        return Stub

    def __iter__(cls):
        return iter(())


class Stub(metaclass=_StubMeta):
    pass


class StubModule(types.ModuleType):
    __path__ = []

    def __getattr__(self, n):
        if n.startswith("__") and n.endswith("__"):
            raise AttributeError(n)
        return Stub


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, roots):
        self.roots = set(roots)

    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in self.roots:
            return importlib.machinery.ModuleSpec(name, self, is_package=True)
        return None

    def create_module(self, spec):
        return StubModule(spec.name)

    def exec_module(self, module):
        pass


def stub_modules(*roots):
    sys.meta_path.insert(0, _StubFinder(roots))


def import_with_autostub(modname, max_tries=30):
    """Import modname, stubbing any top-level package that is missing."""
    finder = _StubFinder([])
    sys.meta_path.insert(0, finder)
    for _ in range(max_tries):
        try:
            return importlib.import_module(modname)
        except ModuleNotFoundError as e:
            root = (e.name or "").split(".")[0]
            if not root or root in finder.roots:
                raise
            finder.roots.add(root)
            for k in [k for k in sys.modules if k == modname or k.startswith(modname.split(".")[0] + ".")]:
                del sys.modules[k]
    raise ImportError(modname)


_AUTO = _StubFinder([])
sys.meta_path.append(_AUTO)  # last, so real modules always win


def _is_main_guard(stmt):
    return isinstance(stmt, ast.If) and "__name__" in ast.unparse(stmt.test)


class _Timeout(Exception):
    pass


def _alarm(*_):
    raise _Timeout()


def load_namespace(path, timeout=20):
    """Execute a file statement by statement, skipping failures and the main guard.

    Failed imports bind their names to Stub so later statements still run.
    """
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    # files inside a package run as a submodule of it, so relative imports resolve
    pkg_dir, pkg = os.path.dirname(path), []
    while os.path.exists(os.path.join(pkg_dir, "__init__.py")):
        pkg.insert(0, os.path.basename(pkg_dir))
        pkg_dir = os.path.dirname(pkg_dir)
    stem = os.path.basename(path)[:-3]
    modname = ".".join(pkg + ([] if stem == "__init__" else [stem])) if pkg else "ex_" + stem
    ns = {"__name__": modname, "__file__": path, "__builtins__": __builtins__,
          "__package__": ".".join(pkg) if pkg else None}
    sys.path[:0] = [os.path.dirname(path), pkg_dir]
    before = set(sys.modules)
    signal.signal(signal.SIGALRM, _alarm)
    try:
        for stmt in tree.body:
            if _is_main_guard(stmt):
                continue
            signal.alarm(timeout)
            try:
                for _ in range(15):
                    try:
                        exec(compile(ast.Module([stmt], []), path, "exec"), ns)
                        break
                    except ModuleNotFoundError as e:
                        # stub just the missing third-party package, then retry the import
                        root = (e.name or "").split(".")[0]
                        if not isinstance(stmt, (ast.Import, ast.ImportFrom)) or not root \
                                or root in _AUTO.roots or os.path.exists(os.path.join(os.path.dirname(path), root + ".py")):
                            raise
                        _AUTO.roots.add(root)
                        for k in set(sys.modules) - before:
                            if "/examples/" in (getattr(sys.modules[k], "__file__", None) or ""):
                                del sys.modules[k]
                else:
                    raise ImportError("too many missing modules")
            except BaseException:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    for a in stmt.names:
                        ns[(a.asname or a.name).split(".")[0]] = Stub
            finally:
                signal.alarm(0)
    finally:
        del sys.path[:2]
        # forget sibling example modules so same-named files in other examples load fresh
        for k in set(sys.modules) - before:
            f = getattr(sys.modules[k], "__file__", None) or ""
            if "/examples/" in f:
                del sys.modules[k]
    return tree, ns


def exec_def(node, ns, path, keep_decorators):
    """Re-execute a (possibly nested) function def in a copy of the module namespace."""
    node = copy.deepcopy(node)
    if not keep_decorators:
        node.decorator_list = []
    code = textwrap.dedent(ast.unparse(node))
    local = dict(ns)
    exec(compile(code, path, "exec"), local)
    return local[node.name]


def eval_node(node, ns):
    return eval(ast.unparse(node), dict(ns))


def call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def is_openai_tool_dict(node):
    if not isinstance(node, ast.Dict):
        return False
    keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
    return isinstance(keys.get("type"), ast.Constant) and keys["type"].value == "function" and "function" in keys


def head_commit(repo):
    """7-char commit id, independent of how many objects the clone has."""
    return subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()[:7]


def emit(out, **rec):
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
