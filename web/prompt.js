/* OpenH3-IR Main: the @ picker on the prompt, and the mentions drawn as objects.
 *
 * Sugar only. The prompt is plain text carrying @label and @speaks("...") and works untouched with
 * this file absent; what this adds is the popup that makes the labels findable: type @ and the
 * tray's slots appear, filtered as you type, Enter or click to insert. The first entry is always
 * the spoken-line form, so @speaks is discoverable in the same motion.
 *
 * The second half of the file draws those mentions as objects rather than loose characters, and the
 * one thing it may not do is change the string. A textarea cannot contain elements, so a MIRROR div
 * sits behind it rendering the same characters with the mentions wrapped in spans, and the textarea
 * keeps its own text transparent. Selection, undo, paste and IME stay exactly as the browser
 * implements them, which a contenteditable rewrite would hand to us, and the widget's value is the
 * sentence the user typed, character for character.
 *
 * Two things about that mirror are load-bearing, and both are the reason it is built this way rather
 * than the obvious way.
 *
 * A mention has to advance the text by exactly the width of its own glyphs. Padding, a margin or a
 * border on a mention would move every character after it, the mirror's lines would wrap at
 * different places than the textarea's, and the error compounds line after line. So the ring around
 * a mention is an OUTER box-shadow spread, which paints beyond the box without occupying space, and
 * box-decoration-break keeps the ring intact when a mention lands on a line break.
 *
 * The metrics are MEASURED off the textarea, not declared. The reference this technique comes from
 * owns its own textarea and can declare both halves identically; ours belongs to ComfyUI, whose
 * theme, font and padding are its business and may change under us. So the mirror copies the font,
 * the line height and the wrapping rules from whatever the host settled on, and re-copies them
 * whenever the box changes size. The wrapper the host puts the textarea in is not touched: its
 * inline style is recomposed by Vue on every frame, so anything written there is gone by the next
 * one. Everything here is a stylesheet rule and a style on elements we own.
 *
 * If the paint ever throws, the transparency comes straight back off and the box degrades to plain
 * readable text. An invisible prompt is the one failure this must not have.
 *
 * Editor state idioms follow ComfyUI-MiniMaxH3-Easy's ui (MIT), and the mirrored-textarea technique
 * follows ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's promptbuilder.js (MIT). Both credited in
 * README.md.
 */
import { app } from "../../scripts/app.js";

const NODE = "OpenH3IRCompile";

/* The prompt's whole grammar, and the same three literals tray.py reads it with. A mention
 * is @ and a label; a locked line runs from @speaks(" to the first ") . Nothing else is a construct.
 *
 * The character class is `\w-` in tray.py under re.UNICODE, which is letters, digits and underscore
 * -- Python's \w excludes combining marks, so \p{M} is deliberately absent here and `@cafe` followed
 * by a combining accent ends at the same character on both sides. Matching more than a label may
 * legally contain is the safe direction anyway: `@some_thing` is drawn as one mention nobody named
 * and refused by that name, rather than as `@some` plus stray text the user never meant.
 */
const MENTION = /@[\p{L}\p{N}_-]+/uy;
const SPEAKS_OPEN = '@speaks("';
const SPEAKS_CLOSE = '")';

/** The prompt as pieces, exactly as tray.py's parse_intent splits it, and never throwing.
 *
 * Where that function raises -- an opener with no closer -- this returns the piece marked wrong, so
 * the box can say so while it is being typed instead of at the moment somebody presses Run.
 */
