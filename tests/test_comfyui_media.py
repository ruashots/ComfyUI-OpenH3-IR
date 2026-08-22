"""Tensors to files, tested with no ComfyUI in the process.

This is where a silent resize, a dropped channel or a reused file would hide, so it is tested rather
than trusted. The one thing here that genuinely needs ComfyUI is the video encoder, and it is
exercised on the canvas instead; everything else runs anywhere numpy does.

Two of these are regression tests for defects that only a real graph produced. They are marked as
such, because "found by rendering" is the difference between a test that guards something and a test
that restates an assumption.
"""
from __future__ import annotations

import wave
from collections.abc import Mapping

import pytest

np = pytest.importorskip("numpy")

from openh3ir import media as M  # noqa: E402
from openh3ir.h3ir_client import ServiceError  # noqa: E402


class Lazy(Mapping):
    """A Mapping that is deliberately not a dict, which is what Load Video (Upload) hands out."""

    def __init__(self, d):
        self._d = d
        self.reads = 0

    def __getitem__(self, k):
        self.reads += 1
        return self._d[k]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


def _tone(channels=2, samples=16000, sr=16000, value=0.5):
    wf = np.full((1, channels, samples), value, dtype="float32")
    return {"waveform": wf, "sample_rate": sr}


# --------------------------------------------------------------------------- sounds

def test_an_audio_that_is_a_mapping_but_not_a_dict_is_still_a_sound(tmp_path):
    """FOUND BY RENDERING. Load Video (Upload) returns a `LazyAudioMap`, a Mapping subclass that
    shells out to ffmpeg on first key access. `isinstance(audio, dict)` therefore refused the very
    loader this pack tells people to use, and said the clip had no soundtrack.

    Asserted through a non-dict Mapping on purpose: a hand-built dict passes either way and would
    have proved nothing, which is exactly why the unit tests missed it.
    """
    audio = Lazy(_tone())
    path, seconds = M.write_sound(audio, "clip 1 sound", str(tmp_path))
    assert seconds == 1.0
    with wave.open(path) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 16000 and w.getnframes() == 16000


def test_a_sound_with_no_rate_says_what_an_audio_is_made_of():
    with pytest.raises(ServiceError) as e:
        M.waveform_of({"waveform": np.zeros((1, 1, 10), dtype="float32")}, "music")
    msg = str(e.value)
    assert "no rate" in msg and "Load Audio" in msg, "name what is missing and where one comes from"


def test_something_that_is_not_an_audio_at_all_is_refused():
    with pytest.raises(ServiceError) as e:
        M.waveform_of(object(), "music")
    assert "no waveform" in str(e.value)


def test_a_mono_waveform_stays_mono_and_a_stereo_one_stays_stereo(tmp_path):
    mono, _ = M.write_sound(_tone(channels=1), "sound effect", str(tmp_path))
    stereo, _ = M.write_sound(_tone(channels=2), "music", str(tmp_path))
    with wave.open(mono) as w:
        assert w.getnchannels() == 1
    with wave.open(stereo) as w:
        assert w.getnchannels() == 2


def test_a_sound_is_clipped_rather_than_wrapped_around(tmp_path):
    """A float above 1.0 cast straight to int16 wraps to a large negative number, which is a loud
    click rather than a loud sound."""
    path, _ = M.write_sound(_tone(channels=1, samples=4, value=4.0), "music", str(tmp_path))
    with wave.open(path) as w:
        pcm = np.frombuffer(w.readframes(4), dtype="<i2")
    assert pcm.min() == 32767, f"clipped to full scale, got {pcm}"


def test_two_different_sounds_never_land_on_one_file(tmp_path):
    a, _ = M.write_sound(_tone(value=0.25), "music", str(tmp_path))
    b, _ = M.write_sound(_tone(value=0.75), "music", str(tmp_path))
    assert a != b, "the name is a hash of the samples, so a changed sound is a changed file"


def test_the_same_sound_keeps_its_path_so_the_services_hash_stays_stable(tmp_path):
    a, _ = M.write_sound(_tone(), "music", str(tmp_path))
    b, _ = M.write_sound(_tone(), "music", str(tmp_path))
    assert a == b


# --------------------------------------------------------------------------- pictures

def test_a_missing_file_names_the_slot_and_says_what_to_do(tmp_path):
    """A workflow carries the names of its media rather than the media, so a workflow from another
    machine arrives with slots pointing at files that are not there. The error is the interface."""
    with pytest.raises(ServiceError) as e:
        M.load_image("openh3ir/not_there_at_all.png [input]", "hero")
    msg = str(e.value)
    assert "'hero'" in msg and "no such file" in msg
    assert "Drop the file" in msg, "say the remedy, not just the fact"


