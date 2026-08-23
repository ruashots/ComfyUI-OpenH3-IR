"""The Setup node's panel: its words, the rules it must not break, and the two halves it joins.

The panel is JavaScript and this is Python, so most of what follows reads the file as text. That is
the weaker kind of test and it is used only where nothing stronger exists: `tests/test_in_process.py`
asserts about payloads because a payload can be produced here, and a DOM board cannot. What IS
asserted here is chosen so that reading the source is enough to settle it -- a string that must
appear word for word, a call that must never be written, a list that must match one in Python.

**Three of these guard rules the owner has raised more than once**, and each has a defect planted for
it in `research/contract_falsification.py`:

  * every field carries a visible label that survives typing, because a placeholder is gone at the
    first keystroke and the field is anonymous from then on;
  * the credential never becomes a widget value, because widget values are written into the saved
    workflow and into the graph inside every rendered video;
  * `installed` is read before `ok`, because the vision route answers `installed: false` with
    `ok: false` and reading `ok` alone paints a red verdict about a model nobody ever asked.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
JS = (REPO / "web" / "setup.js").read_text(encoding="utf-8")
PANEL = REPO / "web" / "setup.js"


# --------------------------------------------------------------------------- it is wired at all

def test_the_pack_ships_the_panel_and_comfyui_will_load_it():
    """`WEB_DIRECTORY` is how a pack ships frontend code: ComfyUI serves that folder and the browser
    loads every `.js` in it. A panel outside it is a file nobody runs."""
    from openh3ir import WEB_DIRECTORY

    assert (REPO / WEB_DIRECTORY / "setup.js").is_file()
    assert 'app.registerExtension({\n  name: "openh3ir.setup"' in JS


def test_the_panel_drives_widgets_that_are_really_on_the_node():
    """A panel that hides a widget by a name the schema does not have takes that control off the
    node and puts nothing in its place. Read off `define_schema`, which is what ComfyUI draws."""
    source = (REPO / "nodes.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'io\.\w+\.Input\(\s*\n?\s*"(\w+)"', source))
    assert declared, "no inputs were found on the node, so this test is blind"
    for name in re.findall(r'"(\w+)"[,\]]', re.search(r"const wanted = \[(.*?)\];", JS, re.S).group(1)):
        assert name in declared, f"the panel hides a widget the node does not declare: {name}"
    for name in re.findall(r'\{ w: "(\w+)"', JS):
        assert name in declared, f"the panel drives a widget the node does not declare: {name}"


def test_the_panel_leaves_the_node_alone_when_a_widget_it_needs_is_missing():
    """The two halves are versioned together and can still disagree after a partial copy. A panel
    that assumed a widget was there would take the node's whole surface away and leave nothing."""
    assert "const absent = wanted.filter" in JS
    assert "drawing the plain node instead" in JS


# ------------------------------------------------------- the rule the owner has raised twice

def _row(anchor: str) -> str:
    """One `el("div", { class: "oh3s-wrow" ... })` call, from its anchor to its balanced close.

    Read as a balanced expression rather than by a regex over the whole file, because the weaker
    check let a real defect through: the address label was deleted from its own row and the test
    still passed, because the word `address` labels a field in the bottom row's control as well.
    A label somewhere else on the panel is not a label on this field.
    """
    start = JS.index(anchor)
    depth, i = 0, JS.index("el(", start)
    while i < len(JS):
        if JS[i] == "(":
            depth += 1
        elif JS[i] == ")":
            depth -= 1
            if depth == 0:
                return JS[start:i + 1]
        i += 1
    raise AssertionError(f"the row starting at {anchor!r} never closes")


@pytest.mark.parametrize("anchor,label", [
    ("this.addrRow = el(", "endpoint"),
    ("this.modelRow = el(", "model"),
])
def test_the_two_typed_fields_carry_a_label_inside_their_own_row(anchor, label):
    """A placeholder disappears at the first keystroke and the field is anonymous from then on. So
    every field on this hand-drawn panel has a label element inside its own row, and the grey text
    in a field is an example rather than a name."""
    row = _row(anchor)
    assert f'class: "oh3s-wlabel", textContent: "{label}"' in row, \
        f"the {label!r} field has no label drawn inside its own row: {row[:200]}"


