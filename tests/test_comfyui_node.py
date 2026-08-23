"""The ComfyUI nodes, tested with no ComfyUI, no torch and no server in the process.

The nodes' value is entirely in what they do on a bad day, so most of what follows asserts on the
sentence a user reads rather than on an exception type. A node that raises the right class with a
useless message has failed at the only job that matters when something is wrong.

Several of these are falsification controls: they fail if the code starts guessing. `render_fields`
inventing a frame count, a model file being resolved from its name instead of being picked, or a
mapping key being renamed would each leave the node looking like it works while quietly producing the
wrong render or breaking every saved workflow in the world.

The tray and the @ prompt have their own file, tests/test_tray.py; what lives here is the service
conversation, the Setup bundle, and the job routing.
"""
from __future__ import annotations

import json

import pytest

from openh3ir import h3ir_client as C


@pytest.mark.parametrize("first,last,pics,clips,sounds,expect", [
    (False, False, 0, 0, 0, "t2va"),
    (True, False, 0, 0, 0, "i2va"),
    (False, True, 0, 0, 0, "l2va"),
    (True, True, 0, 0, 0, "fl2va"),
    (False, False, 2, 0, 0, "ref2va"),
    (False, False, 0, 1, 0, "ref2va"),
    (False, False, 0, 0, 1, "ref2va"),
    (False, False, 0, 0, 3, "ref2va"),
])
def test_the_job_is_read_off_the_sockets(first, last, pics, clips, sounds, expect):
    assert C.expected_mode(first, last, pics, clips, sounds) == expect

def _setup(**over):
    """A Setup bundle with the five picks a person made, since there is no longer any other kind."""
    fields = dict(server=C.DEFAULT_SERVER,
                  reference_model="minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                  frames_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  text_encoder="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  video_vae="minimax_h3_video_vae_fp16.safetensors",
                  audio_vae="minimax_h3_audio_vae_fp32.safetensors",
                  weight_dtype="default", timeout_s=600)
    return C.setup_bundle(**{**fields, **over})


def test_a_service_address_with_no_scheme_is_refused_before_anything_is_requested():
    with pytest.raises(C.ServiceError) as e:
        _setup(server="127.0.0.1:8420")
    assert "no scheme" in str(e.value) and C.DEFAULT_SERVER in str(e.value)


def test_the_bundle_carries_the_five_picks_and_invents_nothing():
    """THE control on the picker. Every file in the bundle is the file the user chose, unchanged and
    unsubstituted, and there is no field left that could mean anything else."""
    d = _setup()
    assert d["reference_model"] == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    assert d["frames_model"] == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    assert d["text_encoder"] == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    assert d["video_vae"] == "minimax_h3_video_vae_fp16.safetensors"
    assert d["audio_vae"] == "minimax_h3_audio_vae_fp32.safetensors"
    assert set(d) == {"server", "llm_url", "llm_model", "reference_model", "frames_model",
                      "text_encoder", "video_vae", "audio_vae", "weight_dtype", "timeout_s"}


def test_a_pick_this_pack_would_once_have_overruled_survives_untouched():
    """The old resolver preferred an int8 build over anything else with the same family word in it,
    which on a Blackwell card is the slower file and was nobody's decision. A pick is a pick."""
    d = _setup(reference_model="MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors")
    assert d["reference_model"] == "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors"


def test_nothing_in_the_pack_searches_for_a_model_file_by_name():
    """The falsification control for the whole change. Auto-resolution answered a question the node
    could not know the answer to ("which of these did you mean?"), so it is gone rather than
    improved, and this fails if it or its sentinel comes back under any name."""
    import pathlib

    assert not hasattr(C, "resolve_model") and not hasattr(C, "setup_defaults")
    assert not hasattr(C, "AUTO"), "a sentinel meaning 'work it out' is the same guess with a label"
    # Read beside the module under test rather than beside the runner, or a cross-tree pytest run
    # asserts about a copy of the pack nobody edited.
    pack = pathlib.Path(C.__file__).parent
    source = "\n".join((pack / name).read_text(encoding="utf-8")
                       for name in ("nodes.py", "h3ir_client.py"))
    assert "found automatically" not in source
    for gone in ("REFERENCE_PATTERNS", "FRAMES_PATTERNS", "ENCODER_PATTERNS", "VIDEO_VAE_PATTERNS",
                 "AUDIO_VAE_PATTERNS"):
        assert gone not in source, f"{gone} is a table for guessing which file was meant"


