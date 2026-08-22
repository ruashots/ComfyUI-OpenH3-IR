"""Talking to an OpenH3-IR service, with no ComfyUI and no third-party packages involved.

Everything in this module is a pure function or a thin call over the standard library, so the whole
integration can be tested without ComfyUI, without torch, and without a running server. The nodes in
`nodes.py` own the parts that can only exist inside ComfyUI: tensors, temp directories, model
loaders, and the schema the canvas draws.

Two deliberate choices worth knowing about before changing anything here.

Only the standard library. ComfyUI installs are other people's machines: embedded Pythons, frozen
requirement sets, five year old forks. A node that adds a dependency can break an install that was
working, so this speaks HTTP with `urllib` and accepts the slightly longer code.

Errors are written for the person on the canvas. A ComfyUI user sees one toast and a console
traceback, and that message is the only documentation they are guaranteed to read. So every failure
this module raises names what went wrong, what it was talking to, and the next action. None of them
say "check your configuration".
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import socket
import textwrap
import urllib.error
import urllib.request
from typing import Any

# The port `h3ir serve` binds by default. Kept here as the node's default so the common case is
# "start the server, drop the node in, it works".
DEFAULT_PORT = 8420
DEFAULT_SERVER = f"http://127.0.0.1:{DEFAULT_PORT}"

# The refusals that are about the REQUEST rather than about the service, the transfer or a file:
# the compiler read what the graph asked for, found it contradictory, and said so in a sentence the
# person can act on. They share one branch in `compile_brief` because they share one answer.
#
# `over-capacity` is deliberately not here. It is the same class and it earns its own branch,
# because the number of sockets H3 has is a fact worth stating rather than leaving to the message.
#
# Kept current by `tests/test_comfyui_node.py`, which drives this module with every refusal the
# shipped contract publishes and fails on any that reaches the generic branch. Eleven of these were
# invisible to that test until the contract listed them.
REFUSED_AS_ASKED = (
    "aspect-invalid", "director-profile-invalid", "duration-invalid", "intent-empty",
    "replacement-subject-undefined", "replacement-target-ambiguous", "replacement-target-unnamed",
    "replaces-without-the-role", "shots-do-not-fit", "shots-invalid", "swap-without-edit-source",
)

CREATIVITY = ("restrained", "balanced", "bold", "extreme")
EFFORT = ("fast", "standard", "max")
# Reported by GET /v1/capabilities. Duplicated as a widget list because a combo has to be populated
# before any server has been contacted.
ASPECTS = ("16:9", "21:9", "4:3", "1:1", "3:4", "9:16")
SIZING = ("match", "max")
WEIGHT_DTYPES = ("default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2")
# The languages GET /v1/capabilities publishes for dialogue, duplicated for the same reason ASPECTS
# is: a combo has to be populated before any server has been contacted. It is the service's own
# published list and not a limit the compiler enforces -- it writes whatever language it is given
# into the `[tag]` H3 reads -- so the field's own tooltip says what to do about a language that is
# not here rather than the surface pretending none exists.
DIALOGUE_LANGUAGES = ("English", "Spanish", "Portuguese", "French", "German", "Italian", "Russian",
                      "Arabic", "Chinese", "Japanese", "Korean")

FPS = 24
# h3ir/shots.py MAX_SHOTS. The compiler clamps to this, so offering more would promise a cut count
# the engine drops without saying so.
MAX_SHOTS = 10   # the service's PINNED_SHOTS_MAX; auto has its own lower heuristic ceiling
SHOTS = ("auto", *(str(i) for i in range(1, MAX_SHOTS + 1)))
# h3ir/grid.py TRAINED_MIN_FRAMES / TRAINED_MAX_FRAMES. Outside this band a render still happens;
# the report says so rather than the surface forbidding it.
TRAINED_MIN_FRAMES = 124
TRAINED_MAX_FRAMES = 362

# H3's own ceilings and the vocabulary of what a file can be live in `tray`, beside the slot they
# describe. This module is the service protocol and nothing else: what a user may say about their
# own media is the tray's business, and it changed once when the sockets became slots.

# Which loader owns a file, decided by its extension because that is the one fact the file itself
# carries. Names as ComfyUI shows them, so the report names something the user can find.
LOADER_NATIVE_UNET = "UNETLoader"
LOADER_GGUF_UNET = "Unet Loader (GGUF)"
LOADER_NATIVE_CLIP = "CLIPLoader"
LOADER_GGUF_CLIP = "CLIPLoader (GGUF)"


class ServiceError(RuntimeError):
    """Raised for every failure a node user can act on. The message is the user interface.

    `code` exists so callers can react to a class of failure without reading the prose. Sniffing the
    message would break the moment the wording improved, and the wording is meant to keep improving.

    `missing` carries the content hashes the service says it does not hold, for the one failure that
    has a next step rather than a reader: the files are sent and the brief asked for again.
    """

    def __init__(self, message: str, code: str = "", missing: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.missing = tuple(missing)


# The marker for the one failure another spelling of the path could fix: the service could not
# RESOLVE the file. Deliberately not called `asset-unreadable`, which is the service's own code for
# a file it resolved, opened and could not decode. That one is not retryable, and a name that
# suggested otherwise would earn somebody three times the wait for the same answer.
PATH_MAY_BE_WRONG = "path-may-be-wrong"

# The marker for "no spelling of a path will do, send the bytes instead". Separate from the one
# above because the two lead to different next moves: another spelling is worth trying when the
# service merely could not find this file, and worth nothing when the service has said it does not
# open paths at all.
SEND_THE_BYTES = "send-the-bytes"


def send_the_bytes(error: Exception) -> bool:
    """True when this failure is worth another attempt at getting the media there.

    The two markers above, and nothing else. Anything else would hide a real problem behind repeated
    attempts: a corrupt clip is corrupt under every spelling and in the service's own store too, and
    a machine with no ffmpeg still has none on the third try.

    One predicate rather than two. It replaced `retranslate`, which asked the narrower question of
    whether another SPELLING was worth trying, and was the only question there was when running out
    of spellings was the end of the road.
    """
    return getattr(error, "code", "") in (SEND_THE_BYTES, PATH_MAY_BE_WRONG)


def path_candidates(comfy_root: str) -> list[str]:
    r"""Spellings of ComfyUI's folder to offer the service, best guess first.

    ComfyUI's own location is known from ComfyUI, so nobody types it. What cannot be known is how a
    service on another view of the same disk spells it, and the common case by far is ComfyUI on
    Windows with the service in WSL or a container, where C:\ComfyUI becomes /mnt/c/ComfyUI. So that
    form is offered and the service is asked to confirm it by actually opening the file. Nothing is
    assumed: a candidate that does not work produces the next attempt, and running out means the
    service cannot see ComfyUI's disk at all, which is where uploading takes over.

    There is no hand-typed override, because there was nothing anyone could usefully type: every
    spelling that can work is a spelling of a folder ComfyUI already named, and a service on another
    machine cannot open these files under any spelling, so it is sent the bytes instead.
    """
    if not comfy_root:
        return [""]
    out = [comfy_root]
    norm = comfy_root.replace("\\", "/")
    if len(norm) > 2 and norm[1] == ":":
        drive, rest = norm[0].lower(), norm[2:].lstrip("/")
        out.append(f"/mnt/{drive}/{rest}")
        out.append(f"/{drive}/{rest}")
    return out


def _url(server: str, path: str) -> str:
    return f"{server.rstrip('/')}{path}"


def _request(server: str, path: str, *, payload: dict[str, Any] | None = None,
             timeout: float = 600.0, method: str = "") -> tuple[int, Any]:
    """One HTTP call. Returns (status, decoded body) and lets 4xx and 5xx come back as values.

    An error status is data here rather than an exception, because the caller needs the body to say
    anything useful: the service reports which rule failed and which asset it could not read, and
    throwing that away would leave the node saying "HTTP 422".
    """
    url = _url(server, path)
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if payload is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, _decode(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, _decode(body)
    except socket.timeout as e:
        raise ServiceError(
            f"the OpenH3-IR service at {server} did not answer within {timeout:.0f}s. Writing a "
            "brief is one call to a language model, so it takes as long as that model takes. Raise "
            "the timeout on an OpenH3-IR Setup node, or point it at a faster endpoint.") from e
    except urllib.error.URLError as e:
        raise ServiceError(
            f"cannot reach an OpenH3-IR service at {server} ({e.reason}). Start one from the repo "
            f"with: h3ir serve --port {DEFAULT_PORT}. If it runs on another machine or another "
            "port, add an OpenH3-IR Setup node and put that address in its service field. The "
            "service also needs H3IR_LLM_URL pointing at your own OpenAI-compatible endpoint.") \
            from e


def _decode(body: str) -> Any:
    try:
        return json.loads(body) if body else None
    except json.JSONDecodeError:
        return body


def shot_count(shots: Any) -> int:
    """The `shots` widget as a number, with `auto` meaning 0: let the compiler decide.

    A combo of `auto` and 1..4 rather than an integer with a magic 0, because a magic value
    explained in its own label is the label doing the code's job. Integers still parse, so a
    workflow saved against the older surface keeps working.
    """
    if shots is None:
        return 0
    text = str(shots).strip().lower()
    if text in ("", "auto", "0"):
        return 0
    try:
        n = int(text)
    except ValueError:
        raise ServiceError(
            f"shots is {shots!r}, which is neither auto nor a number of shots. Pick auto, or 1 to "
            f"{MAX_SHOTS}.") from None
    if not 1 <= n <= MAX_SHOTS:
        raise ServiceError(
            f"{n} shots was asked for and the compiler's ceiling is {MAX_SHOTS}, so the extra cuts "
            "would be dropped without saying so. Pick auto, or 1 to "
            f"{MAX_SHOTS}.")
    return n


def dialogue_lines(said: list[str] | tuple[str, ...], language: str) -> list[dict[str, Any]]:
    """The prompt's locked lines as the service's `dialogue` list, one entry per line.

    Nothing here rewrites a word. These exist because the service checks them against the document it
    wrote -- the exact text has to come back inside `<d>`, word for word and mark for mark, or the
    brief is refused -- so a field that trimmed a quote mark or fixed a capital would break the one
    guarantee they are for. The lines arrive from `tray.parse_intent`, which takes what is between
    the quotes and edits none of it.

    The language is per line in the service's model and one control on the node, because it becomes
    the `[tag]` H3 reads and a Spanish line tagged English is spoken wrong. Mixed languages in one
    piece stay reachable the way they always were, by quoting inside the sentence, which is what the
    field's tooltip says.
    """
    said = [s for s in (said or ()) if s.strip()]
    # Checked where it is used and not before: with no lines in the prompt the language decides
    # nothing, and a combo cannot be mistyped from the canvas anyway. This is for the graph that
    # arrives over /prompt with a language nobody offered, which would otherwise be written into the
    # brief as H3's tag exactly as spelled.
    if said and language not in DIALOGUE_LANGUAGES:
        raise ServiceError(
            f"{language!r} is not one of the languages this field offers, and it would be written "
            "into the brief as H3's language tag exactly as spelled, so the lines would be spoken "
            "wrong. Pick one of: " + ", ".join(DIALOGUE_LANGUAGES) + ". For a language that is not "
            "there, quote the line in the sentence instead and name the language there.")
    return [{"text": t, "language": language} for t in said]


def build_payload(intent: str, *, seconds: float, aspect: str, creativity: str, effort: str,
                  megapixels: float = 0.0,
                  seed: int, silent: bool, shots: Any, assets: list[dict[str, Any]],
                  transcripts: dict[str, str], spoken: list[str] | tuple[str, ...] = (),
                  spoken_language: str = DIALOGUE_LANGUAGES[0],
                  director_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn the node's state into the service's BriefIn.

    Assets arrive already shaped, with their role named, because the node knows the role from the
    socket the user plugged into. Nothing here infers a role: an inferred role can disagree with how
    the graph is wired, and a graph that disagrees with its own brief renders something plausible
    and wrong.

    `auto` shots means "the compiler decides", which is the service's own default when the field is
    absent, so the key is dropped rather than sent as a shot count of zero.
    """
    intent = (intent or "").strip()
    if not intent:
        raise ServiceError(
            "nothing to compile: the intent field is empty. Type what should happen in the shot, "
            "in one ordinary sentence, for example: she walks out onto the wet gantry in the rain "
            "and stops when she sees the city below.")

    payload: dict[str, Any] = {
        "intent": intent,
        "assets": list(assets),
        "seconds": float(seconds),
        "aspect": aspect,
        "creativity": creativity,
        "effort": effort,
        "seed": int(seed),
        "silent": bool(silent),
    }
    # The node sends the PROSE, never an id: a shipped director is loaded into the box on the canvas
    # and is the user's to edit from that moment, so what is on the node is the only honest thing to
    # send. `director` (an id) stays in the service's schema for the CLI and for an agent calling the
    # API, and nothing in this pack fills it.
    #
    # Omitted entirely when nothing is written, so a graph with no Director node sends
    # byte-identically to one written before the node existed. A default that travels is a default
    # that shows up in a diff of two payloads and makes somebody wonder what changed.
    if director_profile and (director_profile.get("notes") or "").strip():
        payload["director_profile"] = dict(director_profile)
    n = shot_count(shots)
    if n > 0:
        payload["shots"] = n
    if transcripts:
        payload["transcripts"] = dict(transcripts)
    # 0 is the node's "H3 decides": the field is omitted and the service renders at the model's
    # native 768 short edge, exactly as every graph before the knob existed. A stated value is the
    # caller stating the budget, and the report's canvas line shows what it bought.
    if megapixels and float(megapixels) > 0:
        # The widget steps from 0.05 and the service's floor is 0.25, so the gap used to travel
        # and come back as a nameless 422. Refused here instead, with the range.
        if float(megapixels) < 0.25:
            raise ServiceError(
                f"size, in megapixels is {float(megapixels):g}, and the smallest stated size the "
                "service renders is 0.25. Set 0 for H3's native size, or a value from 0.25 to 2.5.")
        payload["megapixels"] = round(float(megapixels), 2)
    # Empty means absent. No lines in the prompt is not "no lines were asked for" stated in a field,
    # it is the same request this node made before a line could be locked, so the key is dropped
    # rather than sent as an empty list: the writer is then free to put a line in a mouth exactly as
    # far as `invention` allows, which is the behaviour every saved workflow has.
    dialogue = dialogue_lines(spoken, spoken_language)
    if dialogue:
        payload["dialogue"] = dialogue
    return payload


