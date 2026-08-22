/* OpenH3-IR Director: the panel.
 *
 * The node holds two things — what to call this direction, and the direction itself, written as
 * plain prose. Everything else on this panel exists to fill that second box: picking a director
 * writes its whole text into it, because a preset that selects a name and shows you nothing is a
 * preset you cannot read, edit, or learn from.
 *
 * Everything here is rendering. The node's one real field is the `profile` string (JSON with two
 * keys) and this panel is an editor for it: delete this file and the node still works, still
 * API-drives, and still restores from a saved workflow, exactly as the media tray does. That stays
 * true of the stored directions below — a graph carries the words it was written with, never a
 * pointer to a name, so a workflow opened on a machine that has never seen this store still
 * compiles exactly what you wrote.
 *
 * The seven texts come from ./contract.data.js, which is GENERATED from the compiler's own
 * h3ir/director.py by `h3ir contract --js`. The panel carries a copy because the compiler may be on
 * another machine or not running at all, and a text box that needs a service before it can show you
 * a paragraph is a text box that is empty when you need it. It is generated rather than typed
 * because eleven thousand characters of prose maintained by hand in two languages is drift with a
 * schedule; tests/test_contract_drift.py fails while the copy is stale. Here they are a SEED rather
 * than a menu: the first time the node is opened they are written into the store as ordinary
 * directions, and from then on the list is just what is in the store — no shipped category, nothing
 * that cannot be renamed or deleted.
 *
 * **Where the store is, and why not in the service.** Files in ComfyUI's own per-user folder,
 * `user/default/openh3ir/directors/<name>.json`, through the `/userdata` routes ComfyUI already
 * serves. The compiler's service was the other candidate and it loses on the panel's own rule: it
 * may be on another machine, it may be down, and a list that empties itself exactly when somebody
 * is trying to write in it is the failure this whole file is shaped around. It would also have
 * meant new write routes on a service that binds 0.0.0.0. The cost is stated plainly in the pack's
 * README: a stored direction belongs to this ComfyUI, and a workflow never depends on one.
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
/* The compiler's own three, generated rather than typed: the seven directions word for word, H3's
 * closed motion table, and the length the compiler refuses a longer direction at. See the header
 * for why the panel carries a copy at all. `h3ir contract --js` writes that file and
 * tests/test_contract_drift.py fails while it is stale, so the eleven thousand characters below the
 * import are never maintained by hand in two languages. */
import { CAMERA_MOVES, DIRECTORS, MAX_NOTES } from "./contract.data.js";

const VERSION = "director v3";
console.log("[OpenH3-IR]", VERSION);
const NODE = "OpenH3IRDirector";
const NODE_W = 480;
const NODE_H_EXTRA = 34;
const PANEL_H = 430;
const MIN_W = 380;
const MIN_H = 300;
/* Where every direction lives, under ComfyUI's per-user folder. One JSON per direction, named as
 * you named it, holding exactly the two keys the node's field holds. See the header for why this
 * and not the compiler's service. */
const SAVED_DIR = "openh3ir/directors";

const PLACEHOLDER =
  "How they shoot, shape a scene, what makes their style unique, and what kind of personality " +
  "they bring to their work.";

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