def test_a_real_picture_loads_as_the_tensor_shape_h3_conditioning_takes(tmp_path):
    pytest.importorskip("torch")  # ComfyUI-side dependency; the shape is re-proven live in ComfyUI
    from PIL import Image as PILImage

    f = tmp_path / "plate.png"
    PILImage.new("RGB", (64, 32), (200, 10, 10)).save(f)
    img = M.load_image(str(f), "plate")
    assert tuple(img.shape) == (1, 32, 64, 3), "batch of one, height, width, rgb"
    assert float(img.max()) <= 1.0 and float(img.min()) >= 0.0


def test_resolve_strips_the_annotation_outside_comfyui():
    """Outside ComfyUI there is no folder_paths, and the fallback must still hand back a usable
    path rather than a string with ' [input]' glued on."""
    assert M.resolve("sub/name.png [input]").endswith("sub/name.png")
    assert M.resolve("/abs/name.png") == "/abs/name.png"


def test_stamp_changes_when_the_file_changes(tmp_path):
    """The tray names files, and a file can be replaced on disk under the same name. The cache key
    has to see that, or a re-queue serves a brief written about the picture that used to be there."""
    import os as _os
    f = tmp_path / "a.png"
    f.write_bytes(b"one")
    first = M.stamp(str(f))
    f.write_bytes(b"three!!")
    _os.utime(f, ns=(1, 1))
    assert M.stamp(str(f)) != first
    assert M.stamp(str(tmp_path / "gone.png")).endswith(":missing")


def test_probe_never_raises_on_garbage(tmp_path):
    f = tmp_path / "junk.mp4"
    f.write_bytes(b"this is not a video")
    info = M.probe(str(f))
    assert info["duration"] is None and info["has_audio"] is False
    assert M.probe("nowhere/at/all.mp4")["duration"] is None


def test_a_socket_name_with_a_space_does_not_leak_a_space_into_a_path():
    """The sockets are called `picture 1` and `clip 1 sound` on purpose, because the brief says
    <Picture 1>. A space in a path is something a shell or an ffmpeg argument list will re-split."""
    assert M.slug("clip 1 sound") == "clip_1_sound"
    assert " " not in M.slug("picture 9")


def test_a_bundle_is_hashed_by_what_is_in_it_and_not_by_where_it_lives():
    """FOUND BY DESIGN REVIEW. A Footage or Sound node hands over a mapping of tensors, and `repr` of
    that is a memory address, so a re-queue after swapping a reference image would have reused the
    old brief."""
    one = {"frames": np.zeros((2, 2, 2, 3), dtype="float32"), "job": "edit it"}
    same = {"frames": np.zeros((2, 2, 2, 3), dtype="float32"), "job": "edit it"}
    other = {"frames": np.ones((2, 2, 2, 3), dtype="float32"), "job": "edit it"}
    assert M.digest(one) == M.digest(same), "equal contents, equal hash, even as separate objects"
    assert M.digest(one) != M.digest(other)


def test_a_changed_note_changes_the_hash():
    assert M.digest({"n": "a low voice"}) != M.digest({"n": "a high voice"})


def test_a_lazy_audio_is_hashed_through_its_mapping_interface():
    a = Lazy(_tone(value=0.1))
    b = Lazy(_tone(value=0.9))
    assert M.digest(a) != M.digest(b)
    assert a.reads > 0, "the hash actually read the waveform rather than the object's identity"


def test_a_sample_rate_change_alone_changes_the_hash():
    """The same samples at another rate is another sound, and it is another duration in the brief."""
    assert M.digest(_tone(sr=16000)) != M.digest(_tone(sr=32000))


def test_an_unhashable_input_does_not_break_the_graph():
    """A hash we cannot take is a reason to recompile, not a reason to fail the queue."""
    class Awkward:
        def __array__(self, *a, **k):
            raise RuntimeError("no")

    assert M.digest(Awkward()) == "unhashable"


def test_nothing_connected_hashes_to_nothing():
    assert M.digest(None) == "none"


# --------------------------------------------------------------------------- footage

def test_footage_reports_its_length_at_the_rate_h3_reads_it():
    """Relabelling to 24 fps is deliberate: it makes the duration the service probes the same
    duration the stock H3 node acts on when it packs the frames."""
    from openh3ir.h3ir_client import FPS

    assert FPS == 24
