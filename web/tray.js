/* OpenH3-IR Media: the tray's panel, second construction.
 *
 * The first construction sized itself fluidly against whatever the host gave it, and the host's
 * layout system overrode every declaration: rows painted outside the node at some zooms and inside
 * at others. This one follows the reference loader's principle instead, which the owner spotted:
 * PIN the space for every possible slot beforehand, a fixed 476px board with all nine picture
 * cells, three clip rows and three sound rows drawn from the start, and populate cells as files
 * land. Nothing negotiates for room, so nothing can lose the negotiation.
 *
 * Everything here is rendering. The node's one real field is the `tray` string (JSON slots) and
 * this panel is an editor for it: delete this file and the node still works, still API-drives, and
 * still restores from a saved workflow. The role words and the naming rule MIRROR tray.py,
 * the authority: what it refuses at queue time, the name field here refuses as it is typed, so a
 * tray built on this panel cannot carry a name that would be turned away later.
 *
 * A file lands where it was aimed. Every cell answers a drag itself, so dropping onto a filled one
 * puts that file in its place and keeps the name a prompt already mentions; dropping anywhere else
 * fills the first free cell of that file's own kind, which is the only cell an empty square can
 * mean, because the board draws the slots it has in order and a gap in it is not a thing the tray
 * string can hold. The drag is planned before a byte is sent, and the same plan draws what lights
 * up under the cursor, so the preview cannot promise a landing the release does not make.
 *
 * Board geometry, slot styling and upload idioms follow
 * ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's medialoader.js (MIT), credited in README.md.
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const VERSION = "tray v16";
console.log("[OpenH3-IR]", VERSION);
const NODE = "OpenH3IRMedia";
const NODE_W = 578;
const NODE_H_EXTRA = 84;
const PANEL_H = 532;
const CAPACITY = { picture: 9, video: 3, sound: 3 };
const MAX_FILES = 12;
// The count the service enforces: every slot is a file, and a clip whose soundtrack is sent
// along ("paired") carries a second one. Counting slots here let a full-looking legal tray
// through to a queue-time refusal, with the panel's N/12 disagreeing with the enforcer.
const fileCount = (slots) =>
  slots.length + slots.filter((s) => s.kind === "video" && s.soundtrack === "paired").length;
const PREFIX = { picture: "picture", video: "video", sound: "audio" };
const ROLES = {
  picture: ["something in the shot", "the setting", "a style to copy",
            "add it to an existing clip", "replace the one in an existing clip",
            "first frame", "last frame", "storyboard"],
  video: ["copy what is in it", "copy how it is shot", "edit it", "carry on from it"],
  sound: ["play it", "match its style", "cut to its beat", "sound effect", "voice to match"],
};
const ROLE_TOKEN = {
  "something in the shot": "subject", "the setting": "environment", "a style to copy": "style",
  "add it to an existing clip": "placed_subject", "replace the one in an existing clip": "replacement_subject",
  "first frame": "frame_anchor_first", "last frame": "frame_anchor_last",
  "storyboard": "storyboard",
  "copy what is in it": "subject", "copy how it is shot": "structure", "edit it": "edit_source",
  "carry on from it": "continuation_source",
  "play it": "bgm", "match its style": "music_style", "cut to its beat": "beat_reference",
  "sound effect": "sfx", "voice to match": "voice_timbre",
};
const SOUNDTRACKS = ["off", "paired", "alone"];
// The one role that takes somebody's place, and so the one with somebody to name.
const REPLACEMENT = "replacement_subject";
/* The half of the sentence both halves of this pack say. tray.py refuses the job with it
 * when the graph runs; the panel says it the moment the tray becomes ambiguous, because a rule that
 * only refuses at queue time cannot stop a tray being built wrong. The shared words are held
 * against the Python by tests/test_panel_agrees_with_the_tray.py. */
const SAY_WHO = "replace someone in the clip, so each has to say who";
/* What each kind of slot accepts. web_api.py's EXTENSIONS is the authority -- the upload
 * route refuses by that table -- and tests/test_panel_aims_a_drop.py fails if this restatement
 * drifts from it. It is restated here so a drop can be planned before a byte is sent: a file no
 * slot takes is refused where it was dropped, and a file the tray has no room for is never uploaded
 * into ComfyUI's input folder to sit there with nothing pointing at it. */