def _asset_facts(name: str, kind: str, extra: dict[str, Any], sizing: str) -> dict[str, Any]:
    """Everything about one attachment except where its bytes are.

    Shared by the two ways of saying that, so a fact can never be attached to a path and forgotten
    on an upload: `seconds` decides the soundscape the writer is given, `note` is the only channel by
    which anything is known about a sound at all, and a role is what stops the graph and the brief
    disagreeing. All three going missing on a remote service would be silent.
    """
    role = extra.get("role")
    if not role:
        raise ServiceError(f"internal: no role recorded for {name!r}")
    a: dict[str, Any] = {"kind": kind, "role": role}
    if kind == "image":
        a["sizing"] = sizing
    note = str(extra.get("note") or "")
    if note.strip():
        a["note"] = note.strip()
    # Who a `replacement_subject` picture takes over from, in the user's own words. It was recorded
    # on the slot, validated by the tray and written into `extra` by the node, and then dropped
    # HERE: this function copied four keys and this was not one of them. Everything on both sides of
    # the gap was correct and tested -- the panel collected the words, `check_swaps` refused a swap
    # that named nobody, the service declared the field, the compiler bound the subject with it --
    # and the words never crossed. What the user saw was the compiler refusing a question they had
    # already answered, or a swap bound to whoever the analyser happened to find.
    #
    # The lesson is in `test_contract_drift.py`: the test guarding this compared a line of
    # `nodes.py` against a field of `AssetIn` and never looked at the payload in between, so it
    # passed for as long as the bug lived. Assert about what goes out, not about what is written
    # down.
    if str(extra.get("replaces") or "").strip():
        a["replaces"] = str(extra["replaces"]).strip()
    for key in ("seconds", "frames"):
        if extra.get(key) is not None:
            a[key] = extra[key]
    return a


