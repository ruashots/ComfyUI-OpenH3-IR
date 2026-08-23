"""The compiler running in ComfyUI's own Python, held against the one that answers over HTTP.

The pack has two ways to compile and the bar for the second one is that it is not the poor relation:
the same graph produces the same brief, the same report and the same refusals whichever way it went.
That is not something a reader can check by looking at two files, because the two paths are written
in different languages -- one posts JSON to a pydantic model and the other fills dataclasses -- so
the tests here run both and compare the results.

**Two of them use the compiler's own `service.py` as the reference**, which is the module the
in-process path is written to avoid importing. That is deliberate and it is the point: fastapi is
absent from a user's ComfyUI path at runtime and present in this repository's test environment, so
this is the one place where both conversions can be run side by side. A difference between them
fails here rather than becoming a brief that is subtly not the one the other path would have
written.

Nothing here needs a language model. The conversion, the refusals, the wiring of the answer and
every message are all reachable without one, and the two places that do need a network are driven
against a fake server rather than a real one.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from openh3ir import compiler as C
from openh3ir import contract as PACK
from openh3ir import h3ir_client as CL
from openh3ir.h3ir_client import ServiceError
from openh3ir.media import sha256_file

REPO = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- the shared fixtures

@pytest.fixture
def files(tmp_path):
    """Three real files, because `service._to_brief` opens and hashes what a request names and a
    conversion tested against files that do not exist is a conversion tested against nothing."""
    made = {}
    for name, blob in (("a.png", b"\x89PNG fake picture"),
                       ("v.mp4", b"fake clip bytes"),
                       ("s.wav", b"RIFF fake sound")):
        p = tmp_path / name
        p.write_bytes(blob)
        made[name] = str(p)
    return made


def _written(files):
    """What `nodes.py` hands the client: one picture that replaces somebody, the clip it edits, and
    that clip's soundtrack pointing back at it. Every field the conversion has to carry is in here,
    including the three that were each silently dropped once."""
    return [
        ("carguy", "image", files["a.png"],
         {"role": "replacement_subject", "note": "carguy: the one in the red coat",
          "replaces": "the man in the plaid shirt"}),
        ("clip", "video", files["v.mp4"],
         {"role": "edit_source", "note": "clip: a yard in the rain", "frames": 124,
          "seconds": 5.167}),
        ("clip sound", "audio", files["s.wav"],
         {"role": "bgm", "seconds": 5.167, "note": "clip sound: the soundtrack of clip",
          "paired_video_path": files["v.mp4"]}),
    ]


def _brief():
    """The node's own brief dictionary, with every optional part filled so nothing is untested by
    being absent."""
    return dict(intent="@carguy crosses the wet yard and stops", seconds=5.0, aspect="16:9",
                creativity="bold", effort="max", seed=11, silent=False, shots="3",
                megapixels=1.5, spoken=["not for me"], spoken_language="Spanish",
                director_profile={"name": "My noir", "notes": "The camera stays still."})


def _payload(files, **over):
    """The request itself, built by the one function that decides what a graph is asking for."""
    written = _written(files)
    return CL.build_payload(assets=CL.plan_assets(written, "match", "", ""),
                            transcripts={sha256_file(files["s.wav"]): "not for me"},
                            **{**_brief(), **over})


def _sha_of():
    return sha256_file


# --------------------------------------------- the conversion, against the compiler's own

def test_the_two_paths_build_the_same_brief_from_the_same_graph(files):
    """THE control on the whole change.

    One request, converted both ways: through `service._to_brief`, which is what a POST to
    `/v1/briefs` runs, and through `compiler.brief_from_payload`, which is what an in-process compile
    runs. If those two disagree about any field then one of the paths is writing a different brief
    from the same canvas, and the user has no way to see which.

    Compared as dictionaries rather than by identity, because `Brief.hash()` alone would say THAT
    they differ and never which field, and the field is the whole diagnosis.
    """
    from dataclasses import asdict

    from h3ir.service import BriefIn, _to_brief

    payload = _payload(files)
    over_the_wire = _to_brief(BriefIn(**payload))
    in_this_python = C.brief_from_payload(payload, _sha_of())

    assert asdict(in_this_python) == asdict(over_the_wire), (
        "the two compile paths build different briefs from one graph")
    assert in_this_python.hash() == over_the_wire.hash()


@pytest.mark.parametrize("role", ["subject", "environment", "style", "storyboard",
                                  "frame_anchor_first", "placed_subject"])
def test_every_job_a_picture_can_have_survives_both_conversions(role, files):
    """Not one shape but every one the tray can produce. A role is what decides the mode, the
    retention marker and the definition line, so a role that converts differently on one path is a
    different render with nothing on screen to say why."""
    from dataclasses import asdict

    from h3ir.service import BriefIn, _to_brief

    written = [("carguy", "image", files["a.png"], {"role": role, "note": "carguy: someone"})]
    payload = CL.build_payload(assets=CL.plan_assets(written, "max", "", ""), transcripts={},
                               **_brief())
    assert asdict(C.brief_from_payload(payload, _sha_of())) == asdict(_to_brief(BriefIn(**payload)))


def test_a_graph_with_nothing_in_the_tray_converts_the_same_way(files):
    """The commonest graph there is, and the one where an empty list could quietly become something
    else."""
    from dataclasses import asdict

    from h3ir.service import BriefIn, _to_brief

    payload = CL.build_payload(assets=[], transcripts={}, **_brief())
    assert asdict(C.brief_from_payload(payload, _sha_of())) == asdict(_to_brief(BriefIn(**payload)))


def test_the_role_is_recorded_as_stated_because_this_pack_always_states_it(files):
    """`role_stated` is silent when it is wrong. Mode inference reads it: a stated `storyboard` is
    ground truth about what a picture is FOR and outranks a phrase in the request, while an unstated
    one is a placeholder that must not block the anchor reading. Nothing on screen would show the
    difference."""
    payload = _payload(files)
    for asset in C.brief_from_payload(payload, _sha_of()).assets:
        assert asset.role_stated is True


def test_a_soundtrack_points_at_its_clip_by_content_and_not_by_path(files):
    """The digest is the identity the runtime pairs on. Left as a path, the pair quietly stops being
    a pair: the soundtrack is numbered as a standalone sound while H3 receives it as that clip's own
    audio track, so one file carries two different labels and only the report says so."""
    brief = C.brief_from_payload(_payload(files), _sha_of())
    sound = next(a for a in brief.assets if a.kind.value == "audio")
    clip = next(a for a in brief.assets if a.kind.value == "video")
    assert sound.paired_video_sha256 == clip.sha256
    assert sound.paired_video_sha256 == sha256_file(files["v.mp4"])


def test_who_a_picture_replaces_survives_the_in_process_conversion(files):
    """The field that was written into the node, declared on the service, guarded by a test, and
    dropped in transit for its whole life. It crosses one more boundary now."""
    brief = C.brief_from_payload(_payload(files), _sha_of())
    picture = next(a for a in brief.assets if a.role.value == "replacement_subject")
    assert picture.replaces == "the man in the plaid shirt"


# --------------------------------------------------------------- an unknown key is never dropped

def test_a_brief_key_the_conversion_does_not_know_is_refused_rather_than_dropped(files):
    """The wire sets `extra="forbid"` because pydantic's silent drop cost this project a real bug: a
    picture arrived saying nothing about who it replaces, and that compiles, validates and renders
    the wrong swap. A conversion that read the keys it knows and ignored the rest would put that bug
    straight back on the path that has no wire to catch it."""
    payload = dict(_payload(files), tempo="brisk")
    with pytest.raises(ServiceError) as e:
        C.brief_from_payload(payload, _sha_of())
    assert "tempo" in str(e.value)


def test_an_attachment_key_the_conversion_does_not_know_is_refused_too(files):
    payload = _payload(files)
    payload["assets"][0]["lighting"] = "hard"
    with pytest.raises(ServiceError) as e:
        C.brief_from_payload(payload, _sha_of())
    assert "lighting" in str(e.value)


def test_every_key_this_pack_can_send_is_one_the_conversion_knows(files):
    """The other direction, and the one a stray key would hide in. `payload_shape` reports what the
    request really carries, computed by running the functions that build it, so a field added to the
    pack that nobody taught the conversion about fails here instead of at somebody's queue."""
    _assets, brief_fields, _roles = CL.payload_shape(_written(files), _brief(), {"abc": "hello"})
    assert set(brief_fields) <= C._BRIEF_KEYS, (
        f"this pack sends {sorted(set(brief_fields) - C._BRIEF_KEYS)} and the in-process conversion "
        "has no field for it")
    for asset in CL.plan_assets(_written(files), "match", "", ""):
        assert set(asset) <= C._ASSET_KEYS, (
            f"this pack sends {sorted(set(asset) - C._ASSET_KEYS)} about an attachment and the "
            "in-process conversion has no field for it")


