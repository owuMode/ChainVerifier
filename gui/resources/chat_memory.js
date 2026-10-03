"use strict";


/* =========================================================
   MEMORY SETTINGS UI — dashboard with stats, search, sort
   ========================================================= */

let memorybridge = null;
let _memorySort = "importance";
let _memorySearch = "";


function _bindMemoryBridge() {
    if (!window._rheaChannel || !window._rheaChannel.objects) {
        setTimeout(_bindMemoryBridge, 40);
        return;
    }
    memorybridge = window._rheaChannel.objects.memorybridge || null;
    if (!memorybridge) {
        setTimeout(_bindMemoryBridge, 40);
        return;
    }

    if (typeof memorybridge.memoryChanged.connect === "function") {
        memorybridge.memoryChanged.connect(() => refreshMemorySection());
    }
    if (typeof memorybridge.enabledChanged.connect === "function") {
        memorybridge.enabledChanged.connect((enabled) => {
            const toggle = document.getElementById("memoryEnabledSwitch");
            if (toggle) toggle.classList.toggle("active", !!enabled);
        });
    }
    if (typeof memorybridge.continuityChanged.connect === "function") {
        memorybridge.continuityChanged.connect((enabled) => {
            const toggle = document.getElementById("memoryContinuitySwitch");
            if (toggle) toggle.classList.toggle("active", !!enabled);
        });
    }
    if (typeof memorybridge.expanderChanged.connect === "function") {
        memorybridge.expanderChanged.connect((enabled) => {
            const toggle = document.getElementById("memoryExpanderSwitch");
            if (toggle) toggle.classList.toggle("active", !!enabled);
        });
    }
}


function onMemoryEnabledChanged(enabled) {
    const toggle = document.getElementById("memoryEnabledSwitch");
    if (toggle) toggle.classList.toggle("active", !!enabled);
}


async function refreshMemorySection() {
    if (!memorybridge) return;

    // Master toggles
    try {
        const enabled = await bridgeCall(memorybridge, "isEnabled");
        const t = document.getElementById("memoryEnabledSwitch");
        if (t) t.classList.toggle("active", !!enabled);
    } catch (e) { console.error(e); }

    try {
        const enabled = await bridgeCall(memorybridge, "isContinuityEnabled");
        const t = document.getElementById("memoryContinuitySwitch");
        if (t) t.classList.toggle("active", !!enabled);
    } catch (e) { console.error(e); }

    try {
        const enabled = await bridgeCall(memorybridge, "isExpanderEnabled");
        const t = document.getElementById("memoryExpanderSwitch");
        if (t) t.classList.toggle("active", !!enabled);
    } catch (e) { console.error(e); }

    // Stats
    let stats = { total: 0, embedded: 0, recent_7d: 0 };
    try {
        const raw = await bridgeCall(memorybridge, "getStatsJson");
        stats = JSON.parse(raw || "{}");
    } catch (e) { console.error(e); }
    const totalEl = document.getElementById("memoryStatTotal");
    const embEl = document.getElementById("memoryStatEmbedded");
    const recentEl = document.getElementById("memoryStatRecent");
    if (totalEl) totalEl.textContent = String(stats.total || 0);
    if (embEl) embEl.textContent = String(stats.embedded || 0);
    if (recentEl) recentEl.textContent = String(stats.recent_7d || 0);

    // List
    const kindFilter = document.getElementById("memoryKindFilter");
    const kind = kindFilter ? kindFilter.value : "";

    let items = [];
    try {
        if (_memorySearch && _memorySearch.trim()) {
            const raw = await bridgeCall(memorybridge, "searchJson", _memorySearch.trim());
            items = JSON.parse(raw || "[]");
        } else {
            const raw = await bridgeCall(memorybridge, "listJson", kind);
            items = JSON.parse(raw || "[]");
        }
    } catch (e) { console.error(e); }

    // Client-side filter + sort
    if (kind) {
        items = items.filter(m => m.kind === kind);
    }
    items = _sortMemories(items, _memorySort);

    const list = document.getElementById("memoryList");
    if (!list) return;

    if (!items.length) {
        list.innerHTML = `
            <div class="memory-empty">
                No memories yet. Ask Rhea to remember something.
            </div>
        `;
        return;
    }

    list.innerHTML = "";
    items.forEach(m => list.appendChild(_renderMemoryItem(m)));
}


