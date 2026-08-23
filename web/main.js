/* OpenH3-IR Main: the panel.
 *
 * The node people touch every time was the only one of the four with no surface of its own: one
 * good prompt box sitting on twelve stock widget rows, ungrouped, and with the biggest field on the
 * node unlabelled the moment somebody typed into it. `nodes.py` says so out loud -- "on a multiline
 * widget the placeholder is the only label there is" -- and a placeholder is gone at the first
 * keystroke. The heading `your prompt` is the fix, and it is why this panel earns its place before
 * a single knob is regrouped.
 *
 * Three named groups with one quiet line each, a report line inside the group it talks about, a
 * bottom row for what is rarely touched, and everything that opens floats so the height never
 * jumps.
 *
 * **Rendering only.** The node's real state stays exactly where it is: the same widgets, the same
 * names, the same order, so every saved workflow and every API graph is untouched. They are hidden
 * and driven from here, which is what the Setup node already does with its five file pickers.
 * Delete `web/` and the node still works, still API-drives, and still restores from a save.
 *
 * **The panel owns the prompt textarea rather than borrowing ComfyUI's multiline widget**, because
 * a host widget cannot sit inside a panel and still look like one surface. `prompt.js` survives
 * that unchanged: its picker and its mirror measure their metrics off whatever textarea they are
 * handed, and the mirror only needs to share an offset parent with it, which a sibling always
 * does. The trade has one measured cost, named in AGENTS.md: an installed autocomplete extension
 * that wraps `ComfyWidgets.STRING` binds to the hidden widget rather than to this box.
 *
 * **Nothing here derives a fact about the prompt.** `prompt.js` parses the text and walks the media
 * link, and `promptFacts` hands back what it found. This file only writes the sentences. Two copies
 * of that parse would be two things to keep right.
 */
import { app } from "../../scripts/app.js";
import { attachPrompt, promptFacts } from "./prompt.js";

const VERSION = "main v1";
console.log("[OpenH3-IR]", VERSION);
const NODE = "OpenH3IRCompile";

/* Measured on the live canvas, not chosen. 520 by 773 is the proposed node, the same width as
 * Setup; 595 is the panel inside it, and the 178 between them is the seven output sockets plus the
 * host's own padding, which is not ours to change.
 *
 * **Height drags on this node, and that is the one departure from the other three.** Setup pins its
 * height and the media tray pins its board, and both are right because nothing on either wants more
 * room. Here one element does: the prompt is the work, and a two clause sentence half behind a
 * scrollbar reads as a smaller tool than this is. So width drags, height drags, and the prompt box
 * absorbs every spare pixel. Nothing else on the panel moves. */
const NODE_W = 520;
const MIN_W = 430;
const NODE_H = 773;
const MIN_H = 719;   // MEASURED: the height where the prompt box lands on its own 124 floor
const NODE_H_EXTRA = 178;
const BOX_MIN = 124;

/* Every widget this panel drives, in the schema's own order. Hiding one the node does not have
 * would take that control away and put nothing in its place, so the list is checked at mount and
 * the plain node is drawn instead if anything is missing. */
const WIDGETS = ["intent", "seconds", "aspect", "creativity", "silent", "shots", "megapixels",
                 "spoken_language", "sizing", "seed", "effort"];

/* The rows that open a list, and what the list teaches that the row alone cannot say. Values are
 * the schema's own words, verbatim, so a graph and a panel can never disagree about what was
 * picked. */
const SECONDS_OFFERED = [5, 8, 10, 12, 15];
const RESOLUTIONS = [[0, "768 on the short edge"], [1.5, ""], [2.0, ""], [2.5, ""]];
const INVENTION = [
  ["restrained", "no music, no line, no text"],
  ["balanced", "can add music"],
  ["bold", "can also add words and text"],
  ["extreme", "pushes every choice harder"],
];
/* The boolean underneath is `silent`, where true means no music. A boolean called "no music" set to
 * "false" is a double negative on a canvas, so the row is `music` and its two values are spoken. */
