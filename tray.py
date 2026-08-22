"""The media tray and the @ prompt, as data: the two things a user types, with nothing drawn.

Both live in one module because they share one vocabulary. A slot's LABEL is exactly what an @
mention names, so the rules for a label and the rules for a mention are one set of rules, and a
change to either that forgot the other would leave a mention nobody can write or a label nothing can
reach.

Nothing here imports ComfyUI, numpy or torch. The tray is JSON in an ordinary widget and the prompt
is plain text in an ordinary widget; the panel, the chips and the pills are a *rendering* of those
two strings and never a second source of truth. Everything the nodes refuse about a tray or a prompt
is refused from here, which is why every refusal can be read in a test instead of clicked.

Three decisions in here are worth knowing before changing anything.

The JSON stores the service's own role token, not the words the panel shows. The words are user
interface and may be reworded; `frame_anchor_first` is a wire format and may not. Storing the words
would make a saved workflow break the day a label reads better.

Labels are compared case-insensitively everywhere: `Car` and `car` cannot both exist, and `@Car`
finds `car`. One rule rather than two, because two labels that differ only in case are a trap and a
mention that resolves by a rule the uniqueness check does not share is a worse one.

The plain text under the sugar is small on purpose. A mention is `@label`. A locked line is
`@speaks("the exact words")`. Everything else is prose. There is no third construct, no escape and
no nesting, because every one of those is a thing the user has to be taught before the box works.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .h3ir_client import ServiceError, expected_mode

# H3's own ceilings per kind, and the tray's own ceiling on files. The per-kind numbers are the
# service's published `max_assets`; the total is the tray's, and a video's separated soundtrack
# spends one of them because it is a second file the service opens and a second label H3 receives.
KINDS = ("picture", "video", "sound")
CAPACITY = {"picture": 9, "video": 3, "sound": 3}
MAX_FILES = 12

# What a new slot is called before anybody renames it. The panel assigns these; this side only
# validates, so the two halves cannot disagree about a label -- whatever the panel wrote is what
# gets checked. `sound` slots are labelled `audio` because that is the word the brief uses for
# them: H3's tokenizer emits `<Audio j>`.
LABEL_PREFIX = {"picture": "picture", "video": "video", "sound": "audio"}

# What a file IS, in the user's words, and the role each one means. The same grammar the Footage and
# Sound nodes used for their job dropdowns, now once per slot, which is what makes the setting and
# the style of a picture expressible at all: they were unreachable while a picture's role was fixed
# by the socket it arrived on.
PICTURE_ROLES = {
    "something in the shot": "subject",
    "the setting": "environment",
    "a style to copy": "style",
    # The two that are statements about another slot: a picture set to either of these says what
    # happens to the clip in the tray that is set to "edit it", so both read as a sentence about
    # that clip rather than about the piece. Ordered here between what a picture SHOWS and the
    # three that say a picture IS a frame or a plan, because that is what they are: the same
    # subject, with a job inside somebody else's footage. The service refuses either of them with
    # a sentence when no clip is being edited, rather than quietly demoting it to `subject`.
    "add it to the clip": "placed_subject",
    "replace the one in the clip": "replacement_subject",
    "first frame": "frame_anchor_first",
    "last frame": "frame_anchor_last",
    "storyboard": "storyboard",
}
VIDEO_ROLES = {
    "copy what is in it": "subject",
    "copy how it is shot": "structure",
    "edit it": "edit_source",
    "carry on from it": "continuation_source",
}
SOUND_ROLES = {
    "play it": "bgm",
    "match its style": "music_style",
    "cut to its beat": "beat_reference",
    "sound effect": "sfx",
    "voice to match": "voice_timbre",
}
ROLES = {"picture": PICTURE_ROLES, "video": VIDEO_ROLES, "sound": SOUND_ROLES}
# The first entry of each table, which is the ordinary reading of dropping that kind of file in: a
# picture is something in the shot, a clip is something to copy, a track is something to play. A
# slot that names no role asks for what a slot has always asked for.
DEFAULT_ROLE = {kind: next(iter(table.values())) for kind, table in ROLES.items()}
WORDS_FOR_ROLE = {kind: {role: words for words, role in table.items()}
                  for kind, table in ROLES.items()}

# The two roles that say a picture IS a frame of the video rather than something it contains, and
# the one that says a picture plans the shots and never appears. Named here because three refusals
# and the job decision all read them.
ANCHOR_FIRST = "frame_anchor_first"
ANCHOR_LAST = "frame_anchor_last"
ANCHORS = (ANCHOR_FIRST, ANCHOR_LAST)
BOARD = "storyboard"
# The one role that takes somebody's place, and so the one that has somebody to name.
REPLACEMENT = "replacement_subject"
# Both roles that are statements about the clip being edited rather than about the piece. The
# compiler refuses either one when no clip is set to "edit it", which is why the two read as a
# sentence about that clip. Named as a pair because the checks that hold this pack against the
# compiler read them that way: that both can be picked at all, and that the words on both mention
# the clip. Nothing branches on it; `REPLACEMENT` above is still the one with somebody to name.
ABOUT_THE_EDIT = ("placed_subject", REPLACEMENT)

# What happens to a clip's own soundtrack. `off` sends none of it, `paired` sends it as this clip's
# soundtrack, which is the pairing H3 labels immediately before the clip, and `alone` sends it as a
# sound in its own right. Three states of one control, exactly as the reference loader presents it.
SOUNDTRACKS = ("off", "paired", "alone")

# A label is letters, digits and dashes, and it has to carry at least one letter or digit so that
# `-` is not a name. `speaks` is reserved: `@speaks(` is the one other thing an @ can start, so a
# slot by that name would make the sentence ambiguous where it matters most.
LABEL = re.compile(r"^[A-Za-z0-9-]+$")
RESERVED = ("speaks",)


@dataclass(frozen=True)
class Slot:
    """One tray slot. The file is ComfyUI's own annotated form, `subfolder/name [input]`, which is
    what its file helpers take and what every upload widget in ComfyUI already stores."""

    kind: str
    label: str
    role: str
    file: str
    note: str = ""
    transcript: str = ""
    soundtrack: str = "off"
    # Who this picture takes over from, in the user's own words, and only on a picture set to
    # "replace the one in the clip". Free text rather than a list of the clip's people, because
    # nothing in this chain can enumerate them: the service reads three sampled frames of a clip,
    # so somebody can be in none of them and walk in later. The person looking at the clip knows.
    replaces: str = ""

    @property
    def words(self) -> str:
        """What this slot IS, in the words the panel shows, for a message or a report line."""
        return WORDS_FOR_ROLE[self.kind].get(self.role, self.role)


# --------------------------------------------------------------------------- reading the tray

def auto_label(kind: str, taken: list[str] | tuple[str, ...] = ()) -> str:
    """The name a new slot gets: the kind's word and the lowest free number.

    Here as well as in the panel because it is the one rule both halves have to agree on, and a rule
    stated twice is a rule that drifts. The panel writes the label; this is what it writes.
    """
    used = {t.strip().lower() for t in taken}
    prefix = LABEL_PREFIX[kind]
    for n in range(1, CAPACITY[kind] + 1):
        if f"{prefix}{n}" not in used:
            return f"{prefix}{n}"
    return f"{prefix}{CAPACITY[kind] + 1}"


def check_label(label: str, seen: dict[str, str]) -> str:
    """One label against the rules, returning it. `seen` maps lowercased label to the slot it named
    already, so the duplicate message can say which slot took the name."""
    if not label:
        raise ServiceError(
            "a slot in the media tray has no name, and its name is what an @ mention in the prompt "
            "reaches it by. Name it on the OpenH3-IR Media node, for example "
            f"{auto_label('picture')}.")
    if not LABEL.match(label) or not re.search(r"[A-Za-z0-9]", label):
        raise ServiceError(
            f"{label!r} cannot name a slot: a name is letters, digits and dashes, with at least one "
            "letter or digit, because it is written straight into the prompt after an @. Rename the "
            "slot on the OpenH3-IR Media node, for example the-car.")
    if label.lower() in RESERVED:
        raise ServiceError(
            f"{label!r} cannot name a slot, because @speaks( is how a spoken line is written in the "
            "prompt and @speaks would then mean two things in one sentence. Rename the slot on the "
            "OpenH3-IR Media node.")
    if label.lower() in seen:
        raise ServiceError(
            f"two slots in the media tray are both called {label!r}, so @{label} in the prompt "
            "cannot say which one it means. Names are compared without case, so Car and car are "
            "the same name. Rename one of them on the OpenH3-IR Media node.")
    return label


def _one_slot(entry: dict, seen: dict[str, str]) -> Slot:
    kind = str(entry.get("kind") or "").strip()
    if kind not in KINDS:
        raise ServiceError(
            f"a slot in the media tray says it holds {kind!r}, and a slot holds one of: "
            + ", ".join(KINDS) + ". The panel on the OpenH3-IR Media node writes this field.")
    file = str(entry.get("file") or "").strip()
    label = check_label(str(entry.get("label") or "").strip(), seen)
    if not file:
        raise ServiceError(
            f"the slot called {label!r} in the media tray has no file in it, so there is nothing "
            "for the prompt to refer to. Drop a file on it, or remove the slot.")
    role = str(entry.get("role") or "").strip() or DEFAULT_ROLE[kind]
    if role not in WORDS_FOR_ROLE[kind]:
        raise ServiceError(
            f"{label!r} is a {kind} and it says it is {role!r}, which is not one of the things a "
            f"{kind} can be. A {kind} is one of: " + ", ".join(ROLES[kind])
            + ". Pick one on the OpenH3-IR Media node. Written down, in the tray's own text, those "
              "are: " + ", ".join(ROLES[kind].values()) + ".")
    soundtrack = str(entry.get("soundtrack") or "off").strip()
    if soundtrack not in SOUNDTRACKS:
        raise ServiceError(
            f"{label!r} says its soundtrack is {soundtrack!r}, and a soundtrack is one of: "
            + ", ".join(SOUNDTRACKS) + ".")
    if soundtrack != "off" and kind != "video":
        raise ServiceError(
            f"{label!r} is a {kind} and it asks for its soundtrack to be sent, which only a clip "
            "has. Set it to off, or the setting would be quietly ignored.")
    transcript = str(entry.get("transcript") or "").strip()
    if transcript and kind != "sound":
        raise ServiceError(
            f"{label!r} is a {kind} and it carries the words in a recording, which only a sound "
            "has. Nothing in this chain can hear a picture, and the words would be quietly "
            "dropped, so this is an error rather than a no-op.")
    replaces = str(entry.get("replaces") or "").strip()
    if replaces and role != REPLACEMENT:
        raise ServiceError(
            f"{label!r} says it replaces {replaces!r} and it is set to "
            f"{WORDS_FOR_ROLE[kind].get(role, role)!r}. Only a picture set to "
            f"{WORDS_FOR_ROLE['picture'][REPLACEMENT]!r} takes somebody's place, so those words "
            "would be quietly dropped. Change what it is on the OpenH3-IR Media node, or clear "
            "them.")
    return Slot(kind=kind, label=label, role=role, file=file,
                note=str(entry.get("note") or "").strip(), transcript=transcript,
                soundtrack=soundtrack, replaces=replaces)


def read_tray(text: str | None) -> list[Slot]:
    """The tray widget's text as slots, in the order they sit in the tray.

    An empty field is an empty tray rather than an error, because a Media node someone has just
    added is a tray with nothing in it and that is a legal graph: no media at all is text-only,
    which is what this pack did before a tray existed.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ServiceError(
            f"the media tray's state is not readable ({e.msg}, at character {e.pos}). The panel on "
            "the OpenH3-IR Media node writes this field as a list of slots; if it was edited by "
            "hand, undo that. Nothing was sent.") from None
    if not isinstance(entries, list):
        raise ServiceError(
            "the media tray's state is not a list of slots, so no slot could be read from it. The "
            "panel on the OpenH3-IR Media node writes this field.")
    seen: dict[str, str] = {}
    slots: list[Slot] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ServiceError(
                f"the media tray holds {entry!r} where a slot should be. A slot names its kind, its "
                "label and its file.")
        slot = _one_slot(entry, seen)
        seen[slot.label.lower()] = slot.label
        slots.append(slot)
    over = [(kind, n, CAPACITY[kind]) for kind, n in
            ((k, sum(1 for s in slots if s.kind == k)) for k in KINDS) if n > CAPACITY[kind]]
    if over:
        raise ServiceError(
            "the media tray holds more than H3 has room for: "
            + "; ".join(f"{n} {kind} slots and H3 takes {cap}" for kind, n, cap in over)
            + ". Remove what you can spare on the OpenH3-IR Media node: which reference matters is "
              "yours to decide, so nothing is dropped for you.")
    files = file_count(slots)
    if files > MAX_FILES:
        raise ServiceError(
            f"the media tray sends {files} files and it holds {MAX_FILES}. A clip whose soundtrack "
            "is sent counts as two, because it is two files the service opens and two labels H3 "
            "receives. Remove a slot, or set a clip's soundtrack to off.")
    return slots


