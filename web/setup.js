/* OpenH3-IR Setup: the panel.
 *
 * The node holds two things that have nothing to do with each other. A language model somewhere on
 * a network, which writes the brief. Five files on this machine's disk, which render it. As a flat
 * list of widgets nothing said which was which, and the address sat directly above `ref2va` looking
 * like its neighbour. This panel says it: two named groups, each with a quiet line under its
 * heading, and each reporting on its own line inside itself.
 *
 * Everything here is rendering. The node's real state is the ten widgets it already had, and this
 * is an editor for them: delete this file and the node still works, still API-drives, and still
 * restores from a saved workflow, exactly as the media tray and the Director do. The five file
 * pickers are still ComfyUI combo widgets underneath, hidden and driven from a dressed `<select>`,
 * so ComfyUI keeps validating those five values and the widget order never moves.
 *
 * **What this panel adds that a form cannot: it answers back.** The address is the one thing here
 * you cannot pick from a list, and it is the first thing a new user has to get right. So the field
 * takes any address, the caret beside it offers the four programs people actually run and checks
 * each one as the list opens, and the test button reaches the address, lists what it serves, and
 * finds out whether the model it landed on can read a picture.
 *
 * **Every check runs where the compiler runs.** The three routes in `web_api.py` call the
 * compiler's own client from ComfyUI's Python, off the event loop. A fetch straight from this page
 * would test a different machine, hit cross-origin rules the compiler never hits, need the
 * credential in the page, and on a ComfyUI reached over the network it would test the browser's own
 * machine instead. A green light from that proves nothing.
 *
 * **The credential is the one thing here that is not a widget value.** Widget values are written
 * into the saved workflow and into the graph inside every rendered video, and people share
 * workflows by dropping a picture into a chat. The key goes into ComfyUI's own per-user folder
 * instead, beside the Director's saved directions, and the routes read it from there themselves.
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const VERSION = "setup v1";
console.log("[OpenH3-IR]", VERSION);
const NODE = "OpenH3IRSetup";
const NODE_W = 520;
const MIN_W = 430;
/* One height, at every width, and the panel never negotiates for it.
 *
 * That works because nothing here reflows. Every quiet line is pinned to the number of rows it needs
 * at 430, the narrowest the node goes, so a wider panel puts the spare row under its own paragraph
 * rather than changing the height. The two report lines are boxes of a fixed number of rows for the
 * same reason, and they are where the room that used to sit above the headings went.
 *
 * Two drafts were wrong before this one, and both are worth knowing. The first split the spare
 * pixels above the two headings, which reads as a hole rather than as air: a heading belongs to the
 * rows under it, and space above one pushes it away from what it heads. The second let the height
 * follow the content, which is tight at every width and makes the node jump when a corner is
 * dragged.
 *
 * The number is measured on the canvas, not reasoned from a table of font metrics. With everything
 * pinned the content comes to 548 at 410, 430, 460, 500 and 520 alike, and no child of the board
 * differs between the narrow end and the wide one. The widget is asked for 16 more than that,
 * because the frontend's own wrapper keeps that much of whatever a DOM widget is given. */
const PANEL_H = 564;
const NODE_H_EXTRA = 58;

/* Where what belongs to THIS ComfyUI lives, through the `/userdata` routes ComfyUI already serves,
 * beside the Director's saved directions. Neither file ever reaches a workflow. */
const SEEN = "openh3ir/llm/seen.json";
const KEYS = "openh3ir/llm/keys.json";

/* The shape of an endpoint address, drawn in the field as an example.
 *
 * NOT a proposal. A port is configurable, so a list of ports is a list of guesses and every one of
 * them is confidently wrong for anybody who changed one. This is the shape: a scheme, a host, a
 * port, and the /v1 ending this pack refuses a URL without. It is quoted rather than invented -- it
 * is the value `compiler.resolve_llm_url` names in its own docstring as the compiler's default. */
const EXAMPLE = "http://127.0.0.1:8000/v1";

/* Where the OpenH3-IR service listens when somebody runs one, drawn as an example in the bottom
 * row's own field. A different port and no /v1, which is most of what keeps the two apart. */
const SERVICE_EXAMPLE = "http://another-machine:8420";

/* The five file rows: the widget each one drives, the word on its label, the folder its list comes
 * from, and its tooltip. The order is the schema's order, which is the order every saved workflow
 * depends on. */
const FILES = [
  { w: "reference_model", label: "ref2va", folder: "diffusion_models",
    tip: "H3's checkpoint for reference jobs and text jobs. A .gguf file loads through Unet Loader "
       + "(GGUF). A .safetensors file loads the way Load Diffusion Model loads one." },
  { w: "frames_model", label: "fl2va", folder: "diffusion_models",
    tip: "H3's checkpoint for first frame and last frame jobs. The slots you filled decide which of "
       + "the two a job uses. The report names the one it loaded." },
  { w: "text_encoder", label: "clip", folder: "text_encoders",
    tip: "The Qwen3-VL encoder H3 was trained against. It is the same file a Load CLIP node takes." },
  { w: "video_vae", label: "vae", folder: "vae",
    tip: "H3's video VAE. The decode uses it as well." },
  { w: "audio_vae", label: "audio vae", folder: "vae",
    tip: "H3's audio VAE. It is a different file from the video VAE. A silent piece needs it too, "
       + "because H3 writes picture and sound together." },
];

/* The two H3 checkpoint families, and the one thing their filenames settle. Read only where the
 * name decides the question: a name carrying the other family's word and not this one's is
 * evidence, a name carrying neither is not, and a name carrying both cannot be read.
 *
 * `h3ir_client.family_warning` is the same rule in the pack's Python, where it reaches the report
 * after a render. Saying it when the file is picked costs one comparison and saves the render.
 * tests/test_setup_panel.py fails when the two copies drift apart. */
const FAMILY = { reference_model: "ref2va", frames_model: "fl2va" };

/* The five states of the chip beside the model. `no answer` is the third answer the vision route
 * gives, and it is not a failure: the model was never asked, so nothing is known. It is grey. */
const CHIP = {
  none: { text: "not checked", cls: "" },
  checking: { text: "checking", cls: "" },
  on: { text: "vision on", cls: "oh3s-see" },
  off: { text: "vision off", cls: "oh3s-blind" },
  unknown: { text: "no answer", cls: "" },
};

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

/** An address with no trailing slash and nothing else touched. The one normalisation both halves
 *  agree on: the panel saves a key under it, the node sends it, and `compiler.endpoint_key` looks
 *  it up by the same string. */
function tidy(url) { return String(url || "").trim().replace(/\/+$/, ""); }

/** The host and port a message names, taken from the address rather than restated by hand. */
function where(url) {
  try {
    const u = new URL(tidy(url));
    return u.port ? `${u.hostname}:${u.port}` : u.hostname;
  } catch { return tidy(url); }
}

function host(url) {
  try { return new URL(tidy(url)).hostname; } catch { return tidy(url); }
}

/** Today, as a person writes it. Recorded with a vision pass so the chip's tooltip can say when. */
function today() { return new Date().toISOString().slice(0, 10); }

