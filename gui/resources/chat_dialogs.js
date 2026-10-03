"use strict";

/* =========================================================
   CUSTOM DIALOGS
   =========================================================
   Browser-default confirm() and prompt() render OS-level
   dialogs with ugly titles ("Javascript Confirm - ...").
   These helpers show an in-app modal instead.
   ========================================================= */


function _ensureDialogRoot() {
    let root = document.getElementById("dialogRoot");
    if (root) return root;

    root = document.createElement("div");
    root.id = "dialogRoot";
    root.className = "dialog-overlay";
    root.innerHTML = `
        <div class="dialog-box" role="dialog" aria-modal="true">
            <div class="dialog-title" id="dialogTitle"></div>
            <div class="dialog-message" id="dialogMessage"></div>
            <input class="dialog-input" id="dialogInput" type="text" autocomplete="off" spellcheck="false">
            <div class="dialog-actions">
                <button class="dialog-button" id="dialogCancel">Cancel</button>
                <button class="dialog-button primary" id="dialogOk">OK</button>
            </div>
        </div>
    `;
    document.body.appendChild(root);
    return root;
}


function _hideDialog() {
    const root = document.getElementById("dialogRoot");
    if (root) root.classList.remove("open");
}


function showConfirm(message, title) {
    return new Promise((resolve) => {
        const root = _ensureDialogRoot();
        const titleEl = document.getElementById("dialogTitle");
        const msgEl = document.getElementById("dialogMessage");
        const inputEl = document.getElementById("dialogInput");
        const okBtn = document.getElementById("dialogOk");
        const cancelBtn = document.getElementById("dialogCancel");

        titleEl.textContent = title || "Confirm";
        msgEl.textContent = message || "";
        inputEl.style.display = "none";
        okBtn.textContent = "OK";
        cancelBtn.textContent = "Cancel";
        cancelBtn.style.display = "";

        // Fresh handlers (remove old ones by cloning).
        _resetHandlers(okBtn, cancelBtn, root, resolve, true);
        root.classList.add("open");
        requestAnimationFrame(() => okBtn.focus());
    });
}


function showPrompt(message, defaultValue, title) {
    return new Promise((resolve) => {
        const root = _ensureDialogRoot();
        const titleEl = document.getElementById("dialogTitle");
        const msgEl = document.getElementById("dialogMessage");
        const inputEl = document.getElementById("dialogInput");
        const okBtn = document.getElementById("dialogOk");
        const cancelBtn = document.getElementById("dialogCancel");

        titleEl.textContent = title || "Input";
        msgEl.textContent = message || "";
        inputEl.style.display = "";
        inputEl.value = defaultValue || "";
        okBtn.textContent = "Save";
        cancelBtn.textContent = "Cancel";
        cancelBtn.style.display = "";

        _resetHandlers(okBtn, cancelBtn, root, resolve, false, inputEl);
        root.classList.add("open");
        requestAnimationFrame(() => {
            inputEl.focus();
            inputEl.select();
        });
    });
}


function showAlert(message, title) {
    return new Promise((resolve) => {
        const root = _ensureDialogRoot();
        const titleEl = document.getElementById("dialogTitle");
        const msgEl = document.getElementById("dialogMessage");
        const inputEl = document.getElementById("dialogInput");
        const okBtn = document.getElementById("dialogOk");
        const cancelBtn = document.getElementById("dialogCancel");

        titleEl.textContent = title || "Notice";
        msgEl.textContent = message || "";
        inputEl.style.display = "none";
        okBtn.textContent = "OK";
        cancelBtn.style.display = "none";

        _resetHandlers(okBtn, cancelBtn, root, resolve, true);
        root.classList.add("open");
        requestAnimationFrame(() => okBtn.focus());
    });
}


function _resetHandlers(okBtn, cancelBtn, root, resolve, isConfirm, inputEl) {
    // Replace nodes with clones to strip old event listeners.
    const newOk = okBtn.cloneNode(true);
    const newCancel = cancelBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOk, okBtn);
    cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);

    const close = (value) => {
        _hideDialog();
        resolve(value);
    };

    newOk.addEventListener("click", () => {
        if (isConfirm) {
            close(true);
        } else if (inputEl) {
            close(String(inputEl.value || ""));
        } else {
            close(true);
        }
    });

    newCancel.addEventListener("click", () => {
        if (isConfirm) {
            close(false);
        } else {
            close(null);
        }
    });

    // Enter to submit, Escape to cancel.
    const onKey = (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            newOk.click();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            newCancel.click();
        }
    };

    if (inputEl) {
        inputEl.addEventListener("keydown", onKey);
    } else {
        root.addEventListener("keydown", onKey);
    }
}