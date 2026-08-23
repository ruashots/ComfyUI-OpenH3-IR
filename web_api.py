"""The HTTP routes the pack's panels need, and nothing else.

A browser cannot put a dropped file where the graph can read it, so the panel posts it here and the
file lands in ComfyUI's own input folder under `openh3ir/`. What comes back is the annotated name
ComfyUI's file helpers take, which is what the tray stores, plus the facts the panel shows: a
duration, a size, and whether a clip has a soundtrack.

Written to be safe about the two things a route that writes files has to be safe about. The name is
reduced to a basename and then to letters, digits, dots, dashes and underscores, so nothing can climb
out of the folder, and the resolved path is checked against the folder afterwards anyway, because a
sanitiser you have not verified is a sanitiser you are trusting. Only the extensions H3 can actually
use are accepted, so an executable dropped on the panel by accident is refused rather than stored.

Nothing here decides anything about a render. The probe route exists so the panel can say "this file
is not on this machine" instead of drawing an empty square, and the node re-reads every file itself
when the graph runs: a stale duration in a saved workflow cannot change what gets sent.

The three routes under `/openh3ir/llm/` and `/openh3ir/compiler` are what the Setup node's panel asks
so somebody can find out whether an address answers, which models it serves and whether one of them
can read a picture, without queueing a graph to discover it. Every one of them reports rather than
decides: nothing here writes a widget, and the node re-resolves all of it at queue time from the
values on the canvas.

**Everything in them that talks to a network runs off the event loop.** ComfyUI serves its whole
frontend from one aiohttp loop, and the compiler's client is ordinary blocking `httpx`, so calling it
inline would freeze the canvas -- for everybody on that server -- for as long as a language model
takes to answer. `run_in_executor` is what keeps a slow endpoint a slow button rather than a hung
ComfyUI.

Route shape and the `input/<pack>/` convention follow ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's
`web_api.py` (MIT), which is credited in README.md.
"""
from __future__ import annotations

import asyncio
import functools
import os
import re
import time

from . import compiler, media

try:  # pragma: no cover - only inside ComfyUI
    from aiohttp import web
    from server import PromptServer
except Exception:  # noqa: BLE001 - importable outside ComfyUI is a supported case
    PromptServer = None
    web = None

try:  # pragma: no cover - only inside ComfyUI
    import folder_paths
except Exception:  # noqa: BLE001
    folder_paths = None

# Where uploads land: one folder inside ComfyUI's input tree, so a file dropped on the tray is a file
# every other node in ComfyUI can also see, and clearing it is one folder to delete.
SUBFOLDER = "openh3ir"

