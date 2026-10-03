"use strict";

/* =========================================================
   COPY HELPERS (message text + code blocks)
   ========================================================= */


/* ------------------------------------------------------
   Robust clipboard writer
   ------------------------------------------------------ */
async function _writeToClipboard(text) {
    const value = String(text == null ? "" : text);

    // 1. Modern clipboard API.
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(value);
            return true;
        }
    } catch (e) {
        console.warn("clipboard API failed, falling back", e);
    }

    // 2. execCommand fallback.
    try {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "0";
        document.body.appendChild(ta);
        ta.select();
        ta.setSelectionRange(0, value.length);
        const ok = document.execCommand("copy");
        ta.remove();
        return ok;
    } catch (e) {
        console.error("execCommand copy failed", e);
        return false;
    }
}


/* ------------------------------------------------------
   Copy text + visual feedback on the given button
   ------------------------------------------------------ */
async function copyText(text, button) {
    const ok = await _writeToClipboard(text);
    if (!button) return;
    const old = button.textContent;
    button.textContent = ok ? "✓" : "✕";
    setTimeout(() => { button.textContent = old; }, 900);
}


/* ------------------------------------------------------
   Bind copy buttons inside fenced code blocks
   ------------------------------------------------------ */
function bindCodeCopyButtons(container) {
    if (!container) return;
    container.querySelectorAll(".md-code-copy").forEach((btn) => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const targetId = btn.dataset.copyTarget;
            const pre = document.getElementById(targetId);
            if (!pre) return;
            const code = pre.querySelector("code");
            const text = (code ? code.textContent : pre.textContent) || "";
            copyText(text, btn);
        });
    });
}