class Panel {
  constructor(node, widgets) {
    this.node = node;
    this.w = widgets;
    /* True once this node has been configured out of a saved workflow. It is what stops the
     * one-time address check from firing: that node already has an address, and opening ten
     * workflows must not fire forty requests. */
    this.configured = false;
    /* Which file rows somebody has picked in. A node that came out of a saved workflow counts as
     * having all five picked: those values were saved deliberately. A node built by
     * `onNodeCreated` with no `onConfigure` after it is brand new, and ComfyUI has filled its five
     * combos with the first file in each folder -- values nobody chose.
     *
     * **No file name is read to decide any of this**, so the rule that this node never picks a file
     * from its name is untouched. It is knowable for certain and for free from how the node was
     * built. */
    this.touched = new Set();

    this.compiler = null;      // what GET /openh3ir/compiler answered, or null before it has
    this.report = null;        // the last models report, for the model list and the key row
    this.chip = "none";
    this.chipWhen = "";        // the date a remembered pass was recorded
    this.chipWhy = "";         // why nothing is known, when nothing is
    this.busy = null;          // the run token of a test in flight
    this.slow = false;         // three seconds have passed, so the button offers to stop
    this.open = null;          // "address" | "model" | "where" | "timeout" | "dtype" | null
    this.keyEditing = false;
    this.savedKey = "";        // the credential this ComfyUI holds for the address in the field
    this.armed = null;         // a second click would delete something

    // ------------------------------------------------------------------ the head
    this.root = el("div", { class: "oh3s-panel" });
    this.root.append(
      el("div", { class: "oh3s-title", textContent: "Setup" }),
      el("div", { class: "oh3s-lead", textContent:
        "Point this node at the language model that writes your brief. Pick the five H3 files that "
        + "render it." }));

    // ------------------------------------------------------- group one: the language model
    this.llmLead = el("div", { class: "oh3s-seclead" });
    this.root.append(el("div", { class: "oh3s-sec", textContent: "your language model" }),
                     this.llmLead);

    this.addrIn = el("input", { class: "oh3s-in oh3s-mono", spellcheck: false,
      placeholder: EXAMPLE,
      title: "Where your language model listens. Write it in full and end it with /v1. vLLM, "
           + "llama.cpp, LM Studio, Ollama and paid APIs all work. It can be another machine." });
    // Typing puts down whatever the line was reporting: it describes what just happened, and the
    // moment somebody starts typing it is describing the past.
    this.addrIn.addEventListener("input", () => { this.say(""); this.commitAddress(); });
    this.addrIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this.test(); }
    });
    /* A visible label, drawn to the left, that stays there while you type. The grey address in the
     * field is an EXAMPLE, not a label: a placeholder is gone at the first keystroke and the field
     * is anonymous from then on. That is the standing rule for every panel this pack draws.
     *
     * There is no caret. It existed only to open a list of four addresses this panel guessed at,
     * and a port is configurable, so a list of ports is a list of guesses that is confidently wrong
     * for anybody who changed one.
     *
     * The label is `endpoint` rather than `address`, because that is the word this panel already
     * uses in every message it prints. It is not "openai endpoint": somebody running Ollama on
     * their own machine reads that as needing an account with OpenAI, and that failure stops them
     * cold. The protocol fact lives in the group's quiet line instead, where it is a fact about a
     * protocol rather than a claim about who you buy from. */
    this.addrRow = el("div", { class: "oh3s-wrow" },
      el("span", { class: "oh3s-wlabel", textContent: "endpoint" }), this.addrIn);

    this.modelIn = el("input", { class: "oh3s-in oh3s-mono", spellcheck: false,
      placeholder: "nothing picked yet",
      title: "Which model on that server writes your brief. Type a name, or open the list of what "
           + "the server reports." });
    this.modelIn.addEventListener("input", () => {
      this.say("");
      this.w.llm_model.value = this.modelIn.value.trim();
      // Typing a name never fires the check. It costs a request to the model, and every keystroke
      // would spend one on a name that is half written.
      this.chip = "none";
      this.chipWhen = "";
      this.node.setDirtyCanvas?.(true, true);
      this.renderModel();
      this.renderList();
    });
    this.modelIn.addEventListener("keydown", (e) => this.modelKey(e));
    this.chipEl = el("span", { class: "oh3s-chip" });
    this.modelCaret = el("span", { class: "oh3s-caret", textContent: "▾",
      title: "What this server reports. Type in the field to narrow the list.",
      onclick: (e) => { e.stopPropagation(); this.toggle("model"); } });
    this.modelRow = el("div", { class: "oh3s-wrow" },
      el("span", { class: "oh3s-wlabel", textContent: "model" }), this.modelIn, this.chipEl,
      this.modelCaret);

    this.msg = el("span", { class: "oh3s-msg" });
    this.testBtn = el("span", { class: "oh3s-btn oh3s-wide", textContent: "test",
      onclick: () => (this.busy ? this.stop() : this.test()) });
    this.sayRow = el("div", { class: "oh3s-sayrow" }, this.msg, this.testBtn);

    // the credential row, always present and always the same height
    this.keyVal = el("span", { class: "oh3s-kval" });
    this.keyIn = el("input", { class: "oh3s-in oh3s-mono", type: "password", spellcheck: false,
      placeholder: "paste the key" });
    this.keyIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this.saveKey(); }
      if (e.key === "Escape") { e.preventDefault(); this.keyEditing = false; this.renderKey(); }
    });
    this.keyBtns = el("span", { class: "oh3s-kbtns" });
    this.keyRow = el("div", { class: "oh3s-wrow" }, this.keyVal, this.keyIn, this.keyBtns);
    const keyLabel = el("div", { class: "oh3s-klabel" },
      el("span", { textContent: "api key" }),
      el("span", { class: "oh3s-knote", textContent:
        "Only if your endpoint asks for one. It never goes into the workflow." }));
    this.keyBlock = el("div", { class: "oh3s-krow" }, keyLabel, this.keyRow);
    this.keyRow.title =
      "The key your endpoint wants, sent as an Authorization Bearer header. Most servers on your "
      + "own machine want none. A hosted API wants one, and so does vLLM started with --api-key. It "
      + "stays in this ComfyUI's user folder, so it never goes into a workflow you share.";

    this.llm = el("div", { class: "oh3s-group" },
      this.addrRow, this.modelRow, this.sayRow, this.keyBlock);
    this.root.append(this.llm);

    // ---------------------------------------------------------- group two: the five files
    this.root.append(
      el("div", { class: "oh3s-sec", textContent: "the five MiniMax H3 files" }),
      el("div", { class: "oh3s-seclead oh3s-one", textContent:
        "Pick the five H3 files. They come from your ComfyUI's own model folders." }));

    this.picks = {};
    for (const f of FILES) {
      const sel = el("select", { class: "oh3s-in oh3s-mono", title: f.tip });
      sel.addEventListener("change", () => {
        this.w[f.w].value = sel.value;
        // Picked in, and it stays picked in. From here the row is the ordinary colour and both file
        // warnings are allowed to speak about it.
        this.touched.add(f.w);
        this.node.setDirtyCanvas?.(true, true);
        this.renderFiles();
      });
      /* A real `<select>` dressed as one of these rows, so it keeps the browser's own dropdown --
       * which the node cannot clip -- and keyboard type-ahead for free.
       *
       * The caret is drawn rather than the browser's, and it takes no clicks: two different arrows
       * on one panel is two dialects on one control. `appearance:none` takes the native one away and
       * the span sits over the select with `pointer-events:none`, so a click that lands on the arrow
       * still opens the list under it. */
      const wrap = el("span", { class: "oh3s-selwrap" }, sel,
        el("span", { class: "oh3s-caret oh3s-static", textContent: "▾" }));
      const row = el("div", { class: "oh3s-wrow", title: f.tip },
        el("span", { class: "oh3s-wlabel", textContent: f.label }), wrap);
      this.picks[f.w] = { sel, row };
      this.root.append(row);
    }
    this.fileMsg = el("span", { class: "oh3s-msg" });
    this.root.append(el("div", { class: "oh3s-sayrow oh3s-files" }, this.fileMsg));

    // ------------------------------------------------------------------ the bottom row
    this.footWhere = this.footItem("OpenH3-IR", "where",
      "OpenH3-IR turns your prompt into the brief H3 renders from. It runs inside ComfyUI unless "
      + "you point this at an OpenH3-IR service somewhere else.");
    this.footTimeout = this.footItem("give up after", "timeout",
      "Writing a brief is one call to your language model. This is as slow as that model is.");
    this.footDtype = this.footItem("load weights as", "dtype",
      "The same setting a UNET loader has. Leave it alone unless you are short of VRAM. A GGUF "
      + "checkpoint carries its own quantisation and ignores this. The report says when it was "
      + "ignored.");
    this.root.append(el("div", { class: "oh3s-foot" },
      this.footWhere.root, this.footTimeout.root, this.footDtype.root));

    /* Everything that opens floats over the panel, so the height never changes and nothing fights
     * for room. Both lists and all three bottom controls share one element: only one can be open. */
    this.list = el("div", { class: "oh3s-list" });
    this.root.append(this.list);

    /* Anything the pointer touches that is not the open list, and not the control that opened it,
     * closes it and puts down anything that was armed. Both exclusions are the Director's, and both
     * are measured there: without the list, choosing a row closed the list before the row's own
     * click ran; without the opener, the caret closed and immediately reopened it. */
    this.root.addEventListener("pointerdown", (e) => {
      const inList = Boolean(e.target.closest?.(".oh3s-list"));
      const onOpener = Boolean(e.target.closest?.(".oh3s-caret, .oh3s-fi"));
      if (this.armed && !inList) { this.armed = null; this.renderKey(); }
      if (this.open && !inList && !onOpener) { this.open = null; this.renderList(); }
    });

    this.render();
    this.askCompiler();
    this.readKey();
  }

  footItem(label, which, tip) {
    const value = el("span");
    const root = el("span", { class: "oh3s-fi", title: tip,
      onclick: (e) => { e.stopPropagation(); this.toggle(which); } },
      el("span", { textContent: label }), value);
    return { root, value };
  }

  // ------------------------------------------------------------------ what the node holds

  address() { return tidy(this.w.llm_url.value); }
  modelName() { return String(this.w.llm_model.value || "").trim(); }
  elsewhere() { return tidy(this.w.server.value); }

  commitAddress() {
    this.w.llm_url.value = tidy(this.addrIn.value);
    this.node.setDirtyCanvas?.(true, true);
    // A different endpoint has a different credential and a different verdict about vision.
    this.savedKey = "";
    this.chip = "none";
    this.chipWhen = "";
    this.readKey();
    this.renderKey();
    this.renderModel();
  }

  /** Has somebody chosen in this row, as opposed to ComfyUI having filled it in?
   *
   *  A configured node answers yes for all five: a saved workflow's values were saved on purpose.
   *  A brand new node answers no until somebody picks. */
  chosen(name) { return this.configured || this.touched.has(name); }

  /** Quoted material, short enough to fit the box it is drawn in, ending in an ellipsis.
   *
   *  The ONLY thing this panel ever shortens. Every sentence it writes itself fits the report box
   *  whole; what has no length limit is somebody else's words -- the model's own answer, which the
   *  route caps at 300 characters. That is evidence rather than an instruction, so it is trimmed
   *  here and kept whole on the tooltip. An instruction is never cut. */
  static quote(said, room) {
    const text = String(said || "").trim();
    return text.length <= room ? text : text.slice(0, room - 1).trimEnd() + "\u2026";
  }

  /** The one line the language model half reports on. It is ONE row and it truncates, so the thing
   *  to do goes at the front and the reassurance after it. The `title` carries it whole.
   *
   *  **Something that JUST HAPPENED, which is why it sticks.** A resting line describes the state
   *  and is re-derived on every render; this one describes an event and must survive the renders
   *  that follow it, or the answer to the button somebody just pressed would be painted over by a
   *  description of the state it produced. Typing puts it down again, which is the Director's rule:
   *  the moment somebody starts typing, a line about what just happened is a line about the past.
   */
  say(text, tone = "") {
    this.sticky = Boolean(text);
    this.write_msg(text, tone);
  }

  write_msg(text, tone) {
    this.msg.textContent = text || "";
    this.msg.title = text || "";
    this.msg.className = "oh3s-msg" + (tone ? ` oh3s-${tone}` : "");
  }

  sayFiles(text, tone = "") {
    this.fileMsg.textContent = text || "";
    this.fileMsg.title = text || "";
    this.fileMsg.className = "oh3s-msg" + (tone ? ` oh3s-${tone}` : "");
  }

  // ------------------------------------------------------------------ the compiler

  /** Is there a compiler in this ComfyUI at all, which build, and what would the environment give.
   *  No network, one import. It decides whether the test button works and fills the bottom row. */
  async askCompiler() {
    try {
      const r = await api.fetchApi("/openh3ir/compiler");
      this.compiler = r.ok ? await r.json() : { state: "routes" };
    } catch { this.compiler = { state: "routes" }; }
    this.render();
  }

  compilerTrouble() {
    // Never said to a graph that compiles somewhere else. That machine needs nothing installed
    // here, and telling this person to install something is advice about a machine they are not
    // using.
    if (this.elsewhere() || !this.compiler) return "";
    if (this.compiler.state === "absent") {
      return "open-h3-ir is not installed in ComfyUI's Python. Nothing here can compile. Install "
             + "it, or install this pack again.";
    }
    if (this.compiler.state === "broken") {
      return "open-h3-ir is installed in ComfyUI's Python and it will not load. Nothing here can "
             + "compile. Install it again.";
    }
    if (this.compiler.state === "routes") {
      return "This ComfyUI did not answer the test. Restart ComfyUI.";
    }
    return "";
  }

  // ------------------------------------------------------- the four common addresses

  // ------------------------------------------------------------------ the test

  stop() {
    this.busy = null;
    this.slow = false;
    this.say("Stopped. Nothing changed.");
    this.render();
  }

  /** One press, in order. Every step either says what it did or names what failed. */
  async test() {
    if (this.busy) return;
    if (this.compilerTrouble()) return;

    let url = tidy(this.addrIn.value);
    if (!url) {
      this.say("Type the address of your language model first.", "bad");
      return;
    }
    let fixed = "";
    if (!/^https?:\/\//i.test(url)) {
      // Fixed out loud, never in silence, the way the media tray turns a space in a name into a
      // dash. Without it `setup_bundle` refuses the graph at queue time for the same reason.
      url = `http://${url}`;
      fixed = "The address now starts with http://.";
      this.addrIn.value = url;
      this.commitAddress();
    }

    const run = {};
    this.busy = run;
    this.slow = false;
    this.say(fixed || `Asking ${where(url)}.`);
    this.render();
    const slowly = setTimeout(() => {
      if (this.busy !== run) return;
      this.slow = true;
      this.say("Still asking. A server that loads a model can take a minute.");
      this.render();
    }, 3000);

    try {
      let got = await this.ask(url);
      if (!got.ok && !/\/v1$/.test(url)) {
        // Not a guess. It was tried as typed, it failed, and this is the second try. The field only
        // moves when the second one answers.
        const withV1 = `${url}/v1`;
        const again = await this.ask(withV1);
        if (again.ok) {
          url = withV1;
          got = again;
          this.addrIn.value = url;
          this.commitAddress();
          fixed = "That address answers at /v1. The field now shows the full address.";
        }
      }
      if (this.busy !== run) return;
      this.report = got;
      this.savedKey = await this.readKey();
      if (!got.ok) { this.failed(url, got); return; }
      if (fixed) this.say(fixed);
      await this.afterList(url, got, run);
    } catch (e) {
      if (this.busy === run) this.say(`The test did not run. (${e})`, "bad");
    } finally {
      clearTimeout(slowly);
      if (this.busy === run) { this.busy = null; this.slow = false; }
      this.render();
    }
  }

  async ask(url) {
    const r = await api.fetchApi("/openh3ir/llm/models", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, timeout: 20 }) });
    if (!r.ok) return { ok: false, reason: `This ComfyUI answered ${r.status}.` };
    return r.json();
  }

  /** Nothing came back. Each of these is a different problem with a different fix, so each one gets
   *  its own sentence. The status the compiler's probe recorded is what tells them apart. */
  failed(url, got) {
    const tried = got.tried || [];
    const status = tried.map((t) => t.status).find((s) => s);
    const said = String(tried.map((t) => t.answered).join(" ") || "");
    if (status === 401 || status === 403) {
      if (got.credential) {
        this.say(`That address refused the key. It said: ${Panel.quote(got.reason || said, 150)}`,
                 "bad");
        this.msg.title = `That address refused the key. It said: ${got.reason || said}`;
      } else {
        this.say("That address wants a key. Type one in. Then press test again.", "bad");
        this.keyEditing = true;
        this.renderKey();
        this.keyIn.focus();
      }
      return;
    }
    if (status) {
      this.say(`Something answers at ${where(url)}, and it is not a language model. Check the port `
               + "number.", "bad");
      return;
    }
    if (/getaddrinfo|Name or service not known|nodename nor servname|ENOTFOUND|11001/i.test(said)) {
      this.say(`There is no machine called ${host(url)}. Check the spelling.`, "bad");
      return;
    }
    if (/refused|ConnectError/i.test(said) && !/timeout|timed out/i.test(said)) {
      this.say(`Nothing answers at ${where(url)}. Start your language model. If it is running, `
               + "check the port number.", "bad");
      return;
    }
    this.say(`${where(url)} did not answer in 20 seconds. It can still be starting up. A firewall `
             + "can also block it.", "bad");
  }

  /** A list came back. What happens next depends on what is in the field and what is in the list. */
  async afterList(url, got, run) {
    const choices = got.choose_from || [];
    const ids = got.ids || [];
    if (!ids.length) {
      this.say("That server answers and serves no models. Load a model on it.", "bad");
      return;
    }
    if (!choices.length) {
      this.say("The server answers. It will not list its models. Type the model name in the "
               + "field.", "bad");
      return;
    }
    const set = this.modelName();
    if (!set && choices.length === 1) {
      this.write(choices[0]);
      this.say(`That server serves one model, ${choices[0]}. The field now shows it. Checking its `
               + "vision.");
      await this.look(url, choices[0], run);
      return;
    }
    if (!set) {
      const n = ids.length;
      const m = choices.length;
      this.say(n === m ? `That server serves ${m} models. Pick one from the list.`
                       : `That server lists ${n} names for ${m} models. Pick one from the list.`);
      return;
    }
    if (!choices.includes(set)) {
      // The name stays. Nothing is quietly swapped for a neighbour.
      this.say(`That server does not serve ${set} any more. Pick another one from the list.`, "bad");
      return;
    }
    await this.look(url, set, run);
  }

  write(id) {
    this.w.llm_model.value = id;
    this.modelIn.value = id;
    this.chip = "none";
    this.chipWhen = "";
    this.node.setDirtyCanvas?.(true, true);
    this.renderModel();
  }

  // ------------------------------------------------------------------ vision

  /** Send one picture and report what came back.
   *
   *  **`installed` is read before `ok`.** The route answers `installed: false` with `ok: false` when
   *  there is no compiler, and reading `ok` on its own there paints a red "vision off" about a model
   *  nobody ever asked. And it is never called with an empty model, because an empty model also
   *  answers `ok: false` and that is the same trap.
   *
   *  Three answers, not two. `null` means the model was never asked, so nothing is known, and it
   *  stays grey. That happens more often than a real no.
   */
  async look(url, id, run) {
    if (!id) return;
    this.chip = "checking";
    this.say(`Checking vision for ${id}.`);
    this.renderModel();
    let got;
    try {
      const r = await api.fetchApi("/openh3ir/llm/vision", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, model: id, timeout: 120 }) });
      got = r.ok ? await r.json() : { installed: true, ok: null, reason: `ComfyUI answered ${r.status}.` };
    } catch (e) {
      got = { installed: true, ok: null, reason: String(e) };
    }
    if (run && this.busy !== run) return;
    if (got.installed === false) {
      this.chip = "none";
      this.say(this.compilerTrouble() || String(got.reason || ""), "bad");
      this.renderModel();
      return;
    }
    if (got.ok === true) {
      this.chip = "on";
      this.chipWhen = today();
      this.chipWhy = "";
      this.remember(url, id);
      this.say(`Vision is on for ${id}. This model is ready.`, "good");
    } else if (got.ok === false) {
      this.chip = "off";
      this.chipWhen = "";
      const said = String(got.said || "").trim();
      if (/rejected a request with a picture/i.test(String(got.reason || ""))) {
        this.say(`${id} rejected a request with a picture in it, so it cannot read one. Pick one `
                 + "with a vision tower.", "bad");
      } else {
        // The model's own answer is the one thing here with no length limit, so it is the one thing
        // that is ever shortened. The whole of it stays on the tooltip.
        this.say(`${id} did not read the test picture. It said: ${Panel.quote(said, 70)}. A graph `
                 + "with pictures or clips on the Media node will not work. A prompt with an empty "
                 + "Media node still works.", "bad");
        this.msg.title = `${id} did not read the test picture. It said: ${said}`;
      }
    } else {
      // Nothing is known, so nothing is recorded and nothing is red.
      this.chip = "unknown";
      this.chipWhen = "";
      this.chipWhy = String(got.reason || "");
      const reason = this.chipWhy;
      if (/no model called/i.test(reason)) {
        this.say(`That endpoint has no model called ${id}. Nothing was asked. Check the name `
                 + "against the list.");
      } else if (/unauthorised|credential/i.test(reason)) {
        this.say(`That endpoint refused the request as unauthorised, so ${id} was never asked. It `
                 + "wants a key.");
      } else {
        this.say(`The check did not finish. Nothing is known about ${id} yet. Try again.`);
      }
    }
    this.renderModel();
  }

  // ---------------------------------------------------------- what this ComfyUI remembers

  seenKey(url, id) { return `${tidy(url)}|${id}`; }

  /** Only a PASS is written, against that address and that model name. A reopened workflow then
   *  shows a settled state with no network call at all. */
  async remember(url, id) {
    try {
      const all = await this.readJson(SEEN);
      all[this.seenKey(url, id)] = today();
      await this.writeJson(SEEN, all);
    } catch { /* a memory that cannot be written costs a check, never a queue */ }
  }

  async recall() {
    const url = this.address();
    const id = this.modelName();
    if (!url || !id || this.chip !== "none") return;
    try {
      const all = await this.readJson(SEEN);
      const when = all[this.seenKey(url, id)];
      if (!when) return;
      this.chip = "on";
      this.chipWhen = String(when);
      this.renderModel();
    } catch { /* nothing remembered is the ordinary case */ }
  }

  async readJson(path) {
    const r = await api.fetchApi(`/userdata/${encodeURIComponent(path)}`);
    if (!r.ok) return {};
    const got = await r.json();
    return (got && typeof got === "object" && !Array.isArray(got)) ? got : {};
  }

  async writeJson(path, value) {
    await api.fetchApi(`/userdata/${encodeURIComponent(path)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value, null, 2) });
  }

  // ------------------------------------------------------------------ the credential

  async readKey() {
    const url = this.address();
    if (!url) { this.savedKey = ""; this.renderKey(); return ""; }
    try {
      const all = await this.readJson(KEYS);
      this.savedKey = String(all[url] || "");
    } catch { this.savedKey = ""; }
    this.renderKey();
    return this.savedKey;
  }

  async saveKey() {
    const url = this.address();
    const key = this.keyIn.value.trim();
    if (!url || !key) { this.keyEditing = false; this.renderKey(); return; }
    const all = await this.readJson(KEYS);
    all[url] = key;
    await this.writeJson(KEYS, all);
    this.savedKey = key;
    this.keyEditing = false;
    this.keyIn.value = "";
    this.say(`The key is saved for ${host(url)}. It is not in this workflow.`);
    this.renderKey();
  }

  async forgetKey() {
    const url = this.address();
    if (this.armed !== "forget") {
      this.armed = "forget";
      this.renderKey();
      return;
    }
    this.armed = null;
    const all = await this.readJson(KEYS);
    delete all[url];
    await this.writeJson(KEYS, all);
    this.savedKey = "";
    this.say(`The key for ${host(url)} is deleted.`);
    this.renderKey();
  }

  // ------------------------------------------------------------------ opening things

  toggle(which) {
    this.open = this.open === which ? null : which;
    this.armed = null;
    this.renderList();
  }

  modelKey(e) {
    if (e.key === "Escape" && this.open === "model") {
      e.preventDefault();
      this.open = null;
      this.renderList();
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const rows = this.narrowed();
      if (rows.length) this.pick(rows[0]);
      else { this.open = null; this.renderList(); }
    }
  }

  narrowed() {
    const all = (this.report && this.report.choose_from) || [];
    const typed = this.modelIn.value.trim().toLowerCase();
    return typed ? all.filter((m) => m.toLowerCase().includes(typed)) : all;
  }

  /** A name was chosen from the list. The name goes in first, then the check runs: a failed check
   *  never undoes a pick, because somebody who knows their model better than one picture does keeps
   *  their choice. */
  pick(id) {
    this.open = null;
    this.write(id);
    this.renderList();
    this.look(this.address(), id, null);
  }

  // ------------------------------------------------------------------ rendering

  render() {
    this.addrIn.value = this.address();
    this.modelIn.value = this.modelName();
    this.renderLead();
    this.renderModel();
    this.renderSay();
    this.renderKey();
    this.renderFiles();
    this.renderFoot();
    this.renderList();
    this.recall();
  }

  renderLead() {
    const service = this.elsewhere();
    // A graph that compiles elsewhere writes with that machine's own language model, so these three
    // controls do nothing. They stand down rather than staying live and looking clickable.
    this.llm.classList.toggle("oh3s-standdown", Boolean(service));
    // The address is NOT repeated here. It has no length limit, so it cannot be pinned to a row
    // count, and it is already on the bottom row two lines below. Repeating it was duplication as
    // well as a wrapping risk.
    this.llmLead.textContent = service
      ? "Not used. This graph compiles on another machine, which has its own language model."
      : "This model writes your brief. It also reads every picture and clip on the Media node. Any "
        + "server that speaks the OpenAI API works.";
  }

  renderModel() {
    const c = CHIP[this.chip] || CHIP.none;
    this.chipEl.textContent = c.text;
    this.chipEl.className = `oh3s-chip ${c.cls}`;
    this.chipEl.title =
      this.chip === "on" ? `Checked on ${this.chipWhen}. Vision was on at that endpoint for this `
                           + "model."
      : this.chip === "unknown" ? "The check did not finish, so nothing is known either way. "
                                  + this.chipWhy
      : this.chip === "none" ? "Nothing on this ComfyUI has checked vision for this model. Press "
                               + "test."
      : "";
  }

  renderSay() {
    const trouble = this.compilerTrouble();
    // A compiler that is not there outranks everything: nothing on this half can work, and the
    // sentence says which of the two states it is and what to do.
    if (trouble) this.write_msg(trouble, "bad");
    else if (!this.sticky) this.renderResting();
    const off = Boolean(trouble) || Boolean(this.elsewhere());
    this.testBtn.textContent = this.busy ? (this.slow ? "stop" : "asking") : "test";
    this.testBtn.classList.toggle("oh3s-off", off && !this.busy);
    this.testBtn.title = off
      ? `There is no compiler in ComfyUI's Python to test with. ${trouble}`
      : "This reaches the address, lists what it serves, and checks that vision is on for that "
        + "model. It runs where the compiler runs, not in this browser.";
  }

  /** What the line says when nothing has just happened. Re-derived on every render, never left
   *  behind: a node loaded out of a saved workflow used to open still saying "Type the address of
   *  your language model", with the address sitting in the field above it.
   *
   *  The environment case is the one that has to be said before a queue. An empty field that is not
   *  really empty is the most confusing state this node has, and until the panel could say so it
   *  was a line in the report that only appeared after a run.
   */
  renderResting() {
    if (this.elsewhere()) {
      this.write_msg("Not used. This graph compiles on another machine, which has its own language "
                     + "model.", "");
      return;
    }
    const env = this.compiler && this.compiler.env_url;
    if (!this.address() && env) {
      this.write_msg(`The address field is empty. ComfyUI's environment gives ${env} instead. Type `
                     + "an address here to use a different one.", "");
      return;
    }
    this.write_msg(this.address() ? "" : "Type the address of your language model. Then press "
                                         + "test.", "");
  }

  renderKey() {
    const editing = this.keyEditing;
    this.keyIn.style.display = editing ? "" : "none";
    this.keyVal.style.display = editing ? "none" : "";
    this.keyBtns.replaceChildren();
    if (editing) {
      this.keyBtns.append(el("span", { class: "oh3s-kbtn", textContent: "keep",
        onclick: () => this.saveKey() }));
      return;
    }
    if (this.savedKey) {
      this.keyVal.textContent = `key set, ends in ${this.savedKey.slice(-4)}`;
      this.keyVal.className = "oh3s-kval";
      this.keyBtns.append(
        el("span", { class: "oh3s-kbtn", textContent: "change",
          onclick: () => { this.keyEditing = true; this.renderKey(); this.keyIn.focus(); } }),
        el("span", { class: "oh3s-kbtn" + (this.armed === "forget" ? " oh3s-armed" : ""),
          textContent: this.armed === "forget" ? "delete?" : "forget",
          onclick: () => this.forgetKey() }));
      return;
    }
    this.keyVal.textContent = "no key. That endpoint does not ask for one.";
    this.keyVal.className = "oh3s-kval oh3s-empty";
    this.keyBtns.append(el("span", { class: "oh3s-kbtn", textContent: "add",
      onclick: () => { this.keyEditing = true; this.renderKey(); this.keyIn.focus(); } }));
  }

  /** The five rows, and the two things they can now catch before a render.
   *
   *  A value that is not in the list stays as the first option, marked, and the row goes red.
   *  Rebuilding a `<select>` from a list that no longer holds the saved value silently selects the
   *  first option and silently changes the setting, which is the exact failure this pack refuses.
   */
  renderFiles() {
    const missing = [];
    const empty = [];
    for (const f of FILES) {
      const { sel, row } = this.picks[f.w];
      const options = [...(this.w[f.w].options?.values || [])];
      const value = String(this.w[f.w].value || "");
      const gone = value && !options.includes(value);
      sel.replaceChildren();
      if (!options.length && !value) {
        sel.append(el("option", { value: "", textContent: `nothing in the ${f.folder} folder` }));
        empty.push(f.folder);
      }
      if (gone) sel.append(el("option", { value, textContent: `${value} (not here)` }));
      for (const o of options) sel.append(el("option", { value: o, textContent: o }));
      sel.value = value;
      // A value ComfyUI filled in is drawn in the grey the address field uses for its example. It is
      // real and a queue will use it, so it is never hidden; it is shown as what it is, a value
      // nobody chose. Picking in the row turns it the ordinary colour for good.
      sel.classList.toggle("oh3s-untouched", !this.chosen(f.w));
      row.classList.toggle("oh3s-err", Boolean(gone) || (!options.length && !value));
      if (gone) missing.push(f);
    }
    if (empty.length) {
      this.sayFiles(`ComfyUI has no files in its ${empty[0]} folder. Put H3's files there. Then `
                    + "restart ComfyUI.", "bad");
      return;
    }
    if (missing.length === 5) {
      this.sayFiles("None of the five files are on this ComfyUI. Pick your own.", "bad");
      return;
    }
    if (missing.length > 1) {
      this.sayFiles(`${missing.length} of the five files are not on this ComfyUI: `
                    + `${missing.map((f) => f.label).join(", ")}. Pick your own.`, "bad");
      return;
    }
    if (missing.length === 1) {
      this.sayFiles(`The ${missing[0].label} file is not on this ComfyUI. Pick another file from `
                    + "the list.", "bad");
      return;
    }
    // A brand new node greeted somebody with a complaint about ComfyUI's own defaults. It says what
    // happened and what to do instead, and it is not red, because nothing is broken yet.
    if (!FILES.some((f) => this.chosen(f.w))) {
      this.sayFiles("ComfyUI filled these in. Pick your own five H3 files.");
      return;
    }
    this.sayFiles(this.fileWarning());
  }

  /** The two warnings, and only two. Both are decided from the five values alone, both name the
   *  row, and neither ever blocks anything. */
  fileWarning() {
    for (const [w, wanted] of Object.entries(FAMILY)) {
      // Never about a row nobody has picked in. A warning on a value ComfyUI chose is the panel
      // complaining to somebody about something they did not do.
      if (!this.chosen(w)) continue;
      const name = String(this.w[w].value || "").toLowerCase();
      const other = wanted === "ref2va" ? "fl2va" : "ref2va";
      // Read only where the name settles the question. A name carrying neither word is not
      // evidence, and a name carrying both cannot be read.
      if (name.includes(other) && !name.includes(wanted)) {
        return `This file name says ${other}. It is in the ${wanted} row. It will still render. `
               + "The result will be wrong, and nothing on screen will say why.";
      }
    }
    const video = String(this.w.video_vae.value || "");
    // BOTH rows, for the same reason: two untouched rows holding one file is ComfyUI's doing.
    if (this.chosen("video_vae") && this.chosen("audio_vae")
        && video && video === String(this.w.audio_vae.value || "")) {
      return "Both VAE rows hold the same file. H3 needs a different file for each one.";
    }
    return "";
  }

  renderFoot() {
    const c = this.compiler || {};
    const service = this.elsewhere();
    this.footWhere.value.textContent = service ? `runs at ${service}`
      : c.state === "ok" ? `runs in this ComfyUI, ${c.version || "?"}`
      : c.state ? "not installed here" : "";
    this.footWhere.root.classList.toggle("oh3s-bad", !service && c.state && c.state !== "ok");
    this.footTimeout.value.textContent = `${this.w.timeout_s.value} seconds`;
    this.footDtype.value.textContent = String(this.w.weight_dtype.value || "default");
  }

  // ------------------------------------------------------------------ the floating list

  renderList() {
    this.list.replaceChildren();
    this.list.classList.toggle("oh3s-open", Boolean(this.open));
    this.modelCaret.classList.toggle("oh3s-cue",
      Boolean(this.report && (this.report.choose_from || []).length));
    if (!this.open) return;
    const near = this.open === "model" ? this.modelRow : null;
    // Under the row that opened it, and over everything else, so the panel's height never moves.
    this.list.style.top = near
      ? `${near.offsetTop + near.offsetHeight + 3}px`
      : "";
    this.list.style.bottom = near ? "" : "24px";
    if (this.open === "model") this.modelList();
    else this.footList();
  }

  modelList() {
    const all = (this.report && this.report.choose_from) || [];
    const also = (this.report && this.report.also_known_as) || {};
    const ids = (this.report && this.report.ids) || [];
    const rows = this.narrowed();
    this.list.append(
      el("div", { class: "oh3s-note oh3s-loud", textContent:
        "Type any name in the field above. The list is what this server reports." }));
    if (!all.length) {
      this.list.append(el("div", { class: "oh3s-note", textContent:
        "Nothing has been fetched yet. Press test." }));
      return;
    }
    // The two counts are both said, because somebody who runs that server knows how many names it
    // has and a smaller number on its own looks wrong to them. Pluralised rather than left as the
    // template, because "2 names, 1 models" reads as a bug in the panel.
    this.list.append(el("div", { class: "oh3s-note", textContent:
      `${ids.length} name${ids.length === 1 ? "" : "s"}, ${all.length} `
      + `model${all.length === 1 ? "" : "s"}. Type in the field to narrow the list.` }));
    const set = this.modelName();
    const context = this.report && this.report.context;
    for (const id of rows) {
      const folded = also[id] || [];
      const bits = [];
      if (context) bits.push(`${Math.round(context / 1000)}k context`);
      if (folded.length) bits.push(`also called ${folded[0]}`);
      this.list.append(el("div", { class: "oh3s-row" + (id === set ? " oh3s-on" : ""),
        onclick: () => this.pick(id) },
        el("span", { class: "oh3s-rowname", textContent: id }),
        el("span", { class: "oh3s-rownote", textContent: bits.join(" · ") })));
    }
  }

  /** The three bottom controls. Each one edits one widget and closes. */
  footList() {
    if (this.open === "where") {
      /* One fact, one field. Empty means here, an address means there, and that IS the stored value.
       *
       * It used to be two rows, `in this ComfyUI` and `on another machine`, and they were never a
       * pair: the first is a complete answer and the second is the beginning of a question. Clicking
       * the second could not change anything, because there is no third thing for it to set. It was
       * decoration over a single field. */
      const at = tidy(this.w.server.value);
      this.list.append(el("div", { class: "oh3s-note oh3s-loud", textContent:
        "OpenH3-IR writes your brief. Give it an address only if you run it on another machine." }));
      const line = el("div", { class: "oh3s-note" });
      const clear = el("span", { class: "oh3s-kbtn", textContent: "clear",
        onclick: () => { this.w.server.value = ""; field.value = ""; say(""); this.after(); } });
      const field = el("input", { class: "oh3s-in oh3s-mono", value: at, spellcheck: false,
        placeholder: SERVICE_EXAMPLE });
      const say = (fixed) => {
        // One row, reserved, and it changes with the state. The second sentence is the fact worth
        // having at the moment of the decision: moving the compile does not move the render, and
        // nothing else on this panel says so.
        line.textContent = fixed
          || (tidy(field.value) ? "This ComfyUI still renders. Only the writing moves."
                                : "Empty. OpenH3-IR runs in this ComfyUI.");
        clear.style.display = tidy(field.value) ? "" : "none";
      };
      field.addEventListener("input", () => {
        this.w.server.value = tidy(field.value);
        say("");
        this.node.setDirtyCanvas?.(true, true);
        this.renderLead();
        this.renderSay();
        this.renderFoot();
      });
      field.addEventListener("blur", () => {
        // The same correction the endpoint field makes, said out loud rather than in silence.
        // Without it `setup_bundle` refuses the graph at queue time for exactly this reason.
        const typed = tidy(field.value);
        if (!typed || /^https?:\/\//i.test(typed)) return;
        field.value = `http://${typed}`;
        this.w.server.value = tidy(field.value);
        say("The address now starts with http://.");
        this.node.setDirtyCanvas?.(true, true);
        this.renderFoot();
      });
      field.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); field.blur(); this.open = null; this.after(); }
      });
      this.list.append(
        el("div", { class: "oh3s-wrow" },
          el("span", { class: "oh3s-wlabel", textContent: "runs at" }), field, clear),
        line);
      say("");
      requestAnimationFrame(() => field.focus());
      return;
    }
    if (this.open === "timeout") {
      this.list.append(el("div", { class: "oh3s-note oh3s-loud", textContent:
        "Writing a brief is one call to your language model." }));
      for (const n of [120, 300, 600, 1200, 3600]) {
        this.list.append(el("div", {
          class: "oh3s-row" + (Number(this.w.timeout_s.value) === n ? " oh3s-on" : ""),
          onclick: () => { this.w.timeout_s.value = n; this.open = null; this.after(); } },
          el("span", { class: "oh3s-rowname", textContent: `${n} seconds` })));
      }
      return;
    }
    this.list.append(el("div", { class: "oh3s-note oh3s-loud", textContent:
      "A GGUF checkpoint carries its own quantisation and ignores this." }));
    for (const v of (this.w.weight_dtype.options?.values || ["default"])) {
      this.list.append(el("div", {
        class: "oh3s-row" + (this.w.weight_dtype.value === v ? " oh3s-on" : ""),
        onclick: () => { this.w.weight_dtype.value = v; this.open = null; this.after(); } },
        el("span", { class: "oh3s-rowname", textContent: v })));
    }
  }

  after() {
    this.node.setDirtyCanvas?.(true, true);
    this.render();
  }

}