# ----------------------------------------------- picking the wrong slot is worth saying out loud

def test_a_reference_checkpoint_in_the_frame_slot_is_warned_about():
    """Both files load. A ref2va checkpoint on a frame job renders something plausible that ignores
    the frames, so the filename's own family word is read back to the user."""
    said = C.family_warning("minimax_h3_ref2va_pruned_int8_convrot.safetensors", frames_job=True)
    assert "ref2va" in said and "fl2va" in said, "name what was picked and what the job wants"
    assert "fl2va model" in said, "name the field on the node that fixes it"
    assert "render either way" in said, "it is a warning, not a refusal"


def test_a_frame_checkpoint_in_the_reference_slot_is_warned_about():
    said = C.family_warning("minimax_h3_fl2va_pruned_int8_convrot.safetensors", frames_job=False)
    assert "fl2va" in said and "ref2va model" in said


def test_the_right_checkpoint_says_nothing_at_all():
    assert C.family_warning("minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                            frames_job=False) == ""
    assert C.family_warning("MiniMax_H3_FL2VA_Q4_K_M.gguf", frames_job=True) == "", \
        "case is not a family, and the format is not either"


def test_a_filename_that_names_no_family_is_not_guessed_about():
    """THE control on the warning. A renamed or third-party file is not evidence of a mistake, and a
    warning that fires on no evidence teaches people to ignore warnings."""
    for name in ("h3_weights.safetensors", "", "my_favourite_checkpoint.gguf"):
        assert C.family_warning(name, frames_job=True) == ""
        assert C.family_warning(name, frames_job=False) == ""


def test_a_filename_naming_both_families_is_not_read_either():
    assert C.family_warning("minimax_h3_ref2va_and_fl2va_merged.safetensors",
                            frames_job=True) == ""


# --------------------------------------------------------------------------- the file is the format

def test_both_builds_of_a_folder_land_next_to_each_other_in_one_list():
    """`unet_gguf` is not a different place: ComfyUI-GGUF registers it over the same directories with
    a `.gguf` filter, so a checkpoint's two builds sit side by side and the extension is the only
    thing that tells them apart."""
    got = C.merge_model_options(["minimax_h3_ref2va_pruned_int8.safetensors", "Krea2.safetensors"],
                                ["minimax_h3_ref2va_Q4_K_M.gguf"])
    assert got == ["Krea2.safetensors", "minimax_h3_ref2va_pruned_int8.safetensors",
                   "minimax_h3_ref2va_Q4_K_M.gguf"]
    assert got[0] == "Krea2.safetensors", "case-insensitive, or K sorts away from k"


def test_a_file_listed_twice_is_offered_once():
    assert C.merge_model_options(["a.gguf"], ["a.gguf"]) == ["a.gguf"]


def test_the_loader_is_chosen_from_the_extension_per_file():
    assert C.unet_loader_for("m_Q4_K_M.gguf") == "Unet Loader (GGUF)"
    assert C.unet_loader_for("m.safetensors") == "UNETLoader"
    assert C.clip_loader_for("q.GGUF") == "CLIPLoader (GGUF)", "case is not a format"
    assert C.clip_loader_for("q.safetensors") == "CLIPLoader"


def test_a_gguf_checkpoint_and_a_safetensors_encoder_are_both_legal():
    """Separate files with separate loaders, so the combinations are all valid. One boolean would
    either force both or leave the encoder undefined."""
    assert C.is_gguf("weights.gguf") and not C.is_gguf("encoder.safetensors")


def test_both_builds_of_one_file_are_offered_and_neither_is_preferred():
    """The list is what the user chooses from, in one order, with no build promoted over another. The
    old resolver preferred safetensors and reported the GGUF build as an alternative it passed over;
    there is nothing to pass over when the user is the one picking."""
    got = C.merge_model_options(["minimax_h3_ref2va_pruned_int8_convrot.safetensors"],
                                ["minimax_h3_ref2va_Q4_K_M.gguf"])
    assert got == ["minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                   "minimax_h3_ref2va_Q4_K_M.gguf"]
    assert not hasattr(C, "gguf_alternative_note"), \
        "a note about the build that was passed over described a choice nobody makes any more"


def test_the_ignored_precision_note_says_why_it_was_ignored():
    """A setting that silently does nothing is worse than one that is absent."""
    note = " ".join(C.precision_ignored_note().split())
    assert "carries its own quantisation" in note and "it was ignored" in note


# --------------------------------------------------------------------------- path translation

def test_a_windows_path_becomes_the_services_view_of_the_same_file():
    got = C.translate_path(r"C:\ComfyUI-Production\temp\ref.png",
                           r"C:\ComfyUI-Production", "/mnt/c/ComfyUI-Production")
    assert got == "/mnt/c/ComfyUI-Production/temp/ref.png"


def test_no_prefixes_means_no_translation():
    assert C.translate_path("/srv/x/a.png", "", "") == "/srv/x/a.png"
    assert C.translate_path("/srv/x/a.png", "/srv", "") == "/srv/x/a.png"


def test_a_path_outside_the_prefix_is_returned_untouched():
    """Silently rewriting an unrelated path would send the service a file that does not exist and
    blame the user's mapping. Better to pass it through and let the service say it cannot read it."""
    assert C.translate_path("/elsewhere/a.png", r"C:\ComfyUI", "/mnt/c/ComfyUI") == "/elsewhere/a.png"


def test_translation_is_case_insensitive_because_windows_is():
    got = C.translate_path(r"c:\comfyui-production\temp\ref.png",
                           r"C:\ComfyUI-Production", "/mnt/c/ComfyUI-Production")
    assert got == "/mnt/c/ComfyUI-Production/temp/ref.png"


# --------------------------------------------------------------------------- failure messages

def _fake(monkeypatch, *replies):
    """Replace the HTTP layer with a scripted sequence of (status, body) pairs."""
    calls = list(replies)

    def fake_request(server, path, *, payload=None, timeout=600.0):
        return calls.pop(0)

    monkeypatch.setattr(C, "_request", fake_request)


def test_an_unreachable_service_names_the_command_and_the_node_that_point_elsewhere(monkeypatch):
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(C.urllib.request, "urlopen", boom)
    with pytest.raises(C.ServiceError) as e:
        C._request("http://127.0.0.1:8420", "/v1/capabilities")
    msg = str(e.value)
    assert "h3ir serve" in msg, "the message must tell them how to start the thing that is missing"
    assert "H3IR_LLM_URL" in msg
    assert "8420" in msg
    assert "OpenH3-IR Setup" in msg, \
        "the address left the compile node, so the discovery cost is paid by this message"


def test_a_timeout_points_at_the_node_that_holds_the_knob(monkeypatch):
    import socket as s

    def boom(req, timeout=None):
        raise s.timeout()

    monkeypatch.setattr(C.urllib.request, "urlopen", boom)
    with pytest.raises(C.ServiceError) as e:
        C._request("http://x", "/v1/briefs", payload={}, timeout=30)
    assert "OpenH3-IR Setup" in str(e.value) and "timeout" in str(e.value)


def test_an_unreadable_reference_says_what_is_wrong_and_names_no_field_that_is_gone(monkeypatch):
    """The failure this project will actually generate: ComfyUI on Windows, service in WSL. It used to
    end by naming a widget to fill in, and that widget no longer exists, so the instruction is now
    about the two things a person can actually change."""
    _fake(monkeypatch, (422, {"detail": {"code": "asset-missing",
                                        "message": "no such file: C:\\x\\ref.png"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "no such file: C:\\x\\ref.png" in msg, "pass the service's own words through"
    assert "different paths" in msg, "say what the failure is"
    assert "another machine" in msg, "the remote case has no fix and must be stated"
    assert "read access" in msg, "and the local case does, so say it"
    assert "as the service sees it" not in msg, \
        "THE control: an instruction to fill in a field nobody can find is worse than no instruction"


def test_a_contradictory_request_lists_the_rules_that_fired(monkeypatch):
    _fake(monkeypatch, (422, {"status": "invalid", "errors": [
        {"rule": "T6-duration", "message": "asked for silence and a score"}]}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "T6-duration" in msg and "asked for silence and a score" in msg


def test_a_file_that_opened_and_could_not_be_decoded_is_not_a_path_problem(monkeypatch):
    """The service resolved it, opened it and could not use it. A different spelling would fail the
    same way, so this must not enter the path-retry loop, and the analyser's own sentence, which
    already names the file and what is wrong with it, has to survive."""
    _fake(monkeypatch, (422, {"detail": {
        "code": "asset-unreadable",
        "message": "clip.mp4 is declared kind: video but its bytes are a PNG."}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "declared kind: video but its bytes are a PNG" in msg, "pass the analyser's words through"
    assert "a different path would fail the same way" in msg
    assert C.send_the_bytes(e.value) is False, \
        "THE control: another attempt at this is three waits for one answer"


def test_a_missing_ffmpeg_is_not_reported_as_a_dead_language_model(monkeypatch):
    """Both are 503. Reading the status alone and printing the LLM message would send someone to fix
    an endpoint that is working, which is the wrong-message failure this pack exists to avoid."""
    _fake(monkeypatch, (503, {"detail": {
        "code": "analysis-tool-missing",
        "message": "ffprobe is not installed, and video references need it. Install ffmpeg."}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "Install ffmpeg" in msg, "the analyser already says what to install"
    assert "H3IR_LLM_URL" not in msg, "do not blame a language model for a missing binary"
    assert "not about your graph" in msg
    assert "text-only prompt still works" in msg, "say what does work"


def test_more_references_than_h3_has_sockets_for_names_the_ceilings(monkeypatch):
    """Refused rather than truncated: ten pictures used to compile to `ready` with a manifest
    publishing <Picture 10> and wiring ref_image_10, a socket that does not exist. Which reference
    matters is the user's call."""
    _fake(monkeypatch, (422, {"detail": {
        "code": "over-capacity", "message": "10 images attached; H3 has 9 image sockets."}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "10 images attached" in msg
    assert "nine pictures, three clips and three standalone sounds" in msg
    assert "Nothing was silently dropped" in msg


def _service_failures(where: str = "briefs") -> set[tuple[int, str]]:
    """Every (status, code) pair the compiler can hand this pack, read off the published contract.

    It used to be read out of `h3ir/service.py` and `h3ir/compile.py` by regex, which worked while
    the two halves shared a checkout and stops working the moment they are two repositories. The
    compiler publishes the list now -- `h3ir contract` writes it into `contract.json` -- so
    this reads a file the pack ships and nothing here reaches across the boundary.

    Split by route, because the node talks to two of them and their messages are not
    interchangeable: a `POST /v1/briefs` failure is explained by `compile_brief` in terms of the
    graph, and a `PUT /v1/assets/{sha256}` failure by `upload_asset`, which has to name the tray
    slot. One code is raised on both, so the contract states routes as a list and this filters.
    """
    from openh3ir.contract import SNAPSHOT

    published = SNAPSHOT["error_codes"]
    assert published, "the shipped contract lists no refusals, so this scan is blind"
    return {(int(spec["status"]), code) for code, spec in published.items()
            if where in spec["on"]}


@pytest.mark.parametrize("status,code", sorted(
    (int(s), c) for s, c in _service_failures()
    # Raised before any request this node makes, or about a brief id it never invents: the node's
    # roles come from a fixed map, it never PATCHes, and it never asks for a brief it was not given.
    if c not in {"unknown-brief", "change-empty", "unknown-role"}))
def test_every_failure_the_service_can_send_gets_a_specific_message(status, code, monkeypatch):
    """A falsification control on the node's error UI as a whole.

    Two ways to fail it, and both have happened in this pack: saying nothing useful, and saying
    something confidently wrong. `analysis-tool-missing` shares its 503 with an LLM outage and used
    to be reported as one, which sent people to fix an endpoint that was working.
    """
    _fake(monkeypatch, (status, {"detail": {"code": code, "message": "SERVICE SAID THIS"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "the service rejected the request" not in msg, \
        f"{code} reaches the generic branch and the user is told nothing about it"
    assert "unexpected reply" not in msg, \
        f"{code} reaches the catch-all branch, which reports a status number and nothing to do"
    assert "SERVICE SAID THIS" in msg, f"{code} discards the message the service wrote"
    if code != "llm-unavailable":
        assert "H3IR_LLM_URL" not in msg, f"{code} is blamed on the language model endpoint"


@pytest.mark.parametrize("status,code", sorted(
    (int(s), c) for s, c in _service_failures("assets")))
def test_every_upload_failure_the_service_can_send_names_the_slot(status, code, monkeypatch,
                                                                  tmp_path):
    """The same control for the other half of the conversation, held to the bar that half can meet.

    Not "pass the service's words through", because here the node knows something the service does
    not: which slot the person dropped this file on. The service can only say `a1b2c3...` -- the
    store is content-addressed, so that IS the file's name over there -- and a message naming a hash
    tells somebody with nine references nothing at all. So every upload failure has to name the slot,
    and none of them may fall through to the branch that reports a status number.
    """
    f = tmp_path / "ref.png"
    f.write_bytes(b"pixels")
    monkeypatch.setattr(C, "_put_file",
                        lambda *a, **k: (status, {"detail": {"code": code,
                                                             "message": "SERVICE SAID THIS"}}))
    with pytest.raises(C.ServiceError) as e:
        C.upload_asset("http://x", str(f), "a" * 64, "picture 1")
    msg = str(e.value)
    assert "would not take" not in msg, \
        f"{code} reaches the generic branch, which reports a status number and nothing to do"
    assert "picture 1" in msg, f"{code} does not say which of the graph's files it is about"


def test_a_dead_llm_endpoint_is_not_reported_as_the_nodes_fault(monkeypatch):
    _fake(monkeypatch, (503, {"detail": {"code": "llm-unavailable", "message": "connect refused"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "H3IR_LLM_URL" in msg
    assert "is running" in msg, "distinguish a live service with a dead model from a dead service"


def test_an_llm_error_says_the_graph_is_innocent(monkeypatch):
    _fake(monkeypatch, (502, {"detail": {"message": "model returned 500"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "Nothing is wrong with this node or the graph" in str(e.value)


def test_a_service_bug_is_reported_as_a_service_bug(monkeypatch):
    _fake(monkeypatch, (500, {"status": "invalid", "errors": []}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "bug in the service" in str(e.value)


def test_a_clarification_is_surfaced_as_a_question_not_a_crash(monkeypatch):
    _fake(monkeypatch, (201, {"id": "abc", "status": "needs_input",
                              "question": {"question": "Is the image the opening frame?"},
                              "default_if_unanswered": "reference"}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "Is the image the opening frame?" in msg
    assert "reference" in msg, "say what it would assume, so ignoring it is an informed choice"


def test_an_accepted_brief_returns_the_render_fields(monkeypatch):
    _fake(monkeypatch,
          (201, {"id": "deadbeef", "status": "ready"}),
          (200, {"prompt": "a document", "mode": "t2va", "frames": 192, "canvas": [1344, 768],
                 "wiring": [], "render_hash": "f" * 64}))
    out = C.compile_brief("http://x", {"intent": "a"})
    assert out["brief_id"] == "deadbeef"
    assert out["frames"] == 192
    assert out["degraded"] is False


def test_a_degraded_brief_is_flagged_rather_than_passed_off_as_written(monkeypatch):
    _fake(monkeypatch,
          (201, {"id": "d1", "status": "degraded", "fallback_reason": "model refused twice"}),
          (200, {"prompt": "p", "mode": "t2va", "frames": 124, "canvas": [1344, 768]}))
    out = C.compile_brief("http://x", {"intent": "a"})
    assert out["degraded"] is True
    assert "refused twice" in out["fallback_reason"]
    assert "not a written one" in C.report(out, compiler="the OpenH3-IR service at http://x", sizing_conflict=False)


def test_an_unexpected_status_carries_the_body_rather_than_just_the_number(monkeypatch):
    _fake(monkeypatch, (418, "I am a teapot"))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "418" in str(e.value) and "teapot" in str(e.value)


def test_an_accepted_brief_with_no_id_is_refused(monkeypatch):
    _fake(monkeypatch, (201, {"status": "ready"}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "no id" in str(e.value)


# ------------------------------------------------------- render fields: controls against guessing

@pytest.mark.parametrize("body,missing", [
    ({"frames": 192, "canvas": [1344, 768]}, "prompt"),
    ({"prompt": "  ", "frames": 192, "canvas": [1344, 768]}, "empty prompt"),
    ({"prompt": "p", "canvas": [1344, 768]}, "frame count"),
    ({"prompt": "p", "frames": 0, "canvas": [1344, 768]}, "frame count"),
    ({"prompt": "p", "frames": 192}, "canvas"),
    ({"prompt": "p", "frames": 192, "canvas": [1344]}, "canvas"),
])
def test_a_missing_render_field_raises_instead_of_defaulting(body, missing):
    """This is the control. If any of these ever returns a number, the node will render at a length
    or a size nobody chose, and the result will look like a model problem."""
    with pytest.raises(C.ServiceError) as e:
        C.render_fields(body)
    assert missing.split()[-1] in str(e.value).lower()


def test_render_fields_passes_through_exactly_what_the_service_said():
    prompt, w, h, length, sizing = C.render_fields(
        {"prompt": "doc", "frames": 243, "canvas": [1920, 1088],
         "wiring": [{"sizing": "max"}, {"sizing": "max"}]})
    assert (prompt, w, h, length, sizing) == ("doc", 1920, 1088, 243, "max")


# --------------------------------------------------------------------------- what the report says

def test_the_length_the_user_asked_for_is_printed_when_snapping_moved_it():
    """H3's grid is 17k+5 at 24 fps, so almost every request moves. Silently rendering 10.125 seconds
    for a 10 second script is how a mismatch gets blamed on the model."""
    notes = C.length_notes(10.0, 243)
    assert any("10.0s, snapped up onto the frame grid" in n for n in notes)


def test_a_length_inside_the_trained_band_says_nothing_extra():
    assert C.length_notes(8.0, 192) == [], "8.0 is the one whole second on the grid"


def test_a_long_render_is_reported_as_a_choice_rather_than_a_fault():
    """The range opens past H3's trained band deliberately, so the report carries the fact the
    surface no longer refuses."""
    notes = C.length_notes(20.0, 481)
    text = " ".join(" ".join(n.split()) for n in notes)
    assert "past H3's trained band" in text and "362 frames, 15.083s" in text
    assert "it is untested" in text and "VRAM and time" in text
    assert "note" in notes[-1].split()[0], "a choice belongs in the note register, not as a warning"


def test_a_short_render_is_reported_too():
    notes = C.length_notes(1.0, 39)
    text = " ".join(" ".join(n.split()) for n in notes)
    assert "below H3's trained band" in text and "124 frames, 5.167s" in text


def test_the_report_puts_the_users_own_socket_names_back_on_the_services_labels():
    """The only defence against the plausible-and-wrong case, and it is checkable because both sides
    hash the same bytes: the service's manifest, with the socket each file was plugged into."""
    body = {"mode": "ref2va", "frames": 243, "canvas": [1344, 768], "render_hash": "f" * 64,
            "wiring": [{"label": "<Picture 1>", "wiring": "ref_image_1", "sha256": "a" * 64,
                        "sizing": "match", "retention": "fully_preserved"},
                       {"label": "<Audio 1>", "wiring": "ref_video_audio_1", "sha256": "b" * 64}]}
    text = C.report(body, compiler="the OpenH3-IR service at http://x", sizing_conflict=False, asked_seconds=10.0,
                    bindings={"a" * 64: ["picture 1"], "b" * 64: ["clip 1 sound"]})
    assert "picture 1" in text and "<Picture 1>" in text and "ref_image_1" in text
    assert "fully_preserved" in text
    assert "clip 1 sound" in text and "<Audio 1>" in text


def test_the_same_file_on_two_sockets_gets_both_of_its_labels():
    """FOUND BY RENDERING. Files are content-addressed, so plugging one clip into two sockets sends
    one file twice, and a hash-keyed binding map lost the first socket: one label printed as `?`. Both
    sockets are real, and they take their labels in the order the service numbered them."""
    written = [("sound effect", "audio", "/same.wav", {}),
               ("voice to match", "audio", "/same.wav", {})]
    bindings = C.bindings_by_content(written, lambda _p: "s" * 64)
    assert bindings == {"s" * 64: ["sound effect", "voice to match"]}
    body = {"mode": "ref2va", "frames": 192, "canvas": [1344, 768], "wiring": [
        {"label": "<Audio 1>", "wiring": "ref_audio_1", "sha256": "s" * 64, "kind": "audio"},
        {"label": "<Audio 2>", "wiring": "ref_audio_2", "sha256": "s" * 64, "kind": "audio"}]}
    text = C.report(body, compiler="the OpenH3-IR service at http://x", sizing_conflict=False, bindings=bindings)
    assert "?" not in text, text
    assert "sound effect" in text and "voice to match" in text
    lines = [ln for ln in text.splitlines() if "<Audio" in ln]
    assert "sound effect" in lines[0] and "voice to match" in lines[1], \
        "in numbering order, so the first socket sent takes the first label"

def test_a_sound_is_not_labelled_with_a_sizing_it_has_no_use_for():
    """The service's own manifest defaults `sizing` to match on every entry, so printing it for a
    sound reads as a setting somebody chose about a thing that has no pixel area."""
    body = {"mode": "ref2va", "frames": 141, "canvas": [1344, 768], "wiring": [
        {"label": "<Audio 1>", "wiring": "ref_video_audio_1", "sha256": "b" * 64, "kind": "audio",
         "sizing": "match"},
        {"label": "<Video 1>", "wiring": "ref_video_1", "sha256": "a" * 64, "kind": "video",
         "sizing": "match"}]}
    text = C.report(body, compiler="the OpenH3-IR service at http://x", sizing_conflict=False,
                    bindings={"a" * 64: "clip 1", "b" * 64: "clip 1 sound"})
    audio_line = next(ln for ln in text.splitlines() if "<Audio 1>" in ln)
    assert "sizing" not in audio_line
    assert "ref_video_audio_1" in audio_line, "the wiring it rides is the fact worth printing"
def test_a_label_that_lands_on_no_socket_is_shown_as_unknown_rather_than_guessed():
    body = {"mode": "ref2va", "frames": 243, "canvas": [1344, 768],
            "wiring": [{"label": "<Picture 1>", "wiring": "ref_image_1", "sha256": "z" * 64}]}
    text = C.report(body, compiler="the OpenH3-IR service at http://x", sizing_conflict=False, bindings={})
    assert "?" in text and "<Picture 1>" in text


def test_every_report_line_lines_its_facts_up_in_one_column():
    """It is read in a monospace box, and a wrapped sentence whose continuation starts under the
    label reads as a new fact."""
    got = C.line("note", "x " * 80)
    first, second = got.splitlines()[0], got.splitlines()[1]
    assert first.startswith("note") and len(first) <= 94
    assert second.startswith(" " * 15) and second[15] != " "


# ---------------------------------------------------- finding the path without asking anyone to type it

def test_comfyuis_own_folder_is_offered_first_and_the_wsl_spelling_second():
    """ComfyUI's location comes from ComfyUI. What cannot be known is how a service on another view
    of the same disk spells it, so the usual forms are offered and the service confirms one."""
    got = C.path_candidates(r"C:\ComfyUI-Production")
    assert got[0] == r"C:\ComfyUI-Production", "try it as-is first, which is right when they share a disk"
    assert "/mnt/c/ComfyUI-Production" in got, "the ComfyUI-on-Windows, service-in-WSL case"


def test_a_posix_root_offers_only_itself():
    """No drive letter means nothing to translate, and inventing candidates would just slow the
    failure down."""
    assert C.path_candidates("/opt/ComfyUI") == ["/opt/ComfyUI"]


def test_there_is_nothing_to_type_and_no_second_argument_to_type_it_into():
    """The hand-typed override is gone with the field it belonged to. Every spelling that can work is
    a spelling of a folder ComfyUI already named, and the one case a box could not fix is a service on
    another machine, which cannot open these files under any spelling at all."""
    import inspect

    assert list(inspect.signature(C.path_candidates).parameters) == ["comfy_root"]


def test_only_an_unreachable_attachment_is_worth_another_attempt():
    """Trying again on anything else would hide a real problem behind repeated attempts, and asking a
    dead model endpoint three times is three times the wait for the same answer."""
    assert C.send_the_bytes(C.ServiceError("nope", C.PATH_MAY_BE_WRONG)) is True
    assert C.send_the_bytes(C.ServiceError("nope", C.SEND_THE_BYTES)) is True
    assert C.send_the_bytes(C.ServiceError("llm is down")) is False
    assert C.send_the_bytes(ValueError("something else")) is False


def test_the_retry_marker_is_not_named_after_the_one_failure_it_must_not_retry():
    """The service's own code for a file it opened and could not decode is `asset-unreadable`. If the
    retry marker carried that string, the next person to wire the service's code straight into
    `send_the_bytes` would earn a transfer, and then three attempts, at a corrupt clip for the same
    answer."""
    assert C.PATH_MAY_BE_WRONG != "asset-unreadable"
    assert C.send_the_bytes(C.ServiceError("corrupt", "asset-unreadable")) is False


def test_the_asset_failure_actually_carries_that_code(monkeypatch):
    """The retry is worthless if the error it looks for is never raised. This is the wire between
    the two."""
    _fake(monkeypatch, (422, {"detail": {"code": "asset-missing", "message": "no such file"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert C.send_the_bytes(e.value) is True


def test_a_megapixels_value_below_the_services_floor_is_refused_with_the_range():
    """The widget steps from 0.05 while the service floor is 0.25, so 0.05-0.20 used to travel to
    the service and come back as a nameless 422. The dead zone gets a sentence instead."""
    with pytest.raises(C.ServiceError) as e:
        C.build_payload("a shot", seconds=5.0, aspect="16:9", creativity="balanced",
                        effort="standard", seed=7, silent=False, shots="auto", assets=[],
                        transcripts={}, megapixels=0.1)
    msg = str(e.value)
    assert "0.25" in msg and "0" in msg


def test_zero_megapixels_still_means_native_and_omits_the_field():
    p = C.build_payload("a shot", seconds=5.0, aspect="16:9", creativity="balanced",
                        effort="standard", seed=7, silent=False, shots="auto", assets=[],
                        transcripts={}, megapixels=0.0)
    assert "megapixels" not in p


def test_a_legal_megapixels_value_travels():
    p = C.build_payload("a shot", seconds=5.0, aspect="16:9", creativity="balanced",
                        effort="standard", seed=7, silent=False, shots="auto", assets=[],
                        transcripts={}, megapixels=0.6)
    assert p["megapixels"] == 0.6


# --------------------------------------------------------------------------- the director

def test_a_director_that_did_not_arrive_is_reported_not_swallowed():
    """The one thing a director can do silently: direction travels, something upstream drops it, and
    the brief compiles perfectly with no direction at all. The node knows it sent something and the
    record says what was used; disagreement between those two is the whole failure, and it needs no
    new channel to detect."""
    from openh3ir.h3ir_client import director_note
    assert director_note(False, "") == ""
    assert director_note(False, "director: none") == ""
    assert director_note(True, "director: Wong Kar-wai") == ""
    assert director_note(True, "director: My noir") == ""
    assert "no direction at all" in director_note(True, "director: none")
    assert "no direction at all" in director_note(True, "")


def test_the_payload_omits_the_director_when_nothing_is_written():
    """A graph with no Director node must send byte-identically to one written before the node
    existed, or two payloads differ over a default nobody chose. A node dropped in and left blank is
    the same request as no node at all -- it is somebody who has not written it yet."""
    from openh3ir.h3ir_client import build_payload
    common = dict(seconds=8.0, aspect="16:9", creativity="balanced", effort="standard", seed=7,
                  silent=False, shots="auto", assets=[], transcripts={})
    plain = build_payload("a man walks", **common)
    assert "director" not in plain and "director_profile" not in plain
    blank = build_payload("a man walks", director_profile={"name": "Mine", "notes": "  "}, **common)
    assert "director_profile" not in blank
    steered = build_payload("a man walks",
                            director_profile={"name": "Mine", "notes": "sodium light"}, **common)
    assert steered["director_profile"] == {"name": "Mine", "notes": "sodium light"}
    # The id is the CLI's and an agent's, never this pack's: what is on the canvas is prose the user
    # can edit, so sending a name for it would send something they cannot see.
    assert "director" not in steered


def test_the_node_reads_its_one_field_and_refuses_only_what_is_not_that_shape():
    """Nothing about the writing is judged on the canvas. What is judged is whether the widget holds
    what the panel writes, because that is a fact about the widget rather than an opinion about
    somebody's paragraph."""
    from openh3ir.h3ir_client import ServiceError, director_bundle
    assert director_bundle(profile="") is None
    assert director_bundle(profile="{}") is None
    assert director_bundle(profile='{"name": "Mine", "notes": "   "}') is None
    assert director_bundle(profile='{"notes": "sodium light"}') == {"name": "Custom",
                                                                   "notes": "sodium light"}
    assert director_bundle(profile='{"name": " Mine ", "notes": " sodium light "}') == {
        "name": "Mine", "notes": "sodium light"}
    # A paragraph far past the compiler's cap travels: the sentence about it belongs to the compiler,
    # where the ask is assembled, and a second copy of the number here would be a second opinion.
    long = director_bundle(profile=json.dumps({"name": "x", "notes": "y" * 9000}))
    assert len(long["notes"]) == 9000
    with pytest.raises(ServiceError) as e:
        director_bundle(profile="{not json")
    assert "not readable" in str(e.value)
    with pytest.raises(ServiceError) as e:
        director_bundle(profile="[1, 2]")
    assert "has to be an object" in str(e.value)
