"""The Main node's panel: the words it says, the rules it must not break, and the facts it borrows.

The panel is JavaScript and this is Python, so most of what follows reads the file as text. That is
the weaker kind of test and it is used only where nothing stronger exists. What is asserted here is
chosen so that reading the source settles it: a string that must appear word for word, a value that
must match a Python tuple, a call that must never be written.

**The report line's own branches are not settled here.** Eight sentences chosen from live facts
cannot be proved by reading text, so they are driven on the real canvas instead, in
`research/main_panel_states.mjs`, which types into the real box on a real ComfyUI and reads back
what the panel said. This file asserts that all eight strings exist and that nothing else is
written in their place.

**Three guards here answer rules the owner has raised more than once**, and each has a defect
planted for it in `research/contract_falsification.py`:

  * every field carries a visible label that survives typing, because a placeholder is gone at the
    first keystroke and the field is anonymous from then on;
  * the panel never derives a fact about the prompt, because a second copy of that parse is a
    second thing to keep right and the two would drift;
  * a shot count that cannot fit is dimmed and told what it needs, and it stays clickable, because
    the panel warns and the compiler is the one that refuses.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PANEL = REPO / "web" / "main.js"
JS = PANEL.read_text(encoding="utf-8")
PROMPT_JS = (REPO / "web" / "prompt.js").read_text(encoding="utf-8")
NODES = (REPO / "nodes.py").read_text(encoding="utf-8")


def _flat(source: str) -> str:
    """One sentence written across a `+` join is still one sentence. Both halves of this pack break
    long strings at the margin, and a test that read the raw file would be asserting about where the
    line wrapped."""
    return re.sub(r'[`"]\s*\n\s*\+\s*[`"]', "", source)


FLAT = _flat(JS)
FLAT_NODES = _flat(NODES)
# Every input the node really declares. The name can sit a comment or two below the opening bracket,
# which is where two of them are, so the walk allows anything that is not itself an argument.
DECLARED = set(re.findall(r'io\.\w+\.Input\(\s*(?:#[^\n]*\n\s*)*"(\w+)"', NODES))


# --------------------------------------------------------------------------- it is wired at all

def test_the_pack_ships_the_panel_and_comfyui_will_load_it():
    """`WEB_DIRECTORY` is how a pack ships frontend code: ComfyUI serves that folder and the browser
    loads every `.js` in it. A panel outside it is a file nobody runs."""
    from openh3ir import WEB_DIRECTORY

    assert (REPO / WEB_DIRECTORY / "main.js").is_file()
    assert 'app.registerExtension({\n  name: "openh3ir.main"' in JS


def test_the_panel_drives_widgets_that_are_really_on_the_node():
    """A panel that hides a widget by a name the schema does not have takes that control off the
    node and puts nothing in its place. Read off `define_schema`, which is what ComfyUI draws."""
    declared = DECLARED
    assert declared, "no inputs were found on the node, so this test is blind"
    listed = re.findall(r'"(\w+)"', re.search(r"const WIDGETS = \[(.*?)\];", JS, re.S).group(1))
    assert listed, "the panel names no widgets, so this test is blind"
    for name in listed:
        assert name in declared, f"the panel hides a widget the node does not declare: {name}"
    # And the other direction: every widget the panel reads by name has to be one it also hid, or
    # the node would draw a control the panel is quietly overwriting.
    for name in set(re.findall(r"this\.w\.(\w+)", JS)) | set(re.findall(r'this\.w\["(\w+)"\]', JS)):
        assert name in listed, f"the panel drives a widget it never hid: {name}"


def test_the_panel_leaves_the_node_alone_when_a_widget_it_needs_is_missing():
    """The two halves are versioned together and can still disagree after a partial copy. A panel
    that assumed a widget was there would take the node's whole surface away and leave nothing."""
    assert "const absent = WIDGETS.filter" in JS
    assert "drawing the plain node instead" in JS