const MUSIC = [["the writer decides", true], ["none", false]];
const SIZING = [
  ["match", "fits each picture to the render's pixel area"],
  ["max", "keeps the picture's own size. Stronger identity, and slower."],
];
const EFFORT = [["fast", ""], ["standard", ""],
                ["max", "asks the writer for reasoning prose, and is slower"]];
/* ComfyUI's own control, in ComfyUI's own words, so anybody who has seen it elsewhere recognises
 * it. It is the second half of the seed rather than a control of its own, so it is folded into the
 * seed's floater instead of taking a fourth place in the bottom row. */
const AFTER_RUN = ["fixed", "increment", "decrement", "randomize"];

/* Every frame shape the schema offers, with the proportion drawn beside it at 18 pixels tall. */
const SHAPES = ["16:9", "21:9", "4:3", "1:1", "3:4", "9:16"];
const SWATCH_H = 18;

/* What one shot needs, which the node's own tooltip states as fact. Used ONLY to dim a count and
 * say what it needs: the row stays clickable, because the panel warns and never refuses a value the
 * compiler would accept. If this number ever moves, the compiler still refuses with its own
 * arithmetic and this is out of date rather than lying. */
const SECONDS_PER_SHOT = 1.2;
const MAX_SHOTS = 10;

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

/** A count of one thing, said the way a person says it. */
function count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

/** A list read as a sentence: "a", "a and b", "a, b and c". */
function andList(items) {
  if (items.length <= 1) return items[0] || "";
  return items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}

/** What the resolution row shows. Zero is H3's own geometry and has no number to state; anything
 *  else carries its unit, because a bare 1.5 on a canvas is not a size. */
function sizeWords(mp) {
  const n = Number(mp) || 0;
  return n > 0 ? `${n.toFixed(1)} megapixels` : "H3's native";
}

class Panel {
  constructor(node, widgets) {
    this.node = node;
    this.w = widgets;
    this.rows = {};
    this.open = null;      // which floater is open, or null

    this.root = el("div", { class: "oh3m-panel" });
    this.root.append(
      el("div", { class: "oh3m-title" },
        el("b", { textContent: "Main" }),
        el("span", { textContent: "one prompt to a ready H3 job" })));

    // ------------------------------------------------------------- your prompt
    this.root.append(
      el("div", { class: "oh3m-sec", textContent: "your prompt" }),
      el("div", { class: "oh3m-seclead", textContent:
        "Say what happens. Type @ to name anything in the tray, or to lock a spoken line." }));

    /* The panel's own textarea, a direct child of the panel: `prompt.js` inserts its mirror as a
     * sibling before it and positions it from `offsetLeft`, which only lines up while the two share
     * an offset parent. The panel is the positioned ancestor of both. */
    this.box = el("textarea", { class: "oh3m-box", spellcheck: true,
      placeholder: "one plain sentence, what happens, with @ for anything in the tray\n"
                 + "@carguy walks onto the wet gantry in the rain and stops when he sees the city "
                 + "below" });
    this.box.addEventListener("input", () => {
      this.w.intent.value = this.box.value;
      this.node.setDirtyCanvas?.(true, true);
      this.renderReport();
    });
    this.root.append(this.box);

    this.msg = el("div", { class: "oh3m-msg" });
    this.root.append(this.msg);

    /* `spoken in` belongs to the box above it rather than to the writer's own decisions. The schema
     * says it "decides nothing while no line is locked", and this panel already knows, because
     * `prompt.js` parses `@speaks(` as it is typed. The chip is Setup's own, not a new signal. */
    this.chip = el("span", { class: "oh3m-chip" });
    this.root.append(this.row("spoken in", "spoken_language", { chip: this.chip }));

    // ------------------------------------------------------------- the video
    this.root.append(
      el("div", { class: "oh3m-sec", textContent: "the video" }),
      el("div", { class: "oh3m-seclead", textContent:
        "How long it runs, what shape and size it is, and how many shots." }),
      this.row("seconds", "seconds", { mono: true }),
      this.row("frame shape", "aspect"),
      this.row("resolution", "megapixels"),
      this.row("shots", "shots"));

    // ------------------------------------------------------------- the writing
    this.root.append(
      el("div", { class: "oh3m-sec", textContent: "the writing" }),
      el("div", { class: "oh3m-seclead", textContent:
        "What the writer decides where your prompt leaves things open." }),
      this.row("invention", "creativity"),
      this.row("music", "silent"));

    // ------------------------------------------------------------- the bottom row
    this.foot = {
      seed: this.footItem("brief seed", "seed"),
      sizing: this.footItem("reference size", "sizing"),
      effort: this.footItem("writing effort", "effort"),
    };
    this.footRow = el("div", { class: "oh3m-foot" },
      this.foot.seed.root, this.foot.sizing.root, this.foot.effort.root);
    this.root.append(this.footRow);

    /* One element for every floater, because only one can be open, and it is absolutely positioned
     * so nothing it holds can push the panel taller. */
    this.list = el("div", { class: "oh3m-list" });
    this.root.append(this.list);

    this.root.addEventListener("pointerdown", (e) => {
      const inList = Boolean(e.target.closest?.(".oh3m-list"));
      const onOpener = Boolean(e.target.closest?.(".oh3m-row, .oh3m-fi"));
      if (this.open && !inList && !onOpener) { this.open = null; this.renderList(); }
    });

    this.render();
  }