class Panel {
  constructor(node, widget) {
    this.node = node;
    this.widget = widget;
    /* What a second click would do, and to what. Three things on this panel destroy something that
     * nothing brings back: `pick:<name>` would replace typing that was never saved, `save` would
     * write over a direction that is not the one being edited, `forget` would delete one. Loading a
     * stored direction is not among them, and neither is emptying one -- `reconcile` is what tells
     * those apart. One at a time, and anything else the pointer touches puts it down again. */
    this.armed = null;
    this.saved = [];        // every direction in the store, the shipped ones included
    this.libraryNote = "";  // why the list is short, when it is short for a reason
    this.listOpen = false;
    /* Which stored direction this panel is editing, or null for one that has never been saved.
     *
     * It is NOT re-derived from the text. Two directions can hold identical words — measured on the
     * canvas: after saving a copy of a shipped one under a new name the panel stayed on the
     * original, and `forget` acted on the wrong row. And it deliberately survives editing, because
     * editing a direction and pressing save is how you change one; a row that fell away as soon as
     * you touched it would turn every edit into a new file. */
    this.on = null;

    this.msg = el("span", { class: "oh3d-msg" });
    const top = el("div", { class: "oh3d-top" },
      el("span", { class: "oh3d-title", textContent: "Direction" }), this.msg);
    const lead = el("div", { class: "oh3d-lead", textContent:
      "Anything your prompt in the Main node leaves open to interpretation (camera, lighting, "
      + "pacing, performance, sound, etc) will follow this direction. Choose a saved director or "
      + "create your own." });

    /* One control, not two. The name of the direction and the way you choose a different one were
     * a picker and a `called` field saying the same thing twice — the owner's words: "'start from',
     * 'called', duplication, just put a damn edit name on it." So the name IS the field: type in it
     * to rename what you are editing, or open the list beside it to load another. */
    this.nameIn = el("input", { class: "oh3d-in", placeholder: "name this direction",
      title: "What this direction is called. Type here to rename it, then press save to keep the "
             + "change. The name never reaches the model, only the words in the box, so call it "
             + "whatever you like." });
    // Typing clears whatever the line was saying. It reports what just happened, and the moment
    // somebody starts typing it is reporting the past: the owner watched "Empty. A node with
    // nothing written in it steers nothing." sit there while he filled the box, and reasonably
    // concluded a direction did not count until he pressed save. `renderCount` re-states the
    // over-the-cap warning on the same keystroke, because that one is about what is there now.
    this.nameIn.addEventListener("input", () => { this.armed = null; this.say(""); this.commit(); });
    this.openBtn = el("span", { class: "oh3d-caret", textContent: "▾",
      title: "Every direction saved on this ComfyUI. Pick one and its whole text drops into the "
             + "box, yours to read and change.",
      onclick: (e) => { e.stopPropagation(); this.toggleList(); } });

    this.saveBtn = el("span", { class: "oh3d-btn", textContent: "save",
      title: "Keeps this direction under the name above so you can pick it in any graph on this "
             + "ComfyUI. You do not need to save: what is in the box already works. Saving is only "
             + "so you can use it again.",
      onclick: () => this.save() });
    this.forgetBtn = el("span", { class: "oh3d-btn oh3d-quiet", textContent: "forget",
      title: "Removes this direction from the list. What is in the box stays, and any workflow "
             + "already written with it is unaffected.",
      onclick: () => this.forget() });
    this.list = el("div", { class: "oh3d-list" });

    /* A visible label, not a placeholder. The owner's standing rule for panels this pack draws
     * itself: "the placeholder is not enough ... doesn't have a label", because a placeholder is
     * gone the moment somebody types and the field is unlabelled from then on. The media tray
     * already labels every field this way (`name`, `what it is`, `about it`).
     *
     * "Their" points at the name in the pill directly above. */
    this.notesLabel = el("div", { class: "oh3d-nlabel" },
      el("span", { textContent: "Their style" }),
      /* The one fact he had to learn twice, kept where it is still true when it matters.
       *
       * Not the placeholder: that is gone on the first keystroke, and the moment he needs this is
       * the moment he has just filled the box. Not the message line either, which reports what just
       * happened and which typing deliberately clears. So it sits on the label's own row, above the
       * box, permanent, wrapping rather than truncating. The row already existed, so at the width
       * the node opens at this costs no height at all. */
      el("span", { class: "oh3d-nnote",
        textContent: "Changes here apply immediately. Save only if you want to reuse this style "
                     + "later." }));
    this.notesIn = el("textarea", { class: "oh3d-notes", placeholder: PLACEHOLDER, spellcheck: true,
      title: "How this director works. It steers the writing rather than commanding it: nothing "
             + "here is enforced, and your own sentence always comes first." });
    this.notesIn.addEventListener("input", () => { this.armed = null; this.say(""); this.commit(); });

    this.count = el("span", { class: "oh3d-count" });
    this.movesBtn = el("span", { class: "oh3d-link",
      textContent: "the twenty camera moves",
      title: "The twenty camera moves H3 knows by name. Naming one is the strongest lever you "
             + "have over the camera.",
      onclick: () => {
        this.movesOpen = !this.movesOpen;
        this.renderMoves();
      } });
    const foot = el("div", { class: "oh3d-foot" }, this.count, this.movesBtn);
    this.moves = el("div", { class: "oh3d-moves" });

    this.root = el("div", { class: "oh3d-panel" }, top, lead,
      this.pickRow = el("div", { class: "oh3d-row" },
        el("div", { class: "oh3d-wrow" },
          el("span", { class: "oh3d-wlabel", textContent: "director" }), this.nameIn, this.openBtn),
        this.saveBtn, this.forgetBtn),
      this.notesLabel, this.notesIn, foot, this.list, this.moves);
    // Anything the pointer touches that is not the armed control itself puts it down again, so a
    // half-pressed destructive action never waits around for an unrelated click to finish it. The
    // open list closes on the same principle.
    /* This handler runs BEFORE the click handler on whatever was pressed, so anything it decides
     * about is decided twice unless the control that owns the decision is excluded here.
     *
     * Both exclusions are measured, not precautionary. Without the list: choosing a row armed it,
     * this disarmed it, and the row's own click armed it again -- a confirmation that could never
     * be given. Without the caret: this closed the list and the caret's toggle immediately
     * reopened it, so the one control that opens the list could never close it. */
    this.root.addEventListener("pointerdown", (e) => {
      const inList = Boolean(e.target.closest?.(".oh3d-list"));
      const onCaret = e.target === this.openBtn;
      const answering = e.target.classList?.contains("oh3d-btn") || inList;
      if (this.armed && !answering) { this.armed = null; this.renderControls(); this.renderList(); }
      if (this.listOpen && !inList && !onCaret) { this.listOpen = false; this.renderList(); }
    });
    this.render();
    this.refreshLibrary();
  }