def test_the_size_bounds_are_the_wire_models_own():
    """A number restated in two places drifts. The wire model owns what a stated canvas size may be,
    and this pins the in-process mirror of it to that model from the side where both are installed:
    change one and this fails rather than one path taking a graph the other refuses."""
    from h3ir.service import BriefIn

    field = BriefIn.model_fields["megapixels"]
    bounds = {type(m).__name__: m for m in field.metadata}
    assert float(bounds["Ge"].ge) == C.MEGAPIXELS_MIN
    assert float(bounds["Le"].le) == C.MEGAPIXELS_MAX


# --------------------------------------------------- the answer, against the service's own routes

def _document(**over):
    """One compiled document, built by hand rather than compiled, so this needs no language model.

    Hand-built is honest here: what is under test is the translation from a document into the
    dictionary the node reads, and every field of that translation is set below.
    """
    from h3ir.grid import Target
    from h3ir.models import (AssetKind, IRDocument, ManifestEntry, Mode, Plan, Role, ShotPlan,
                             SubjectPlan)

    plan = Plan(
        mode=Mode.REF2VA,
        target=Target(nominal_seconds=5.0, frames=124, canvas=(1344, 768)),
        manifest=[ManifestEntry(slot=1, label="<Picture 1>", kind=AssetKind.IMAGE, sha256="a" * 64,
                                wiring="ref_image_1", role=Role.SUBJECT, sizing="max")],
        subjects=[SubjectPlan(label="<Subject 1>", kind="person", sources=["<Picture 1>"],
                              descriptor="the young man", retention="fully_preserved")],
        speakers=[], shots=[ShotPlan(n=1, start_ms=0, end_ms=5000, beat="he crosses")],
        task_types=["reference generation"], style_phrase="documentary, natural light")
    doc = IRDocument(ir_version="1", profile="h3ir/2026-08-a", mode=Mode.REF2VA,
                     prompt="a written brief", plan=plan, sections={"summary": "x"},
                     provenance={"director": "director: My noir"})
    for key, value in over.items():
        setattr(doc, key, value)
    return doc