def test_every_file_row_carries_its_own_label():
    """The five are built in a loop, so one label serves them all. What has to be true is that the
    loop draws it from the row's own entry rather than leaving the value to name itself."""
    row = _row("      const row = el(")
    assert 'class: "oh3s-wlabel", textContent: f.label' in row, \
        f"a file row draws no label of its own: {row[:200]}"
    assert {f for f in re.findall(r'label: "([a-z0-9 ]+)"', JS)} >= \
        {"ref2va", "fl2va", "clip", "vae", "audio vae"}


def test_the_credential_row_is_labelled_even_though_it_is_not_a_wrow():
    """It is the one row whose label sits above it rather than beside it, because it carries a note
    as well. It is still a label, and it is still always drawn."""
    assert 'el("span", { textContent: "api key" })' in JS
    assert "Only if your endpoint asks for one. It never goes into the workflow." in JS


def test_the_endpoint_field_shows_an_example_and_still_has_its_label():
    """The one field where the two are easiest to confuse: the grey text is a real address, so
    without a label beside it somebody would read it as the name of the field.

    The example is not a proposal. It is the shape a URL has to have -- a scheme, a host, a port and
    the /v1 this pack refuses a URL without -- and it is quoted from the compiler's own default
    rather than invented here.
    """
    assert "placeholder: EXAMPLE" in JS, "the endpoint field lost its example"
    assert 'const EXAMPLE = "http://127.0.0.1:8000/v1";' in JS
    assert re.search(r'class: "oh3s-wlabel", textContent: "endpoint"', JS), \
        "the endpoint field lost the label that survives typing"


def test_the_endpoint_label_is_the_word_the_panel_already_uses_everywhere_else():
    """The panel's own messages say endpoint in every one of them. The label was the one place
    disagreeing with the rest of it.

    And it is never "openai endpoint". Somebody running Ollama on their own machine reads that as
    needing an account with OpenAI, and that failure stops them cold. Not knowing the API shape only
    produces an error they can act on, which is the smaller of the two.
    """
    labels = set(re.findall(r'class: "oh3s-wlabel", textContent: "([^"]+)"', JS))
    assert "endpoint" in labels and "address" not in labels, (
        f"the endpoint field is labelled from {sorted(labels)}, and `address` is the only word on "
        "this panel that disagrees with the panel")
    for label in labels:
        assert "openai" not in label.lower(), f"a label claims who you buy from: {label!r}"


def test_the_openai_fact_is_a_sentence_rather_than_a_label():
    """It is a real fact and somebody needs it. A sentence saying a server speaks the OpenAI API is
    a fact about a protocol; a label reading "openai endpoint" is a claim about who you buy from."""
    assert "Any server that speaks the OpenAI API works." in re.sub(r'"\s*\n\s*\+ "', "", JS), \
        "the group's quiet line no longer says which servers work"


def test_no_label_is_only_a_placeholder():
    """Every `placeholder:` in this panel belongs to a field that also has a label or a control word
    beside it. Listed rather than inferred, so adding a field forces a decision about its label."""
    placeholders = set(re.findall(r'placeholder: "(.*?)"', JS))
    allowed = {"nothing picked yet",        # the model row, labelled `model`
               "paste the key",             # the key row, labelled `api key`
               "http://another-machine:8420"}  # the bottom row's address, labelled `address`
    assert placeholders <= allowed, (
        f"a new placeholder appeared with no label decided for it: {sorted(placeholders - allowed)}")


# --------------------------------------------------------------------------- the credential