def file_count(slots: list[Slot]) -> int:
    """Files the tray sends. A clip whose soundtrack is separated sends two."""
    return sum(2 if s.kind == "video" and s.soundtrack != "off" else 1 for s in slots)


# ------------------------------------------------------- the order everything gets numbered in

def in_numbering_order(slots: list[Slot]) -> list[Slot]:
    """Every slot in the order the service numbers its kind: pictures, clips, then sounds.

    The frame anchors are ranked ahead of the other pictures because the service does the same and
    the runtime does the same: `MiniMaxH3ImageToVideo` appends the first frame and then the last, so
    <Picture 1> is the opening plate whatever order the tray lists them in. `sorted` is stable, so
    every other picture keeps the order the user put it in, which is the order they will read in the
    report.
    """
    rank = {ANCHOR_FIRST: 0, ANCHOR_LAST: 1}
    pictures = sorted((s for s in slots if s.kind == "picture"), key=lambda s: rank.get(s.role, 2))
    return (pictures + [s for s in slots if s.kind == "video"]
            + [s for s in slots if s.kind == "sound"])


def asset_order(slots: list[Slot]) -> list[tuple[Slot, str]]:
    """Every file the tray sends, as (slot, part), in the one order that makes the labels true.

    `part` is "file" or "soundtrack". A clip's separated soundtrack follows its clip, which is what
    makes the service's <Audio j> and the runtime's ref_video_audio_N the same soundtrack: the
    runtime emits a paired soundtrack's label immediately before its clip's.

    THE control on the whole tray. This list is read twice -- once to tell the service what to
    number and once to fill H3's own sockets -- and deriving it twice is how <Picture 3> in the
    brief becomes ref_image_1 in the graph, which describes one file while handing the model
    another.
    """
    out: list[tuple[Slot, str]] = []
    for slot in in_numbering_order(slots):
        out.append((slot, "file"))
        if slot.kind == "video" and slot.soundtrack != "off":
            out.append((slot, "soundtrack"))
    return out


