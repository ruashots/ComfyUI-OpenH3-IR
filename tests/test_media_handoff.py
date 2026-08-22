"""Getting a graph's media to the service, both ways, tested with no ComfyUI and no server.

THE MEASURED PROBLEM. The nodes hand the service file paths and the service opens the user's
pictures, clips and sounds off its own disk. `path_candidates` tries the spellings a second view of
one disk can have -- `C:\\ComfyUI\\...` then `/mnt/c/ComfyUI/...` -- and its own docstring named the
case none of them covers: "the one case a box could not fix is a service on another machine, which
cannot open these files under any spelling." So every job with anything in the tray failed against a
service on another machine, and three places in the repo said the service was free to live there.

WHAT IS ASSERTED HERE is the sequence, because the sequence is the design: paths first and always,
uploads only once no spelling has worked, one request to find out what is missing, one transfer per
file rather than one per queue, and one retry. Sequence is what a live service cannot show you --
you cannot see from the outside whether the second queue sent bytes -- so it is counted here.

WHAT PROVES IT WORKS is not here: it is a real service in a container with the media directory not
mounted, driven by this same `compile_with_media`, compiling a picture, a clip, a paired soundtrack
and a voice reference end to end through a live vision model. That run cannot be CI's, because it
needs a model. The brief it produced was byte-identical to the one the path handoff produces from the
same graph, which is the strongest thing anybody measured about this: uploading is a transport, not a
second way of compiling.

THE FAKE BELOW IS A TRANSPORT, NOT A SERVICE. It answers with the service's own codes, and those
strings are pinned to `h3ir/service.py` by `_service_failures` in test_comfyui_node.py, which reads
them out of the source. A code renamed over there fails that test rather than quietly rotting this
one into a test of the fake.
"""
from __future__ import annotations

import hashlib

import pytest

from openh3ir import h3ir_client as C

PROMPT_BODY = {"prompt": "a document", "mode": "ref2va", "frames": 124, "canvas": [1344, 768],
               "wiring": [], "render_hash": "f" * 64}

BRIEF = dict(intent="a car pulls out of the dark", seconds=5.0, aspect="16:9",
             creativity="balanced", effort="fast", seed=7, silent=False, shots="auto",
             megapixels=0.0, spoken=[], spoken_language="English")


class Transport:
    """The service's answers, and a record of every request it was asked for."""

    def __init__(self, *, readable=(), holds=(), paths=True, max_bytes=10_000_000,
                 uploads=True, old=False, forgets=False):
        self.readable = set(readable)
        self.holds = set(holds)
        self.paths = paths
        self.max_bytes = max_bytes
        self.uploads = uploads
        self.old = old                    # a service with no `assets` block at all
        self.forgets = forgets            # drops every upload as fast as it arrives
        self.calls: list[tuple[str, str]] = []

    def request(self, server, path, *, payload=None, timeout=600.0):
        self.calls.append(("POST" if payload is not None else "GET", path))
        if path == "/v1/capabilities":
            if self.old:
                return 200, {"aspects": ["16:9"]}
            return 200, {"assets": {"paths": self.paths, "uploads": self.uploads,
                                    "upload_endpoint": "PUT /v1/assets/{sha256}",
                                    "upload_max_bytes": self.max_bytes}}
        if path.endswith("/prompt"):
            return 200, dict(PROMPT_BODY)
        assert path == "/v1/briefs", path
        assets = payload.get("assets") or []
        by_path = [a for a in assets if a.get("path") is not None]
        by_sha = [a for a in assets if a.get("sha256") is not None]
        if self.old and by_sha:
            # What a service older than the upload endpoint really does: its `AssetIn` has no
            # `sha256` field, pydantic drops the one it does not know, and the asset it is left with
            # has no path. So a hash-named request comes back as a complaint about a path.
            return 422, {"detail": {"code": "asset-no-path",
                                    "message": "each asset needs a `path` readable by the service"}}
        if by_path and not self.paths:
            return 422, {"detail": {"code": "asset-paths-disabled",
                                    "message": "this service does not open files from its own "
                                               "filesystem"}}
        for a in by_path:
            if a["path"] not in self.readable:
                return 422, {"detail": {"code": "asset-missing",
                                        "message": f"no such file: {a['path']}"}}
        absent = [a["sha256"] for a in by_sha if a["sha256"] not in self.holds]
        if absent:
            return 422, {"detail": {"code": "asset-not-uploaded", "missing": absent,
                                    "message": "this service does not hold 1 of the attachments"}}
        return 201, {"id": "abc123", "status": "ready"}

    def put(self, server, path, sha256, label, *, timeout=600.0):
        self.calls.append(("PUT", f"/v1/assets/{sha256[:12]}"))
        if not self.forgets:
            self.holds.add(sha256)
        return 201, {"sha256": sha256, "stored": True, "bytes": 99}

    # what the assertions read
    @property
    def posts(self):
        return [p for m, p in self.calls if m == "POST"]

    @property
    def puts(self):
        return [p for m, p in self.calls if m == "PUT"]


