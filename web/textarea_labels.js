import { app } from "../../scripts/app.js";

// The classic canvas shows a text box's name only as its placeholder, so it disappears once the box has text.
// Keep a small name label in the box's top-left corner, as the Nodes 2.0 renderer does.

const NODES = new Set(["H3ImageReference", "H3VideoReference", "H3AudioReference", "H3Ref2VAPrompt"]);
const LABEL = "h3-textarea-label";

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
        textarea.style.paddingTop = "16px";
        if (textarea.placeholder === widget.name) {
            textarea.placeholder = "";
        }
    }
}

app.registerExtension({
    name: "H3RefPrompt.TextareaLabels",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODES.has(nodeData.name)) {
            return;
        }
        // text boxes are mounted after the node is created, and again after being hidden, so check on every draw
        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function () {
            onDrawForeground?.apply(this, arguments);
            addLabels(this);
        };
    },
});
