"""What the nodes look like on a canvas, checked without a canvas.

`nodes.py` imports ComfyUI's node API at module scope, so it cannot be imported here. The
alternative to giving up on these checks was to write a fake `comfy_api` and assert against that,
which would have tested the fake. So this reads the source instead: it parses each schema declaration
and asserts on what it actually says. Crude, and it cannot prove ComfyUI draws it correctly, but it
does prove the declaration says what it is supposed to say, and it runs anywhere.

The live half of this pair is running ComfyUI and reading `/object_info`, which is how the real drawn
schema was verified. That needs a GPU box with the model files, so it is not something CI can do.

Every rule below exists because a version of these nodes got it wrong. Three of them are measurements
rather than opinions, and they are worth restating because they are the reason the labels are terse:

  * A label shares one widget row with its value and the row holds about 38 characters, so a long
    label makes both unreadable. Measured on the owner's own screenshot.
  * On a multiline STRING the placeholder is the only label there is, and with no placeholder the
    frontend prints the input's id (`createMultilineInputElement(default, placeholder || name)`).
  * `advanced` collapses widgets only under Nodes 2.0 with `Comfy.Node.AlwaysShowAdvancedWidgets`
    false. It is not a hide, so every rule here assumes every input is visible.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "nodes.py"
TEXT = SRC.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)

# Input kinds whose label alone cannot explain them, so they must carry a tooltip too.
NEEDS_TOOLTIP = {"String", "Float", "Int", "Combo", "Boolean"}

# A label spends the pixels the value needs. The measured row is about 38 characters and a filename
# is most of that, so nothing here gets to be a sentence.
MAX_LABEL = 30


def _str(node: ast.AST | None) -> str:
    """Join a literal or an implicitly concatenated literal back into one string."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _str(node.left) + _str(node.right)
    return ""


def _is_input_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Input")


def _kind(call: ast.Call) -> str:
    """`io.Image.Input` -> "Image"; `Footage.Input` -> "Footage"."""
    owner = call.func.value
    if isinstance(owner, ast.Attribute):
        return owner.attr
    if isinstance(owner, ast.Name):
        return owner.id
    return ""


def _inputs_in(subtree: ast.AST) -> list[tuple[str, str, dict[str, ast.AST]]]:
    """Every `<Kind>.Input(...)` under one node, in declaration order, as (kind, id, keywords)."""
    found = []
    for node in ast.walk(subtree):
        if not _is_input_call(node):
            continue
        ident = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else ""
        found.append((_kind(node), ident, {k.arg: k.value for k in node.keywords if k.arg}))
    return found


def _schemas() -> dict[str, ast.Call]:
    """Every `io.Schema(...)` call in the file, keyed by its node_id."""
    out: dict[str, ast.Call] = {}
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Schema"):
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            out[_str(kw.get("node_id"))] = node
    return out


def _template_input_ids() -> set[str]:
    """The ids declared inside an autogrow template.

    They are a special case in both directions: the frontend overwrites a template's display_name
    with `names[ordinal]`, so setting one is dead weight that a reader of this source would believe.
    """
    out = set()
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("TemplateNames", "TemplatePrefix")):
            for inner in ast.walk(node):
                if _is_input_call(inner) and inner.args:
                    out.add(inner.args[0].value)
    return out


SCHEMAS = _schemas()
TEMPLATE_IDS = _template_input_ids()
# The compile node's own inputs, which is where "how many boxes is this" is decided.
COMPILE = _inputs_in(SCHEMAS["OpenH3IRCompile"])
SETUP = _inputs_in(SCHEMAS["OpenH3IRSetup"])
MEDIA = _inputs_in(SCHEMAS["OpenH3IRMedia"])
DIRECTOR = _inputs_in(SCHEMAS["OpenH3IRDirector"])
ALL = [(node_id, *rest) for node_id, call in SCHEMAS.items() for rest in _inputs_in(call)]


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _multiline(kw: dict[str, ast.AST]) -> bool:
    node = kw.get("multiline")
    return isinstance(node, ast.Constant) and node.value is True


def _ids(inputs) -> list[str]:
    return [i for _k, i, _kw in inputs]