def test_the_api_key_never_becomes_a_widget_value():
    """Widget values are written into the saved workflow AND into the graph inside every rendered
    video, which the Director's own documentation calls a feature. For a paid API key that same
    mechanism is a leak, and people share workflows by dropping a picture into a chat.

    So the key is written to ComfyUI's per-user folder and read from there by the routes. Nothing in
    this file may assign it to a widget.
    """
    written = re.findall(r"this\.w\.(\w+)\.value\s*=\s*([^;\n]+)", JS)
    assert written, "nothing writes a widget any more, so this test is blind"
    # WHAT is written, not which widget it is written to. The first draft of this only looked at the
    # widget's name, so planting `this.w.llm_model.value = key` walked straight past it.
    for name, value in written:
        assert not re.search(r"\bkey\b|savedKey|keyIn", value), (
            f"the credential is written into the {name} widget, which puts it in every saved "
            f"workflow and in the graph inside every rendered video: {name}.value = {value}")
    assert not re.search(r"widgets_values|serialize\(\)", JS.split("const CSS")[0]), \
        "the panel touches what a save writes"


def test_the_credential_is_stored_where_the_python_that_uses_it_reads_it():
    """A test that reads the key by one path while the queue reads it by another can pass while the
    real job fails. Both halves name the same file."""
    from openh3ir import compiler as C

    assert f'const KEYS = "{C.KEY_STORE}"' in JS, (
        f"the panel and compiler.py disagree about where a key lives: the panel says "
        f"{re.search(r'const KEYS = .(.*?).;', JS).group(1)!r}, Python says {C.KEY_STORE!r}")


def test_the_two_stores_are_the_only_places_the_panel_writes():
    """Both are under ComfyUI's own per-user folder, beside the Director's saved directions. Neither
    ever reaches a workflow."""
    calls = set(re.findall(r'(?<!async )writeJson\((\w+),', JS)) - {"path"}   # not its own definition
    assert calls == {"SEEN", "KEYS"}, f"the panel writes somewhere new: {calls}"


def test_the_key_is_keyed_on_the_address_the_way_python_keys_it():
    """The panel saves under the trimmed address with no trailing slash, and `endpoint_key` looks it
    up by the same string. A slash on one side and not the other is a key that is never found, and
    the failure is a 401 nobody can explain."""
    from openh3ir import compiler as C

    assert 'function tidy(url) { return String(url || "").trim().replace(/\\/+$/, ""); }' in JS
    assert C.endpoint_key("   ") == ""


# --------------------------------------------------------------------------- three answers

def test_the_chip_reads_installed_before_it_reads_ok():
    """The one place this panel can get it badly wrong. The vision route answers `installed: false`
    with `ok: false` when there is no compiler, so reading `ok` on its own paints a red "vision off"
    about a model nobody ever asked."""
    look = JS[JS.index("  async look("):JS.index("  // ---------------------------------------------------------- what this ComfyUI remembers")]
    installed = look.index("got.installed === false")
    assert installed < look.index("got.ok === true"), \
        "the chip reads ok before it reads installed"
    assert installed < look.index("got.ok === false"), \
        "the chip reads ok before it reads installed"


def test_the_vision_route_is_never_asked_about_an_empty_model():
    """An empty model also answers `ok: false`, which is the same trap wearing different clothes."""
    assert re.search(r"async look\(url, id, run\) \{\s*\n\s*if \(!id\) return;", JS), \
        "the vision check can be started with no model named"


def test_a_check_that_did_not_finish_is_never_painted_as_a_model_that_cannot_see():
    """Three answers, not two. Null means the model was never asked, so nothing is known, and it is
    grey. That happens more often than a real no."""
    assert '  unknown: { text: "no answer", cls: "" },' in JS, \
        "the chip lost its third state, or that state gained a colour"
    assert '  off: { text: "vision off", cls: "oh3s-blind" },' in JS


def test_the_five_chip_words_are_the_ones_that_were_specified():
    assert set(re.findall(r'text: "([a-z ]+)", cls:', JS)) == {
        "not checked", "checking", "vision on", "vision off", "no answer"}


# --------------------------------------------------------------------------- what it says