def soundtrack_name(slot: Slot) -> str:
    """What the report calls a clip's separated soundtrack. Its own name, so a line about it cannot
    be read as a line about the clip."""
    return f"{slot.label} sound"


def job_for(slots: list[Slot]) -> str:
    """Which H3 task the tray describes, decided by what the slots say they are.

    The same function the sockets used to feed, now fed by roles: a picture set to first frame IS
    the opening frame, and a picture set to something in the shot is a reference. Reading the answer
    off the tray means the brief and the graph cannot disagree about which job this is.
    """
    return expected_mode(
        any(s.role == ANCHOR_FIRST for s in slots),
        any(s.role == ANCHOR_LAST for s in slots),
        sum(1 for s in slots if s.kind == "picture" and s.role not in ANCHORS and s.role != BOARD),
        sum(1 for s in slots if s.kind == "video"),
        sum(1 for s in slots if s.kind == "sound"),
        any(s.role == BOARD for s in slots))


def exclusivity(slots: list[Slot]) -> None:
    """The refusals H3's own two routes force, keyed off what each slot says it is.

    All three were socket-shaped before and are role-shaped now, and all three are refused here
    rather than sent: they are about the graph, not about the brief, so a model call spent on one
    would buy a document describing files H3 is never handed.
    """
    anchors = [s for s in slots if s.role in ANCHORS]
    if not anchors:
        return
    for role, which in ((ANCHOR_FIRST, "first frame"), (ANCHOR_LAST, "last frame")):
        same = [s.label for s in anchors if s.role == role]
        if len(same) > 1:
            raise ServiceError(
                f"{len(same)} slots are set to {which}: " + ", ".join(same)
                + f". A video has one {which}, so only one picture can be it. Change the others on "
                  "the OpenH3-IR Media node.")
    board = [s.label for s in slots if s.role == BOARD]
    if board:
        raise ServiceError(
            f"a storyboard cannot ride along with a first or last frame. {board[0]} plans the "
            f"shots and {anchors[0].label} is a frame of the video, and a frame job runs on H3's "
            "fl2va model, whose node takes the two frames and no reference picture at all: the "
            "brief would lay the shots out from your sketch and H3 would never receive it. On the "
            "OpenH3-IR Media node, change the sketch or change the frame.")
    others = [s for s in slots if s.role not in ANCHORS]
    if others:
        one = others[0]
        raise ServiceError(
            "this is two different jobs at once. " + f"{anchors[0].label} is set to "
            f"{anchors[0].words}, which says a picture IS a frame of the video, and {one.label} is "
            f"set to {one.words}, which says a file is something the shot should contain. H3 does "
            "one or the other, and its fl2va model takes no reference picture, clip or sound at "
            "all, so the brief would name your file and H3 would never receive it. Change one of "
            "them on the OpenH3-IR Media node.")