def test_the_in_process_answer_is_what_the_service_would_have_replied(files):
    """The node reads one dictionary and must not be able to tell where it came from.

    Held against the service's own two route handlers, called directly. `get_prompt` is what the
    HTTP path fetches second, and `_envelope` is what it reads the other four fields off, so this
    compares the real reference rather than a description of it.
    """
    from h3ir.service import _envelope, _remember, get_prompt

    doc, brief = _document(), C.brief_from_payload(_payload(files), _sha_of())
    _remember("deadbeefdeadbeef", brief, doc)
    envelope = _envelope("deadbeefdeadbeef", doc, brief)
    over_the_wire = dict(get_prompt("deadbeefdeadbeef"))
    over_the_wire["brief_id"] = "deadbeefdeadbeef"
    over_the_wire["degraded"] = envelope["status"] == "degraded"
    over_the_wire["fallback_reason"] = envelope["fallback_reason"] or ""
    over_the_wire["director_used"] = (envelope["plan"] or {}).get("director") or ""

    here = C._as_the_service_answers(doc, brief)
    assert set(here) == set(over_the_wire), (
        f"the two answers do not carry the same keys: {sorted(set(here) ^ set(over_the_wire))}")
    for key in over_the_wire:
        if key == "brief_id":
            continue        # the service mints a random one; nothing in-process remembers anything
        assert here[key] == over_the_wire[key], f"the two paths disagree about {key}"


def test_the_answer_carries_everything_the_node_then_reads(files):
    """A missing key would become a plausible default somewhere downstream, which is how somebody
    renders at the wrong length and blames the model. So the answer is driven through the very
    functions the node uses it with."""
    body = C._as_the_service_answers(_document(), C.brief_from_payload(_payload(files), _sha_of()))
    prompt, width, height, frames, sizing = CL.render_fields(body)
    assert (prompt, width, height, frames, sizing) == ("a written brief", 1344, 768, 124, "max")
    text = CL.report(body, compiler=PACK.the_compiler("").where, sizing_conflict=False)
    assert "ref2va" in text and "1344x768" in text
    assert "the open-h3-ir in ComfyUI's own Python" in text, \
        "the report does not say which compiler wrote this brief"
    assert CL.director_note(True, body["director_used"]) == "", \
        "direction was sent and applied, and the node was told it was dropped"


def test_a_brief_id_names_this_request_and_the_same_graph_gets_the_same_one(files):
    """Nothing in-process remembers a brief, so the id is the request's own content hash. That makes
    it worth quoting: two queues of an unchanged graph produce the same one, and a changed graph
    produces a different one."""
    brief = C.brief_from_payload(_payload(files), _sha_of())
    other = C.brief_from_payload(_payload(files, seconds=9.0), _sha_of())
    first = C._as_the_service_answers(_document(), brief)["brief_id"]
    assert first == C._as_the_service_answers(_document(), brief)["brief_id"]
    assert first != C._as_the_service_answers(_document(), other)["brief_id"]


def test_a_fallback_brief_is_flagged_rather_than_passed_off_as_written(files):
    """A silent fallback produced three generations of identical output once and cost hours, because
    the caller could not see that the model's work had been discarded."""
    doc = _document(source="draft", fallback_reason="the detailed pass did not pass checks")
    body = C._as_the_service_answers(doc, C.brief_from_payload(_payload(files), _sha_of()))
    assert body["degraded"] is True
    assert "not a written one" in CL.report(body, compiler="x", sizing_conflict=False)