@pytest.mark.parametrize("said", [
    "Point this node at the language model that writes your brief. Pick the five H3 files that "
    "render it.",
    "This model writes your brief. It also reads every picture and clip on the Media node.",
    "Pick the five H3 files. They come from your ComfyUI's own model folders.",
    "Only if your endpoint asks for one. It never goes into the workflow.",
    "no key. That endpoint does not ask for one.",
    "Type any name in the field above. The list is what this server reports.",
    "OpenH3-IR writes your brief. Give it an address only if you run it on another machine.",
    "Empty. OpenH3-IR runs in this ComfyUI.",
    "This ComfyUI still renders. Only the writing moves.",
    "Type the address of your language model. Then press test.",
    "Type the address of your language model first.",
    "The address now starts with http://.",
    "That address answers at /v1. The field now shows the full address.",
    "Still asking. A server that loads a model can take a minute.",
    "Stopped. Nothing changed.",
    "That server answers and serves no models. Load a model on it.",
    "The server answers. It will not list its models. Type the model name in the field.",
    "That address wants a key. Type one in. Then press test again.",
    "Both VAE rows hold the same file. H3 needs a different file for each one.",
    "None of the five files are on this ComfyUI. Pick your own.",
    "This ComfyUI did not answer the test. Restart ComfyUI.",
])
def test_the_panel_says_the_words_that_were_specified(said):
    """Every sentence on this panel was written and approved word for word. Held here so a tidy-up
    that reads better to whoever is editing cannot quietly replace one."""
    flat = re.sub(r'"\s*\n\s*\+ "', "", JS)
    assert said in flat, f"this sentence is not on the panel any more: {said}"


def test_no_backtick_reaches_the_css_block():
    """The CSS is one JavaScript template literal, so a pair of backticks anywhere inside it ends the
    string and the file stops parsing.

    MEASURED twice, which is why this is a test and not a comment. Both times it took the whole panel
    off the canvas and left the node bare, and both times `node --check` passed the file: only
    importing the module catches it. The second time I had already written the warning into the file
    and wrote a backtick into the very comment underneath it.
    """
    # The region is bounded by the two things around the literal, NOT by the first backtick inside
    # it. A first draft looked for the first backtick and then checked there was none before it,
    # which is true of any string and caught nothing: the very next edit put two backticks in a CSS
    # comment and this passed.
    region = JS[JS.index("const CSS = ") + len("const CSS = "):JS.index("app.registerExtension")]
    ticks = region.count("`")
    assert ticks == 2, (
        f"the CSS block holds {ticks} backticks and it may only hold the two that open and close it. "
        "A pair inside ends the string early and the whole file stops parsing, which takes the panel "
        "off the canvas with no error anybody sees.")


def test_the_panel_is_a_module_that_actually_parses():
    """The check that catches what `node --check` does not. Read as a whole rather than by pattern:
    a file that does not parse ships a node with no panel on it and no error anybody sees."""
    import subprocess

    probe = subprocess.run(["node", "--input-type=module", "-e",
                            PANEL.read_text(encoding="utf-8").split("import {")[0] + "\n"
                            + "\n".join(l for l in PANEL.read_text(encoding="utf-8").splitlines()
                                         if not l.startswith("import "))],
                           capture_output=True, text=True)
    assert "SyntaxError" not in probe.stderr, (
        f"the panel does not parse: {probe.stderr.strip().splitlines()[:3]}")


def test_no_em_dash_reaches_anything_a_person_reads_on_this_panel():
    """The owner treats an em dash as a machine tell, so none may appear in a string this panel
    shows. Comment lines are excluded the same way the Director's rule excludes them."""
    offenders = [ln.strip() for ln in JS.split("\n")
                 if "—" in ln and not ln.lstrip().startswith(("*", "/*", "//"))]
    assert not offenders, "an em dash reached the panel's own text: " + " | ".join(offenders)[:300]


def test_the_sentences_a_person_reads_are_written_the_short_way():
    """The house rule for everything a person reads: at most 20 words for an instruction and 25 for
    an explanation. Measured over the panel's own report lines, which are the ones somebody reads
    under pressure."""
    flat = re.sub(r'"\s*\n\s*\+ "', "", JS)
    for said in re.findall(r'this\.(?:say|write_msg)\(\s*`?([A-Z][^`"]{20,}?)[`"]', flat):
        for sentence in re.split(r"(?<=[.?]) ", said):
            words = [w for w in sentence.split() if w.strip(".,")]
            assert len(words) <= 25, f"{len(words)} words in one sentence: {sentence}"