def plan_assets(written: list[tuple[str, str, str, dict[str, Any]]],
                sizing: str, from_prefix: str, to_prefix: str) -> list[dict[str, Any]]:
    """Describe every attached file for the service as paths, in the order it should be numbered.

    `written` is already on disk: a list of (name, kind, path, extra), where the name is the tray
    slot's own label and is what the report puts back onto the service's labels. `extra` carries
    everything the slot knows and this function cannot: its role, its note, the clip a soundtrack
    belongs to, a duration and a frame count.

    Nothing here infers a role. Every slot states what it is, so a missing role is an internal error
    rather than a quiet `subject`: an inferred role can disagree with what the tray says, and a
    request that disagrees with itself renders something plausible and wrong.
    """
    assets: list[dict[str, Any]] = []
    for name, kind, path, extra in written:
        a = _asset_facts(name, kind, extra, sizing)
        a["path"] = translate_path(path, from_prefix, to_prefix)
        # The pointer from a soundtrack back to its own clip is a path like any other, so it needs
        # the same translation. Sent untranslated it named a file the service could not open, the
        # service quietly stopped treating the pair as a pair, and the soundtrack was numbered as a
        # standalone <Audio 1> while H3 received it as ref_video_audio_1. Two different labels for
        # one file, and only the report said so.
        if extra.get("paired_video_path"):
            a["paired_video_path"] = translate_path(extra["paired_video_path"], from_prefix,
                                                    to_prefix)
        assets.append(a)
    return assets


def plan_uploaded_assets(written: list[tuple[str, str, str, dict[str, Any]]],
                         sizing: str, sha_of: Any) -> list[dict[str, Any]]:
    """The same description, for a service that cannot see this disk: content hashes, not paths.

    Every other field is identical, because nothing else about an attachment depends on how it got
    there. What changes is the one thing that cannot survive the trip -- a path is meaningless on
    another machine -- so the file is named by what is in it instead, which is a name both sides
    compute from the same bytes and neither has to be told.

    A soundtrack's pointer at its own clip becomes a hash for the same reason. Sent as a path it
    would name nothing on the service's disk, the pair would quietly stop being a pair, and the
    soundtrack would be numbered as a standalone sound while the runtime received it as that clip's
    own audio track.
    """
    assets: list[dict[str, Any]] = []
    for name, kind, path, extra in written:
        a = _asset_facts(name, kind, extra, sizing)
        a["sha256"] = sha_of(path)
        if extra.get("paired_video_path"):
            a["paired_video_sha256"] = sha_of(extra["paired_video_path"])
        assets.append(a)
    return assets