def test_one_decision_the_compiler_will_not_take_stops_the_queue_rather_than_being_assumed(files):
    """A queue has no second turn. Answering the question here would decide on the canvas's behalf
    whether a picture is the opening frame or a reference for how something looks, which are two
    different renders."""
    doc = _document()
    doc.provenance["clarification"] = {"question": "is that picture the opening frame?",
                                       "default_if_unanswered": "a reference"}
    with pytest.raises(ServiceError) as e:
        C._as_the_service_answers(doc, C.brief_from_payload(_payload(files), _sha_of()))
    assert "is that picture the opening frame?" in str(e.value)
    assert "a reference" in str(e.value), "the assumption it would otherwise make is not stated"


def test_a_request_that_contradicts_itself_is_reported_with_its_rules(files):
    from h3ir.models import Finding

    doc = _document(findings=[Finding(rule="T6-1", severity="ERROR", msg="two things disagree")])
    with pytest.raises(ServiceError) as e:
        C._as_the_service_answers(doc, C.brief_from_payload(_payload(files), _sha_of()))
    assert "contradicts itself" in str(e.value) and "T6-1" in str(e.value)


def test_the_compilers_own_broken_invariant_is_reported_as_its_bug_and_not_the_users(files):
    """The compiler separates a contradiction the caller stated from an invariant of its own. A
    caller can act on the first and should never be handed the second as though they wrote it."""
    from h3ir.models import Finding

    doc = _document(findings=[Finding(rule="Z9-1", severity="ERROR", msg="internal")])
    with pytest.raises(ServiceError) as e:
        C._as_the_service_answers(doc, C.brief_from_payload(_payload(files), _sha_of()))
    assert "bug in open-h3-ir" in str(e.value)
    assert "contradicts itself" not in str(e.value)


# --------------------------------------------------------------------------- where things are

def test_the_setup_node_decides_where_the_compile_happens_and_nothing_else_does():
    """One field, two states, no third. A graph that quietly compiled somewhere other than where it
    says would produce a brief nobody can account for."""
    assert PACK.the_compiler("").where == "the open-h3-ir in ComfyUI's own Python"
    assert PACK.the_compiler("http://box:8420/").where == "the OpenH3-IR service at http://box:8420"
    assert PACK.the_compiler("   ").where == PACK.the_compiler("").where, \
        "a field with a space in it is an empty field"


def test_an_empty_service_field_is_the_ordinary_case_and_never_a_refusal():
    """It used to be required, because there was nothing else to compile with. An empty one is what
    every new graph has now."""
    bundle = CL.setup_bundle(server="", reference_model="a", frames_model="b", text_encoder="c",
                             video_vae="d", audio_vae="e", weight_dtype="default", timeout_s=600)
    assert bundle["server"] == ""
    assert bundle["llm_url"] == "" and bundle["llm_model"] == ""


def test_a_language_model_address_with_no_scheme_is_refused_on_the_node():
    with pytest.raises(ServiceError) as e:
        CL.setup_bundle(server="", llm_url="192.168.1.20:8000/v1", reference_model="a",
                        frames_model="b", text_encoder="c", video_vae="d", audio_vae="e",
                        weight_dtype="default", timeout_s=600)
    assert "no scheme" in str(e.value) and "language model" in str(e.value)


def test_a_trailing_slash_on_the_language_model_address_is_taken_off():
    """`http://host:11434/v1/` is an ordinary thing to paste out of a browser, and left alone every
    request goes to `/v1//chat/completions`, which answers with a 404 that says nothing about the
    extra slash."""
    bundle = CL.setup_bundle(server="", llm_url="http://host:11434/v1/", reference_model="a",
                             frames_model="b", text_encoder="c", video_vae="d", audio_vae="e",
                             weight_dtype="default", timeout_s=600)
    assert bundle["llm_url"] == "http://host:11434/v1"


# --------------------------------------------------------------------------- is it installed

def test_a_compiler_that_is_here_is_reported_as_here():
    state, detail = C.availability()
    assert state == "ok" and detail == ""
    assert C.package_version(), "no version was reported for an installed compiler"


def test_an_absent_compiler_and_a_broken_one_are_never_reported_as_each_other(monkeypatch):
    """Two states with two different fixes. Absent means install it; broken means the install is
    half-finished, and telling somebody to install a package that is already there sends them round
    a loop."""
    import builtins

    real = builtins.__import__

    def missing(name, *a, **kw):
        if name.split(".")[0] == "h3ir":
            raise ModuleNotFoundError("no module named 'h3ir'", name="h3ir")
        return real(name, *a, **kw)

    def half_installed(name, *a, **kw):
        if name.split(".")[0] == "h3ir":
            raise ModuleNotFoundError("no module named 'tiktoken'", name="tiktoken")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", missing)
    assert C.availability()[0] == "absent"
    with pytest.raises(ServiceError) as absent:
        C.require_installed()

    monkeypatch.setattr(builtins, "__import__", half_installed)
    assert C.availability()[0] == "broken"
    with pytest.raises(ServiceError) as broken:
        C.require_installed()

    assert "pip install 'open-h3-ir'" in str(absent.value)
    assert "tiktoken" in str(broken.value), "the missing piece is not named"
    assert "force-reinstall" in str(broken.value)
    assert str(absent.value) != str(broken.value)