const EXTENSIONS = {
  picture: [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"],
  video: [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg"],
  sound: [".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"],
};
// The board's own word for a kind. It heads its columns pictures, clips and sounds, so a refusal
// that says "video" is naming something the user cannot find on it.
const WORD = { picture: "picture", video: "clip", sound: "sound" };
// A drag still in the air carries the type of each file and never its name, so the preview reads
// the kind from that. The drop reads it from the extension, which is what the route judges by.
const KIND_BY_MIME = { image: "picture", video: "video", audio: "sound" };

/** The extension of a filename, by Python's rule, because Python's rule is what refuses it: a name
 *  that is nothing but dots has no extension, and `os.path.splitext` and this agree on that. */
function extensionOf(name) {
  const base = String(name ?? "").replace(/\\/g, "/").split("/").pop();
  const dot = base.lastIndexOf(".");
  if (dot < 0) return "";
  for (let i = 0; i < dot; i += 1) if (base[i] !== ".") return base.slice(dot);
  return "";
}

/** Which kind of slot a filename belongs on, or "" for a file no slot takes. */
function kindForName(name) {
  const ext = extensionOf(name).toLowerCase();
  for (const kind of Object.keys(EXTENSIONS)) if (EXTENSIONS[kind].includes(ext)) return kind;
  return "";
}

/** Which kind a file being dragged looks like, from the only thing a drag in flight exposes. */
function kindForType(type) {
  return KIND_BY_MIME[String(type ?? "").split("/")[0].toLowerCase()] || "";
}

/** Why the tray takes no such file, in the words the upload route refuses it with. */
function noKindFor(name) {
  const ext = extensionOf(name);
  return `the tray takes no ${ext || "extensionless"} file. `
    + `Pictures: ${EXTENSIONS.picture.join(", ")}. Clips: ${EXTENSIONS.video.join(", ")}. `
    + `Sounds: ${EXTENSIONS.sound.join(", ")}.`;
}

/** The plain name of the file a slot points at: no subfolder, no annotation. */
function fileNameOf(annotated) {
  return String(annotated ?? "").replace(/ \[(input|output|temp)\]$/, "").split("/").pop();
}
// What a filled cell wears so its settings are visible without opening the editor. Every slot
// wears its role in the same style: which role matters more is the user's business, not the
// panel's.
//
// A picture's badge is drawn OVER its thumbnail, so it has to hold one line. Measured on the
// board at rest: a picture cell is 64px, the note chip beside the role takes 12 of them, and 11
// characters of this font measure 47px. Twelve wrap, and a wrapped badge takes a fifth of the
// picture and pushes the image down. "replace in clip" was the first draft of the row below and
// did exactly that. tests/test_panel_agrees_with_the_tray.py holds the ceiling.
const BADGE_BY_KIND = {
  picture: { subject: "in shot", environment: "setting", style: "style",
             placed_subject: "add to clip", replacement_subject: "in place of",
             frame_anchor_first: "first", frame_anchor_last: "last", storyboard: "storyboard" },
  video: { subject: "copy", structure: "how it's shot", edit_source: "edit",
           continuation_source: "continue" },
  sound: { bgm: "play", music_style: "style", beat_reference: "beat", sfx: "sfx",
           voice_timbre: "voice" },
};
const DEFAULT_ROLE = { picture: "subject", video: "subject", sound: "bgm" };

/* What may name a slot. tray.py is the authority and refuses exactly this rule at queue
 * time; these three lines restate it so the panel can make a name it would refuse impossible to
 * type, and tests/test_panel_agrees_with_the_tray.py fails if the two ever drift apart.
 *
 * A name is letters, digits and dashes, it carries at least one letter or digit so that `-` is not a
 * name, and `speaks` is taken because @speaks( is the one other thing an @ can begin. */
const LABEL_CHAR = /[A-Za-z0-9-]/;
const LABEL_ALNUM = /[A-Za-z0-9]/;
const RESERVED = ["speaks"];
// The characters people separate words with inside a name. Each becomes the dash the rule allows,
// rather than being dropped: `the man` typed through as `theman` runs two words into one and is a
// different name from the one that was meant.
const SEPARATORS = " \t\n\r\f\v_./\\";

/** A typed name reduced to what may name a slot, with whatever could not be translated named back.
 *
 * Accents are folded instead of dropped, so a name types straight through in Spanish: jose with an
 * acute comes out jose, and pinata with a tilde comes out pinata, both of which the rule accepts.
 */
function cleanName(text) {
  const flat = String(text ?? "").normalize("NFD").replace(/\p{M}/gu, "");
  let out = "";
  const dropped = [];
  for (const ch of flat) {
    if (SEPARATORS.includes(ch)) out += "-";
    else if (LABEL_CHAR.test(ch)) out += ch;
    else if (!dropped.includes(ch)) dropped.push(ch);
  }
  return { text: out, dropped };
}

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "style") Object.assign(e.style, v);
    else if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e[k] = v;
  }
  for (const kid of kids) e.append(kid);
  return e;
}

function viewUrl(annotated) {
  const name = annotated.replace(/ \[(input|output|temp)\]$/, "");
  const type = (annotated.match(/\[(input|output|temp)\]$/) || [, "input"])[1];
  const i = name.lastIndexOf("/");
  const params = new URLSearchParams({
    filename: i < 0 ? name : name.slice(i + 1),
    subfolder: i < 0 ? "" : name.slice(0, i),
    type,
  });
  return api.apiURL("/view?" + params);
}

function autoLabel(kind, taken) {
  const used = new Set(taken.map((t) => String(t).toLowerCase()));
  for (let n = 1; n <= CAPACITY[kind] + 1; n++) {
    if (!used.has(`${PREFIX[kind]}${n}`)) return `${PREFIX[kind]}${n}`;
  }
  return `${PREFIX[kind]}${CAPACITY[kind] + 1}`;
}

class Tray {
  constructor(node, widget) {
    this.node = node;
    this.widget = widget;
    this.selected = null; // label of the slot the editor strip is showing
    this.dragKey = null;  // the aim and contents of the drag being previewed, so it is planned once
    this.saidBefore = null; // the top line before a drag wrote its preview over it

    this.counts = el("span", { class: "oh3-counts" });
    this.msg = el("span", { class: "oh3-msg" });
    const top = el("div", { class: "oh3-top" },
      this.counts, this.msg);

    this.picGrid = el("div", { class: "oh3-pics" });
    this.vidRows = el("div", { class: "oh3-vids" });
    this.sndRows = el("div", { class: "oh3-auds" });
    const right = el("div", { class: "oh3-col" },
      el("div", { class: "oh3-sec", textContent: "clips" }), this.vidRows,
      el("div", { class: "oh3-sec", textContent: "sounds" }), this.sndRows);
    const cols = el("div", { class: "oh3-cols" },
      el("div", { class: "oh3-col" },
        el("div", { class: "oh3-sec", textContent: "pictures" }), this.picGrid),
      right);

    this.editor = el("div", { class: "oh3-edit" });

    this.root = el("div", { class: "oh3-panel" }, top, cols, this.editor);
    this.watchDrags(this.root, null);
    this.render();
  }

  slots() {
    try { const v = JSON.parse(this.widget.value || "[]"); return Array.isArray(v) ? v : []; }
    catch { return []; }
  }

  write(slots) {
    this.widget.value = JSON.stringify(slots);
    this.node.setDirtyCanvas?.(true, true);
    this.render();
  }