# ------------------------------------------------- the panel never cuts its own words

def test_the_report_is_a_box_that_wraps_rather_than_a_line_that_truncates():
    """An instruction does not live in a tooltip. Nobody hovers a red line they did not expect.

    The report line used to be one row with `text-overflow: ellipsis`, so
    `Nothing answers at 127.0.0.1:9. Start your language model. If it is running, check the port
    number.` lost its second instruction. It is a box of fixed rows now and it wraps.
    """
    css = JS[JS.index("const CSS = "):]
    msg = css[css.index(".oh3s-msg{"):]
    msg = msg[:msg.index("}")]
    assert "text-overflow" not in msg and "nowrap" not in msg, \
        f"the report line truncates again: {msg}"
    assert "min-height" in msg, "the report box no longer reserves the rows it needs"


def test_the_report_boxes_are_pinned_to_the_rows_the_longest_message_needs():
    """Three rows beside the model and two under the files, measured at 430 on the canvas. Stated in
    em so the row count is the decision and the pixels follow the element's own type."""
    css = JS[JS.index("const CSS = "):]
    assert re.search(r"\.oh3s-msg\{[^}]*min-height:4\.2em", css, re.S), \
        "the model report box is not three rows"
    assert ".oh3s-sayrow.oh3s-files .oh3s-msg{min-height:2.8em;}" in css, \
        "the files report box is not two rows"


def test_every_quiet_line_is_pinned_so_none_of_them_reflows():
    """A line that wraps to a different number of rows at a different width is a line negotiating for
    room, and it is what put a band of empty space above each heading. Every one of them is pinned to
    the rows it needs at 430, so the content never changes height and the spare collects above the
    rule at the bottom."""
    css = JS[JS.index("const CSS = "):]
    for selector in (".oh3s-lead", ".oh3s-seclead", ".oh3s-klabel"):
        rule = css[css.index(selector + "{"):]
        rule = rule[:rule.index("}")]
        assert "min-height" in rule, f"{selector} is not pinned, so it reflows and moves the height"
    assert ".oh3s-seclead.oh3s-one{min-height:1.45em;}" in css, \
        "the second group's lead lost its own row count"


def test_the_spare_space_is_above_the_rule_and_never_above_a_heading():
    """A heading belongs to the rows under it. Space above one pushes it away from what it heads, so
    it reads as a hole. The bottom row is the one thing here that is not pinned: its auto top margin
    sticks it to the bottom, so every spare pixel collects above its rule."""
    css = JS[JS.index("const CSS = "):]
    foot = css[css.index(".oh3s-foot{"):]
    foot = foot[:foot.index("}")]
    assert "margin-top:auto" in foot, "the bottom row no longer collects the spare above its rule"
    assert "min-height" not in foot, \
        "the bottom row is pinned, which puts the spare under the rule instead of above it"
    assert "oh3s-air" not in JS, "the spacers above the headings are back"


def test_only_quoted_material_is_ever_shortened():
    """Every sentence this panel writes fits its box whole. The one thing with no length limit is
    somebody else's words, which the route caps at 300 characters, and that is evidence rather than
    an instruction."""
    from openh3ir import compiler as C  # noqa: F401 - the route that caps it is the pack's

    assert "static quote(said, room)" in JS
    # The whole argument, not its first word: `got.reason` is the server's own sentence and is
    # quoted material too, and a check on the first word alone read that as something else.
    quoted = re.findall(r"Panel\.quote\(([^,]+),", JS)
    assert quoted, "nothing is being shortened, so this test is blind"
    for arg in quoted:
        assert "said" in arg or "reason" in arg, (
            f"something other than quoted material is being shortened: {arg.strip()}. Only somebody "
            "else's words are ever trimmed; an instruction this panel wrote is never cut.")
    assert "\\u2026" in JS, "the shortened quote does not end in an ellipsis"
    assert JS.count("this.msg.title = ") >= 2, \
        "a shortened quote does not keep the whole of itself on the tooltip"


# ------------------------------------------------- what a brand new node shows