def test_an_absent_compiler_is_never_mentioned_to_a_graph_that_compiles_elsewhere():
    """A graph driving a service on another machine needs no local package, and telling its owner to
    install one is the wrong-message failure from the other side."""
    source = (REPO / "nodes.py").read_text(encoding="utf-8")
    assert "require_installed()" in source, "the in-process path no longer checks at all"
    assert source.index("here = not machine[\"server\"]") < source.index("require_installed()"), \
        "the pack checks for a local compiler before it knows whether this graph needs one"


# --------------------------------------------------------------------------- the language model

def test_the_address_on_the_node_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv(C.LLM_URL_ENV, "http://from-the-environment:8000/v1")
    url, whence = C.resolve_llm_url("http://on-the-node:8000/v1")
    assert url == "http://on-the-node:8000/v1" and whence == "the Setup node"


def test_an_address_from_the_environment_is_used_and_said_out_loud(monkeypatch):
    """The compiler's own documented channel, and a ComfyUI started from a shell that sets it is a
    real setup. What must not happen is it being used in silence: a setting nobody can see on the
    canvas is one somebody spends an afternoon looking for."""
    monkeypatch.setenv(C.LLM_URL_ENV, "http://from-the-environment:8000/v1")
    url, whence = C.resolve_llm_url("")
    assert url == "http://from-the-environment:8000/v1"
    assert C.LLM_URL_ENV in whence and whence != "the Setup node"


def test_no_address_anywhere_is_refused_by_naming_the_field_on_the_node(monkeypatch):
    """And never by naming an environment variable. There is no service to set one on, which is the
    whole point of the pack being an all-in-one, so a message that named one would send somebody to
    configure a process that does not exist."""
    monkeypatch.delenv(C.LLM_URL_ENV, raising=False)
    with pytest.raises(ServiceError) as e:
        C.resolve_llm_url("")
    assert "language model field" in str(e.value)
    assert "Setup node" in str(e.value)
    assert C.LLM_URL_ENV not in str(e.value), \
        "somebody with no service is told to set an environment variable on it"


def test_the_compiler_is_never_left_to_pick_the_default_address(monkeypatch):
    """The compiler's own default is a placeholder meaning "a server on this machine". Taking it
    would send a queue at a port with nothing behind it and then explain the failure in terms of a
    variable nobody set."""
    monkeypatch.delenv(C.LLM_URL_ENV, raising=False)
    from h3ir.config import LLMConfig

    with pytest.raises(ServiceError):
        C.resolve_llm_url("")
    assert LLMConfig().base_url, "the compiler has no default, so this test guards nothing"


# ------------------------------------------------------- asking an endpoint what it serves

class _Endpoint:
    """A fake OpenAI-compatible server, driven through the compiler's own client.

    A fake rather than a real one because what is under test is the pack's reading of an answer, and
    the shapes below are the ones real servers give: vLLM publishes one checkpoint under several ids
    and gives every entry the same `root`, while Ollama's entries carry no `root` at all.
    """

    def __init__(self, models, *, healthy=True):
        self.models, self.healthy = models, healthy

    def __call__(self, url, *a, **kw):
        import httpx

        if not self.healthy:
            raise httpx.ConnectError("connection refused")
        if url.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": self.models},
                                  request=httpx.Request("GET", url))
        return httpx.Response(404, json={}, request=httpx.Request("GET", url))


def _serving(monkeypatch, models, *, healthy=True):
    from h3ir.backend import Backend

    monkeypatch.setattr(Backend, "_get", lambda self, url, timeout: _Endpoint(
        models, healthy=healthy)(url))


def test_several_names_for_one_checkpoint_are_one_choice(monkeypatch):
    """Measured against a real vLLM: `--served-model-name` publishes one set of weights under
    several ids and gives every entry the same `root`. Offering both would be this pack inventing a
    decision, and the person picking one has no way to know the two are the same file.

    **The survivor is the name the operator chose**, which the server itself distinguishes: an id
    that is not its own `root` is a name somebody typed into `--served-model-name`, and `root` is
    only where the weights came from. That name is what a person clicks, types, and recognises later
    on their own server. This is the exact shape of the live endpoint this was measured on.
    """
    _serving(monkeypatch, [
        {"id": "philbert440/Qwen3.8-27B", "root": "philbert440/Qwen3.8-27B", "max_model_len": 262144},
        {"id": "qwen3.8u", "root": "philbert440/Qwen3.8-27B", "max_model_len": 262144},
    ])
    got = C.endpoint_report("http://box:8000/v1")
    assert got["ok"] is True
    assert got["ids"] == ["philbert440/Qwen3.8-27B", "qwen3.8u"]
    assert got["choose_from"] == ["qwen3.8u"], (
        "one checkpoint under two names was offered as two models, or the surviving name is the "
        "repository it came from rather than the one the operator gave it")
    assert got["also_known_as"] == {"qwen3.8u": ["philbert440/Qwen3.8-27B"]}, \
        "the collapsed name is gone, so nobody can tell where the id they typed last week went"
    assert got["context"] == 262144


