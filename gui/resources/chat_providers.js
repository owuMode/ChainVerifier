"use strict";

/* =========================================================
   PROVIDER + MODEL MANAGEMENT
   =========================================================
   Adds:
     * Real model list in the topbar model picker (per provider).
     * A "Providers" section inside Settings:
         - provider dropdown
         - API key input + save/delete
         - "Test connection" button
         - current-model display
         - "Restart to apply" hint when the provider changes

   Model changes apply live. Provider changes take effect on the
   next application start.

   Depends on:
     * chat.js        — provides `whenBridgeReady`, `bridgeCall`, `$`
     * providerbridge — Python object registered with QWebChannel
   ========================================================= */

let providerbridge = null;
let allProviders = [];
let currentProviderKey = "";      // active provider (from backend)
let selectedProviderKey = "";     // provider selected in the dropdown
let currentModelId = "";


/* =========================================================
   BRIDGE BINDING
   ========================================================= */

function _bindProviderBridge() {
    if (!window._rheaChannel || !window._rheaChannel.objects) {
        setTimeout(_bindProviderBridge, 40);
        return;
    }

    providerbridge = window._rheaChannel.objects.providerbridge || null;

    if (!providerbridge) {
        setTimeout(_bindProviderBridge, 40);
        return;
    }

    _setupProviderUI();

    (async () => {
        await loadProviders();
        await loadActiveProvider();
        await loadCurrentModel();
        await renderModelPicker();
        await renderProviderSection();
    })();
}


/* =========================================================
   DATA LOADING
   ========================================================= */

async function loadProviders() {
    try {
        const raw = await bridgeCall(providerbridge, "listProvidersJson");
        allProviders = JSON.parse(raw || "[]");
    } catch (e) {
        console.error("loadProviders failed", e);
        allProviders = [];
    }
}


async function loadActiveProvider() {
    try {
        const raw = await bridgeCall(providerbridge, "getActiveProviderJson");
        const obj = JSON.parse(raw || "{}");
        currentProviderKey = obj.key || "";
        // By default, the dropdown reflects the active provider.
        if (!selectedProviderKey) {
            selectedProviderKey = currentProviderKey;
        }
    } catch (e) {
        console.error("loadActiveProvider failed", e);
        currentProviderKey = "";
    }
}


async function loadCurrentModel() {
    try {
        currentModelId = await bridgeCall(providerbridge, "getCurrentModel");
    } catch (e) {
        console.error("loadCurrentModel failed", e);
        currentModelId = "";
    }
}


async function loadModelsFor(providerKey) {
    try {
        const raw = await bridgeCall(providerbridge, "listModelsJson", providerKey);
        return JSON.parse(raw || "[]");
    } catch (e) {
        console.error("loadModelsFor failed", e);
        return [];
    }
}


/* =========================================================
   MODEL PICKER (topbar)
   ========================================================= */

async function renderModelPicker() {
    const menu = document.getElementById("modelMenu");
    const labelEl = document.getElementById("modelLabel");
    if (!menu || !labelEl) return;

    const models = await loadModelsFor(currentProviderKey);

    if (!models.length) {
        menu.innerHTML = `
            <div class="model-option" data-empty="true">
                No models — configure a provider in Settings
            </div>
        `;
        labelEl.textContent = currentProviderKey ? "No models" : "No provider";
        return;
    }

    // Ensure currentModelId is valid for the active provider.
    if (!currentModelId || !models.some(m => m.id === currentModelId)) {
        const def = models.find(m => m.is_default) || models[0];
        currentModelId = def.id;
        try {
            await bridgeCall(providerbridge, "setCurrentModel", currentModelId);
        } catch (e) {
            console.error("setCurrentModel failed", e);
        }
    }

    const current = models.find(m => m.id === currentModelId);
    labelEl.textContent = current ? (current.name || current.id) : currentModelId;

    menu.innerHTML = "";
    models.forEach(m => {
        const button = document.createElement("button");
        button.className = "model-option" + (m.id === currentModelId ? " active" : "");
        button.dataset.modelId = m.id;

        const icon = document.createElement("span");
        icon.className = "model-option-icon";
        icon.textContent = (m.name || "?").charAt(0).toUpperCase();

        const info = document.createElement("span");
        info.className = "model-option-info";

        const title = document.createElement("span");
        title.className = "model-option-title";
        title.textContent = m.name || m.id;

        const desc = document.createElement("span");
        desc.className = "model-option-desc";
        desc.textContent = m.description || "";

        info.appendChild(title);
        info.appendChild(desc);

        const check = document.createElement("span");
        check.className = "model-check";
        check.textContent = m.id === currentModelId ? "✓" : "";

        button.appendChild(icon);
        button.appendChild(info);
        button.appendChild(check);

        button.addEventListener("click", () => selectRealModel(m.id));
        menu.appendChild(button);
    });
}