  /** One widget row: a label that survives typing, the value, an optional chip, and a caret. */
  row(label, widget, { chip = null, mono = false } = {}) {
    const value = el("span", { class: "oh3m-val" + (mono ? " oh3m-mono" : "") });
    const kids = [el("span", { class: "oh3m-label", textContent: label }), value];
    if (chip) kids.push(chip);
    kids.push(el("span", { class: "oh3m-caret", textContent: "▾" }));
    const root = el("div", { class: "oh3m-row",
      onclick: (e) => { e.stopPropagation(); this.toggle(widget); } }, ...kids);
    this.rows[widget] = { root, value };
    return root;
  }

  footItem(label, widget) {
    const value = el("span");
    const root = el("span", { class: "oh3m-fi",
      onclick: (e) => { e.stopPropagation(); this.toggle(widget); } },
      el("span", { textContent: label }), value);
    return { root, value };
  }

  toggle(which) {
    this.open = this.open === which ? null : which;
    this.renderList();
  }

  set(widget, value) {
    this.w[widget].value = value;
    this.w[widget].callback?.(value);
    this.open = null;
    this.node.setDirtyCanvas?.(true, true);
    this.render();
  }

  // ------------------------------------------------------------------ the report line

  /** The one line the prompt half reports on.
   *
   *  Every fact comes from `prompt.js`. The order below is the order a person needs them in: an
   *  unclosed line is a mistake in what they are typing and outranks everything, then a name that
   *  will not resolve, then what did resolve, then the tray's own state.
   */
  renderReport() {
    const f = promptFacts(this.node, this.box.value);
    const say = (text, bad = false) => {
      this.msg.textContent = text;
      this.msg.title = text;
      this.msg.className = "oh3m-msg" + (bad ? " oh3m-bad" : "");
    };
    this.renderChip(f);
    if (!f.written) return say("nothing written yet");
    if (f.unclosed) {
      return say("One spoken line was never closed. Close it with a quote mark and a bracket.",
                 true);
    }
    if (f.unknown.length && !f.connected) {
      return say(`No Media node is connected, so @${f.unknown[0]} names nothing. Wire an OpenH3-IR `
                 + "Media node into media.", true);
    }
    if (f.unknown.length === 1) {
      return say(`@${f.unknown[0]} is not in the tray. Rename a slot on the Media node, or change `
                 + "the name here.", true);
    }
    if (f.unknown.length > 1) {
      return say(`${andList(f.unknown.map((n) => "@" + n))} are not in the tray. Rename those slots `
                 + "on the Media node, or change the names here.", true);
    }
    const parts = [];
    if (f.named.picture) parts.push(count(f.named.picture, "picture", "pictures"));
    if (f.named.video) parts.push(count(f.named.video, "clip", "clips"));
    if (f.named.sound) parts.push(count(f.named.sound, "sound", "sounds"));
    const said = [];
    if (parts.length) said.push(`${andList(parts)} named.`);
    if (f.locked) said.push(`${count(f.locked, "line is", "lines are")} locked.`);
    if (said.length) return say(said.join(" "));
    if (!f.connected) {
      return say("No Media node is connected, so the video is written from your words alone.");
    }
    // A connected Media node with nothing in its tray yet. The design's table has no row for this
    // one, and both of its neighbours would be false here: no Media node is connected is wrong,
    // and a count of zero files is not a sentence.
    if (!f.trayCount) return say("The tray is empty. Add files on the Media node.");
    return say(`The tray holds ${count(f.trayCount, "file", "files")}. Type @ to name one in the `
               + "prompt.");
  }