@pytest.fixture()
def wire(monkeypatch):
    def install(transport):
        monkeypatch.setattr(C, "_request", transport.request)
        monkeypatch.setattr(C, "_put_file", transport.put)
        return transport
    return install


@pytest.fixture()
def tray(tmp_path):
    """Two real files, shaped the way `_describe_everything` hands them over."""
    root = tmp_path / "ComfyUI"
    (root / "input").mkdir(parents=True)
    pic = root / "input" / "plate.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels" * 30)
    clip = root / "input" / "shot.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"frames" * 60)
    written = [
        ("picture 1", "image", str(pic), {"role": "subject", "note": "picture 1: the car"}),
        ("clip 1", "video", str(clip), {"role": "style", "note": "clip 1: how it is shot",
                                        "seconds": 4.0, "frames": 96}),
    ]
    return root, written


def sha_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(server="http://x", *, written, root, transcripts=None):
    return C.compile_with_media(server=server, written=written, sizing="match",
                                transcripts=transcripts or {}, timeout=600.0, brief=dict(BRIEF),
                                sha_of=sha_of, comfy_root=str(root))


def flat(text):
    """The report wraps its lines, so a sentence is only a sentence once the newlines are gone."""
    return " ".join(text.split())


# --------------------------------------------------------------- the fast path, exactly as it was

def test_a_service_that_shares_the_disk_is_handed_paths_and_nothing_else(wire, tray):
    """THE control on the whole change. This is the path every existing user is on and the fast one:
    nothing is copied, the service opens the very file the user dropped, and a 200 MB clip costs
    nothing to hand over. One request, no capabilities call, no transfer, and no note on the report.
    """
    root, written = tray
    t = wire(Transport(readable=[p for _n, _k, p, _x in written]))
    body, note = run(written=written, root=root)
    assert body["frames"] == 124
    assert t.posts == ["/v1/briefs"], t.calls
    assert t.puts == [], "the fast path sent bytes"
    assert "/v1/capabilities" not in [p for _m, p in t.calls], \
        "the fast path asked the service what it accepts, which it never needs to know"
    assert note == "", "an unremarkable handoff does not get a line on the report"


def test_the_second_spelling_of_the_folder_is_still_tried_and_still_reported(wire, tmp_path):
    r"""ComfyUI on Windows with the service in WSL: C:\ComfyUI is /mnt/c/ComfyUI over there. Still
    one file opened rather than one file sent, and the report says which spelling worked, because
    that is a fact about somebody's install that took a while to establish.
    """
    f = tmp_path / "ref.png"
    f.write_bytes(b"pixels")
    written = [("picture 1", "image", "C:\\ComfyUI\\input\\ref.png",
                {"role": "subject", "note": "picture 1"})]
    t = wire(Transport(readable=["/mnt/c/ComfyUI/input/ref.png"]))
    monkey_sha = lambda _p: "a" * 64          # noqa: E731 - the file is not on this disk
    body, note = C.compile_with_media(server="http://x", written=written, sizing="match",
                                      transcripts={}, timeout=600.0, brief=dict(BRIEF),
                                      sha_of=monkey_sha, comfy_root="C:\\ComfyUI")
    assert body["frames"] == 124
    assert t.posts == ["/v1/briefs", "/v1/briefs"], "one attempt per spelling until one opens"
    assert t.puts == [], "a shared disk must never turn into a transfer"
    assert "/mnt/c/ComfyUI" in note and "reads ComfyUI's folder" in note


def test_a_failure_that_is_not_about_paths_stops_everything(wire, tray):
    """A dead language model is not a reason to upload nine references. Retrying anything but an
    unresolvable path would hide a real problem behind repeated attempts."""
    root, written = tray
    t = Transport()
    t.request = lambda *a, **k: (503, {"detail": {"code": "llm-unavailable",
                                                  "message": "connect refused"}})
    wire(t)
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    assert "H3IR_LLM_URL" in str(e.value)
    assert t.puts == [], "it uploaded a graph's media because a model was down"


