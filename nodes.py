"""One node that turns a sentence into a ready-to-sample MiniMax H3 job, one tray that holds
everything the piece looks at or listens to, and one that holds the machine it runs on.

The compile node replaces the text box, the resolution picker, the frame-count arithmetic, the
model, encoder and VAE loaders, and the H3 conditioning node. Out comes the model, the conditioning,
the latent and both VAEs, which is everything the rest of the graph needs.

Five ideas hold it together.

All the media is in one tray, and each slot says what it is. Drop a file, and the choice beside it is
what H3 will be told: a picture that IS the opening frame is a different job from a picture that is
something the shot should contain, and the tray is where that gets said rather than inferred. Every
slot carries a name, and the name is what the prompt refers to it by.

The prompt says where things go. `@carguy walks onto the gantry` names a slot, and
`@speaks("not for me")` locks a line the compiler then enforces word for word. Both are plain text
under whatever the canvas draws, so a graph submitted over the API and a graph typed on the canvas
are the same graph.

Length lives in one place. One seconds field, used for both the brief and the latent. Two dials that
both claim to set the duration is how eight seconds of a ten second script gets rendered.

Which file to load is a question only the user can answer. There is no search by name, no preferred
build and no sentinel that means "work it out": a filename says what a file is called, not what
somebody intended it to be, and a node that answers that question anyway is choosing for the user
without telling them. So the picks are visible on the Setup node, they are trivial to change, and the
report names every file that was loaded and the loader that read it.

The file is the format. A `.gguf` checkpoint or encoder loads through ComfyUI-GGUF's loader and a
`.safetensors` one loads natively, decided per file from the extension, with no toggle anywhere. A
boolean beside a filename would be two controls describing one fact, and two of its four states
would be wrong with nothing on the canvas to resolve them.

This uses ComfyUI's current node schema, the same one the stock H3 nodes use, so any ComfyUI that can
render H3 can load this. Heavy imports stay inside the functions that need them: an exception while
ComfyUI imports a custom node takes the whole pack off the menu with a traceback nobody can act on.

The panel on the tray and the chips in the prompt are drawn by `web/`, and they are decoration in the
strict sense: delete that folder and both nodes still work, still import, still API-drive, and still
restore from a saved workflow. The tray is JSON in a widget and the prompt is plain text in a widget,
and those two strings are the whole contract.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from comfy_api.latest import ComfyExtension, io

from . import tray as T
from .contract import differences as contract_differences
from .media import (digest, load_image, load_sound, load_video, resolve, sha256_file, stamp,
                    write_sound)
from .h3ir_client import (ASPECTS, CREATIVITY, DEFAULT_SERVER,
                          DIALOGUE_LANGUAGES,
                          EFFORT, FPS, SHOTS, SIZING, WEIGHT_DTYPES,
                          director_bundle, director_note,
                          ServiceError, bindings_by_content, check_mode,
                          clip_loader_for, compile_with_media, family_warning,
                          fetch_contract, inputs_fingerprint, is_gguf, payload_shape,
                          length_notes, line,
                          merge_model_options, precision_ignored_note, render_fields, report,
                          setup_bundle, unet_loader_for)

# One socket carrying eight facts about a machine, one carrying everything the piece looks at or
# listens to. Custom io types, so a plain IMAGE cannot be dropped into a socket that needs a bundle
# and the refusal happens on the canvas rather than after a queue.
Setup = io.Custom("H3IR_SETUP")
Media = io.Custom("H3IR_MEDIA")
Director = io.Custom("H3IR_DIRECTOR")


def _temp_dir() -> str:
    """A directory ComfyUI owns, falling back to the system temp outside it. Never beside this
    source: a node that writes into its own folder dirties a checkout and survives no update."""
    try:
        import folder_paths
        d = folder_paths.get_temp_directory()
    except Exception:  # noqa: BLE001 - importable outside ComfyUI is a supported case
        d = os.path.join(tempfile.gettempdir(), "openh3ir")
    os.makedirs(d, exist_ok=True)
    return d


def _comfy_root() -> str:
    """Where ComfyUI lives, asked of ComfyUI rather than typed by hand."""
    try:
        import folder_paths
        return str(folder_paths.base_path)
    except Exception:  # noqa: BLE001
        return ""


def _content_hashes():
    """A sha256-of-a-file function that reads each file at most once per queue.

    Not a cache across queues on purpose: a file can be replaced on disk under the same name, and a
    remembered hash would name the picture that used to be there. Within one queue the tray has
    already been read, so the bytes cannot change underneath it.
    """
    seen: dict[str, str] = {}

    def sha_of(path: str) -> str:
        if path not in seen:
            seen[path] = sha256_file(path)
        return seen[path]

    return sha_of


def _files(kind: str) -> list[str]:
    """Whatever this install actually has, so the dropdowns are real rather than a guess about
    someone's disk.

    An unregistered key comes back empty rather than raising, which is how the GGUF lists behave on
    an install without ComfyUI-GGUF: nothing is offered, so nothing can be selected that has no
    loader behind it.
    """
    try:
        import folder_paths
        return list(folder_paths.get_filename_list(kind))
    except Exception:  # noqa: BLE001 - an absent folder key is a fact, not a failure
        return []


def _model_options(native_kind: str, gguf_kind: str = "") -> list[str]:
    """A model combo: both builds of the same folder, merged into one list.

    No sentinel and no default, so the combo behaves like every loader in ComfyUI: it opens on a real
    filename, the filename is what the node shows, and changing it is one click.

    The GGUF half comes only from ComfyUI-GGUF's own registered list. It is never globbed off the
    disk, because a file offered with no loader behind it is exactly the plausible-and-wrong option
    this pack exists to prevent.
    """
    native = _files(native_kind)
    gguf = _files(gguf_kind) if gguf_kind else []
    return merge_model_options(native, gguf)


class OpenH3IRCompile(io.ComfyNode):
    """Sentence in; model, conditioning, latent and both VAEs out."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRCompile",
            display_name="OpenH3-IR Main",
            category="OpenH3-IR",
            search_aliases=["minimax", "h3", "openh3", "ir", "brief", "prompt", "ref2va", "fl2va",
                            "t2va"],
            description=("One sentence to a ready H3 job: writes the brief H3 wants, picks the right "
                         "weights, loads the encoder and VAEs, and outputs model, conditioning and "
                         "latent."),
            inputs=[
                # --------------------------------------------------------- this is what I want
                # No display name: on a multiline widget the placeholder is the only label there is,
                # and a display name would spend the row this box does not have.
                io.String.Input(
                    "intent", multiline=True, default="",
                    placeholder="one plain sentence, what happens, with @ for anything in the "
                                "tray\n@carguy walks onto the wet gantry in the rain and stops when "
                                "he sees the city below",
                    tooltip="One plain sentence. Not a tag list and not a shot breakdown, because "
                            "the compiler writes those. Say the action and the beat you care "
                            "about.\n\nType @ to name a slot in the media tray, which is how you "
                            "say where a file belongs in the shot. Type "
                            "@speaks(\"the exact words\") for a line that has to be said exactly: "
                            "those come back in the brief word for word and mark for mark, because "
                            "a brief that rewords one is refused. Words you merely quote in the "
                            "sentence get no such check."),
                io.Float.Input(
                    "seconds", display_name="seconds", default=8.0, min=1.0, max=149.0, step=0.1,
                    tooltip="The only place length is set, used for both the brief and the latent. "
                            "H3 renders on a 17 frame grid so this snaps up: ask for 10 and you get "
                            "10.125. 8.0 is the only whole second on the grid. H3's trained band is "
                            "5.167 to 15.083 seconds. Outside it a render still happens, untested "
                            "and slower, and the report says so."),
                io.Combo.Input(
                    "aspect", display_name="frame shape", options=list(ASPECTS), default="16:9",
                    tooltip="The canvas is sized from this, 768 on the short edge, so there is no "
                            "resolution box to keep in step with anything."),
                io.Combo.Input(
                    "creativity", display_name="invention", options=list(CREATIVITY),
                    default="balanced",
                    tooltip="How much the writer may add where your sentence is silent, which is "
                            "three things: a score, a spoken line, text in the frame. restrained "
                            "adds none of them. balanced may add a score. bold may also put words "
                            "in a mouth and text on screen. extreme adds nothing beyond bold, it "
                            "pushes every choice harder. Shot count is never on this dial, and "
                            "saying no dialogue in your sentence still means no dialogue at every "
                            "position."),
                io.Boolean.Input(
                    "silent", display_name="no music", default=False,
                    tooltip="H3 writes sound in the same pass as the picture, so silence is a "
                            "decision rather than an absence. This turns off the score only. "
                            "Ambient and physical sound still get written, and speech is governed "
                            "by your sentence and by invention."),
                io.Combo.Input(
                    "shots", display_name="shots", options=list(SHOTS), default="auto",
                    tooltip="auto is usually right: the writer decides the edit, and cut times "
                            "have to land on the frame grid too. A number is kept exactly, up to "
                            "10. Every shot needs 1.2 seconds, so a count that cannot fit the "
                            "video's length is refused with the arithmetic."),
                # The machine, and the only required socket. It sits here because ComfyUI groups every
                # required input ahead of every optional one when it publishes the schema, so a
                # declaration order that read better in this file would be a different node from the
                # one people are looking at.
                Setup.Input(
                    "setup", display_name="setup",
                    tooltip="Required. The service address and the five H3 files to load, from an "
                            "OpenH3-IR Setup node. Which files those are is your choice, so there is "
                            "one node that holds it and the report names every file that was "
                            "loaded."),

                # --------------------------------------------------------- and these are the words
                # Still the ask, and it reads with the ask on the canvas, but it is declared here
                # because ComfyUI publishes every required input ahead of every optional one and this
                # one has to stay optional: a required input is missing from every API-format graph
                # that was written before it existed, and that is a hard refusal at /prompt.
                io.Float.Input(
                    "megapixels", display_name="size, in megapixels", default=0.0, min=0.0,
                    max=2.5, step=0.05, optional=True,
                    tooltip="How many pixels the frame gets, the same number a resolution picker "
                            "calls 1.5. Zero means H3's native size, 768 on the short edge, which "
                            "is what it was trained at. Bigger is sharper, slower, and eats VRAM "
                            "in proportion; the report shows the exact canvas it bought."),
                io.Combo.Input(
                    "spoken_language", display_name="spoken in",
                    options=list(DIALOGUE_LANGUAGES), default=DIALOGUE_LANGUAGES[0], optional=True,
                    tooltip="The language every @speaks line in the sentence is spoken in. It "
                            "becomes the language tag in the brief, which is what H3 reads, so "
                            "Spanish words tagged English are spoken wrong. It decides nothing while "
                            "no line is locked. For a language that is not listed, quote the line in "
                            "the sentence instead and name the language there."),

                # --------------------------------------------------------- this is what it looks at
                Director.Input(
                    "director", display_name="director", optional=True,
                    tooltip="Optional. Whose taste fills what your sentence and your references do "
                            "not say: the camera, the framing, the light and colour, what the frame "
                            "looks at, how bodies and delivery are written, and what the room and "
                            "any score are made of. From an OpenH3-IR Director node, where it is "
                            "written as plain prose. Leave it unconnected and nothing steers the "
                            "writing, which is how every graph without one behaves.\n\nIt never "
                            "decides how many shots there are or where they cut, and anything you "
                            "state yourself wins over it: say 'a locked-off wide' and you get one "
                            "whoever is directing."),
                Media.Input(
                    "media", display_name="media", optional=True,
                    tooltip="Everything the piece looks at or listens to, from an OpenH3-IR Media "
                            "node: its pictures, clips and sounds, each one saying what it is. The "
                            "names of its slots are what @ in the sentence above refers to. Leave it "
                            "empty for a piece with no media at all."),

                # --------------------------------------------------------- rarely touched
                io.Combo.Input(
                    "sizing", display_name="reference size", options=list(SIZING), default="match",
                    optional=True, advanced=True,
                    tooltip="match fits each picture to the render's pixel area. max keeps the "
                            "picture's own size for stronger identity and is slower, because "
                            "reference tokens ride every sampling step."),
                io.Int.Input(
                    "seed", display_name="brief seed", default=7, min=0, max=0xFFFFFFFFFFFFFF,
                    optional=True, advanced=True,
                    tooltip="The compiler is seeded, so the same inputs give the same brief. Change "
                            "this for a different take on the same sentence. This is not the "
                            "sampler's seed."),
                io.Combo.Input(
                    "effort", display_name="writing effort", options=list(EFFORT),
                    default="standard", optional=True, advanced=True,
                    tooltip="max asks the writer for reasoning prose and is slower."),
            ],
            outputs=[
                io.Model.Output(display_name="model",
                                tooltip="Already the right H3 checkpoint for the job. Feed your "
                                        "LoRAs and sigma shift from here."),
                io.Conditioning.Output(display_name="positive"),
                io.Latent.Output(display_name="latent",
                                 tooltip="Empty picture and sound latent, already the length the "
                                         "brief was written for."),
                io.Vae.Output(display_name="vae",
                              tooltip="H3's video VAE for the decode, so the graph needs no "
                                      "loader boxes."),
                io.Vae.Output(display_name="audio_vae", tooltip="H3's audio VAE."),
                io.String.Output(display_name="prompt",
                                 tooltip="The compiled brief, to read or to keep."),
                io.String.Output(display_name="report",
                                 tooltip="What happened in plain words: the job, the real length, "
                                         "what each @ became, which slot became which picture, and "
                                         "every file loaded."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs: Any) -> Any:
        """Re-run when something changed and never otherwise. The compiler is seeded, so an unchanged
        graph re-queued would spend a model call to produce the same brief.

        The bundles are hashed by content, because the Media and Setup nodes hand over a dict whose
        `repr` is a memory address: hashing that would make a swapped file or a re-typed note look
        like no change at all. The Media bundle carries the tray's own text and the decoded tensors,
        so a file replaced on disk under the same name changes this hash too.
        """
        bundles = [digest(kwargs.pop("media", None)), digest(kwargs.pop("setup", None)),
                   # Hashed by content like the other two: a Director bundle's `repr` is a memory
                   # address, so hashing that would make a swapped profile look like no change and
                   # the cache would serve the brief the previous director wrote.
                   digest(kwargs.pop("director", None))]
        return inputs_fingerprint(sorted((k, repr(v)) for k, v in kwargs.items()), bundles)

    # ------------------------------------------------------------------ the work

    @classmethod
    def execute(cls, intent: str, seconds: float, aspect: str, creativity: str, silent: bool,
                shots: str, megapixels: float = 0.0,
                spoken_language: str = DIALOGUE_LANGUAGES[0], media=None,
                setup=None, director=None, sizing: str = "match", seed: int = 7,
                effort: str = "standard") -> io.NodeOutput:
        # The socket is required, so ComfyUI refuses an unconnected graph before this runs. This is
        # the same refusal in this pack's own words, for the graph that arrives over /prompt with the
        # socket present and empty: without the five picks there is nothing to load, and the node
        # will not choose five files on somebody's behalf.
        if not setup:
            raise ServiceError(
                "this node has no setup. Add an OpenH3-IR Setup node, pick the five H3 files it "
                "asks for (the ref2va and fl2va models, the clip, and the two VAEs) and wire "
                "its setup output into this node's setup socket. "
                "Which files those are cannot be worked out from their names, so they are your "
                "choice rather than a guess this node makes for you.")
        machine = setup
        # An empty tray and no tray at all are the same request: a piece with no media, which is what
        # this pack did before a tray existed and is still a legal graph.
        loaded = (media or {}).get("slots") or []
        slots = [entry["slot"] for entry in loaded]

        # Refused before a file is written or a model call is spent. Both refusals are about the
        # graph rather than about the brief: H3's fl2va model runs through a node with sockets for
        # the two frames and nothing else, so anything else in the tray would be described in the
        # brief, numbered in the report, and never handed to H3 at all.
        T.exclusivity(slots)
        # And the one about the swap roles: two pictures taking somebody's place and one of them
        # not saying whose is a question the render cannot answer. The panel says so the moment it
        # becomes true; this is the same sentence for a tray the panel never drew.
        T.check_swaps(slots)
        resolved = T.resolve_intent(intent, slots)

        declared = T.job_for(slots)
        frames_job = declared in ("i2va", "l2va", "fl2va")

        # One hash per file, taken once. Three things want it -- the transcript map, the report's
        # slot labels, and naming a file for a service that cannot see this disk -- and a reference
        # clip is big enough that reading it three times is a wait somebody would notice. Memoised
        # rather than passed around as a dict, so the same file on two slots is read once too.
        sha_of = _content_hashes()

        # One ordered list, read by the half that tells the service and by the half that fills H3's
        # sockets, so the two cannot disagree about which file is <Picture 1>.
        order = T.asset_order(slots)
        written, transcripts = cls._describe_everything(loaded, order, sha_of)
        bindings = bindings_by_content(written, sha_of)

        brief = dict(intent=resolved.intent, seconds=seconds, aspect=aspect,
                     creativity=creativity, effort=effort, seed=seed, silent=silent, shots=shots,
                     megapixels=megapixels, spoken=list(resolved.spoken),
                     spoken_language=spoken_language, director_profile=director)

        # Are the two halves talking about the same thing? The pack and the compiler are installed
        # separately and drift apart on purpose, and until this ran there was nothing anywhere that
        # noticed. Asked BEFORE the media travels, because a clip can be hundreds of megabytes and
        # the answer does not depend on it, and compared against what THIS graph is sending rather
        # than against everything the pack can do -- an older compiler is perfectly good for every
        # brief that uses nothing newer than itself, and breaking those would be worse than the
        # drift. One small GET; see contract.py for what is a stop and what is a line.
        asset_fields, brief_fields, roles = payload_shape(written, brief, transcripts)
        gaps = contract_differences(
            # Capped rather than given the compile timeout. The contract is a static dict with no
            # computation behind it, so a service that has not answered in half a minute is not
            # working on it -- and waiting out a ten-minute compile timeout here would push the
            # failure the NEXT request explains well past the point anybody is still watching.
            fetch_contract(machine["server"], timeout=min(30.0, float(machine["timeout_s"]))),
            asset_fields=asset_fields, brief_fields=brief_fields, roles=roles)
        stops = [g.message for g in gaps if g.stop]
        if stops:
            raise ServiceError("\n\n".join(stops))

        body, handoff = compile_with_media(
            server=machine["server"], written=written, sizing=sizing, sha_of=sha_of,
            comfy_root=_comfy_root(), transcripts=transcripts, timeout=float(machine["timeout_s"]),
            brief=brief)

        prompt, width, height, length, ref_sizing = render_fields(body)
        warning = check_mode(declared, str(body.get("mode", "")))

        # Which file, decided on the Setup node and read straight off it. What the tray says its
        # pictures are decides which of the two checkpoints this job needs, which is the one question
        # a graph can answer on its own.
        checkpoint = machine["frames_model" if frames_job else "reference_model"]
        encoder = machine["text_encoder"]
        video_vae = machine["video_vae"]
        audio_vae = machine["audio_vae"]

        model = cls._load_model(checkpoint, machine["weight_dtype"])
        clip = cls._load_clip(encoder)
        vae = cls._load_vae(video_vae)
        avae = cls._load_vae(audio_vae)

        positive, latent = cls._condition(
            declared=declared, clip=clip, vae=vae, audio_vae=avae, prompt=prompt, width=width,
            height=height, length=length, ref_image_size=ref_sizing, loaded=loaded, order=order)

        wiring = body.get("wiring") or []
        conflict = len({w.get("sizing") for w in wiring if w.get("sizing")}) > 1
        text = report(body, server=machine["server"], sizing_conflict=conflict,
                      asked_seconds=seconds, bindings=bindings)
        # Never silent: something was sent, against what the record says was used.
        mismatch = director_note(bool(director), str(body.get("director_used", "")))
        if mismatch:
            text += "\n" + line("note", mismatch)
        elif director:
            text += "\n" + line("director", str(body.get("director_used", director["name"])))
        # Everything the two halves disagree about that this graph did not depend on. After the
        # report's own facts, because they describe the render and these describe the setup.
        for gap in gaps:
            text += "\n" + line("note", gap.message)
        for said in T.mention_notes(resolved, slots):
            text += "\n" + said
        for said in cls._resample_notes(loaded):
            text += "\n" + said
        text += "\n" + line("job", declared)
        text += "\n" + line("weights", f"{checkpoint}  via {unet_loader_for(checkpoint)}")
        text += "\n" + line("encoder", f"{encoder}  via {clip_loader_for(encoder)}")
        text += "\n" + line("vaes", f"{video_vae}  +  {audio_vae}")
        if handoff:
            text += "\n" + handoff
        if is_gguf(checkpoint) and machine["weight_dtype"] != "default":
            text += "\n" + precision_ignored_note()
        # Both warnings go to the report and to the console. Nothing obliges anyone to wire the
        # report output to a node that shows it, and a warning nobody can see is not a warning.
        for said in (warning, family_warning(checkpoint, frames_job=frames_job)):
            if said:
                text += "\n" + line("WARNING", said)
                print("[OpenH3-IR] " + said)
        # A length outside the trained band is a choice, not a fault, so it stays in the `note`
        # register. It also goes to the console, because nothing obliges anyone to wire the report
        # output to a node that shows it.
        for note in length_notes(seconds, length):
            if note.startswith("note"):
                print("[OpenH3-IR] " + " ".join(note.split()[1:]))
        print(f"[OpenH3-IR] {declared}: {length} frames ({length / FPS:.3f}s), {width}x{height}")
        return io.NodeOutput(model, positive, latent, vae, avae, prompt, text)

    # ------------------------------------------------------------------ helpers

    @classmethod
    def _resample_notes(cls, loaded: list[dict[str, Any]]) -> list[str]:
        """One line per clip that was not filmed at H3's own rate, because it was resampled onto it
        and the frame count in the attachment block is therefore not the file's own."""
        out = []
        for entry in loaded:
            slot, fps = entry["slot"], entry.get("source_fps")
            if slot.kind != "video" or not fps or abs(float(fps) - FPS) <= 0.01:
                continue
            out.append(line("note", f"{slot.label} was filmed at {float(fps):g} fps and H3 reads "
                                    f"footage at {FPS}, so it was resampled onto that grid: "
                                    f"{entry['frames'].shape[0]} frames, "
                                    f"{entry['seconds']:.2f}s, the length the file actually is."))
        return out

    @classmethod
    def _describe_everything(cls, loaded: list[dict[str, Any]], order, sha_of):
        """Every file the tray sends, described for the service in the one order that numbers them.

        Nothing is converted here and almost nothing is written: the tray's files are already on
        disk, which is the point of a tray, so the service opens the very file the user dropped and
        H3 receives the very same file decoded. The exception is a clip's separated soundtrack, which
        lives inside the video container: the service needs a file per asset and a `.mp4` declared as
        audio is a file whose bytes contradict its declaration, so that one is written out as a wav.

        A soundtrack asset carries a pointer back to its own clip, which is what makes the service's
        <Audio j> the same soundtrack H3 receives as ref_video_audio_N: the runtime emits a paired
        soundtrack's label immediately before its clip's.
        """
        by_label = {entry["slot"].label: entry for entry in loaded}
        written: list[tuple[str, str, str, dict[str, Any]]] = []
        transcripts: dict[str, str] = {}
        temp = _temp_dir()

        for slot, part in order:
            entry = by_label[slot.label]
            if part == "file":
                kind = {"picture": "image", "video": "video", "sound": "audio"}[slot.kind]
                extra: dict[str, Any] = {"role": slot.role, "note": T.note_for(slot)}
                # Only ever set on a picture that replaces somebody: the service refuses it on any
                # other role rather than dropping it, which is the same answer the tray gives.
                if slot.replaces:
                    extra["replaces"] = slot.replaces
                if entry.get("seconds") is not None:
                    extra["seconds"] = round(float(entry["seconds"]), 3)
                if slot.kind == "video":
                    extra["frames"] = int(entry["frames"].shape[0])
                written.append((slot.label, kind, entry["path"], extra))
                if slot.transcript:
                    # The service keys transcripts by the file's own hash, taken here from the very
                    # bytes the service will read.
                    transcripts[sha_of(entry["path"])] = slot.transcript
                continue

            name = T.soundtrack_name(slot)
            snd_path, snd_seconds = write_sound(entry["its_sound"], name, temp)
            extra = {"role": "bgm", "seconds": round(snd_seconds, 3),
                     "note": f"{name}: the soundtrack of {slot.label}"}
            if slot.soundtrack == "paired":
                extra["paired_video_path"] = entry["path"]
            written.append((name, "audio", snd_path, extra))

        return written, transcripts

    # Getting the media to the service is `h3ir_client.compile_with_media`, not a method here.
    # Nothing in that decision needs a canvas -- `_comfy_root()` below is the only fact only ComfyUI
    # knows, and it is passed in -- and over there it can be exercised against a real service with
    # no ComfyUI in the process, which is how the remote path was proved.

    @classmethod
    def _node(cls, class_name: str, missing: str):
        import nodes
        cls_ = nodes.NODE_CLASS_MAPPINGS.get(class_name)
        if cls_ is None:
            raise ServiceError(missing)
        return cls_()

    @classmethod
    def _load_model(cls, name: str, weight_dtype: str):
        if is_gguf(name):
            loader = cls._node("UnetLoaderGGUF",
                               f"{name} is a GGUF checkpoint, and the ComfyUI-GGUF pack that reads "
                               "one is not installed. Install ComfyUI-GGUF, or pick a .safetensors "
                               "checkpoint on the Setup node.")
            return loader.load_unet(name)[0]
        return cls._node("UNETLoader", "ComfyUI's own UNETLoader is missing from this install, "
                                       "which no custom node can work around.") \
            .load_unet(name, weight_dtype)[0]

    @classmethod
    def _load_clip(cls, name: str):
        """H3's encoder, loaded as H3's family and never as whatever the loader defaults to.

        Both loaders resolve the CLIP type by name, and ComfyUI-GGUF's does it with a getattr whose
        default is STABLE_DIFFUSION: an unknown name there loads H3's encoder as the wrong family
        silently, and the render comes out plausible and wrong. So the member is asserted first.
        """
        import comfy.sd
        if not hasattr(comfy.sd.CLIPType, "MINIMAX"):
            raise ServiceError(
                "this ComfyUI does not know MiniMax H3's clip family (comfy.sd.CLIPType "
                "has no MINIMAX member), so the encoder would be loaded as the wrong family and "
                "the render would be wrong with nothing on screen to say so. Update ComfyUI to a "
                "version whose own MiniMax H3 nodes work.")
        if is_gguf(name):
            loader = cls._node("CLIPLoaderGGUF",
                               f"{name} is a GGUF clip, and the ComfyUI-GGUF pack that "
                               "reads one is not installed. Install ComfyUI-GGUF, or pick a "
                               ".safetensors clip on the Setup node.")
            return loader.load_clip(name, "minimax")[0]
        loader = cls._node("CLIPLoader", "ComfyUI's own CLIPLoader is missing from this install, "
                                         "which no custom node can work around.")
        try:
            return loader.load_clip(name, "minimax", "default")[0]
        except TypeError:
            return loader.load_clip(name, "minimax")[0]

    @classmethod
    def _load_vae(cls, name: str):
        return cls._node("VAELoader", "ComfyUI's own VAELoader is missing from this install, which "
                                      "no custom node can work around.").load_vae(name)[0]

    @classmethod
    def _condition(cls, *, declared, clip, vae, audio_vae, prompt, width, height, length,
                   ref_image_size, loaded, order):
        """Hand the conditioning to ComfyUI's own H3 nodes rather than reimplementing it. They own
        how references are tokenised and how the latent is packed, and a copy of that here would be
        the version that rots.

        `order` is the very list `_describe_everything` sent to the service, so <Picture N> in the
        brief and ref_image_N in the graph are the same N for every file. Deriving it twice is how a
        document describing one picture gets handed another, with nothing on screen to say so.
        """
        from comfy_extras.nodes_minimax_h3 import (MiniMaxH3ImageToVideo,
                                                  MiniMaxH3ReferenceToVideo)

        by_label = {entry["slot"].label: entry for entry in loaded}
        if declared in ("i2va", "l2va", "fl2va"):
            anchors = {T.ANCHOR_FIRST: None, T.ANCHOR_LAST: None}
            for slot, _part in order:
                if slot.role in anchors:
                    anchors[slot.role] = by_label[slot.label]["image"]
            out = MiniMaxH3ImageToVideo.execute(
                clip=clip, vae=vae, prompt=prompt, width=width, height=height, length=length,
                first_frame=anchors[T.ANCHOR_FIRST], last_frame=anchors[T.ANCHOR_LAST])
            return tuple(out.result)

        # Index-paired, exactly as the stock node reads them: ref_video_audio_N belongs to
        # ref_video_N. This is the pairing the service was told about, so the labels it computed and
        # the labels H3 receives are the same labels.
        ref_images: dict[str, Any] = {}
        ref_videos: dict[str, Any] = {}
        ref_video_audios: dict[str, Any] = {}
        ref_audios: dict[str, Any] = {}
        for slot, part in order:
            entry = by_label[slot.label]
            if part == "soundtrack":
                if slot.soundtrack == "paired":
                    ref_video_audios[f"ref_video_audio_{len(ref_videos)}"] = entry["its_sound"]
                else:
                    ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = entry["its_sound"]
            elif slot.kind == "picture":
                ref_images[f"ref_image_{len(ref_images) + 1}"] = entry["image"]
            elif slot.kind == "video":
                ref_videos[f"ref_video_{len(ref_videos) + 1}"] = entry["frames"]
            else:
                ref_audios[f"ref_audio_{len(ref_audios) + 1}"] = entry["sound"]
        out = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, audio_vae=audio_vae, prompt=prompt, width=width, height=height,
            length=length, ref_image_size=ref_image_size, ref_images=ref_images or None,
            ref_videos=ref_videos or None, ref_video_audios=ref_video_audios or None,
            ref_audios=ref_audios or None)
        return tuple(out.result)