def _and_list(names: list[str]) -> str:
    """`@a`, then `@a and @b`, then `@a, @b and @c`. One joining rather than two, because this
    sentence is written on both sides of the pack and two joinings would drift."""
    if len(names) < 2:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + f" and {names[-1]}"


# The half of the sentence both halves of this pack say. The panel writes it the moment the tray
# becomes ambiguous, and `check_swaps` writes it again when the job runs; the shared words are
# pinned from Python by tests/test_panel_agrees_with_the_tray.py so the two cannot drift.
SAY_WHO = "replace someone in the clip, so each has to say who"


def check_swaps(slots: list[Slot]) -> None:
    """Refuse a tray where two pictures take somebody's place and one of them does not say whose.

    One replacement is never ambiguous: whatever it stands in for, only one picture is asking, and
    the compiler binds it to the one figure of its kind. Two are ambiguous -- and the ambiguity is
    NOT the count. Nothing in this chain knows how many people a clip holds: the service reads
    three sampled frames of it, so a figure can be in none of them and walk in later, and any rule
    resting on a head count would be guessing. What is missing is which figure each picture stands
    in for, and the words on the picture are the only thing that can say.

    So the job stops here rather than rendering a swap that picks whichever figure came first.
    Refused before a byte is uploaded and before a model call is spent, like every other rule about
    the wiring, and refused from Python rather than only in the panel because a tray can be written
    by another program or edited by hand and nobody saw the panel.
    """
    swapping = [s for s in slots if s.role == REPLACEMENT]
    if len(swapping) < 2:
        return
    silent = [s.label for s in swapping if not s.replaces]
    if not silent:
        return
    # What is missing comes FIRST, and that is not a style choice. The panel says this on a line
    # one slot wide that ends in an ellipsis, and measured on the canvas it cuts about forty
    # characters -- which, with the general complaint in front, was exactly the part naming the
    # picture that still has to answer. The whole sentence is in the line's tooltip either way.
    raise ServiceError(
        f"{_and_list([f'@{lb}' for lb in silent])} "
        + ("does not say who it replaces." if len(silent) == 1
           else "do not say who they replace.")
        + f" {_and_list([f'@{s.label}' for s in swapping])} "
        + f"{'both' if len(swapping) == 2 else 'all'} {SAY_WHO}. Say who on the OpenH3-IR Media "
        "node, in your own words, for example: the man in the plaid shirt.")


