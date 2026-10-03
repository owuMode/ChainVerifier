"use strict";


/* =========================================================
   MODE PICKER (topbar)
   =========================================================
   Tool cards + reasoning now live inside chat.js as inline
   "thinking" lines inside the AI message. This file only owns
   the top-bar mode selector.
   ========================================================= */


const MODE_KEY = "rhea_mode";

const MODE_LABELS = {
    chat: "Chat",
    agent: "Agent",
    auto: "Auto"
};

let currentMode = "auto";


function loadModePreference() {
    const stored = localStorage.getItem(MODE_KEY);
    currentMode = (stored && MODE_LABELS[stored]) ? stored : "auto";
}


function saveModePreference() {
    try { localStorage.setItem(MODE_KEY, currentMode); } catch {}
}


function updateModeUI() {
    const labelEl = document.getElementById("modeLabel");
    if (labelEl) labelEl.textContent = MODE_LABELS[currentMode] || "Auto";

    document.querySelectorAll(".mode-option").forEach(opt => {
        const active = opt.dataset.mode === currentMode;
        opt.classList.toggle("active", active);
        const check = opt.querySelector(".mode-check");
        if (check) check.textContent = active ? "✓" : "";
    });
}


function selectMode(value) {
    if (!MODE_LABELS[value]) return;
    if (value === currentMode) { closeModeMenu(); return; }

    currentMode = value;
    updateModeUI();
    saveModePreference();

    whenBridgeReady(bridge => bridge.setMode(value));
    closeModeMenu();
}


function closeModeMenu() {
    const menu = document.getElementById("modeMenu");
    if (menu) menu.classList.remove("open");
}


function onModeChanged(mode) {
    if (MODE_LABELS[mode]) {
        currentMode = mode;
        updateModeUI();
        saveModePreference();
    }
}


function _setupModeUI() {
    const button = document.getElementById("modeButton");
    const menu = document.getElementById("modeMenu");
    if (!button || !menu) return;

    button.addEventListener("click", event => {
        event.stopPropagation();
        const modelMenu = document.getElementById("modelMenu");
        if (modelMenu) modelMenu.classList.remove("open");
        const moreMenu = document.getElementById("moreMenu");
        if (moreMenu) moreMenu.classList.remove("open");
        menu.classList.toggle("open");
    });

    document.querySelectorAll(".mode-option").forEach(opt => {
        opt.addEventListener("click", () => selectMode(opt.dataset.mode));
    });

    document.addEventListener("click", event => {
        if (!event.target.closest(".mode-area")) {
            closeModeMenu();
        }
    });
}


loadModePreference();

whenBridgeReady(bridge => bridge.setMode(currentMode));

requestAnimationFrame(() => {
    _setupModeUI();
    updateModeUI();
});