def test_the_surviving_name_is_always_one_the_server_published_as_an_id():
    """A correctness line, not a taste one. Whatever a person picks is sent straight back as `model`,
    and a `root` is not promised to be a name the server answers to: vLLM sets it from the model
    path, so a server started from a local directory has a filesystem path there with no route behind
    it. Only the strings in `data[].id` are names the server offered."""
    entries = [{"id": "qwen3.8u", "root": "/models/qwen-27b-awq"},
               {"id": "qwen-long", "root": "/models/qwen-27b-awq"}]
    survivors, _also = C.one_name_per_checkpoint(entries)
    ids = {str(m["id"]) for m in entries}
    assert survivors and set(survivors) <= ids, \
        f"a name the server never published was offered as something to pick: {survivors}"
    assert "/models/qwen-27b-awq" not in survivors


def test_several_chosen_names_for_one_checkpoint_keep_the_first_the_server_listed():
    """`--served-model-name a b` publishes two names the operator chose and one root. There is
    nothing to prefer between them, so the rule is the server's own order, which is the order the
    operator wrote them in. Stated rather than fallen into: an arbitrary pick that changes between
    two reads of the same server is worse than a plain one that does not."""
    survivors, also = C.one_name_per_checkpoint([
        {"id": "/models/qwen", "root": "/models/qwen"},
        {"id": "fast", "root": "/models/qwen"},
        {"id": "big", "root": "/models/qwen"},
    ])
    assert survivors == ["fast"]
    assert also == {"fast": ["/models/qwen", "big"]}


def test_a_checkpoint_nobody_named_keeps_the_id_the_server_lists():
    """No id in the group differs from its root, so nobody chose anything and there is nothing to
    prefer. This is what an unaliased vLLM and a one-model llama.cpp both look like."""
    survivors, also = C.one_name_per_checkpoint(
        [{"id": "Qwen/Qwen3-VL-8B", "root": "Qwen/Qwen3-VL-8B"}])
    assert survivors == ["Qwen/Qwen3-VL-8B"]
    assert also == {}


def test_an_endpoint_that_reports_no_root_at_all_collapses_nothing():
    """Ollama's model objects carry id, object, created and owned_by and nothing else. Every id is
    its own model there, which is the safe direction: it can offer more choice and can never merge
    two models that really are two."""
    survivors, also = C.one_name_per_checkpoint([{"id": "llava"}, {"id": "qwen2.5-coder"}])
    assert survivors == ["llava", "qwen2.5-coder"]
    assert also == {}


def test_an_endpoint_with_no_root_on_its_entries_offers_every_id(monkeypatch):
    """Ollama's model objects carry id, object, created and owned_by and nothing else. Counting each
    id as its own model there can only make this offer more choice, never less, which is the safe
    direction: it can refuse to guess and it can never guess wrong."""
    _serving(monkeypatch, [{"id": "llava"}, {"id": "qwen2.5-coder"}])
    assert C.endpoint_report("http://box:11434/v1")["choose_from"] == ["llava", "qwen2.5-coder"]


def test_the_private_methods_this_reaches_for_are_still_on_the_backend():
    """One deliberate coupling, held against the installed compiler rather than hoped for.

    `endpoint_report` asks the compiler's own client for the model list instead of fetching it with
    `httpx` here, because two things about that request are measured facts the compiler owns: which
    liveness paths to try and in what order, and whether a configured credential goes out. Restating
    either would give the panel a second opinion, and a panel that says an endpoint is down when the
    queue would have reached it is worse than no panel.

    The cost is that two of the three names are private. So a compiler release that renames one fails
    here, on a clean run, rather than as a button that stops working in somebody's browser.
    """
    from h3ir.backend import Backend

    for name in ("_get", "_headers", "base_url", "health_probe", "server_version"):
        assert callable(getattr(Backend, name, None)), (
            f"the installed open-h3-ir has no Backend.{name}, and endpoint_report calls it. Either "
            "follow the rename or fetch the model list here.")


def test_an_address_that_answers_nothing_is_reported_with_what_was_tried(monkeypatch):
    _serving(monkeypatch, [], healthy=False)
    got = C.endpoint_report("http://nothing-here:8000/v1")
    assert got["ok"] is False
    assert got["tried"], "nothing recorded which paths were asked"
    assert "http://nothing-here:8000/v1" in got["reason"]


def test_a_named_model_is_taken_without_asking_the_endpoint(monkeypatch):
    """A graph that names its model spends no request finding out what it already knows."""
    def refuse(*a, **kw):
        raise AssertionError("the endpoint was asked about a model the node already named")

    monkeypatch.setattr(C, "endpoint_report", refuse)
    assert C.resolve_llm_model("http://box:8000/v1", "qwen3.8u") == ("qwen3.8u", "the Setup node")