const CSS = `
.oh3s-panel{font-family:system-ui,sans-serif;color:#f3efe6;font-size:11px;
  background:#0a0a0d;border:1px solid rgba(243,239,230,.12);border-radius:8px;padding:8px;
  display:flex;flex-direction:column;gap:6px;box-sizing:border-box;position:relative;
  width:100%;height:100%;min-height:0;overflow:hidden;}
.oh3s-panel *{box-sizing:border-box;min-width:0;}
.oh3s-title{flex:0 0 auto;font-size:11px;color:#f3efe6;}
/* Every panel in this pack draws its small text at 38% of the bone colour, which measures 3.2 to 1
   on this near-black ground at 9 and 10 pixels. That is under the floor for text a person has to
   read, and on this panel most of the words ARE the text a person has to read. 56% measures 5.8 to
   1. Same colours, one number. */
/* Every quiet line is pinned to the rows it needs at 430, the narrowest the node goes, so none of
   them reflows as the node is dragged and the panel is one height at every width. Stated in em
   rather than pixels: the row count is the decision and the pixels follow the element's own type, so
   a machine whose font metrics differ still gets whole rows. Measured on the canvas, not reasoned. */
.oh3s-lead{flex:0 0 auto;font-size:10px;line-height:1.45;color:rgba(243,239,230,.56);
  min-height:2.9em;}
.oh3s-sec{flex:0 0 auto;font-size:9px;letter-spacing:.08em;text-transform:uppercase;
  color:rgba(243,239,230,.56);margin-top:2px;}
.oh3s-seclead{flex:0 0 auto;font-size:9.5px;line-height:1.45;color:rgba(243,239,230,.56);
  margin-top:-3px;min-height:2.9em;}
.oh3s-seclead.oh3s-one{min-height:1.45em;}
.oh3s-group{flex:0 0 auto;display:flex;flex-direction:column;gap:6px;}
/* A graph that compiles elsewhere writes with that machine's own model, so these controls do
   nothing. Standing them down is the alternative to leaving three live-looking controls that
   silently decide nothing. */
.oh3s-standdown{opacity:.42;pointer-events:none;}

.oh3s-wrow{flex:0 0 auto;display:flex;align-items:center;gap:6px;min-height:22px;
  background:var(--oh3-wbg);border:1px solid var(--oh3-wline);border-radius:12px;
  padding:2px 9px;overflow:hidden;}
.oh3s-wrow.oh3s-err{border-color:#f07070;}
.oh3s-wlabel{flex:0 0 auto;font-size:10px;color:var(--oh3-wmuted);white-space:nowrap;}
.oh3s-wrow .oh3s-in{flex:1;min-width:0;background:none;border:0;padding:2px 0;font-size:11px;
  font-family:inherit;color:var(--oh3-wtext);outline:none;}
.oh3s-mono{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;}
.oh3s-wrow .oh3s-in::placeholder{color:rgba(243,239,230,.44);}
.oh3s-wrow select.oh3s-in{background:transparent;color:var(--oh3-wtext);cursor:pointer;
  appearance:none;-webkit-appearance:none;padding-right:14px;}
.oh3s-wrow select.oh3s-in option{background:#101016;color:#f3efe6;}
.oh3s-wrow.oh3s-err select.oh3s-in{color:#f07070;}
/* The same grey the address field draws its example in. A value nobody chose, shown as one. */
.oh3s-wrow select.oh3s-in.oh3s-untouched{color:rgba(243,239,230,.44);}
.oh3s-wrow.oh3s-err select.oh3s-in.oh3s-untouched{color:#f07070;}
/* The select fills the row and the drawn caret sits over its right edge taking no clicks, so one
   arrow is drawn on every row of this panel and a click on the arrow still opens the list. */
.oh3s-selwrap{flex:1;min-width:0;position:relative;display:flex;align-items:center;}
.oh3s-selwrap .oh3s-in{flex:1;min-width:0;}
.oh3s-caret{flex:0 0 auto;color:rgba(243,239,230,.56);font-size:10px;line-height:1;cursor:pointer;
  padding:2px 2px 2px 5px;user-select:none;min-width:16px;text-align:center;}
.oh3s-caret:hover{color:#eb8219;}
.oh3s-caret.oh3s-static{position:absolute;right:0;pointer-events:none;padding:0;}
.oh3s-cue{color:#eb8219;}

/* The report is a BOX of a fixed number of rows, not a line. It wraps rather than truncating, and
   the room for it is the room that used to sit above the two headings. Three rows beside the model
   and two under the files, which is what every sentence in the message table needs at 430 wide.
   The row aligns to flex-start so the button sits at the top of the box beside the first row. */
.oh3s-sayrow{flex:0 0 auto;display:flex;align-items:flex-start;gap:8px;}
.oh3s-msg{flex:1;min-width:0;font-size:10px;line-height:1.4;color:rgba(243,239,230,.56);
  overflow:hidden;min-height:4.2em;}
.oh3s-sayrow.oh3s-files .oh3s-msg{min-height:2.8em;}
.oh3s-msg.oh3s-bad{color:#f07070;}
.oh3s-msg.oh3s-good{color:#5fc98a;}

.oh3s-chip{flex:0 0 auto;font-size:8.5px;line-height:1.7;padding:0 5px;border-radius:3px;
  font-family:ui-monospace,Menlo,monospace;border:1px solid rgba(243,239,230,.16);
  background:rgba(10,10,13,.6);color:rgba(243,239,230,.60);
  transition:color 120ms ease,border-color 120ms ease,background-color 120ms ease;}
.oh3s-chip.oh3s-see{color:#5fc98a;border-color:rgba(95,201,138,.45);background:rgba(95,201,138,.12);}
.oh3s-chip.oh3s-blind{color:#f07070;border-color:rgba(240,112,112,.45);background:rgba(240,112,112,.12);}

.oh3s-btn{flex:0 0 auto;border:1px solid rgba(243,239,230,.22);border-radius:11px;background:#101016;
  color:rgba(243,239,230,.80);font-size:10px;line-height:1.9;padding:0 11px;cursor:pointer;
  white-space:nowrap;user-select:none;}
.oh3s-btn:hover{border-color:rgba(243,239,230,.56);color:#f3efe6;}
.oh3s-btn.oh3s-wide{padding:0 16px;}
.oh3s-armed{border-color:#eb8219;color:#eb8219;background:rgba(235,130,25,.20);}
/* A dead button with a reason beats a button that fails for no visible cause. */
.oh3s-btn.oh3s-off{color:rgba(243,239,230,.30);border-color:rgba(243,239,230,.12);cursor:default;}
.oh3s-btn.oh3s-off:hover{color:rgba(243,239,230,.30);border-color:rgba(243,239,230,.12);}

.oh3s-krow{flex:0 0 auto;display:flex;flex-direction:column;gap:1px;}
/* Pinned like the other quiet lines. It is one row at 520 and two at 430, and an unpinned row here
   moves the panel's height by exactly as much as an unpinned lead does. */
.oh3s-klabel{display:flex;flex-wrap:wrap;gap:0 8px;align-items:baseline;font-size:10px;
  line-height:1.4;color:rgba(243,239,230,.56);min-height:2.8em;}
.oh3s-knote{color:rgba(243,239,230,.44);font-size:9.5px;}
.oh3s-kval{flex:1;min-width:0;font-size:10.5px;color:var(--oh3-wtext);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;}
.oh3s-kval.oh3s-empty{color:rgba(243,239,230,.44);}
.oh3s-kbtns{flex:0 0 auto;display:flex;align-items:center;gap:8px;}
.oh3s-kbtn{flex:0 0 auto;font-size:9.5px;color:rgba(243,239,230,.56);cursor:pointer;
  user-select:none;white-space:nowrap;}
.oh3s-kbtn:hover{color:#eb8219;}
.oh3s-kbtn.oh3s-armed{color:#eb8219;background:none;border:0;}

/* Whatever is left over sits here, above the rule, where it reads as the end of the panel. Never
   above a heading: a heading belongs to the rows under it, and space above one pushes it away from
   what it heads. */
/* The one row here that is NOT pinned, and that is the point of it. Its auto top margin sticks it to
   the bottom of the board, so whatever height the three items need -- one row at 520, three at 410
   -- the rule and the items sit at the bottom and every spare pixel in the panel collects ABOVE the
   rule. That is where spare space belongs. A draft pinned this to three rows and top-aligned the
   items, which put the same spare space under the rule instead, inside the bottom row. */
.oh3s-foot{flex:0 0 auto;display:flex;align-items:center;gap:14px;padding-top:6px;margin-top:auto;
  border-top:1px solid rgba(243,239,230,.12);font-size:9.5px;line-height:1.5;
  color:rgba(243,239,230,.56);flex-wrap:wrap;}
.oh3s-fi{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none;}
.oh3s-fi>span+span{color:rgba(243,239,230,.80);}
.oh3s-fi:hover>span+span{color:#eb8219;}
.oh3s-fi.oh3s-bad>span+span{color:#f07070;}

/* Everything that opens floats, so the panel's height never changes and nothing fights for room.
   One element, because only one thing can be open. */
.oh3s-list{display:none;position:absolute;left:8px;right:8px;z-index:3;
  flex-direction:column;overflow:auto;padding:4px;max-height:calc(100% - 40px);
  border-radius:6px;background:#0a0a0d;border:1px solid rgba(243,239,230,.22);
  box-shadow:0 10px 24px rgba(0,0,0,.6);}
.oh3s-list.oh3s-open{display:flex;}
.oh3s-note{flex:0 0 auto;padding:3px 8px;font-size:10px;line-height:1.45;
  color:rgba(243,239,230,.56);white-space:normal;}
.oh3s-note.oh3s-loud{color:rgba(243,239,230,.80);}
.oh3s-row{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;padding:3px 8px;border-radius:4px;
  color:rgba(243,239,230,.80);font-size:11px;line-height:1.55;cursor:pointer;user-select:none;}
.oh3s-row:hover{background:rgba(243,239,230,.08);color:#f3efe6;}
.oh3s-row.oh3s-on{color:#eb8219;}
/* The name is what somebody clicks and what they will type, so it keeps the room. The note beside
   it is the folded name and the context length, and it gives way first: a row whose name is cut to
   six characters while the note runs off the panel is a list of nothing useful.

   No backtick may appear anywhere in this block. It is one JavaScript template literal, so a pair of
   them in a comment ends the string and the file stops parsing. Measured: it took the whole panel
   off the canvas, and node --check passed the file. What catches it is importing the module. */
.oh3s-rowname{flex:1 1 auto;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;}
.oh3s-rownote{flex:0 1 auto;margin-left:auto;max-width:58%;min-width:0;font-size:9px;
  color:rgba(243,239,230,.56);font-family:ui-monospace,Menlo,monospace;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;}
.oh3s-rownote.oh3s-live{color:#5fc98a;}
.oh3s-list .oh3s-wrow{margin:2px 4px 4px;}

.oh3s-panel :focus-visible{outline:1px solid #eb8219;outline-offset:1px;}
`;

