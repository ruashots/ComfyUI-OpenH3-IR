"""The panel restates two of tray.py's rules, and these tests fail when the two drift.

The naming rule and the prompt's grammar are deliberately ONE rule each, stated in
tray.py and enforced there. The panel now restates both, because a rule that only refuses
at queue time cannot stop a name being typed, and a grammar the browser does not know cannot draw a
mention as an object. Two statements of one rule is a rule that drifts, so the drift is what gets
tested: these read the shipped JavaScript as text and hold it against the Python that governs it.

No node and no browser. The panel's behaviour is proved by driving it; what is proved here is the
narrower and more durable thing -- that the alphabet, the reserved word and the two spoken-line
literals in the browser are the ones this package refuses by. Every scan asserts that it found
something first, because a regex that quietly stops matching is a test that passes forever.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from openh3ir import tray as T

WEB = pathlib.Path(__file__).resolve().parents[1] / "web"
TRAY_JS = (WEB / "tray.js").read_text(encoding="utf-8")
PROMPT_JS = (WEB / "prompt.js").read_text(encoding="utf-8")

# Every class name the panels put on an element, and every one their stylesheets define. The
# stylesheets are template literals, so a stray backtick anywhere inside one -- a class name quoted
# in a comment is the easy way to write one -- ends the literal early, and everything past that
# point stops being CSS. ComfyUI says nothing when that happens: the extension throws on import and
# the whole panel is simply absent, with the node still there and every widget still working. The
# names below are how that is caught from Python, which is the only place this suite runs.
# `oh3d?-` covers both prefixes the pack uses: the tray and the prompt write `oh3-`, the director's
# panel writes `oh3d-`. One expression rather than two, because the failure it catches is pack-wide
# and a new panel with a new prefix that this scan cannot see is a panel with no cover at all.
CLASS_USED = re.compile(r"(?<!-)\b(oh3d?-[a-z0-9-]+)")
CLASS_STYLED = re.compile(r"\.(oh3d?-[a-z0-9-]+)")


def _stylesheet_of(path: pathlib.Path) -> str | None:
    """One file's `const CSS = ...` template literal, as the text between its backticks."""
    src = path.read_text(encoding="utf-8")
    start = re.search(r"^const CSS = `", src, re.MULTILINE)
    if not start:
        return None
    end = src.find("`", start.end())
    assert end > 0, f"{path.name}'s stylesheet is opened and never closed"
    return src[start.end():end]


def _stylesheets() -> str:
    """Every stylesheet in the pack, which all land in the one document together."""
    out = [css for css in (_stylesheet_of(p) for p in sorted(WEB.glob("*.js"))) if css]
    assert out, "no stylesheet was found in the pack, so this scan is blind"
    return "\n".join(out)


def _js(source: str, name: str) -> str:
    """One `const NAME = <literal>;` from a JS file, as the literal's own text."""
    m = re.search(rf"^const {name} = (.+);$", source, re.MULTILINE)
    assert m, f"{name} is no longer declared in the panel, so this comparison is blind"
    return m.group(1).strip()


def _js_string(source: str, name: str) -> str:
    """One declared JavaScript string literal, unquoted but NOT unescaped, so the comparisons below
    read the same characters the browser was handed."""
    raw = _js(source, name)
    assert raw[0] == raw[-1] and raw[0] in "'\"", f"{name} is not a plain string literal: {raw}"
    return raw[1:-1]


def _js_object(source: str, name: str) -> str:
    """One `const NAME = { ... };` spanning several lines, as the literal's own text.

    `_js` above stops at the first line end, which every declaration in the panel respects except
    the three role tables. Those are the ones this file has to read, so the block runs from the
    opening bracket to the `};` or `];` that closes it in the first column, which is the shape all
    three are written in and is asserted here rather than assumed.
    """
    opened = re.search(rf"^const {name} = (\{{|\[)", source, re.MULTILINE)
    assert opened, f"{name} is no longer declared in the panel, so this comparison is blind"
    closed = re.search(r"^[}\]];$", source[opened.start():], re.MULTILINE)
    assert closed, f"{name} is opened and never closed on a line of its own"
    return source[opened.end() - 1:opened.start() + closed.end()]


def _js_strings(literal: str) -> list[str]:
    """Every double-quoted string in a JS literal, in the order it writes them."""
    out = re.findall(r'"([^"]*)"', literal)
    assert out, "no strings were read out of this literal, so the comparison below is blind"
    return out