  // ------------------------------------------------------------- the one real field

  state() {
    try {
      const v = JSON.parse(this.widget.value || "{}");
      return (v && typeof v === "object" && !Array.isArray(v)) ? v : {};
    } catch { return {}; }
  }

  /** Write the two fields back into the widget. Empty on both sides writes an empty object, so a
   *  node dropped in and left alone is byte-identical to one that was never touched. */
  commit() {
    const name = this.nameIn.value.trim();
    const notes = this.notesIn.value;
    this.widget.value = (!name && !notes.trim()) ? "{}" : JSON.stringify({ name, notes });
    this.node.setDirtyCanvas?.(true, true);
    this.renderControls();
    this.renderCount();
  }

  /** The one line that reports what just happened.
   *
   *  It is ONE row and it truncates. Measured on the real element rather than counted: the slot is
   *  384px at the width the node opens at and 284px at its minimum, which is **77 characters of
   *  ordinary prose at the default and 57 at the minimum**. State it in prose-characters, because
   *  the budget is glyph-dependent: the same slot takes only 62 characters of capitals. Anything
   *  longer is not lost, the `title` carries it whole, but the tail is what goes, so put the thing
   *  to do at the front and the reassurance after it. */
  say(text, bad = false) {
    this.msg.textContent = text || "";
    this.msg.title = text || "";
    this.msg.classList.toggle("oh3d-bad", Boolean(bad));
  }

  // ------------------------------------------------------------- the one control
  //
  // The name of the direction and the way you choose a different one used to be two controls
  // saying the same thing -- a `start from` picker above a `called` field. They are one now: the
  // field IS the name, typing in it renames what you are editing, and the caret beside it opens
  // the list. The owner's words: "'start from', 'called', duplication, just put a damn edit name
  // on it."
  //
  // And the list is FLAT. The seven that ship are not a category, they are seven directions that
  // were already in the store the first time you opened the node, indistinguishable from the ones
  // you write. That is what makes `forget` work on any of them without a special case: there is
  // only one kind of row. "just preload the list with them, they should be able to be removed too."

  path(name) { return `${SAVED_DIR}/${name}.json`; }

  /** Write the two fields, and record which stored direction they came from. */
  write(name, notes, from) {
    this.on = from ?? null;
    this.nameIn.value = name;
    this.notesIn.value = notes;
    this.notesIn.scrollTop = 0;
    this.commit();
  }

  toggleList() {
    this.listOpen = !this.listOpen;
    this.armed = null;
    if (this.listOpen) this.movesOpen = false;
    this.renderMoves();
    this.renderList();
  }

  /** A row was chosen. It loads on the first click unless doing so would destroy typing that
   *  exists nowhere else, and the difference is `this.on`.
   *
   *  **The owner hit this asking when it had no business asking**, and read the first click as the
   *  control being broken -- "reads as 'button didn't work'". That reading is fair: a control that
   *  visibly refuses an ordinary action is indistinguishable from a dead one. But the fault was the
   *  panel not knowing that the box already held a stored direction, which `reconcile` now settles.
   *  Loaded, restored, or empty, this asks nothing.
   *
   *  **It still asks for typing that was never saved, because nothing else brings that back.** That
   *  was measured rather than assumed, and it is the opposite of what I first concluded: ComfyUI's
   *  undo restores a whole direction that a CHOICE replaced, but it does not restore what somebody
   *  TYPED -- ctrl+Z after typing 80 characters and choosing a row returned an empty object, not the
   *  words, however long the stack was left to settle. So the one case left is the one case that
   *  cannot be undone, and the row itself becomes the question rather than a sentence in a corner. */
  choose(name) {
    const unsaved = this.notesIn.value.trim() && this.on === null;
    if (unsaved && this.armed !== `pick:${name}`) {
      this.armed = `pick:${name}`;
      this.say("Choose it again to replace what you wrote, or save yours first.");
      this.renderControls();
      this.renderList();     // the row that is asking has to be the row that looks like it is
      return;
    }
    this.armed = null;
    this.listOpen = false;
    if (!name) {
      this.write("", "", null);
      this.say("Empty. This video has no director now.");
      this.renderList();
      return;
    }
    this.open(name);
  }

