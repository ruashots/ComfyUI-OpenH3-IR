"""What this pack believes about the compiler, and what it does when the compiler disagrees.

The pack and the compiler are installed separately and drift apart on purpose: a user can have any
version of one against any version of the other, and neither can make the other update. So the pack
carries a SNAPSHOT of the contract it was built against, asks the compiler for its live one, and
compares them.

**It compares against what this graph is actually sending, not against everything the pack can do.**
That distinction is the whole reason an old compiler keeps working. A pack that knows about
`replaces` talking to a compiler that does not is perfectly fine for every brief that replaces
nobody, and refusing those would be this pack breaking working setups to protect a feature they are
not using. So the stop conditions read the payload; the rest is a line in the report.

Three answers and nothing in between:

    stop      the compiler cannot do what this graph is asking, and going ahead renders the wrong
              thing. Refused here, before any media is uploaded, naming the fix.
    note      something differs and this graph does not depend on it. One sentence in the report.
    silence   nothing differs, or nothing that this graph or this pack can see.

**Nothing here reads the compiler's source and nothing imports `h3ir`.** The snapshot is a generated
JSON file beside this one, written by `h3ir contract` at build time, and the live contract arrives as
an ordinary dict. Where that dict came from is `Half`'s business -- `GET /v1/contract` for a service
and `h3ir.contract.contract()` for the package in this Python. Both are the same comparison, which is
the point of taking a dict.

**`Half` is also how every message below knows what to call the other half.** The same difference has
two different fixes depending on where the compiler is, and a sentence telling a ComfyUI user to
restart a service they never started is the wrong-message failure this pack exists to prevent. So the
comparison is written once and the naming comes from the half it is comparing against.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from . import compiler as _compiler
from . import tray as T
from .h3ir_client import fetch_contract

# The contract this pack was built against, as `h3ir contract` printed it. Read at import: it is a
# few kilobytes, it is packaged beside this file, and a pack that cannot read its own snapshot is
# broken in a way worth failing loudly at import rather than at queue time.
SNAPSHOT_PATH = pathlib.Path(__file__).with_name("contract.json")
SNAPSHOT: dict[str, Any] = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
BUILT_AGAINST: int = int(SNAPSHOT["contract_version"])

# The oldest release this pack can actually work against. Named so the "your service is older than
# this pack" message can say what to install instead of saying that something is wrong. This is a
# fact about the compiler's release history, not a preference, and it moves only when that history
# does.
#
# 0.3.0 was the first release to publish a contract at all, and for a while this said 0.3.0 for that
# reason. It never reached PyPI, and 0.4.0 is the first one that did. 0.4.0 also publishes contract
# version 2, which is what `contract.json` beside this file was built against, so a pack installing
# 0.3.0 would have met a mismatch on its first queue. Both facts point at the same number.
FIRST_PUBLISHING_RELEASE = "0.4.0"


class Half:
    """The compiler this graph is about to use: what to call it, how to ask it what it takes, and
    what a person does to change it.

    **One object rather than a flag, because every one of these differs and none of them is
    cosmetic.** A field the compiler does not understand is the same difference either way, and the
    fix is `pip install --upgrade` in ComfyUI's Python on one path and `git pull` plus a restart on
    somebody else's machine on the other. A reader handed the wrong one goes and fixes something
    that is not broken.

    `contract` is a callable rather than a value so that nothing asks a compiler this graph is not
    going to use. Reading the local package's contract while compiling over HTTP compares this
    machine's version to another machine's work and refuses graphs that are perfectly fine, and it
    is the kind of mistake that produces confident nonsense rather than an error.
    """

    def __init__(self, *, where: str, update: str, ask):
        self.where = where
        self.update = update
        self._ask = ask

    def contract(self) -> dict[str, Any] | None:
        """What this compiler says crosses between it and whatever drives it, or None when it is
        older than the release that publishes one. Never raises: a client fails on the request, not
        on the check."""
        return self._ask()

    def __repr__(self) -> str:                                # pragma: no cover - debugging only
        return f"Half({self.where!r})"


def the_compiler(server: str, *, timeout: float = 30.0) -> Half:
    """Which compiler this graph compiles with, decided by the one field that decides it.

    An address on the Setup node means the service at that address. An empty field means the
    `open-h3-ir` installed in the Python ComfyUI is running, which is the ordinary case and the whole
    point of the pack being an all-in-one.

    **There is no merging and no fallback between the two.** A graph whose compile quietly moved
    somewhere else would produce a brief nobody can account for, and a check that asked one compiler
    about a compile the other is doing would refuse working graphs. So this returns one, and it is
    the one that does the work.
    """
    address = (server or "").strip().rstrip("/")
    if address:
        return Half(
            where=f"the OpenH3-IR service at {address}",
            update=("Update open-h3-ir on the machine that service runs on, then restart "
                    "h3ir serve."),
            ask=lambda: fetch_contract(address, timeout=timeout))
    return Half(
        where="the open-h3-ir in ComfyUI's own Python",
        update=("Update it where ComfyUI runs, with that Python: python -m pip install --upgrade "
                f"'{_compiler.DISTRIBUTION}'."),
        ask=_compiler.installed_contract)


class Difference:
    """One thing the two halves disagree about, and whether it stops this graph.

    `stop` is a property of THIS difference against THIS payload, decided by `differences()`, not a
    property of the field or the role in the abstract. The same missing field is a stop for a graph
    that fills it and silence for a graph that does not.
    """

    def __init__(self, message: str, *, stop: bool = False):
        self.message = message
        self.stop = stop

    def __repr__(self) -> str:                                # pragma: no cover - debugging only
        return f"Difference({'stop' if self.stop else 'note'}: {self.message[:60]!r})"


# --------------------------------------------------------------------------- the comparison

def differences(live: dict[str, Any] | None, *, half: Half, asset_fields: tuple[str, ...] = (),
                brief_fields: tuple[str, ...] = (),
                roles: tuple[tuple[str, str], ...] = ()) -> list[Difference]:
    """Everything worth saying about the gap between this pack and the compiler it is talking to.

    `live` is the compiler's own contract, or None when it publishes none -- which is what an older
    release looks like from here and is a note rather than a failure.

    `half` is which compiler that was, and it is what every message below says out loud. The same
    difference has two fixes, one on each path, and naming the wrong one sends a reader to repair
    something that is working.

    `asset_fields`, `brief_fields` and `roles` are what THIS graph is about to send:
    `h3ir_client.payload_shape` computes them from the same functions that build the request, so
    they cannot describe a payload other than the one that goes out. `roles` is (kind, role) pairs
    in the wire's own words -- image, video, audio.
    """
    if live is None:
        return [Difference(
            f"{half.where} does not publish a contract, so nothing about it was checked. That "
            f"means it is older than open-h3-ir {FIRST_PUBLISHING_RELEASE}. Everything this graph "
            "uses that it also has will work; anything newer will be refused by name when it gets "
            f"there. {half.update} Then the two are checked before a queue instead.")]

    out: list[Difference] = []
    out += _fields_this_graph_needs(live, half, asset_fields, brief_fields)
    out += _roles_this_graph_needs(live, half, roles)
    out += _what_this_pack_cannot_reach(live, half)
    out += _what_this_pack_shows_wrongly(live, half)
    out += _limits_that_moved(live, half)
    return out


def _fields_this_graph_needs(live: dict[str, Any], half: Half, asset_fields: tuple[str, ...],
                             brief_fields: tuple[str, ...]) -> list[Difference]:
    """A key in the request that the compiler does not take. The one that renders the wrong thing.

    A field the compiler has never heard of is refused there with its own message, which is the
    backstop and works for every client. This is the same refusal before the upload, where the wait
    is nothing and the message can name the version to install.
    """
    out = []
    for where, sending, key in (("about an attachment", asset_fields, "asset_fields"),
                                ("about the piece", brief_fields, "brief_fields")):
        known = set(live.get(key) or ())
        if not known:
            continue
        for field in sending:
            if field in known:
                continue
            out.append(Difference(stop=True, message=(
                f"this graph says something {where} that {half.where} does not understand: "
                f"`{field}`. This node pack is newer than it, and it refuses a field it does not "
                "know rather than ignoring it, because a dropped field comes back as a brief that "
                f"looks right and describes something else. {half.update} (This pack was built "
                f"against contract {BUILT_AGAINST}, and it reports "
                f"{live.get('contract_version', '?')}.) Or take off whatever in the graph fills "
                "that field.")))
    return out


# The wire calls a picture an image; the panel calls it a picture. Every message below is read on a
# canvas, so it uses the tray's words -- and so does the vocabulary inside it: somebody set that slot
# from a dropdown that said "replace the one in an existing clip" and has never seen the word
# `replacement_subject`. The token is kept in brackets on the one that failed, because that is the
# string they would search for in the API documentation, and dropped everywhere else.
KIND_WORD = {"image": "a picture", "video": "a clip", "audio": "a sound"}
TRAY_KIND = {"image": "picture", "video": "video", "audio": "sound"}


def _in_the_panels_words(kind: str, role: str) -> str:
    """What the tray's own dropdown calls this job, or the raw token when it has no name for it."""
    return T.WORDS_FOR_ROLE.get(TRAY_KIND.get(kind, ""), {}).get(role, role)