  /** The chip beside `spoken in`. It reads `no line locked` until one exists, which is the field's
   *  own proof that it decides nothing until you have decided something. */
  renderChip(f) {
    const facts = f || promptFacts(this.node, this.box.value);
    const on = facts.locked > 0;
    this.chip.textContent = on ? `${count(facts.locked, "line", "lines")} locked` : "no line locked";
    this.chip.className = "oh3m-chip" + (on ? " oh3m-on" : "");
  }

  // ------------------------------------------------------------------ rendering

  render() {
    if (this.box.value !== String(this.w.intent.value ?? "")) {
      this.box.value = String(this.w.intent.value ?? "");
      this.node._oh3Chips?.paint();
    }
    this.rows.seconds.value.textContent = Number(this.w.seconds.value).toFixed(1);
    this.rows.aspect.value.textContent = String(this.w.aspect.value);
    this.rows.megapixels.value.textContent = sizeWords(this.w.megapixels.value);
    this.rows.shots.value.textContent = String(this.w.shots.value);
    this.rows.creativity.value.textContent = String(this.w.creativity.value);
    this.rows.silent.value.textContent = this.w.silent.value ? "none" : "the writer decides";
    this.rows.spoken_language.value.textContent = String(this.w.spoken_language.value);
    this.foot.seed.value.textContent = String(this.w.seed.value);
    this.foot.sizing.value.textContent = String(this.w.sizing.value);
    this.foot.effort.value.textContent = String(this.w.effort.value);
    this.renderReport();
    this.renderList();
  }

  renderList() {
    this.list.replaceChildren();
    this.list.classList.toggle("oh3m-open", Boolean(this.open));
    if (!this.open) return;
    ({
      seconds: () => this.secondsList(),
      aspect: () => this.shapeList(),
      megapixels: () => this.resolutionList(),
      shots: () => this.shotList(),
      creativity: () => this.wordList("creativity", INVENTION),
      silent: () => this.musicList(),
      spoken_language: () => this.languageList(),
      seed: () => this.seedList(),
      sizing: () => this.wordList("sizing", SIZING),
      effort: () => this.wordList("effort", EFFORT),
    })[this.open]?.();
    this.place(this.rows[this.open]?.root || this.footRow);
  }

  /** Put the open list where it can be read.
   *
   *  MEASURED on the live canvas: `shots` is twelve rows and it opens from a row two thirds of the
   *  way down, so a list that always dropped downward ran off the bottom of the panel and the last
   *  four counts were behind the node's edge. It is placed after its rows are built, because how
   *  tall it is decides which side of the row it opens on.
   */
  place(near) {
    const room = this.root.clientHeight;
    const tall = this.list.offsetHeight;
    const below = near.offsetTop + near.offsetHeight + 3;
    const above = room - near.offsetTop + 3;
    if (below + tall <= room - 8) {
      this.list.style.top = `${below}px`;
      this.list.style.bottom = "";
      return;
    }
    this.list.style.top = "";
    // Upward off the top of the row, or pinned to the panel's own floor when neither side has the
    // room. `max-height` keeps it inside either way, so the worst case is a list that scrolls.
    this.list.style.bottom = room - above - tall >= 8 ? `${above}px` : "8px";
  }