def test_a_brand_new_node_says_what_happened_rather_than_complaining():
    """ComfyUI fills each of the five combos with the first file in that folder, so the first thing
    somebody met was five names nobody chose and a complaint about two of them being the same. It
    says what happened and what to do now, and it is not red, because nothing is broken yet."""
    # The GATE, not just the sentence. A first draft asserted the string was present and something
    # said it, and planting `if (false)` around the whole branch walked past it: the call was still
    # in the file, just unreachable.
    block = JS[JS.index("  renderFiles() {"):JS.index("  /** The two warnings, and only two.")]
    guarded = re.search(
        r"if \(!FILES\.some\(\(f\) => this\.chosen\(f\.w\)\)\) \{\s*\n"
        r'\s*this\.sayFiles\("ComfyUI filled these in\. Pick your own five H3 files\."\);\s*\n'
        r"\s*return;", block)
    assert guarded, (
        "the sentence for a brand new node is not reached by asking whether any row has been picked "
        "in. Either the guard is gone or something else decides it.")
    assert '"bad"' not in guarded.group(0), "the sentence is drawn as an error"


def test_neither_file_warning_fires_on_a_row_nobody_has_picked_in():
    """A warning about a value ComfyUI chose is the panel complaining to somebody about something
    they did not do. The same-file warning needs BOTH VAE rows picked in, and the wrong-row warning
    needs THAT row picked in."""
    warn = JS[JS.index("  fileWarning() {"):JS.index("  renderFoot() {")]
    assert "if (!this.chosen(w)) continue;" in warn, \
        "the wrong-row warning fires on a row nobody has picked in"
    assert 'this.chosen("video_vae") && this.chosen("audio_vae")' in warn, \
        "the same-file warning fires on two rows nobody has picked in"


def test_a_new_node_is_known_from_how_it_was_built_and_never_from_a_file_name():
    """The rule that this node never picks a file from its name is untouched. Whether a node is brand
    new is knowable for certain and for free: it was built by `onNodeCreated` and nothing configured
    it afterwards."""
    chosen = JS[JS.index("  chosen(name) {"):]
    chosen = chosen[:chosen.index("\n\n")]
    assert chosen.count("this.configured") == 1 and "this.touched.has(name)" in chosen
    for word in ("ref2va", "fl2va", "minimax", "safetensors", ".gguf"):
        assert word not in chosen, f"the new-node test reads {word!r} out of a file name"


def test_an_untouched_row_is_drawn_in_the_grey_the_address_example_uses():
    """The value is real and a queue will use it, so it is never hidden. It is shown as what it is: a
    value nobody chose. Picking in the row turns it the ordinary colour for good."""
    css = JS[JS.index("const CSS = "):]
    grey = re.search(r"\.oh3s-wrow select\.oh3s-in\.oh3s-untouched\{color:([^;}]+)", css).group(1)
    example = re.search(r"\.oh3s-wrow \.oh3s-in::placeholder\{color:([^;}]+)", css).group(1)
    assert grey == example, (
        f"an untouched row is drawn in {grey} and the address example in {example}. They are the "
        "same idea and they have to be the same colour.")
    assert 'sel.classList.toggle("oh3s-untouched", !this.chosen(f.w));' in JS


# --------------------------------------------------------------------------- two copies of a rule

def test_the_wrong_row_warning_is_the_compilers_own_rule():
    """The same warning exists in `h3ir_client.family_warning`, where it reaches the report after a
    render. Saying it when the file is picked costs one comparison and saves the render, and two
    copies of one rule is exactly the drift this repository keeps finding.

    Both are checked against the same two family words and the same evidence rule: a name carrying
    the other family's word and not this one's.
    """
    from openh3ir.h3ir_client import FRAMES_FAMILY, REFERENCE_FAMILY, family_warning

    assert f'const FAMILY = {{ reference_model: "{REFERENCE_FAMILY}", frames_model: ' \
           f'"{FRAMES_FAMILY}" }};' in JS, \
        "the panel and the client disagree about H3's two checkpoint families"
    # the same three judgements, made on this side, so a change to either is a change to both
    assert family_warning(f"a_{FRAMES_FAMILY}_file.safetensors", frames_job=False)
    assert not family_warning(f"a_{REFERENCE_FAMILY}_file.safetensors", frames_job=False)
    assert not family_warning("a_file_naming_neither.safetensors", frames_job=False)
    assert 'name.includes(other) && !name.includes(wanted)' in JS, \
        "the panel stopped reading the name only where the name settles the question"


