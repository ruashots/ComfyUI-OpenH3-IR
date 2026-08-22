"""The media tray and the @ prompt, tested with no ComfyUI, no torch and no browser.

Every guard in here is ported from the socket-era tests or demanded by the tray contract. The panel
and the picker are rendering over this logic; this logic is the contract, so it is what gets pinned.
The messages are asserted as much as the behaviour, because on a canvas the message IS the interface.
"""
from __future__ import annotations

import json

import pytest

from openh3ir import tray as T
from openh3ir.h3ir_client import ServiceError


def _slot(kind="picture", label=None, role=None, note="", transcript="", soundtrack="off",
          file="openh3ir/x.png [input]"):
    entry = {"kind": kind, "label": label or T.auto_label(kind), "file": file, "note": note}
    if role:
        entry["role"] = role
    if transcript:
        entry["transcript"] = transcript
    if kind == "video":
        entry["soundtrack"] = soundtrack
    return entry


def _tray(*entries) -> list[T.Slot]:
    return T.read_tray(json.dumps(list(entries)))


# --------------------------------------------------------------------------- labels

def test_auto_labels_count_from_one_and_skip_taken_names():
    assert T.auto_label("picture") == "picture1"
    assert T.auto_label("picture", ("picture1", "picture2")) == "picture3"
    assert T.auto_label("sound", ("AUDIO1",)) == "audio2", "case does not hide a taken name"


def test_a_nameless_slot_is_refused_with_the_fix_in_the_message():
    with pytest.raises(ServiceError) as e:
        T.check_label("", {})
    assert "has no name" in str(e.value) and "picture1" in str(e.value)


def test_a_label_that_cannot_follow_an_at_sign_is_refused():
    for bad in ("the car", "car!", "über+", "---"):
        with pytest.raises(ServiceError):
            T.check_label(bad, {})
    T.check_label("the-car", {})
    T.check_label("CAR2", {})


def test_speaks_is_reserved_because_it_would_mean_two_things():
    with pytest.raises(ServiceError) as e:
        T.check_label("speaks", {})
    assert "@speaks(" in str(e.value)


def test_two_slots_with_one_name_are_refused_case_blind():
    with pytest.raises(ServiceError) as e:
        _tray(_slot(label="Car"), _slot(label="car"))
    assert "both called" in str(e.value)


# --------------------------------------------------------------------------- reading the tray

def test_garbage_tray_text_is_refused_in_words_a_person_can_act_on():
    with pytest.raises(ServiceError) as e:
        T.read_tray("{not json")
    assert "media tray" in str(e.value).lower()


def test_capacity_is_h3s_own_and_refused_by_name():
    with pytest.raises(ServiceError) as e:
        _tray(*[_slot(label=f"p{i}") for i in range(10)])
    assert "9" in str(e.value)
    with pytest.raises(ServiceError):
        _tray(*[_slot(kind="video", label=f"v{i}", file="a.mp4 [input]") for i in range(4)])


def test_twelve_files_total_counts_a_paired_soundtrack_as_its_own_file():
    nine = [_slot(label=f"p{i}") for i in range(9)]
    three = [_slot(kind="video", label=f"v{i}", soundtrack="paired", file="a.mp4 [input]")
             for i in range(3)]
    with pytest.raises(ServiceError) as e:
        _tray(*(nine + three))
    assert "12" in str(e.value)


def test_an_unknown_role_is_refused_rather_than_defaulted():
    with pytest.raises(ServiceError):
        _tray(_slot(role="protagonist"))


# --------------------------------------------------------------------------- ordering

def test_frame_anchors_lead_the_numbering_and_the_rest_keep_their_order():
    slots = _tray(_slot(label="a"), _slot(label="b", role="frame_anchor_last"),
                  _slot(label="c", role="frame_anchor_first"))
    assert [s.label for s in T.in_numbering_order(slots)] == ["c", "b", "a"]


def test_a_paired_soundtrack_travels_directly_behind_its_clip():
    slots = _tray(_slot(label="p1"),
                  _slot(kind="video", label="clip", soundtrack="paired", file="a.mp4 [input]"),
                  _slot(kind="sound", label="song", file="a.wav [input]"))
    order = [(s.label, part) for s, part in T.asset_order(slots)]
    assert order == [("p1", "file"), ("clip", "file"), ("clip", "soundtrack"), ("song", "file")]


def test_a_clips_soundtrack_set_off_sends_no_soundtrack():
    slots = _tray(_slot(kind="video", label="clip", soundtrack="off", file="a.mp4 [input]"))
    assert [(s.label, p) for s, p in T.asset_order(slots)] == [("clip", "file")]


# --------------------------------------------------------------------------- the job

def test_the_job_is_read_off_the_roles():
    assert T.job_for(_tray(_slot(label="p", role="frame_anchor_first"))) == "i2va"
    assert T.job_for(_tray(_slot(label="p", role="frame_anchor_first"),
                           _slot(label="q", role="frame_anchor_last"))) == "fl2va"
    assert T.job_for(_tray(_slot(label="p"))) == "ref2va"
    assert T.job_for([]) == "t2va"


