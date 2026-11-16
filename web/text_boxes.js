import { app } from "../../scripts/app.js";

// Text boxes of the H3 nodes in the classic canvas:
// - keep a small name label in the top-left corner, as the Nodes 2.0 renderer does; the canvas shows the name only as
//   a placeholder, which disappears once the box has text
// - in H3 Ref2VA Prompt, give shots the spare height and keep summary, soundscape and music at two lines
// - keep_these / ignore_these: draw the name above the list, and fill in the role's picks, which the frontend's
//   multi-select ignores, when the list is created or the role changes (not when a saved workflow is loaded)

const NODES = new Set(["H3ImageReference", "H3VideoReference", "H3AudioReference", "H3Ref2VAPrompt"]);
const TWO_LINE = new Set(["summary", "soundscape", "music"]);
const LABEL = "h3-textarea-label";
const LABEL_SPACE = 16;
// the frontend's multi-select is sized for Nodes 2.0; shrink it to a normal widget row. Only these lists are this short,
// so the container query leaves other nodes' multi-selects alone. The margin above the box holds the drawn name.
const PICKS_MARGIN = 12;
const PICKS_HEIGHT = 20;
const style = document.createElement("style");
style.textContent = `
.dom-widget:has(> .size-full > .p-multiselect) { container-type: size; }
@container (max-height: ${PICKS_HEIGHT + 2}px) {
    .p-multiselect { height: 100%; align-items: center; font-size: 12px; border-radius: ${PICKS_HEIGHT / 2}px; }
    .p-multiselect-label { padding: 0 10px; line-height: ${PICKS_HEIGHT}px; }
    .p-multiselect-dropdown { width: 24px; }
    .p-multiselect-dropdown svg { width: 10px; height: 10px; }
}`;
document.head.appendChild(style);
const restored = new WeakSet();
const prepared = new WeakSet();

function picks(node) {
    return (node.widgets ?? []).filter((w) => w.inputSpec?.multi_select);
}

function preparePicks(node) {
    let changed = false, fresh = false;
    for (const widget of picks(node)) {
        if (prepared.has(widget)) {
            continue;
        }
        prepared.add(widget);
        widget.options.margin = PICKS_MARGIN;
        widget.options.getMinHeight = widget.options.getMaxHeight = () => PICKS_HEIGHT + 2 * PICKS_MARGIN;
        if (!restored.has(widget)) {
            fresh = true;
            if (!widget.value?.length && widget.inputSpec.default?.length) {
                widget.value = [...widget.inputSpec.default];
            }
        }
        changed = true;
    }
    // new lists fit the node to its content; a loaded node keeps its saved size unless it is too small
    if (changed) {
        const height = node.computeSize()[1];
        node.setSize([node.size[0], fresh ? height : Math.max(node.size[1], height)]);
    }
}

function drawPickLabels(node, ctx) {
    ctx.save();
    ctx.font = "10px Arial";
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--descrip-text").trim() || "#999";
    for (const widget of picks(node)) {
        if (node.isWidgetVisible?.(widget) !== false && widget.y) {
            ctx.fillText(widget.name.replace("role.", "").replaceAll("_", " "), PICKS_MARGIN + 4, widget.y + 10);
        }
    }
    ctx.restore();
}

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
        nodeType.prototype.onDrawForeground = function (ctx) {
            onDrawForeground?.apply(this, arguments);
            addLabels(this);
            if (!this.flags?.collapsed) {
                preparePicks(this);
                drawPickLabels(this, ctx);
            }
        };
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            for (const widget of picks(this)) {
                restored.add(widget);
            }
        };
    },
});