def test_one_model_on_the_endpoint_is_taken_because_there_is_nothing_to_choose(monkeypatch):
    monkeypatch.delenv(C.LLM_MODEL_ENV, raising=False)
    _serving(monkeypatch, [{"id": "the-only-one", "root": "the-only-one"}])
    model, whence = C.resolve_llm_model("http://box:8000/v1", "")
    assert model == "the-only-one" and "only model" in whence


def test_several_models_are_refused_by_listing_them_rather_than_by_guessing(monkeypatch):
    """The model that has to be picked is the one that can read a picture, and no model list on any
    of these servers says which. Reported from a real Ollama install: the first id was a large
    text-only coding model, every reference image went unread, and nothing said so."""
    monkeypatch.delenv(C.LLM_MODEL_ENV, raising=False)
    _serving(monkeypatch, [{"id": "llava"}, {"id": "qwen2.5-coder"}])
    with pytest.raises(ServiceError) as e:
        C.resolve_llm_model("http://box:11434/v1", "")
    assert "llava" in str(e.value) and "qwen2.5-coder" in str(e.value)
    assert "Setup node" in str(e.value), "the refusal does not say where to pick one"
    assert C.LLM_MODEL_ENV not in str(e.value), \
        "somebody with no service is told to set an environment variable on it"


def test_an_unreachable_endpoint_is_refused_by_naming_the_field_rather_than_the_symptom(monkeypatch):
    monkeypatch.delenv(C.LLM_MODEL_ENV, raising=False)
    _serving(monkeypatch, [], healthy=False)
    with pytest.raises(ServiceError) as e:
        C.resolve_llm_model("http://nothing-here:8000/v1", "")
    assert "Setup node" in str(e.value)


def test_an_unreachable_language_model_never_tells_a_node_user_to_set_an_environment_variable(
        monkeypatch):
    """MEASURED live, and the first draft of this message got it wrong.

    The compiler's own sentence for an unreachable endpoint ends "Start it, or set H3IR_LLM_URL",
    which is right for a service and wrong here: there is no service, and the address is a field on
    the canvas. The first draft quoted that sentence and then added "that is the field on the Setup
    node", so the reader got two contradictory instructions and had to pick one.
    """
    from h3ir.backend import BackendUnavailable

    _serving(monkeypatch, [], healthy=False)
    said = C._endpoint_did_not_answer(
        BackendUnavailable("the reasoning model at http://box:8000/v1 is not reachable. Start it, "
                           "or set H3IR_LLM_URL."),
        "http://box:8000/v1", "some-model")
    assert C.LLM_URL_ENV not in said, \
        f"somebody with no service is told to set an environment variable on it: {said}"
    assert "Setup node" in said, "the message does not say where the address is"
    assert "answered" in said, "the message drops the evidence about what was tried"


def test_an_endpoint_that_answers_on_the_second_look_keeps_the_compilers_own_sentence(monkeypatch):
    """The failure was then about something other than reachability, and the compiler's description
    of it is the best one there is. Rewriting it would replace a real diagnosis with a guess."""
    from h3ir.backend import BackendUnavailable

    _serving(monkeypatch, [{"id": "m", "root": "m"}])
    said = C._endpoint_did_not_answer(BackendUnavailable("names 4 model ids"), "http://box:8000/v1",
                                      "m")
    assert "names 4 model ids" in said
    assert "It is answering" in said


def test_a_model_that_cannot_see_is_reported_as_that_and_a_timeout_is_reported_as_neither(monkeypatch):
    """Three answers, not two. A model that read the picture, a model that did not, and a check that
    could not be completed -- and the third must never be reported as the second, because a verdict
    from a timeout is this pack guessing about the thing it was asked to measure."""
    from h3ir import backend as B

    monkeypatch.setattr(B, "vision_check", lambda b: (True, "479"))
    assert C.can_it_see("http://box:8000/v1", "m")["ok"] is True

    monkeypatch.setattr(B, "vision_check", lambda b: (False, "I cannot see images."))
    said = C.can_it_see("http://box:8000/v1", "m")
    assert said["ok"] is False and "vision tower" in said["reason"]

    def times_out(b):
        raise B.BackendError("read timeout")

    monkeypatch.setattr(B, "vision_check", times_out)
    assert C.can_it_see("http://box:8000/v1", "m")["ok"] is None


def test_the_vision_check_refuses_to_answer_about_no_model_at_all():
    assert C.can_it_see("http://box:8000/v1", "  ")["ok"] is False