# --------------------------------------------------------------------------- the @ prompt

# A mention is @ and a label. Word characters and dashes are matched rather than the stricter label
# rule, so `@some_thing` is read as a mention nobody named and refused by name, instead of being
# read as `@some` followed by the text `_thing`, which would send a sentence the user never wrote.
MENTION = re.compile(r"@([\w-]+)", re.UNICODE)
SPEAKS_OPEN = '@speaks("'
SPEAKS_CLOSE = '")'


def parse_intent(text: str | None) -> list[tuple[str, str]]:
    """The prompt as pieces: ("text", s), ("mention", label) or ("spoken", the exact words).

    The words of a spoken line run from `@speaks("` to the first `")`, so a line may contain a quote
    mark: `@speaks("he said "no"")` closes at the `")` and keeps the inner marks. What it may not
    contain is the two characters `")` together, and there is no escape for that, because an escape
    is a thing every user of the box would have to be taught to avoid one line nobody writes.

    Nothing is edited. The words between the quotes arrive here exactly as typed, mark for mark and
    space for space, because the compiler checks the document it wrote against this string and a
    field that tidied a capital or a space would break the one guarantee it exists for.
    """
    src = str(text or "")
    pieces: list[tuple[str, str]] = []
    plain: list[str] = []

    def flush() -> None:
        if plain:
            pieces.append(("text", "".join(plain)))
            plain.clear()

    i = 0
    while i < len(src):
        at = src.find("@", i)
        if at < 0:
            plain.append(src[i:])
            break
        plain.append(src[i:at])
        if src.startswith(SPEAKS_OPEN, at):
            start = at + len(SPEAKS_OPEN)
            end = src.find(SPEAKS_CLOSE, start)
            if end < 0:
                raise ServiceError(
                    'a spoken line in the prompt was opened with @speaks(" and never closed. A '
                    'line is written @speaks("the exact words") and the words come back in the '
                    "brief word for word. Close it, or delete it.")
            words = src[start:end]
            if not words.strip():
                raise ServiceError(
                    'there is an empty @speaks("") in the prompt, which asks for a line with no '
                    "words in it. Type the words, or delete it.")
            flush()
            pieces.append(("spoken", words))
            i = end + len(SPEAKS_CLOSE)
            continue
        m = MENTION.match(src, at)
        if not m:
            plain.append("@")
            i = at + 1
            continue
        flush()
        pieces.append(("mention", m.group(1)))
        i = m.end()
    flush()
    return pieces