def test_the_panel_hides_the_host_textarea_as_well_as_the_widget_row():
    """A multiline string is not drawn by LiteGraph: it is a real `<textarea>` the frontend keeps
    positioned over the canvas. Sizing its widget row to nothing leaves the element floating on top
    of the panel that replaced it, so the element itself has to be told to go.

    It is hidden and never removed, because its value is read and written through it and removing
    it would take the prompt out of every saved workflow.
    """
    body = JS[JS.index("function conceal("):JS.index("app.registerExtension")]
    assert "w.computeSize = () => [0, -4]" in body
    assert 'e.style.setProperty("display", "none", "important")' in body
    assert ".remove()" not in body, "the element carries the value, so it is hidden, never removed"


def test_the_board_is_never_hidden_along_with_the_widgets_it_replaced():
    """The board is itself a widget, so a loop that hides every widget on the node hides the board
    too and leaves an empty box with sockets on it.

    MEASURED on the live canvas: it happened on every path that configures an existing node -- an
    undo, a workflow opened from disk, a workflow dragged in off a rendered video -- and never on a
    node added by hand, because the board is added after the first hiding loop has already run and
    only a configure runs a second one.

    Both loops are asserted, not just the one that broke, because the same line in either place
    brings the same empty node back.
    """
    hides = [line.strip() for line in JS.splitlines() if "conceal(w)" in line and "for (" in line]
    assert len(hides) == 2, f"expected two hiding loops, found {len(hides)}: {hides}"
    for line in hides:
        assert "w.name !== BOARD" in line, f"this loop hides the board itself: {line}"
    assert 'const BOARD = "oh3m_panel";' in JS
    assert "this.addDOMWidget(BOARD," in JS, "the board must be added under the name the loops skip"


# ------------------------------------------------- every field keeps a label after you type

ROW_LABELS = ["spoken in", "seconds", "frame shape", "resolution", "shots", "invention", "music"]
FOOT_LABELS = ["brief seed", "reference size", "writing effort"]


@pytest.mark.parametrize("label", ROW_LABELS)
def test_every_row_carries_a_visible_label(label):
    """The rule this whole panel exists for. A placeholder is gone at the first keystroke, so a
    field labelled only by one is anonymous from then on. Eight labels are drawn to the left of
    their field and stay there while you type."""
    assert f'this.row("{label}"' in JS, f"no row is labelled {label!r}"


@pytest.mark.parametrize("label", FOOT_LABELS)
def test_every_bottom_row_item_carries_a_visible_label(label):
    assert f'this.footItem("{label}"' in JS, f"nothing in the bottom row is labelled {label!r}"


def test_the_label_is_a_real_element_and_not_a_placeholder():
    """A label that is a placeholder attribute disappears the moment somebody types. Every label on
    this panel is its own element beside the field, so read the row builder and prove it."""
    body = JS[JS.index("  row(label, widget"):JS.index("  footItem(")]
    assert 'el("span", { class: "oh3m-label", textContent: label })' in body
    assert "placeholder" not in body


def test_the_prompt_box_is_labelled_by_a_heading_rather_than_by_its_placeholder():
    """The one field that cannot take a label beside it, because it is the whole width of the panel.
    It gets the heading instead, and the heading is what survives typing."""
    assert 'el("div", { class: "oh3m-sec", textContent: "your prompt" })' in JS
    # And the placeholder is still the schema's own, word for word, so an install with no `web/`
    # reads the same thing.
    said = "one plain sentence, what happens, with @ for anything in the tray"
    assert said in FLAT
    assert said in re.sub(r'"\s*\n\s*"', "", NODES)


# ------------------------------------------------- the words, exactly as the design wrote them

@pytest.mark.parametrize("said", [
    "Main",
    "one prompt to a ready H3 job",
    "your prompt",
    "Say what happens. Type @ to name anything in the tray, or to lock a spoken line.",
    "the video",
    "How long it runs, what shape and size it is, and how many shots.",
    "the writing",
    "What the writer decides where your prompt leaves things open.",
])
def test_the_panel_says_what_the_design_says(said):
    assert said in FLAT, f"the panel does not say {said!r}"


