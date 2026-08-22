"""Every module must be parseable by the oldest Python this pack claims to support.

This matters more here than in most packs: the pack runs on whatever Python the user's ComfyUI was
built with, which is frequently older than the one it was written on, and a pack that will not parse
is a pack ComfyUI drops off the menu with a traceback nobody can act on.

`pyproject.toml` declares `requires-python = ">=3.10"`. In the compiler that promise was once false:
a backslash inside an f-string expression is a SyntaxError before 3.12 (PEP 701 relaxed it), so one
module could not be imported on 3.10 or 3.11 at all, and collection died before a single test ran.

Nothing local could see it. A 3.12 interpreter parses the construct happily, and two attempts to
detect it from a 3.12 process were both worthless: a grep whose escaping was wrong found nothing,
and `compile(..., _feature_version=10)` also found nothing, because that flag does not gate the
f-string tokenizer rules. Only a real 3.10 run, or an AST walk that inspects the source segment of
every format expression, actually detects it.

So this test does the AST walk. It cannot prove a module runs on 3.10, only that it parses under the
rules that changed, which is the class that bit us. Running the suite under a real 3.10 is the
stronger check and belongs in CI, not here.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent


def _min_version() -> tuple[int, int]:
    """Read requires-python without a TOML parser.

    `tomllib` is 3.11+, so using it here made this very test unimportable on 3.10, the version it
    exists to protect. Fourth instance in this project of an instrument carrying the defect it was
    written to detect, so: one regex, no imports beyond the standard library of the oldest version
    supported.
    """
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*requires-python\s*=\s*["\']([^"\']+)["\']', text, re.M)
    assert m, "requires-python not found in pyproject.toml"
    v = re.search(r"(\d+)\.(\d+)", m.group(1))
    assert v, f"could not read a version out of {m.group(1)!r}"
    return int(v.group(1)), int(v.group(2))


def _python_files() -> list[pathlib.Path]:
    """Every module in the pack, plus the ones beside it.

    The pack's own modules sit at the repository root, because the root is what ComfyUI imports.
    A `rglob` from there would walk `.venv` and every installed package with it, so the root is
    globbed one level deep and the subdirectory that holds the rest of the Python is named.
    """
    out = [p for p in REPO.glob("*.py")]
    out += [p for p in (REPO / "tests").rglob("*.py")]
    return sorted(out)


def test_no_backslash_inside_an_f_string_expression():
    """Legal from 3.12, a SyntaxError before it. The one construct that made this package
    unimportable on the versions it advertises."""
    if _min_version() >= (3, 12):
        import pytest
        pytest.skip("package no longer claims a version where this is a SyntaxError")

    offenders = []
    for f in _python_files():
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    seg = ast.get_source_segment(src, part.value) or ""
                    if "\\" in seg:
                        offenders.append(
                            f"{f.relative_to(REPO)}:{part.value.lineno}  {seg[:60]}")

    assert not offenders, (
        "a backslash inside an f-string expression is a SyntaxError before Python 3.12, and this "
        f"package declares {'.'.join(map(str, _min_version()))}+. Bind the value to a name on the "
        "line above and interpolate the name:\n  " + "\n  ".join(offenders))


def test_every_module_parses():
    """A cheap guard that nothing in the pack is syntactically broken at all."""
    broken = []
    for f in _python_files():
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            broken.append(f"{f.relative_to(REPO)}:{e.lineno}  {e.msg}")
    assert not broken, "modules that do not parse:\n  " + "\n  ".join(broken)