  // ------------------------------------------------------------- the store
  //
  // Files in ComfyUI's own per-user store, one JSON per direction holding exactly the two keys the
  // node's field holds. So a stored direction IS a direction: nothing is translated on the way in
  // or out, and the files sit beside the workflows where a person can read, copy, back up or delete
  // them without this panel. See the header for why the store is here and not in the compiler's.

  /** Read the list. The first time ever, write the seven into it first.
   *
   *  Seeding is keyed on the FOLDER not existing, which is the only state that means "this has
   *  never been used". Deleting every direction leaves the folder behind, so an empty list stays
   *  empty and a director you removed stays removed -- which is the whole point of being able to
   *  remove one. Deleting the folder by hand is therefore the way to get the shipped seven back,
   *  and it is the only way, on purpose: an undo that fires on its own would be the silent
   *  behaviour this pack refuses everywhere else.
   */
  async refreshLibrary() {
    try {
      let r = await api.fetchApi(`/userdata?dir=${encodeURIComponent(SAVED_DIR)}`);
      if (r.status === 404) {
        await this.seed();
        r = await api.fetchApi(`/userdata?dir=${encodeURIComponent(SAVED_DIR)}`);
      }
      if (!r.ok) {
        this.saved = [];
        this.libraryNote = `ComfyUI answered ${r.status}, so the saved directions could not be `
                           + "listed.";
      } else {
        const files = await r.json();
        this.saved = files.filter((f) => typeof f === "string" && f.endsWith(".json")
                                         && !f.startsWith("."))
          .map((f) => f.slice(0, -5)).sort((a, b) => a.localeCompare(b));
        this.libraryNote = "";
      }
    } catch (e) {
      this.saved = [];
      this.libraryNote = `The saved directions could not be listed. (${e})`;
    }
    this.renderControls();
    this.renderList();
    await this.reconcile();
  }

  /** The seven, written into the store as ordinary directions. */
  async seed() {
    for (const d of DIRECTORS) {
      try {
        await api.fetchApi(`/userdata/${encodeURIComponent(this.path(d.name))}?overwrite=false`,
                           { method: "POST",
                             body: JSON.stringify({ name: d.name, notes: d.notes }) });
      } catch (e) { /* one that will not write is one row short, and the listing will show that */ }
    }
  }

  /** After repainting from the graph, work out whether the box IS one of the stored directions.
   *
   *  `render()` cannot know: what a workflow carries is words and a name, never a pointer into this
   *  store, so it clears `this.on` and the panel forgets which row it is holding. Everything keyed
   *  on that then reads a freshly restored director as unsaved work -- measured on the canvas: open
   *  a workflow with Denis Villeneuve in it, choose another director, and the guard asks twice and
   *  says "it is not saved" about a direction sitting in the list two rows above. `forget`
   *  disappears for the same reason, and `blank` asks as well.
   *
   *  The name in the field is the lookup, so this costs ONE request rather than one per row, and it
   *  compares the notes byte for byte: same name and same words means the box holds that direction
   *  and there is nothing of anybody's to protect. Different words under the same name is a real
   *  edit and the guard is right to fire.
   *
   *  Anything that goes wrong here leaves `this.on` null, which is the safe direction: the panel
   *  asks before it destroys instead of assuming it may. That is why the failures below are quiet
   *  rather than spoken -- a store that cannot be read is already said once, by `refreshLibrary`.
   */
  async reconcile() {
    const name = this.nameIn.value.trim();
    const notes = this.notesIn.value;
    if (this.on !== null || !name || !notes.trim() || !this.saved.includes(name)) return;
    let stored;
    try {
      const r = await api.fetchApi(`/userdata/${encodeURIComponent(this.path(name))}`);
      if (!r.ok) return;
      stored = JSON.parse(await r.text());
    } catch (e) { return; }
    if (String(stored?.notes ?? "") !== notes) return;
    this.on = name;
    this.renderControls();
    this.renderList();
  }

  /** Load one into the box. */
  async open(name) {
    let data;
    try {
      const r = await api.fetchApi(`/userdata/${encodeURIComponent(this.path(name))}`);
      if (!r.ok) throw new Error(`ComfyUI answered ${r.status}`);
      data = JSON.parse(await r.text());
    } catch (e) {
      this.say(`${name} could not be read. Nothing in the box changed. (${e})`, true);
      this.renderControls();
      return;
    }
    const notes = String(data?.notes || "");
    if (!notes.trim()) {
      this.say(`${name} has nothing written in it.`, true);
      this.renderControls();
      return;
    }
    this.write(String(data?.name || name), notes, name);
    this.say(`${name} is directing. Edit any of it.`);
    this.renderList();
  }