async function selectRealModel(modelId) {
    if (modelId === currentModelId) {
        closeMenus();
        return;
    }
    currentModelId = modelId;

    try {
        await bridgeCall(providerbridge, "setCurrentModel", modelId);
    } catch (e) {
        console.error("setCurrentModel failed", e);
    }

    whenBridgeReady(bridge => bridge.setModel(modelId));

    await renderModelPicker();
    closeMenus();
}


/* =========================================================
   SETTINGS — PROVIDER SECTION
   ========================================================= */

function renderProviderSection() {
    const selectEl = document.getElementById("providerSelect");
    const apiInput = document.getElementById("apiKeyInput");
    const statusEl = document.getElementById("providerStatus");
    const hintEl = document.getElementById("providerHint");
    const restartEl = document.getElementById("providerRestartHint");
    if (!selectEl || !apiInput) return;

    // Populate the dropdown.
    selectEl.innerHTML = "";
    allProviders.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.key;
        opt.textContent = p.name + (p.has_api_key ? " (key set)" : "");
        selectEl.appendChild(opt);
    });

    if (selectedProviderKey) {
        selectEl.value = selectedProviderKey;
    }

    // Update hint with the docs URL for the selected provider.
    const preset = allProviders.find(p => p.key === selectedProviderKey);
    if (hintEl) {
        if (preset && preset.docs_url) {
            hintEl.innerHTML =
                `Get a key: <a href="${preset.docs_url}" target="_blank" rel="noopener">${preset.docs_url}</a>`;
        } else {
            hintEl.textContent = "Enter the API key for this provider.";
        }
    }

    // API key input placeholder.
    apiInput.value = "";
    apiInput.placeholder = preset && preset.has_api_key ? "•••• (saved)" : "Paste API key";

    // Clear status.
    if (statusEl) {
        statusEl.textContent = "";
        statusEl.className = "setting-status";
    }

    // "Restart to apply" hint — only when selection != active.
    if (restartEl) {
        if (selectedProviderKey && selectedProviderKey !== currentProviderKey) {
            restartEl.textContent =
                "Restart Rhea to apply the new provider.";
            restartEl.style.display = "block";
        } else {
            restartEl.textContent = "";
            restartEl.style.display = "none";
        }
    }

    // Current model display.
    updateCurrentModelDisplay();
}


function updateCurrentModelDisplay() {
    const el = document.getElementById("currentModelDisplay");
    if (!el) return;
    el.textContent = currentModelId || "(default)";
}


/* =========================================================
   ACTIONS
   ========================================================= */

async function onProviderChanged() {
    const selectEl = document.getElementById("providerSelect");
    if (!selectEl) return;

    const key = selectEl.value;
    if (!key) return;

    selectedProviderKey = key;

    // Update the docs hint + restart hint immediately.
    const preset = allProviders.find(p => p.key === key);
    const hintEl = document.getElementById("providerHint");
    if (hintEl) {
        if (preset && preset.docs_url) {
            hintEl.innerHTML =
                `Get a key: <a href="${preset.docs_url}" target="_blank" rel="noopener">${preset.docs_url}</a>`;
        } else {
            hintEl.textContent = "Enter the API key for this provider.";
        }
    }

    const apiInput = document.getElementById("apiKeyInput");
    if (apiInput) {
        apiInput.value = "";
        apiInput.placeholder = preset && preset.has_api_key ? "•••• (saved)" : "Paste API key";
    }

    const restartEl = document.getElementById("providerRestartHint");
    if (restartEl) {
        if (key !== currentProviderKey) {
            restartEl.textContent =
                "Restart Rhea to apply the new provider.";
            restartEl.style.display = "block";
        } else {
            restartEl.textContent = "";
            restartEl.style.display = "none";
        }
    }

    // Persist to backend.
    const ok = await bridgeCall(providerbridge, "setActiveProvider", key);
    if (!ok) {
        showProviderStatus("Could not switch provider.", "error");
        return;
    }

    // Refresh providers (has_api_key flags might change).
    await loadProviders();
    showProviderStatus("Provider saved.", "ok");
}