def _js_by_kind(literal: str) -> dict[str, str]:
    """A `{ picture: ..., video: ..., sound: ... }` literal split into its three blocks.

    Split rather than parsed, because the two per-kind tables hold different shapes -- a list of
    words in one, token-to-badge pairs in the other -- and each test reads its own.
    """
    out = {}
    for kind in T.KINDS:
        m = re.search(rf"\b{kind}: *([\[{{].*?[\]}}]),?\n", literal, re.DOTALL)
        assert m, f"the panel's table has no {kind} block, so this comparison is blind"
        out[kind] = m.group(1)
    return out


# ------------------------------------------------------------- the panel is there at all to judge

def test_every_class_the_panels_put_on_an_element_is_one_they_style():
    """The cheapest proof from here that a stylesheet is whole.

    A panel whose stylesheet was cut short still runs and still puts its classes on its elements, and
    what reaches the canvas is an unstyled pile: rows outside the node, no board, no chips. Nothing
    on the Python side can see that. What it CAN see is a class the pack asks for and never defines,
    which is what a cut-short stylesheet leaves behind in quantity.
    """
    styled = set(CLASS_STYLED.findall(_stylesheets()))
    assert len(styled) > 30, f"only {len(styled)} classes are styled, so a stylesheet is truncated"
    used = set()
    for path in sorted(WEB.glob("*.js")):
        used |= set(CLASS_USED.findall(path.read_text(encoding="utf-8")))
    assert not used - styled, (
        f"these classes are put on elements and never styled: {sorted(used - styled)}. Either the "
        "rule is missing, or a stylesheet was ended early by a backtick inside it.")


def test_no_class_is_styled_by_two_of_the_panels():
    """Every panel's stylesheet lands in the same document, so a class name is pack-wide.

    Two files styling one name is not a clash the browser reports: the later rule simply wins on
    whichever properties it sets. The prompt's mentions and the tray's name field both wanted to call
    the orange @ the same thing, and the tray's version carries a font-family, which on a mention
    would change how wide it is and slide the drawing off the sentence it is drawn over.
    """
    where: dict[str, set[str]] = {}
    for path in sorted(WEB.glob("*.js")):
        css = _stylesheet_of(path)
        if css is None:
            continue
        for name in set(CLASS_STYLED.findall(css)):
            where.setdefault(name, set()).add(path.name)
    assert len(where) > 30, f"only {len(where)} classes were found, so a stylesheet is truncated"
    shared = {name: sorted(files) for name, files in where.items() if len(files) > 1}
    assert not shared, (
        f"these class names are styled in more than one of the pack's stylesheets: {shared}. Give "
        "one of them its own name; they are not separate namespaces.")


# ----------------------------------------------------------------- the roles, one table twice

"""What a file IS is written down twice: `ROLES` in tray.py, which refuses anything else at
queue time, and `ROLES` / `ROLE_TOKEN` / `BADGE_BY_KIND` in the panel, which is where a user picks
one. The four tests below are what makes that two statements of one table rather than two tables.

They exist because the drift already happened and shipped: `placed_subject` and
`replacement_subject` were added to the compiler, the service and the tray's Python, and the panel
kept offering six picture roles, so the feature could be reached over HTTP and not from the node it
was built for. Nothing failed -- there was nothing here to fail."""


def test_the_panel_offers_exactly_the_roles_the_tray_takes():
    """In the same order, because the first entry is the role a dropped file lands on."""
    shown = {kind: _js_strings(block) for kind, block
             in _js_by_kind(_js_object(TRAY_JS, "ROLES")).items()}
    for kind in T.KINDS:
        assert shown[kind] == list(T.ROLES[kind]), (
            f"the panel offers {shown[kind]} for a {kind} and tray.py takes "
            f"{list(T.ROLES[kind])}. A role in the panel and not in the tray is refused at queue "
            "time; a role in the tray and not in the panel cannot be picked at all.")