def _roles_this_graph_needs(live: dict[str, Any], half: Half, roles: tuple[tuple[str, str], ...]
                            ) -> list[Difference]:
    """A slot set to a job the compiler has no name for.

    Refused before the media travels rather than after. The service refuses it too, and its message
    is good; what it cannot say is which tray slot to change, because by then a file is a content
    hash. The caller adds that.
    """
    known = live.get("roles") or {}
    if not known:
        return []
    out = []
    for kind, role in dict.fromkeys(roles):
        takes = known.get(kind) or []
        if not takes or role in takes:
            continue
        offer = ", ".join(f'"{_in_the_panels_words(kind, r)}"' for r in takes)
        out.append(Difference(stop=True, message=(
            f'a slot in the tray is set to "{_in_the_panels_words(kind, role)}" (`{role}`), and '
            f"{half.where} has no such job. This node pack is newer than it. {half.update} Or set "
            f"that slot to one of the jobs it does take for {KIND_WORD.get(kind, kind)}: "
            f"{offer}.")))
    return out


def _what_this_pack_cannot_reach(live: dict[str, Any], half: Half) -> list[Difference]:
    """A job the compiler takes and this pack cannot offer. The drift that already shipped once.

    `placed_subject` and `replacement_subject` reached the compiler, the service and the tray's
    Python while the panel kept offering six picture roles, so the feature could be used over HTTP
    and not from the node it was built for. Nothing failed, because nothing was watching this
    direction. A note rather than a stop: the graph in front of the user is fine, and what they have
    lost is a choice they never saw.
    """
    mine = SNAPSHOT.get("roles") or {}
    theirs = live.get("roles") or {}
    out = []
    for kind, takes in theirs.items():
        extra = [r for r in takes if r not in (mine.get(kind) or [])]
        if extra:
            # The raw tokens, and here that is right: these are jobs this pack has no word for,
            # because it has never heard of them.
            job = "job" if len(extra) == 1 else "jobs"
            out.append(Difference(
                f"{half.where} takes {len(extra)} {job} for {KIND_WORD.get(kind, kind)} that this "
                f"node pack cannot offer: {', '.join(extra)}. The compiler is newer than the pack. "
                "Update the pack to reach them from the tray; nothing in this graph is wrong."))
    return out