export function pieces(text) {
  const src = String(text ?? "");
  const out = [];
  let plain = [];
  const flush = () => {
    if (plain.length) out.push({ kind: "text", text: plain.join("") });
    plain = [];
  };
  let i = 0;
  while (i < src.length) {
    const at = src.indexOf("@", i);
    if (at < 0) { plain.push(src.slice(i)); break; }
    plain.push(src.slice(i, at));
    if (src.startsWith(SPEAKS_OPEN, at)) {
      const start = at + SPEAKS_OPEN.length;
      const end = src.indexOf(SPEAKS_CLOSE, start);
      flush();
      if (end < 0) {
        out.push({ kind: "unclosed", text: src.slice(at) });
        i = src.length;
        continue;
      }
      out.push({ kind: "spoken", words: src.slice(start, end) });
      i = end + SPEAKS_CLOSE.length;
      continue;
    }
    MENTION.lastIndex = at;
    const m = MENTION.exec(src);
    if (!m) { plain.push("@"); i = at + 1; continue; }
    flush();
    out.push({ kind: "mention", label: m[0].slice(1) });
    i = at + m[0].length;
  }
  flush();
  return out;
}

function trayState(node) {
  // The media input's origin node, walked live so the popup and the mentions always read the tray
  // as it is now rather than as it was when this node was made.
  try {
    const input = (node.inputs || []).find((i) => i.name === "media");
    if (!input || input.link == null) return null;
    const link = node.graph.links[input.link];
    const origin = node.graph.getNodeById(link.origin_id);
    return (origin?.widgets || []).find((w) => w.name === "tray") || null;
  } catch {
    return null;
  }
}

export function trayOf(node) {
  try {
    const slots = JSON.parse(trayState(node)?.value || "[]");
    return Array.isArray(slots) ? slots : null;
  } catch {
    return null;
  }
}

function viewUrl(annotated) {
  const name = annotated.replace(/ \[(input|output|temp)\]$/, "");
  const i = name.lastIndexOf("/");
  const params = new URLSearchParams({
    filename: i < 0 ? name : name.slice(i + 1),
    subfolder: i < 0 ? "" : name.slice(0, i),
    type: "input",
  });
  return "/api/view?" + params;
}

/** Everything the Main panel's report line says, computed HERE.
 *
 *  The panel writes the sentences and this decides the facts, because the parse and the walk to the
 *  tray already live in this file and a second copy of either would be a second thing to keep right.
 *  Nothing new is derived: `pieces` is the same parse the mentions are drawn from, and `trayOf` is
 *  the same live walk the picker uses.
 */
export function promptFacts(node, text) {
  const parts = pieces(text);
  // Not connected and connected-but-empty are two different sentences, and `trayOf` answers `[]`
  // to both, so the link itself is what says which.
  const connected = Boolean(trayState(node));
  const slots = connected ? (trayOf(node) || []) : [];
  const known = new Map(slots.map((s) => [String(s.label), String(s.kind || "picture")]));
  const named = { picture: 0, video: 0, sound: 0 };
  const unknown = [];
  let locked = 0;
  let unclosed = false;
  for (const part of parts) {
    if (part.kind === "spoken") locked += 1;
    else if (part.kind === "unclosed") unclosed = true;
    else if (part.kind === "mention") {
      const kind = known.get(part.label);
      if (kind) named[kind] = (named[kind] || 0) + 1;
      else unknown.push(part.label);
    }
  }
  return { written: Boolean(String(text ?? "").trim()), connected, tray: slots,
           trayCount: slots.length, named, unknown, locked, unclosed };
}

class Picker {
  constructor(textarea, node) {
    this.ta = textarea;
    this.node = node;
    this.box = document.createElement("div");
    this.box.className = "oh3-pick";
    this.box.style.display = "none";
    document.body.append(this.box);
    this.at = -1;
    this.items = [];
    this.sel = 0;
    textarea.addEventListener("input", () => this.consider());
    textarea.addEventListener("keydown", (e) => this.keys(e));
    textarea.addEventListener("blur", () => setTimeout(() => this.hide(), 150));
  }