  /** What the tray still has to be told, or "" when there is nothing outstanding.
   *
   *  One picture replacing somebody is never ambiguous: whatever it stands in for, only one picture
   *  is asking. Two are, and what is missing is not a count -- nothing here knows how many people a
   *  clip holds -- it is which figure each one stands in for. tray.py stops the job over
   *  exactly this; saying it here is what stops the user reaching the queue to find out.
   */
  nag() {
    const swapping = this.slots().filter((s) => s.role === REPLACEMENT);
    if (swapping.length < 2) return "";
    const silent = swapping.filter((s) => !String(s.replaces || "").trim());
    if (!silent.length) return "";
    const list = (xs) => (xs.length < 2 ? xs[0] || ""
      : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
    const named = (xs) => list(xs.map((s) => `@${s.label}`));
    // What is missing first: this line is one slot wide and ends in an ellipsis, and with the
    // general complaint in front it was the name of the picture still to answer that got cut.
    return `${named(silent)} `
      + (silent.length === 1 ? "does not say who it replaces." : "do not say who they replace.")
      + ` ${named(swapping)} ${swapping.length === 2 ? "both" : "all"} ${SAY_WHO}.`;
  }

  /** The top line. An outstanding question rides along with whatever just happened rather than
   *  replacing it: both are true, and the one the user did not ask for is the one that would
   *  otherwise be found at queue time. */
  say(text, bad = false) {
    const nag = this.nag();
    const full = nag ? (text ? `${text} ${nag}` : nag) : (text || "");
    this.msg.textContent = full;
    // One line, and it ends in an ellipsis when it does not fit. A name can be long enough to push
    // a refusal past the edge, so the whole sentence is on the line itself as well.
    this.msg.title = full;
    this.msg.classList.toggle("oh3-bad", !!bad || !!nag);
  }

  // ---------------------------------------------------------------- taking files in

  /** The file browser. A kind narrows it to what that kind of slot takes, so clicking an empty
   *  sound row does not offer pictures it would then have to turn away. */
  pick(kind) {
    const input = el("input", { type: "file", multiple: true });
    if (kind) input.accept = EXTENSIONS[kind].join(",");
    input.addEventListener("change", () => this.receive([...input.files], null));
    input.click();
  }

  /** Why one more file of this kind cannot go on this tray, or null if it can. */
  refuseFor(slots, kind) {
    if (slots.filter((s) => s.kind === kind).length >= CAPACITY[kind])
      return `all ${CAPACITY[kind]} ${WORD[kind]} slots are full.`;
    if (fileCount(slots) >= MAX_FILES)
      return `the tray takes at most ${MAX_FILES} files, and it is full. A clip whose soundtrack `
        + "is sent along counts as two.";
    return null;
  }

  /** Where these files would land, decided before a byte is sent.
   *
   *  `items` is one entry per file: a name at drop time, a kind on its own while the drag is still
   *  in the air, which is all a drag exposes. `aim` is the cell under the cursor, or null for the
   *  board's own space.
   *
   *  Two things come out of planning first rather than uploading first. A file that cannot fit is
   *  refused without being sent, instead of being written into ComfyUI's input folder and then
   *  refused, with the bytes left there and nothing pointing at them. And the preview under the
   *  cursor is drawn from this same plan, so it cannot promise a landing the release does not make.
   */
  plan(items, aim) {
    const slots = this.slots();
    const onto = aim ? slots.filter((s) => s.kind === aim.kind)[aim.index] || null : null;
    // The tray as this batch fills it, so each file is judged against the room the ones before it
    // left. A clip counts as one file here because whether it has a soundtrack to send is not known
    // until it has been uploaded; land() counts it again for real once it is.
    const projected = slots.slice();
    const moves = [];
    const refusals = [];
    let swapped = false;
    for (const item of items) {
      if (!item.kind) { refusals.push(noKindFor(item.name)); continue; }
      if (onto && !swapped && onto.kind === item.kind) {
        swapped = true;
        moves.push({ item, kind: item.kind, cell: aim.index, onto });
        continue;
      }
      const refusal = this.refuseFor(projected, item.kind);
      if (refusal) { refusals.push(refusal); continue; }
      const label = autoLabel(item.kind, projected.map((s) => s.label));
      moves.push({ item, kind: item.kind, label,
                   cell: projected.filter((s) => s.kind === item.kind).length });
      projected.push({ kind: item.kind, label, soundtrack: "off" });
    }
    // Refusals are NOT collapsed here: four pictures onto a tray with room for one is four
    // files turned away, and receive() counts them before it writes the one sentence.
    return { moves, refusals, stranded: onto && !swapped ? onto : null };
  }

  /** Take a set of files onto the tray, aimed at one cell or at the board.
   *
   *  What this leaves on the top line is the whole account of the drop: where each file went, and
   *  a sentence for anything that could not go anywhere. A drop where some files land and others
   *  are turned away is the ordinary case with a full tray, and the line has to carry both without
   *  the good half hiding the bad half.
   */
  async receive(files, aim) {
    const items = [...files].map((file) => ({ file, name: file.name, kind: kindForName(file.name) }));
    const { moves, refusals, stranded } = this.plan(items, aim);
    if (moves.length > 1) this.say(`sending ${moves.length} files…`);
    const landed = [];
    for (const move of moves) {
      try { landed.push(await this.land(move)); }
      catch (err) { refusals.push(String(err.message || err)); }
    }
    // Files turned away for the same reason are one sentence with a count in front of it. Four
    // pictures onto a tray with room for one is one full sentence and "3 files could not go on",
    // not the same sentence four times over.
    const tally = new Map();
    for (const refusal of refusals) tally.set(refusal, (tally.get(refusal) || 0) + 1);
    const trouble = [...tally].map(([sentence, n]) =>
      (n > 1 ? `${n} files could not go on: ${sentence}` : sentence));
    const said = [];
    if (landed.length) said.push(landed.join(", ") + (trouble.length || stranded ? "." : ""));
    // Only worth saying once something did land. When nothing did, the refusal below already
    // explains why, and this would be a second sentence about the same failure.
    if (stranded && landed.length)
      said.push(`@${stranded.label} holds a ${WORD[stranded.kind]}, so nothing in that drop took `
        + "its place.");
    said.push(...trouble);
    this.say(said.join(" ") || "nothing in that drop was a file.", trouble.length > 0);
  }

  /** Send one file and put it where the plan said.
   *
   *  The tray is read again here rather than carried over from the plan: an upload takes as long as
   *  it takes, and what was projected has to hold against the tray as it actually is when the bytes
   *  arrive. Everything this returns is a sentence about what happened to that one file.
   */
  async land(move) {
    const data = await this.upload(move.item.file);
    const slots = this.slots();
    const shown = data.original || data.name;
    if (move.onto) return this.swapInto(slots, move.onto.label, data, shown);
    const refusal = this.refuseFor(slots, move.kind);
    if (refusal) throw new Error(refusal);
    const slot = { kind: move.kind, label: autoLabel(move.kind, slots.map((s) => s.label)),
                   file: data.file, role: ROLE_TOKEN[ROLES[move.kind][0]], note: "" };
    if (move.kind === "video") slot.soundtrack = data.has_audio ? "paired" : "off";
    if (move.kind === "sound") slot.transcript = "";
    // The one file that can cost two. Room was checked before the upload, so the only way past
    // MAX_FILES from here is a clip that turned out to have a soundtrack to send along.
    const after = fileCount([...slots, slot]);
    if (after > MAX_FILES)
      throw new Error(`${shown} and its soundtrack would make ${after} files and the tray holds `
        + `${MAX_FILES}. A clip whose soundtrack is sent along counts as two.`);
    this.selected = slot.label;
    this.write([...slots, slot]);
    return `${shown} → @${slot.label}`;
  }

  /** One file put in another's place, keeping what the user set on the slot.
   *
   *  The name and the role are the wiring: a prompt that already says @hero has to go on meaning
   *  this slot, so a swap changes the file and leaves the rest alone. The two exceptions are the
   *  settings that are claims about the file itself, and carrying either onto a different file
   *  would have the panel state something untrue: a soundtrack sent along that the new clip does
   *  not have, and typed words that are the words of a recording that is gone.
   */
  swapInto(slots, label, data, shown) {
    const i = slots.findIndex((s) => s.label === label);
    if (i < 0) throw new Error(`@${label} left the tray while ${shown} was being sent.`);
    const slot = slots[i];
    if (slot.kind !== data.kind)
      throw new Error(`${shown} is a ${WORD[data.kind] || "file"} and @${label} is a `
        + `${WORD[slot.kind]} slot.`);
    const was = fileNameOf(slot.file);
    const patch = { file: data.file };
    const notes = [];
    if (slot.kind === "video" && (slot.soundtrack || "off") !== "off" && !data.has_audio) {
      patch.soundtrack = "off";
      notes.push("its soundtrack is off: the new clip has none");
    }
    if (slot.kind === "sound" && String(slot.transcript || "").trim()) {
      patch.transcript = "";
      notes.push("its typed words were cleared");
    }
    slots[i] = { ...slot, ...patch };
    this.selected = label;
    this.write(slots);
    return `${shown} replaced ${was} in @${label}`
      + (notes.length ? ` (${notes.join("; ")})` : "");
  }

  /** One file into ComfyUI's input folder, and the facts the panel shows for it. */
  async upload(file) {
    const body = new FormData();
    body.append("file", file, file.name);
    const resp = await api.fetchApi("/openh3ir/upload", { method: "POST", body });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `${file.name} did not upload (${resp.status}).`);
    return data;
  }

