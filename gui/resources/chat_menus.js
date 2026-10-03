"use strict";

/* =========================================================
   MENUS / CONTEXT MENU / SEARCH / SETTINGS HOOKS
   ========================================================= */


/* ------------------------------------------------------
   Model menu
   ------------------------------------------------------ */
const _modelButton = document.getElementById("modelButton");
if (_modelButton) {
    _modelButton.addEventListener("click", (event) => {
        event.stopPropagation();
        const more = document.getElementById("moreMenu");
        if (more) more.classList.remove("open");
        const mode = document.getElementById("modeMenu");
        if (mode) mode.classList.remove("open");
        const menu = document.getElementById("modelMenu");
        if (menu) menu.classList.toggle("open");
    });
}


/* ------------------------------------------------------
   More menu
   ------------------------------------------------------ */
const _moreButton = document.getElementById("moreButton");
if (_moreButton) {
    _moreButton.addEventListener("click", (event) => {
        event.stopPropagation();
        const modelMenu = document.getElementById("modelMenu");
        if (modelMenu) modelMenu.classList.remove("open");
        const modeMenu = document.getElementById("modeMenu");
        if (modeMenu) modeMenu.classList.remove("open");
        const more = document.getElementById("moreMenu");
        if (more) more.classList.toggle("open");
    });
}


/* ------------------------------------------------------
   Chat context menu (right-click on a history item)
   ------------------------------------------------------ */
let _ctxMenuChatId = null;


function openChatContextMenu(x, y, chatId) {
    _ctxMenuChatId = chatId;
    const menu = document.getElementById("chatContextMenu");
    if (!menu) return;

    menu.style.left = x + "px";
    menu.style.top = y + "px";
    menu.classList.add("open");

    requestAnimationFrame(() => {
        const rect = menu.getBoundingClientRect();
        const winW = window.innerWidth;
        const winH = window.innerHeight;
        let newX = x;
        let newY = y;
        if (rect.right > winW - 8) newX = Math.max(8, winW - rect.width - 8);
        if (rect.bottom > winH - 8) newY = Math.max(8, winH - rect.height - 8);
        menu.style.left = newX + "px";
        menu.style.top = newY + "px";
    });
}


function closeChatContextMenu() {
    const menu = document.getElementById("chatContextMenu");
    if (menu) menu.classList.remove("open");
    _ctxMenuChatId = null;
}


/* ------------------------------------------------------
   Context menu actions
   ------------------------------------------------------ */
async function _onCtxRename() {
    const chatId = _ctxMenuChatId;
    closeChatContextMenu();
    if (!chatId) return;

    if (typeof chats === "undefined") return;
    const chat = chats.find((c) => c.id === chatId);
    const current = chat ? (chat.title || "") : "";

    const next = await showPrompt(
        "Enter a new title for this chat:",
        current,
        "Rename chat"
    );
    if (next === null) return;
    const trimmed = String(next).trim();
    if (!trimmed) return;

    try {
        await bridgeCall(historybridge, "renameConversation", chatId, trimmed);
    } catch (e) {
        console.error("renameConversation failed", e);
    }
    if (typeof onConversationsChanged === "function") {
        await onConversationsChanged();
    }
}


async function _onCtxDelete() {
    const chatId = _ctxMenuChatId;
    closeChatContextMenu();
    if (!chatId) return;

    const chat = (typeof chats !== "undefined") ? chats.find((c) => c.id === chatId) : null;
    const title = chat ? (chat.title || "this chat") : "this chat";

    const ok = await showConfirm(
        `Delete "${title}"? This cannot be undone.`,
        "Delete chat"
    );
    if (!ok) return;

    try {
        await bridgeCall(historybridge, "deleteConversation", chatId);
    } catch (e) {
        console.error("deleteConversation failed", e);
        return;
    }

    if (typeof currentId !== "undefined" && chatId === currentId) {
        currentId = null;
        messages = [];
        if (typeof renderMessages === "function") renderMessages();
        if (typeof _notifyActiveConversation === "function") {
            _notifyActiveConversation("");
        }
    }

    if (typeof onConversationsChanged === "function") {
        await onConversationsChanged();
    }
}


/* ------------------------------------------------------
   Search
   ------------------------------------------------------ */
function openSearch() {
    if (typeof closeMenus === "function") closeMenus();
    const overlay = document.getElementById("searchOverlay");
    if (overlay) overlay.classList.add("open");
    const input = document.getElementById("searchInput");
    if (input) input.value = "";
    if (typeof renderSearch === "function") renderSearch("");
    setTimeout(() => {
        if (input) input.focus();
    }, 20);
}


function renderSearch(query) {
    const results = document.getElementById("searchResults");
    if (!results) return;
    results.innerHTML = "";
    if (typeof chats === "undefined") return;

    const q = String(query || "").trim().toLowerCase();
    const found = chats.filter((chat) => {
        if (!q) return true;
        return String(chat.title || "").toLowerCase().includes(q);
    });

    if (!found.length) {
        const empty = document.createElement("div");
        empty.className = "history-empty";
        empty.textContent = "No conversations found";
        results.appendChild(empty);
        return;
    }

    found.forEach((chat) => {
        const button = document.createElement("button");
        button.className = "history-item";

        const icon = document.createElement("span");
        icon.className = "history-item-icon";
        icon.textContent = "💬";

        const title = document.createElement("span");
        title.className = "history-item-title";
        title.textContent = chat.title || "New chat";

        button.appendChild(icon);
        button.appendChild(title);

        button.addEventListener("click", () => {
            if (typeof openChat === "function") openChat(chat.id);
            const overlay = document.getElementById("searchOverlay");
            if (overlay) overlay.classList.remove("open");
        });

        results.appendChild(button);
    });
}