@pytest.mark.parametrize("said", [
    "nothing written yet",
    "No Media node is connected, so the video is written from your words alone.",
    "Type @ to name one in the prompt.",
    "is not in the tray. Rename a slot on the Media node, or change the name here.",
    "are not in the tray. Rename those slots on the Media node, or change the names here.",
    "names nothing. Wire an OpenH3-IR Media node into media.",
    "One spoken line was never closed. Close it with a quote mark and a bracket.",
])
def test_every_state_of_the_report_line_is_written(said):
    """Eight sentences, one box. Which one is chosen is proved on the live canvas; that each exists
    at all is proved here, so a rewrite cannot quietly drop one."""
    assert said in FLAT, f"the report line can never say {said!r}"


@pytest.mark.parametrize("said", [
    "Type any number instead. H3 was trained between 5 and 15 seconds.",
    "Bigger is sharper, slower, and eats VRAM in proportion. Type any number instead.",
    "auto leaves the edit to the writer. A number is kept exactly.",
    "Ambient and physical sound are always written. This decides the background music.",
    "The language every locked line is spoken in. For a language not listed, name it in the prompt.",
    "The same prompt and the same seed give the same brief. Change it for a different take.",
    "ComfyUI's own control. It decides whether the seed moves on the next run.",
])
def test_every_list_teaches_what_the_row_alone_cannot_say(said):
    assert said in FLAT, f"no list says {said!r}"


def test_the_music_row_replaces_a_double_negative_with_two_spoken_values():
    """The boolean underneath is `silent`, where true means no music. `no music: false` is a double
    negative on a canvas, so the row is `music` and its values are words."""
    assert 'this.row("music", "silent")' in JS
    assert '["the writer decides", true]' in JS
    assert '["none", false]' in JS
    # And the schema keeps its own name, because that is what a graph without `web/` shows.
    assert 'display_name="no music"' in NODES


def test_the_resolution_row_says_h3s_own_size_rather_than_a_bare_zero():
    """Zero megapixels is not a size a person can read. It is H3's own geometry, and the list says
    which pixels that is."""
    assert '"H3\'s native"' in JS
    assert '[0, "768 on the short edge"]' in JS
    assert 'return n > 0 ? `${n.toFixed(1)} megapixels` : "H\'s native";' not in JS  # a real typo guard
    assert "megapixels`" in JS, "a number without its unit is not a size"


# ------------------------------------------------- the values are the schema's own words

def _tuple(name: str) -> tuple[str, ...]:
    src = (REPO / "h3ir_client.py").read_text(encoding="utf-8")
    body = re.search(rf"^{name} = \((.*?)\)$", src, re.S | re.M).group(1)
    return tuple(re.findall(r'"([^"]+)"', body))


def test_the_frame_shapes_are_the_schema_s_own_list():
    listed = re.findall(r'"([\d:]+)"', re.search(r"const SHAPES = \[(.*?)\];", JS, re.S).group(1))
    assert tuple(listed) == _tuple("ASPECTS")


@pytest.mark.parametrize("const,pyname", [("INVENTION", "CREATIVITY"), ("SIZING", "SIZING"),
                                          ("EFFORT", "EFFORT")])
def test_every_option_a_list_offers_is_a_value_the_schema_accepts(const, pyname):
    """A panel that offers a word the schema does not know writes a value the node refuses, and the
    graph fails at queue time with the panel still showing the word it chose."""
    block = re.search(rf"const {const} = \[(.*?)\];", JS, re.S).group(1)
    words = tuple(m.group(1) for m in re.finditer(r'\[\s*"([^"]+)"', block))
    assert words == _tuple(pyname), f"{const} offers {words}, the schema accepts {_tuple(pyname)}"