def _outputs_of(node_id: str) -> list[tuple[str, str]]:
    out = []
    for node in ast.walk(SCHEMAS[node_id]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Output"):
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            out.append((_kind(node) if False else node.func.value.attr
                        if isinstance(node.func.value, ast.Attribute)
                        else node.func.value.id, _str(kw.get("display_name"))))
    return out


# --------------------------------------------------------------------------- labels a person reads

def test_every_input_a_person_can_see_carries_a_label_or_a_placeholder():
    """The widget id is what shows on the canvas when nothing else does, and an id like `sound_notes`
    on screen is the node talking to itself. Measured: it shipped like that.

    A multiline box is the exception, and not a lenient one: it has no room for a label beside its
    value, so its placeholder IS its label and the placeholder is therefore required.
    """
    nameless = []
    for node_id, kind, ident, kw in ALL:
        if not ident or ident in TEMPLATE_IDS:
            continue
        label, ph = _str(kw.get("display_name")), _str(kw.get("placeholder"))
        if _multiline(kw):
            if not ph:
                nameless.append(f"{node_id}.{ident} (multiline with no placeholder prints its id)")
        elif not label:
            nameless.append(f"{node_id}.{ident}")
    assert not nameless, f"inputs with nothing readable on them: {nameless}"


def test_a_grown_sockets_template_does_not_pretend_to_set_its_own_label():
    """`autogrowOrdinalToName` returns `{name: ..., display_name: s}` and overwrites whatever the
    template declared, so a `display_name` on a template input is a claim the canvas ignores. The old
    node set one to "a thing in the shot" and the sockets still read `reference_0`."""
    claimed = [f"{n}.{i}" for n, _k, i, kw in ALL
               if i in TEMPLATE_IDS and _str(kw.get("display_name"))]
    assert not claimed, f"template display names the frontend overwrites: {claimed}"


def test_a_multiline_box_does_not_also_carry_a_display_name():
    """Two labels for one box, one of which the canvas will not draw. The placeholder is the label
    there, so a display name is a second thing to keep in step for no gain."""
    doubled = [f"{n}.{i}" for n, _k, i, kw in ALL if _multiline(kw) and _str(kw.get("display_name"))]
    assert not doubled, f"multiline inputs with a redundant display name: {doubled}"


def test_the_first_line_of_a_placeholder_stands_alone():
    """A short box shows one line, so line one has to be the whole instruction. `the man` on its own
    teaches nothing about what the box is for."""
    for node_id, _k, ident, kw in ALL:
        ph = _str(kw.get("placeholder"))
        if not ph:
            continue
        first = ph.splitlines()[0].strip()
        assert len(first.split()) >= 4, f"{node_id}.{ident}: placeholder line one is {first!r}"


def test_no_label_is_an_identifier():
    """An underscore in a label means the identifier leaked onto the canvas, which is what happened:
    `sound_notes` and `spoken_words` were showing as-is. `weight_dtype` is the one exception, and it
    is the opposite of a leak: it quotes Load Diffusion Model's own widget name letter for letter,
    because that exact string is the name people relate the setting to."""
    offenders = [f"{n}.{i} -> {_str(kw.get('display_name'))!r}" for n, _k, i, kw in ALL
                 if "_" in _str(kw.get("display_name"))
                 and _str(kw.get("display_name")) != "weight_dtype"]
    assert not offenders, f"identifiers used as labels: {offenders}"


def test_no_label_is_long_enough_to_hide_its_own_value():
    """The measurement behind every terse label in this pack: a label and its value share one row of
    about 38 characters, so `H3 weights for reference and text jobs` left no room for the filename it
    was labelling and neither could be read."""
    long = [f"{n}.{i} -> {_str(kw.get('display_name'))!r}" for n, _k, i, kw in ALL
            if len(_str(kw.get("display_name"))) > MAX_LABEL]
    assert not long, f"labels that will eat their own value: {long}"


def test_a_placeholder_shows_an_example_rather_than_the_field_name():
    """A placeholder is the one piece of guidance someone reads before typing, so it shows what an
    answer looks like. Repeating the label there teaches nothing."""
    offenders = []
    for node_id, _kind, ident, kw in ALL:
        ph = _str(kw.get("placeholder"))
        if not ph:
            continue
        label = _str(kw.get("display_name"))
        if ph.strip().lower() in (ident.lower(), label.strip().lower()):
            offenders.append(f"{node_id}.{ident}: {ph!r}")
    assert not offenders, f"placeholders that just repeat the name: {offenders}"


def test_no_placeholder_is_dev_talk():
    """`usually blank, worked out automatically` was on the node, and on a single-line widget the
    legacy canvas never draws a placeholder at all, so it was invisible dev talk. Single-line
    placeholders are therefore not used: the display name carries it."""
    single = [f"{n}.{i}" for n, k, i, kw in ALL
              if k == "String" and not _multiline(kw) and _str(kw.get("placeholder"))]
    assert not single, f"single-line placeholders are never drawn on the legacy canvas: {single}"


def test_every_text_number_and_choice_input_explains_itself():
    missing = [f"{n}.{i}" for n, kind, i, kw in ALL
               if kind in NEEDS_TOOLTIP and i and not _str(kw.get("tooltip"))]
    assert not missing, f"inputs with no explanation: {missing}"


def test_every_socket_explains_what_plugging_into_it_means():
    """A socket has no value to show, so its tooltip is the only thing that can say what the job is.
    An IMAGE in `first frame` and an IMAGE in `picture 1` are different H3 checkpoints."""
    missing = [f"{n}.{i}" for n, kind, i, kw in ALL
               if kind in {"Image", "Audio", "Setup", "Footage", "Sound"} and i
               and not _str(kw.get("tooltip"))]
    assert not missing, f"sockets with no explanation: {missing}"


# --------------------------------------------------------------------------- nothing that is false

def test_the_silence_flag_is_labelled_with_what_it_actually_does():
    """`prose.py` sets non-diegetic music to N/A and nothing else: it keeps ambient and sync sound
    and never touches speech. The old label said `no music or speech`, which was simply untrue, and
    a label that is wrong is worse than a label that is terse."""
    label = next(_str(kw.get("display_name")) for _k, i, kw in COMPILE if i == "silent")
    assert label == "no music"
    tip = next(_str(kw.get("tooltip")) for _k, i, kw in COMPILE if i == "silent")
    assert "score only" in tip and "Ambient" in tip, \
        "the tooltip has to say what survives, or the flag reads as a mute button"


def test_the_shot_ceiling_is_the_compilers_own_ceiling():
    """The old field offered 0 to 8 while `shots.py` clamped to 4, so asking for 6 silently got 4.
    Offering what the engine drops is the surface lying. The engine's contract is now the pin
    ceiling: an explicit number is kept exactly up to PINNED_SHOTS_MAX (proven live and by
    test_pinned_shots.py), so that is the number the combo may offer.

    Read off the published contract rather than by importing `h3ir.shots`, which is a reach across
    a boundary that will not be there: `contract.json` is what the pack ships and
    `tests/test_contract_drift.py` is what keeps it current.
    """
    from openh3ir.contract import SNAPSHOT
    from openh3ir.h3ir_client import SHOTS

    ceiling = SNAPSHOT["limits"]["max_pinned_shots"]
    assert SHOTS == ("auto", *(str(i) for i in range(1, ceiling + 1)))

    kw = next(kw for _k, i, kw in COMPILE if i == "shots")
    options = _str(_kw(kw["options"], "x")) if False else kw["options"]
    assert isinstance(options, ast.Call), "the options come from the shared constant, not a literal"


def test_the_shots_widget_is_a_choice_rather_than_a_number_with_a_magic_zero():
    kinds = {i: k for k, i, _kw in COMPILE}
    assert kinds["shots"] == "Combo", "0 meaning auto was a label doing the code's job"


def test_the_creativity_tooltip_does_not_promise_extra_content_at_extreme():
    """`creativity.py` gives extreme exactly what bold has, and the cut count is off the dial at
    every position. The old tooltip implied both."""
    tip = next(_str(kw.get("tooltip")) for _k, i, kw in COMPILE if i == "creativity")
    assert "extreme adds nothing beyond bold" in tip
    assert "Shot count is never on this dial" in tip


def test_the_seconds_range_is_the_one_that_was_decided_and_the_tooltip_admits_it():
    """The range is deliberately wider than H3's trained band, so the tooltip has to say the band
    exists and the report has to say when a render left it. A wide range with a silent surface is how
    someone renders two seconds of nothing and blames the model."""
    kw = next(kw for _k, i, kw in COMPILE if i == "seconds")
    assert kw["min"].value == 1.0 and kw["max"].value == 149.0
    tip = _str(kw.get("tooltip"))
    assert "5.167 to 15.083" in tip and "the report says so" in tip


# --------------------------------------------------------------------------- one source of truth

def test_there_is_exactly_one_place_to_set_the_length():
    """Two dials that both claim to set duration is how eight seconds of a ten second script gets
    rendered. The graph used to have its own seconds and its own frame arithmetic as well."""
    duration_ish = [i for _n, _k, i, _kw in ALL
                    if any(w in i for w in ("second", "length", "duration", "frames"))
                    and i not in ("frames_model", "frames", "timeout_s")]
    assert duration_ish == ["seconds"], f"more than one duration control: {duration_ish}"


def test_the_canvas_size_is_not_a_second_source_of_truth():
    ids = _ids(ALL and [(k, i, kw) for _n, k, i, kw in ALL])
    assert "width" not in ids and "height" not in ids, \
        "the canvas comes from the frame shape; a resolution box would be able to disagree with it"


def test_there_is_no_gguf_toggle_anywhere_in_the_pack():
    """The file is the toggle. A boolean beside a filename is two controls for one fact, with two of
    its four states wrong and nothing on the canvas able to resolve them."""
    offenders = [f"{n}.{i}" for n, _k, i, kw in ALL
                 if "gguf" in i.lower() or "gguf" in _str(kw.get("display_name")).lower()]
    assert not offenders, f"a format control was added: {offenders}"


def test_the_gguf_option_lists_come_from_the_packs_own_registered_lists():
    """Globbing `*.gguf` off the folder would offer files with no loader behind them on an install
    without ComfyUI-GGUF, which is the plausible-and-wrong option this pack exists to prevent."""
    from openh3ir import h3ir_client

    assert "unet_gguf" in TEXT and "clip_gguf" in TEXT
    for forbidden in ("glob(", "listdir", "scandir", "iterdir"):
        assert forbidden not in TEXT, f"nodes.py walks the disk with {forbidden}"
    # One predicate owns the extension, so there is one place to look when the rule changes, and the
    # node routes on that predicate rather than carrying its own copy of it. Constants rather than
    # source text, so documenting the rule does not count as re-implementing it.
    owners = sorted(name for name, fn in vars(h3ir_client).items()
                    if getattr(fn, "__module__", "") == h3ir_client.__name__
                    and hasattr(fn, "__code__")
                    and ".gguf" in [c for c in fn.__code__.co_consts if c is not fn.__doc__])
    assert owners == ["is_gguf"], f"the extension is tested in more than one place: {owners}"
    body = TEXT[TEXT.index("class OpenH3IRCompile"):TEXT.index("class OpenH3IRSetup")]
    assert ".gguf" not in body, "the node routes on is_gguf rather than on its own copy of the rule"


def test_no_path_prefix_is_something_people_have_to_type():
    """ComfyUI's own folder is known from ComfyUI, and the service's spelling of it is found by trying
    and checking. Two hand-typed prefix boxes were the first design and one advanced override was the
    second; both asked the user to answer a question the node answers by asking the service to open
    the file. What is left when that fails is a service that cannot reach ComfyUI's disk at all, and
    no box fixes that."""
    ids = [i for _n, _k, i, _kw in ALL]
    for gone in ("comfy_path_prefix", "service_path_prefix", "service_sees_comfy_at"):
        assert gone not in ids, f"{gone} is not a question for the user"
    assert "service sees" not in TEXT, "nor a field named in a message, since it is not on any node"
def test_the_model_combos_are_a_picker_and_nothing_else():
    """The five files are a question only the user can answer: a filename says what a file is called,
    not what somebody intended it to be. So each combo lists what this install has and opens on one of
    them, exactly like every loader in ComfyUI, with no sentinel default meaning "work it out" and no
    hidden preference behind it."""
    for model in ("reference_model", "frames_model", "text_encoder", "video_vae", "audio_vae"):
        kw = next(kw for _k, i, kw in SETUP if i == model)
        assert isinstance(kw["options"], ast.Call) and kw["options"].func.id == "_model_options", \
            f"{model} must list what this install actually has"
        assert "default" not in kw, \
            f"{model} carries no default, so the combo opens on a real file the user can read"
        assert "(found" not in _str(kw.get("tooltip")), "no tooltip promises a search either"


def test_the_pick_is_the_file_that_loads_and_no_table_second_guesses_it():
    """THE control on the picker. Auto-resolution matched H3's filenames against a table of expected
    words, with a preference for int8 builds nobody asked for, and the render then used a file the
    canvas never showed. The node reads the five names off the bundle and loads those."""
    execute = TEXT[TEXT.index("    def execute(cls, intent"):TEXT.index("helpers", TEXT.index(
        "    def execute(cls, intent"))]
    for guess in ("PATTERNS", "resolve_model", "int8", "found automatically"):
        assert guess not in TEXT, f"{guess} is how the node used to answer a question it cannot"
    for direct in ('"frames_model" if frames_job else "reference_model"', 'machine["text_encoder"]',
                   'machine["video_vae"]', 'machine["audio_vae"]'):
        assert direct in execute, f"{direct} has to be read straight off the Setup bundle"


# --------------------------------------------------------------------------- identity and outputs
def test_the_compile_node_is_findable_by_the_words_a_user_types():
    """`OpenH3-IR` alone tells a stranger nothing, and the siblings they already know are called
    "MiniMax H3 Image to Video" and "MiniMax H3 Reference to Video"."""
    aliases = _kw(SCHEMAS["OpenH3IRCompile"], "search_aliases")
    words = {_str(e) for e in aliases.elts}
    assert {"minimax", "h3", "ref2va", "fl2va", "t2va"} <= words
    assert _str(_kw(SCHEMAS["OpenH3IRCompile"], "display_name")) == "OpenH3-IR Main"


def test_every_node_in_the_pack_is_in_one_category():
    for node_id, call in SCHEMAS.items():
        assert _str(_kw(call, "category")) == "OpenH3-IR", node_id


def test_the_graph_needs_no_loader_boxes():
    """Every model file the render touches comes out of the compile node, decode included."""
    kinds = [k for k, _label in _outputs_of("OpenH3IRCompile")]
    assert kinds == ["Model", "Conditioning", "Latent", "Vae", "Vae", "String", "String"]
    labels = [label for _k, label in _outputs_of("OpenH3IRCompile")]
    assert labels == ["model", "positive", "latent", "vae", "audio_vae", "prompt", "report"]



# --------------------------------------------------------------------------- the tray-era surface

def test_the_node_set_is_four_and_the_ids_are_frozen():
    """A rename silently breaks every workflow anyone saved and every video anyone rendered, which
    the owner hit in person. Pinned.

    Four since the Director node. This pin exists to catch a RENAME, not to forbid a fourth node --
    so adding one is a deliberate edit here, and removing or renaming one still has to be."""
    assert sorted(SCHEMAS) == ["OpenH3IRCompile", "OpenH3IRDirector", "OpenH3IRMedia",
                               "OpenH3IRSetup"]


def test_main_is_one_sentence_a_tray_a_setup_and_the_knobs():
    """`director` is an optional SOCKET, not a widget, and it sits with the other two bundles.

    Optional is mechanical rather than stylistic, for the reason `megapixels` records: ComfyUI
    publishes every required input ahead of every optional one, so a required input is missing from
    every API-format graph written before it existed and that is a hard refusal at /prompt.
    """
    ids = [i for _k, i, _kw in COMPILE]
    assert ids == ["intent", "seconds", "aspect", "creativity", "silent", "shots", "setup",
                   "megapixels", "spoken_language", "director", "media", "sizing", "seed",
                   "effort"], ids


def test_the_director_is_optional_so_older_graphs_still_submit():
    """The whole point of the fourth node: a graph without one behaves exactly as it always did."""
    node = next(kw for _k, i, kw in COMPILE if i == "director").get("optional")
    assert isinstance(node, ast.Constant) and node.value is True


def test_the_director_is_one_field_the_panel_writes():
    """The same shape as the tray, and for the same reason: one widget holding one string, so a
    saved workflow and a rendered video carry the direction with them and the panel can be deleted
    without changing what any graph does.

    It is also the whole answer to "'none' should not exist, because the node optional". There is no
    combo on this node, so there is no position on it that means "no director" -- the node's absence
    is that, and its presence with nothing written in it is the same request."""
    ids = [i for _k, i, _kw in DIRECTOR]
    assert ids == ["profile"], ids
    kw = DIRECTOR[0][2]
    assert not _multiline(kw), "the panel is the editor; the field itself is one line of JSON"
    assert _str(kw.get("default")) == "{}"


def test_no_node_offers_a_none_that_means_the_absence_of_itself():
    """A combo position meaning "do nothing" is a second way to say what unplugging already says,
    and the two can disagree. The owner named it on the Director node and it holds pack-wide."""
    for name, inputs in (("OpenH3IRCompile", COMPILE), ("OpenH3IRSetup", SETUP),
                         ("OpenH3IRMedia", MEDIA), ("OpenH3IRDirector", DIRECTOR)):
        for _k, i, kw in inputs:
            opts = kw.get("options")
            if opts is None:
                continue
            words = [e.value for e in getattr(opts, "elts", []) if isinstance(e, ast.Constant)]
            assert "none" not in words, f"{name}.{i} offers a 'none' position: {words}"


def test_the_only_text_box_left_is_the_sentence():
    boxes = [i for _k, i, kw in COMPILE if _multiline(kw)]
    assert boxes == ["intent"], \
        "the notes went to the tray's slots and the locked lines went inline as @speaks"


def test_the_sentence_teaches_both_at_constructs_where_the_user_types():
    kw = next(kw for _k, i, kw in COMPILE if i == "intent")
    ph, tip = _str(kw.get("placeholder")), _str(kw.get("tooltip"))
    assert "@" in ph.splitlines()[0], "the placeholder's first line must show the @ exists"
    assert '@speaks("' in tip and "word for word" in tip
    assert "no such check" in tip, "say what a plain quote does NOT get, or the box reads as magic"


def test_the_language_choice_says_it_binds_to_the_locked_lines():
    kw = next(kw for _k, i, kw in COMPILE if i == "spoken_language")
    tip = _str(kw.get("tooltip"))
    assert "@speaks" in tip and "decides nothing" in tip


def test_the_media_socket_names_the_tray_and_the_at_sign():
    kind, _i, kw = next(t for t in COMPILE if t[1] == "media")
    assert kind == "Media"
    tip = _str(kw.get("tooltip"))
    assert "OpenH3-IR Media" in tip and "@" in tip
    assert "empty" in tip.lower(), "no media is a legal piece and the tooltip must say so"


def test_the_tray_node_is_one_field_and_one_output():
    ids = [i for _k, i, _kw in MEDIA]
    assert ids == ["tray"], "the panel is rendering; the string is the node"
    kw = next(kw for _k, i, kw in MEDIA if i == "tray")
    tip = _str(kw.get("tooltip"))
    assert "drag" in tip.lower() or "rendered video" in tip, \
        "the tooltip carries the reimport promise"
    outs = _outputs_of("OpenH3IRMedia")
    assert [k for k, _l in outs] == ["Media"]


def test_the_tray_state_survives_a_rendered_video():
    """The owner's rule: drag the mp4 back in and the tray comes back. That only works if the tray
    is an ordinary widget value, because those are what land in the embedded graph."""
    kind, _i, kw = next(t for t in MEDIA if t[1] == "tray")
    assert kind == "String", "widget state is what a rendered video's embedded graph carries"
    assert _str(kw.get("default")) == "[]"


def test_the_pack_ships_its_frontend_and_names_the_folder():
    import openh3ir
    assert getattr(openh3ir, "WEB_DIRECTORY", None) == "web"
    web = SRC.parent / "web"
    assert web.is_dir(), "WEB_DIRECTORY points at a folder that must exist"
    names = {p.name for p in web.glob("*.js")}
    assert names, "an empty web folder ships a pack with no panel and no picker"


def test_every_node_the_pack_declares_is_painted_in_the_family_colors():
    """`web/style.js` holds the one list of node ids the pack paints, and it is written by hand
    beside a list of schemas that is written somewhere else.

    The Director shipped missing from it, which is the worst shape this fault has: the node worked
    perfectly and was simply drawn in ComfyUI's default grey, so it read as a node from somebody
    else's pack rather than as a bug, and nothing anywhere complained. Two hand-kept lists that must
    agree is the pair this project has found silent faults with, and checking it costs one read."""
    import re
    style = (SRC.parent / "web" / "style.js").read_text(encoding="utf-8")
    m = re.search(r"const OURS = \[(.*?)\];", style, re.S)
    assert m, "the pack's color list was not found, so this test is blind"
    ours = re.findall(r'"([^"]+)"', m.group(1))
    assert ours, "the color list parsed as empty, which is also this test going blind"
    assert sorted(ours) == sorted(SCHEMAS), (
        f"style.js paints {sorted(ours)} and nodes.py declares {sorted(SCHEMAS)}. A node in one and "
        "not the other is a node drawn in the wrong colors, or a color rule aimed at nothing.")
