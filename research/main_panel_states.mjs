/* Drive the Main panel through every state it can be in, on a real ComfyUI, and photograph each.
 *
 * The report line chooses one of eight sentences from live facts: a parse of the text being typed
 * and a walk to the tray on whichever Media node is wired in. Neither can be produced in Python, so
 * neither is settled by `tests/test_main_panel.py`, which only proves the eight strings exist. This
 * types into the real box, wires a real Media node, and reads back what the panel said.
 *
 * Run it against a ComfyUI that is already serving this pack:
 *
 *     node research/main_panel_states.mjs [http://127.0.0.1:8188] [out-dir]
 *
 * It needs Playwright, which is not a dependency of this pack. Point PLAYWRIGHT at an install, or
 * pass one on the command line, if `playwright` is not resolvable from here.
 *
 * **The canvas is not ours.** The node is added, driven and removed again, and the removal is in a
 * `finally` so it happens even when a step throws. Nothing is saved and no workflow is touched.
 */
const COMFY = process.argv[2] || process.env.COMFY_URL || "http://127.0.0.1:8188";
const OUT = process.argv[3] || process.env.OUT_DIR || ".";
const PW = process.env.PLAYWRIGHT || "playwright";

const { chromium } = await import(PW);

/** What the panel must say, given what is on the canvas. The left side is what this script sets up;
 *  the right side is the exact sentence the design wrote for it. */
const STATES = [
  { name: "01-nothing-typed", tray: null, text: "",
    says: "nothing written yet" },
  { name: "02-no-tray", tray: null,
    text: "a hot air balloon drifts over misty green hills at sunrise",
    says: "No tray is connected, so the video is written from your words alone." },
  { name: "03-tray-unused", tray: "four",
    text: "a hot air balloon drifts over misty green hills at sunrise",
    says: "The tray holds 4 files. Type @ to name one in the prompt." },
  { name: "04-all-resolve", tray: "four",
    text: '@carguy walks onto @the-gantry and stops when he sees @the-city. '
          + '@speaks("we are not going back")',
    says: "2 pictures and 1 clip named. 1 line is locked." },
  { name: "04b-one-of-each", tray: "four",
    text: '@carguy walks onto @the-gantry and stops. @speaks("we are not going back")',
    says: "1 picture and 1 clip named. 1 line is locked." },
  { name: "04c-all-three-kinds", tray: "four",
    text: "@carguy walks onto @the-gantry under @audio1.",
    says: "1 picture, 1 clip and 1 sound named." },
  { name: "05-one-bad-name", tray: "gantry",
    text: "@carguy walks onto @the-gantry and stops.",
    says: "@carguy is not in the tray. Rename a slot on the Media node, or change the name here." },
  { name: "06-two-bad-names", tray: "gantry",
    text: "@carguy walks onto @the-city and stops.",
    says: "@carguy and @the-city are not in the tray. Rename those slots on the Media node, or "
          + "change the names here." },
  { name: "07-mention-no-tray", tray: null,
    text: "@carguy walks onto the wet gantry in the rain.",
    says: "No tray is connected, so @carguy names nothing. Wire an OpenH3-IR Media node into "
          + "media." },
  { name: "08-unclosed-line", tray: null,
    text: 'he stops and says @speaks("we are not going back',
    says: "One spoken line was never closed. Close it with a quote mark and a bracket." },
  { name: "09-empty-tray", tray: "none",
    text: "a hot air balloon drifts over misty green hills at sunrise",
    says: "The tray is empty. Add files on the Media node." },
];

/** Trays to hang off the Media node. `four` is the design's own example. */
const TRAYS = {
  none: [],
  gantry: [{ kind: "video", label: "the-gantry", role: "edit", file: "gantry.mp4 [input]" }],
  four: [
    { kind: "picture", label: "carguy", role: "person", file: "carguy.png [input]" },
    { kind: "picture", label: "the-city", role: "place", file: "city.png [input]" },
    { kind: "video", label: "the-gantry", role: "edit", file: "gantry.mp4 [input]" },
    { kind: "sound", label: "audio1", role: "music", file: "hum.wav [input]" },
  ],
};

/** Lists to open and photograph, by the widget each one belongs to. */
const LISTS = [
  ["10-list-seconds", "seconds"],
  ["11-list-frame-shape", "aspect"],
  ["12-list-resolution", "megapixels"],
  ["13-list-shots", "shots"],
  ["14-list-invention", "creativity"],
  ["15-list-music", "silent"],
  ["16-list-spoken-in", "spoken_language"],
  ["17-list-brief-seed", "seed"],
  ["18-list-reference-size", "sizing"],
  ["19-list-writing-effort", "effort"],
];

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1100, height: 1100 },
                                     deviceScaleFactor: 2 });