  // ---------------------------------------------------------------- the drag still in the air

  /** The three events an element answers to receive a file, wired the same way whether it is one
   *  cell or the whole board. A cell stops the event so the board does not overwrite the cell's aim
   *  with its own; what is left for the board's own handler is the space between the cells.
   */
  watchDrags(element, aim) {
    // A drag with no files in it is somebody else's: a node out of ComfyUI's sidebar, a link, a
    // selection. The board neither lights up for it nor takes it off the host's hands.
    const carriesFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
    const preview = (e) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      if (aim) e.stopPropagation();
      this.previewDrag(e, aim);
    };
    element.addEventListener("dragenter", preview);
    element.addEventListener("dragover", preview);
    element.addEventListener("drop", (e) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      if (aim) e.stopPropagation();
      this.saidBefore = null;
      this.endDrag();
      this.receive([...(e.dataTransfer?.files || [])], aim);
    });
    if (aim) return;
    // dragleave bubbles up from every cell, so the board is the one place that judges it, and it
    // judges by where the cursor went: the event fires on the way INTO each child element too, and
    // a board that unlit itself on every one of those would flicker through the whole drag.
    element.addEventListener("dragleave", (e) => {
      if (element.contains(e.relatedTarget)) return;
      this.endDrag();
      if (this.saidBefore) { this.say(this.saidBefore.text, this.saidBefore.bad); }
      this.saidBefore = null;
    });
  }

  /** What this drag would do: drawn on the board and said in words, from the plan that will run
   *  when it is released.
   *
   *  A drag carries types and no names, so a file whose type says nothing about it is left out of
   *  the preview rather than promised or refused on a guess. The line it writes is put back if the
   *  drag leaves without a drop, because whatever was on it belonged to what happened last.
   */
  previewDrag(e, aim) {
    // Two different unknowns, and running them together is how a preview lies. A file the system
    // has a type for that no slot takes is one the board can say no to now. A file it has no type
    // for at all -- which happens for perfectly good media on machines that do not know the
    // format -- is one the board says nothing about, because the extension settles it on release
    // and guessing either way would be a promise the drop might not keep.
    const dragged = [...(e.dataTransfer?.items || [])].filter((i) => i.kind === "file")
      .map((i) => ({ mime: String(i.type || ""), kind: kindForType(i.type) }));
    const placeable = dragged.filter((d) => d.kind);
    const untyped = dragged.filter((d) => !d.kind && !d.mime);
    const key = (aim ? `${aim.kind}:${aim.index}` : "board")
      + "|" + dragged.map((d) => d.kind || d.mime || "?").join(",");
    if (key === this.dragKey) return;   // dragover fires on every pixel; the plan changes only here
    this.dragKey = key;
    const { moves, refusals, stranded } = this.plan(placeable, aim);
    const nothingCanLand = dragged.length > 0 && !moves.length && !untyped.length;
    this.root.classList.toggle("oh3-hot", !nothingCanLand);
    this.root.classList.toggle("oh3-cold", nothingCanLand);
    this.mark(moves);
    if (!dragged.length) return;
    if (!this.saidBefore)
      this.saidBefore = { text: this.msg.textContent, bad: this.msg.classList.contains("oh3-bad") };
    const words = moves.map((m) => (m.onto
      ? `@${m.onto.label}, over ${fileNameOf(m.onto.file)}` : `@${m.label}`));
    const said = words.length ? [`drop → ${words.join(", ")}`] : [];
    if (stranded && moves.length)
      said.push(`@${stranded.label} holds a ${WORD[stranded.kind]}.`);
    said.push(...new Set(refusals));
    const turned = dragged.length - placeable.length - untyped.length;
    if (turned) said.push(turned === dragged.length
      ? `${turned > 1 ? "none of those are" : "that is not"} a picture, a clip or a sound.`
      : `${turned} of those are not a picture, a clip or a sound.`);
    if (said.length) this.say(said.join(" "), nothingCanLand || refusals.length > 0);
  }

  /** Light the cells this drop would land in. An arrival and a swap are drawn differently, because
   *  a user who cannot tell one from the other cannot aim.
   *
   *  A lit empty cell also wears the name its file would get. At rest a cell is captioned by its
   *  position on the board and a slot is named by the first free name, and the two are not always
   *  the same word: with @hero and @coat in the first two squares, the third square is captioned
   *  picture3 and the file dropped on it arrives as @picture1. Lit, it says @picture1, so the
   *  square and the sentence above it cannot be read as disagreeing.
   */
  mark(moves) {
    const grids = { picture: this.picGrid, video: this.vidRows, sound: this.sndRows };
    const take = {}, swap = {};
    for (const kind of Object.keys(grids)) { take[kind] = new Map(); swap[kind] = new Set(); }
    for (const m of moves) {
      if (m.onto) swap[m.kind].add(m.cell);
      else take[m.kind].set(m.cell, m.label);
    }
    for (const [kind, grid] of Object.entries(grids)) {
      [...grid.children].forEach((cell, i) => {
        const naming = take[kind].get(i);
        cell.classList.toggle("oh3-take", naming !== undefined);
        cell.classList.toggle("oh3-swap", swap[kind].has(i));
        // Only ever a cell whose whole content is its caption. A filled cell is a picture, a tag
        // and a remove button, and writing text into one would take all three out.
        if (cell.firstElementChild) return;
        if (naming !== undefined) {
          if (cell.dataset.rest === undefined) cell.dataset.rest = cell.textContent;
          cell.textContent = `@${naming}`;
        } else if (cell.dataset.rest !== undefined) {
          cell.textContent = cell.dataset.rest;
          delete cell.dataset.rest;
        }
      });
    }
  }

  /** The drag is over, by release or by leaving. Put the board back. */
  endDrag() {
    this.dragKey = null;
    this.root.classList.remove("oh3-hot", "oh3-cold");
    this.mark([]);
  }

  update(label, patch, said = "") {
    const slots = this.slots();
    const i = slots.findIndex((s) => s.label === label);
    if (i < 0) return;
    slots[i] = { ...slots[i], ...patch };
    if (patch.label) this.selected = patch.label;
    this.write(slots);
    // Every edit ends on the top line: whatever this one had to say, plus anything the tray is
    // still waiting to be told. Nothing said and nothing outstanding clears it, because the line
    // described the edit before this one.
    this.say(said);
  }

  remove(label) {
    if (this.selected === label) this.selected = null;
    this.write(this.slots().filter((s) => s.label !== label));
    this.say("");
  }

  // ---------------------------------------------------------------- naming a slot

  /** The name field, corrected as it is typed. A space becomes the dash the rule allows, and so does
   *  every other character people put between words in a name; anything left that cannot be a name
   *  does not go in, and the panel says which character it was rather than leaving a keyboard that
   *  looks broken. */
  fixName(input) {
    const at = input.selectionStart;
    const whole = cleanName(input.value);
    if (whole.text !== input.value) {
      const head = cleanName(input.value.slice(0, at)).text.length;
      input.value = whole.text;
      input.setSelectionRange(head, head);
    }
    input.classList.remove("oh3-wrongname");
    // The line speaks for the keystroke that just happened and nothing earlier: a message about a
    // character refused three keystroke ago, still sitting there while a clean name is typed, reads
    // as a complaint about the clean name.
    this.say(whole.dropped.length
      ? whole.dropped.map((c) => `“${c}”`).join(" ") + " cannot go in a name: a name is letters, "
        + "digits and dashes, and it follows an @."
      : "", true);
  }

  /** Why this name cannot be used, in a sentence, or nothing if it can.
   *
   *  The three cases no correction can fix: a name has to exist, it has to carry a letter or a
   *  digit, and it has to be free. Every one of them is legal characters and an unavailable name, so
   *  the field cannot head them off as they are typed and refuses to take them instead. */
  nameTrouble(name, current) {
    if (!name)
      return "a slot needs a name: it is what an @ in the prompt reaches this file by.";
    if (!LABEL_ALNUM.test(name))
      return "a name needs a letter or a digit in it, so dashes on their own cannot name a slot.";
    if (RESERVED.includes(name.toLowerCase()))
      return `${name} is taken, because @speaks( is how a spoken line starts in the prompt.`;
    const taken = this.slots().find((s) => s.label !== current
      && String(s.label).toLowerCase() === name.toLowerCase());
    if (taken)
      // The case note is not a footnote here: it is the whole reason SHOWROOM reads as taken when
      // the tray plainly shows showroom, and without it the refusal looks like a mistake.
      return `${taken.label} already names another slot, and case is ignored: @${name} is the same.`;
    return null;
  }

  rename(current, input) {
    const name = cleanName(input.value).text;
    const trouble = this.nameTrouble(name, current);
    if (trouble) {
      input.classList.add("oh3-wrongname");
      this.say(trouble, true);
      return;
    }
    this.say("");
    this.update(current, { label: name });
  }

  // ---------------------------------------------------------------- the pinned board

  cell(kind, index, slot) {
    // Every cell answers a drag itself. An empty one is where a file of its kind arrives, a filled
    // one is a file to put another in the place of, and both are aimed at by dropping on them.
    const aim = { kind, index };
    if (!slot) {
      const empty = el("div", { class: "oh3-slot", textContent: `${PREFIX[kind]}${index + 1}`,
        title: `drop a ${WORD[kind]} here, or click to browse for one`,
        onclick: () => this.pick(kind) });
      this.watchDrags(empty, aim);
      return empty;
    }
    const cls = { picture: "pic", video: "vid", sound: "aud" }[kind];
    const cell = el("div", { class: `oh3-slot oh3-filled oh3-${cls}`
      + (this.selected === slot.label ? " oh3-sel" : ""),
      title: `@${slot.label}: ${fileNameOf(slot.file)}. Drop a ${WORD[kind]} on it to put that `
             + "file in this one's place, keeping the name." });
    this.watchDrags(cell, aim);
    // Whatever the top line was saying belonged to the slot being left behind.
    cell.addEventListener("click", () => { this.say(""); this.selected = slot.label; this.render(); });

    if (kind === "picture") {
      cell.append(el("img", { class: "oh3-fit", src: viewUrl(slot.file), loading: "lazy" }));
      cell.append(this.badges(slot));
      cell.append(el("div", { class: "oh3-bar" },
        el("span", { class: "oh3-tag", textContent: "@" + slot.label }),
        el("span", { class: "oh3-x", textContent: "×",
          onclick: (e) => { e.stopPropagation(); this.remove(slot.label); } })));
      return cell;
    }

    const row = el("div", { class: "oh3-rowline" });
    if (kind === "video") {
      row.append(el("video", { class: "oh3-vthumb", src: viewUrl(slot.file), muted: true,
        loop: true, preload: "metadata",
        onmouseenter(e) { e.target.play?.(); }, onmouseleave(e) { e.target.pause?.(); } }));
    } else {
      row.append(el("button", { class: "oh3-play", textContent: "♪", title: "play",
        onclick: (e) => {
          e.stopPropagation();
          if (this._audio) { this._audio.pause(); this._audio = null; return; }
          this._audio = new Audio(viewUrl(slot.file));
          this._audio.play();
          this._audio.addEventListener("ended", () => { this._audio = null; });
        } }));
    }
    row.append(el("span", { class: "oh3-tag", textContent: "@" + slot.label }));
    row.append(this.badges(slot, true));
    row.append(el("span", { class: "oh3-x", textContent: "×",
      onclick: (e) => { e.stopPropagation(); this.remove(slot.label); } }));
    cell.append(row);
    return cell;
  }

  badges(slot, inline = false) {
    const wrap = el("span", { class: inline ? "oh3-badges oh3-inlinebadges" : "oh3-badges" });
    const word = (BADGE_BY_KIND[slot.kind] || {})[slot.role];
    if (word) wrap.append(el("span", { class: "oh3-badge oh3-rolebadge",
      textContent: word, title: "what it is: set in the editor below" }));
    if ((slot.note || "").trim()) wrap.append(el("span", { class: "oh3-badge",
      textContent: "✎", title: "described: " + slot.note }));
    if ((slot.transcript || "").trim()) wrap.append(el("span", { class: "oh3-badge",
      textContent: "abc", title: "its words are typed in" }));
    if (slot.kind === "video" && slot.soundtrack && slot.soundtrack !== "paired")
      wrap.append(el("span", { class: "oh3-badge",
        textContent: "sound " + slot.soundtrack,
        title: "its soundtrack: set in the editor below" }));
    return wrap;
  }

  // ---------------------------------------------------------------- the editor strip

  widgetRow(labelText, input) {
    return el("div", { class: "oh3-wrow" },
      el("span", { class: "oh3-wlabel", textContent: labelText }), input);
  }

  header() {
    return el("div", { class: "oh3-edithead" },
      el("div", { class: "oh3-edittitle", textContent: "What is this file to your clip?" }),
      el("div", { class: "oh3-editsub", textContent:
        "Name it to mention it, choose what it is, describe it. The brief is written from "
        + "exactly these." }));
  }

  renderEditor() {
    const slot = this.slots().find((s) => s.label === this.selected);
    if (!slot) {
      this.editor.replaceChildren(this.header(), el("div", { class: "oh3-hint", textContent:
        "Drop files on the board, or click an empty slot to browse. Drop one onto a filled slot to "
        + "put that file in its place, keeping the name. Click a filled slot to name it and say "
        + "what it is." }));
      return;
    }
    const label = el("input", { class: "oh3-in oh3-name", value: slot.label,
      title: "the name @ mentions this file by: letters, digits and dashes. A space becomes a dash "
             + "as you type it." });
    label.addEventListener("input", () => this.fixName(label));
    label.addEventListener("change", () => this.rename(slot.label, label));
    const role = el("select", { class: "oh3-in", title: "what this file is to the video" });
    for (const words of ROLES[slot.kind]) role.append(el("option", {
      value: ROLE_TOKEN[words], textContent: words, selected: ROLE_TOKEN[words] === slot.role }));
    role.addEventListener("change", () => {
      // Words about who this picture stands in for mean nothing on a role that stands in for
      // nobody, and tray.py refuses a slot carrying them. Cleared here rather than left to
      // be turned away at the queue, and said out loud rather than done quietly: it is the same
      // judgement a file swap makes about a soundtrack the new clip does not have.
      const drop = slot.role === REPLACEMENT && role.value !== REPLACEMENT
        && !!String(slot.replaces || "").trim();
      this.update(slot.label, drop ? { role: role.value, replaces: "" } : { role: role.value },
        drop ? `@${slot.label} takes nobody's place now, so who it stood in for was cleared.` : "");
    });
    // The description asks in the words of the chosen role, and fields a role cannot use do not
    // appear: a sound effect has no lyrics, so it gets no words box.
    const NOTE_ASK = {
      voice_timbre: "how the voice sounds: hoarse, unhurried, mid-forties",
      sfx: "what it is: a heavy door slamming, close, no reverb",
      bgm: "timbre, tempo, instruments: slow synth music, no drums",
      music_style: "timbre, tempo, instruments: slow synth music, no drums",
      beat_reference: "the rhythm: a steady 90 bpm pulse, one hit per bar",
    };
    const note = el("input", { class: "oh3-in oh3-wide", value: slot.note || "", placeholder:
      slot.kind === "sound"
        ? (NOTE_ASK[slot.role] || "what it sounds like") +
          " — the only description the model will ever have"
        : "what it is, in a few words" });
    note.addEventListener("change", () => this.update(slot.label, { note: note.value }));

    const first = el("div", { class: "oh3-editrow" },
      this.widgetRow("name", el("span", { class: "oh3-atwrap" },
        el("span", { class: "oh3-at", textContent: "@" }), label)),
      this.widgetRow("what it is", role));
    if (slot.kind === "video") {
      const st = el("select", { class: "oh3-in oh3-st", title:
        "its own soundtrack: off sends none, paired sends it as this clip's sound, alone sends it as a track in its own right" });
      for (const v of SOUNDTRACKS) st.append(el("option", { value: v,
        textContent: v, selected: v === (slot.soundtrack || "off") }));
      st.addEventListener("change", () => this.update(slot.label, { soundtrack: st.value }));
      first.append(this.widgetRow("soundtrack", st));
    }
    const rows = [this.header(), first,
                  el("div", { class: "oh3-editrow" }, this.widgetRow("about it", note))];
    // Who this picture takes over from. Beside what it is rather than instead of it: what it is
    // says a figure is being replaced, and this says which one, and the brief needs both. Free
    // text, because nothing in this chain can list the people in a clip -- the service reads three
    // sampled frames of it, so somebody can be in none of them and walk in later.
    if (slot.kind === "picture" && slot.role === REPLACEMENT) {
      const who = el("input", { class: "oh3-in oh3-wide", value: slot.replaces || "", placeholder:
        "who it takes over from, in your own words: the man in the plaid shirt" });
      who.addEventListener("change", () => this.update(slot.label, { replaces: who.value }));
      rows.push(el("div", { class: "oh3-editrow" }, this.widgetRow("in place of", who)));
    }
    // Only the roles for which a recording's own words mean anything: a voice to imitate, or a
    // track played outright whose lyrics must ride along. Style, beat and effects have no words.
    if (slot.kind === "sound" && (slot.role === "voice_timbre" || slot.role === "bgm")) {
      const words = el("input", { class: "oh3-in oh3-wide", value: slot.transcript || "",
        placeholder: "the words in this recording, exactly as spoken — nothing here can hear" });
      words.addEventListener("change", () => this.update(slot.label, { transcript: words.value }));
      rows.push(el("div", { class: "oh3-editrow" }, this.widgetRow("its words", words)));
    }
    this.editor.replaceChildren(...rows);
  }

  render() {
    const slots = this.slots();
    const of = (kind) => slots.filter((s) => s.kind === kind);
    if (this.selected && !slots.some((s) => s.label === this.selected)) this.selected = null;

    this.counts.textContent =
      `${fileCount(slots)} / ${MAX_FILES}`;
    this.picGrid.replaceChildren(
      ...Array.from({ length: 9 }, (_, i) => this.cell("picture", i, of("picture")[i])));
    this.vidRows.replaceChildren(
      ...Array.from({ length: 3 }, (_, i) => this.cell("video", i, of("video")[i])));
    this.sndRows.replaceChildren(
      ...Array.from({ length: 3 }, (_, i) => this.cell("sound", i, of("sound")[i])));
    this.renderEditor();
  }
}