def test_the_panel_offers_the_folded_list_and_never_every_id():
    """One set of weights under two names is a choice with nothing in it. The route folds them and
    publishes what it folded; the panel offers the survivors and draws the rest as a note."""
    # The positive path, because a negative regex only forbids the one spelling somebody thought of.
    assert re.search(r"narrowed\(\) \{\s*\n\s*const all = \(this\.report && this\.report\.choose_from\)",
                     JS), "the list the panel narrows no longer comes from the folded names"
    # Inside `modelList` specifically. `const rows` is written twice in this file and the other one
    # belongs to the Enter key, so a search over the whole file found the wrong one and the guard
    # passed with the defect live.
    model_list = JS[JS.index("  modelList() {"):JS.index("  /** The three bottom controls")]
    rows = re.search(r"const rows = ([^;]+);", model_list).group(1)
    assert rows.strip() == "this.narrowed()", \
        f"the model list draws its rows from {rows.strip()} rather than the folded list"
    assert "also_known_as" in JS, "the folded name is not drawn beside the row it stands for"


# --------------------------------------------------------------------------- what it does on its own

def test_a_fresh_node_makes_no_network_call_at_all():
    """The rule this panel used to be the only thing in the pack breaking.

    It checked four addresses somebody might be running a language model on, the moment a node was
    dropped. A port is configurable, so that was four guesses, and it reached the network without
    being asked. The list those requests fed is gone, so the payoff is gone and the departure has no
    defence left.

    What is left may only be reached by pressing something: the models route from the test button,
    the vision route from the test button or picking a name.
    """
    assert "COMMON" not in JS, "the list of guessed addresses is back"
    assert "maybeProbe" not in JS and "askCommon" not in JS, "the on-drop check is back"
    # Every call to the two language model routes, and the method it lives in.
    for route in ("/openh3ir/llm/models", "/openh3ir/llm/vision"):
        for at in [m.start() for m in re.finditer(re.escape(route), JS)]:
            method = JS.rfind("\n  async ", 0, at)
            name = re.match(r"\n  async (\w+)", JS[method:]).group(1)
            assert name in ("ask", "look"), (
                f"{route} is called from {name}, which is not one of the two places a person "
                "presses")
    # And what the constructor RUNS, as opposed to what it wires to a click. Its last statements are
    # the whole of what a dropped node does on its own, and none of the three touches those routes:
    # `askCompiler` asks whether the compiler is installed, which is one import and no network.
    ctor = JS[JS.index("  constructor(node, widgets) {"):JS.index("  footItem(")]
    tail = ctor[ctor.rindex("    this.render();"):]
    ran = re.findall(r"^\s*this\.(\w+)\(", tail, re.M)
    assert ran == ["render", "askCompiler", "readKey"], (
        f"a dropped node now runs {ran} on its own. Anything beyond these three has to be shown not "
        "to reach the network.")


def test_the_endpoint_field_has_no_caret_because_there_is_nothing_to_open():
    """The caret existed only to open the list of four guesses. A control that opens nothing is a
    control that reads as broken."""
    row = _row("this.addrRow = el(")
    assert "oh3s-caret" not in row, "the endpoint row still draws a caret"
    assert "addrCaret" not in JS


