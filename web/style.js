/* OpenH3-IR: the family's colors.
 *
 * The tray and the director carry their own boards, but Main and Setup are standard widget nodes
 * drawn by ComfyUI's theme, and their widget rows are the theme's business. What is ours on every
 * node: the title bar, the body, and the status dot. Painted once here so the four nodes read as
 * one family: void ground, and the single orange accent on the dot.
 *
 * Only unset colors are painted, so a color a user picked by hand, or one carried inside a saved
 * workflow, is never overruled.
 */
import { app } from "../../scripts/app.js";

const OURS = ["OpenH3IRCompile", "OpenH3IRMedia", "OpenH3IRSetup", "OpenH3IRDirector"];
const TITLE = "#0a0a0d";
const BODY = "#101016";
const DOT = "#eb8219";

app.registerExtension({
  name: "openh3ir.style",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!OURS.includes(nodeData?.name)) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      if (!this.color) this.color = TITLE;
      if (!this.bgcolor) this.bgcolor = BODY;
      this.boxcolor = DOT;
      return r;
    };
  },
});