  consider() {
    const pos = this.ta.selectionStart;
    const text = this.ta.value.slice(0, pos);
    const at = text.lastIndexOf("@");
    if (at < 0 || /\s/.test(text.slice(at + 1))) return this.hide();
    const typed = text.slice(at + 1).toLowerCase();
    const slots = trayOf(this.node) || [];
    this.items = [{ label: 'speaks("…")', insert: 'speaks("")', kind: "say" }];
    for (const s of slots) {
      if (!typed || s.label.toLowerCase().startsWith(typed))
        this.items.push({ label: s.label, insert: s.label, kind: s.kind, file: s.file,
                          note: s.note || "" });
    }
    if (typed && !"speaks".startsWith(typed)) this.items = this.items.slice(1);
    if (!this.items.length) return this.hide();
    this.at = at;
    this.sel = 0;
    this.show();
  }

  show() {
    this.box.replaceChildren(...this.items.map((it, i) => {
      const row = document.createElement("div");
      row.className = "oh3-pickrow" + (i === this.sel ? " oh3-picksel" : "");
      if (it.kind === "picture" || it.kind === "video") {
        const img = document.createElement(it.kind === "picture" ? "img" : "video");
        img.src = viewUrl(it.file);
        img.className = "oh3-pickthumb";
        row.append(img);
      } else {
        const dot = document.createElement("span");
        dot.className = "oh3-pickdot";
        dot.textContent = it.kind === "say" ? "❝" : "♪";
        row.append(dot);
      }
      const name = document.createElement("span");
      name.textContent = "@" + it.label + (it.note ? `  —  ${it.note}` : "");
      row.append(name);
      row.addEventListener("mousedown", (e) => { e.preventDefault(); this.take(i); });
      return row;
    }));
    const r = this.ta.getBoundingClientRect();
    this.box.style.left = `${r.left}px`;
    this.box.style.top = `${r.bottom + 2}px`;
    this.box.style.minWidth = `${Math.max(180, r.width * 0.6)}px`;
    this.box.style.display = "block";
  }

  hide() {
    this.box.style.display = "none";
    this.at = -1;
  }