const complaints = [];
page.on("console", (m) => {
  if (m.type() === "error") complaints.push(m.text().slice(0, 200));
});
let red = 0;

const panelText = () => page.evaluate(() => {
  const el = window.__n.widgets.find((w) => w.name === "oh3m_panel").element;
  return el.querySelector(".oh3m-msg").textContent;
});

async function shoot(name) {
  await page.evaluate(() =>
    document.querySelectorAll(".p-toast,.p-dialog-mask").forEach((e) => e.remove()));
  await page.waitForTimeout(300);
  const box = await page.evaluate(() => {
    const r = window.__n.widgets.find((w) => w.name === "oh3m_panel").element
      .getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  await page.screenshot({ path: `${OUT}/${name}.png`,
    clip: { x: Math.max(0, box.x - 30), y: Math.max(0, box.y - 44),
            width: Math.min(760, box.w + 60), height: Math.min(1060, box.h + 88) } });
}

function check(name, got, want) {
  const ok = got === want;
  if (!ok) red += 1;
  console.log(`${ok ? "  ok  " : " RED  "} ${name}`);
  if (!ok) console.log(`        wanted: ${want}\n        got:    ${got}`);
}

try {
  await page.goto(COMFY, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForFunction(() => window.app?.graph && window.LiteGraph, null, { timeout: 90000 });
  await page.waitForTimeout(2500);

  await page.evaluate(() => {
    const n = LiteGraph.createNode("OpenH3IRCompile");
    // Clear of ComfyUI's own left sidebar, which is an overlay: a node under it is not clipped, it
    // is covered, and a photograph taken there loses the panel's left edge.
    n.pos = [130, 300];
    app.graph.add(n);
    window.__n = n;
    const m = LiteGraph.createNode("OpenH3IRMedia");
    m.pos = [1100, 300];
    app.graph.add(m);
    window.__m = m;
    app.canvas.ds.offset = [0, 0];
    app.canvas.ds.scale = 1;
    app.graph.setDirtyCanvas(true, true);
  });
  await page.waitForFunction(() => {
    const w = window.__n?.widgets?.find((x) => x.name === "oh3m_panel");
    return Boolean(w?.element?.querySelector(".oh3m-msg"));
  }, null, { timeout: 30000 });
  await page.waitForTimeout(900);
  console.log("panel mounted");

  /* --------------------------------------------------- the host's own textarea is gone
   *
   * This node's own widgets, and nothing else on the page: a first draft read every textarea in
   * the document and failed on two that belonged to the owner's existing CLIPTextEncode nodes.
   */
  const strays = await page.evaluate(() => {
    const panel = window.__n.widgets.find((w) => w.name === "oh3m_panel").element;
    return (window.__n.widgets || [])
      .filter((w) => w.element && !panel.contains(w.element)
                     && w.element.getBoundingClientRect().width > 1)
      .map((w) => `${w.name}: ${Math.round(w.element.getBoundingClientRect().width)}px wide`);
  });
  check("no host widget is left drawn over the panel", JSON.stringify(strays), "[]");

  // --------------------------------------------------------------- the size the design drew
  await page.evaluate(() => { app.canvas.ds.scale = 1; app.graph.setDirtyCanvas(true, true); });
  const size = await page.evaluate(() => ({ node: window.__n.size,
    asked: window.__n.widgets.find((w) => w.name === "oh3m_panel").computeSize(520)
      .map(Math.round),
    panel: (() => {
      const r = window.__n.widgets.find((w) => w.name === "oh3m_panel").element
        .getBoundingClientRect();
      return [Math.round(r.width), Math.round(r.height)];
    })(),
    box: (() => {
      const r = window.__n.widgets.find((w) => w.name === "oh3m_panel").element
        .querySelector(".oh3m-box").getBoundingClientRect();
      return Math.round(r.height);
    })() }));
  console.log("  measured:", JSON.stringify(size));
  check("the node is 520 by 773", `${Math.round(size.node[0])}x${Math.round(size.node[1])}`,
        "520x773");
  /* The board asks for the whole node minus its sockets. ComfyUI then insets a DOM widget inside
   * the node body: MEASURED at 10 pixels each side and 16 off the height, so the element is 500 by
   * 579 where it asked for 520 by 595. The node is the size the design specified and the inset is
   * the host's, not ours. */
  check("the board asks for the node minus its sockets", JSON.stringify(size.asked), "[520,595]");
  check("ComfyUI insets it by 20 across and 16 down",
        `${size.asked[0] - size.panel[0]}x${size.asked[1] - size.panel[1]}`, "20x16");

  /* Every quiet line is pinned to one row, and a line that wrapped to two at some width would push
   * every row under it. Read at the narrowest the node allows, with the pin lifted. */
  const wraps = await page.evaluate(() => {
    const n = window.__n;
    n.setSize([430, 900]);
    n.onResize?.(n.size);
    return [...n._oh3Main.root.querySelectorAll(".oh3m-seclead")].map((e) => {
      const lh = parseFloat(getComputedStyle(e).lineHeight);
      const was = e.style.minHeight;
      e.style.minHeight = "0px";
      const rows = Math.round(e.scrollHeight / lh);
      e.style.minHeight = was;
      return rows;
    });
  });
  check("every quiet line is one row at the narrowest the node goes", wraps.join(","), "1,1,1");
  await page.evaluate(() => { window.__n.setSize([520, 773]); });

  // --------------------------------------------------------------- the eight report states
  for (const state of STATES) {
    await page.evaluate((s) => {
      const n = window.__n;
      const m = window.__m;
      const input = n.inputs.find((i) => i.name === "media");
      // Disconnect first, so every state starts from the same place.
      n.disconnectInput(n.inputs.indexOf(input));
      if (s.tray) {
        m.widgets.find((w) => w.name === "tray").value = JSON.stringify(s.slots);
        m.connect(0, n, n.inputs.indexOf(input));
      }
      const panel = n._oh3Main;
      panel.box.value = s.text;
      panel.box.dispatchEvent(new Event("input", { bubbles: true }));
    }, { ...state, slots: TRAYS[state.tray] });
    await page.waitForTimeout(400);
    check(state.name, await panelText(), state.says);
    await shoot(state.name);
  }

  // --------------------------------------------------------------- the chip beside `spoken in`
  const chip = await page.evaluate(() => {
    const panel = window.__n._oh3Main;
    const read = () => panel.root.querySelector(".oh3m-chip").textContent;
    panel.box.value = "nobody says anything here";
    panel.box.dispatchEvent(new Event("input", { bubbles: true }));
    const quiet = read();
    panel.box.value = 'he stops. @speaks("we are not going back")';
    panel.box.dispatchEvent(new Event("input", { bubbles: true }));
    const one = read();
    panel.box.value = '@speaks("one") and then @speaks("two")';
    panel.box.dispatchEvent(new Event("input", { bubbles: true }));
    return [quiet, one, read()];
  });
  check("the chip while nothing is locked", chip[0], "no line locked");
  check("the chip with one line locked", chip[1], "1 line locked");
  check("the chip with two lines locked", chip[2], "2 lines locked");

  // --------------------------------------------------------------- every list, drawn and shot
  // Back to a tray that answers, so the lists are photographed over a healthy panel rather than
  // over the red left behind by the last report state.
  await page.evaluate((slots) => {
    const n = window.__n;
    const m = window.__m;
    const at = n.inputs.findIndex((i) => i.name === "media");
    n.disconnectInput(at);
    m.widgets.find((w) => w.name === "tray").value = JSON.stringify(slots);
    m.connect(0, n, at);
    const panel = n._oh3Main;
    panel.box.value = '@carguy walks onto the wet gantry\nin the rain and stops when he sees '
                      + '@the-city\nbelow. @speaks("we are not going back")';
    panel.box.dispatchEvent(new Event("input", { bubbles: true }));
  }, TRAYS.four);
  await page.waitForTimeout(300);

  for (const [name, widget] of LISTS) {
    const rows = await page.evaluate((w) => {
      const panel = window.__n._oh3Main;
      panel.open = null;
      panel.toggle(w);
      const list = panel.root.querySelector(".oh3m-list");
      return {
        open: list.classList.contains("oh3m-open"),
        // A list that opened off the bottom of the panel would be a list nobody can read.
        inside: list.getBoundingClientRect().bottom
                <= panel.root.getBoundingClientRect().bottom + 1,
        rows: [...list.querySelectorAll(".oh3m-lrow")].map((r) => r.textContent.trim()),
        dim: [...list.querySelectorAll(".oh3m-lrow.oh3m-dim")].map((r) => r.textContent.trim()),
      };
    }, widget);
    check(`${name} opens`, String(rows.open), "true");
    check(`${name} stays inside the panel`, String(rows.inside), "true");
    console.log(`        rows: ${rows.rows.join(" | ").slice(0, 150)}`);
    if (rows.dim.length) console.log(`        dimmed: ${rows.dim.join(" | ")}`);
    await shoot(name);
  }

  // The shot list carries the only arithmetic on the panel, so it is read rather than glanced at.
  const shots = await page.evaluate(() => {
    const panel = window.__n._oh3Main;
    panel.w.seconds.value = 8.0;
    panel.open = null;
    panel.toggle("shots");
    return [...panel.root.querySelectorAll(".oh3m-lrow")].map((r) => [
      r.querySelector(".oh3m-lname").textContent,
      r.classList.contains("oh3m-dim"),
      r.querySelector(".oh3m-lnote")?.textContent || "",
    ]);
  });
  const dimmed = shots.filter((s) => s[1]).map((s) => `${s[0]} ${s[2]}`).join(", ");
  check("at 8.0 seconds, seven shots and up cannot fit", dimmed,
        "7 needs 8.4 s, 8 needs 9.6 s, 9 needs 10.8 s, 10 needs 12.0 s");
  check("a dimmed count is still clickable", await page.evaluate(() => {
    const panel = window.__n._oh3Main;
    panel.open = null;
    panel.toggle("shots");
    const row = [...panel.root.querySelectorAll(".oh3m-lrow.oh3m-dim")][0];
    row.click();
    return String(panel.w.shots.value);
  }), "7");
  await page.evaluate(() => { window.__n._oh3Main.set("shots", "auto"); });

  // --------------------------------------------------------------- the panel writes the graph
  const wrote = await page.evaluate(() => {
    const panel = window.__n._oh3Main;
    panel.set("aspect", "9:16");
    panel.set("megapixels", 1.5);
    panel.set("silent", true);
    panel.set("creativity", "bold");
    panel.set("spoken_language", "Spanish");
    const w = (n) => panel.w[n].value;
    return { aspect: w("aspect"), megapixels: w("megapixels"), silent: w("silent"),
             creativity: w("creativity"), language: w("spoken_language"),
             shown: [...panel.root.querySelectorAll(".oh3m-row .oh3m-val")]
               .map((v) => v.textContent) };
  });
  console.log("  wrote:", JSON.stringify(wrote));
  check("the picked frame shape reached the widget", wrote.aspect, "9:16");
  check("the picked resolution reached the widget", String(wrote.megapixels), "1.5");
  check("music: none set the boolean the schema has", String(wrote.silent), "true");
  // In panel order: spoken in, seconds, frame shape, resolution, shots, invention, music.
  check("the resolution row shows its unit", wrote.shown[3], "1.5 megapixels");
  check("the music row shows a word, not a boolean", wrote.shown[6], "none");
  await shoot("20-values-picked");

  // --------------------------------------------------------------- height drags, the box takes it
  const grown = await page.evaluate(() => {
    const n = window.__n;
    const read = () => Math.round(n.widgets.find((w) => w.name === "oh3m_panel").element
      .querySelector(".oh3m-box").getBoundingClientRect().height);
    const before = read();
    n.setSize([520, 1100]);
    n.onResize?.(n.size);
    app.graph.setDirtyCanvas(true, true);
    return { before, after: read(), size: n.size.map(Math.round) };
  });
  await page.waitForTimeout(400);
  const after = await page.evaluate(() => Math.round(
    window.__n.widgets.find((w) => w.name === "oh3m_panel").element
      .querySelector(".oh3m-box").getBoundingClientRect().height));
  console.log(`  prompt box: ${grown.before}px at 773 tall, ${after}px at 1100 tall`);
  check("the prompt box takes the pixels the node gained", String(after > grown.before + 250),
        "true");
  await shoot("21-dragged-taller");

  // And it refuses to go under the minimum, where the box is at its own floor.
  const floor = await page.evaluate(() => {
    const n = window.__n;
    n.setSize([200, 200]);
    n.onResize?.(n.size);
    app.graph.setDirtyCanvas(true, true);
    return [Math.round(n.size[0]), Math.round(n.size[1])];
  });
  check("the node stops at its minimum", floor.join("x"), "430x719");
  await page.waitForTimeout(400);
  await shoot("22-at-the-minimum");
} catch (e) {
  red += 1;
  console.log("FAILED:", String(e).slice(0, 600));
} finally {
  const left = await page.evaluate(() => {
    const strays = app.graph._nodes.filter(
      (n) => n.type === "OpenH3IRCompile" || n.type === "OpenH3IRMedia");
    strays.forEach((n) => app.graph.remove(n));
    app.graph.setDirtyCanvas(true, true);
    return `removed ${strays.length}; the graph holds ${app.graph._nodes.length}`;
  }).catch((e) => "cleanup failed: " + e);
  console.log("cleanup:", left);
  await browser.close();
}

if (complaints.length) console.log("console errors:", complaints.slice(0, 5).join(" | "));
console.log(red ? `\n${red} RED` : "\nall green");
process.exit(red ? 1 : 0);
