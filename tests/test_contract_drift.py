"""Does the node pack agree with the compiler, and what happens on the day it does not.

This file belongs to the PACK. The compiler publishes a contract -- `h3ir/contract.py`, served at
`GET /v1/contract`, printed by `h3ir contract` -- and the pack holds a snapshot of the one it was
built against plus two generated copies of the part the browser needs. What is asked here is whether
those copies are current, whether everything the pack sends is something the compiler takes, and
whether a mismatch at runtime produces a sentence somebody can act on.

**Why this shape, and what it replaces.** Three tests used to hold the two halves together by
opening the other half's source file and reading it as text, and they cannot survive the two halves
becoming two repositories. Worse, one of them was already guarding the wrong hop and had been for
its whole life:

    tests/test_swap_roles.py asserted that `nodes.py` contains the line `extra["replaces"] = ...`
    and that `AssetIn` declares a field called `replaces`. Both were true. In between them
    `_asset_facts` copied four keys out of `extra` into the request, and `replaces` was not one of
    them, so the words a user typed to say who a picture takes over from never left this machine.
    The panel collected them, the tray refused a swap that named nobody, the service declared the
    field and the compiler knew what to do with it. The test was green throughout.

So nothing here asserts about source text where it can assert about the payload. `payload_shape`
runs the very functions that build the request and reports what comes out, which is the only
description of a request that cannot be true while the request is wrong.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

from openh3ir import contract as PACK
from openh3ir import tray as T
from openh3ir.h3ir_client import ServiceError, fetch_contract, payload_shape

REPO = pathlib.Path(__file__).resolve().parents[1]
PACK_DIR = REPO

BRIEF = dict(intent="a man crosses a wet yard", seconds=5.0, aspect="16:9",
             creativity="balanced", effort="standard", seed=7, silent=False, shots="auto",
             megapixels=0.0, spoken=[], spoken_language="English", director_profile=None)


def _written(role="replacement_subject", replaces="the man in the plaid shirt"):
    """One picture and the clip it edits, in the shape `nodes.py` hands to the client."""
    return [("carguy", "image", "/comfy/input/a.png",
             {"role": role, "note": "carguy: something in the shot", "replaces": replaces}),
            ("clip", "video", "/comfy/input/v.mp4",
             {"role": "edit_source", "note": "clip", "frames": 124, "seconds": 5.167})]


def _live(**changes):
    """The compiler's contract as this pack's snapshot has it, with something moved."""
    live = json.loads(json.dumps(PACK.SNAPSHOT))
    live["package_version"] = "9.9.9"
    for key, value in changes.items():
        live[key] = value
    return live


# --------------------------------------------------------- the copies the pack ships are current

def test_the_generated_copies_are_what_this_compiler_publishes():
    """The eleven thousand characters of director prose the panel draws, and the snapshot its
    Python compares against, regenerated and held against what is on disk.

    This is the test that survived the split, and it survived it by getting BETTER. It now runs
    against the `open-h3-ir` this pack depends on -- an installed package, resolved the same way it
    resolves inside a user's ComfyUI -- rather than against a sibling working tree that no user ever
    has. What it reports is whether the copies this pack SHIPS match the compiler it will be
    installed beside.

    A failure means one of the two halves moved and the other was not regenerated:

        h3ir contract        > contract.json
        h3ir contract --js   > web/contract.data.js
    """
    from h3ir import contract as C

    for path, expected, how in (
            (PACK_DIR / "contract.json", C.as_json(), "h3ir contract"),
            (PACK_DIR / "web" / "contract.data.js", C.as_js(), "h3ir contract --js")):
        on_disk = path.read_text(encoding="utf-8")
        assert on_disk == expected, (
            f"{path.relative_to(REPO)} is not what this compiler publishes. Regenerate it: "
            f"`{how} > {path.relative_to(REPO)}`")


def test_the_snapshot_the_pack_compares_against_is_the_file_it_ships():
    """`contract.py` reads its snapshot at import from a file packaged beside it. A pack
    whose snapshot is missing cannot check anything, and would do it silently."""
    assert PACK.SNAPSHOT_PATH.is_file()
    assert PACK.BUILT_AGAINST == json.loads(PACK.SNAPSHOT_PATH.read_text())["contract_version"]
    assert PACK.SNAPSHOT["digests"], "the snapshot carries no digests, so nothing can be compared"


def test_the_version_the_pack_tells_people_to_install_is_the_one_it_requires():
    """One number in a message a stranger acts on, held against the thing that decides it.

    A service too old to publish a contract gets a note saying which release to install. That number
    is written in the pack, and a message naming a version that does not carry the endpoint sends
    somebody to install something that will not fix their problem.

    **This is the check that changed shape in the split, and it is the same question.** It used to
    read the compiler's own `pyproject.toml`, because the two lived in one repository and the
    working tree's version was the release being described. There is no compiler version in this
    repository now. What there is instead is the floor this pack requires -- the line Manager
    pip-installs -- and it has to be the same number: a pack that installs 0.3.0 and then tells
    somebody their service is too old and to install 0.2.0 is a pack contradicting its own
    installer.
    """
    requirement = re.search(r"^open-h3-ir>=(\S+)$",
                            (REPO / "requirements.txt").read_text(encoding="utf-8"), re.MULTILINE)
    assert requirement, "requirements.txt no longer states a compiler floor, so this is blind"
    assert PACK.FIRST_PUBLISHING_RELEASE == requirement.group(1), (
        f"the pack tells people to install {PACK.FIRST_PUBLISHING_RELEASE} and requires "
        f"{requirement.group(1)}. Whichever release first carries GET /v1/contract is the one both "
        "have to name.")


def test_the_pack_never_imports_the_compiler_while_it_is_being_imported():
    """The rule that survives the pack becoming an all-in-one, stated as what it actually protects.

    It used to be "the pack imports nothing from `h3ir`", which was right while the nodes only ever
    spoke HTTP and is wrong the moment the pack ships against the published package. What does NOT
    change is that the import must be LAZY, and there are three reasons, none of them style:

      * ComfyUI takes a pack whose import raises off the menu entirely, with a traceback in a
        console the user is not reading. The compiler is a separate installation that can be absent,
        half-installed, or shadowed, and none of those may cost somebody every node in this pack.
      * A pack driving a compiler on another machine needs no local package at all, and must not be
        made to install one.
      * The compiler brings fastapi, uvicorn, pydantic and tiktoken. Pulling those into ComfyUI's
        Python at import time, on every start, for a graph that may never compile anything, is the
        collision this pack has always refused.

    So: no `h3ir` import at module scope anywhere in the pack. Inside a function is fine, and
    `contract.installed_contract` is the one that does it.
    """
    for path in sorted(PACK_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lazy = {id(node) for fn in ast.walk(tree)
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                for node in ast.walk(fn) if isinstance(node, (ast.Import, ast.ImportFrom))}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in lazy:
                continue
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""])
            for name in names:
                assert name.split(".")[0] != "h3ir", (
                    f"{path.name}:{node.lineno} imports {name} at module scope. A missing or "
                    "broken compiler would take this whole pack off ComfyUI's menu. Move it inside "
                    "the function that needs it and give it an answer when it is not there.")


def test_the_one_place_that_does_import_the_compiler_is_the_one_that_must():
    """A lazy import is cheap to add and easy to spread. Every one of them is a place that fails
    when the compiler is absent, so there is exactly one and it is the one with an answer for
    that."""
    where = []
    for path in sorted(PACK_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                if any(n.split(".")[0] == "h3ir" for n in names):
                    where.append(f"{path.name}:{fn.name}")
    assert where == ["contract.py:installed_contract"], (
        f"the compiler is imported in {where}. Each one is a place that breaks when it is absent; "
        "there is one, and it answers None.")


# --------------------------------------------------- asking whichever compiler will do the work

def test_the_contract_can_be_read_from_a_compiler_in_the_same_python():
    """The other way in, and after the pack ships as an all-in-one it is the ordinary one.

    **What this proves, and it is more than it used to.** Before the split `import h3ir` resolved to
    a sibling folder in the same working tree, so this could prove the wiring and nothing about
    whether a real install works. There is no sibling folder here. The compiler this finds is the
    installed `open-h3-ir` named in `requirements.txt`, resolved exactly as it resolves inside a
    user's ComfyUI, so a failure here is a failure a user would have.

    It still says nothing about WHICH version is installed. Two halves at different versions is the
    ordinary case and the rest of this file is about what happens then; this one asks whether the
    in-process path works at all.
    """
    got = PACK.installed_contract()
    assert got is not None, "no compiler was importable, so this test proved nothing"
    assert got["contract_version"] == PACK.SNAPSHOT["contract_version"]
    assert got["digests"] == PACK.SNAPSHOT["digests"], \
        "the compiler in this Python and the pack's snapshot disagree; regenerate the snapshot"
    # and it is the same comparison whichever way the dict arrived
    assert PACK.differences(got, asset_fields=("path", "role"), brief_fields=("intent",)) == []


def test_no_compiler_in_this_python_is_an_answer_rather_than_a_crash():
    """A pack talking to a compiler on another machine needs no local package, and a half-installed
    one must not take the node pack off ComfyUI's menu. Both are None, and `differences()` turns
    None into the same sentence an old service gets."""
    import builtins

    real = builtins.__import__

    def refuse(name, *a, **kw):
        if name.split(".")[0] == "h3ir":
            raise ImportError("no module named 'h3ir'")
        return real(name, *a, **kw)

    # `sys.modules` is deliberately left alone. An earlier version of this test evicted every
    # `h3ir` module to force a real re-import, and that poisoned the whole session: the next test
    # to touch the compiler re-imported it from scratch, lost every module-level cache, and 32
    # tests in other files failed while the suite went from 3 seconds to 103. Evicting a module
    # another test is holding a class from also makes `isinstance` start lying.
    #
    # It is not needed either. `from h3ir.contract import ...` calls `__import__` whether or not
    # the module is already loaded, so the hook below fires regardless -- which is the same thing
    # that happens on a machine where the package really is absent.
    builtins.__import__ = refuse
    try:
        assert PACK.installed_contract() is None
    finally:
        builtins.__import__ = real


def test_a_compiler_that_answers_with_rubbish_is_treated_as_absent():
    """Half-installed, shadowed by something else on the path, or a version whose `contract()`
    raises. A client never fails on the CHECK -- the request after it has its own messages."""
    import h3ir.contract as real

    for broken in (lambda: {"nope": 1}, lambda: "a string",
                   lambda: (_ for _ in ()).throw(RuntimeError("half installed"))):
        original = real.contract
        real.contract = broken
        try:
            assert PACK.installed_contract() is None, broken
        finally:
            real.contract = original


def test_the_pack_never_reaches_for_the_compiler_while_it_is_talking_to_a_service():
    """The invariant that stops the check producing confident nonsense.

    Reading the local package's contract while compiling against a remote service compares this
    machine's version to another machine's work, and refuses graphs that are fine. So the two
    sources are separate functions and the caller picks one to match its own compile path. The
    compile node talks HTTP today, so it asks over HTTP.
    """
    source = (PACK_DIR / "nodes.py").read_text(encoding="utf-8")
    assert "fetch_contract(" in source, "the node stopped asking the service it compiles against"
    assert "installed_contract(" not in source, (
        "the node reads the contract of the compiler in this Python while it compiles over HTTP. "
        "Those are two different compilers and comparing them refuses graphs that are fine.")


# ------------------------------------------------- everything the pack can say is something it takes

def test_every_job_the_tray_offers_is_a_job_the_compiler_takes():
    """The tray's words are the pack's own and its tokens are the compiler's. This is that join.

    A token the tray offers and the compiler does not take is a slot a user can set and the queue
    then refuses. It happened in the other direction once -- two picture roles reached the compiler
    while the panel kept offering six -- and nothing failed, because nothing was comparing.
    """
    published = PACK.SNAPSHOT["roles"]
    wire = {"picture": "image", "video": "video", "sound": "audio"}
    for kind, table in T.ROLES.items():
        takes = published[wire[kind]]
        unknown = [role for role in table.values() if role not in takes]
        assert not unknown, (
            f"the tray offers {unknown} for a {kind} and the compiler takes {takes}. A slot set to "
            "one of those is refused when the graph is queued.")


def test_both_swap_jobs_can_be_picked_on_a_picture_slot():
    """The half that shipped missing: a job no interface offers is a job nobody can use.

    Every compiler-side test of these two passed while `PICTURE_ROLES` in this pack offered the
    original six, and the only way to ask for a swap was to write JSON into the tray widget by
    hand. Nothing failed, because nothing was comparing.

    Asked of both sides at once, which is what the published contract makes possible from inside
    this repository: the tray has to offer each one, and each one has to be a job the compiler takes
    for a picture. Before the split this was asserted from the compiler's suite, which was the only
    place that could see both. tray.js is held against tray.py by
    tests/test_panel_agrees_with_the_tray.py, so these two lines reach the dropdown a user opens.
    """
    offered = set(T.PICTURE_ROLES.values())
    published = set(PACK.SNAPSHOT["roles"]["image"])
    for role in T.ABOUT_THE_EDIT:
        assert role in offered, (
            f"{role} cannot be picked on a picture slot in the media tray, so this feature is "
            "reachable over HTTP and not from the node pack it was built for. Add it to "
            "PICTURE_ROLES in tray.py, in the words the panel shows.")
        assert role in published, (
            f"{role} is offered on a picture slot and the compiler does not take it for a picture. "
            f"It takes {sorted(published)}.")


def test_every_field_this_pack_sends_is_a_field_the_compiler_takes():
    """The replacement for a test that read two source files and missed what happened between them.

    Asked of the payload rather than of the code: `payload_shape` runs `plan_assets`,
    `plan_uploaded_assets` and `build_payload`, so what it reports is what goes on the wire. A key
    this pack emits that the compiler does not declare is now refused by the service instead of
    dropped, so this is the same failure caught at build time.
    """
    asset_fields, brief_fields, _roles = payload_shape(_written(), BRIEF)
    assert asset_fields and brief_fields, "the payload described nothing, so this test is blind"
    assert not set(asset_fields) - set(PACK.SNAPSHOT["asset_fields"]), (
        f"this pack sends {sorted(set(asset_fields) - set(PACK.SNAPSHOT['asset_fields']))} about "
        "an attachment and the compiler does not take it")
    assert not set(brief_fields) - set(PACK.SNAPSHOT["brief_fields"]), (
        f"this pack sends {sorted(set(brief_fields) - set(PACK.SNAPSHOT['brief_fields']))} about "
        "the piece and the compiler does not take it")


@pytest.mark.parametrize("transcripts,expected", [({}, False), ({"abc": "she says hello"}, True)])
def test_the_optional_keys_are_described_by_what_the_graph_actually_carries(transcripts, expected):
    """`build_payload` drops a key that has no value, so a description built from a fixed stand-in
    is wrong in both directions.

    Empty stand-in on a graph that HAS transcripts misses the field, which is the check silently
    not covering it. A fake stand-in on a graph that has none reports a field the request never
    carries, and against an older service that is a stop for something nobody is doing.
    """
    _assets, brief_fields, _roles = payload_shape(_written(), BRIEF, transcripts)
    assert ("transcripts" in brief_fields) is expected


def test_who_a_picture_replaces_reaches_the_request():
    """The regression itself, asserted where it actually broke.

    The words travelled from the panel into the tray, from the tray onto the slot, from the slot
    into the node's `extra`, and stopped. Both delivery routes are checked because which one runs
    is decided later by whether the service can open ComfyUI's disk, and the bug was in the one
    function they share.
    """
    from openh3ir.h3ir_client import plan_assets, plan_uploaded_assets

    written = _written()
    for planned in (plan_assets(written, "match", "", ""),
                    plan_uploaded_assets(written, "match", lambda _p: "0" * 64)):
        picture = next(a for a in planned if a["role"] == "replacement_subject")
        assert picture.get("replaces") == "the man in the plaid shirt", (
            "the words saying who this picture takes over from did not reach the request. The "
            "compiler binds the swap to whoever it finds in three sampled frames instead.")


def test_a_picture_that_replaces_nobody_says_nothing_about_it():
    """An empty field must not travel as an empty string. The compiler refuses `replaces` on any
    role but one, and a blank one arriving on a plain subject would be refused for saying nothing."""
    from openh3ir.h3ir_client import plan_assets

    planned = plan_assets(_written(role="subject", replaces=""), "match", "", "")
    assert "replaces" not in planned[0]


def test_the_shot_ceiling_the_pack_offers_is_the_one_the_contract_publishes():
    """The combo cannot offer a pin the compiler clamps away: asking for six and silently getting
    four is the surface lying. It used to read `h3ir.shots` directly, which is an import across the
    boundary; it reads the published limit now."""
    from openh3ir.h3ir_client import SHOTS

    ceiling = PACK.SNAPSHOT["limits"]["max_pinned_shots"]
    assert SHOTS == ("auto", *(str(i) for i in range(1, ceiling + 1)))


def test_the_option_lists_the_pack_draws_are_the_ones_the_contract_publishes():
    """Four widget lists that have to be populated before any service has been contacted, so they
    are copies by necessity. Copies with nothing comparing them are how a surface starts offering a
    setting the compiler stopped taking."""
    from openh3ir import h3ir_client as CL

    limits = PACK.SNAPSHOT["limits"]
    assert list(CL.CREATIVITY) == limits["creativity"]
    assert list(CL.EFFORT) == limits["effort"]
    assert list(CL.SIZING) == limits["sizing"]
    assert sorted(CL.ASPECTS) == sorted(limits["aspects"])
    assert sorted(CL.DIALOGUE_LANGUAGES) == sorted(limits["dialogue_languages"])
    assert CL.FPS == limits["fps"]
    assert (CL.TRAINED_MIN_FRAMES, CL.TRAINED_MAX_FRAMES) == tuple(limits["trained_frames"])


def test_the_capacity_the_tray_refuses_at_is_the_compilers_own():
    published = PACK.SNAPSHOT["limits"]["max_assets"]
    assert T.CAPACITY == {"picture": published["images"], "video": published["videos"],
                          "sound": published["audios"]}


def test_every_refusal_the_contract_publishes_carries_what_a_client_needs():
    """A status and a route, for each. Whether the client then writes a good message for each one is
    `test_comfyui_node.py`, which drives the client with every pair this list produces -- that test
    now reads its list from here rather than from the compiler's source, which is what carries it
    across the split."""
    published = PACK.SNAPSHOT["error_codes"]
    assert published, "the shipped contract lists no refusals"
    for code, spec in published.items():
        assert isinstance(spec["status"], int), code
        assert spec["on"] and set(spec["on"]) <= {"briefs", "assets"}, code


def test_the_refusals_the_client_groups_are_all_refusals_the_compiler_still_makes():
    """`REFUSED_AS_ASKED` is a list of codes written in the pack, so it can go stale in two ways.

    A code the compiler gained and the list did not is caught by `test_comfyui_node.py`, which
    drives the client with every published refusal and fails on any that reaches the generic
    branch. This is the other direction: a code the compiler no longer raises, still named here,
    which is a branch nothing can reach and a reader being told about a refusal that cannot happen.
    """
    from openh3ir.h3ir_client import REFUSED_AS_ASKED

    published = set(PACK.SNAPSHOT["error_codes"])
    assert set(REFUSED_AS_ASKED) <= published, (
        f"the client groups {sorted(set(REFUSED_AS_ASKED) - published)} and the compiler does not "
        "publish them, so that branch is unreachable")


# ------------------------------------------------------------- what happens when they disagree

def test_an_agreeing_pair_says_nothing_at_all():
    """The common case. A note nobody needs is noise in a report people are meant to read."""
    assert PACK.differences(_live(), asset_fields=("path", "role"), brief_fields=("intent",),
                            roles=(("image", "subject"),)) == []


def test_a_service_too_old_to_publish_a_contract_is_a_note_and_never_a_failure():
    """A service that predates the endpoint still compiles every brief that uses nothing newer than
    itself. Refusing those would be this pack breaking working setups to protect a feature they are
    not using."""
    gaps = PACK.differences(None, asset_fields=("path",), brief_fields=("intent",))
    assert len(gaps) == 1 and not gaps[0].stop
    assert PACK.FIRST_PUBLISHING_RELEASE in gaps[0].message, \
        "the note does not say which version to install"


def test_a_field_the_service_cannot_take_stops_the_graph_and_names_it():
    """The failure that used to be silent. Stopped before any media travels, because a clip can be
    hundreds of megabytes and the answer does not depend on it."""
    older = _live(asset_fields=[f for f in PACK.SNAPSHOT["asset_fields"] if f != "replaces"])
    gaps = PACK.differences(older, asset_fields=("path", "role", "replaces"),
                            brief_fields=("intent",))
    stops = [g for g in gaps if g.stop]
    assert len(stops) == 1, [g.message for g in gaps]
    assert "`replaces`" in stops[0].message
    assert "update open-h3-ir" in stops[0].message.lower(), \
        "the refusal does not say what to do about it"


def test_a_brief_setting_the_service_cannot_take_stops_the_graph_too():
    older = _live(brief_fields=[f for f in PACK.SNAPSHOT["brief_fields"] if f != "director_profile"])
    stops = [g for g in PACK.differences(older, asset_fields=("path",),
                                         brief_fields=("intent", "director_profile")) if g.stop]
    assert len(stops) == 1 and "`director_profile`" in stops[0].message


def test_the_same_older_service_is_fine_for_a_graph_that_does_not_use_the_new_thing():
    """The whole reason the check reads the payload rather than the pack's capabilities. Two halves
    at different versions have to keep working for everything that did not change."""
    older = _live(asset_fields=[f for f in PACK.SNAPSHOT["asset_fields"] if f != "replaces"])
    gaps = PACK.differences(older, asset_fields=("path", "role", "note"), brief_fields=("intent",),
                            roles=(("image", "subject"),))
    assert [g for g in gaps if g.stop] == []


def test_a_slot_set_to_a_job_the_service_has_no_name_for_stops_the_graph():
    roles = json.loads(json.dumps(PACK.SNAPSHOT["roles"]))
    roles["image"] = [r for r in roles["image"] if r != "replacement_subject"]
    gaps = PACK.differences(_live(roles=roles), asset_fields=("path",), brief_fields=("intent",),
                            roles=(("image", "replacement_subject"), ("video", "edit_source")))
    stops = [g for g in gaps if g.stop]
    assert len(stops) == 1
    assert "`replacement_subject`" in stops[0].message, \
        "the token is gone, and it is the string somebody searches the API docs for"
    # And it is said in the words the person actually chose from, not in the wire's. They set that
    # slot from a dropdown reading "replace the one in the clip" and have never seen the token.
    assert '"replace the one in the clip"' in stops[0].message, \
        "the refusal names the job in the wire's words rather than the panel's"
    assert '"first frame"' in stops[0].message, \
        "the jobs it offers instead are listed as tokens rather than as what the dropdown says"
    assert "frame_anchor_first" not in stops[0].message, \
        "a raw role token is offered to the user as something to pick"


def test_a_job_the_service_takes_and_the_pack_cannot_offer_is_reported_and_never_stops():
    """The drift that already shipped, seen from the pack's side. The graph in front of the user is
    fine; what they have lost is a choice they never saw."""
    roles = json.loads(json.dumps(PACK.SNAPSHOT["roles"]))
    roles["image"] = roles["image"] + ["hologram"]
    gaps = PACK.differences(_live(roles=roles), asset_fields=("path",), brief_fields=("intent",))
    assert [g for g in gaps if g.stop] == []
    assert any("hologram" in g.message and "Update the pack" in g.message for g in gaps), \
        [g.message for g in gaps]


def test_a_drifted_direction_is_reported_and_never_stops_a_render():
    """The Director node sends the prose in its box, so what compiles is always what the canvas
    showed. A drifted copy cannot render the wrong thing; it can only teach the wrong thing."""
    digests = dict(PACK.SNAPSHOT["digests"], directors="0000000000000000")
    gaps = PACK.differences(_live(digests=digests), asset_fields=("path",),
                            brief_fields=("intent",))
    assert [g for g in gaps if g.stop] == []
    assert any("seven directions" in g.message for g in gaps), [g.message for g in gaps]


def test_a_drifted_camera_vocabulary_is_reported():
    digests = dict(PACK.SNAPSHOT["digests"], camera_moves="0000000000000000")
    gaps = PACK.differences(_live(digests=digests), asset_fields=("path",),
                            brief_fields=("intent",))
    assert any("camera vocabulary" in g.message for g in gaps), [g.message for g in gaps]


@pytest.mark.parametrize("key,value,phrase", [
    ("director_notes_max_chars", 2000, "the longest direction it accepts"),
    ("max_pinned_shots", 4, "the most shots a graph may pin"),
    ("aspects", ["16:9"], "the shapes it offers"),
    ("max_assets", {"images": 4, "videos": 1, "audios": 1, "video_soundtracks": 1},
     "how many references of each kind it takes"),
])
def test_a_limit_that_moved_is_reported_in_words_a_user_reads(key, value, phrase):
    """Every one of these is a number a surface restates so it can offer or refuse something early.
    Being wrong about one costs a legal thing refused here or an illegal thing refused there, both
    with a message, rather than a render nobody can explain. So: a note, never a stop, and written
    as what it means rather than as the name of a field."""
    limits = dict(PACK.SNAPSHOT["limits"], **{key: value})
    gaps = PACK.differences(_live(limits=limits), asset_fields=("path",), brief_fields=("intent",))
    assert [g for g in gaps if g.stop] == []
    said = [g.message for g in gaps if phrase in g.message]
    assert said, [g.message for g in gaps]
    assert key not in said[0], f"the note names the field instead of saying what it is: {said[0]}"


def test_every_difference_names_the_service_it_is_about():
    """A ComfyUI console carries every pack's output. A sentence about "the service" with no name
    in it is a sentence somebody has to work out the owner of."""
    older = _live(asset_fields=[f for f in PACK.SNAPSHOT["asset_fields"] if f != "replaces"],
                  limits=dict(PACK.SNAPSHOT["limits"], max_pinned_shots=4))
    gaps = PACK.differences(older, asset_fields=("path", "replaces"), brief_fields=("intent",))
    assert gaps
    for gap in gaps:
        assert "OpenH3-IR" in gap.message, f"nothing names the pack or the service: {gap.message}"


# ------------------------------------------------------------------ how the node uses all of this

def test_the_check_happens_before_the_media_travels():
    """The order is the point. A clip can be hundreds of megabytes and the answer does not depend on
    it, so asking after the upload would spend the transfer to learn something free.

    Read as structure rather than as text: the calls inside `execute` are taken in order and the
    contract fetch has to come first.
    """
    tree = ast.parse((PACK_DIR / "nodes.py").read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "OpenH3IRCompile")
    execute = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
    # By source position, not by walk order: `ast.walk` is breadth-first, so a call nested inside
    # another call's arguments comes out later than the call that contains it. Ordering on that
    # would have this test claiming the wrong thing about a file that is correct.
    where = {n.func.id: n.lineno for n in ast.walk(execute)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "fetch_contract" in where, "the compile node never asks the service what it takes"
    assert "compile_with_media" in where, "this scan no longer finds the compile call; it is blind"
    assert where["fetch_contract"] < where["compile_with_media"], \
        "the contract is checked after the media has already been sent"


def test_the_node_passes_the_graphs_own_transcripts_to_the_check():
    """The half of `payload_shape` the node has to supply. Called with the default, a graph carrying
    transcripts is described as one that does not, and `transcripts` is never checked at all."""
    source = (PACK_DIR / "nodes.py").read_text(encoding="utf-8")
    assert "payload_shape(written, brief, transcripts)" in source, \
        "the check describes a payload without the transcripts this graph is actually sending"


def test_the_node_refuses_on_a_stop_and_reports_the_rest():
    """Both halves of the answer reach the user, and they reach it differently: a stop is raised so
    the queue ends there, and a note is a line in the report beside the render's own facts."""
    source = (PACK_DIR / "nodes.py").read_text(encoding="utf-8")
    assert re.search(r"stops = \[g\.message for g in gaps if g\.stop\]", source), \
        "the node no longer separates what stops the graph from what is worth a line"
    assert re.search(r"if stops:\n\s+raise ServiceError", source), \
        "a difference that stops the graph no longer stops it"
    assert re.search(r"for gap in gaps:\n\s+text \+= .*line\(\"note\", gap\.message\)", source), \
        "the differences that do not stop the graph reach nobody"


def test_asking_an_unreachable_service_is_never_an_exception():
    """The request that matters is the one after this, and it has its own messages for every way a
    service can be unreachable. Failing a queue here would replace those with a worse one."""
    assert fetch_contract("http://127.0.0.1:9", timeout=0.25) is None


def test_a_service_that_answers_with_something_else_is_treated_as_publishing_nothing():
    """A proxy, a login page, a different service on the port. None of them are a contract, and
    guessing that a 200 means one would compare against a dict of whatever came back."""
    import openh3ir.h3ir_client as CL

    for status, body in ((200, {"hello": "world"}), (200, "<html>"), (404, {"detail": "nope"}),
                         (500, {})):
        original = CL._request
        CL._request = lambda *a, **k: (status, body)
        try:
            assert fetch_contract("http://example.invalid") is None, (status, body)
        finally:
            CL._request = original


def test_a_service_error_while_asking_is_swallowed_rather_than_raised():
    import openh3ir.h3ir_client as CL

    original = CL._request

    def boom(*_a, **_k):
        raise ServiceError("the endpoint is not answering")

    CL._request = boom
    try:
        assert fetch_contract("http://example.invalid") is None
    finally:
        CL._request = original
