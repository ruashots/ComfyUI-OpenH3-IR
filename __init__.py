"""OpenH3-IR nodes for ComfyUI.

This repository is the whole node pack, and its root is the pack's root. ComfyUI Manager clones a
repository straight into `custom_nodes`, so what lands there is this directory, and this file is what
ComfyUI imports. Installation and wiring are in README.md beside it.

**The compiler runs here.** Install the pack, put the address of your own language model on the
Setup node, and render: there is no service to start, no port to pick and no second process. The
compiler is the `open-h3-ir` package that `requirements.txt` names, ComfyUI Manager pip-installs it
with the pack, and it runs in the same Python. This pack still carries no copy of it: a compiler bug
is fixed and released over there, and nothing here changes for it.

Putting an address in that same field on the Setup node moves the compile to a service there, for
somebody running it on another machine, and that path is not the poor relation -- the same graph
produces the same brief either way. The media then goes to the service as a filesystem path when the
two share a disk, and as uploaded bytes named by their own sha256 when they do not. `h3ir_client`
owns that choice and makes it by trying, never by asking anyone to declare which case they are in.

Nothing here imports the `h3ir` package while ComfyUI is loading the pack. `compiler.py` is the one
module that names it at all and every one of those imports is inside a function, because a pack
whose import raises is a pack ComfyUI drops off the menu with a traceback nobody can act on, a pack
driving a remote compiler needs no local package, and the compiler declares fastapi, uvicorn,
pydantic and tiktoken. Measured: an in-process compile loads none of those four.

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

`web_api` is imported at module scope because its HTTP routes have to be registered while ComfyUI is
starting, and it is written to import cleanly with no ComfyUI present: an exception here would take
the whole pack off the menu with a traceback nobody can act on. Those routes are what the panels ask
-- where a dropped file went, whether the compiler is installed here, what a language model endpoint
serves, and whether one of its models can read a picture.
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