@pytest.mark.parametrize("status,verdict,says", [
    (400, False, "vision tower"),
    (415, False, "vision tower"),
    (404, None, "no model called"),
    (401, None, "credential"),
    (403, None, "credential"),
    (500, None, "nothing is known"),
])
def test_a_refused_request_is_only_a_verdict_about_vision_when_it_is_one(status, verdict, says,
                                                                         monkeypatch):
    """MEASURED against a live vLLM, and the first draft of this route got it wrong.

    Asking about a model the endpoint does not serve came back as `HTTP 404: The model does not
    exist`, and it was reported as "it cannot read a picture, pick one with a vision tower".
    Somebody reading that goes looking for a vision model to replace one that was never there. A
    rejected credential and a broken server are the same mistake wearing different numbers.

    So only the statuses that mean "I looked at this request and it is not acceptable" produce a
    verdict. The rest say nothing about vision and must not pretend to.
    """
    from h3ir import backend as B

    def refused(b):
        raise B.EndpointRefused(status, '{"error": {"message": "no"}}')

    monkeypatch.setattr(B, "vision_check", refused)
    got = C.can_it_see("http://box:8000/v1", "some-model")
    assert got["ok"] is verdict
    assert says in got["reason"], got["reason"]
    if verdict is None:
        assert "vision tower" not in got["reason"], (
            "a failure that says nothing about vision is reported as a model that cannot see")


# ------------------------------------------------------------ what the report says either way

def test_the_report_names_which_compiler_wrote_the_brief():
    """A brief id names one request to one compiler, and the pair is what somebody quotes when they
    ask why a render came out the way it did. Either alone is half an answer."""
    body = {"mode": "ref2va", "frames": 124, "canvas": [1344, 768], "brief_id": "abc123",
            "render_hash": "z" * 16}
    here = CL.report(body, compiler=PACK.the_compiler("").where, sizing_conflict=False)
    there = CL.report(body, compiler=PACK.the_compiler("http://box:8420").where,
                      sizing_conflict=False)
    assert "abc123   from the open-h3-ir in ComfyUI's own Python" in here
    assert "abc123   from the OpenH3-IR service at http://box:8420" in there


def test_a_language_model_field_a_service_graph_cannot_use_is_reported_and_never_ignored():
    """Not a refusal: the graph is fine and it compiled where it said it would. But a field somebody
    filled in and the node ignored is the kind of silence that has them changing it and wondering
    why nothing moves."""
    source = (REPO / "nodes.py").read_text(encoding="utf-8")
    assert 'elif machine["llm_url"] or machine["llm_model"]:' in source, \
        "a graph on a service no longer says anything about the language model fields it ignored"
    assert "were not used" in source


def test_the_language_model_that_wrote_the_brief_is_named_in_the_report():
    """Two models write two different briefs from one sentence, so a report that did not say which
    one had been used would be a record of a render nobody can reproduce."""
    source = (REPO / "nodes.py").read_text(encoding="utf-8")
    assert 'line("written by"' in source, "the report does not name the language model"


# --------------------------------------------------------- what a stranger's ComfyUI has to do

def test_the_pack_declares_the_compiler_it_now_runs_in_process():
    """The whole all-in-one rests on pip having installed it. A pack that runs the compiler and does
    not declare it works on the machine it was built on and nowhere else."""
    requirements = (REPO / "requirements.txt").read_text(encoding="utf-8")
    project = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert f"{C.DISTRIBUTION}>=" in requirements
    assert f'"{C.DISTRIBUTION}>=' in project, \
        "the registry reads pyproject.toml, and it does not name the compiler"


def test_running_the_compiler_here_never_loads_fastapi_or_uvicorn():
    """The constraint the all-in-one has to answer. The compiler declares fastapi, uvicorn, pydantic
    and tiktoken, so pip puts all four in ComfyUI's Python -- and importing them on every start, for
    a graph that may never compile, is the collision this pack has always refused.

    `h3ir.service` is the one module that needs fastapi, and it holds the conversion this pack builds
    itself instead of borrowing. So the measurement is: run the in-process path with those two
    blocked, and it works.
    """
    import subprocess
    import sys

    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys\n"
         "for n in ('fastapi', 'uvicorn'): sys.modules[n] = None\n"
         "import h3ir.compile, h3ir.backend, h3ir.contract, h3ir.models, h3ir.plan, h3ir.analyse\n"
         "print('loaded' if h3ir.contract.contract()['contract_version'] else 'no')\n"],
        capture_output=True, text=True)
    assert probe.returncode == 0, (
        "the compiler cannot run with fastapi and uvicorn blocked, so the in-process path drags "
        f"them into ComfyUI's Python: {probe.stderr.strip()[-400:]}")
    assert probe.stdout.strip() == "loaded"


def test_the_falsification_run_covers_the_in_process_path():
    """Every guard here has a planted defect written for it, like every other guard in this pack. A
    test that has never been seen failing is a test nobody has verified."""
    cases = (REPO / "research" / "contract_falsification.py").read_text(encoding="utf-8")
    assert "tests/test_in_process.py" in cases, \
        "nothing in the falsification run plants a defect this file's guards have to catch"
    assert json.dumps("compiler.py") in cases or "\"compiler.py\"" in cases, \
        "the falsification run cannot edit the module the in-process path lives in"
