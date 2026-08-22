"""Files in ComfyUI's input tree, turned into the tensors H3 needs and the facts a panel shows.

The tray holds files, not tensors, and that is the whole point: the bytes the service opens and the
pixels H3 receives come from one file, so a path and a tensor cannot describe different pictures. The
old version of this module went the other way, writing a tensor from a socket back out to a temp file
for the service to read, and the two could drift.

Decoding is delegated to ComfyUI's own machinery wherever ComfyUI has some, which is deliberate and
not laziness: `comfy_extras.nodes_audio.load` is byte-for-byte what Load Audio does and
`InputImpl.VideoFromFile` is what Load Video does, so anything that works in one of those works
identically here, and a copy of either would be the version that rots. Stills go through PIL with
`exif_transpose`, which is what ComfyUI's own Load Image does.

Two facts about ComfyUI's types shape the rest, and both were learned by running a real graph.

An AUDIO is a **mapping** of `waveform` and `sample_rate`, not necessarily a dict. Load Video
(Upload) hands out a `LazyAudioMap`: a Mapping subclass that runs ffmpeg the first time a key is
read. Anything here that tested for `dict` refused that loader and reported the clip as having no
soundtrack.

An IMAGE is a batch even when the user is thinking of one picture, so a clip's frames and a still are
the same type and only their length tells them apart.

The one thing still written rather than read is a clip's separated soundtrack: it lives inside the
video container, the service needs a file per asset, and a `.mp4` handed over as `kind: audio` is a
file whose bytes contradict its declaration. So it is decoded and written as a wav named by its own
content, which is also what keeps an unchanged clip's soundtrack on an unchanged path.

Technique for reading media out of ComfyUI's input tree follows ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's
`media_io.py` (MIT), which is credited in README.md.
"""
from __future__ import annotations

import hashlib
import os
import wave
from collections.abc import Mapping
from typing import Any

from .h3ir_client import FPS, ServiceError

# H3's runtime refuses a reference clip below five frames outright, so a shorter one is a brief that
# cannot render. `h3ir/compile.py` MIN_REF_VIDEO_FRAMES.
MIN_CLIP_FRAMES = 5


def slug(name: str) -> str:
    """A slot label as a filename fragment. Labels are letters, digits and dashes, and a separated
    soundtrack is named `<label> sound`, so the space is flattened here rather than leaking into a
    path some tool will re-split."""
    return "".join(c if c.isalnum() else "_" for c in name)


def digest(obj: Any) -> str:
    """Content hash of anything that can arrive on a socket.

    The bundle is walked rather than hashed by identity: the Media node hands over a mapping of
    tensors, and `repr` of that is a memory address. Hashing the address would make a swapped file or
    a re-typed note look like no change at all, and ComfyUI would hand back the previous brief.
    """
    if obj is None:
        return "none"
    try:
        import numpy as np
        if isinstance(obj, Mapping):
            if "waveform" in obj:
                return digest(obj.get("waveform")) + f"@{obj.get('sample_rate')}"
            return "{" + ",".join(f"{k}={digest(obj[k])}" for k in sorted(obj)) + "}"
        if isinstance(obj, (list, tuple)):
            return "[" + ",".join(digest(o) for o in obj) + "]"
        if isinstance(obj, (str, int, float, bool)):
            return repr(obj)
        arr = obj.detach().cpu().numpy() if hasattr(obj, "detach") else np.asarray(obj)
        return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()
    except Exception:  # noqa: BLE001 - a hash we cannot take must not break the graph
        return "unhashable"


