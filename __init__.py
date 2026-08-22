"""OpenH3-IR nodes for ComfyUI.

This repository is the whole node pack, and its root is the pack's root. ComfyUI Manager clones a
repository straight into `custom_nodes`, so what lands there is this directory, and this file is what
ComfyUI imports. Installation and wiring are in README.md beside it.

Nothing here imports the `h3ir` package while ComfyUI is loading the pack. The nodes speak to a
running OpenH3-IR service over HTTP, and the service is free to live on another machine: the media
goes to it as a filesystem path when the two share a disk, and as uploaded bytes named by their own
sha256 when they do not. `h3ir_client` owns that choice and makes it by trying, never by asking
anyone to declare which case they are in.

The compiler is a declared dependency, in `pyproject.toml` and in the `requirements.txt` Manager
pip-installs. That is what makes an in-process compile possible without this pack ever carrying a
copy of the compiler. The import stays lazy, and `contract.py` holds the one function that does it.

The node registration lives in `nodes.py` as a `comfy_entrypoint`, which is ComfyUI's current way of
declaring nodes and the same one the built-in MiniMax H3 nodes use. It is imported lazily below so
that this package stays importable outside ComfyUI: the parts worth testing do not need a canvas, and
`h3ir_client` and `tray` have no ComfyUI imports at all.

`WEB_DIRECTORY` is how a pack ships frontend code: ComfyUI reads this name off this module and serves
that folder, and the browser loads every `.js` in it. What is in there is the media tray's panel, the
prompt's @ picker, the director's panel, the family's colours, and one generated data module the
director's panel reads its seven directions out of. All of it is decoration in the strict sense. The
tray and the direction are JSON in ordinary widgets and the prompt is plain text in one; delete this
folder and all three nodes still work, still API-drive, and still restore from a saved workflow, with
the strings visible as themselves.

`contract.py` is the other half of that: the pack's snapshot of what the compiler takes, and what a
difference between the two costs. It reads a generated JSON file beside it with the standard library
and imports nothing from `h3ir`, so the rule above still holds.

`web_api` is imported at module scope because its two HTTP routes have to be registered while ComfyUI
is starting, and it is written to import cleanly with no ComfyUI present: an exception here would take
the whole pack off the menu with a traceback nobody can act on.
"""
from __future__ import annotations

from . import web_api  # noqa: F401 - imported for the routes it registers

WEB_DIRECTORY = "web"


async def comfy_entrypoint():
    """Hand ComfyUI the node list. Imported here rather than at module scope so a machine without
    ComfyUI can still import this package to test the parts that do not need it."""
    from .nodes import comfy_entrypoint as real
    return await real()


__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]