def test_two_first_frames_are_refused_by_name():
    with pytest.raises(ServiceError) as e:
        T.exclusivity(_tray(_slot(label="a", role="frame_anchor_first"),
                            _slot(label="b", role="frame_anchor_first")))
    assert "a" in str(e.value) and "b" in str(e.value)


def test_a_sketch_beside_a_frame_anchor_is_refused_with_the_reason():
    with pytest.raises(ServiceError) as e:
        T.exclusivity(_tray(_slot(label="board", role="storyboard"),
                            _slot(label="open", role="frame_anchor_first")))
    assert "H3 would never receive it" in str(e.value)


def test_a_reference_beside_a_frame_anchor_is_refused_as_two_jobs():
    with pytest.raises(ServiceError) as e:
        T.exclusivity(_tray(_slot(label="open", role="frame_anchor_first"), _slot(label="extra")))
    assert "two different jobs" in str(e.value)


# --------------------------------------------------------------------------- the @ prompt

def test_the_prompt_is_split_into_text_mentions_and_spoken_lines():
    got = T.parse_intent('the man from @hero says @speaks("We close at six."), then leaves')
    assert got == [("text", "the man from "), ("mention", "hero"), ("text", " says "),
                   ("spoken", "We close at six."), ("text", ", then leaves")]


def test_a_spoken_line_arrives_letter_for_letter_including_inner_quotes():
    got = T.spoken_lines('@speaks("he said "no", twice")')
    assert got == ['he said "no", twice']


def test_an_unclosed_spoken_line_is_refused_with_the_shape_of_the_fix():
    with pytest.raises(ServiceError) as e:
        T.parse_intent('she says @speaks("hello')
    assert '@speaks("' in str(e.value) and "Close it" in str(e.value)


def test_an_empty_spoken_line_is_refused():
    with pytest.raises(ServiceError):
        T.parse_intent('@speaks("  ")')


def test_a_lone_at_sign_is_just_text():
    assert T.parse_intent("mail me @ home") == [("text", "mail me @ home")]


def test_mention_order_and_duplicates_are_preserved():
    assert T.mentioned_labels("@a then @b then @a") == ["a", "b", "a"]


# --------------------------------------------------------------------------- resolving

def test_a_mention_becomes_the_slots_note_words():
    slots = _tray(_slot(label="hero", note="the man in the leather jacket"))
    r = T.resolve_intent("@hero walks out", slots)
    assert r.intent == "the man in the leather jacket walks out"
    assert r.became == (("hero", "the man in the leather jacket"),)


def test_a_mention_with_no_note_becomes_the_label_itself():
    r = T.resolve_intent("@picture1 sits there", _tray(_slot()))
    assert r.intent == "picture1 sits there"


def test_mentions_are_case_blind_like_the_labels_are():
    r = T.resolve_intent("@HERO nods", _tray(_slot(label="hero", note="the man")))
    assert r.intent == "the man nods"


def test_an_unknown_mention_is_refused_naming_what_exists():
    with pytest.raises(ServiceError) as e:
        T.resolve_intent("@ghost walks", _tray(_slot(label="hero")))
    msg = str(e.value)
    assert "@ghost" in msg and "hero" in msg and "Rename" in msg


def test_a_mention_with_no_tray_at_all_says_to_add_one():
    with pytest.raises(ServiceError) as e:
        T.resolve_intent("@ghost walks", [])
    assert "no media tray" in str(e.value)


def test_a_spoken_line_stays_in_place_as_a_quote_and_is_collected_for_the_lock():
    r = T.resolve_intent('the guard says @speaks("Not for me.") and turns', [])
    assert r.intent == 'the guard says "Not for me." and turns'
    assert r.spoken == ("Not for me.",)


def test_unmentioned_slots_are_reported_not_dropped():
    slots = _tray(_slot(label="hero", note="the man"), _slot(label="extra", note="a red bike"))
    r = T.resolve_intent("@hero rides", slots)
    assert r.unmentioned == ("extra",)
    notes = "\n".join(T.mention_notes(r, slots))
    assert "@extra" in notes and "never mentions" in notes


def test_the_note_sent_to_the_service_carries_the_label_for_the_binding():
    slots = _tray(_slot(label="carguy", note="the man in the leather jacket"))
    assert T.note_for(slots[0]) == "carguy: the man in the leather jacket"
    assert T.note_for(_tray(_slot(label="plain"))[0]) == "plain"


# ---------------------------------------------------------- the table, restated in the front doors

