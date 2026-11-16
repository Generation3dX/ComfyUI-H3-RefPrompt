import { app } from "../../scripts/app.js";

// Text boxes of the H3 nodes in the classic canvas:
// - keep a small name label in the top-left corner, as the Nodes 2.0 renderer does; the canvas shows the name only as
//   a placeholder, which disappears once the box has text
// - in H3 Ref2VA Prompt, give shots the spare height and keep summary, soundscape and music at two lines

const NODES = new Set(["H3ImageReference", "H3VideoReference", "H3AudioReference", "H3Ref2VAPrompt"]);
const TWO_LINE = new Set(["summary", "soundscape", "music"]);
const LABEL = "h3-textarea-label";
const LABEL_SPACE = 16;

function addLabels(node) {
    for (const widget of node.widgets ?? []) {
        const textarea = widget.element;
        const box = textarea?.parentElement;
        if (!(textarea instanceof HTMLTextAreaElement) || !box?.classList.contains("dom-widget") || box.querySelector(`:scope > .${LABEL}`)) {
            continue;
        }
        const label = document.createElement("span");
        label.className = LABEL;
        label.textContent = (widget.label || widget.name).replaceAll("_", " ");
        Object.assign(label.style, {
            position: "absolute", top: "2px", left: "8px", fontSize: "10px", lineHeight: "12px",
            color: "var(--descrip-text, #999)", pointerEvents: "none", zIndex: 1,
        });
        box.appendChild(label);
        textarea.style.paddingTop = `${LABEL_SPACE}px`;
        if (textarea.placeholder === widget.name) {
            textarea.placeholder = "";
        }
    }
}

function sizeBoxes(node) {
    const fontSize = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--comfy-textarea-font-size")) || 10;
    // BaseDOMWidgetImpl.DEFAULT_MARGIN (10) is taken off the top and bottom of the box
    const twoLines = LABEL_SPACE + 2 * Math.ceil(fontSize * 1.1) + 4 + 2 * 10;
    for (const widget of node.widgets ?? []) {
        const textarea = widget.element;
        if (!(textarea instanceof HTMLTextAreaElement)) {
            continue;
        }
        if (TWO_LINE.has(widget.name)) {
            textarea.style.setProperty("--comfy-widget-min-height", `${twoLines}`);
            textarea.style.setProperty("--comfy-widget-max-height", `${twoLines}`);
        } else if (widget.name === "shots") {
            textarea.style.setProperty("--comfy-widget-min-height", "240");
        }
    }
    node.setSize([node.size[0], node.computeSize()[1]]);
}

app.registerExtension({
    name: "H3RefPrompt.TextBoxes",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODES.has(nodeData.name)) {
            return;
        }
        if (nodeData.name === "H3Ref2VAPrompt") {
            // runs before a saved workflow restores the node's size, so only new nodes take the computed height
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);
                sizeBoxes(this);
            };
        }
        // text boxes are mounted after the node is created, and again after being hidden, so check on every draw
        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function () {
            onDrawForeground?.apply(this, arguments);
            addLabels(this);
        };
    },
});