def mentioned_labels(text: str | None) -> list[str]:
    """Every label the prompt mentions, in the order it mentions them, duplicates included."""
    return [value for kind, value in parse_intent(text) if kind == "mention"]


def spoken_lines(text: str | None) -> list[str]:
    """Every locked line in the prompt, in the order it says them."""
    return [value for kind, value in parse_intent(text) if kind == "spoken"]


@dataclass(frozen=True)
class Resolved:
    """What the service is actually sent, and what the report has to say about it."""

    intent: str
    spoken: tuple[str, ...]
    # label -> the words it became in the intent, in the order the prompt mentions them.
    became: tuple[tuple[str, str], ...]
    unmentioned: tuple[str, ...]


def resolve_intent(text: str | None, slots: list[Slot]) -> Resolved:
    """The prompt with its mentions and pills turned into the sentence the compiler reads.

    A mention becomes the slot's note, which is the words a person wrote about that file, or its
    label when there is no note. That is the half of the binding the writer reads as prose; the
    other half is `plan_assets` putting the label on the front of the note it sends, so the same
    words appear on both sides and the compiler ties them together.

    A locked line becomes its own words in quotes, in place. Quoted speech inside the sentence is
    what this pack always supported and the position of the line in the sentence is real
    information: stripping the pill out would tell the writer that a line is said and not where.
    The words also go to the service's `dialogue` field, which is what makes them enforceable.

    A mention nobody named is refused. Not because the compiler could not cope -- it would weave the
    unmentioned files in anyway -- but because the user wrote a name and meant a file, and the two
    plausible outcomes of guessing are the wrong file and a sentence with a stray word in it.
    """
    by_label = {s.label.lower(): s for s in slots}
    out: list[str] = []
    spoken: list[str] = []
    became: list[tuple[str, str]] = []
    hit: set[str] = set()
    for kind, value in parse_intent(text):
        if kind == "text":
            out.append(value)
        elif kind == "spoken":
            spoken.append(value)
            out.append(f'"{value}"')
        else:
            slot = by_label.get(value.lower())
            if slot is None:
                raise ServiceError(_no_such_label(value, slots))
            words = slot.note or slot.label
            hit.add(slot.label.lower())
            became.append((slot.label, words))
            out.append(words)
    return Resolved(intent="".join(out), spoken=tuple(spoken), became=tuple(became),
                    unmentioned=tuple(s.label for s in slots if s.label.lower() not in hit))


