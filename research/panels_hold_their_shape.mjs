/* Every panel keeps the shape the node gives it. Two ways it stopped doing that, both driven
 * here on a real ComfyUI.
 *
 * ONE: put every panel through a configure and prove it is still there afterwards.
 *
 * A node is configured on three ordinary paths: an undo, a workflow opened from disk, and a
 * workflow dragged in off a rendered video. All three end in the same call, so one of them stands
 * for all three here.
 *
 * MEASURED, and the reason this file exists: the Main board hid itself on that call and left an
 * empty box with sockets on it. A node added by hand never showed it, because the board is added
 * after the first hiding loop has run and only a configure runs a second one. Reading the source
 * cannot settle whether a panel survives a configure, so this drives it.
 *
 * Run it against a ComfyUI that is already serving this pack:
 *
 *     node research/panels_hold_their_shape.mjs [http://127.0.0.1:8188] [out-dir]
 *
 * It needs Playwright, which is not a dependency of this pack. Point PLAYWRIGHT at an install, or
 * pass one on the command line, if `playwright` is not resolvable from here.
 *
 * TWO: write a width onto every board and prove none of them takes it. A board fills the node it
 * is in and has no width of its own. The frontend writes one anyway, from a node layout pass, and
 * for a full-bleed board that number is the content width rather than the box. Nothing reads it
 * while the board is a live element. Zoom out far enough that the element is hidden and the canvas
 * draws the board from that number: painted past the right edge of the node, over empty canvas,
 * taking the mouse where it lands. Measured from the owner's screenshot at node 497 wide, board
 * 660.
 *
 * **The canvas is not ours.** It runs in a browser profile with no history, so ComfyUI opens its
 * own empty graph and no workflow of anybody's is loaded, touched or saved.
 */
const COMFY = process.argv[2] || process.env.COMFY_URL || "http://127.0.0.1:8188";
const OUT = process.argv[3] || process.env.OUT_DIR || ".";
const PW = process.env.PLAYWRIGHT || "playwright";

const { chromium } = await import(PW);

/** Every node in this pack that draws its own panel, and the class its board carries. */
const PANELS = [
  { node: "OpenH3IRCompile",  board: ".oh3m-panel", name: "Main" },
  { node: "OpenH3IRMedia",    board: ".oh3-panel",  name: "Media" },
  { node: "OpenH3IRSetup",    board: ".oh3s-panel", name: "Setup" },
  { node: "OpenH3IRDirector", board: ".oh3d-panel", name: "Director" },
];

/** A board is alive when it is on the page with real height, and its widget still asks the node for
 *  real room. A board hidden by the bug fails both: nothing to see, and nothing reserved for it. */
const alive = (page, panel) => page.evaluate(({ node, board }) => {
  const n = window.app.graph._nodes.find((n) => n.type === node);
  if (!n) return { found: false };
  const root = document.querySelector(board);
  const w = (n.widgets || []).find((w) => w.element && w.element.matches?.(board));
  let asks = null;
  try { asks = w ? w.computeSize(400)[1] : null; } catch { asks = "threw"; }
  return {
    found: true,
    drawn: !!root && Math.round(root.getBoundingClientRect().height),
    asks,
    display: w?.element?.style?.display ?? "",
  };
}, panel);

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1000 } })).newPage();
const noise = [];
page.on("pageerror", (e) => noise.push(String(e)));

let bad = 0;
const broken = [];
try {
  await page.goto(COMFY, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.app?.graph, null, { timeout: 60000 });
  await page.waitForTimeout(3000);

  for (const panel of PANELS) {
    await page.evaluate(() => window.app.graph.clear());
    await page.waitForTimeout(500);
    await page.evaluate(({ node }) => {
      const n = window.LiteGraph.createNode(node);
      n.pos = [60, 60];
      window.app.graph.add(n);
    }, panel);
    await page.waitForTimeout(2500);

    const before = await alive(page, panel);
    await page.screenshot({ path: `${OUT}/configure-${panel.name}-before.png` });

    // The call every one of the three paths ends in.
    await page.evaluate(async () => {
      const data = window.app.graph.serialize();
      window.app.graph.clear();
      await window.app.loadGraphData(data, false, false);
    });
    await page.waitForTimeout(2500);

    const after = await alive(page, panel);
    await page.screenshot({ path: `${OUT}/configure-${panel.name}-after.png` });

    /* A board that was never drawn to begin with is a case that did not run, and it must not print
     * the same word as a board that a configure took away. MEASURED: the first draft of this file
     * had the wrong class for the Media board and reported it GONE both before and after, which
     * reads as a failure and is really a test of nothing. */
    if (!before.found || !(before.drawn > 100)) {
      broken.push(`${panel.name}: no board matched ${panel.board} before the configure, so this `
                  + "case proved nothing. Fix the selector.");
      console.log(`??    ${panel.name.padEnd(9)} case did not run: nothing matched ${panel.board}`);
      continue;
    }
    const ok = after.found && after.drawn > 100 && after.asks > 100 && after.display !== "none";
    if (!ok) bad += 1;
    console.log(`${ok ? "OK  " : "GONE"}  ${panel.name.padEnd(9)} `
                + `before ${before.drawn}px asks ${before.asks}  ->  `
                + `after ${after.drawn}px asks ${after.asks}`
                + (after.display === "none" ? "  display:none" : ""));
  }

  // TWO: no board takes a width.
  console.log("");
  for (const panel of PANELS) {
    await page.evaluate(() => window.app.graph.clear());
    await page.waitForTimeout(400);
    await page.evaluate(({ node }) => {
      const n = window.LiteGraph.createNode(node);
      n.pos = [60, 60];
      window.app.graph.add(n);
    }, panel);
    await page.waitForTimeout(2000);

    const r = await page.evaluate(({ node, board }) => {
      const n = window.app.graph._nodes.find((n) => n.type === node);
      const w = (n?.widgets || []).find((w) => w.element && w.element.matches?.(board));
      if (!w) return { found: false };
      w.width = 900;                                 // what the host's layout pass does
      return { found: true, after: w.width };
    }, panel);

    if (!r.found) {
      broken.push(`${panel.name}: no board matched ${panel.board}, so the width case proved nothing.`);
      console.log(`??    ${panel.name.padEnd(9)} width case did not run`);
      continue;
    }
    const ok = r.after === null || r.after === undefined;
    if (!ok) bad += 1;
    console.log(`${ok ? "OK  " : "TOOK"}  ${panel.name.padEnd(9)} `
                + `width written 900, board reports ${r.after}`);
  }
} finally {
  await browser.close();
}

for (const line of noise) console.log("page error:", line.slice(0, 300));
for (const line of broken) console.log("BROKEN CASE:", line);
console.log(bad ? `\n${bad} of ${PANELS.length * 2} checks failed`
                : broken.length ? `\n${broken.length} cases never ran`
                : `\nall ${PANELS.length} panels survived a configure and none took a width`);
process.exit(bad || broken.length ? 1 : 0);
