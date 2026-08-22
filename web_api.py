"""The two HTTP routes the media tray's panel needs, and nothing else.

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

Route shape and the `input/<pack>/` convention follow ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's
`web_api.py` (MIT), which is credited in README.md.
"""
from __future__ import annotations

import os
import re
import time

from . import media

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