  note(text) {
    if (text) this.list.append(el("div", { class: "oh3m-note", textContent: text }));
  }

  lrow(name, { note = "", on = false, dim = false, warn = false, onclick, swatch = null } = {}) {
    const kids = [el("span", { class: "oh3m-lname", textContent: name })];
    if (swatch) kids.push(swatch);
    if (note) {
      kids.push(el("span", { class: "oh3m-lnote" + (warn ? " oh3m-warn" : ""), textContent: note }));
    }
    return el("div", { class: "oh3m-lrow" + (on ? " oh3m-on" : "") + (dim ? " oh3m-dim" : ""),
                       onclick }, ...kids);
  }

  /** The field itself, inside the floater, so any value the schema allows can still be reached: a
   *  list of round numbers over a field that would otherwise refuse what the graph is holding. */
  typeIn(widget, parse) {
    const input = el("input", { class: "oh3m-in", value: String(this.w[widget].value),
                                spellcheck: false });
    input.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const v = parse(input.value);
      if (Number.isFinite(v)) this.set(widget, v);
    });
    input.addEventListener("click", (e) => e.stopPropagation());
    return el("div", { class: "oh3m-row oh3m-typein" },
      el("span", { class: "oh3m-label", textContent: "or type" }), input);
  }

  secondsList() {
    this.note("Type any number instead. H3 was trained between 5 and 15 seconds.");
    const held = Number(this.w.seconds.value);
    for (const n of SECONDS_OFFERED) {
      this.list.append(this.lrow(String(n), { on: Math.abs(held - n) < 1e-9,
        onclick: () => this.set("seconds", n) }));
    }
    this.list.append(this.typeIn("seconds", (v) => Number(v)));
  }

  shapeList() {
    const held = String(this.w.aspect.value);
    for (const shape of SHAPES) {
      const [a, b] = shape.split(":").map(Number);
      const swatch = el("span", { class: "oh3m-ratio",
        style: { width: `${Math.floor(SWATCH_H * a / b)}px`, height: `${SWATCH_H}px` } });
      this.list.append(this.lrow(shape, { on: shape === held, swatch,
        onclick: () => this.set("aspect", shape) }));
    }
  }

  resolutionList() {
    this.note("Bigger is sharper, slower, and eats VRAM in proportion. Type any number instead.");
    const held = Number(this.w.megapixels.value) || 0;
    for (const [mp, said] of RESOLUTIONS) {
      this.list.append(this.lrow(sizeWords(mp), { note: said,
        on: Math.abs(held - mp) < 1e-9, onclick: () => this.set("megapixels", mp) }));
    }
    this.list.append(this.typeIn("megapixels", (v) => Number(v)));
  }

  /** Every count, with the ones that cannot fit dimmed and told what they need.
   *
   *  Drawn as an offer and never as a claim: a dimmed count is still clickable, because the panel
   *  warns and the compiler is the one that refuses. If the arithmetic ever moves, this is out of
   *  date rather than lying.
   */
  shotList() {
    this.note("auto leaves the edit to the writer. A number is kept exactly.");
    const held = String(this.w.shots.value);
    const seconds = Number(this.w.seconds.value) || 0;
    this.list.append(this.lrow("auto", { on: held === "auto",
      onclick: () => this.set("shots", "auto") }));
    for (let n = 1; n <= MAX_SHOTS; n++) {
      const needs = n * SECONDS_PER_SHOT;
      const fits = seconds + 1e-9 >= needs;
      this.list.append(this.lrow(String(n), {
        on: held === String(n), dim: !fits, warn: true,
        note: fits ? "" : `needs ${needs.toFixed(1)} s`,
        onclick: () => this.set("shots", String(n)) }));
    }
  }

  wordList(widget, rows) {
    const held = String(this.w[widget].value);
    for (const [word, said] of rows) {
      this.list.append(this.lrow(word, { note: said, on: word === held,
        onclick: () => this.set(widget, word) }));
    }
  }

  musicList() {
    this.note("Ambient and physical sound are always written. This decides the background music.");
    const writes = !this.w.silent.value;
    for (const [word, writing] of MUSIC) {
      this.list.append(this.lrow(word, { on: writing === writes,
        onclick: () => this.set("silent", !writing) }));
    }
  }

  languageList() {
    this.note("The language every locked line is spoken in. For a language not listed, name it in "
              + "the prompt.");
    const held = String(this.w.spoken_language.value);
    const offered = this.w.spoken_language.options?.values || [held];
    for (const lang of offered) {
      this.list.append(this.lrow(lang, { on: lang === held,
        onclick: () => this.set("spoken_language", lang) }));
    }
  }

  /** The seed, and ComfyUI's own control folded in beside it, because the two are one control.
   *
   *  `control after generate` is a widget the host bolts onto a seed. It is edited here rather than
   *  given its own item in the bottom row, and its four values keep ComfyUI's own words so anybody
   *  who has seen it elsewhere still recognises them.
   */
  seedList() {
    this.note("The same prompt and the same seed give the same brief. Change it for a different "
              + "take.");
    this.list.append(this.typeIn("seed", (v) => parseInt(v, 10)));
    const after = this.afterRun();
    if (!after) return;
    this.note("ComfyUI's own control. It decides whether the seed moves on the next run.");
    for (const word of AFTER_RUN) {
      this.list.append(this.lrow(word, { on: String(after.value) === word,
        onclick: () => {
          after.value = word;
          this.open = null;
          this.node.setDirtyCanvas?.(true, true);
          this.render();
        } }));
    }
  }

  /** ComfyUI adds this beside a seed and has spelled it both ways across versions. */
  afterRun() {
    return (this.node.widgets || []).find(
      (w) => w.name === "control_after_generate" || w.name === "control after generate");
  }
}