function _sortMemories(items, sortKey) {
    const copy = items.slice();
    if (sortKey === "importance") {
        copy.sort((a, b) => (b.importance || 0) - (a.importance || 0));
    } else if (sortKey === "recent") {
        copy.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    } else if (sortKey === "used") {
        copy.sort((a, b) => (b.use_count || 0) - (a.use_count || 0));
    }
    return copy;
}


function _renderMemoryItem(m) {
    const item = document.createElement("div");
    item.className = "memory-item" + (m.archived_at ? " archived" : "");

    const kind = document.createElement("div");
    kind.className = "memory-item-kind";
    kind.textContent = m.kind || "other";

    const content = document.createElement("div");
    content.className = "memory-item-content";

    const text = document.createElement("div");
    text.textContent = m.content;

    const meta = document.createElement("div");
    meta.className = "memory-item-meta";
    const imp = m.importance || 3;
    const used = m.use_count || 0;
    meta.textContent = `imp ${imp} · used ${used} · ${(m.source || "").toUpperCase()}`;

    content.appendChild(text);
    content.appendChild(meta);

    const forget = document.createElement("button");
    forget.className = "memory-item-action danger";
    forget.title = m.archived_at ? "Restore" : "Forget";
    forget.textContent = m.archived_at ? "↻" : "✕";
    forget.addEventListener("click", async () => {
        if (m.archived_at) {
            await bridgeCall(memorybridge, "restore", m.memory_id);
        } else {
            await bridgeCall(memorybridge, "forget", m.memory_id);
        }
    });

    item.appendChild(kind);
    item.appendChild(content);
    item.appendChild(forget);
    return item;
}


async function onMemoryAdd() {
    if (!memorybridge) return;
    const contentEl = document.getElementById("memoryNewContent");
    const kindEl = document.getElementById("memoryNewKind");
    if (!contentEl) return;
    const content = contentEl.value.trim();
    if (!content) return;
    const kind = kindEl ? kindEl.value : "fact";
    try {
        await bridgeCall(memorybridge, "remember", content, kind, 4);
        contentEl.value = "";
    } catch (e) { console.error("remember failed", e); }
}


async function onMemoryClearAll() {
    if (!memorybridge) return;
    if (!confirm("Clear all memories? This cannot be undone from the UI.")) return;
    try {
        await bridgeCall(memorybridge, "clearAll");
    } catch (e) { console.error("clearAll failed", e); }
}


function _setupMemoryUI() {
    const addBtn = document.getElementById("memoryAddButton");
    const clearBtn = document.getElementById("memoryClearButton");
    const reembedBtn = document.getElementById("memoryReembedButton");
    const consolidateBtn = document.getElementById("memoryConsolidateButton");
    const mainToggle = document.getElementById("memoryEnabledSwitch");
    const contToggle = document.getElementById("memoryContinuitySwitch");
    const expToggle = document.getElementById("memoryExpanderSwitch");
    const kindFilter = document.getElementById("memoryKindFilter");
    const sortSelect = document.getElementById("memorySort");
    const searchInput = document.getElementById("memorySearchInput");

    if (addBtn) addBtn.addEventListener("click", onMemoryAdd);
    if (clearBtn) clearBtn.addEventListener("click", onMemoryClearAll);
    if (reembedBtn) reembedBtn.addEventListener("click", onMemoryReembed);
    if (consolidateBtn) consolidateBtn.addEventListener("click", onMemoryConsolidate);

    if (mainToggle) {
        mainToggle.addEventListener("click", async () => {
            if (!memorybridge) return;
            const now = mainToggle.classList.contains("active");
            const ok = await bridgeCall(memorybridge, "setEnabled", !now);
            if (ok) mainToggle.classList.toggle("active", !now);
        });
    }

    if (contToggle) {
        contToggle.addEventListener("click", async () => {
            if (!memorybridge) return;
            const now = contToggle.classList.contains("active");
            const ok = await bridgeCall(memorybridge, "setContinuityEnabled", !now);
            if (ok) contToggle.classList.toggle("active", !now);
        });
    }

    if (expToggle) {
        expToggle.addEventListener("click", async () => {
            if (!memorybridge) return;
            const now = expToggle.classList.contains("active");
            const ok = await bridgeCall(memorybridge, "setExpanderEnabled", !now);
            if (ok) expToggle.classList.toggle("active", !now);
        });
    }

    if (kindFilter) {
        kindFilter.addEventListener("change", () => refreshMemorySection());
    }

    if (sortSelect) {
        sortSelect.addEventListener("change", () => {
            _memorySort = sortSelect.value || "importance";
            refreshMemorySection();
        });
    }

    if (searchInput) {
        let debounce = null;
        searchInput.addEventListener("input", () => {
            if (debounce) clearTimeout(debounce);
            debounce = setTimeout(() => {
                _memorySearch = searchInput.value || "";
                refreshMemorySection();
            }, 250);
        });
    }
}