def _what_this_pack_shows_wrongly(live: dict[str, Any], half: Half) -> list[Difference]:
    """The panel's own copies: the seven directions and the camera vocabulary.

    Never a stop, and the reason is worth knowing. The Director node sends the PROSE that is in its
    box, so what compiles is always exactly what the canvas showed -- a drifted copy cannot render
    the wrong thing. What it can do is teach: somebody starts from this pack's James Cameron and the
    compiler's own documentation, CLI and API describe a different one, and somebody writing their
    own direction reads a camera move the renderer has no name for.
    """
    mine = SNAPSHOT.get("digests") or {}
    theirs = live.get("digests") or {}
    out = []
    if theirs.get("directors") and theirs["directors"] != mine.get("directors"):
        out.append(Difference(
            f"the seven directions this node pack ships are not the ones {half.where} publishes. "
            "Whichever is newer, what compiles is always the text in the Director node's own box, "
            "so this render is exactly what the canvas showed. Run `h3ir directors` against that "
            "compiler to read its versions."))
    if theirs.get("camera_moves") and theirs["camera_moves"] != mine.get("camera_moves"):
        out.append(Difference(
            f"the camera vocabulary this node pack shows is not the one {half.where} publishes. "
            "The list is H3's own closed table, so a direction written against the wrong one names "
            "moves the renderer cannot make. Update whichever half is older."))
    return out


def _limits_that_moved(live: dict[str, Any], half: Half) -> list[Difference]:
    """A ceiling or a list of choices that differs, said in the words the user reads on the node.

    Never a stop. Every one of these is a number a surface restates so it can refuse or offer
    something early, and being wrong about one costs a legal thing refused here or an illegal thing
    refused there -- both with a message -- rather than a render nobody can explain.
    """
    mine = SNAPSHOT.get("limits") or {}
    theirs = live.get("limits") or {}
    if not theirs:
        return []
    said = {
        "director_notes_max_chars": "the longest direction it accepts",
        "max_pinned_shots": "the most shots a graph may pin",
        "fps": "the frame rate it renders at",
        "trained_frames": "the frame range H3 was trained on",
        "max_assets": "how many references of each kind it takes",
        "aspects": "the shapes it offers",
        "creativity": "the settings of the creativity dial",
        "effort": "the effort settings",
        "sizing": "how a reference may be sized",
        "dialogue_languages": "the languages it lists for dialogue",
    }
    out = []
    for key, phrase in said.items():
        if key not in theirs or key not in mine or theirs[key] == mine[key]:
            continue
        out.append(Difference(
            f"this node pack and {half.where} disagree about {phrase}: the pack shows "
            f"{_plain(mine[key])} and the compiler says {_plain(theirs[key])}. The compiler is what "
            "decides; the pack is what you pick from. Update whichever half is older."))
    return out


def _plain(value: Any) -> str:
    """A contract value written the way a sentence needs it rather than the way JSON does."""
    if isinstance(value, dict):
        return ", ".join(f"{k} {v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)