def sha256_file(path: str) -> str:
    """The same hash the service takes of the same bytes, which is what lets the report put the
    user's slot labels back onto the labels the service computed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- where a file is

def resolve(annotated: str) -> str:
    """`subfolder/name [input]` as an absolute path, asked of ComfyUI rather than assembled here.

    ComfyUI's own helper is what every upload widget's value is designed for, and it is the only
    thing that knows where this install keeps its input, output and temp folders.
    """
    try:
        import folder_paths
        return str(folder_paths.get_annotated_filepath(annotated))
    except Exception:  # noqa: BLE001 - importable outside ComfyUI is a supported case
        name = annotated
        for suffix in (" [input]", " [output]", " [temp]"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name


def present(annotated: str) -> bool:
    path = resolve(annotated)
    return bool(path) and os.path.isfile(path)


def stamp(annotated: str) -> str:
    """What a file is right now, for the cache key: its size and its modification time.

    The tray names files, and a file can be replaced on disk under the same name. Hashing only the
    tray's text would then serve a brief written about the picture that used to be there. Cheap
    enough to do on every queue, which is the point: the alternative is reading every file.
    """
    path = resolve(annotated)
    try:
        st = os.stat(path)
        return f"{annotated}:{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return f"{annotated}:missing"


def probe(annotated: str) -> dict[str, Any]:
    """Duration, dimensions and whether there is a soundtrack, for the panel to show. Never raises.

    Only ever used for display and for deciding what a panel offers. Nothing about the render is
    decided from it: the node re-reads the file itself, so a stale number in a saved workflow cannot
    change what gets sent.
    """
    info: dict[str, Any] = {"duration": None, "has_audio": False, "width": None, "height": None}
    path = resolve(annotated)
    if not path or not os.path.isfile(path):
        return info
    try:
        import av
        with av.open(path) as c:
            if c.duration:
                info["duration"] = round(c.duration / 1000000.0, 2)
            info["has_audio"] = len(c.streams.audio) > 0
            if c.streams.video:
                s = c.streams.video[0]
                info["width"] = int(s.codec_context.width)
                info["height"] = int(s.codec_context.height)
    except Exception:  # noqa: BLE001 - a fact we cannot read is not a failure of the graph
        pass
    return info


# --------------------------------------------------------------------------- reading a file

def _missing(annotated: str, label: str) -> ServiceError:
    return ServiceError(
        f"the slot {label!r} points at {annotated}, and there is no such file in this ComfyUI's "
        "input folder. A workflow carries the names of its media rather than the media, so a "
        "workflow from another machine has to have its files dropped on the tray again. Drop the "
        "file on that slot, or remove the slot.")


def load_image(annotated: str, label: str) -> Any:
    """One still as an IMAGE batch of one, [1, H, W, 3] in 0..1.

    `exif_transpose` because ComfyUI's own Load Image does it and because the browser thumbnail in
    the tray does it: what the user saw when they dropped the file is what H3 receives.
    """
    path = resolve(annotated)
    if not os.path.isfile(path):
        raise _missing(annotated, label)

    import numpy as np
    import torch
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            arr = np.asarray(img).astype(np.float32) / 255.0
    except Exception as e:  # noqa: BLE001 - an unreadable file must say which one
        raise ServiceError(
            f"{label!r} could not be read as a picture ({type(e).__name__}: {e}). The file is "
            f"{os.path.basename(path)}. Drop a png, jpeg or webp on that slot.") from e
    return torch.from_numpy(arr)[None, ...]


def load_video(annotated: str, label: str) -> tuple[Any, Any, float]:
    """A clip as (frames at 24 fps, its soundtrack or None, the rate it was filmed at).

    Resampled onto H3's own 24 fps grid rather than relabelled. H3 reads reference footage at 24 fps
    and the stock node assumes it, so a 30 fps clip handed over untouched plays a quarter slow inside
    the model while the service's own probe of the file reports the real duration: the brief is then
    written about one length and the render conditioned on another. Picking frames on the 24 fps grid
    keeps both true at once, which is the only arrangement where the report is not lying to somebody.
    """
    path = resolve(annotated)
    if not os.path.isfile(path):
        raise _missing(annotated, label)

    import torch
    from comfy_api.latest import InputImpl

    try:
        parts = InputImpl.VideoFromFile(path).get_components()
    except Exception as e:  # noqa: BLE001 - a clip ComfyUI cannot open must name itself
        raise ServiceError(
            f"{label!r} could not be read as a clip ({type(e).__name__}: {e}). The file is "
            f"{os.path.basename(path)}. It is opened with the same decoder as ComfyUI's own Load "
            "Video, so a file that fails here fails there too.") from e
    frames = parts.images
    source_fps = float(parts.frame_rate or FPS)
    n = int(frames.shape[0])
    if n < 1:
        raise ServiceError(
            f"{label!r} decoded to no frames at all, so there is no footage in it. The file is "
            f"{os.path.basename(path)}.")
    if abs(source_fps - FPS) > 0.01:
        want = max(1, round(n * FPS / source_fps))
        picked = torch.linspace(0, n - 1, want, device=frames.device).round().long()
        frames = frames[picked]
    if int(frames.shape[0]) < MIN_CLIP_FRAMES:
        raise ServiceError(
            f"{label!r} is {frames.shape[0]} frame(s) long at {FPS} fps, and H3's runtime refuses a "
            f"reference clip under {MIN_CLIP_FRAMES} frames outright. H3 reads footage of 2 to 15 "
            "seconds. Use a real clip rather than a still, or put the still on a picture slot.")
    return frames, parts.audio, source_fps


def load_sound(annotated: str, label: str) -> Any:
    """One sound as an AUDIO, decoded by ComfyUI's own Load Audio so the two cannot differ."""
    path = resolve(annotated)
    if not os.path.isfile(path):
        raise _missing(annotated, label)
    try:
        from comfy_extras.nodes_audio import load as comfy_load
    except Exception as e:  # noqa: BLE001
        raise ServiceError(
            "this ComfyUI has no audio loading of its own (comfy_extras.nodes_audio would not "
            "import), so a sound cannot be read. Update ComfyUI to a version whose own Load Audio "
            "node works.") from e
    try:
        waveform, rate = comfy_load(path)
    except Exception as e:  # noqa: BLE001
        raise ServiceError(
            f"{label!r} could not be read as a sound ({type(e).__name__}: {e}). The file is "
            f"{os.path.basename(path)}. It is opened with the same decoder as ComfyUI's own Load "
            "Audio, so a file that fails here fails there too.") from e
    return {"waveform": waveform.unsqueeze(0), "sample_rate": int(rate)}