const CSS = `
.oh3m-panel{font-family:system-ui,sans-serif;color:#f3efe6;font-size:11px;
  background:#0a0a0d;border:1px solid rgba(243,239,230,.12);border-radius:8px;padding:8px;
  display:flex;flex-direction:column;gap:6px;position:relative;overflow:hidden;
  width:100%;height:100%;min-height:0;box-sizing:border-box;}
.oh3m-panel *{box-sizing:border-box;min-width:0;}
.oh3m-title{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;}
.oh3m-title b{font-size:11px;font-weight:400;color:#f3efe6;}
.oh3m-title span{font-size:9.5px;color:rgba(243,239,230,.56);}
/* Every quiet line is pinned to the rows it needs at 430 wide, so none of them reflows as the node
   is dragged and only the prompt box changes height. Stated in em, so the row count is the decision
   and the pixels follow the element's own type.

   MEASURED at 520, 470 and 430: all three are one row at every width this node allows, so one row
   is what they get. Pinned to two, they held back 41 pixels of prompt that nothing ever used. */
.oh3m-sec{flex:0 0 auto;font-size:9px;letter-spacing:.08em;text-transform:uppercase;
  color:rgba(243,239,230,.56);margin-top:2px;}
.oh3m-seclead{flex:0 0 auto;font-size:9.5px;line-height:1.45;color:rgba(243,239,230,.56);
  margin-top:-3px;min-height:1.45em;}

/* THE one element that grows. Every pixel the node gains above its minimum goes here. */
.oh3m-box{flex:1 1 auto;min-height:${BOX_MIN}px;width:100%;resize:none;border-radius:6px;
  background:#111117;border:1px solid rgba(243,239,230,.16);padding:7px 9px;
  font-family:ui-monospace,Menlo,monospace;font-size:11.5px;line-height:1.55;
  color:#f3efe6;outline:none;position:relative;z-index:1;}
.oh3m-box:focus{border-color:rgba(243,239,230,.38);}
.oh3m-box::placeholder{color:rgba(243,239,230,.44);}

.oh3m-row{flex:0 0 auto;display:flex;align-items:center;gap:6px;min-height:22px;
  background:var(--oh3-wbg);border:1px solid var(--oh3-wline);border-radius:12px;
  padding:2px 9px;overflow:hidden;cursor:pointer;}
.oh3m-label{flex:0 0 auto;font-size:10px;color:var(--oh3-wmuted);white-space:nowrap;}
.oh3m-val{flex:1;min-width:0;font-size:11px;color:var(--oh3-wtext);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
.oh3m-val.oh3m-mono{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;}
.oh3m-caret{flex:0 0 auto;color:rgba(243,239,230,.56);font-size:10px;line-height:1;min-width:16px;
  text-align:center;}
.oh3m-row:hover .oh3m-caret{color:#eb8219;}
.oh3m-chip{flex:0 0 auto;font-size:8.5px;line-height:1.7;padding:0 5px;border-radius:3px;
  font-family:ui-monospace,Menlo,monospace;border:1px solid rgba(243,239,230,.16);
  background:rgba(10,10,13,.6);color:rgba(243,239,230,.60);white-space:nowrap;
  transition:color 120ms ease,border-color 120ms ease,background-color 120ms ease;}
.oh3m-chip.oh3m-on{color:#5fc98a;border-color:rgba(95,201,138,.45);
  background:rgba(95,201,138,.12);}

/* The report is pinned to two rows so the prompt above it never jumps. It wraps rather than
   truncating: an instruction does not live in a tooltip. */
.oh3m-msg{flex:0 0 auto;font-size:10px;line-height:1.4;color:rgba(243,239,230,.56);
  min-height:2.8em;overflow:hidden;}
.oh3m-msg.oh3m-bad{color:#f07070;}

/* Three things nobody touches while working, all visible at once and one click from changing.
   Nothing is hidden behind a disclosure. */
.oh3m-foot{flex:0 0 auto;display:flex;align-items:center;gap:14px;padding-top:6px;margin-top:auto;
  border-top:1px solid rgba(243,239,230,.12);font-size:9.5px;line-height:1.5;
  color:rgba(243,239,230,.56);flex-wrap:wrap;min-height:2.5em;}
.oh3m-fi{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none;}
.oh3m-fi>span+span{color:rgba(243,239,230,.80);}
.oh3m-fi:hover>span+span{color:#eb8219;}

/* One element, because only one thing can be open. It scrolls rather than clipping: the drawing
   shows four rows and the language list has eleven. */
.oh3m-list{display:none;position:absolute;left:8px;right:8px;z-index:4;flex-direction:column;
  padding:4px;border-radius:6px;background:#0a0a0d;border:1px solid rgba(243,239,230,.22);
  box-shadow:0 10px 24px rgba(0,0,0,.6);overflow:auto;max-height:calc(100% - 40px);}
.oh3m-list.oh3m-open{display:flex;}
.oh3m-note{flex:0 0 auto;padding:3px 8px;font-size:10px;line-height:1.45;
  color:rgba(243,239,230,.56);}
.oh3m-lrow{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;padding:3px 8px;
  border-radius:4px;color:rgba(243,239,230,.80);font-size:11px;line-height:1.55;cursor:pointer;
  user-select:none;}
.oh3m-lrow:hover{background:rgba(243,239,230,.08);color:#f3efe6;}
.oh3m-lrow.oh3m-on{color:#eb8219;background:rgba(243,239,230,.05);}
/* A count that cannot fit is dimmed and told what it needs, and it stays clickable. The panel
   warns; it never refuses a value the compiler would accept. */
.oh3m-lrow.oh3m-dim{opacity:.55;}
.oh3m-lname{flex:1 1 auto;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;}
.oh3m-lnote{flex:0 1 auto;margin-left:auto;font-size:9px;color:rgba(243,239,230,.56);
  font-family:ui-monospace,Menlo,monospace;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.oh3m-lnote.oh3m-warn{color:#eb8219;}
.oh3m-ratio{display:inline-block;border:1px solid rgba(243,239,230,.44);margin-left:auto;
  flex:0 0 auto;background:rgba(243,239,230,.05);}
.oh3m-typein{margin:3px 4px 2px;cursor:default;}
.oh3m-typein .oh3m-in{flex:1;min-width:0;background:none;border:0;padding:2px 0;font-size:11px;
  font-family:ui-monospace,Menlo,monospace;color:var(--oh3-wtext);outline:none;}
.oh3m-panel :focus-visible{outline:1px solid #eb8219;outline-offset:1px;}
`;

