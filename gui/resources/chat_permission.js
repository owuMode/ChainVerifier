"use strict";


/* =========================================================
   PERMISSION DIALOG (inline, with "Allow for chat")
   ========================================================= */

let permissionbridge = null;
let activePermissionRequest = null;
let permissionQueue = [];


function _bindPermissionBridge() {
    if (!window._rheaChannel || !window._rheaChannel.objects) {
        setTimeout(_bindPermissionBridge, 40);
        return;
    }
    permissionbridge = window._rheaChannel.objects.permissionbridge || null;
    if (!permissionbridge) {
        setTimeout(_bindPermissionBridge, 40);
        return;
    }
    if (typeof permissionbridge.permissionRequested.connect === "function") {
        permissionbridge.permissionRequested.connect(onPermissionRequested);
    }
    if (typeof permissionbridge.permissionResolved.connect === "function") {
        permissionbridge.permissionResolved.connect(onPermissionResolved);
    }
}


function onPermissionRequested(payloadJson) {
    let payload;
    try {
        payload = JSON.parse(payloadJson);
    } catch (e) {
        console.error("onPermissionRequested: bad payload", e, payloadJson);
        return;
    }
    if (activePermissionRequest) {
        permissionQueue.push(payload);
        return;
    }
    _showPermissionCard(payload);
}


function _showPermissionCard(payload) {
    const stale = document.querySelector(".permission-card");
    if (stale) { try { stale.remove(); } catch {} }

    const card = _renderPermissionCard(payload);
    _insertPermissionCard(card);

    activePermissionRequest = {
        request_id: payload.request_id,
        card,
        resolved: false,
        payload,
    };

    requestAnimationFrame(() => {
        try { card.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch {}
    });
}


function _showNextQueuedPermission() {
    if (permissionQueue.length === 0) return;
    const next = permissionQueue.shift();
    _showPermissionCard(next);
}


function onPermissionResolved(payloadJson) {
    let payload;
    try { payload = JSON.parse(payloadJson); } catch { return; }
    if (!activePermissionRequest) return;
    if (activePermissionRequest.request_id !== payload.request_id) return;
    if (activePermissionRequest.resolved) return;
    const kind = payload.decision === "deny" ? "denied" : "allowed";
    _finalizePermission(activePermissionRequest, kind);
}


function _renderPermissionCard(payload) {
    const card = document.createElement("div");
    card.className = "permission-card";
    card.dataset.requestId = payload.request_id || "";

    const header = document.createElement("div");
    header.className = "permission-header";
    const icon = document.createElement("div");
    icon.className = "permission-icon";
    icon.textContent = "⚠";

    const titleBox = document.createElement("div");
    titleBox.className = "permission-title-box";
    const title = document.createElement("div");
    title.className = "permission-title";
    title.textContent = "Rhea wants to modify files";
    const tool = document.createElement("div");
    tool.className = "permission-tool";
    tool.textContent = payload.tool_display_name || payload.tool_id || "tool";
    titleBox.appendChild(title);
    titleBox.appendChild(tool);
    header.appendChild(icon);
    header.appendChild(titleBox);
    card.appendChild(header);

    if (payload.preview) {
        const preview = document.createElement("div");
        preview.className = "permission-preview";
        preview.textContent = payload.preview;
        card.appendChild(preview);
    }

    const actions = document.createElement("div");
    actions.className = "permission-actions";

    const allowBtn = _button("Allow once", "allow");
    const allowChatBtn = _button("Allow for chat", "allow-chat");
    const denyBtn = _button("Deny", "deny");

    allowBtn.addEventListener("click", () => _userDecide("allow", allowBtn, allowChatBtn, denyBtn));
    allowChatBtn.addEventListener("click", () => _userDecide("allow_chat", allowBtn, allowChatBtn, denyBtn));
    denyBtn.addEventListener("click", () => _userDecide("deny", allowBtn, allowChatBtn, denyBtn));

    actions.appendChild(allowBtn);
    actions.appendChild(allowChatBtn);
    actions.appendChild(denyBtn);
    card.appendChild(actions);

    return card;
}


function _button(label, extraClass) {
    const btn = document.createElement("button");
    btn.className = "permission-btn" + (extraClass ? " " + extraClass : "");
    btn.textContent = label;
    return btn;
}


function _insertPermissionCard(card) {
    if (typeof activeTaskContainer !== "undefined" && activeTaskContainer) {
        const wrap = document.createElement("div");
        wrap.className = "permission-wrap";
        wrap.appendChild(card);
        activeTaskContainer.parentElement.appendChild(wrap);
        return;
    }
    const messages = document.querySelectorAll("#chatInner .message.ai");
    const last = messages[messages.length - 1];
    if (last) {
        const content = last.querySelector(".ai-content") || last;
        content.appendChild(card);
        return;
    }
    const inner = document.getElementById("chatInner");
    if (inner) inner.appendChild(card);
}


function _userDecide(decision, ...buttons) {
    const state = activePermissionRequest;
    if (!state || state.resolved) return;
    buttons.forEach(b => { if (b) b.disabled = true; });
    if (!permissionbridge) {
        _finalizePermission(state, "denied");
        return;
    }
    try {
        permissionbridge.resolve(state.request_id, decision);
    } catch (e) {
        console.error("permissionbridge.resolve failed", e);
    }
    const kind = decision === "deny" ? "denied" : "allowed";
    _finalizePermission(state, kind);
}


function _finalizePermission(state, kind) {
    if (!state || state.resolved) return;
    state.resolved = true;
    const card = state.card;
    if (!card) return;
    try { card.remove(); } catch {}
    if (activePermissionRequest === state) {
        activePermissionRequest = null;
    }
    setTimeout(() => _showNextQueuedPermission(), 50);
}


_bindPermissionBridge();