def test_each_word_the_panel_shows_becomes_the_token_the_tray_stores():
    """The words are user interface and the tokens are the wire format, so this is the join.

    One flat table in the panel against three in the tray, which is safe only while no two kinds
    share a word: `<select>` writes `ROLE_TOKEN[words]` with no idea which kind it is on, so a word
    meaning one thing on a picture and another on a sound would store the wrong one. That is
    asserted here rather than trusted.
    """
    pairs = re.findall(r'"([^"]+)": "([^"]+)"', _js_object(TRAY_JS, "ROLE_TOKEN"))
    assert pairs, "ROLE_TOKEN no longer reads as pairs, so this comparison is blind"
    every = [(words, role) for kind in T.KINDS for words, role in T.ROLES[kind].items()]
    assert len(dict(every)) == len(every), (
        "two kinds now share a word for a role, and the panel's one flat table cannot tell them "
        "apart. Give one of them different words, or make ROLE_TOKEN per kind.")
    assert dict(pairs) == dict(every), (
        f"the panel translates {sorted(set(pairs) - set(every))} and the tray reads "
        f"{sorted(set(every) - set(pairs))}.")


def test_the_role_a_dropped_file_lands_on_is_the_one_the_tray_defaults_to():
    """Two statements of the default in the panel -- `DEFAULT_ROLE`, and the first entry of `ROLES`
    that `place` actually writes -- and the tray's own, which is what an empty role field means."""
    declared = dict(re.findall(r"(\w+): \"([^\"]+)\"", _js(TRAY_JS, "DEFAULT_ROLE")))
    shown = {kind: _js_strings(block) for kind, block
             in _js_by_kind(_js_object(TRAY_JS, "ROLES")).items()}
    token = dict(re.findall(r'"([^"]+)": "([^"]+)"', _js_object(TRAY_JS, "ROLE_TOKEN")))
    assert "role: ROLE_TOKEN[ROLES[move.kind][0]]" in TRAY_JS, (
        "a dropped file no longer takes the first role in the list, so the check below is blind")
    for kind in T.KINDS:
        assert declared[kind] == T.DEFAULT_ROLE[kind], (
            f"the panel calls a new {kind} {declared[kind]!r} and the tray reads an unset role as "
            f"{T.DEFAULT_ROLE[kind]!r}.")
        assert token[shown[kind][0]] == T.DEFAULT_ROLE[kind], (
            f"a dropped {kind} lands on {token[shown[kind][0]]!r} and an unset one is read as "
            f"{T.DEFAULT_ROLE[kind]!r}.")


def test_every_role_wears_a_badge_on_a_filled_cell():
    """A cell shows its role as a chip; a role with no chip is a setting nothing on the board shows.

    Compared both ways: a missing badge hides a role the user set, and a badge for a role that no
    longer exists is a line nothing can reach.
    """
    badges = {kind: dict(re.findall(r'(\w+): "([^"]+)"', block)) for kind, block
              in _js_by_kind(_js_object(TRAY_JS, "BADGE_BY_KIND")).items()}
    for kind in T.KINDS:
        assert set(badges[kind]) == set(T.ROLES[kind].values()), (
            f"these {kind} roles wear no badge: {sorted(set(T.ROLES[kind].values()) - set(badges[kind]))}; "
            f"these badges name no role: {sorted(set(badges[kind]) - set(T.ROLES[kind].values()))}.")


def test_a_picture_badge_holds_one_line():
    """A picture's badge is drawn over its thumbnail, and a wrapped one takes a fifth of the image.

    Measured in a browser on the board at rest, at the size the panel pins itself to: a picture
    cell is 64px wide, the note chip that sits beside the role badge takes 12 of them, and 11
    characters of this font measure 47px. "replace in clip", the first badge written for the
    replacement role, measured 60px and wrapped onto a second line, pushing the plate down inside
    its own cell. The clips and sounds columns are wide rows rather than squares, so this ceiling
    is the picture column's alone -- "how it's shot" is 13 characters and sits on one line there.
    """
    badges = dict(re.findall(r'(\w+): "([^"]+)"',
                             _js_by_kind(_js_object(TRAY_JS, "BADGE_BY_KIND"))["picture"]))
    too_long = {role: text for role, text in badges.items() if len(text) > 11}
    assert not too_long, (
        f"these picture badges are longer than the 11 characters a cell holds: {too_long}. They "
        "wrap onto a second line and cover the picture they are drawn over.")


# ------------------------------------------------- who a replacement replaces, one rule twice