class OpenH3IRSetup(io.ComfyNode):
    """The machine, not the shot: where the service is and which files to load.

    A picker, and only a picker. Every combo lists the files this install actually has, in both
    formats, and opens on one of them the way ComfyUI's own loaders do. Nothing is searched for by
    name, no build is preferred, and there is no option meaning "work it out": which of two H3
    checkpoints somebody meant is not written in either filename, so the answer belongs to the person
    who put the files there. The pick is on the canvas where it can be read and changed, and the
    compile node's report names every file it loaded.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRSetup",
            display_name="OpenH3-IR Setup",
            category="OpenH3-IR",
            search_aliases=["openh3", "h3", "ir", "service", "server", "gguf", "models"],
            description=("Where the OpenH3-IR service is, and which five H3 files to load. Every H3 "
                         "graph needs one: the compile node loads what you pick here."),
            inputs=[
                io.String.Input(
                    "server", display_name="OpenH3-IR service", default=DEFAULT_SERVER,
                    tooltip="Where the OpenH3-IR service is listening. Start one from the repo with "
                            "h3ir serve. It can be another machine."),
                io.Combo.Input(
                    "reference_model", display_name="ref2va model",
                    options=_model_options("diffusion_models", "unet_gguf"),
                    tooltip="H3's checkpoint for reference and text jobs. Both formats are in "
                            "this list: pick a .gguf and it loads through Unet Loader (GGUF), "
                            "pick a .safetensors and it loads like Load Diffusion Model does."),
                io.Combo.Input(
                    "frames_model", display_name="fl2va model",
                    options=_model_options("diffusion_models", "unet_gguf"),
                    tooltip="H3's checkpoint for first and last frame jobs. The compile node "
                            "uses this one or the ref2va model depending on which slots you "
                            "filled, and says which in its report. Both formats are in this "
                            "list."),
                io.Combo.Input(
                    "text_encoder", display_name="clip",
                    options=_model_options("text_encoders", "clip_gguf"),
                    tooltip="The Qwen3-VL encoder H3 was trained against, the same file a Load "
                            "CLIP node takes. Both formats are in this list, chosen independently "
                            "of the checkpoint: a GGUF clip works with safetensors weights and "
                            "the other way round."),
                io.Combo.Input(
                    "video_vae", display_name="vae", options=_model_options("vae"),
                    tooltip="H3's video VAE, used for the decode as well."),
                io.Combo.Input(
                    "audio_vae", display_name="audio vae", options=_model_options("vae"),
                    tooltip="H3's audio VAE, a different file from the video VAE. Needed even for "
                            "a silent piece, because H3 writes picture and sound together."),
                io.Combo.Input(
                    "weight_dtype", display_name="weight_dtype", options=list(WEIGHT_DTYPES),
                    default="default", advanced=True,
                    tooltip="The same setting a UNET loader has. Leave alone unless you are short "
                            "of VRAM. It does not apply to a GGUF checkpoint, which carries its own "
                            "quantisation, and the report says when it was ignored."),
                io.Int.Input(
                    "timeout_s", display_name="timeout, seconds", default=600, min=10, max=3600,
                    advanced=True,
                    tooltip="Writing a brief is one call to your language model, so this is as slow "
                            "as that model is."),
            ],
            outputs=[Setup.Output(display_name="setup")],
        )

    @classmethod
    def execute(cls, server: str, reference_model: str, frames_model: str, text_encoder: str,
                video_vae: str, audio_vae: str, weight_dtype: str = "default",
                timeout_s: int = 600) -> io.NodeOutput:
        return io.NodeOutput(setup_bundle(
            server=server, reference_model=reference_model, frames_model=frames_model,
            text_encoder=text_encoder, video_vae=video_vae, audio_vae=audio_vae,
            weight_dtype=weight_dtype, timeout_s=timeout_s))


class OpenH3IRDirector(io.ComfyNode):
    """Whose taste steers the writing, written as prose. Optional: a graph without one writes the
    way it always has.

    **A fourth node rather than a control on Main, and that is the owner's shape:** "should only be
    there if the user wants to steer, makes room for the other controls like saving the profiles and
    such." Most graphs never want direction, and a permanent row on the busiest node in the pack is
    a row everybody reads and almost nobody uses. Absent, it costs nothing; present, it has room for
    a paragraph.

    It also settles a question a combo on Main could not. There is exactly ONE place direction is
    written -- this node -- so there is no second dial to disagree with, which is the same fault as
    two widgets both claiming to set the duration. Unplug it and nothing steers; that is not a third
    state, it is the absence of the only one. There is no `none` on it for the same reason: the node
    IS the choice.

    **Two fields, and both of them are yours.** What to call this direction, and the direction
    itself. The seven directors the panel offers are not a menu that selects something invisible --
    each one writes its whole text into the box, where you can read it, change a line, or throw half
    of it away. A preset that shows you nothing is a preset you cannot learn from.

    **What direction reaches, and what it never does.** It fills what your sentence and your
    references leave open, and the compiler places it under a licence block that has already said in
    computed terms which attributes your own words took. It never sets how many shots there are or
    where they cut: pin `shots` on Main and the count is your contract, enforced; leave it on `auto`
    and the writer decides the edit, the way `auto` has always meant.

    **Everything typed here is a widget value**, so it is already kept in a saved workflow and in a
    rendered video's embedded graph, exactly as the media tray is: drag that mp4 back in and the
    direction comes with it. The panel's **save** and **forget** keep a copy in ComfyUI's own user
    folder, `user/default/openh3ir/directors/`, so a direction written here can be picked again in
    another graph. That store is a convenience and never a dependency: a graph carries the words it
    was written with rather than a pointer to a name, so this node compiles the same thing on a
    machine whose store is empty.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRDirector",
            display_name="OpenH3-IR Director",
            category="OpenH3-IR",
            search_aliases=["openh3", "h3", "ir", "director", "style", "look", "voice", "camera",
                            "cinematography", "steer", "custom", "profile", "taste"],
            # The node introduces itself here, in the node-library sidebar and in search, before
            # anybody opens it. It said the same thing the panel's lead used to say and the owner
            # rejected that sentence, so leaving it would have meant the node still speaking in the
            # voice he turned down, one step earlier than the panel.
            description=("Give a video a director. Whatever your own sentence leaves open gets "
                         "shot, lit and scored the way they would. Seven to pick from, all of them "
                         "editable, or write your own."),
            inputs=[
                io.String.Input(
                    "profile", display_name="direction", default="{}",
                    tooltip="The direction's own state, as text. The panel on this node writes it, "
                            "and it is a field rather than hidden state so that a saved workflow "
                            "and a rendered video carry the direction with them: drag that video "
                            "back in and it comes back. Two keys: what you call it, and the notes "
                            "themselves. Editing it by hand works."),
            ],
            outputs=[Director.Output(
                display_name="director",
                tooltip="Wire into the director socket on OpenH3-IR Main.")],
        )

    @classmethod
    def execute(cls, profile: str = "{}") -> io.NodeOutput:
        """Read the one field and hand it down the socket.

        Nothing about the writing is judged here. A cap on how long a direction may be belongs to
        the compiler, which is where the ask is assembled and where the sentence about it is
        written, and the panel says the same number while there is still something to do about it.
        An unwritten node is not an error: it hands over nothing, and Main compiles exactly as a
        graph with no Director node in it.
        """
        bundle = director_bundle(profile=profile)
        print("[OpenH3-IR] director  "
              + (f"{bundle['name']}, {len(bundle['notes'])} characters" if bundle
                 else "nothing written, so nothing steers"))
        return io.NodeOutput(bundle)