/* =========================================================
   TOAST
   ========================================================= */

let _memoryToastTimer = null;

function onMemoryRemembered(count) {
    const n = parseInt(count, 10) || 0;
    if (n <= 0) return;

    let toast = document.getElementById("memoryToast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "memoryToast";
        toast.className = "memory-toast";
        toast.innerHTML = `
            <span class="memory-toast-icon">🧠</span>
            <span id="memoryToastText"></span>
        `;
        document.body.appendChild(toast);
    }

    const textEl = document.getElementById("memoryToastText");
    if (textEl) {
        textEl.textContent = n === 1
            ? "Remembered 1 fact"
            : `Remembered ${n} facts`;
    }

    toast.classList.add("show");

    if (_memoryToastTimer) clearTimeout(_memoryToastTimer);
    _memoryToastTimer = setTimeout(() => {
        toast.classList.remove("show");
    }, 2600);
}


/* =========================================================
   RE-EMBED / CONSOLIDATE
   ========================================================= */

async function onMemoryReembed() {
    if (!memorybridge) return;
    const btn = document.getElementById("memoryReembedButton");
    const status = document.getElementById("memoryReembedStatus");
    if (btn) btn.disabled = true;
    if (status) {
        status.textContent = "Re-embedding…";
        status.className = "setting-status";
    }

    let done = 0;
    try {
        done = await bridgeCall(memorybridge, "reembedAll");
    } catch (e) { console.error("reembedAll failed", e); }

    if (status) {
        status.textContent = `Re-embedded ${done} memories.`;
        status.className = "setting-status ok";
    }
    if (btn) btn.disabled = false;
}


async function onMemoryConsolidate() {
    if (!memorybridge) return;
    const btn = document.getElementById("memoryConsolidateButton");
    const status = document.getElementById("memoryConsolidateStatus");
    if (btn) btn.disabled = true;
    if (status) {
        status.textContent = "Consolidating…";
        status.className = "setting-status";
    }

    let raw = "{}";
    try {
        raw = await bridgeCall(memorybridge, "consolidate");
    } catch (e) { console.error("consolidate failed", e); }

    let stats = {};
    try { stats = JSON.parse(raw || "{}"); } catch {}

    const merged = stats.groups_merged || 0;
    const archived = stats.memories_archived || 0;
    const created = stats.memories_created || 0;
    const found = stats.groups_found || 0;

    if (status) {
        if (stats.errors && !merged) {
            status.textContent = stats.reason || "Consolidation failed.";
            status.className = "setting-status error";
        } else if (found === 0) {
            status.textContent = "No similar memories to merge.";
            status.className = "setting-status";
        } else {
            status.textContent =
                `Merged ${merged} group(s) of ${found}. ` +
                `${archived} archived, ${created} new.`;
            status.className = "setting-status ok";
        }
    }
    if (btn) btn.disabled = false;
    refreshMemorySection();
}


_bindMemoryBridge();
requestAnimationFrame(() => _setupMemoryUI());