def payload_shape(written: list[tuple[str, str, str, dict[str, Any]]], brief: dict[str, Any],
                  transcripts: dict[str, str] | None = None
                  ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Exactly what this graph is about to say: its attachment keys, its brief keys, and its roles.

    Derived by running the very functions that build the request rather than by listing what the
    pack can do, and that is the entire point. A list of what the pack CAN send is a second
    statement that drifts from what it does send -- which is the failure this whole module was
    audited for: `replaces` was written into the node's `extra`, declared on the service's model,
    guarded by a test that read both of those as text, and dropped in between by a function that
    copied four keys. Nothing that describes the payload from the outside would have caught it.

    Both delivery routes are asked, because which one runs is decided later by whether the service
    can open ComfyUI's disk, and a check that only covered one of them would pass on a machine that
    shares a filesystem and stop covering anything on a machine that does not.

    The roles come back as (kind, role) in the WIRE's words -- image, video, audio -- because that
    is what the contract publishes them under. A tray calls a picture a picture; the request says
    image.
    """
    by_path = plan_assets(written, "match", "", "")
    by_hash = plan_uploaded_assets(written, "match", lambda _p: "0" * 64)
    asset_fields: dict[str, None] = {}
    roles: dict[tuple[str, str], None] = {}
    for a in (*by_path, *by_hash):
        for key in a:
            asset_fields[key] = None
        if a.get("role"):
            roles[(str(a.get("kind", "image")), str(a["role"]))] = None
    # Built with no attachments, so the asset half above is the only statement about attachments and
    # this one is only about the piece. An empty list is a legal request and `build_payload` refuses
    # nothing else here that a real one would pass.
    #
    # The transcripts ARE passed, and that is not symmetry with the assets: `build_payload` drops
    # the key when there are none, so describing a graph that has them with an empty dict would miss
    # `transcripts` entirely -- and passing a fake one on a graph without them would report a field
    # the request never carries, which against an older service is a stop for something nobody is
    # doing. Every optional key in a request has to be decided by the real value.
    brief_fields = tuple(build_payload(assets=[], transcripts=dict(transcripts or {}), **brief))
    return tuple(asset_fields), brief_fields, tuple(roles)


def fetch_contract(server: str, *, timeout: float = 30.0) -> dict[str, Any] | None:
    """What the service says crosses between it and whatever drives it, or None if it does not say.

    None means one thing only: this service predates the contract endpoint. It is not an error and
    must never be raised as one -- a service that is simply older still compiles every brief that
    uses nothing newer than itself, and refusing those would be this pack breaking working setups.
    The caller turns None into a sentence; see `contract.differences`.

    Anything that is not a clean answer is also None rather than an exception, for the same reason.
    The request that matters is the one after this, and it has its own messages for every way a
    service can be unreachable. Failing a queue here would replace those with a worse one.
    """
    try:
        status, body = _request(server, "/v1/contract", timeout=timeout)
    except ServiceError:
        return None
    if status != 200 or not isinstance(body, dict) or "contract_version" not in body:
        return None
    return body


def expected_mode(has_first: bool, has_last: bool, n_pictures: int, n_clips: int,
                  n_sounds: int = 0, has_storyboard: bool = False) -> str:
    """Which H3 task the tray describes, decided by what each slot says it is rather than by prose.

    The user set a picture to `first frame` or to `something in the shot`, and those are different
    jobs with different model weights behind them. Reading the answer off the tray means the graph
    and the brief cannot disagree, which is the failure this replaced: the compiler deciding an image
    was an opening frame while the graph fed it as a reference, with nothing to say so.

    A sound counts as a reference. FOUND BY RENDERING: it did not, so a graph with only a music clip
    attached declared t2va while the service correctly wrote ref2va, and the node then printed a
    warning saying the render would come out wrong. It would not have. The service's own rule is
    explicit that an attached video or audio forces ref2va, because H3's frame checkpoint cannot
    accept either, and a warning that fires on a correct graph teaches people to ignore warnings.
    """
    if has_first and has_last:
        return "fl2va"
    if has_last:
        return "l2va"
    if has_first:
        return "i2va"
    # A storyboard counts as a reference for the same reason a sound does: it is an attached file the
    # reference route carries and the frame route cannot, so a graph holding nothing but a board is a
    # ref2va job and saying t2va here would print a warning about a correct graph.
    if n_pictures or n_clips or n_sounds or has_storyboard:
        return "ref2va"
    return "t2va"


def check_mode(declared: str, reported: str) -> str | None:
    """Compare what the graph asked for with what the service says it wrote.

    Returns a sentence when they disagree, or None. The service can still reach a different
    conclusion, and when it does the render is about to be wrong in a way no error would otherwise
    reveal.
    """
    if declared == reported:
        return None
    return (f"the graph is wired for a {declared} job, but the service wrote a {reported} brief. "
            "The brief and the wiring disagree, so the render would come out wrong in a way that "
            "looks like a model problem. Check which sockets you filled: a picture in first frame "
            "is the first frame of the video, and a picture in picture 1 is something the shot "
            "should contain.")


def translate_path(path: str, from_prefix: str, to_prefix: str) -> str:
    """Rewrite a path from ComfyUI's view of the filesystem to the service's view.

    This exists because a path is not a file. ComfyUI on Windows writes a reference to
    C:\\ComfyUI\\temp\\ref.png; a service running in WSL or a container looks at the very same bytes
    through /mnt/c/ComfyUI/temp/ref.png and cannot open the Windows spelling. Both are correct and
    neither program can work the other one out, so the mapping is stated once by whoever set the two
    of them up.

    Empty prefixes mean no translation, which is right whenever both halves see one filesystem.
    """
    if not from_prefix or not to_prefix:
        return path
    norm = path.replace("\\", "/")
    src = from_prefix.replace("\\", "/").rstrip("/")
    if not norm.lower().startswith(src.lower()):
        return path
    return to_prefix.rstrip("/") + norm[len(src):]


# --------------------------------------------------------------------------- sending the bytes

def upload_limits(server: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """What this service accepts as an upload, asked of it rather than assumed.

    Read for two facts, both of which turn a long wait into an immediate sentence. Whether the
    service takes uploads at all: one that does not, and cannot see ComfyUI's folder either, has no
    way to receive media and the person needs telling now rather than after nine transfers. And the
    size ceiling, so a file over it is refused here, before the bytes are spent finding out.
    """
    status, body = _request(server, "/v1/capabilities", timeout=timeout)
    if status != 200 or not isinstance(body, dict):
        raise ServiceError(
            f"the OpenH3-IR service at {server} could not say what it accepts: HTTP {status}. It "
            "answered, so it is running; queue again, and if it keeps happening restart it.")
    assets = body.get("assets")
    if not isinstance(assets, dict) or not assets.get("uploads"):
        # One message for two causes, because they have one shape here and the reader cannot tell
        # them apart from the outside: a service started with H3IR_UPLOAD_MAX_BYTES at 0 publishes
        # `uploads: false`, and one older than this node pack publishes no assets block at all.
        raise ServiceError(
            f"the OpenH3-IR service at {server} cannot open ComfyUI's folder and will not take the "
            "files sent to it, so there is no way to get your media to it. Either it was started "
            "with H3IR_UPLOAD_MAX_BYTES set to 0, in which case set that to the largest attachment "
            "it should take, or it is older than this node pack, in which case update it: run git "
            "pull in the OpenH3-IR checkout, then restart h3ir serve. A prompt with nothing in the "
            "tray works either way.")
    return assets


def _put_file(server: str, path: str, sha256: str, label: str, *,
              timeout: float) -> tuple[int, Any]:
    """PUT one file's bytes, streamed. Returns (status, decoded body), errors included.

    Streamed rather than read into memory: the files this exists for are video, and holding one in
    memory to send it is the difference between a clip that uploads and a ComfyUI that dies. urllib
    reads a file object in blocks when the length is stated, so the length is stated.
    """
    size = os.path.getsize(path)
    req = urllib.request.Request(
        _url(server, f"/v1/assets/{sha256}"), method="PUT",
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(size),
                 "Accept": "application/json"})
    try:
        with open(path, "rb") as fh:
            req.data = fh
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, _decode(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, _decode(e.read().decode("utf-8", "replace"))
    except socket.timeout as e:
        raise ServiceError(
            f"sending {label} to the OpenH3-IR service at {server} did not finish within "
            f"{timeout:.0f}s. A large reference takes as long as the link between the two machines "
            "takes. Raise the timeout on an OpenH3-IR Setup node.") from e
    except urllib.error.URLError as e:
        # MEASURED: a connection that breaks WHILE the body is going out arrives here too, not as a
        # bare OSError, because urllib wraps everything `send` raises into a URLError. Read as "the
        # service is not there" that produced the confidently wrong advice to queue again, for a file
        # the service had in fact just refused. The errno is the difference and it is worth reading.
        broken = getattr(e.reason, "errno", None) in (errno.EPIPE, errno.ECONNRESET,
                                                      errno.ESHUTDOWN)
        if broken:
            raise ServiceError(
                f"the OpenH3-IR service at {server} closed the connection while {label} was going "
                "out, which is what it does when it will not take a file: either the file is larger "
                "than it accepts, or it has no room left for it. Its console output has the reason "
                "it gave. Queueing again will do the same thing.") from e
        raise ServiceError(
            f"cannot reach an OpenH3-IR service at {server} to send it your media ({e.reason}). It "
            "answered a moment ago, so it may have restarted; queue again.") from e


def upload_asset(server: str, path: str, sha256: str, label: str, *,
                 timeout: float = 600.0, max_bytes: int = 0) -> int:
    """Send one attachment's bytes and return how many there were.

    Named by content, so this is safe to repeat and cheap to repeat: a service that already holds
    these bytes says so and takes nothing. `label` is the tray slot's own name, because every
    message below is about a file the person chose and they think of it by where they dropped it.
    """
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise ServiceError(
            f"{label} cannot be read to send it to the service ({type(e).__name__}: {e}). The file "
            "was there when the graph was queued, so it has been moved or deleted since. Drop it on "
            "that slot again.") from e
    if max_bytes and size > max_bytes:
        raise ServiceError(
            f"{label} is {_mb(size)} and the OpenH3-IR service at {server} accepts at most "
            f"{_mb(max_bytes)} for one file. Raise H3IR_UPLOAD_MAX_BYTES where the service runs, or "
            "put a shorter or more compressed version of it on that slot. Nothing was sent.")
    status, body = _put_file(server, path, sha256, label, timeout=timeout)
    return _upload_reply(status, body, label=label, server=server, sha256=sha256, size=size)


def _upload_reply(status: int, body: Any, *, label: str, server: str, sha256: str,
                  size: int) -> int:
    """What the service said about the bytes it was sent, in the words of whoever sent them."""
    det = _detail(body)
    code = det.get("code", "")
    if status in (200, 201):
        # Read back rather than assumed. The service answers with the name it filed the bytes under,
        # and a name that is not the one asked for means the two sides disagree about which file this
        # is -- after which the brief would be written about one file and the render conditioned on
        # another, with nothing to say so.
        got = body.get("sha256") if isinstance(body, dict) else None
        if got and got != sha256:
            raise ServiceError(
                f"the service filed {label} under {str(got)[:12]} and this node sent it as "
                f"{sha256[:12]}. The two disagree about which file this is, so nothing further was "
                "asked of it. This is a defect in OpenH3-IR rather than something in your graph.")
        return int(det.get("bytes") or (body.get("bytes") if isinstance(body, dict) else 0) or size)
    if status == 413 or code == "asset-too-large":
        raise ServiceError(
            f"the OpenH3-IR service at {server} refused {label} for being too large: "
            f"{_sentence(det.get('message', ''))} It is {_mb(size)}.")
    if status == 507 or code == "upload-store-full":
        raise ServiceError(
            f"the OpenH3-IR service at {server} has no room to keep {label}: "
            f"{_sentence(det.get('message', ''))} Nothing in your graph is wrong.")
    if code == "asset-digest-mismatch":
        raise ServiceError(
            f"{label} changed while it was being sent to the service, so what arrived was not the "
            "file this graph measured. That happens when something else is still writing it. Wait "
            "for that to finish and queue again.")
    if code == "asset-name-not-a-digest":
        raise ServiceError(
            f"the service refused the name this node gave {label}. That name is a hash of the "
            "file's own bytes, computed here, so this is a defect in OpenH3-IR rather than "
            "something in your graph.")
    if status in (404, 405):
        raise ServiceError(
            f"the OpenH3-IR service at {server} has no way to receive files: PUT /v1/assets "
            f"answered HTTP {status}. It is older than this node pack. Update it on the machine it "
            "runs on: run git pull, then restart h3ir serve.")
    raise ServiceError(
        f"the OpenH3-IR service at {server} would not take {label}: HTTP {status}: "
        f"{str(det.get('message') or body)[:300]}")


def compile_with_media(*, server: str, written: list[tuple[str, str, str, dict[str, Any]]],
                       sizing: str, transcripts: dict[str, str], timeout: float,
                       brief: dict[str, Any], sha_of: Any,
                       comfy_root: str) -> tuple[dict[str, Any], str]:
    r"""Compile, getting the media to the service whichever of the two ways it can take.

    Paths first, always, because where they work they are strictly better: nothing is copied, the
    service opens the very file the user dropped, and a 200 MB clip costs nothing to hand over. The
    catch is that a path is not a file. ComfyUI on Windows writes C:\ComfyUI\temp\ref.png while a
    service in WSL sees /mnt/c/ComfyUI/temp/ref.png, and neither program can work out the other's
    spelling, so the plausible ones are offered in turn and the service confirms one by actually
    opening the file. A guess that is never checked is the silent-failure trap; this one is checked
    on every run.

    Running out of spellings is not a dead end any more. It means the service cannot see ComfyUI's
    disk at all, which is what a service on another machine looks like from here, and the media is
    sent to it instead. A service that refuses paths outright says so in its first reply, and then
    not even the second spelling is tried.

    This lives here rather than on the node because nothing in it needs a canvas: `comfy_root` is the
    one fact only ComfyUI knows, and it arrives as an argument. Everything else is the service
    protocol, which is what this module is for and what makes it testable against a real service with
    no ComfyUI in the process.
    """
    candidates = path_candidates(comfy_root)
    last: ServiceError | None = None
    for prefix in candidates:
        assets = plan_assets(written, sizing, comfy_root, prefix)
        payload = build_payload(assets=assets, transcripts=transcripts, **brief)
        try:
            body = compile_brief(server, payload, timeout=timeout)
            return body, handoff_note(
                prefix=(prefix if prefix and prefix != comfy_root else ""))
        except ServiceError as e:
            if not send_the_bytes(e):
                raise
            last = e
            if e.code == SEND_THE_BYTES:
                break
    # Only reachable once an attachment has failed to resolve, and an attachment is the only thing
    # that can fail that way: with an empty tray there is nothing to resolve, and the first attempt
    # above either worked or raised something this does not catch.
    return _compile_from_uploads(server=server, written=written, sizing=sizing,
                                 transcripts=transcripts, timeout=timeout, brief=brief,
                                 sha_of=sha_of, tried=candidates, why=last)


def _compile_from_uploads(*, server, written, sizing, transcripts, timeout, brief, sha_of,
                          tried, why) -> tuple[dict[str, Any], str]:
    """Compile against media the service holds itself, sending it whatever it turns out to lack.

    Asked first and sent second, which is the whole reason this is affordable. A brief naming its
    attachments by content hash comes back either as the brief or as the list of hashes the service
    does not hold, so re-queueing a graph whose clip has not changed spends one request and no bytes
    at all, and a file travels once rather than once per queue.

    One retry and no more. A file that has to be sent twice inside one queue is a service dropping
    uploads as fast as they arrive, and looping on that would spend somebody's evening re-sending a
    clip into a full disk instead of telling them the disk is full.
    """
    assets = plan_uploaded_assets(written, sizing, sha_of)
    payload = build_payload(assets=assets, transcripts=transcripts, **brief)
    sent: list[tuple[str, int]] = []
    try:
        try:
            body = compile_brief(server, payload, timeout=timeout)
        except ServiceError as absent:
            if not absent.missing:
                # Two very different failures share this branch and used to share one message. The
                # service having no way to take the files at all is a delivery problem and gets the
                # whole story. Anything else means the service HAS the media and is refusing the
                # request on its own terms -- a still attached as a clip, more references than H3 has
                # sockets -- and burying that under a paragraph about path spellings sends the reader
                # to fix the one thing that is not wrong.
                if send_the_bytes(absent):
                    raise _nowhere_to_put_it(absent, tried=tried, why=why) from absent
                raise
            sent = send_the_missing(server, written, sha_of, absent.missing, timeout=timeout)
            try:
                body = compile_brief(server, payload, timeout=timeout)
            except ServiceError as again:
                if not again.missing:
                    raise
                raise ServiceError(
                    f"the OpenH3-IR service at {server} dropped this graph's media straight after "
                    f"it was sent: {again} Its store of uploaded files is full, or it keeps them "
                    "for too short a time. Raise H3IR_UPLOAD_STORE_BYTES or H3IR_UPLOAD_TTL_HOURS "
                    "where the service runs, and queue again.") from again
    except ServiceError as e:
        raise in_the_users_words(e, written, sha_of) from e
    names = {name for name, _n in sent}
    held = tuple(dict.fromkeys(name for name, _k, _p, _x in written if name not in names))
    return body, handoff_note(sent=tuple(sent), held=held)


def in_the_users_words(error: ServiceError, written: list[tuple[str, str, str, dict[str, Any]]],
                       sha_of: Any) -> ServiceError:
    """The same failure with the tray's own labels where the service could only name a hash.

    MEASURED against a live service on another machine, with the commonest remote mistake there is --
    a still dropped on a clip slot: "0f7a5659754169c6... was attached as kind: video, and its bytes
    are a image file", followed by this pack's own "check the file in the tray slot the message
    names". It names no slot. It cannot: an uploaded attachment IS its content hash over there, which
    is the right name for a store and the wrong one for a person with nine references.

    Both sides hash the same bytes, so the translation is exact rather than a guess -- the same
    property the report already relies on to put slot labels on the service's manifest. The whole
    token is replaced, not the hash inside it, or a store path would come back as
    `/state/uploads/0f/picture 1`.
    """
    text = str(error)
    for name, _kind, path, _extra in written:
        prefix = sha_of(path)[:12]
        if prefix in text:
            text = re.sub(r"\S*" + prefix + r"\S*", lambda _m, n=name: n, text)
    if text == str(error):
        return error
    return ServiceError(text, error.code, error.missing)


def _nowhere_to_put_it(absent: ServiceError, *, tried, why) -> ServiceError:
    """The failure when the service can neither open ComfyUI's folder nor be sent the files.

    In practice that is one service: one too old to know what an uploaded attachment is. It was sent
    a request naming its media by content hash, ignored the field it does not have, and answered that
    the asset has no path -- which is also the only way a request carrying no paths at all can
    produce a complaint about one.

    Both facts go in the message, because they are two different fixes and a reader who is told only
    one of them goes off to fix whichever they were told about.
    """
    return ServiceError(
        "the media in this graph could not reach the OpenH3-IR service. It cannot open ComfyUI's "
        f"folder: {why if why else 'no spelling of it worked'}. It would not take the files "
        f"sent to it either: {absent}\n\nThat last reply is what a service older than this node pack "
        "gives: it was handed an attachment by content hash and asked for a path instead, because "
        "the version it is running has no way to be sent a file. Update it on the machine it runs on: "
        "run git pull in the OpenH3-IR checkout, then restart h3ir serve. If instead it runs beside "
        "ComfyUI, give it read access to ComfyUI's folder, spelled one of these ways: "
        + ", ".join(repr(c) for c in tried)
        + ". A prompt with nothing in the tray works either way.")


def send_the_missing(server: str, written: list[tuple[str, str, str, dict[str, Any]]], sha_of: Any,
                     missing: tuple[str, ...] | list[str], *,
                     timeout: float) -> list[tuple[str, int]]:
    """Send exactly the files the service asked for, and nothing it already has.

    The service's own list in its own order, because it is the one that knows. Every hash in it
    should be a file this graph named, and one that is not is refused rather than skipped: it would
    mean the two sides disagree about what this request contains, and a brief written about media the
    render never receives is the failure with no symptom.
    """
    limits = upload_limits(server, timeout=min(float(timeout), 60.0))
    cap = int(limits.get("upload_max_bytes") or 0)
    by_sha: dict[str, tuple[str, str]] = {}
    for name, _kind, path, _extra in written:
        by_sha.setdefault(sha_of(path), (name, path))

    sent: list[tuple[str, int]] = []
    for sha in dict.fromkeys(missing):
        if sha not in by_sha:
            raise ServiceError(
                f"the service asked for a file this graph never named ({str(sha)[:12]}), so the two "
                "disagree about what is attached. This is a defect in OpenH3-IR rather than "
                "something in your graph.")
        label, path = by_sha[sha]
        # On the console because it is the only place this wait can explain itself: the first queue
        # against a service on another machine moves every reference across the network.
        print(f"[OpenH3-IR] sending {label} to {server}")
        sent.append((label, upload_asset(server, path, sha, label, timeout=float(timeout),
                                         max_bytes=cap)))
    return sent


def _mb(n: int) -> str:
    """Bytes as a person would say them, because 536870912 is not a size anybody reads."""
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024 ** 3):.1f} GB"
    if n >= 1024 * 1024:
        return f"{n / (1024 ** 2):.0f} MB"
    return f"{max(1, n // 1024)} KB"


# --------------------------------------------------------------------------- the machine's files

def merge_model_options(native: list[str], gguf: list[str]) -> list[str]:
    """One combo listing both builds of the same folder, sorted so a checkpoint's variants land
    next to each other.

    `unet_gguf` and `clip_gguf` are not different places: ComfyUI-GGUF registers them over the very
    same directories with a `.gguf` extension filter, so the GGUF build of a checkpoint sits beside
    the safetensors build and the only thing that tells them apart is the extension. Merging the two
    views is therefore one control describing one fact, and every state of it is valid.

    The GGUF half comes from that pack's own registered list and is never globbed off the disk. A
    file listed with no loader behind it is the plausible-and-wrong option this pack exists to
    prevent, so an install without the pack is offered nothing.
    """
    seen: dict[str, str] = {}
    for name in list(native) + list(gguf):
        seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=lambda s: (s.lower(), s))


def is_gguf(name: str) -> bool:
    """The file is the toggle. A boolean beside a filename would be a second source of truth for
    one fact, with two of its four states wrong and nothing on the canvas to resolve them."""
    return name.strip().lower().endswith(".gguf")


def unet_loader_for(name: str) -> str:
    return LOADER_GGUF_UNET if is_gguf(name) else LOADER_NATIVE_UNET


def clip_loader_for(name: str) -> str:
    return LOADER_GGUF_CLIP if is_gguf(name) else LOADER_NATIVE_CLIP


# The words H3's own two checkpoint families put in their filenames. Used for one thing only: saying
# out loud that a pick looks like the other family. Never for choosing a file, because which file the
# user meant is not something a filename can answer.
REFERENCE_FAMILY = "ref2va"
FRAMES_FAMILY = "fl2va"


def family_warning(chosen: str, *, frames_job: bool) -> str:
    """A plain warning when the picked checkpoint's own name says it is the other H3 family.

    The two slots are easy to swap and both files load: a reference checkpoint on a first-and-last
    frame job renders something plausible with nothing on screen to say why it ignored the frames.
    So the filename is read, and only where it decides the question. A name carrying the other
    family's word and not this one's is evidence; a name carrying neither is not, and a name carrying
    both cannot be read. Silence in those cases, because a guess dressed as a warning teaches people
    to ignore warnings.

    It never blocks the render. Which file is right is the user's call and a renamed file is still
    the file they meant.
    """
    wanted, other = ((FRAMES_FAMILY, REFERENCE_FAMILY) if frames_job
                     else (REFERENCE_FAMILY, FRAMES_FAMILY))
    name = (chosen or "").lower()
    if other not in name or wanted in name:
        return ""
    job = "a first and last frame job" if frames_job else "a reference or text job"
    slot = "fl2va model" if frames_job else "ref2va model"
    return (f"{chosen} names H3's {other} family, and this graph is {job}, which runs on the "
            f"{wanted} checkpoint. Check the {slot} field on the Setup node: it will render either "
            "way, and it will be wrong in a way nothing on screen explains.")


# --------------------------------------------------------------------------- the bundles

def setup_bundle(*, server: str, reference_model: str, frames_model: str, text_encoder: str,
                 video_vae: str, audio_vae: str, weight_dtype: str,
                 timeout_s: int) -> dict[str, Any]:
    """One socket carrying the eight facts that describe a machine rather than a shot.

    Every file in it was picked by a person. Nothing here searches, prefers a build or fills a gap:
    which file was meant is not a question a filename can answer, and a node that answered it anyway
    was choosing for the user without saying so.
    """
    address = (server or "").strip()
    if not address:
        raise ServiceError(
            "the service field is empty. Put the address the OpenH3-IR service listens on, for "
            f"example {DEFAULT_SERVER}, or delete this node to use that address.")
    if not address.startswith(("http://", "https://")):
        raise ServiceError(
            f"the service address {address!r} has no scheme, so nothing can be requested from it. "
            f"Write it in full, for example {DEFAULT_SERVER}.")
    if weight_dtype not in WEIGHT_DTYPES:
        raise ServiceError(f"weight_dtype {weight_dtype!r} is not one of {WEIGHT_DTYPES}.")
    return {"server": address.rstrip("/"), "reference_model": reference_model,
            "frames_model": frames_model, "text_encoder": text_encoder, "video_vae": video_vae,
            "audio_vae": audio_vae, "weight_dtype": weight_dtype, "timeout_s": int(timeout_s)}


def _detail(body: Any) -> dict[str, Any]:
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else {}


def _sentence(text: str) -> str:
    """Somebody else's message, closed off so the next sentence does not run into it.

    The service's messages are written for a person and most of them end in a full stop, but not all,
    and `...reports it in its own terms rather than yours That is about the file` is the sort of seam
    that makes a careful message read like a generated one.
    """
    text = str(text).strip()
    return text if not text or text[-1] in ".!?:" else text + "."


def compile_brief(server: str, payload: dict[str, Any], *, timeout: float = 600.0) -> dict[str, Any]:
    """POST the brief, then fetch the render fields. Returns the /prompt body plus the brief id.

    Every branch below is a failure a user hit or can hit, turned into a sentence that says what to
    do next. The status codes and payload shapes come from the service's own route handlers.
    """
    status, body = _request(server, "/v1/briefs", payload=payload, timeout=timeout)

    if status == 422:
        det = _detail(body)
        code = det.get("code", "")
        if code in ("asset-no-path", "asset-missing"):
            raise ServiceError(
                f"the service could not read an attachment: {det.get('message', code)}. "
                "ComfyUI and the service are looking at the same file through different paths, for "
                "example /mnt/c/ComfyUI-Production where ComfyUI itself says C:\\ComfyUI-Production. "
                "The node tries the plausible spellings itself and this is what is left when none of "
                "them opened. If the service runs on another machine entirely it cannot open "
                "ComfyUI's files at all, and only text-only prompts will work; if it runs beside "
                "ComfyUI, give it read access to ComfyUI's folder.", PATH_MAY_BE_WRONG)
        if code == "asset-not-uploaded":
            # Usually not read by anyone: `missing` names the files to send, the caller sends them
            # and asks again, and that is how a service on another machine works at all. So this
            # states the fact and nothing about what happens next, which is the caller's business
            # and not something this branch can know.
            raise ServiceError(
                "the OpenH3-IR service does not hold the media this graph named: "
                f"{_sentence(det.get('message', code))} Nothing in your graph is wrong.",
                "", tuple(det.get("missing") or ()))
        if code == "asset-paths-disabled":
            # The service saying "do not send me paths, send me bytes". Marked so the caller does
            # exactly that instead of stopping, which is why this sentence is rarely read.
            raise ServiceError(
                f"the OpenH3-IR service does not open files from its own disk: "
                f"{_sentence(det.get('message', code))} Your media is sent to it instead.",
                SEND_THE_BYTES)
        if code in ("asset-name-not-a-digest", "asset-two-sources"):
            # Both describe a request this node cannot write: it names every uploaded file by a hash
            # it computed, and it never states a path and a hash for one file. So the person reading
            # this cannot fix it in their graph, and saying so is the whole message.
            raise ServiceError(
                "the service refused how this node described one of your files: "
                f"{_sentence(det.get('message', code))} That description is written here rather than "
                "by you, so it is a defect in OpenH3-IR rather than something in your graph. A "
                "prompt with nothing in the tray still works.")
        if code == "asset-unreadable":
            # The file was found and opened, and could not be used. A different spelling of the path
            # cannot help, so this must NOT carry the retry marker. The analyser writes these for a
            # person to read and already names the file and what is wrong with it, so it is passed
            # through whole and only the socket-side action is added.
            raise ServiceError(
                f"the service opened your attachment and could not use it: "
                f"{_sentence(det.get('message', code))} That is about the file rather than about the wiring: a "
                "different path would fail the same way. Check the file in the tray slot the message "
                "names on the OpenH3-IR Media node.")
        if code == "unknown-field":
            # The two halves at different versions, caught at the wire instead of before it. The
            # node asks `GET /v1/contract` first and refuses there with the tray slot named, so
            # reaching this branch means the service is old enough to publish no contract at all --
            # and old enough that something this graph sends did not exist when it was built. The
            # service's own message names the field and says what to install, so it is passed
            # through whole and only the location is added.
            raise ServiceError(
                f"the OpenH3-IR service at {server} is older than this node pack and refused "
                f"something this graph sent: {_sentence(det.get('message', code))} Update it where "
                "it runs, or take off whatever in the graph fills that field. Nothing was rendered "
                "with part of your request missing, which is what refusing it buys.")
        if code == "malformed-request":
            # This node writes the request, so its shape is never the user's doing. Same answer as
            # the two `asset-` codes below that describe a request this pack cannot write: say that
            # it is ours, and say what still works.
            raise ServiceError(
                f"the service could not read the request this node wrote: "
                f"{_sentence(det.get('message', code))} That request is written here rather than by "
                "you, so it is a defect in OpenH3-IR rather than something in your graph. A prompt "
                "with nothing in the tray may still work.")
        if code in REFUSED_AS_ASKED:
            # The compiler read the request, understood it, and will not write it as stated. Every
            # one of these names the specific contradiction in words the person can act on -- which
            # slot says nothing about who it replaces, which shot count does not fit the duration --
            # so the message is passed through whole and this only says whose decision it was and
            # where the fix is.
            #
            # One branch for the class rather than eleven for the members, because the answer is the
            # same for all of them and eleven paraphrases of one sentence is eleven things to keep
            # true. The list is what makes the branch reachable, and `contract.json`
            # publishes the codes so a new one added over there fails a test over here instead of
            # falling through to a sentence that says nothing.
            raise ServiceError(
                "the compiler will not write this brief as asked: "
                f"{_sentence(det.get('message', code))} Nothing is wrong with the service or the "
                "connection; this is about what the graph is asking for, and the sentence above "
                "says which part. Change it and queue again.")
        if code == "over-capacity":
            raise ServiceError(
                f"more references than H3 has sockets for: {_sentence(det.get('message', code))} Nothing "
                "was silently dropped, because which reference matters is your call. Unplug what you can "
                "spare: H3 takes nine pictures, three clips and three standalone sounds.")
        problems = body.get("errors") if isinstance(body, dict) else None
        if problems:
            lines = "\n  ".join(f"{p.get('rule')}: {p.get('message')}" for p in problems)
            raise ServiceError(
                "the request contradicts itself, so no brief was written:\n  " + lines)
        raise ServiceError(f"the service rejected the request: {det.get('message') or body}")

    if status == 503:
        det = _detail(body)
        if det.get("code") == "analysis-tool-missing":
            # A missing binary is the service host's problem and shares the 503 shape with an LLM
            # outage. Reading the shape alone and printing the LLM message would send someone to fix
            # an endpoint that is working, which is the wrong-message failure this pack exists to
            # avoid. The analyser already names the tool and how to install it, so it is passed
            # through and only the location is added.
            raise ServiceError(
                f"the OpenH3-IR service at {server} cannot read your attachment because a tool it "
                f"needs is not installed where it runs: {_sentence(det.get('message', ''))} This is about the "
                "machine running the service, not about your graph. A text-only prompt still works.")
        raise ServiceError(
            f"the OpenH3-IR service at {server} is running, but the language model endpoint it "
            f"writes with is not answering: {det.get('message', '')}. That endpoint is "
            "yours, set as H3IR_LLM_URL where the service runs. Bring it up and queue again.")

    if status == 502:
        raise ServiceError(
            "the language model endpoint answered with an error rather than a brief: "
            f"{_detail(body).get('message', '')}. Nothing is wrong with this node or the graph.")

    if status == 500:
        raise ServiceError(
            "the service failed internally while writing the brief, which is a bug in the service "
            "rather than in your request. Its console output has the detail.")

    if status != 201:
        raise ServiceError(f"unexpected reply from {server}: HTTP {status}: "
                           f"{str(body)[:400]}")

    if not isinstance(body, dict) or not body.get("id"):
        raise ServiceError(f"the service accepted the brief but returned no id: {str(body)[:300]}")

    brief_id = body["id"]

    if body.get("status") == "needs_input":
        q = body.get("question") or {}
        asked = q.get("question") or "it needs one decision from you"
        default = body.get("default_if_unanswered")
        raise ServiceError(
            f"the compiler needs one thing settled before it can write this brief: {asked} "
            + (f"It would otherwise assume: {default}. " if default else "")
            + "State it in the intent text, for example by saying whether an attached image is the "
              "opening frame or a reference for how something looks.")

    status2, prompt_body = _request(server, f"/v1/briefs/{brief_id}/prompt", timeout=timeout)
    if status2 != 200 or not isinstance(prompt_body, dict):
        raise ServiceError(
            f"the brief compiled as {brief_id}, but reading its render fields failed with HTTP "
            f"{status2}. The service may have restarted between the two calls; queue again.")

    out = dict(prompt_body)
    out["brief_id"] = brief_id
    out["degraded"] = body.get("status") == "degraded"
    out["fallback_reason"] = body.get("fallback_reason") or ""
    # What the compiler says it actually directed with. Carried over so the node can check it
    # against what it SENT -- see `director_note`. Two fields that must agree is the check this
    # project has found four silent faults with, and it costs one string.
    out["director_used"] = ((body.get("plan") or {}).get("director") or "")
    return out


def director_note(sent: bool, used: str) -> str:
    """A sentence when direction was sent and the compiler says none was applied, or "".

    The one thing a director can do silently: a profile travels, something upstream drops it, and
    the brief compiles perfectly with no direction at all. The service says so in its diagnostics
    and the node cannot see those -- but it does not need to. It knows it sent something, the record
    says what was used, and disagreement between the two is the whole failure. Two fields that must
    agree is the check this project has found four silent faults with, and it costs one string.
    """
    if not sent:
        return ""
    # The record's own shape: "director: <name>", and "director: none" when there was none.
    got = (used or "").split(";")[0].replace("director:", "").strip()
    if got and got.lower() != "none":
        return ""
    return ("the direction on the Director node was not applied and the brief was written with no "
            "direction at all. The service may be an older version that does not read it.")


def render_fields(prompt_body: dict[str, Any]) -> tuple[str, int, int, int, str]:
    """Pull out the five things a graph needs, refusing to invent any of them.

    A missing field here would otherwise become a plausible default, and a plausible default is how
    someone renders at the wrong length and blames the model.
    """
    prompt = prompt_body.get("prompt")
    frames = prompt_body.get("frames")
    canvas = prompt_body.get("canvas")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ServiceError("the service returned an empty prompt, so there is nothing to render.")
    if not isinstance(frames, int) or frames <= 0:
        raise ServiceError(f"the service returned no usable frame count (got {frames!r}).")
    if not (isinstance(canvas, (list, tuple)) and len(canvas) == 2):
        raise ServiceError(f"the service returned no usable canvas (got {canvas!r}).")
    width, height = int(canvas[0]), int(canvas[1])

    sizings = {w.get("sizing") for w in prompt_body.get("wiring") or [] if w.get("sizing")}
    sizing = sizings.pop() if len(sizings) == 1 else "match"
    return prompt, width, height, int(frames), sizing


# --------------------------------------------------------------------------- the report

# Every report line is `label` in a 15 character column and then the fact, so the facts line up in
# whatever monospace box the user reads them in.
_COL = 15


def line(label: str, text: str) -> str:
    """One report line, wrapped with its continuations under the fact rather than under the label."""
    return textwrap.fill(text, width=94, initial_indent=label.ljust(_COL),
                         subsequent_indent=" " * _COL)


def length_notes(asked_seconds: float, frames: int) -> list[str]:
    """What the length really came out as, and whether it left H3's trained band.

    Neither is a warning. A long render is a choice, not a fault, and `note` is the register this
    report already uses for choices. Both are here because the surface deliberately allows lengths
    the model was never trained on, and a surface that allows something has to say what it did.
    """
    out: list[str] = []
    asked_frames = max(5, round(float(asked_seconds) * FPS))
    if asked_frames != frames:
        out.append(line("asked for", f"{float(asked_seconds):.1f}s, snapped up onto the frame grid"))
    real = frames / FPS
    if frames > TRAINED_MAX_FRAMES:
        out.append(line("note", f"{real:.3f}s is past H3's trained band, which ends at "
                                f"{TRAINED_MAX_FRAMES} frames, "
                                f"{TRAINED_MAX_FRAMES / FPS:.3f}s. It still renders, it is "
                                "untested, and it costs VRAM and time in proportion."))
    elif frames < TRAINED_MIN_FRAMES:
        out.append(line("note", f"{real:.3f}s is below H3's trained band, which starts at "
                                f"{TRAINED_MIN_FRAMES} frames, "
                                f"{TRAINED_MIN_FRAMES / FPS:.3f}s. It still renders, and it is "
                                "untested."))
    return out


def handoff_note(*, prefix: str = "", sent: tuple[tuple[str, int], ...] = (),
                 held: tuple[str, ...] = ()) -> str:
    """One report line saying how the service came by the media, or nothing when there is no story.

    Worth a line because the two ways cost differently and only one of them is visible from the
    canvas. Somebody who waited on a slow first queue and a fast second one should be able to read
    why, and somebody whose service quietly stopped sharing a disk should not have to guess that the
    files are now travelling over the network.
    """
    if sent or held:
        parts = []
        if sent:
            parts.append(f"{len(sent)} sent to it, {_mb(sum(n for _, n in sent))}: "
                         + ", ".join(name for name, _ in sent))
        if held:
            parts.append("already there: " + ", ".join(held))
        return line("media", "the service cannot see ComfyUI's folder, so the files went to it. "
                    + "; ".join(parts) + ".")
    if prefix:
        return line("paths", f"the service reads ComfyUI's folder at {prefix}")
    return ""


def precision_ignored_note() -> str:
    return line("note", "weight_dtype does not apply to a GGUF checkpoint, which carries its "
                        "own quantisation, so it was ignored.")


def bindings_by_content(written: list[tuple[str, str, str, dict[str, Any]]],
                        sha_of: Any) -> dict[str, list[str]]:
    """slot labels per file hash, in the order the slots were numbered.

    A list rather than one name, because two slots can legitimately hold the same file and the
    service addresses files by content, so they are the same file. FOUND BY RENDERING: keyed by hash
    alone, the second slot overwrote the first and one of the two labels printed as `?`. Both are
    real and both get their label, assigned in the order the service numbered them.
    """
    out: dict[str, list[str]] = {}
    for name, _kind, path, _extra in written:
        out.setdefault(sha_of(path), []).append(name)
    return out


def report(prompt_body: dict[str, Any], *, server: str, sizing_conflict: bool,
           asked_seconds: float | None = None,
           bindings: dict[str, list[str]] | None = None) -> str:
    """A short human-readable account of what came back, for a preview node or the console.

    It exists because the interesting facts are the ones a user cannot see in a STRING socket: which
    mode was inferred, whether the length they asked for was moved, and which socket became which
    picture label.

    `bindings` maps a file's sha256 to the tray slots holding it. The service hashes the same bytes,
    so the attachment block below is the service's own manifest with the user's own slot labels put
    back on it: slot, then label, then the input on H3's node it rides. The two sides speak the same
    words, and a label landing on the wrong slot becomes visible instead of becoming a render nobody
    can explain.
    """
    frames = prompt_body.get("frames") or 0
    canvas = prompt_body.get("canvas") or [0, 0]
    lines = [
        line("mode", str(prompt_body.get("mode", "?"))),
        line("length", f"{frames} frames, {frames / FPS:.3f}s at {FPS} fps"),
    ]
    if asked_seconds is not None:
        lines.extend(length_notes(asked_seconds, frames))
    lines.extend([
        line("canvas", f"{canvas[0]}x{canvas[1]}"),
        line("render hash", str(prompt_body.get("render_hash", ""))[:16]),
        line("brief id", f"{prompt_body.get('brief_id', '')}   on {server}"),
    ])

    wiring = prompt_body.get("wiring") or []
    # One label is accepted as well as a list of them, because a bare string is iterable and
    # `list("music")` is five slots called m, u, s, i and c.
    by_sha = {sha: ([names] if isinstance(names, str) else list(names))
              for sha, names in (bindings or {}).items()}
    if wiring:
        lines.append("attachments")
        for w in wiring:
            sha = str(w.get("sha256", ""))
            waiting = by_sha.get(sha) or []
            slot_name = waiting.pop(0) if waiting else "?"
            parts = [f"  {slot_name:<14} ->  {w.get('label')}", str(w.get("wiring"))]
            if w.get("retention"):
                parts.append(str(w["retention"]))
            # Only where it means something. A sound has no pixel area to fit, and the service's own
            # default lands "match" on every entry, so printing it for audio is noise that reads as a
            # setting somebody chose.
            if w.get("sizing") and w.get("kind", "image") == "image":
                parts.append(f"sizing={w['sizing']}")
            parts.append(f"sha256={sha[:12]}")
            lines.append("  ".join(parts))
    for names in by_sha.values():
        for slot_name in names:
            lines.append(line("note", f"the brief does not mention what is in {slot_name}, so it "
                                      "reached the service and was left out. Nothing in the render "
                                      "will refer to it."))
    if sizing_conflict:
        lines.append(line("note", "the references do not all want the same sizing. The H3 node has "
                                  "one ref_image_size for all of them, so pick per the list "
                                  "above."))
    if prompt_body.get("degraded"):
        lines.append(line("note", "the brief is a fallback, not a written one: "
                                  f"{prompt_body.get('fallback_reason')}"))
    return "\n".join(lines)


def inputs_fingerprint(*parts: Any) -> str:
    """Stable hash of everything that can change the brief, for ComfyUI's IS_CHANGED.

    The compiler is seeded, so the same inputs produce the same brief. That makes content hashing
    the honest cache key: re-queueing an unchanged graph should not spend another model call, and
    changing any input, including an image's pixels, must re-compile.
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()


# --------------------------------------------------------------------------- the director bundle


def director_bundle(*, profile: str) -> dict[str, Any] | None:
    """What the Director node hands down its socket: a name and a paragraph, or nothing.

    The panel writes one JSON string into one widget, exactly as the media tray does, so a saved
    workflow and a rendered video carry the direction with them and the panel can be deleted without
    changing what any graph does. This is the only thing that reads that string.

    **Nothing about the writing is refused here.** The cap on how long a direction may be belongs to
    the compiler, which is where the ask is assembled and where the sentence about it is written; a
    second copy of that number in this file would be a second opinion about somebody's paragraph.
    What IS refused is text that is not the shape the panel writes, because that is a fact about the
    widget rather than a judgement about the writing.
    """
    text = (profile or "").strip()
    if not text or text == "{}":
        return None
    try:
        data = json.loads(text)
    except ValueError:
        raise ServiceError(
            "the Director node's field is not readable. The panel keeps it as JSON with two keys, "
            'for example {"name": "My noir", "notes": "The camera stays still ..."}. If you edited '
            "it by hand, fix the quoting; if you did not, delete the node and add it "
            "again.") from None
    if not isinstance(data, dict):
        raise ServiceError(
            f"the Director node's field holds a {type(data).__name__}, and it has to be an object "
            "with a name and notes in it.")
    notes = str(data.get("notes") or "").strip()
    if not notes:
        return None
    return {"name": str(data.get("name") or "").strip() or "Custom", "notes": notes}