def test_the_seconds_offered_are_inside_the_band_the_note_names():
    """The note says H3 was trained between 5 and 15 seconds, so every round number offered has to
    be inside it or the note is lying about the list under it."""
    offered = [float(n) for n in
               re.findall(r"[\d.]+", re.search(r"const SECONDS_OFFERED = \[(.*?)\];", JS).group(1))]
    assert offered, "no lengths are offered, so this test is blind"
    assert min(offered) >= 5 and max(offered) <= 15


def test_the_shot_ceiling_is_the_one_the_compiler_enforces():
    """Offering an eleventh shot would promise a cut the engine drops without saying so."""
    from openh3ir.h3ir_client import MAX_SHOTS

    assert f"const MAX_SHOTS = {MAX_SHOTS};" in JS


def test_the_arithmetic_the_shot_list_shows_is_the_one_the_tooltip_states():
    """1.2 seconds a shot is a fact the node's own tooltip states. The panel repeats it to dim a
    count, so if the two ever disagree the dimming is wrong."""
    assert "const SECONDS_PER_SHOT = 1.2;" in JS
    assert "Every shot needs 1.2 seconds" in NODES


def test_a_count_that_cannot_fit_is_dimmed_and_told_what_it_needs_and_stays_clickable():
    """Drawn as an offer, never as a claim. The panel warns; the compiler refuses. A list that
    removed the row, or made it inert, would be the panel deciding on the compiler's behalf."""
    body = JS[JS.index("  shotList()"):JS.index("  wordList(")]
    assert "dim: !fits" in body
    assert 'note: fits ? "" : `needs ${needs.toFixed(1)} s`' in body
    # The click is attached unconditionally: no branch anywhere in the row builder drops it.
    assert re.search(r"onclick: \(\) => this\.set\(\"shots\", String\(n\)\) \}\)", body)
    assert "disabled" not in body and "pointer-events" not in body


# ------------------------------------------------- it borrows the parse, it does not repeat it

def test_the_panel_derives_no_fact_about_the_prompt_itself():
    """`prompt.js` parses the text and walks the media link. A second copy of either would be a
    second thing to keep right, and the mentions drawn in the box would drift from the line that
    reports on them."""
    assert 'import { attachPrompt, promptFacts } from "./prompt.js";' in JS
    # Comments are excluded: the panel is allowed to SAY why it does not do a thing.
    code = [ln for ln in JS.splitlines() if not ln.lstrip().startswith(("*", "/*", "//"))]
    flat_code = "\n".join(code)
    for banned in ("@speaks", "RegExp(", "MENTION", "JSON.parse", "origin_id", "getNodeById"):
        assert banned not in flat_code, f"the panel parses the prompt itself: {banned}"
    # The precise rule, rather than a list of spellings somebody could get around. A first draft
    # banned the literal `@speaks(` and a planted defect walked straight past it by writing the
    # bracket as a regex escape. The text in the box is only ever read for three things: handed to
    # the parse, compared with the widget, or written to the widget.
    allowed = ("promptFacts(", "this.w.intent.value", "this.box.value = ")
    for line in code:
        if "this.box.value" not in line:
            continue
        assert any(a in line for a in allowed), (
            "the panel reads the text in the box for something other than handing it to "
            f"`promptFacts`: {line.strip()}")


def test_prompt_js_exports_everything_the_panel_imports():
    for name in ("attachPrompt", "promptFacts"):
        assert f"export function {name}(" in PROMPT_JS, f"prompt.js does not export {name}"


def test_the_report_can_tell_an_unconnected_tray_from_an_empty_one():
    """Two different sentences, and the slot list answers `[]` to both. The link itself is what says
    which, so the fact is computed where the link is walked."""
    assert "const connected = Boolean(trayState(node));" in PROMPT_JS
    assert "connected," in PROMPT_JS
    assert "f.connected" in JS