def _no_such_label(name: str, slots: list[Slot]) -> str:
    if not slots:
        return (f"the prompt mentions @{name}, and there is no media tray for it to name. Add an "
                "OpenH3-IR Media node, drop a file on it and wire its media output into this "
                "node's media socket, or remove the @ from the sentence.")
    return (f"the prompt mentions @{name}, and the media tray has no slot called that. It has: "
            + ", ".join(s.label for s in slots)
            + ". Rename a slot on the OpenH3-IR Media node, or fix the mention. If you did not mean "
              "a mention at all, put a space after the @.")


def mention_notes(resolved: Resolved, slots: list[Slot]) -> list[str]:
    """The report's account of the prompt: what each mention became, and what nothing mentioned.

    The second half is the one worth printing. An unmentioned file is not an error -- the compiler
    weaves it in and it renders -- so nothing else in the chain would ever say that a file the user
    loaded is not referred to by the sentence they wrote.
    """
    from .h3ir_client import line

    out: list[str] = []
    for label, words in resolved.became:
        out.append(line("@" + label, f"became {words!r} in the sentence"))
    for label in resolved.unmentioned:
        slot = next(s for s in slots if s.label == label)
        out.append(line("note", f"the prompt never mentions @{label}, so it was sent as "
                                f"{slot.words} for the compiler to place. Write @{label} in the "
                                "sentence to say where it goes."))
    return out


def note_for(slot: Slot) -> str:
    """The note the service is told, which carries the label so the compiler can bind the file to
    the words the sentence uses for it.

    A note of "the man in the leather jacket" on a slot called carguy is sent as
    `carguy: the man in the leather jacket`, and the sentence says "the man in the leather jacket".
    Both halves of the pair are in the request, so the writer has the words and the tie between
    them rather than one or the other.
    """
    return f"{slot.label}: {slot.note}" if slot.note else slot.label