def test_the_panel_asks_for_who_on_the_role_the_tray_refuses_it_on():
    """One role token, two files. The panel draws the field only for it and clears the words when
    the role moves away; tray.py refuses a slot that carries them under any other role. If
    those two ever named different roles, the panel would collect words the queue turns away."""
    assert _js_string(TRAY_JS, "REPLACEMENT") == T.REPLACEMENT
    assert 'slot.kind === "picture" && slot.role === REPLACEMENT' in TRAY_JS, (
        "the panel no longer gates the field on that role, so this comparison is blind")


def test_both_halves_say_the_same_thing_about_a_replacement_that_names_nobody():
    """The panel says it the moment it becomes true and the tray says it again when the job runs.
    Two statements of one sentence, so the sentence itself is what gets compared."""
    assert _js_string(TRAY_JS, "SAY_WHO") == T.SAY_WHO
    with pytest.raises(Exception) as refused:
        T.check_swaps([T.Slot(kind="picture", label=who, role=T.REPLACEMENT, file="x.png [input]")
                       for who in ("carguy", "picture2")])
    assert T.SAY_WHO in str(refused.value)


def test_the_example_answer_is_the_same_on_both_sides():
    """The field's placeholder and the refusal both show the shape of an answer, and a user who
    reads one and then the other is reading about the same thing."""
    assert "the man in the plaid shirt" in TRAY_JS
    with pytest.raises(Exception) as refused:
        T.check_swaps([T.Slot(kind="picture", label=who, role=T.REPLACEMENT, file="x.png [input]")
                       for who in ("a", "b")])
    assert "the man in the plaid shirt" in str(refused.value)


# --------------------------------------------------------------- the naming rule, one rule twice

def test_the_panel_types_in_the_alphabet_the_tray_accepts():
    """`LABEL_CHAR` in tray.js is the one-character form of `LABEL` in tray.py.

    The panel writes every label that exists, so the set it can emit has to be inside the set the
    enforcer takes. Compared as the character class's own text: `LABEL` is anchored and repeated and
    `LABEL_CHAR` matches one character, and stripping those two differences leaves the same body.
    """
    body = T.LABEL.pattern
    assert body.startswith("^[") and body.endswith("]+$"), (
        "tray.py's LABEL is no longer a plain anchored character class, so comparing it to the "
        "panel's by text no longer means anything. Compare them another way.")
    assert _js(TRAY_JS, "LABEL_CHAR") == f"/[{body[2:-3]}]/", (
        "the panel types names in a different alphabet than the tray accepts. tray.py's "
        "LABEL is the authority; tray.js's LABEL_CHAR has to be the same set.")


def test_the_panel_demands_the_letter_or_digit_the_tray_demands():
    """The second half of the rule: `-` alone is not a name. Both sides look for the same thing."""
    demanded = re.search(r'search\(r"(\[[^"]+\])", label\)', pathlib.Path(
        T.__file__).read_text(encoding="utf-8"))
    assert demanded, "tray.py no longer searches a character class for the letter-or-digit rule"
    assert _js(TRAY_JS, "LABEL_ALNUM") == f"/{demanded.group(1)}/"


def test_the_panel_holds_back_exactly_the_names_the_tray_reserves():
    reserved = _js(TRAY_JS, "RESERVED")
    assert reserved == "[" + ", ".join(f'"{w}"' for w in T.RESERVED) + "]", (
        f"tray.py reserves {T.RESERVED} and the panel holds back {reserved}. A word reserved on one "
        "side only is a name the panel offers and the queue refuses.")


# Every character the panel turns into a dash, written the way the JavaScript writes it so the
# declaration can be read as text, beside the character it actually stands for.
SEPARATORS = ((" ", " "), (r"\t", "\t"), (r"\n", "\n"), (r"\r", "\r"), (r"\f", "\f"),
              (r"\v", "\v"), ("_", "_"), (".", "."), ("/", "/"), ("\\\\", "\\"))


@pytest.mark.parametrize("written,character", SEPARATORS)
def test_every_character_the_panel_translates_becomes_a_legal_name(written, character):
    """The panel turns each of these into `-` as it is typed. Nothing it can produce that way may be
    a name the tray then turns away, which is the whole point of translating rather than warning."""
    declared = _js_string(TRAY_JS, "SEPARATORS")
    assert written in declared, (
        f"{character!r} is no longer one of the characters the panel translates, so this case is "
        "testing nothing")
    T.check_label("the-man", {})
    with pytest.raises(Exception) as bad:
        T.check_label(f"the{character}man", {})
    assert "letters, digits and dashes" in str(bad.value), (
        f"{character!r} is refused for some other reason than the alphabet, so translating it to a "
        "dash is not what makes this name legal")