# --------------------------------------------------------------- the service on another machine

def test_media_that_no_spelling_reaches_is_sent_to_the_service(wire, tray):
    """The case the pack could not do at all. Nothing on the service's disk answers to these paths,
    so the files go to it, and the brief that comes back is a brief.
    """
    root, written = tray
    t = wire(Transport(readable=[]))
    body, note = run(written=written, root=root)
    assert body["frames"] == 124
    assert t.puts == [f"/v1/assets/{sha_of(p)[:12]}" for _n, _k, p, _x in written], \
        "every file this graph named, once each, in the order the service asked for them"
    assert t.posts == ["/v1/briefs", "/v1/briefs", "/v1/briefs"], (
        "one path attempt, one to find out what is missing, one after sending it", t.calls)
    assert "the service cannot see ComfyUI's folder" in note
    assert "picture 1" in note and "clip 1" in note, "name what was sent, in the user's own words"


def test_a_service_that_refuses_paths_is_not_asked_twice(wire, tmp_path):
    """A service that has said it does not open paths has answered for every spelling at once.
    Trying the rest is two more round trips for an answer already given.
    """
    root = tmp_path / "ComfyUI"
    (root / "input").mkdir(parents=True)
    f = root / "input" / "ref.png"
    f.write_bytes(b"pixels")
    written = [("picture 1", "image", str(f), {"role": "subject", "note": "picture 1"})]
    t = wire(Transport(paths=False))
    # A Windows root offers three spellings, so a short-circuit that does not work is visible here
    # and invisible with a posix root, which offers one.
    body, note = C.compile_with_media(server="http://x", written=written, sizing="match",
                                      transcripts={}, timeout=600.0, brief=dict(BRIEF),
                                      sha_of=sha_of, comfy_root="C:\\ComfyUI")
    assert t.posts.count("/v1/briefs") == 3, ("one refused path attempt, then hashes, then again",
                                              t.calls)
    assert t.puts, "the files were never sent"


def test_a_file_the_service_already_holds_is_not_sent_again(wire, tray):
    """What makes a big reference bearable, and the second queue's whole story: the digest has not
    changed, the store already answers to it, and no bytes move.
    """
    root, written = tray
    t = wire(Transport(readable=[], holds=[sha_of(p) for _n, _k, p, _x in written]))
    body, note = run(written=written, root=root)
    assert t.puts == [], "it re-sent files the service said it already had"
    assert t.posts == ["/v1/briefs", "/v1/briefs"], (
        "the path attempt and the hash attempt; nothing else is needed", t.calls)
    assert "already there: picture 1, clip 1" in flat(note)


def test_only_the_missing_half_is_sent(wire, tray):
    """The service's own list decides, because it is the one that knows what it holds."""
    root, written = tray
    held = sha_of(written[0][2])
    t = wire(Transport(readable=[], holds=[held]))
    _body, note = run(written=written, root=root)
    assert t.puts == [f"/v1/assets/{sha_of(written[1][2])[:12]}"], t.calls
    assert "already there: picture 1" in flat(note) and "sent to it" in flat(note)


def test_a_service_that_keeps_forgetting_is_told_about_once_and_not_looped_on(wire, tray):
    """One retry and no more. A file that has to be sent twice inside one queue is a service dropping
    uploads as fast as they arrive, and looping would spend somebody's evening re-sending a clip into
    a full disk instead of telling them the disk is full.
    """
    root, written = tray
    t = wire(Transport(readable=[], forgets=True))
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    msg = str(e.value)
    assert "dropped this graph's media straight after it was sent" in msg
    assert "H3IR_UPLOAD_STORE_BYTES" in msg and "H3IR_UPLOAD_TTL_HOURS" in msg, \
        "name the two settings that cause it"
    assert t.posts.count("/v1/briefs") == 3, ("path, hashes, hashes again, and then stop", t.calls)
    assert len(t.puts) == len(written), "each file was sent once, not once per attempt"


def test_a_transfer_the_service_refuses_is_reported_as_that_and_not_as_a_path_problem(wire, tray):
    """The paths failing is why the transfer was attempted, not what went wrong. What the person can
    act on is the file the service would not take, so that is the whole message."""
    root, written = tray
    t = Transport(readable=[])
    t.put = lambda *a, **k: (507, {"detail": {"code": "upload-store-full",
                                              "message": "there is no room"}})
    wire(t)
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    msg = str(e.value)
    assert "no room" in msg, "the service's own words about the transfer"
    assert "picture 1" in msg, "which file it was about"