/* The board: every dimension pinned, nothing negotiated with the host. */
const CSS = `
.oh3-panel{font-family:system-ui,sans-serif;color:#f3efe6;font-size:11px;
  background:#0a0a0d;border:1px solid rgba(243,239,230,.12);border-radius:8px;padding:7px;
  display:flex;flex-direction:column;gap:6px;box-sizing:border-box;
  width:100%;max-width:546px;height:${PANEL_H}px;min-height:${PANEL_H}px;overflow:hidden;}
.oh3-panel *{box-sizing:border-box;min-width:0;}
.oh3-panel.oh3-hot{border-color:#eb8219;}
.oh3-top{flex:0 0 auto;display:flex;align-items:center;gap:8px;overflow:hidden;}
.oh3-counts{font-family:ui-monospace,monospace;font-size:10px;color:rgba(243,239,230,.38);flex:0 0 auto;}
.oh3-msg{flex:1;min-width:0;font-size:10px;color:rgba(243,239,230,.56);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;}
.oh3-msg.oh3-bad{color:#f07070;}
.oh3-ver{flex:0 0 auto;font-size:8px;color:rgba(243,239,230,.22);font-family:ui-monospace,monospace;}
.oh3-cols{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.oh3-col{display:flex;flex-direction:column;gap:4px;min-width:0;min-height:0;}
.oh3-sec{flex:0 0 auto;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:rgba(243,239,230,.38);}
.oh3-pics{flex:1;min-height:0;display:grid;gap:5px;
  grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(3,minmax(0,1fr));}
.oh3-vids{flex:1;min-height:0;display:grid;grid-template-rows:repeat(3,minmax(0,1fr));gap:5px;
  grid-template-columns:minmax(0,1fr);}
.oh3-auds{flex:1;min-height:0;display:grid;grid-template-rows:repeat(3,minmax(0,1fr));gap:5px;
  grid-template-columns:minmax(0,1fr);}
.oh3-slot{border:1px dashed rgba(243,239,230,.12);border-radius:6px;background:#101016;
  display:flex;align-items:center;justify-content:center;color:rgba(243,239,230,.22);font-size:10px;
  cursor:pointer;overflow:hidden;min-width:0;min-height:0;}
.oh3-slot:hover{border-color:rgba(243,239,230,.38);color:rgba(243,239,230,.56);}
.oh3-filled{border-style:solid;border-color:rgba(243,239,230,.22);background:#101016;cursor:pointer;
  display:block;position:relative;}
.oh3-filled.oh3-pic{border-color:rgba(243,239,230,.22);}
.oh3-filled.oh3-vid{border-color:rgba(243,239,230,.22);}
.oh3-filled.oh3-aud{border-color:rgba(243,239,230,.22);}
.oh3-sel{outline:1px solid #eb8219;outline-offset:1px;}
.oh3-fit{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block;
  background:#0a0a0d;}
.oh3-bar{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;gap:4px;
  padding:1px 4px;background:rgba(10,10,13,.85);overflow:hidden;}
.oh3-tag{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-family:ui-monospace,monospace;font-size:9px;color:rgba(243,239,230,.80);text-align:left;}

.oh3-x{flex:0 0 auto;cursor:pointer;color:rgba(243,239,230,.38);font-size:11px;line-height:1;}
.oh3-x:hover{color:#ff9a2e;}
.oh3-rowline{display:flex;align-items:center;gap:6px;padding:0 6px;height:100%;overflow:hidden;}
.oh3-vthumb{width:56px;height:32px;min-width:56px;border-radius:4px;object-fit:contain;
  background:#0a0a0d;flex:0 0 auto;}
.oh3-play{width:20px;height:20px;border-radius:50%;border:1px solid rgba(243,239,230,.22);background:#101016;
  color:rgba(243,239,230,.80);font-size:10px;line-height:1;cursor:pointer;flex:0 0 auto;padding:0;}
.oh3-seg{flex:0 0 auto;width:96px;background:#101016;border:1px solid rgba(243,239,230,.22);color:rgba(243,239,230,.80);
  border-radius:4px;font-size:10px;padding:2px;}
.oh3-edit{flex:0 0 auto;height:144px;border-top:1px solid rgba(243,239,230,.12);padding-top:6px;
  display:flex;flex-direction:column;gap:5px;overflow:hidden;}
.oh3-edithead{display:flex;flex-direction:column;gap:1px;overflow:hidden;}
.oh3-edittitle{font-size:11px;color:#f3efe6;}
.oh3-editsub{font-size:9px;color:rgba(243,239,230,.38);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;}
.oh3-wrow{flex:1;min-width:0;display:flex;align-items:center;gap:6px;
  background:var(--oh3-wbg);border:1px solid var(--oh3-wline);border-radius:12px;
  padding:2px 9px;overflow:hidden;}
.oh3-wlabel{flex:0 0 auto;font-size:10px;color:var(--oh3-wmuted);white-space:nowrap;}
.oh3-wrow .oh3-in{flex:1;min-width:0;background:none;border:0;padding:2px 0;
  color:var(--oh3-wtext);}
.oh3-wrow select.oh3-in{background:transparent;color:var(--oh3-wtext);}
.oh3-wrow select.oh3-in option,.oh3-role option,.oh3-seg option{
  background:#101016;color:#f3efe6;}
.oh3-atwrap{flex:1;min-width:0;display:flex;align-items:center;gap:2px;}
.oh3-atwrap .oh3-in{flex:1;min-width:0;}
.oh3-editrow{display:flex;align-items:center;gap:5px;overflow:hidden;}
.oh3-at{flex:0 0 auto;color:#eb8219;font-family:ui-monospace,monospace;}
.oh3-in{background:#101016;border:1px solid rgba(243,239,230,.22);color:#f3efe6;border-radius:4px;
  padding:3px 6px;font-size:11px;}
.oh3-name{flex:0 0 110px;}
/* A name the panel would not take. Left in the field so it can be fixed rather than reverted, and
   red so the message in the top line has something to point at. Written against the row as well as
   the field, because the two-class rule above sets the theme's text colour and is the more specific
   of the two: a rule on this class alone is painted over and the field stays the colour of a name
   that was accepted. */
.oh3-wrow .oh3-in.oh3-wrongname,.oh3-wrongname{color:#f07070;}
select.oh3-in{flex:1;}
.oh3-st{flex:0 0 132px;}
.oh3-wide{flex:1;width:100%;}
.oh3-hint{color:rgba(243,239,230,.38);font-size:10px;padding-top:14px;text-align:center;}
/* A drag in the air. The board says yes in the accent it says everything else in, and says no in
   the colour it refuses in, so a file it cannot take never looks like it is about to land. The two
   yeses are told apart on purpose: a solid edge is an arrival, a dashed one is a file about to take
   the place of the file already there. */
.oh3-panel.oh3-cold{border-color:#f07070;}
.oh3-slot.oh3-take{border-style:solid;border-color:#eb8219;background:rgba(235,130,25,.12);
  color:rgba(243,239,230,.80);}
.oh3-slot.oh3-swap{outline:2px dashed #eb8219;outline-offset:-2px;background:rgba(235,130,25,.12);}
.oh3-badges{position:absolute;top:3px;right:3px;display:flex;gap:3px;z-index:1;}
.oh3-inlinebadges{position:static;flex:0 0 auto;}
.oh3-badge{background:rgba(10,10,13,.85);border:1px solid rgba(243,239,230,.12);border-radius:3px;
  color:rgba(243,239,230,.56);font-size:8px;padding:0 3px;line-height:1.5;font-family:ui-monospace,monospace;}
.oh3-rolebadge{color:#eb8219;border-color:#b85a0e;}
`;

