"""The panel plans a drop before it uploads anything, and it plans by three tables it does not own.

Aiming a drop meant the browser had to answer questions it used to leave to the server: which kind
of slot this file belongs on, whether there is room for it, and what to say when there is not. Every
one of those is settled in Python -- `web_api.py` for the extensions and
`tray.py` for the capacities -- so the panel now restates three tables it must not be the
authority on. A restatement that drifts is what these catch.

The cost of drift is not symmetric, and neither are the assertions. An extension the panel takes and
the route refuses is one wasted round trip and a correct refusal from the authority, which is
survivable. A capacity the panel believes is larger than the tray's is a file uploaded into
ComfyUI's input folder, refused after the fact, and left there with nothing pointing at it -- which
is exactly the failure planning first was added to remove.

No node and no browser: this reads the shipped JavaScript as text and holds it against the Python
that governs it, the same way tests/test_panel_agrees_with_the_tray.py does. Every scan asserts it
found something first, because a regex that quietly stops matching is a test that passes forever.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from openh3ir import tray as T
from openh3ir import web_api as W

TRAY_JS = (pathlib.Path(__file__).resolve().parents[1]
           / "web" / "tray.js").read_text(encoding="utf-8")


def _js_object(name: str) -> dict:
    """One `const NAME = { ... };` from the panel, read as data.

    The panel writes its tables as JavaScript object literals with unquoted keys, single-level, of
    strings and arrays of strings. That is a subset of Python once the keys are quoted, so this
    quotes them and hands the rest to `ast.literal_eval` rather than trusting a regex to take the
    values apart.
    """
    m = re.search(rf"^const {name} = (\{{.*?\}});$", TRAY_JS, re.MULTILINE | re.DOTALL)
    assert m, f"{name} is no longer declared in the panel, so this comparison is blind"
    quoted = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*):", r'\1"\2":', m.group(1))
    return ast.literal_eval(quoted.replace("\n", " "))


# ------------------------------------------------------------------ which kind a file belongs on

def test_the_panel_sorts_files_by_the_table_the_route_refuses_by():
    """`EXTENSIONS` in tray.js is `EXTENSIONS` in web_api.py.

    The panel decides a dropped file's kind from its name so it can aim it at a slot and count it
    against that kind's capacity before uploading. The route decides the same thing from the same
    name and is the authority. An extension in one table and not the other is a file the panel
    aims at a slot the route will not put it in, or one the panel turns away that the tray takes.
    """
    declared = _js_object("EXTENSIONS")
    assert set(declared) == set(W.EXTENSIONS), (
        f"the panel sorts files into {sorted(declared)} and the route into "
        f"{sorted(W.EXTENSIONS)}")
    for kind, allowed in W.EXTENSIONS.items():
        assert declared[kind] == list(allowed), (
            f"{kind}: the route takes {list(allowed)} and the panel takes {declared[kind]}. "
            "web_api.py is the authority; tray.js restates it.")


def test_the_panel_refuses_an_unusable_file_in_the_route_s_own_words():
    """One refusal, written twice, and the two have to read the same.

    The panel now turns a file away without asking the server, so the sentence the user gets is the
    panel's. It is the route's sentence: same opening, same three lists in the same order, same
    word for a file with no extension at all.
    """
    m = re.search(r"function noKindFor\(name\) \{(.+?)\n\}", TRAY_JS, re.DOTALL)
    assert m, "the panel no longer has its own refusal for a file no slot takes"
    said = m.group(1)
    route = (pathlib.Path(W.__file__).read_text(encoding="utf-8")
             .split("if not kind:")[1].split("status=400)")[0])
    for piece in ("the tray takes no ", " file. ", "extensionless",
                  "Pictures: ", "Clips: ", "Sounds: "):
        assert piece in said, f"the panel's refusal no longer says {piece!r}"
        assert piece.strip() in route, (
            f"the route's refusal no longer says {piece!r}, so the panel is quoting a sentence "
            "that has moved on")
    for kind in ("picture", "video", "sound"):
        assert f"EXTENSIONS.{kind}.join" in said, (
            f"the panel's refusal no longer lists the {kind} extensions from the shared table, so "
            "it can name a set of extensions it does not actually accept")


# ------------------------------------------------------------------------- how much the tray holds

def test_the_panel_counts_the_same_room_the_tray_enforces():
    """`CAPACITY` and `MAX_FILES` in tray.js are the ones tray.py refuses by.

    These stopped being decoration when the panel began refusing a drop before uploading it. Too
    small and the panel turns away a file the tray would have taken. Too large and the file is
    uploaded into ComfyUI's input folder, refused once it is there, and left behind with nothing
    pointing at it, which is the whole reason the check moved in front of the upload.
    """
    declared = _js_object("CAPACITY")
    assert declared == T.CAPACITY, (
        f"tray.py holds {T.CAPACITY} and the panel counts {declared}")
    m = re.search(r"^const MAX_FILES = (\d+);$", TRAY_JS, re.MULTILINE)
    assert m, "MAX_FILES is no longer declared in the panel, so this comparison is blind"
    assert int(m.group(1)) == T.MAX_FILES, (
        f"tray.py sends at most {T.MAX_FILES} files and the panel counts to {m.group(1)}")


@pytest.mark.parametrize("kind", ["picture", "video", "sound"])
def test_the_panel_names_every_kind_the_tray_has_a_slot_for(kind):
    """`WORD` is what a refusal calls a kind, and there has to be one for each of them.

    The board heads its columns pictures, clips and sounds, so a refusal that says "video" names
    something the user cannot find on it. A kind missing from this table produces `undefined` in
    the middle of the sentence instead.
    """
    words = _js_object("WORD")
    assert set(words) == set(T.KINDS), (
        f"tray.py has slots for {sorted(T.KINDS)} and the panel has words for "
        f"{sorted(words)}")
    assert words[kind] and words[kind].strip() == words[kind]


# ----------------------------------------------------------------- the drop plan itself is honest

def test_room_is_judged_before_the_file_is_sent():
    """The order that keeps a refused file from being written to disk.

    The panel used to upload first and check afterwards, so a drop onto a full tray left the bytes
    in ComfyUI's input folder with no slot pointing at them. `plan` now runs over the whole batch
    before `land` sends anything, and `land` calls `upload` rather than the other way round.
    """
    plan = re.search(r"\n  plan\(items, aim\) \{(.+?)\n  \}\n", TRAY_JS, re.DOTALL)
    assert plan, "the panel no longer plans a drop, so nothing is decided before the upload"
    assert "this.refuseFor(projected" in plan.group(1), (
        "the plan no longer judges each file against the room the ones before it left")
    assert "this.upload(" not in plan.group(1) and "fetchApi" not in plan.group(1), (
        "planning a drop now sends something, so a file can again be written to disk and then "
        "refused")
    receive = re.search(r"\n  async receive\(files, aim\) \{(.+?)\n  \}\n", TRAY_JS, re.DOTALL)
    assert receive, "the panel no longer has one way in for files"
    assert receive.group(1).index("this.plan(") < receive.group(1).index("this.land("), (
        "files are landed before the batch is planned, so the plan cannot refuse anything in time")


def test_a_swap_keeps_the_name_a_prompt_already_mentions():
    """Dropping onto a filled slot changes its file and not its wiring.

    @hero in the prompt has to go on meaning this slot after a swap, so the label and the role are
    carried over untouched. The two things that are claims about the file itself are not: a
    soundtrack sent along that the new clip does not have, and typed words belonging to a recording
    that is gone, are both the panel stating something untrue about what will be sent.
    """
    swap = re.search(r"\n  swapInto\(slots, label, data, shown\) \{(.+?)\n  \}\n", TRAY_JS, re.DOTALL)
    assert swap, "the panel no longer puts one file in another's place"
    body = swap.group(1)
    assert "{ ...slot, ...patch }" in body, (
        "a swap no longer carries the slot's own settings over, so the name a prompt mentions and "
        "the role the brief is written from are lost with the file")
    assert re.search(r"patch\.soundtrack = \"off\"", body) and "!data.has_audio" in body, (
        "a swap no longer turns off a soundtrack the new clip does not have, so the tray would "
        "claim to send a sound that is not in the file")
    assert 'patch.transcript = ""' in body, (
        "a swap no longer clears the words typed for the recording it replaced, so the brief would "
        "carry one recording's words as another's")
    assert "role" not in body, (
        "a swap now touches the role, which is the user's answer to what this file is to the clip "
        "and not a fact about the bytes")