  /** Everything that makes a name unusable, in the words to read. */
  refuseName(name) {
    if (!name) return "Give it a name first. That is what you will pick it by.";
    if (/[\\/:*?"<>|]/.test(name)) {
      return "A name cannot contain \\ / : * ? \" < > or |.";
    }
    if (name.startsWith(".")) return "A name cannot start with a dot.";
    if (name.length > 80) return `That name is ${name.length} characters and the limit is 80.`;
    return "";
  }

  /** Keep this direction under the name in the field.
   *
   *  Renaming falls out of this rather than being a second button: the panel knows which stored
   *  direction it is editing, so a changed name moves that one instead of leaving a copy behind.
   *  The second click is asked for in exactly one case -- when the name is a DIFFERENT direction
   *  that already exists -- because overwriting the one you are already editing is what save means.
   */
  async save() {
    const name = this.nameIn.value.trim();
    const notes = this.notesIn.value;
    if (!notes.trim()) { this.say("Nothing to save yet. Write the direction first.", true); return; }
    const refusal = this.refuseName(name);
    if (refusal) { this.say(refusal, true); this.renderControls(); return; }
    const renaming = this.on !== null && this.on !== name;
    const overwriting = this.saved.includes(name) && name !== this.on;
    if (overwriting && this.armed !== "save") {
      this.armed = "save";
      this.say(`${name} already exists. Click save again to write over it.`);
      this.renderControls();
      return;
    }
    this.armed = null;
    try {
      const r = await api.fetchApi(`/userdata/${encodeURIComponent(this.path(name))}`,
                                   { method: "POST", body: JSON.stringify({ name, notes }) });
      if (!r.ok) throw new Error(`ComfyUI answered ${r.status}`);
    } catch (e) {
      this.say(`${name} was not saved (${e}). What is in the box is untouched.`, true);
      this.renderControls();
      return;
    }
    // The rename is the delete of the old name, and it happens only after the new one is safely
    // written. The other order loses the direction if the write fails.
    let orphan = "";
    if (renaming) {
      try {
        const r = await api.fetchApi(`/userdata/${encodeURIComponent(this.path(this.on))}`,
                                     { method: "DELETE" });
        if (!r.ok) throw new Error(`ComfyUI answered ${r.status}`);
      } catch (e) {
        orphan = ` The old ${this.on} could not be removed (${e}), so both are in the list.`;
      }
    }
    this.on = name;
    await this.refreshLibrary();
    this.say(renaming && !orphan ? `Renamed to ${name}.`
             : `Saved. Pick ${name} in any graph on this ComfyUI.${orphan}`, Boolean(orphan));
  }

  async forget() {
    if (this.on === null) {
      // Kept rather than deleted, though the button is hidden in exactly this state: without it
      // `this.on` of null would build a path ending `/null.json` and send a DELETE for a file that
      // was never there. Three lines against a nonsense request on a delete route.
      this.say("Nothing to forget. This direction has never been saved.", true);
      return;
    }
    const name = this.on;
    if (this.armed !== "forget") {
      this.armed = "forget";
      this.say(`Click forget again to delete ${name} for good.`);
      this.renderControls();
      return;
    }
    this.armed = null;
    try {
      const r = await api.fetchApi(`/userdata/${encodeURIComponent(this.path(name))}`,
                                   { method: "DELETE" });
      if (!r.ok) throw new Error(`ComfyUI answered ${r.status}`);
    } catch (e) {
      this.say(`${name} was not deleted (${e}). It is still in the list.`, true);
      this.renderControls();
      return;
    }
    this.on = null;
    await this.refreshLibrary();
    this.say(`${name} is gone from the list. The box keeps its words.`);
  }

  // ------------------------------------------------------------- drawing them

  renderControls() {
    /* The button says what it is about to do. Changing the name of a direction you are editing
     * MOVES it rather than leaving a copy, which is what was asked for and is also the one thing
     * here somebody could be surprised by -- start from a shipped one, name it yours, and the
     * shipped one is what you renamed. Reading `rename` before the click is the whole fix; it
     * costs no control and no second meaning. */
    const renaming = this.on !== null && this.on !== this.nameIn.value.trim()
                     && Boolean(this.nameIn.value.trim());
    this.saveBtn.textContent = this.armed === "save" ? "overwrite?" : (renaming ? "rename" : "save");
    this.saveBtn.title = renaming
      ? `Renames ${this.on} to what is in the field, keeping one direction rather than two. `
        + "Anything you changed in the box is kept with it."
      : "Keeps this direction under the name above so you can pick it in any graph on this "
        + "ComfyUI. You do not need to save: what is in the box already works. Saving is only so "
        + "you can use it again.";
    this.saveBtn.classList.toggle("oh3d-armed", this.armed === "save");
    this.forgetBtn.textContent = this.armed === "forget" ? "delete?" : "forget";
    this.forgetBtn.classList.toggle("oh3d-armed", this.armed === "forget");
    // `forget` only exists while there is something for it to act on, so it is never a button whose
    // meaning you have to work out from a disabled state.
    this.forgetBtn.style.display = this.on === null ? "none" : "";
  }

  renderList() {
    this.list.replaceChildren();
    this.list.classList.toggle("oh3d-open", Boolean(this.listOpen));
    if (!this.listOpen) return;
    /* Anchored under the control it belongs to, and given only the room below it. A fixed offset
     * was wrong twice over: it floated over the panel's own lead paragraph, so a click meant to
     * dismiss the list landed on a row instead, and at the node's minimum height it ran past the
     * bottom of the panel where `overflow:hidden` simply cut it off. Both are arithmetic the
     * browser already knows, so ask it rather than guessing. */
    const top = this.pickRow.offsetTop + this.pickRow.offsetHeight + 4;
    this.list.style.top = `${top}px`;
    this.list.style.maxHeight = `${Math.max(60, this.root.clientHeight - top - 10)}px`;
    const armed = (name) => this.armed === `pick:${name}`;
    const row = (name, label, extra) => el("div", {
      class: "oh3d-lrow" + (extra || "") + (this.on === name ? " oh3d-lon" : "")
             + (armed(name) ? " oh3d-larm" : ""),
      // The row IS the answer to "did that do anything": it changes its words where the pointer
      // already is, rather than only printing a sentence at the far end of the panel.
      textContent: armed(name) ? `${label}: this replaces what you wrote. Click again.` : label,
      onclick: () => this.choose(name),
    });
    this.list.append(row("", "no director", " oh3d-lquiet"));
    for (const n of this.saved) this.list.append(row(n, n));
    if (!this.saved.length) {
      this.list.append(el("div", { class: "oh3d-lnote", textContent: this.libraryNote
        || "Nothing saved yet. Write a direction, give it a name, and press save." }));
    }
  }


  renderCount() {
    const n = this.notesIn.value.length;
    const over = n > MAX_NOTES;
    // The limit is only named once it is in the way. Under it, a count is a count.
    this.count.textContent = n === 0 ? "nothing written yet"
      : over ? `${n.toLocaleString()} of ${MAX_NOTES.toLocaleString()} characters`
      : `${n.toLocaleString()} characters`;
    this.count.classList.toggle("oh3d-bad", over);
    // `h3ir/director.py` REFUSES this at intake rather than trimming it, so the sentence says a
    // hard stop. It used to say the direction would crowd out the request, which describes a
    // degraded compile and would have somebody queue and wait to find out otherwise.
    if (over) this.say(`Too long to run. Trim it to ${MAX_NOTES.toLocaleString()} characters.`, true);
  }

  renderMoves() {
    this.moves.replaceChildren();
    // Emptied AND hidden: the list floats over the writing, so an empty box with a border and a
    // background would be a sliver of panel sitting on the textarea for no reason.
    this.moves.classList.toggle("oh3d-open", Boolean(this.movesOpen));
    if (!this.movesOpen) return;
    this.moves.append(el("div", { class: "oh3d-movehint", textContent:
      "H3 knows these twenty by name. Write one into your direction and it reads as that move; any "
      + "other wording works less well. How hard it gets played comes from the invention setting "
      + "on the Main node." }));
    for (const m of CAMERA_MOVES) this.moves.append(el("span", { class: "oh3d-move", textContent: m }));
  }

  render() {
    const s = this.state();
    this.nameIn.value = String(s.name || "");
    this.notesIn.value = String(s.notes || "");
    // Repainting from the field is the one case where nothing was chosen: a workflow just loaded,
    // or the node was configured. What the graph carries is words, never a name pointing into this
    // store, so nothing here is editing a stored direction until somebody chooses or saves one.
    this.on = null;
    this.listOpen = false;
    this.renderControls();
    this.renderCount();
    this.renderMoves();
    this.renderList();
    if (this.libraryNote && !this.msg.textContent) this.say(this.libraryNote, true);
    // The list is not read yet on the very first render; `refreshLibrary` reconciles again once it
    // is, so both orders end up knowing what the box is holding.
    this.reconcile();
  }
}

const CSS = `
.oh3d-panel{font-family:system-ui,sans-serif;color:#f3efe6;font-size:11px;
  background:#0a0a0d;border:1px solid rgba(243,239,230,.12);border-radius:8px;padding:8px;
  display:flex;flex-direction:column;gap:6px;box-sizing:border-box;position:relative;
  width:100%;height:100%;min-height:0;overflow:hidden;}
.oh3d-panel *{box-sizing:border-box;min-width:0;}
.oh3d-top{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;overflow:hidden;}
.oh3d-title{flex:0 0 auto;font-size:11px;color:#f3efe6;}
.oh3d-msg{flex:1;min-width:0;font-size:10px;color:rgba(243,239,230,.56);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;text-align:right;}
.oh3d-msg.oh3d-bad{color:#f07070;}
.oh3d-lead{flex:0 0 auto;font-size:10px;line-height:1.45;color:rgba(243,239,230,.38);}
/* The picker and the two buttons. The row dresses as a native ComfyUI widget for the same reason
   the media tray's role picker does: the owner has already learned what a dropdown on one of these
   panels looks like, and a second dialect would be a second thing to learn. */
.oh3d-row{flex:0 0 auto;display:flex;align-items:center;gap:5px;overflow:hidden;}
.oh3d-row .oh3d-wrow{flex:1;min-width:0;}
.oh3d-caret{flex:0 0 auto;color:rgba(243,239,230,.56);font-size:10px;line-height:1;cursor:pointer;
  padding:2px 0 2px 6px;user-select:none;}
.oh3d-caret:hover{color:#eb8219;}
/* The list floats, for the same reason the camera list does: it is a disclosure with a content
   height of its own, and a node the user has dragged small must not decide how much of it is
   readable. It closes on the next click anywhere else in the panel. */
.oh3d-list{display:none;position:absolute;left:8px;right:8px;z-index:3;
  flex-direction:column;overflow:auto;padding:4px;
  border-radius:6px;background:#0a0a0d;border:1px solid rgba(243,239,230,.22);
  box-shadow:0 10px 24px rgba(0,0,0,.6);}
.oh3d-list.oh3d-open{display:flex;}
.oh3d-lrow{flex:0 0 auto;padding:3px 8px;border-radius:4px;color:rgba(243,239,230,.80);
  font-size:11px;line-height:1.5;cursor:pointer;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;user-select:none;}
.oh3d-lrow:hover{background:rgba(243,239,230,.08);color:#f3efe6;}
.oh3d-lquiet{color:rgba(243,239,230,.38);}
.oh3d-lon{color:#eb8219;}
/* Written against hover as well, because the pointer is ON the row that is asking and the hover
   rule is the more specific of the two: without this the question rendered in the ordinary hover
   grey and looked like the row had merely been moused over. */
.oh3d-lrow.oh3d-larm,.oh3d-lrow.oh3d-larm:hover{color:#eb8219;background:rgba(235,130,25,.22);
  white-space:normal;}
.oh3d-lnote{flex:0 0 auto;padding:3px 8px;font-size:10px;line-height:1.4;
  color:rgba(243,239,230,.38);white-space:normal;}
.oh3d-btn{flex:0 0 auto;border:1px solid rgba(243,239,230,.22);border-radius:11px;background:#101016;
  color:rgba(243,239,230,.80);font-size:10px;line-height:1.9;padding:0 10px;cursor:pointer;
  white-space:nowrap;user-select:none;}
.oh3d-btn:hover{border-color:rgba(243,239,230,.56);color:#f3efe6;}
.oh3d-quiet{color:rgba(243,239,230,.38);}
/* Armed: one more click and something you cannot get back is gone. The same orange the rest of the
   pack accents with, so it reads as this pack asking rather than as an error. */
.oh3d-armed{border-color:#eb8219;color:#eb8219;background:rgba(235,130,25,.20);}
.oh3d-wrow{flex:0 0 auto;display:flex;align-items:center;gap:6px;
  background:var(--oh3-wbg);border:1px solid var(--oh3-wline);border-radius:12px;
  padding:2px 9px;overflow:hidden;}
.oh3d-wlabel{flex:0 0 auto;font-size:10px;color:var(--oh3-wmuted);white-space:nowrap;}
.oh3d-nlabel{flex:0 0 auto;display:flex;flex-wrap:wrap;align-items:baseline;gap:0 8px;
  font-size:10px;color:rgba(243,239,230,.38);margin-bottom:-2px;}
/* Quieter than the label it sits beside, and it wraps under it rather than truncating: this is the
   answer to "does what I just typed count", so it may never end in an ellipsis. */
.oh3d-nnote{color:rgba(243,239,230,.28);}
.oh3d-wrow .oh3d-in{flex:1;min-width:0;background:none;border:0;padding:2px 0;font-size:11px;
  font-family:inherit;color:var(--oh3-wtext);outline:none;}
/* A real flex-basis, not 0, and the moves list below shrinks with it. "flex:1" means "1 1 0%", and
   shrinking is weighted by the basis, so a basis of zero means this box never gives room back. At
   the size the node opens at that costs nothing and both spellings render identically -- which is
   how it nearly shipped. Measured with the node dragged to its minimum and the moves list open:
   with basis 0 the panel's content is 340px inside a 266px box and 74px of it is clipped away by
   overflow:hidden; with a real basis it is 264px and nothing is cut. */
.oh3d-notes{flex:1 1 90px;min-height:48px;width:100%;resize:none;background:#101016;
  border:1px solid rgba(243,239,230,.22);border-radius:6px;color:#f3efe6;
  font-family:inherit;font-size:11px;line-height:1.5;padding:7px 8px;outline:none;}
.oh3d-notes:focus{border-color:rgba(243,239,230,.38);}
.oh3d-notes::placeholder{color:rgba(243,239,230,.28);}
.oh3d-foot{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;overflow:hidden;}
.oh3d-count{flex:1;min-width:0;font-family:ui-monospace,monospace;font-size:9px;
  color:rgba(243,239,230,.38);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.oh3d-count.oh3d-bad{color:#f07070;}
.oh3d-link{flex:0 0 auto;font-size:9px;color:rgba(243,239,230,.38);cursor:pointer;
  border-bottom:1px dotted rgba(243,239,230,.28);user-select:none;}
.oh3d-link:hover{color:#eb8219;border-bottom-color:#eb8219;}
/* The camera list floats over the writing rather than competing with it for the node's height.
   Twenty fixed names have exactly one right height, so there was nothing to negotiate, and as a
   flex sibling it lost that negotiation twice. Measured: at the size the node opens at it was 7px
   short of its own last row, and dragged to the node's own minimum it collapsed to 36px and showed
   one row of names sliced through the middle with the other fourteen unreachable. Floating costs
   the textarea nothing at any node size, and it is a disclosure somebody opened deliberately and
   closes with the same click. */
.oh3d-moves{display:none;position:absolute;left:8px;right:8px;bottom:24px;z-index:2;
  flex-wrap:wrap;gap:3px;padding:6px;border-radius:6px;background:#0a0a0d;
  border:1px solid rgba(243,239,230,.22);box-shadow:0 -8px 20px rgba(0,0,0,.6);
  max-height:calc(100% - 34px);overflow:auto;}
.oh3d-moves.oh3d-open{display:flex;}
.oh3d-movehint{flex:0 0 100%;font-size:9px;line-height:1.4;color:rgba(243,239,230,.38);}
.oh3d-move{border:1px solid rgba(243,239,230,.12);border-radius:3px;background:#101016;
  color:rgba(243,239,230,.56);font-size:9px;line-height:1.6;padding:0 4px;
  font-family:ui-monospace,monospace;white-space:nowrap;}
`;

app.registerExtension({
  name: "openh3ir.director",
  init() {
    // The name row dresses as a native ComfyUI widget, and the surest way to match the theme is to
    // ask it: LiteGraph carries the widget colors the canvas actually draws with.
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
      const state = (this.widgets || []).find((w) => w.name === "profile");
      if (!state) return r;
      state.computeSize = () => [0, -4];
      state.hidden = true;
      if (state.options) state.options.hidden = true;
      const panel = new Panel(this, state);
      this._oh3Director = panel;
      // Unlike the media tray this node IS resizable, because its one field is prose somebody may
      // want more room to read. The tray pins itself because a nine-cell grid negotiating for space
      // is what painted rows outside the node; a single column with one growing child is the case
      // that survives being resized, and the minimums below are what stop it collapsing.
      const w = this.addDOMWidget("oh3d_panel", "div", panel.root, { serialize: false });
      /* The board has no width of its own: it is the node's, whatever the node has been dragged to.
       *
       * Saying so is load-bearing rather than tidy. The frontend writes a `width` onto every widget
       * from a node layout pass each time a value changes, and for a full-bleed DOM board that
       * number is wrong. Measured: choosing a director set it to 238 on a node that was still 480
       * wide, the wrapper followed it down to 218px, and the name field -- the one thing this
       * control is named for -- was squeezed to eleven pixels, clipping `Denis Villeneuve` to `De`.
       * It never recovered, at any node size. Unset is the state the widget starts in and the state
       * that renders correctly, so this keeps it there and ignores the writes. */
      Object.defineProperty(w, "width", { get: () => null, set: () => {}, configurable: true });
      w.computeSize = (width) => [width || NODE_W,
                                  Math.max(MIN_H, (this.size?.[1] || PANEL_H + NODE_H_EXTRA))
                                  - NODE_H_EXTRA];
      this.size = [NODE_W, PANEL_H + NODE_H_EXTRA];
      requestAnimationFrame(() => panel.render());
      return r;
    };
    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      try {
        size[0] = Math.max(MIN_W, size[0]);
        size[1] = Math.max(MIN_H + NODE_H_EXTRA, size[1]);
      } catch (e) { /* leave the size alone */ }
      return onResize?.apply(this, arguments);
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      this._oh3Director?.render();
      return r;
    };
  },
});