def test_the_panel_hands_prompt_js_its_own_textarea():
    """The panel owns the box, because a host widget cannot sit inside a panel and still look like
    one surface. `prompt.js` takes whatever textarea it is handed."""
    assert "attachPrompt(panel.box, this)" in JS
    assert "export function attachPrompt(textarea, node)" in PROMPT_JS
    # And the mirror is positioned from `offsetLeft`, which only lines up while the mirror and the
    # textarea share an offset parent. A wrapper between them would have to be positioned too.
    assert "this.root.append(this.box);" in JS
    assert "position:relative" in JS[JS.index("const CSS = "):]


# ------------------------------------------------- the shape of the thing

def test_the_prompt_box_is_the_only_element_that_grows():
    """Height drags on this node, which is the one departure from the other three panels, and every
    pixel it gains goes to the prompt. Anything else that could grow would take room from it."""
    css = JS[JS.index("const CSS = "):]
    # Only the panel's own column is read. A row inside a floating list grows within that list,
    # which is absolutely positioned and cannot take a pixel from the box.
    listed = css[css.index(".oh3m-list{"):]
    column = css.replace(listed, "")
    growers = re.findall(r"\.(oh3m-[a-z]+)\{[^}]*flex:1 1 auto", column)
    assert growers == ["oh3m-box"], f"more than the prompt box can grow: {growers}"
    assert "const BOX_MIN = 124;" in JS


def test_the_quiet_lines_are_pinned_so_only_the_prompt_moves():
    """A quiet line that reflows from two rows to three as the node narrows moves every row under
    it. They are pinned in `em`, so the row count is the decision and the pixels follow the type."""
    css = JS[JS.index("const CSS = "):]
    lead = re.search(r"\.oh3m-seclead\{([^}]*)\}", css).group(1)
    # One row, MEASURED at 520, 470 and 430: none of the three ever wraps.
    assert "min-height:1.45em" in lead
    msg = re.search(r"\.oh3m-msg\{([^}]*)\}", css).group(1)
    assert "min-height:2.8em" in msg


def test_the_minimum_height_is_the_one_the_prompt_box_forces():
    """The design drew the resting size and left the floor to whatever the box needs.

    MEASURED on the live canvas at 520 and at 430: at 719 the prompt box is exactly on its own 124
    floor and nothing is clipped, and below 719 nothing moves any more. At the resting 773 the box
    is 178, so 54 pixels of prompt are what dragging the node shorter gives back.
    """
    min_h = int(re.search(r"const MIN_H = (\d+);", JS).group(1))
    extra = int(re.search(r"const NODE_H_EXTRA = (\d+);", JS).group(1))
    box = int(re.search(r"const BOX_MIN = (\d+);", JS).group(1))
    node_h = int(re.search(r"const NODE_H = (\d+);", JS).group(1))
    assert min_h == 719
    # The resting height is above the floor, or the node would arrive with no room to give.
    assert node_h > min_h
    # And the floor still leaves the box its own minimum.
    assert min_h - extra > box


def test_the_node_is_the_size_the_design_drew():
    for line in ("const NODE_W = 520;", "const NODE_H = 773;", "const MIN_W = 430;",
                 "const MIN_H = 719;"):
        assert line in JS, f"the geometry moved: {line}"


def test_the_panel_is_exactly_the_node_minus_its_sockets():
    """The board is the node's width, whatever it has been dragged to, and the height left after the
    seven output sockets and the host's own padding."""
    node_h = int(re.search(r"const NODE_H = (\d+);", JS).group(1))
    extra = int(re.search(r"const NODE_H_EXTRA = (\d+);", JS).group(1))
    assert node_h - extra == 595, "the panel is no longer the 595 the design drew"


def test_the_board_never_takes_a_width_from_the_frontend():
    """Measured on the Director: the frontend writes a `width` onto every widget from a layout pass,
    and for a full-bleed board that number is the content width, not the box. It squeezed a field to
    eleven pixels and never recovered."""
    assert 'Object.defineProperty(w, "width", { get: () => null' in JS