async function onSaveApiKey() {
    const input = document.getElementById("apiKeyInput");
    const key = selectedProviderKey;
    if (!input || !key) return;

    const value = input.value.trim();
    if (!value) {
        showProviderStatus("Paste an API key first.", "error");
        return;
    }

    const ok = await bridgeCall(providerbridge, "setApiKey", key, value);
    if (ok) {
        input.value = "";
        showProviderStatus("API key saved.", "ok");
        await loadProviders();
        // Keep the selected provider, just refresh dropdown labels.
        const selectEl = document.getElementById("providerSelect");
        if (selectEl) selectEl.value = key;
        const preset = allProviders.find(p => p.key === key);
        input.placeholder = preset && preset.has_api_key ? "•••• (saved)" : "Paste API key";
    } else {
        showProviderStatus("Could not save API key.", "error");
    }
}


async function onDeleteApiKey() {
    const key = selectedProviderKey;
    if (!key) return;
    if (!confirm("Delete the stored API key for this provider?")) return;

    const ok = await bridgeCall(providerbridge, "deleteApiKey", key);
    if (ok) {
        showProviderStatus("API key deleted.", "ok");
        await loadProviders();
        const selectEl = document.getElementById("providerSelect");
        if (selectEl) selectEl.value = key;
        const apiInput = document.getElementById("apiKeyInput");
        if (apiInput) apiInput.placeholder = "Paste API key";
    } else {
        showProviderStatus("Could not delete API key.", "error");
    }
}


async function onTestConnection() {
    const key = selectedProviderKey;
    if (!key) return;

    showProviderStatus("Testing…", "");

    let raw = "";
    try {
        raw = await bridgeCall(providerbridge, "testConnection", key);
    } catch (e) {
        showProviderStatus("Test failed: " + e, "error");
        return;
    }

    let result;
    try {
        result = JSON.parse(raw || "{}");
    } catch {
        result = { ok: false, message: "Bad response" };
    }

    showProviderStatus(
        result.message || (result.ok ? "Connected" : "Failed"),
        result.ok ? "ok" : "error"
    );
}


function showProviderStatus(message, kind) {
    const el = document.getElementById("providerStatus");
    if (!el) return;
    el.textContent = message || "";
    el.className = "setting-status" + (kind ? " " + kind : "");
}


/* =========================================================
   HOOK — called when Settings opens
   ========================================================= */

function onSettingsOpened() {
    (async () => {
        await loadProviders();
        await loadActiveProvider();
        await loadCurrentModel();
        await renderProviderSection();
    })();
}


/* =========================================================
   EVENTS
   ========================================================= */

function _setupProviderUI() {
    const selectEl = document.getElementById("providerSelect");
    const saveBtn = document.getElementById("apiKeySave");
    const delBtn = document.getElementById("apiKeyDelete");
    const testBtn = document.getElementById("providerTest");

    if (selectEl) selectEl.addEventListener("change", onProviderChanged);
    if (saveBtn) saveBtn.addEventListener("click", onSaveApiKey);
    if (delBtn) delBtn.addEventListener("click", onDeleteApiKey);
    if (testBtn) testBtn.addEventListener("click", onTestConnection);
}


/* =========================================================
   SIGNALS FROM PYTHON
   ========================================================= */

function onProviderChangedFromPython(key) {
    currentProviderKey = key;
    selectedProviderKey = key;
    (async () => {
        await loadProviders();
        await loadCurrentModel();
        await renderModelPicker();
        await renderProviderSection();
    })();
}


function onApiKeyChangedFromPython(_key) {
    (async () => {
        await loadProviders();
        // Keep dropdown selection stable.
        const selectEl = document.getElementById("providerSelect");
        if (selectEl && selectedProviderKey) {
            selectEl.value = selectedProviderKey;
        }
    })();
}


/* =========================================================
   STARTUP
   ========================================================= */

_bindProviderBridge();