# --------------------------------------------------------------------------- writing a soundtrack

def waveform_of(audio: Any, label: str) -> tuple[Any, int]:
    """A ComfyUI AUDIO as (channels-by-samples array, sample rate).

    Read through the Mapping interface, which is the actual contract: the stock nodes do
    `audio["waveform"]` and never ask what class it is.
    """
    import numpy as np

    wf = audio.get("waveform") if isinstance(audio, Mapping) else None
    sr = int(audio.get("sample_rate") or 0) if isinstance(audio, Mapping) else 0
    if wf is None or not sr:
        raise ServiceError(
            f"{label} is not a sound this node can read: an AUDIO carries a waveform and a sample "
            f"rate, and this one has {'no rate' if wf is not None else 'no waveform'}. Feed it from "
            "a Load Audio node, or from a video loader's audio output.")
    arr = wf.detach().cpu().numpy() if hasattr(wf, "detach") else np.asarray(wf)
    while arr.ndim > 2:
        arr = arr[0]
    if arr.ndim == 1:
        arr = arr[None, :]
    return arr, sr


def write_sound(audio: Any, label: str, into: str) -> tuple[str, float]:
    """Write a ComfyUI AUDIO as a 16-bit wav using the standard library, so no install is asked for
    an encoder it might not have.

    Named by its own content, so an unchanged soundtrack keeps its path, the service's hash of it
    stays stable, and two different clips of the same length can never land on one file and have the
    second silently reuse the first.
    """
    import numpy as np

    arr, sr = waveform_of(audio, label)
    channels, samples = arr.shape
    pcm = (np.clip(arr.T, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    path = os.path.join(into, f"openh3ir_{slug(label)}_"
                              f"{hashlib.sha256(pcm).hexdigest()[:16]}.wav")
    if not os.path.exists(path):
        with wave.open(path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
    return path, samples / float(sr)