def test_a_request_the_service_refuses_on_its_own_terms_is_not_dressed_up_as_a_path_problem(wire,
                                                                                           tray):
    """MEASURED against a live service, and the message was misleading: a still dropped on a clip
    slot came back wrapped in "the media in this graph could not reach the service", followed by a
    paragraph about spellings of ComfyUI's folder. The media reached it perfectly well. The service
    has the file and is refusing the request, and its own answer is the whole thing worth reading.
    """
    root, written = tray
    t = Transport(readable=[])
    real = t.request

    def refuses_hashes(server, path, *, payload=None, timeout=600.0):
        if payload and any(a.get("sha256") for a in payload.get("assets") or []):
            return 422, {"detail": {"code": "over-capacity",
                                    "message": "10 images attached; H3 has 9 image sockets"}}
        return real(server, path, payload=payload, timeout=timeout)

    t.request = refuses_hashes
    wire(t)
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    msg = str(e.value)
    assert "9 image sockets" in msg, "the service's own answer"
    assert "Spellings tried" not in msg and "could not reach" not in msg, \
        "the path story is why the files were sent, not what went wrong"
    assert t.puts == [], "nothing was sent for a request the service refuses either way"


def test_a_service_that_cannot_be_reached_either_way_says_both_fixes(wire, tray):
    """The one service this happens with: older than the upload endpoint. It cannot open ComfyUI's
    folder and it does not understand a request that names its media by content hash, so both facts
    are in the message, because they are two different fixes.
    """
    root, written = tray
    t = wire(Transport(readable=[], old=True))
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    msg = str(e.value)
    assert "older than this node pack" in msg and "git pull" in msg, "the likely fix"
    assert "read access" in msg, "and the other one"
    assert repr(str(root)) in msg, "which spelling of the folder it was offered"
    assert "nothing in the tray works either way" in msg, "and what does work meanwhile"
    assert t.puts == [], "it tried to send files to a service with nowhere to put them"


def test_a_prompt_with_nothing_in_the_tray_is_never_blamed_on_the_media(wire, tmp_path):
    """An empty tray cannot produce a path failure, so a failure with an empty tray is about
    something else and must be reported as itself."""
    t = Transport(readable=[])
    t.request = lambda *a, **k: (500, {"status": "invalid", "errors": []})
    wire(t)
    with pytest.raises(C.ServiceError) as e:
        run(written=[], root=tmp_path)
    assert "bug in the service" in str(e.value)
    assert t.puts == []


def test_the_service_asking_for_a_file_this_graph_never_named_is_refused(wire, tray):
    """It would mean the two sides disagree about what is attached, and a brief written about media
    the render never receives is the failure with no symptom."""
    root, written = tray
    t = wire(Transport(readable=[]))
    real = t.request

    def confused(server, path, *, payload=None, timeout=600.0):
        status, body = real(server, path, payload=payload, timeout=timeout)
        if isinstance(body, dict) and body.get("detail", {}).get("missing"):
            body["detail"]["missing"] = ["9" * 64]
        return status, body

    t.request = confused
    wire(t)
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    assert "never named" in str(e.value) and "defect in OpenH3-IR" in str(e.value)


def test_sending_a_file_says_so_on_the_console(wire, tray, capsys):
    """A first queue against a service on another machine moves every reference across the network,
    and a wait with no output is indistinguishable from a hang."""
    root, written = tray
    wire(Transport(readable=[]))
    run(written=written, root=root)
    out = capsys.readouterr().out
    assert "sending picture 1 to http://x" in out and "sending clip 1" in out


# --------------------------------------------------------------- what an upload is told about a file

def test_an_uploaded_asset_carries_every_fact_a_path_asset_carries(tray):
    """THE control on the second way in. Everything about an attachment except where its bytes are
    has to survive it, and each of these going missing would be silent: `role` is what stops the
    graph and the brief disagreeing, `note` is the only channel by which anything is known about a
    sound at all, and `seconds` decides what the writer is told about its length.
    """
    _root, written = tray
    by_path = C.plan_assets(written, "match", "", "")
    by_hash = C.plan_uploaded_assets(written, "match", sha_of)
    assert len(by_path) == len(by_hash)
    for p, h in zip(by_path, by_hash):
        assert p.pop("path")
        assert h.pop("sha256")
        assert p == h, "an attachment described differently depending on how it travels"