/** Take a host widget off the canvas without taking its value out of the graph.
 *
 *  A combo or a number is drawn by LiteGraph, so a size of nothing is enough. A multiline string is
 *  a real `<textarea>` the frontend positions over the canvas every frame, and it has to be told to
 *  go as well or it floats on top of the panel that replaced it. Its value is still read and
 *  written through that element, so the element is hidden and never removed.
 */
function conceal(w) {
  w.computeSize = () => [0, -4];
  w.hidden = true;
  if (w.options) w.options.hidden = true;
  const e = w.element;
  if (e) {
    e.style.setProperty("display", "none", "important");
    e.hidden = true;
  }
}

app.registerExtension({
  name: "openh3ir.main",
  init() {
    // The rows dress as native ComfyUI widgets, and the surest way to match the theme is to ask it.
    const LG = window.LiteGraph || {};
    document.head.append(el("style", { textContent: CSS
      .replaceAll("var(--oh3-wbg)", LG.WIDGET_BGCOLOR || "#222")
      .replaceAll("var(--oh3-wline)", LG.WIDGET_OUTLINE_COLOR || "#666")
      .replaceAll("var(--oh3-wtext)", LG.WIDGET_TEXT_COLOR || "#ddd")
      .replaceAll("var(--oh3-wmuted)", LG.WIDGET_SECONDARY_TEXT_COLOR || "#999") }));
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const by = {};
      for (const w of this.widgets || []) by[w.name] = w;
      const absent = WIDGETS.filter((n) => !by[n]);
      if (absent.length) {
        console.warn("[OpenH3-IR] the Main panel expected inputs this node does not have:",
                     absent.join(", "), "- drawing the plain node instead");
        return r;
      }
      for (const w of this.widgets || []) conceal(w);
      const panel = new Panel(this, by);
      this._oh3Main = panel;
      const w = this.addDOMWidget("oh3m_panel", "div", panel.root, { serialize: false });
      /* The board has no width of its own: it is the node's, whatever the node has been dragged to.
       * The frontend writes a `width` onto every widget from a layout pass on each value change and
       * for a full-bleed board that number is the content width, not the box. Measured on the
       * Director: it squeezed a field to eleven pixels and never recovered. */
      Object.defineProperty(w, "width", { get: () => null, set: () => {}, configurable: true });
      w.computeSize = (width) => [width || NODE_W,
                                  Math.max(MIN_H, this.size?.[1] || NODE_H) - NODE_H_EXTRA];
      this.size = [NODE_W, NODE_H];
      requestAnimationFrame(() => {
        attachPrompt(panel.box, this);
        panel.render();
      });
      return r;
    };
    /* Width drags and so does height, which is the departure this node earns: the prompt is the
     * work, and it takes every spare pixel. Nothing else on the panel moves. */
    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      try {
        size[0] = Math.max(MIN_W, size[0]);
        size[1] = Math.max(MIN_H, size[1]);
      } catch (err) { /* an unexpected size object is not worth losing the node over */ }
      return onResize?.apply(this, arguments);
    };
    /* A saved workflow restores its values after the node is made, so the panel is told to read
     * them again rather than being left showing the defaults it was built with. */
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      for (const w of this.widgets || []) conceal(w);
      this._oh3Main?.render();
      return r;
    };
  },
});