  keys(e) {
    if (this.box.style.display === "none") return;
    if (e.key === "ArrowDown") { this.sel = (this.sel + 1) % this.items.length; this.show(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { this.sel = (this.sel + this.items.length - 1) % this.items.length; this.show(); e.preventDefault(); }
    else if (e.key === "Enter" || e.key === "Tab") { this.take(this.sel); e.preventDefault(); }
    else if (e.key === "Escape") this.hide();
  }

  take(i) {
    const it = this.items[i];
    if (!it) return this.hide();
    const pos = this.ta.selectionStart;
    const before = this.ta.value.slice(0, this.at + 1);
    const after = this.ta.value.slice(pos);
    // A mention is a word in a sentence and the next thing typed is the next word, so the space
    // belongs to the insertion: picking a slot used to leave the caret jammed against the label.
    // Not doubled when the sentence already has one there, which is what happens when a mention is
    // picked in the middle of a line the user is editing.
    const gap = /^[ \t\n]/.test(after) ? "" : " ";
    this.ta.value = before + it.insert + gap + after;
    const cursor = it.kind === "say"
      ? before.length + it.insert.length - 2   // inside the empty quotes
      : before.length + it.insert.length + gap.length;
    this.ta.setSelectionRange(cursor, cursor);
    this.ta.dispatchEvent(new Event("input", { bubbles: true }));
    if (it.kind !== "say") this.hide();
    this.ta.focus();
  }
}

/* Everything that decides where a character lands. Copied off the host's textarea rather than
 * declared, because a difference in any one of them wraps the mirror's lines somewhere else. */
const METRICS = [
  "fontFamily", "fontSize", "fontWeight", "fontStyle", "fontVariant", "fontStretch",
  "lineHeight", "letterSpacing", "wordSpacing", "textIndent", "textTransform", "textAlign",
  "whiteSpace", "overflowWrap", "wordBreak", "tabSize", "direction",
];

class Chips {
  constructor(textarea, node) {
    this.ta = textarea;
    this.node = node;
    this.mirror = document.createElement("div");
    this.mirror.className = "oh3-mirror";
    this.mirror.setAttribute("aria-hidden", "true");
    textarea.parentElement.insertBefore(this.mirror, textarea);
    this.live = false;
    this.was = null;      // the text last painted
    this.wasTray = null;  // the tray's own text when it was last painted

    textarea.addEventListener("input", () => this.paint());
    textarea.addEventListener("scroll", () => this.follow());
    // While an input method is composing, its unconfirmed characters live in the textarea and
    // nowhere else, so the mirror stands down and the real text shows until the word is committed.
    textarea.addEventListener("compositionstart", () => this.reveal(false));
    textarea.addEventListener("compositionend", () => this.paint());
    // The mirror cannot take a pointer, since it sits under the textarea and must not steal a
    // click, so the marks are hit-tested through it against the pointer's own position.
    textarea.addEventListener("mousemove", (e) => this.peek(e));
    textarea.addEventListener("mouseleave", () => this.unpeek());
    textarea.addEventListener("scroll", () => this.unpeek());
    // The one event that reports the box's real geometry, including the first time it has any.
    this.watch = new ResizeObserver(() => { this.metrics(); this.paint(); });
    this.watch.observe(textarea);
  }

  /** The file a mention names, shown while the pointer is on it.
   *
   * A thumbnail cannot go in the line itself: an image occupies room, the mirror's lines would then
   * wrap somewhere the textarea's do not, and every character after it drifts. So the picture is
   * shown beside the sentence instead of inside it, which is also the only version of this that
   * works for a clip and for a sound.
   */
  peek(e) {
    let on = null;
    for (const chip of this.mirror.querySelectorAll(".oh3-m[data-slot]")) {
      const r = chip.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right
          && e.clientY >= r.top && e.clientY <= r.bottom) { on = chip; break; }
    }
    if (!on) return this.unpeek();
    const label = on.dataset.slot;
    if (this.peeking === label) return;
    this.unpeek();
    const slot = (trayOf(this.node) || []).find((s) => s.label === label);
    if (!slot) return;
    this.peeking = label;
    this.card = document.createElement("div");
    this.card.className = "oh3-peek";
    if (slot.kind === "picture" || slot.kind === "video") {
      const media = document.createElement(slot.kind === "picture" ? "img" : "video");
      media.className = "oh3-peekmedia";
      media.src = viewUrl(slot.file);
      if (slot.kind === "video") { media.muted = true; media.preload = "metadata"; }
      this.card.append(media);
    }
    // Its own note, which is the words the user wrote about this file, and the words this mention
    // becomes in the sentence the compiler reads. Not the role: that is the tray panel's vocabulary
    // and restating it here would be a third place to keep it right.
    this.card.append(this.span("oh3-peekname", "@" + slot.label));
    if (slot.note) this.card.append(this.span("oh3-peeknote", slot.note));
    document.body.append(this.card);
    const r = on.getBoundingClientRect();
    this.card.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - 220))}px`;
    const above = r.top - this.card.offsetHeight - 6;
    this.card.style.top = `${above > 4 ? above : r.bottom + 6}px`;
  }

  unpeek() {
    this.peeking = null;
    this.card?.remove();
    this.card = null;
  }

  /** Plain readable text, sugar off. Called on composition and on the one failure this must
   *  survive: whatever went wrong, the sentence stays legible. */
  reveal(permanently) {
    this.live = false;
    // `was` is the text the mirror is currently SHOWING, so hiding the mirror has to clear it.
    // Leaving it set told the next paint that the drawing was already up to date and there was
    // nothing to do, and the chips never came back after an input method finished composing.
    this.was = null;
    this.ta.classList.remove("oh3-chiptext");
    this.mirror.style.display = "none";
    if (permanently) {
      this.dead = true;
      this.watch.disconnect();
      this.mirror.remove();
    }
  }

  metrics() {
    const cs = getComputedStyle(this.ta);
    const n = (v) => parseFloat(v) || 0;
    const [pl, pr, pt, pb] = [cs.paddingLeft, cs.paddingRight, cs.paddingTop, cs.paddingBottom]
      .map(n);
    const [bl, bt] = [cs.borderLeftWidth, cs.borderTopWidth].map(n);
    const s = this.mirror.style;
    for (const k of METRICS) s[k] = cs[k];
    // The mirror IS the textarea's content box: no padding of its own, and a width taken from
    // clientWidth, which already excludes the scrollbar. A mirror sized to the outer box would
    // wrap a line later than the textarea does the moment the text is long enough to scroll.
    s.left = `${this.ta.offsetLeft + bl + pl}px`;
    s.top = `${this.ta.offsetTop + bt + pt}px`;
    s.width = `${Math.max(0, this.ta.clientWidth - pl - pr)}px`;
    s.height = `${Math.max(0, this.ta.clientHeight - pt - pb)}px`;
    this.boxWidth = this.ta.clientWidth;
    this.ready = this.boxWidth > 0;
  }

  follow() {
    this.mirror.scrollTop = this.ta.scrollTop;
    this.mirror.scrollLeft = this.ta.scrollLeft;
  }

  span(cls, text) {
    const e = document.createElement("span");
    e.className = cls;
    e.textContent = text;
    return e;
  }

  build(text) {
    const slots = new Map((trayOf(this.node) || [])
      .map((s) => [String(s.label).toLowerCase(), s]));
    const kids = [];
    for (const p of pieces(text)) {
      if (p.kind === "text") { kids.push(document.createTextNode(p.text)); continue; }
      if (p.kind === "mention") {
        // The same case-blind lookup resolve_intent does, so a mention the tray cannot answer is
        // drawn as wrong here and refused by that name there, instead of looking fine until Run.
        const slot = slots.get(p.label.toLowerCase());
        const chip = this.span("oh3-m" + (slot ? "" : " oh3-mbad"), "");
        // The sigil is tinted by what the file IS, which is the one place a kind can be shown
        // without costing room: a picture, a clip and a sound read differently in the sentence
        // while every character still lands exactly where the textarea puts it.
        chip.append(this.span("oh3-sig oh3-sig" + (slot ? slot.kind : "none"), "@"),
                    document.createTextNode(p.label));
        if (slot) chip.dataset.slot = slot.label;
        kids.push(chip);
        continue;
      }
      // Opened and never closed: the same object, unfinished. It wears the box rather than a
      // mention's ring, so the shape still says which construct it is while the colour says the
      // graph will refuse it.
      if (p.kind === "unclosed") {
        kids.push(this.span("oh3-say oh3-saybad", p.text));
        continue;
      }
      // The whole construct is one object, sigil and quotes and words together. Boxing only the
      // words made @speaks(" and ") read as scaffolding standing outside the thing, and they are
      // part of how the line is written: nothing inside it is dimmed or set apart.
      kids.push(this.span("oh3-say", SPEAKS_OPEN + p.words + SPEAKS_CLOSE));
    }
    return kids;
  }

  paint() {
    if (this.dead) return;
    // The keystroke that makes the prompt long enough to scroll is also the one that takes a
    // scrollbar's width out of the box, on the platforms where a scrollbar occupies room rather than
    // floating over the text. Reading clientWidth flushes layout and reports the width the text will
    // actually wrap in, so the mirror narrows in the same frame instead of a frame later, when the
    // resize observer would otherwise be the one to notice.
    if (this.ta.clientWidth !== this.boxWidth) this.metrics();
    const text = this.ta.value || "";
    const trayText = trayState(this.node)?.value ?? null;
    // One keystroke arrives here twice: once from the textarea's own input event, and once because
    // ComfyUI's handler for that same event assigns the widget's value, which runs the setValue this
    // class wraps. Both routes are kept, since either one alone would be a bet on how the host wires
    // its own widget, and a redraw of text that did not change is skipped instead.
    if (this.live && text === this.was && trayText === this.wasTray) return this.follow();
    // Whatever was being hovered has just moved, and a card pointing at where a mention used to be
    // is worse than no card. This also clears it when the box itself goes away, since removing the
    // textarea resizes it to nothing and lands here.
    this.unpeek();
    this.was = text;
    this.wasTray = trayText;
    try {
      if (!text) {
        // Nothing to draw, so the sugar comes off entirely and the box shows the host's own
        // placeholder, which is this widget's only label. Drawing a second copy of it in the mirror
        // put two of them on top of each other.
        this.mirror.replaceChildren();
        this.ta.classList.remove("oh3-chiptext");
      } else {
        // The trailing newline keeps the mirror's last line in step with the textarea's when the
        // text ends on one.
        this.mirror.replaceChildren(...this.build(text), document.createTextNode("\n"));
        if (this.ready) this.ta.classList.add("oh3-chiptext");
      }
      this.mirror.style.display = "";
      this.live = true;
      this.follow();
    } catch (err) {
      console.error("[OpenH3-IR] the prompt's mentions could not be drawn, so the box is showing "
                    + "plain text. The sentence itself is untouched.", err);
      this.reveal(true);
    }
  }

  /** Repaint when something outside this box changed what it should say: a slot renamed on the
   *  Media node, or a value written straight into the widget by a workflow load or an undo. Two
   *  string comparisons, on the canvas's own redraw, and no layout is read. */
  check() {
    if (!this.live) return;
    if (this.ta.value === this.was && (trayState(this.node)?.value ?? null) === this.wasTray) return;
    this.paint();
  }
}

const CSS = `
.oh3-pick{position:fixed;z-index:10000;background:#14161c;border:1px solid #2e3440;border-radius:6px;
  padding:3px;font-family:system-ui,sans-serif;font-size:12px;color:#dde2ea;max-height:240px;
  overflow-y:auto;box-shadow:0 12px 32px rgba(0,0,0,.5);}
