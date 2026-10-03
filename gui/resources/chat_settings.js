"use strict";


/* =========================================================
   SETTINGS PAGE — TABS, STORAGE, ABOUT
   ========================================================= */

let settingsbridge = null;

let currentSettingsTab = "general";


/* =========================================================
   BRIDGE BINDING
   ========================================================= */

function _bindSettingsBridge() {
    if (!window._rheaChannel || !window._rheaChannel.objects) {
        setTimeout(_bindSettingsBridge, 40);
        return;
    }

    settingsbridge = window._rheaChannel.objects.settingsbridge || null;

    if (!settingsbridge) {
        setTimeout(_bindSettingsBridge, 40);
        return;
    }

    _setupSettingsUI();
}


/* =========================================================
   TAB SWITCHING
   ========================================================= */

function showSettingsTab(tab) {
    if (!tab) return;
    currentSettingsTab = tab;

    document.querySelectorAll(".settings-tab").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    });

    document.querySelectorAll(".settings-pane").forEach(pane => {
        pane.classList.toggle("active", pane.dataset.pane === tab);
    });

    if (tab === "storage") {
        refreshStorageInfo();
    } else if (tab === "about") {
        refreshAboutInfo();
    } else if (tab === "providers") {
        if (typeof onSettingsOpened === "function") {
            onSettingsOpened();
        }
    } else if (tab === "memory") {
        if (typeof refreshMemorySection === "function") {
            refreshMemorySection();
        }
    }
}


/* =========================================================
   STORAGE
   ========================================================= */

async function refreshStorageInfo() {
    if (!settingsbridge) return;

    let data;
    try {
        const raw = await bridgeCall(settingsbridge, "getStorageInfoJson");
        data = JSON.parse(raw || "{}");
    } catch (e) {
        console.error("getStorageInfoJson failed", e);
        return;
    }

    const currentEl = document.getElementById("storageCurrentPath");
    const badgeEl = document.getElementById("storageBadge");
    const warnEl = document.getElementById("storageWarning");

    if (currentEl) currentEl.textContent = data.current_root || "—";
    if (badgeEl) {
        badgeEl.textContent = data.is_custom ? "Custom" : "Default";
        badgeEl.classList.toggle("default", !data.is_custom);
    }

    if (warnEl) {
        if (data.restart_required) {
            warnEl.style.display = "block";
            warnEl.textContent =
                "A new storage folder is pending. Restart Rhea to apply it.";
        } else {
            warnEl.style.display = "none";
            warnEl.textContent = "";
        }
    }
}


async function onStorageChoose() {
    if (!settingsbridge) return;

    let path = "";
    try {
        path = await bridgeCall(settingsbridge, "pickFolder");
    } catch (e) {
        console.error("pickFolder failed", e);
        showStorageStatus("Could not open folder picker.", "error");
        return;
    }

    if (!path) return;

    let valid;
    try {
        const raw = await bridgeCall(settingsbridge, "validateStoragePath", path);
        valid = JSON.parse(raw || "{}");
    } catch (e) {
        console.error("validateStoragePath failed", e);
        showStorageStatus("Could not validate the folder.", "error");
        return;
    }

    if (!valid.ok) {
        showStorageStatus(valid.reason || "This folder cannot be used.", "error");
        return;
    }

    let ok = false;
    try {
        ok = await bridgeCall(settingsbridge, "setCustomStorageRoot", path);
    } catch (e) {
        console.error("setCustomStorageRoot failed", e);
        showStorageStatus("Could not save the folder.", "error");
        return;
    }

    if (ok) {
        showStorageStatus("Saved. Restart Rhea to use the new folder.", "ok");
        refreshStorageInfo();
    } else {
        showStorageStatus("Could not save the folder.", "error");
    }
}


async function onStorageReset() {
    if (!settingsbridge) return;
    if (!confirm("Revert to the default storage folder? (Applies on restart)")) return;

    let ok = false;
    try {
        ok = await bridgeCall(settingsbridge, "setCustomStorageRoot", "");
    } catch (e) {
        console.error("setCustomStorageRoot('') failed", e);
    }

    if (ok) {
        showStorageStatus("Reverted to default. Restart Rhea to apply.", "ok");
        refreshStorageInfo();
    } else {
        showStorageStatus("Could not revert.", "error");
    }
}


function showStorageStatus(message, kind) {
    const el = document.getElementById("storageStatus");
    if (!el) return;
    el.textContent = message || "";
    el.className = "setting-status" + (kind ? " " + kind : "");
}


/* =========================================================
   ABOUT
   ========================================================= */

async function refreshAboutInfo() {
    if (!settingsbridge) return;

    let data;
    try {
        const raw = await bridgeCall(settingsbridge, "getAboutJson");
        data = JSON.parse(raw || "{}");
    } catch (e) {
        console.error("getAboutJson failed", e);
        return;
    }

    const container = document.getElementById("aboutBlock");
    if (!container) return;

    container.innerHTML = "";

    const rows = [
        ["App", data.app_name || "Rhea AI"],
        ["Version", data.app_version || "1.0.0"],
        ["Python", `${data.python_version || "?"} (${data.python_implementation || "?"})`],
        ["OS", `${data.os_name || "?"} ${data.os_release || ""}`.trim()],
        ["Build", data.os_version || "—"],
        ["Architecture", data.architecture || "—"],
        ["Executable", data.executable || "—"],
    ];

    rows.forEach(([label, value]) => {
        const row = document.createElement("div");
        row.className = "about-row";

        const lbl = document.createElement("div");
        lbl.className = "about-label";
        lbl.textContent = label;

        const val = document.createElement("div");
        val.className = "about-value";
        val.textContent = value;

        row.appendChild(lbl);
        row.appendChild(val);
        container.appendChild(row);
    });
}


/* =========================================================
   HOOK — called from chat.js when Settings is opened
   ========================================================= */

function onSettingsOpenedExtended() {
    showSettingsTab(currentSettingsTab);
}


/* =========================================================
   EVENTS
   ========================================================= */

function _setupSettingsUI() {
    document.querySelectorAll(".settings-tab").forEach(btn => {
        btn.addEventListener("click", () => showSettingsTab(btn.dataset.tab));
    });

    const chooseBtn = document.getElementById("storageChoose");
    const resetBtn = document.getElementById("storageReset");

    if (chooseBtn) chooseBtn.addEventListener("click", onStorageChoose);
    if (resetBtn) resetBtn.addEventListener("click", onStorageReset);
}


/* =========================================================
   STARTUP
   ========================================================= */

_bindSettingsBridge();