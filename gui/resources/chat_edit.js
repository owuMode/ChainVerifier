"use strict";

/* =========================================================
   INLINE MESSAGE EDIT (DeepSeek / ChatGPT style)
   =========================================================
   Edit a user message in place. Save re-sends from that point.
   Never opens a modal.
   ========================================================= */


function _startEditMessage(index) {
    if (typeof generating !== "undefined" && generating) return;
    if (typeof messages === "undefined") return;
    if (typeof index !== "number") return;

    const msg = messages[index];
    if (!msg || msg.role !== "user") return;

    // If another edit is already open, close it first.
    _cancelEditMessage(true);

    const inner = document.getElementById("chatInner");
    if (!inner) return;

    const wrapper = inner.querySelector(
        `.message.user[data-msg-index="${index}"]`
    );
    if (!wrapper) return;

    const bubble = wrapper.querySelector(".user-bubble");
    if (!bubble) return;

    wrapper.classList.add("editing");
    bubble.classList.add("editing");

    // Preserve the original HTML so we can restore on Cancel.
    bubble.dataset.originalHtml = bubble.innerHTML;

    bubble.innerHTML = "";

    const ta = document.createElement("textarea");
    ta.className = "user-edit-input";
    ta.value = msg.text || "";
    ta.spellcheck = false;

    const actions = document.createElement("div");
    actions.className = "user-edit-actions";

    const cancel = document.createElement("button");
    cancel.className = "user-edit-button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => _cancelEditMessage(false));

    const save = document.createElement("button");
    save.className = "user-edit-button primary";
    save.textContent = "Save & resend";

    const doSave = () => {
        const newText = (ta.value || "").trim();
        if (!newText) return;
        if (newText === (msg.text || "").trim()) {
            _cancelEditMessage(false);
            return;
        }
        _saveEditAndResend(index, newText);
    };

    save.addEventListener("click", doSave);

    ta.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") {
            ev.preventDefault();
            _cancelEditMessage(false);
            return;
        }
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            doSave();
        }
    });

    actions.appendChild(cancel);
    actions.appendChild(save);

    bubble.appendChild(ta);
    bubble.appendChild(actions);

    // Auto-grow + focus.
    const autosize = () => {
        ta.style.height = "auto";
        const h = Math.max(56, Math.min(ta.scrollHeight, 240));
        ta.style.height = h + "px";
    };
    ta.addEventListener("input", autosize);

    requestAnimationFrame(() => {
        autosize();
        ta.focus();
        // Put cursor at the end.
        ta.setSelectionRange(ta.value.length, ta.value.length);
    });
}


function _cancelEditMessage(silent) {
    const inner = document.getElementById("chatInner");
    if (!inner) return;

    const wrapper = inner.querySelector(".message.user.editing");
    if (!wrapper) return;

    const bubble = wrapper.querySelector(".user-bubble");
    if (!bubble) return;

    const originalHtml = bubble.dataset.originalHtml || "";
    if (!silent && originalHtml) {
        bubble.innerHTML = originalHtml;
    }

    wrapper.classList.remove("editing");
    bubble.classList.remove("editing");
    delete bubble.dataset.originalHtml;
}


function _saveEditAndResend(index, newText) {
    // Close the editor first.
    _cancelEditMessage(true);

    // Trim the conversation to just before this message.
    messages = messages.slice(0, index);

    // Re-render and send the edited text.
    if (typeof renderMessages === "function") renderMessages();

    const input = document.getElementById("messageInput");
    if (input) {
        input.value = newText;
        if (typeof resizeInput === "function") resizeInput();
    }

    if (typeof sendMessage === "function") {
        sendMessage();
    }
}


/* =========================================================
   Hook into the global edit button
   =========================================================
   chat.js's createMessage() calls window.editMessage(index)
   when the user clicks the edit button. We expose that here.
   ========================================================= */

window.editMessage = function (index) {
    _startEditMessage(index);
};