class OpenH3IRMedia(io.ComfyNode):
    """One tray for everything the piece looks at or listens to, and one name per file.

    Nine pictures, three clips, three sounds. Drop a file on a slot and two things about it get said
    that no socket could say: what it IS, chosen in plain words, and what it is CALLED, which is what
    the sentence on the Main node refers to it by. Both were unreachable before. A picture's role was
    fixed by which socket it arrived on, so the setting and the style were simply not expressible; and
    a picture had no name at all, so where it belonged in the shot was a note matched by position.

    The whole tray is one widget holding one string, and that string is the contract. It serialises
    into a saved workflow and into a rendered video's embedded graph like any other widget value, so
    dragging the mp4 back in restores the slots, their names, what each one is, its note and its file.
    The panel drawn on the node is a rendering of that string and can be deleted without changing what
    any graph does.

    Files, not tensors, and deliberately. The service opens attachments from disk and H3 receives them
    decoded, and when both come from one file on disk they cannot describe different pictures. The cost
    is real and worth naming: an IMAGE produced by another node in the same graph cannot be fed in
    here, so it has to be saved first. The gain is that the bytes the compiler was told about are the
    bytes that get rendered.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRMedia",
            display_name="OpenH3-IR Media",
            category="OpenH3-IR",
            search_aliases=["openh3", "h3", "ir", "media", "tray", "reference", "picture", "video",
                            "clip", "audio", "sound", "music", "voice", "upload", "load"],
            description=("Everything H3 looks at or listens to, in one tray: up to nine pictures, "
                         "three clips and three sounds, each saying what it is and carrying the name "
                         "the prompt refers to it by."),
            inputs=[
                io.String.Input(
                    "tray", display_name="slots", default="[]",
                    tooltip="The tray's own state, as text. The panel on this node writes it, and it "
                            "is a field rather than hidden state so that a saved workflow and a "
                            "rendered video carry the tray with them: drag that video back in and the "
                            "slots come back. Each slot names its kind, its label, what it is, its "
                            "note, and the file in ComfyUI's input folder. Editing it by hand works "
                            "and every rule about it is checked when the graph runs."),
            ],
            outputs=[Media.Output(
                display_name="media",
                tooltip="The whole tray, decoded once: every file's pixels or samples, its label, "
                        "what it is, and its note. Wire it into the media socket on OpenH3-IR "
                        "Main.")],
        )

    @classmethod
    def fingerprint_inputs(cls, tray: str = "[]") -> Any:
        """Re-run when the tray changed, or when a file it names changed on disk.

        A content hash rather than a clock, because the honest answer to "did this change" is the
        tray's own text plus the state of the files it points at. The text alone is not enough: a tray
        names files, and a file replaced under the same name would otherwise serve the pixels that
        used to be there for as long as ComfyUI's cache lived. The size and modification time are
        read rather than the bytes, because a re-queue must not cost a full read of twelve files.
        """
        try:
            slots = T.read_tray(tray)
        except ServiceError:
            # A tray this node is about to refuse still has to hash to something stable, or the
            # refusal arrives once and the cache answers for it afterwards.
            return inputs_fingerprint(tray, "unreadable")
        return inputs_fingerprint(tray, [stamp(s.file) for s in slots])

    @classmethod
    def execute(cls, tray: str = "[]") -> io.NodeOutput:
        slots = T.read_tray(tray)
        loaded: list[dict[str, Any]] = []
        for slot in slots:
            entry: dict[str, Any] = {"slot": slot, "path": resolve(slot.file),
                                     "image": None, "frames": None, "its_sound": None,
                                     "sound": None, "seconds": None, "source_fps": None}
            if slot.kind == "picture":
                entry["image"] = load_image(slot.file, slot.label)
            elif slot.kind == "video":
                frames, its_sound, source_fps = load_video(slot.file, slot.label)
                entry["frames"] = frames
                entry["source_fps"] = source_fps
                entry["seconds"] = int(frames.shape[0]) / float(FPS)
                if slot.soundtrack != "off":
                    if its_sound is None:
                        raise ServiceError(
                            f"{slot.label!r} asks for its soundtrack to be sent and the file has no "
                            "sound in it at all. Set its soundtrack to off on the OpenH3-IR Media "
                            "node, or drop a clip that has one.")
                    entry["its_sound"] = its_sound
            else:
                sound = load_sound(slot.file, slot.label)
                entry["sound"] = sound
                entry["seconds"] = float(sound["waveform"].shape[-1]) / float(
                    sound["sample_rate"] or 1)
            loaded.append(entry)

        for entry in loaded:
            slot = entry["slot"]
            shown = [slot.label, slot.kind, slot.words]
            if entry["seconds"] is not None:
                shown.append(f"{entry['seconds']:.2f}s")
            if slot.kind == "video":
                shown.append(f"{int(entry['frames'].shape[0])} frames at {FPS} fps")
                shown.append(f"soundtrack {slot.soundtrack}")
            print("[OpenH3-IR] tray  " + "  ".join(shown))
        if not loaded:
            print("[OpenH3-IR] tray  empty, so the piece has no media")
        return io.NodeOutput({"slots": loaded, "tray": tray})


# There is deliberately no text-preview node in this pack any more. One existed, and it drew an
# empty box on the canvas: the frontend never rendered its executed text, and a display node that
# displays nothing is worse than none. Core ComfyUI ships "Preview as Text" (PreviewAny), which
# accepts any input including our report string and renders it. Use that.

class OpenH3IRExtension(ComfyExtension):
    async def get_node_list(self):
        return [OpenH3IRCompile, OpenH3IRDirector, OpenH3IRMedia, OpenH3IRSetup]


async def comfy_entrypoint() -> OpenH3IRExtension:
    return OpenH3IRExtension()


__all__ = ["OpenH3IRCompile", "OpenH3IRDirector", "OpenH3IRMedia", "OpenH3IRSetup",
           "OpenH3IRExtension",
           "comfy_entrypoint", "ServiceError"]