app.registerExtension({
  name: "openh3ir.tray",
  init() {
    // The editor's rows dress as native ComfyUI widgets, and the surest way to match the theme is
    // to ask it: LiteGraph carries the widget colors the canvas actually draws with.
    const LG = window.LiteGraph || {};
    const css = CSS
      .replaceAll("var(--oh3-wbg)", LG.WIDGET_BGCOLOR || "#222")
      .replaceAll("var(--oh3-wline)", LG.WIDGET_OUTLINE_COLOR || "#666")
      .replaceAll("var(--oh3-wtext)", LG.WIDGET_TEXT_COLOR || "#ddd")
      .replaceAll("var(--oh3-wmuted)", LG.WIDGET_SECONDARY_TEXT_COLOR || "#999");
    document.head.append(el("style", { textContent: css }));
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const state = (this.widgets || []).find((w) => w.name === "tray");
      if (!state) return r;
      state.computeSize = () => [0, -4];
      state.hidden = true;
      if (state.options) state.options.hidden = true;
      const tray = new Tray(this, state);
      this._oh3Tray = tray;
      const panel = this.addDOMWidget("oh3_panel", "div", tray.root, { serialize: false });
      /* The board has no width of its own: it is the node's, whatever the node is.
       *
       * The frontend writes a `width` onto every widget from a node layout pass, and for a
       * full-bleed board that number is the content width rather than the box. While the board is
       * a live element nothing reads it, so nothing looks wrong. Zoom out far enough and the
       * element is hidden and the canvas draws the board itself, from that number -- and the board
       * is painted past the right edge of the node, over empty canvas, where it also takes the
       * mouse clicks that land on it.
       *
       * MEASURED from the owner's own screenshot: the node body was drawn 497 pixels wide and the
       * board 660, one third wider than the node it belongs to. Reproduced here by writing 900 onto
       * the widget by hand. The other three panels in this pack already refuse the write; this one
       * was the only board still taking it. */
      Object.defineProperty(panel, "width", { get: () => null, set: () => {}, configurable: true });
      // Honoured by the canvas renderer; harmless where Vue owns layout, and the board's own
      // pinned CSS is what actually keeps it intact there.
      panel.computedHeight = PANEL_H;
      panel.computeSize = (w) => [w || NODE_W, PANEL_H];
      this.size[0] = NODE_W;
      this.size[1] = PANEL_H + NODE_H_EXTRA;
      requestAnimationFrame(() => tray.render());
      return r;
    };
    nodeType.prototype.computeSize = function () {
      // The node hugs the board exactly: a pinned board inside a fluid node is what left gray
      // slack around the panel. Nothing about this node benefits from being resized.
      return [NODE_W, PANEL_H + NODE_H_EXTRA];
    };

    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      try {
        size[0] = NODE_W;
        size[1] = PANEL_H + NODE_H_EXTRA;
      } catch (e) { /* leave the size alone */ }
      return onResize?.apply(this, arguments);
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      this._oh3Tray?.render();
      return r;
    };
  },
});