.oh3-pickrow{display:flex;align-items:center;gap:7px;padding:4px 7px;border-radius:4px;cursor:pointer;}
.oh3-pickrow:hover,.oh3-picksel{background:#232735;}
.oh3-pickthumb{width:28px;height:20px;object-fit:cover;border-radius:3px;flex:0 0 auto;}
.oh3-pickdot{width:28px;text-align:center;color:#e8873a;flex:0 0 auto;}

/* The mirror. Every metric that decides where a character lands is written from the textarea's own
   computed style, so nothing about type is declared here -- only the things that cannot be
   inherited from an element this div is not inside. */
.oh3-mirror{position:absolute;margin:0;padding:0;border:0;overflow:hidden;pointer-events:none;
  color:#f3efe6;background:none;}
/* The textarea over it: its own glyphs transparent, its caret and its selection not. The selection
   deliberately paints opaque text, so what you have selected stays readable on top of the mirror. */
textarea.oh3-chiptext{background:transparent;color:transparent;caret-color:#f3efe6;}
textarea.oh3-chiptext::selection{background:rgba(235,130,25,.34);color:#f3efe6;}
/* A mention, drawn as one object. No padding, no margin and no border, because any of them would
   move the characters after it and the mirror would stop lining up with the text: the ring is an
   outer box-shadow spread, which paints outside the box without taking any room, and
   box-decoration-break keeps it whole when a mention falls on a line break. */
.oh3-m{border-radius:3px;background:rgba(235,130,25,.16);color:#ffb066;
  box-shadow:0 0 0 2px rgba(235,130,25,.16), inset 0 0 0 1px rgba(235,130,25,.55);
  -webkit-box-decoration-break:clone;box-decoration-break:clone;}
/* A name the tray cannot answer, and an opener with no closer. Both are refused when the graph
   runs, so both say so while they are being typed. */
.oh3-m.oh3-mbad{background:rgba(240,112,112,.16);color:#f28b8b;
  box-shadow:0 0 0 2px rgba(240,112,112,.16), inset 0 0 0 1px rgba(240,112,112,.55);}
/* A locked line, boxed whole. The breathing room inside the box is a wider outer spread for the same
   reason a mention has no padding: room taken in the line is room the textarea did not take.

   Green because this is the one span of the sentence that reaches the model letter for letter, and a
   brief that rewords it is refused and rewritten. The bone grey it wore first was dimmer than the
   prose around it, and dim on a canvas reads as disabled, which is the opposite of what a locked
   line is. Green is also clear of every hue already spoken for here: orange a picture, teal a clip,
   violet a sound, red something the graph will turn away. */
.oh3-say{border-radius:3px;background:rgba(95,201,138,.16);color:#b9efca;
  box-shadow:0 0 0 3px rgba(95,201,138,.16), inset 0 0 0 1px rgba(95,201,138,.62);
  -webkit-box-decoration-break:clone;box-decoration-break:clone;}
/* Opened and never closed. The same box, because it is the same object: the shape says which
   construct this is and the colour says whether it is finished. */
.oh3-say.oh3-saybad{background:rgba(240,112,112,.16);color:#f7bcbc;
  box-shadow:0 0 0 3px rgba(240,112,112,.16), inset 0 0 0 1px rgba(240,112,112,.62);}
/* The sigil carries the kind. Colour only: anything that changed its width would move every
   character after it. A name the tray cannot answer keeps the red of its own chip. */
.oh3-sig{color:#eb8219;}
.oh3-signone{color:#f28b8b;}
.oh3-sigpicture{color:#eb8219;}
.oh3-sigvideo{color:#68b6c8;}
.oh3-sigsound{color:#b48ce8;}
.oh3-mbad .oh3-sig{color:#f28b8b;}
/* The file a mention names, beside the sentence rather than in it. */
.oh3-peek{position:fixed;z-index:10002;width:212px;background:#14161c;
  border:1px solid #2e3440;border-radius:8px;overflow:hidden;pointer-events:none;
  box-shadow:0 14px 36px rgba(0,0,0,.55);font-family:system-ui,sans-serif;}
.oh3-peekmedia{width:100%;max-height:142px;object-fit:contain;display:block;background:#0a0a0d;}
.oh3-peekname{display:block;padding:5px 8px 0;font-size:10px;color:#eb8219;
  font-family:ui-monospace,monospace;}
/* The note wraps rather than ending in an ellipsis: it is the whole reason to look at this card. */
.oh3-peeknote{display:block;padding:1px 8px 5px;font-size:10px;line-height:1.45;
  color:rgba(243,239,230,.72);}
`;

/** Wire the picker and the mentions onto a textarea somebody else owns.
 *
 *  It used to find ComfyUI's own multiline widget and attach there. The Main panel draws its own
 *  box now, because a host widget cannot sit inside a panel and still look like one surface, so
 *  this takes whatever textarea it is handed. Nothing in either class had to change: both measure
 *  their metrics off the element rather than declaring them.
 */
export function attachPrompt(textarea, node) {
  if (!textarea || textarea._oh3Picker) return;
  textarea._oh3Picker = new Picker(textarea, node);
  node._oh3Chips = new Chips(textarea, node);
  return node._oh3Chips;
}

app.registerExtension({
  name: "openh3ir.prompt",
  init() {
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.append(style);
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE) return;
    // The canvas redraws when anything changes, including a slot being renamed on the Media node,
    // which is the one thing that can turn a mention wrong without this box being touched.
    const onDraw = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function () {
      this._oh3Chips?.check();
      return onDraw?.apply(this, arguments);
    };
  },
});