/* ------------------------------------------------------
   Settings
   ------------------------------------------------------ */
function openSettings() {
    if (typeof closeMenus === "function") closeMenus();
    if (typeof updateSettingsUI === "function") updateSettingsUI();
    const overlay = document.getElementById("settingsOverlay");
    if (overlay) overlay.classList.add("open");
    if (typeof onSettingsOpened === "function") onSettingsOpened();
    if (typeof onSettingsOpenedExtended === "function") onSettingsOpenedExtended();
}


/* ------------------------------------------------------
   Export
   ------------------------------------------------------ */
async function exportCurrentChat() {
    if (typeof closeMenus === "function") closeMenus();
    if (typeof currentId === "undefined" || !currentId) {
        if (typeof _toast === "function") _toast("Nothing to export yet");
        return;
    }
    try {
        const raw = await bridgeCall(historybridge, "exportConversationJson", currentId);
        const data = JSON.parse(raw || "{}");
        if (data.ok) {
            if (typeof _toast === "function") _toast(`Exported to ${data.path}`);
        } else {
            if (typeof _toast === "function") {
                _toast("Export failed: " + (data.reason || "unknown"));
            }
        }
    } catch (e) {
        console.error("exportConversationJson failed", e);
        if (typeof _toast === "function") _toast("Export failed");
    }
}


/* ------------------------------------------------------
   Event bindings
   ------------------------------------------------------ */
(function _bindMenus() {
    const newChat = document.getElementById("newChat");
    if (newChat && typeof newChatFn === "function") {
        newChat.addEventListener("click", newChatFn);
    }

    const searchBtn = document.getElementById("searchButton");
    if (searchBtn) searchBtn.addEventListener("click", openSearch);

    const sidebarBtn = document.getElementById("sidebarButton");
    if (sidebarBtn && typeof toggleSidebar === "function") {
        sidebarBtn.addEventListener("click", toggleSidebar);
    }

    const clearBtn = document.getElementById("clearButton");
    if (clearBtn && typeof clearCurrent === "function") {
        clearBtn.addEventListener("click", clearCurrent);
    }

    const settingsBtn = document.getElementById("settingsButton");
    if (settingsBtn) settingsBtn.addEventListener("click", openSettings);

    const accountBtn = document.getElementById("accountButton");
    if (accountBtn) accountBtn.addEventListener("click", openSettings);

    const exportBtn = document.getElementById("exportButton");
    if (exportBtn) exportBtn.addEventListener("click", exportCurrentChat);

    const deleteAllBtn = document.getElementById("deleteAll");
    if (deleteAllBtn && typeof deleteAllChats === "function") {
        deleteAllBtn.addEventListener("click", deleteAllChats);
    }

    const ctxRenameBtn = document.getElementById("ctxRename");
    if (ctxRenameBtn) ctxRenameBtn.addEventListener("click", _onCtxRename);

    const ctxDeleteBtn = document.getElementById("ctxDelete");
    if (ctxDeleteBtn) ctxDeleteBtn.addEventListener("click", _onCtxDelete);

    const searchInput = document.getElementById("searchInput");
    if (searchInput) {
        searchInput.addEventListener("input", (ev) => renderSearch(ev.target.value));
    }

    const darkBtn = document.getElementById("darkButton");
    if (darkBtn && typeof setTheme === "function") {
        darkBtn.addEventListener("click", () => setTheme("dark"));
    }

    const lightBtn = document.getElementById("lightButton");
    if (lightBtn && typeof setTheme === "function") {
        lightBtn.addEventListener("click", () => setTheme("light"));
    }

    const compactSwitch = document.getElementById("compactSwitch");
    if (compactSwitch && typeof _toggleCompact === "function") {
        compactSwitch.addEventListener("click", _toggleCompact);
    }

    const enterSwitch = document.getElementById("enterSwitch");
    if (enterSwitch && typeof _toggleEnter === "function") {
        enterSwitch.addEventListener("click", _toggleEnter);
    }

    // Click-away closes all menus.
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".model-area") &&
            !event.target.closest(".more-area") &&
            !event.target.closest(".mode-area")) {
            if (typeof closeMenus === "function") closeMenus();
        }
        if (!event.target.closest(".chat-context-menu")) {
            closeChatContextMenu();
        }
    });

    // Escape key.
    document.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "k") {
            event.preventDefault();
            openSearch();
        }
        if (event.key === "Escape") {
            if (typeof closeMenus === "function") closeMenus();
            const s = document.getElementById("settingsOverlay");
            if (s) s.classList.remove("open");
            const so = document.getElementById("searchOverlay");
            if (so) so.classList.remove("open");
        }
    });

    // Right-click: allow only on history items.
    document.addEventListener("contextmenu", (event) => {
        if (event.target.closest(".history-item")) return;
        event.preventDefault();
    });
})();