def test_a_name_of_only_translated_separators_is_still_refused_by_both():
    """`___` types through as `---`, which is legal characters and not a name. The panel refuses it
    on commit and so does the tray; neither may let it past."""
    with pytest.raises(Exception) as bad:
        T.check_label("---", {})
    assert "letter or digit" in str(bad.value)
    assert "LABEL_ALNUM.test(name)" in TRAY_JS, (
        "the panel no longer checks for a letter or digit before taking a name, so a slot called "
        "--- can be typed and only refused at queue time")


def test_the_panel_folds_accents_rather_than_dropping_them():
    """A folded name has to be a name. `jose` with an acute becomes `jose`, which the tray takes."""
    assert 'normalize("NFD")' in TRAY_JS and r"\p{M}" in TRAY_JS, (
        "the panel no longer folds accents, so a Spanish name loses its letters instead of keeping "
        "them")
    T.check_label("jose", {})
    T.check_label("pinata", {})
    with pytest.raises(Exception):
        T.check_label("josé", {}), "the fold is needed because the accent itself is refused"


# ------------------------------------------------------ the prompt's grammar, one grammar twice

def test_the_browser_opens_and_closes_a_spoken_line_with_the_tray_s_own_marks():
    for name, literal in (("SPEAKS_OPEN", T.SPEAKS_OPEN), ("SPEAKS_CLOSE", T.SPEAKS_CLOSE)):
        declared = _js_string(PROMPT_JS, name)
        assert declared == literal, (
            f"the browser reads a spoken line as {declared} and tray.py reads it as "
            f"{literal!r}. A line drawn as speech in the box and read as prose by the compiler is "
            "worse than one drawn as prose.")


def test_a_mention_ends_at_the_same_character_in_both():
    r"""tray.py matches `[\w-]` under re.UNICODE, and the browser has no such class.

    Python's `\w` is letters, digits and underscore and does NOT include a combining mark, so the
    browser's class is `\p{L}\p{N}_-` with `\p{M}` deliberately absent. These three cases are where
    a wrong translation would show, and they pin the Python half of the claim the JS comment makes.
    """
    assert r"/@[\p{L}\p{N}_-]+/uy" in PROMPT_JS, (
        "the browser's mention class changed; the cases below no longer describe it")
    assert T.mentioned_labels("@café walks") == ["café"], "a letter with its own code point"
    assert T.mentioned_labels("@café walks") == ["cafe"], (
        "a combining accent is not a word character, so the mention stops in front of it on both "
        "sides")
    assert T.mentioned_labels("@some_thing") == ["some_thing"], (
        "an underscore is matched so the whole word is one mention nobody named, drawn as wrong and "
        "refused by that name, rather than @some plus text the user never wrote")


def test_the_browser_calls_a_mention_the_tray_cannot_answer_wrong():
    """Both halves of the same judgement: the panel paints it as wrong, the compiler refuses it.

    The lookup has to be case-blind on both sides, or a mention drawn as good is turned away.
    """
    assert "slots.get(p.label.toLowerCase())" in PROMPT_JS, (
        "the browser no longer resolves a mention case-blind, so @Car draws as wrong while the tray "
        "answers it")
    slots = T.read_tray('[{"kind": "picture", "label": "car", "file": "x.png [input]"}]')
    assert T.resolve_intent("@Car drives", slots).intent == "car drives"
    with pytest.raises(Exception) as bad:
        T.resolve_intent("@nobody drives", slots)
    assert "@nobody" in str(bad.value)


def test_the_browser_never_becomes_the_thing_that_makes_the_prompt_work():
    """The line the panel may not cross: it draws the sentence and never edits it.

    A mirror that rewrote the value would make the widget's text depend on a browser being present,
    and this pack's prompt is plain text that an API caller writes by hand. So the mirror is written
    to, and the textarea's value is only ever read.
    """
    assert "mirror.replaceChildren" in PROMPT_JS, "the mirror is no longer what gets written to"
    writes = re.findall(r"[\w.]*\.value\s*=(?!=)", PROMPT_JS)
    assert writes == ["this.ta.value ="], (
        "the picker inserting what the user chose is the one place this file may write the prompt, "
        f"and these writes were found instead: {writes}. Anything else drawing over the sentence by "
        "editing it would make the value depend on a browser being present.")