# What each kind of slot accepts. Only formats ComfyUI's own loaders read, because a file the panel
# accepts and the node cannot open is a failure moved from the drop to the queue.
EXTENSIONS = {
    "picture": (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"),
    "video": (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg"),
    "sound": (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"),
}


def kind_for(name: str) -> str:
    """Which kind of slot a filename belongs on, or "" for a file no slot takes."""
    ext = os.path.splitext(name or "")[1].lower()
    for kind, allowed in EXTENSIONS.items():
        if ext in allowed:
            return kind
    return ""


def safe_name(name: str) -> str:
    """A basename with nothing in it that means anything to a path."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (cleaned or "upload")[:120]


def _target_dir() -> str:
    base = folder_paths.get_input_directory() if folder_paths else "input"
    path = os.path.join(base, SUBFOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def _free_name(directory: str, name: str) -> str:
    """A name nothing already uses, so an upload never overwrites a file a saved workflow points at."""
    stem, ext = os.path.splitext(name)
    candidate = name
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem}_{int(time.time() * 1000) % 1000000}{ext}"
        stem = os.path.splitext(candidate)[0]
    return candidate


if PromptServer is not None and web is not None:  # pragma: no cover - needs a running ComfyUI

    routes = PromptServer.instance.routes

    @routes.post("/openh3ir/upload")
    async def openh3ir_upload(request):
        """One file onto the tray. Returns the annotated name the tray stores plus what to show."""
        try:
            reader = await request.multipart()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "expected a multipart form with one file in it"},
                                     status=400)
        field = await reader.next()
        while field is not None and field.name != "file":
            field = await reader.next()
        if field is None:
            return web.json_response({"error": "no file in the request"}, status=400)

        original = field.filename or "upload"
        kind = kind_for(original)
        if not kind:
            return web.json_response({
                "error": f"the tray takes no {os.path.splitext(original)[1] or 'extensionless'} "
                         "file. Pictures: " + ", ".join(EXTENSIONS["picture"]) + ". Clips: "
                         + ", ".join(EXTENSIONS["video"]) + ". Sounds: "
                         + ", ".join(EXTENSIONS["sound"]) + "."}, status=400)

        directory = _target_dir()
        name = _free_name(directory, safe_name(original))
        path = os.path.abspath(os.path.join(directory, name))
        if os.path.commonpath((os.path.abspath(directory), path)) != os.path.abspath(directory):
            return web.json_response({"error": "that filename does not stay inside the input "
                                               "folder"}, status=400)
        size = 0
        try:
            with open(path, "wb") as fh:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    fh.write(chunk)
        except Exception as exc:  # noqa: BLE001 - a half-written file is worse than none
            if os.path.exists(path):
                os.remove(path)
            return web.json_response({"error": f"could not write the file: {exc}"}, status=500)

        annotated = f"{SUBFOLDER}/{name} [input]"
        info = media.probe(annotated)
        return web.json_response({"file": annotated, "name": name, "original": original,
                                  "kind": kind, "size": size, **info})

    @routes.get("/openh3ir/probe")
    async def openh3ir_probe(request):
        """Whether a file a saved tray names is still here, and what to show for it."""
        annotated = request.query.get("file") or ""
        if not annotated:
            return web.json_response({"error": "no file asked about"}, status=400)
        return web.json_response({"file": annotated, "present": media.present(annotated),
                                  "kind": kind_for(annotated), **media.probe(annotated)})

    async def _off_the_loop(fn, *args, **kw):
        """Run a blocking call in a thread, so a slow endpoint never stops ComfyUI serving pages."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(fn, *args, **kw))

    @routes.get("/openh3ir/compiler")
    async def openh3ir_compiler(request):
        """Whether the pack can compile in this ComfyUI at all, and which build would do it.

        The one question the panel cannot answer from the canvas: `open-h3-ir` is a separate
        installation and it can be absent, half-installed or older than this pack. Three states
        rather than two, because absent and broken have two different fixes.

        Importing a package is disk work and can be slow the first time, so it goes off the loop
        like the rest.
        """
        state, detail = await _off_the_loop(compiler.availability)
        live = await _off_the_loop(compiler.installed_contract) if state == "ok" else None
        # What the environment would give if the node's two fields are left empty. The panel says so
        # before a queue: an empty field that is not really empty is the most confusing state this
        # node has, and until now it was a line in the report that only appeared after a run.
        env = compiler.environment_defaults()
        return web.json_response({
            "state": state,
            "detail": detail,
            "version": (await _off_the_loop(compiler.package_version)) if state == "ok" else "",
            "contract_version": (live or {}).get("contract_version"),
            "distribution": compiler.DISTRIBUTION,
            "env_url": env["url"],
            "env_model": env["model"],
        })

    @routes.post("/openh3ir/llm/models")
    async def openh3ir_llm_models(request):
        """What is answering at an address and which models it serves.

        `choose_from` is the list to offer. It can be shorter than `ids`: one set of weights
        published under several names is one model, and offering the same model twice would be this
        panel inventing a decision.
        """
        try:
            body = await request.json()
        except Exception:                               # noqa: BLE001 - a malformed body is a 400
            return web.json_response({"error": "expected a JSON body with a url in it"}, status=400)
        url = str((body or {}).get("url") or "").strip()
        if not url:
            return web.json_response({"error": "no address to test. Type the language model's "
                                               "address first."}, status=400)
        return web.json_response(await _off_the_loop(compiler.endpoint_report, url,
                                                     timeout=float(body.get("timeout") or 20.0)))

    @routes.post("/openh3ir/llm/vision")
    async def openh3ir_llm_vision(request):
        """Whether one model can read a picture, by sending it one.

        The only way to know. No model list on any of these servers reports vision, and a text-only
        model answers every other check perfectly and then reads none of the tray, so the brief comes
        back describing pictures nobody looked at.

        It costs one request to the model, so the panel asks for it rather than doing it on every
        keystroke, and `ok` comes back as null when the check could not be completed: a timeout says
        nothing either way, and reporting a verdict from one would be guessing about the thing this
        was asked to measure.
        """
        try:
            body = await request.json()
        except Exception:                               # noqa: BLE001 - a malformed body is a 400
            return web.json_response({"error": "expected a JSON body with a url and a model in it"},
                                     status=400)
        url = str((body or {}).get("url") or "").strip()
        model = str((body or {}).get("model") or "").strip()
        if not url:
            return web.json_response({"error": "no address to test"}, status=400)
        return web.json_response(await _off_the_loop(compiler.can_it_see, url, model,
                                                     timeout=float(body.get("timeout") or 120.0)))