def test_a_paired_soundtrack_points_at_its_clip_by_hash(tray, tmp_path):
    """Sent as a path it would name nothing on the other machine, the pair would quietly stop being
    a pair, and the soundtrack would be numbered as a standalone sound while the runtime received it
    as that clip's own track."""
    _root, written = tray
    clip = written[1][2]
    snd = tmp_path / "clip_1_sound.wav"
    snd.write_bytes(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"samples" * 20)
    written = written + [("clip 1 sound", "audio", str(snd),
                          {"role": "bgm", "seconds": 4.0, "paired_video_path": clip,
                           "note": "clip 1 sound: the soundtrack of clip 1"})]
    out = C.plan_uploaded_assets(written, "match", sha_of)[-1]
    assert out["paired_video_sha256"] == sha_of(clip)
    assert "paired_video_path" not in out, "a path is meaningless on the machine this is going to"


def test_a_file_over_the_services_ceiling_is_refused_here_rather_than_transferred(tmp_path):
    """Nothing is sent. The service publishes what it accepts precisely so this is a sentence rather
    than a wait, and the sentence names the slot, the size, the ceiling and the setting."""
    f = tmp_path / "big.mp4"
    f.write_bytes(b"x" * 5000)
    with pytest.raises(C.ServiceError) as e:
        C.upload_asset("http://x", str(f), "a" * 64, "clip 1", max_bytes=1000)
    msg = str(e.value)
    assert "clip 1" in msg and "H3IR_UPLOAD_MAX_BYTES" in msg
    assert "Nothing was sent" in msg
    assert "4 KB" in msg and "1 KB" in msg, "a size a person reads, not a byte count"


def test_a_service_with_uploads_switched_off_says_so_before_sending_anything(wire, tray):
    """A service can be told to accept no uploads at all, which with no shared disk means there is
    no way to get media to it. Read off what it publishes, so it is a sentence rather than a failed
    transfer, and it names both things that produce it.
    """
    root, written = tray
    t = wire(Transport(readable=[], uploads=False))
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    msg = str(e.value)
    assert "H3IR_UPLOAD_MAX_BYTES" in msg, "the setting that turns it off"
    assert "older than this node pack" in msg, "and the other thing that looks identical from here"
    assert t.puts == [], "it sent bytes to a service that had said it would not take them"


def test_the_slot_label_replaces_the_hash_the_service_had_to_use(wire, tray):
    """MEASURED against a live service on another machine, with the commonest remote mistake there
    is -- a still dropped on a clip slot: "0f7a5659754169c6... was attached as kind: video, and its
    bytes are a image file", and then this pack's own "check the file in the tray slot the message
    names". It named no slot. It could not: an uploaded attachment IS its content hash over there.

    Both sides hash the same bytes, so putting the label back is exact rather than a guess. The whole
    token goes, not the hash inside it, or the store's own path would come back as
    `/state/uploads/0f/clip 1`.
    """
    root, written = tray
    t = Transport(readable=[])
    real = t.request
    clip_sha = sha_of(written[1][2])

    def refuses_the_clip(server, path, *, payload=None, timeout=600.0):
        if payload and any(a.get("sha256") for a in payload.get("assets") or []):
            return 422, {"detail": {
                "code": "asset-unreadable",
                "message": f"could not sample a single frame from {clip_sha} (attached as kind: "
                           f"video, /state/uploads/{clip_sha[:2]}/{clip_sha})"}}
        return real(server, path, payload=payload, timeout=timeout)

    t.request = refuses_the_clip
    wire(t)
    with pytest.raises(C.ServiceError) as e:
        run(written=written, root=root)
    msg = str(e.value)
    assert "clip 1" in msg, "the slot the person actually dropped the file on"
    assert clip_sha[:12] not in msg, "a hash is the store's name for the file, not the user's"
    assert "/state/uploads" not in msg, "and neither is a path inside the service's own state"


def test_the_report_line_says_how_the_media_got_there(tray):
    """Two ways in that cost differently, and only one of them is visible from the canvas."""
    assert C.handoff_note() == ""
    assert "reads ComfyUI's folder at /mnt/c/ComfyUI" in C.handoff_note(prefix="/mnt/c/ComfyUI")
    line = C.handoff_note(sent=(("picture 1", 2_000_000),), held=("clip 1",))
    assert "2 MB" in line and "picture 1" in line and "already there: clip 1" in line