def test_the_readme_lists_exactly_the_roles_the_tray_takes():
    """`ROLES` is the answer to the question this front page promises to answer, so a stale table
    there is a reader wiring up a role that does not exist, or never learning one that does.

    Written after the two swap roles reached the compiler, the service and the tray while the README
    table still listed six picture roles. The panel had the same gap and nothing failed, which is
    what a restatement with no test always looks like.

    It used to read the compiler's README as well, and after the split it cannot: that file is in
    another repository and no check can span the two. The compiler's own front page carries a copy
    of this table with nothing holding it true, which is the drift this test exists to prevent,
    living on in the one place this repository cannot reach.
    """
    import pathlib as _p

    root = _p.Path(__file__).resolve().parents[1]
    for doc in ("README.md",):
        body = (root / doc).read_text(encoding="utf-8")
        for kind, word in (("picture", "picture"), ("video", "clip"), ("sound", "sound")):
            rows = [l for l in body.splitlines() if l.startswith(f"| {word} | ")]
            assert len(rows) == 1, f"{doc} has {len(rows)} rows for a {word}, so this scan is blind"
            listed = [w.strip() for w in rows[0].split("|")[2].split("·")]
            assert listed == list(T.ROLES[kind]), (
                f"{doc} says a {word} can be {listed} and tray.py takes "
                f"{list(T.ROLES[kind])}.")


# ------------------------------------------------------------ who a replacement takes over from

def _swap(label, replaces="", role="replacement_subject"):
    entry = {"kind": "picture", "label": label, "role": role, "file": "openh3ir/x.png [input]"}
    if replaces:
        entry["replaces"] = replaces
    return entry


def test_who_a_picture_replaces_survives_the_tray():
    slots = _tray(_swap("carguy", "the man in the plaid shirt"))
    assert slots[0].replaces == "the man in the plaid shirt"


def test_a_slot_that_replaces_nobody_carries_no_words():
    assert _tray(_slot())[0].replaces == ""


def test_saying_who_on_a_role_that_takes_nobodys_place_is_refused():
    """The same judgement the transcript field gets: a statement this chain would drop is an error
    rather than a no-op, because nothing downstream would ever mention it again."""
    with pytest.raises(ServiceError) as e:
        _tray(_swap("carguy", "the man in the plaid shirt", role="subject"))
    assert "replace the one in the clip" in str(e.value)
    assert "something in the shot" in str(e.value)


def test_one_picture_replacing_somebody_is_never_asked_who():
    """Nothing is ambiguous with one: whatever it stands in for, only one picture is asking."""
    assert T.check_swaps(_tray(_swap("carguy"))) is None
    assert T.check_swaps(_tray(_swap("carguy", "the man in the plaid shirt"))) is None


def test_two_pictures_replacing_and_one_silent_stops_the_job():
    with pytest.raises(ServiceError) as e:
        T.check_swaps(_tray(_swap("carguy", "the man in the plaid shirt"), _swap("picture2")))
    said = str(e.value)
    assert said.startswith("@picture2 does not say who it replaces."), (
        "what is missing comes first: the panel's line is one slot wide and cuts the tail")
    assert "@carguy and @picture2 both" in said
    assert T.SAY_WHO in said


def test_two_pictures_that_both_say_who_are_left_alone():
    assert T.check_swaps(_tray(_swap("carguy", "the man in the plaid shirt"),
                               _swap("picture2", "the woman at the lathe"))) is None


def test_three_replacements_read_as_a_sentence_and_name_every_silent_one():
    with pytest.raises(ServiceError) as e:
        T.check_swaps(_tray(_swap("a", "the man in the plaid shirt"), _swap("b"), _swap("c")))
    said = str(e.value)
    assert said.startswith("@b and @c do not say who they replace.")
    assert "@a, @b and @c all" in said


def test_the_refusal_says_where_to_fix_it_and_shows_the_shape_of_an_answer():
    """On a canvas the message IS the interface: a refusal that does not say what to type leaves
    the user guessing at a field they have never used."""
    with pytest.raises(ServiceError) as e:
        T.check_swaps(_tray(_swap("a"), _swap("b")))
    assert "OpenH3-IR Media node" in str(e.value)
    assert "the man in the plaid shirt" in str(e.value)


def test_the_words_the_tray_shows_for_a_swap_are_not_the_role_tokens():
    """P9's ground again, one layer out. The panel's vocabulary is the user's craft, not the wire
    format: a dropdown reading `replacement_subject` is a dropdown that has to be explained."""
    for words, role in T.PICTURE_ROLES.items():
        if role not in T.ABOUT_THE_EDIT:
            continue
        assert "_" not in words and words != role, words
        assert "clip" in words, (
            f"{words!r} says nothing about the clip, and both of these roles are statements "
            "about one: a picture set to either without a clip being edited is refused.")


def test_a_clip_can_be_told_to_lend_its_camera_and_cutting():
    """The words and the token for `structure`, and what a tray holding one compiles as.

    A structure clip is a reference use, so the job stays in the reference family. Carved out of the
    compiler's own suite in the split: the compiler half of that test asks what the brief says about
    a structure clip, and this half asks whether the tray can express one at all.
    """
    import json

    assert T.VIDEO_ROLES.get("copy how it is shot") == "structure"
    slots = T.read_tray(json.dumps([{
        "kind": "video", "label": "clip", "file": "a.mp4 [input]",
        "role": "structure", "soundtrack": "off", "note": "its camera and cutting"}]))
    assert T.job_for(slots) == "ref2va"
