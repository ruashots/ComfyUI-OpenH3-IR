"""The repository IS the ComfyUI node pack, and its root is the pack's root.

ComfyUI Manager's git-clone install drops the entire repository into `custom_nodes` and imports its
top level, exactly the way `spec_from_file_location` on an `__init__.py` does. So whatever is at the
root of this repository is what a stranger's ComfyUI loads, and a pack one directory deeper produces
zero nodes and no error anyone can act on. Measured 2026-08-15, in the repository this pack was split
out of, where the pack lived in a subfolder and the clone found nothing at the top.

Manager also pip-installs a cloned pack's `requirements.txt` on every install, which is the other
half of what a stranger gets. Both halves get a control here.
"""
from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Every module ComfyUI has to find at the top level for this pack to be a pack.
PACK_MODULES = ("contract.py", "h3ir_client.py", "media.py", "nodes.py", "tray.py", "web_api.py")


def _load_repo_root_as_comfyui_does():
    """ComfyUI's loader in miniature: the directory's __init__.py becomes a package.

    Loaded under its own name rather than reusing the one `conftest.py` registered, so this is a
    fresh execution of the file ComfyUI executes rather than a reading of an already-imported
    module. `submodule_search_locations` is what makes the relative imports inside it resolve, and
    it is what ComfyUI's own loader passes.
    """
    spec = importlib.util.spec_from_file_location(
        "openh3ir_clone_test", REPO / "__init__.py", submodule_search_locations=[str(REPO)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        # the module stays importable for the duration of the test that asked for it, but the
        # fake clone must not leak into the rest of the suite
        sys.modules.pop(spec.name, None)
    return module


def test_the_repo_root_presents_the_pack_contract():
    module = _load_repo_root_as_comfyui_does()
    assert asyncio.iscoroutinefunction(module.comfy_entrypoint)
    web = REPO / module.WEB_DIRECTORY
    assert web.is_dir(), f"WEB_DIRECTORY points at nothing: {module.WEB_DIRECTORY}"
    assert list(web.glob("*.js")), "the served web folder has no frontend code in it"


def test_the_pack_itself_is_at_the_top_and_not_one_folder_down():
    """The failure the repository this was split out of actually had.

    A pack whose modules sit in a subdirectory still passes the check above, because a one-line
    bridge at the root can re-export `comfy_entrypoint` from anywhere. What it cannot do is survive
    a user renaming the cloned folder, a Manager update, or a second entry point; and the version
    of this repository that needed a bridge is exactly the one this test exists to stop coming back.
    """
    missing = [name for name in PACK_MODULES if not (REPO / name).is_file()]
    assert not missing, (
        f"{missing} are not at the repository root, so ComfyUI is loading a bridge rather than the "
        "pack. Manager clones this repository into custom_nodes; the root is the pack.")


# One requirement, written once. The number in it is a literal a person chose, and everything else
# that names a compiler release is held against it: `pyproject.toml` below, and
# `contract.FIRST_PUBLISHING_RELEASE` in tests/test_contract_drift.py.
REQUIREMENT = re.compile(r"^open-h3-ir>=(\d+\.\d+\.\d+)$")


def requirement_lines() -> list[str]:
    lines = (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def test_requirements_txt_installs_the_compiler_and_nothing_else():
    """Manager runs `pip install -r requirements.txt` on every install of the cloned pack, so this
    file is what a stranger's ComfyUI Python gets.

    Exactly one requirement, and it is the compiler at or above a stated release. Two things are
    being kept out at once. A second package here is a package this pack forces into somebody
    else's ComfyUI for a graph that may never use it, and the reason `open-h3-ir` is worth that cost
    is that the alternative is carrying a copy of the compiler in this repository. And `-e .`, or
    anything naming this repository, would install the pack's own dev extras -- pytest included --
    into a ComfyUI. An earlier version of this file said `-e .[dev]` and would have done exactly
    that.
    """
    lines = requirement_lines()
    assert len(lines) == 1, (
        f"requirements.txt installs {lines} into every user's ComfyUI. It takes one line, and it "
        "is the compiler.")
    assert REQUIREMENT.match(lines[0]), (
        f"{lines[0]!r} is not `open-h3-ir>=<release>`. The floor has to be a release somebody can "
        "be told to install, because that is what the pack's own mismatch message names.")


def test_the_two_places_the_compiler_is_required_say_the_same_thing():
    """`requirements.txt` is what Manager installs and `pyproject.toml` is what the ComfyUI Registry
    reads. Two statements of one requirement drift, and the half that drifts is invisible: whichever
    install path a user took is the only one they can see."""
    wanted = requirement_lines()[0]
    declared = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert f'"{wanted}"' in declared, (
        f"requirements.txt asks for {wanted} and pyproject.toml does not, so a Manager install and "
        "a Registry install would take different versions of the compiler.")


def test_the_shipped_workflow_is_the_graph_the_readme_describes():
    """The example is the front door: it is what "open it and run" means, and nothing else in the
    suite reads it. Three things about it are claims the docs make out loud.

    The scheduler is the one that has already gone wrong once. This chain was copied from
    Comfy-Org's reference-to-video template, whose own note says beta or normal outperform simple
    on reference-heavy prompts; the widget value came across and the note did not. Re-exporting the
    graph from a canvas that has drifted back to `simple` is a silent way to lose it again.
    """
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    graph = json.loads((root / "example" / "openh3ir_base_workflow.json")
                       .read_text(encoding="utf-8"))
    nodes = [n for sg in graph["definitions"]["subgraphs"] for n in sg["nodes"]]
    kinds = {n["type"] for n in graph["nodes"]}
    assert {"OpenH3IRSetup", "OpenH3IRMedia", "OpenH3IRCompile"} <= kinds, sorted(kinds)

    scheduler = [n for n in nodes if n["type"] == "BasicScheduler"]
    assert len(scheduler) == 1, "one scheduler, or this check no longer knows which one it reads"
    assert scheduler[0]["widgets_values"][0] == "beta", (
        f"the shipped graph schedules on {scheduler[0]['widgets_values'][0]!r} and README.md "
        "says beta, which the template it came from recommends for reference-heavy prompts")
    assert "beta" in (root / "README.md").read_text(encoding="utf-8")

    # No turbo, in the graph or in any of its titles: ruled out on 2026-08-20 and stripped.
    assert "turbo" not in json.dumps(graph).lower()


def test_no_message_this_pack_shows_a_person_uses_a_dash_as_punctuation():
    """A dash standing in for a full stop is the house tell, and these strings are read by users.

    Four of them carried one until 2026-08-22, all in the same family of message: "update it -- git
    pull, then restart". A reader hits that dash and has to work out whether the second half is an
    aside, a correction or the actual instruction. A colon or a full stop says which.

    Docstrings and comments are exempt, because nobody outside this repository reads them. This
    walks the module strings instead, which is every sentence the pack can put on a canvas or in a
    ComfyUI log. The panel's own text has its own rule in `test_director_panel.py`; this one covers
    the Python side.
    """
    import ast
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                text = ast.get_docstring(node, clean=False)
                if text:
                    docs.add(text)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if node.value in docs:
                continue
            # An em dash anywhere, or a double hyphen with space on both sides. `--flag` and
            # `well-known` are not punctuation and are left alone.
            if re.search(r"—|\s--\s", node.value):
                offenders.append(f"{path.name}:{node.lineno} {node.value.strip()[:90]}")

    assert not offenders, (
        "a dash is standing in for punctuation in text a person reads. Use a colon or a full stop:\n"
        + "\n".join(offenders))


# ------------------------------------------------- every board refuses the width the host writes

BOARDS = (
    ("web/main.js", "Main"),
    ("web/tray.js", "Media"),
    ("web/setup.js", "Setup"),
    ("web/director.js", "Director"),
)


def test_every_board_refuses_the_width_the_host_writes_onto_it():
    """A board fills the node it is in, so it has no width of its own to be told.

    The frontend writes a `width` onto every widget from a node layout pass, and for a full-bleed
    board that number is the content width rather than the box. Nothing reads it while the board is
    a live element, so nothing looks wrong. Zoom out far enough that the element is hidden, and the
    canvas draws the board from that number instead: painted past the right edge of the node, over
    empty canvas, taking the mouse where it lands.

    MEASURED from the owner's screenshot: node body 497 pixels wide, board 660. Reproduced by
    writing 900 onto the widget by hand and photographing the result.

    Three of the four boards already refused the write. The Media board was the one that did not,
    which is the node the owner reported. The rule is one rule, so it is checked for all four here
    rather than left to whoever writes the fifth.
    """
    for rel, name in BOARDS:
        js = (REPO / rel).read_text(encoding="utf-8")
        assert 'Object.defineProperty(' in js and '"width", { get: () => null, set: () => {}' in js, (
            f"the {name} board takes the width the host writes onto it. Refuse it the way the "
            f"other boards do, or it is drawn at that width when the canvas draws it.")