def test_nothing_in_the_pack_names_a_real_machine_on_anybody_s_network():
    """Every address written into this repository is a loopback address or one of the ranges set
    aside for documentation. A LAN address in a shipped file is somebody else's network."""
    for path in [*REPO.glob("*.py"), *(REPO / "web").glob("*.js"), REPO / "README.md",
                 *(REPO / "tests").glob("*.py")]:
        text = path.read_text(encoding="utf-8")
        for found in re.findall(r"\b(?:10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text):
            assert found.startswith(("192.0.2.", "192.168.1.")), \
                f"{path.name} names {found}, which is a real machine on a real network"


# --------------------------------------------------------------------------- the Python it needs

def test_the_route_tells_the_panel_what_the_environment_would_give():
    """State 02: the address field is empty and the compiler would still find one, because somebody
    started ComfyUI from a shell that exports it. An empty field that is not really empty is the
    most confusing state this node has, and without this it is a line in the report that only
    appears after a run."""
    from openh3ir import compiler as C

    import os

    got = C.environment_defaults()
    assert set(got) == {"url", "model"}
    os.environ[C.LLM_URL_ENV] = "http://from-the-environment:8000/v1"
    try:
        assert C.environment_defaults()["url"] == "http://from-the-environment:8000/v1"
    finally:
        os.environ.pop(C.LLM_URL_ENV, None)
    # The route has to pass that value through, not a blank of its own. Asserted on the exact
    # mapping, because the first draft only checked that the key existed and a defect that answered
    # an empty string for it went straight past.
    routes = (REPO / "web_api.py").read_text(encoding="utf-8")
    assert '"env_url": env["url"]' in routes and '"env_model": env["model"]' in routes, \
        "the route publishes an env field that does not come from the environment"
    assert "this.compiler.env_url" in JS or "this.compiler && this.compiler.env_url" in JS


def test_the_liveness_attempts_carry_the_status_that_tells_the_failures_apart(monkeypatch):
    """Nothing answering and a server answering 401 are two problems with two fixes, and the
    compiler's probe records both as text. Parsed once, in Python, with this on it."""
    from openh3ir import compiler as C

    assert C._status_in("HTTP 401") == 401
    assert C._status_in("HTTP 404") == 404
    assert C._status_in("ConnectError: [Errno 111] Connection refused") is None
    assert C._status_in("") is None
    assert C._status_in("HTTP 4010") is None, "a four digit number is not a status"


def test_a_stored_credential_reaches_the_compiler_and_an_absent_one_leaves_the_environment_alone(
        tmp_path, monkeypatch):
    """The store wins where there is one. With none, `H3IR_LLM_KEY` still decides, exactly as it did
    before this store existed: moving the credential onto the node must not take the environment
    channel away from somebody who was already using it."""
    from openh3ir import compiler as C

    store = tmp_path / "openh3ir" / "llm" / "keys.json"
    store.parent.mkdir(parents=True)
    store.write_text('{"http://box:8000/v1": "sk-from-the-store"}', encoding="utf-8")
    monkeypatch.setattr(C, "_user_file", lambda name: str(store))

    assert C.endpoint_key("http://box:8000/v1") == "sk-from-the-store"
    assert C.endpoint_key("http://box:8000/v1/") == "sk-from-the-store", \
        "a trailing slash lost the key, so the request goes out with no credential"
    assert C.endpoint_key("http://somewhere-else:8000/v1") == ""

    monkeypatch.setenv("H3IR_LLM_KEY", "sk-from-the-environment")
    assert C._config("http://box:8000/v1", "m", timeout=5).llm.api_key == "sk-from-the-store"
    assert C._config("http://elsewhere:8000/v1", "m", timeout=5).llm.api_key \
        == "sk-from-the-environment"


@pytest.mark.parametrize("broken", ["", "not json at all", "[]", '"a string"', "null"])
def test_a_credential_store_that_cannot_be_read_is_no_credential_rather_than_a_failure(
        broken, tmp_path, monkeypatch):
    """A store that raised would take a queue down over a file nobody has."""
    from openh3ir import compiler as C

    store = tmp_path / "keys.json"
    store.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(C, "_user_file", lambda name: str(store))
    assert C.endpoint_key("http://box:8000/v1") == ""


def test_no_credential_store_at_all_is_the_ordinary_answer(tmp_path, monkeypatch):
    from openh3ir import compiler as C

    monkeypatch.setattr(C, "_user_file", lambda name: str(tmp_path / "nothing" / "here.json"))
    assert C.endpoint_key("http://box:8000/v1") == ""
