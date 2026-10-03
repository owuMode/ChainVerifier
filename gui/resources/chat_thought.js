"use strict";

/* =========================================================
   INLINE THOUGHT BOX + TASK EVENT HANDLER
   =========================================================
   Renders the small "Thinking…" chip and appends activity
   lines from the EventBus. Completion updates the label to
   "Thought for Xs" and collapses the body.
   ========================================================= */


let _thinkingStartedAt = null;


function _ensureThoughtBox() {
    let container = document.getElementById("typing");
    if (!container) {
        const msgs = document.querySelectorAll("#chatInner .message.ai");
        container = msgs[msgs.length - 1] || null;
    }
    if (!container) return null;

    const content = container.querySelector(".ai-content");
    if (!content) return null;

    let box = content.querySelector(".ai-thought");
    if (box) return box;

    box = document.createElement("div");
    box.className = "ai-thought";

    const header = document.createElement("button");
    header.className = "ai-thought-header";
    header.type = "button";

    const icon = document.createElement("span");
    icon.className = "ai-thought-icon";
    icon.textContent = "✻";

    const label = document.createElement("span");
    label.className = "ai-thought-label";
    label.textContent = "Thinking…";

    const chevron = document.createElement("span");
    chevron.className = "ai-thought-chevron";
    chevron.textContent = "▾";

    header.appendChild(icon);
    header.appendChild(label);
    header.appendChild(chevron);

    const body = document.createElement("div");
    body.className = "ai-thought-body";

    header.addEventListener("click", () => {
        box.classList.toggle("expanded");
    });

    box.appendChild(header);
    box.appendChild(body);

    content.insertBefore(box, content.firstChild);

    return box;
}


function _addThoughtLine(kind, text, opts) {
    const box = _ensureThoughtBox();
    if (!box) return;
    const body = box.querySelector(".ai-thought-body");
    if (!body) return;

    const optsSafe = opts || {};

    const line = document.createElement("div");
    line.className = "ai-thought-line" + (optsSafe.isReplan ? " replan" : "");
    line.dataset.kind = kind;

    const marker = document.createElement("span");
    marker.className = "ai-thought-marker";
    marker.textContent = optsSafe.marker || "·";

    const txt = document.createElement("span");
    txt.className = "ai-thought-text";
    txt.textContent = text;

    line.appendChild(marker);
    line.appendChild(txt);
    body.appendChild(line);

    if (!box.classList.contains("expanded") && body.children.length === 1) {
        box.classList.add("expanded");
    }
}


function _finalizeThought() {
    const box = document.querySelector(".ai-thought");
    if (!box) return;

    const label = box.querySelector(".ai-thought-label");
    if (label && _thinkingStartedAt) {
        const secs = Math.max(
            1,
            Math.round((Date.now() - _thinkingStartedAt) / 1000)
        );
        label.textContent = `Thought for ${secs}s`;
    }

    box.classList.remove("expanded");
    _thinkingStartedAt = null;
}


function _startThinkingClock() {
    _thinkingStartedAt = Date.now();
}


/* ------------------------------------------------------
   EventBus -> UI
   ------------------------------------------------------ */
function onTaskEvent(jsonPayload) {
    let event;
    try {
        event = JSON.parse(jsonPayload);
    } catch (e) {
        console.error("onTaskEvent: bad payload", e, jsonPayload);
        return;
    }

    const type = event.type;
    const payload = event.payload || {};

    if (type === "TASK_CREATED") return;

    if (type === "TASK_UPDATED") {
        if (payload.reasoning) {
            _addThoughtLine(
                "reasoning",
                String(payload.reasoning),
                { marker: "◇", isReplan: !!payload.replan }
            );
        }
        return;
    }

    if (type === "TOOL_STARTED") {
        const name = payload.display_name || payload.tool_id || "tool";
        _addThoughtLine("tool-start", name, { marker: "◐" });
        return;
    }

    if (type === "TOOL_COMPLETED") {
        const name = payload.display_name || payload.tool_id || "tool";
        _addThoughtLine("tool-ok", name, { marker: "✓" });
        return;
    }

    if (type === "TOOL_FAILED") {
        const name = payload.display_name || payload.tool_id || "tool";
        _addThoughtLine("tool-fail", name, { marker: "✕" });
        return;
    }

    if (type === "SYNTHESIS_CHUNK") {
        const chunk = payload.chunk || "";
        if (!chunk) return;
        if (typeof _handleSynthesisChunk === "function") {
            _handleSynthesisChunk(chunk);
        }
        return;
    }

    if (type === "TASK_COMPLETED" ||
        type === "TASK_FAILED" ||
        type === "TASK_CANCELLED") {
        _finalizeThought();
        if (typeof _finalizeSynthesis === "function") {
            _finalizeSynthesis();
        }
        return;
    }
}