app.registerExtension({
  name: "openh3ir.setup",
  init() {
    // The rows dress as native ComfyUI widgets, and the surest way to match the theme is to ask it:
    // LiteGraph carries the widget colors the canvas actually draws with.
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
      const wanted = ["server", "llm_url", "llm_model", "weight_dtype", "timeout_s",
                      ...FILES.map((f) => f.w)];
      // A pack whose panel assumes a widget that is not there would take the node's whole surface
      // away. Missing one means the Python and this file disagree about the schema; leave the node
      // as ComfyUI drew it and say so once in the console.
      const absent = wanted.filter((n) => !by[n]);
      if (absent.length) {
        console.warn("[OpenH3-IR] the Setup panel expected widgets this node does not have:",
                     absent.join(", "), "- drawing the plain node instead");
        return r;
      }
      for (const name of wanted) {
        by[name].computeSize = () => [0, -4];
        by[name].hidden = true;
        if (by[name].options) by[name].options.hidden = true;
      }
      const panel = new Panel(this, by);
      this._oh3Setup = panel;
      const w = this.addDOMWidget("oh3s_panel", "div", panel.root, { serialize: false });
      /* The board has no width of its own: it is the node's, whatever the node has been dragged to.
       *
       * Load-bearing rather than tidy. The frontend writes a `width` onto every widget from a node
       * layout pass each time a value changes, and for a full-bleed DOM board that number is the
       * node's CONTENT width rather than its box. Measured on the Director: choosing one set it to
       * 238 on a node that was still 480 wide and squeezed its name field to eleven pixels, and it
       * never recovered at any node size. Unset is the state a widget starts in and the one that
       * renders full-bleed. */
      Object.defineProperty(w, "width", { get: () => null, set: () => {}, configurable: true });
      w.computedHeight = PANEL_H;
      w.computeSize = (width) => [width || NODE_W, PANEL_H];
      this.size = [NODE_W, PANEL_H + NODE_H_EXTRA];
      requestAnimationFrame(() => panel.render());
      return r;
    };
    /* Width drags, height does not. Everything that can overflow here is a long file name or a long
     * model name, and those want width; nothing on this panel wants more height, and everything that
     * opens floats rather than pushing the panel taller.
     *
     * One number at every width, and that only works because nothing on this panel reflows: every
     * quiet line is pinned to the rows it needs at the NARROWEST width, so a wider panel puts the
     * spare row under its own paragraph instead of changing the height. A draft that let the height
     * follow the width was turned down for the reason the media tray was built on: drag a corner and
     * the height jumps, which is a panel negotiating for room. */
    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      try {
        size[0] = Math.max(MIN_W, size[0]);
        size[1] = PANEL_H + NODE_H_EXTRA;
      } catch (e) { /* leave the size alone */ }
      return onResize?.apply(this, arguments);
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      const panel = this._oh3Setup;
      if (panel) {
        // This node came out of a saved workflow, so it already has an address and the one-time
        // check must not fire. Opening ten workflows must not fire forty requests.
        panel.configured = true;
        panel.render();
        panel.readKey();
      }
      return r;
    };
  },
});