def test_everything_that_opens_floats():
    """A list that pushed would change the node's height every time somebody opened one."""
    css = JS[JS.index("const CSS = "):]
    rule = re.search(r"\.oh3m-list\{([^}]*)\}", css).group(1)
    assert "position:absolute" in rule
    assert "z-index" in rule
    assert JS.count('this.list = el("div", { class: "oh3m-list" })') == 1, (
        "only one thing can be open, so there is one element")


# ------------------------------------------------- the file survives being edited

def test_no_backtick_reaches_the_css_block():
    """The CSS is one JavaScript template literal, so a pair of backticks anywhere inside it ends
    the string and the file stops parsing.

    MEASURED three times on the Setup panel, which is why this is a test and not a comment. Every
    time it took the whole panel off the canvas and left the node bare, and every time
    `node --check` passed the file: only importing the module catches it.
    """
    region = JS[JS.index("const CSS = ") + len("const CSS = "):JS.index("/** Take a host widget")]
    ticks = region.count("`")
    assert ticks == 2, (
        f"the CSS block holds {ticks} backticks and it may only hold the two that open and close "
        "it. A pair inside ends the string early and the whole file stops parsing, which takes the "
        "panel off the canvas with no error anybody sees.")


def test_the_panel_is_a_module_that_actually_parses():
    """The check that catches what `node --check` does not: a file that does not parse ships a node
    with no panel on it and no error anybody sees."""
    import subprocess

    body = "\n".join(l for l in JS.splitlines() if not l.startswith("import "))
    probe = subprocess.run(["node", "--input-type=module", "-e", body],
                           capture_output=True, text=True)
    assert "SyntaxError" not in probe.stderr, (
        f"the panel does not parse: {probe.stderr.strip().splitlines()[:3]}")


def test_no_em_dash_reaches_anything_a_person_reads_on_this_panel():
    """The owner treats an em dash as a machine tell, so none may appear in a string this panel
    shows. Comment lines are excluded the same way the other panels' rule excludes them."""
    offenders = [ln.strip() for ln in JS.split("\n")
                 if "—" in ln and not ln.lstrip().startswith(("*", "/*", "//"))]
    assert not offenders, "an em dash reached the panel's own text: " + " | ".join(offenders)[:300]


def test_no_dash_is_used_as_punctuation_in_anything_a_person_reads():
    """A hyphen joining two words is a word. A dash standing between two clauses is a machine tell,
    and it reads as one whether it is long or short."""
    offenders = []
    for said in re.findall(r'textContent: "([^"]{4,})"', FLAT) + re.findall(r'say\("([^"]{4,})"',
                                                                           FLAT):
        if re.search(r"\s[-–—]\s", said):
            offenders.append(said)
    assert not offenders, "a dash is doing a comma's job: " + " | ".join(offenders)[:300]


def test_the_sentences_a_person_reads_are_written_the_short_way():
    """The house rule for everything a person reads: at most 20 words for an instruction and 25 for
    an explanation. Measured over the report line and the list notes, which are the ones somebody
    reads under pressure."""
    said = re.findall(r'say\(\s*`?([^`"]{20,}?)[`"]', FLAT) + re.findall(r'this\.note\("([^"]+)"',
                                                                        FLAT)
    assert said, "no sentences were found, so this test is blind"
    for line in said:
        for sentence in re.split(r"(?<=[.?]) ", line):
            words = [w for w in sentence.split() if w.strip(".,")]
            assert len(words) <= 25, f"{len(words)} words in one sentence: {sentence}"


def test_the_panel_never_names_a_token_or_a_field_at_a_person():
    """Nothing a person reads is an enum, a token or a field name. The one exception is `auto`,
    which is the schema's own word and the value the row shows."""
    shown = re.findall(r'textContent: "([^"]+)"', FLAT)
    for word in shown:
        assert "_" not in word, f"a field name reached the canvas: {word}"
