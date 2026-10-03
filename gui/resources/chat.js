"use strict";

/* =========================================================
   RHEA CHAT — CORE
   =========================================================
   Only: bridges, preferences, persistence, send/receive,
   streaming, message rendering. Everything else lives in
   the other chat_*.js modules.
   ========================================================= */


/* ------------------------------------------------------
   Bridge plumbing
   ------------------------------------------------------ */
let pybridge = null;
let historybridge = null;
let bridgeReady = false;
const pendingBridgeCalls = [];


function whenBridgeReady(fn) {
    if (bridgeReady && pybridge && historybridge) {
        fn(pybridge, historybridge);
    } else {
        pendingBridgeCalls.push(fn);
    }
}


function _flushBridgeCalls() {
    while (pendingBridgeCalls.length) {
        const fn = pendingBridgeCalls.shift();
        try { fn(pybridge, historybridge); } catch (e) { console.error(e); }
    }
}


function _setupBridge() {
    if (typeof QWebChannel === "undefined") {
        console.error("QWebChannel is not loaded");
        return;
    }
    new QWebChannel(qt.webChannelTransport, function (channel) {
        window._rheaChannel = channel;
        pybridge = channel.objects.pybridge;
        historybridge = channel.objects.historybridge;
        bridgeReady = true;
        _flushBridgeCalls();
        pybridge.requestInitialState();
        _bootstrapFromHistory();
    });
}


function bridgeCall(obj, method, ...args) {
    return new Promise((resolve, reject) => {
        if (!obj || typeof obj[method] !== "function") {
            reject(new Error(`bridge method missing: ${method}`));
            return;
        }
        try {
            obj[method](...args, resolve);
        } catch (e) {
            reject(e);
        }
    });
}


/* ------------------------------------------------------
   Format / escape
   ------------------------------------------------------ */
function formatAI(value) {
    if (typeof renderMarkdown === "function") {
        return renderMarkdown(value);
    }
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replace(/\n/g, "<br>");
}


function escapeHTML(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* ------------------------------------------------------
   Storage keys
   ------------------------------------------------------ */
const THEME_KEY = "rhea_theme";
const MODEL_KEY = "rhea_model";
const ENTER_KEY = "rhea_enter";
const COMPACT_KEY = "rhea_compact";
const SIDEBAR_KEY = "rhea_sidebar";


/* ------------------------------------------------------
   State
   ------------------------------------------------------ */
let chats = [];
let currentId = null;
let messages = [];
let model = "Rhea";
let generating = false;
let enterEnabled = true;
let compactEnabled = false;
let sidebarVisible = true;

let streamBuffer = "";
let streamTarget = null;
let streamStarted = false;

let _aiResponsePersisted = false;


/* ------------------------------------------------------
   DOM helpers
   ------------------------------------------------------ */
const $ = (id) => document.getElementById(id);

function createId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}


/* ------------------------------------------------------
   History load / refresh
   ------------------------------------------------------ */
async function _bootstrapFromHistory() {
    try {
        const raw = await bridgeCall(historybridge, "listConversationsJson");
        chats = JSON.parse(raw || "[]");
    } catch (e) {
        console.error("loadConversations failed", e);
        chats = [];
    }
    renderHistory();
    currentId = null;
    messages = [];
    renderMessages();
}


async function onConversationsChanged() {
    try {
        const raw = await bridgeCall(historybridge, "listConversationsJson");
        chats = JSON.parse(raw || "[]");
    } catch (e) {
        console.error("onConversationsChanged failed", e);
        return;
    }
    renderHistory();
}


/* ------------------------------------------------------
   Preferences
   ------------------------------------------------------ */
function loadPreferences() {
    model = localStorage.getItem(MODEL_KEY) || "Rhea";
    enterEnabled = localStorage.getItem(ENTER_KEY) !== "false";
    compactEnabled = localStorage.getItem(COMPACT_KEY) === "true";
    sidebarVisible = localStorage.getItem(SIDEBAR_KEY) !== "false";

    const theme = localStorage.getItem(THEME_KEY) || "dark";
    document.body.classList.toggle("light", theme === "light");
    document.body.classList.toggle("compact", compactEnabled);

    updateSidebar();
    updateSettingsUI();
}


function savePreferences() {
    try {
        localStorage.setItem(MODEL_KEY, model);
        localStorage.setItem(ENTER_KEY, String(enterEnabled));
        localStorage.setItem(COMPACT_KEY, String(compactEnabled));
        localStorage.setItem(SIDEBAR_KEY, String(sidebarVisible));
        localStorage.setItem(
            THEME_KEY,
            document.body.classList.contains("light") ? "light" : "dark"
        );
    } catch {}
}


/* ------------------------------------------------------
   Persistence (background)
   ------------------------------------------------------ */
function getChatTitle() {
    const first = messages.find((item) => item.role === "user");
    if (!first) return "New chat";
    let title = String(first.text || "").replace(/\s+/g, " ").trim();
    if (!title) return "New chat";
    if (title.length > 45) title = title.substring(0, 45) + "…";
    return title;
}


function _persistMessageAsync(role, text) {
    (async () => {
        try {
            if (!currentId) currentId = createId();
            const dbRole = role === "ai" ? "assistant" : role;
            await bridgeCall(historybridge, "ensureConversation", currentId, "");
            await bridgeCall(historybridge, "appendMessage", currentId, dbRole, text);
            if (role === "user") {
                await bridgeCall(
                    historybridge,
                    "renameConversation",
                    currentId,
                    getChatTitle()
                );
            }
            _notifyActiveConversation(currentId);
            if (role === "user") {
                try {
                    const raw = await bridgeCall(historybridge, "listConversationsJson");
                    chats = JSON.parse(raw || "[]");
                    renderHistory();
                } catch {}
            }
        } catch (e) {
            console.error("persist failed", e);
        }
    })();
}


function _notifyActiveConversation(conversationId) {
    whenBridgeReady((bridge) => {
        try {
            if (typeof bridge.setConversation === "function") {
                bridge.setConversation(conversationId || "");
            }
        } catch (e) {
            console.error("setConversation failed", e);
        }
    });
}


/* ------------------------------------------------------
   New / open / clear
   ------------------------------------------------------ */
function newChatFn() {
    stopGeneration();
    currentId = null;
    messages = [];
    _aiResponsePersisted = false;
    if (typeof _startThinkingClock === "function") _startThinkingClock();
    resetStreamState();
    renderMessages();
    if (typeof closeMenus === "function") closeMenus();
    focusInput();
    _notifyActiveConversation("");
}


async function openChat(id) {
    if (id === currentId) {
        if (typeof closeMenus === "function") closeMenus();
        return;
    }
    stopGeneration();
    currentId = id;
    messages = [];
    _aiResponsePersisted = false;

    _notifyActiveConversation(id);

    try {
        const raw = await bridgeCall(historybridge, "listMessagesJson", id);
        const rows = JSON.parse(raw || "[]");
        messages = rows.map((item) => ({
            role: item.role === "user" ? "user" : "ai",
            text: String(item.content || "")
        }));
    } catch (e) {
        console.error("openChat failed", e);
    }
    renderMessages();
    renderHistory();
    if (typeof closeMenus === "function") closeMenus();
}


async function clearCurrent() {
    stopGeneration();
    if (currentId) {
        try {
            await bridgeCall(historybridge, "deleteConversation", currentId);
        } catch (e) {
            console.error("deleteConversation failed", e);
        }
    }
    messages = [];
    currentId = null;
    renderMessages();
    renderHistory();
    if (typeof closeMenus === "function") closeMenus();
    focusInput();
    _notifyActiveConversation("");
}


async function deleteAllChats() {
    if (!chats.length) return;
    const ok = await showConfirm(
        "Delete all locally stored conversations? This cannot be undone.",
        "Delete all chats"
    );
    if (!ok) return;
    stopGeneration();
    try {
        await bridgeCall(historybridge, "deleteAllConversations");
    } catch (e) {
        console.error("deleteAllConversations failed", e);
    }
    chats = [];
    messages = [];
    currentId = null;
    renderHistory();
    renderMessages();
    const overlay = document.getElementById("settingsOverlay");
    if (overlay) overlay.classList.remove("open");
}


/* ------------------------------------------------------
   History rendering
   ------------------------------------------------------ */
function renderHistory() {
    const list = document.getElementById("historyList");
    if (!list) return;
    list.innerHTML = "";

    if (!chats.length) {
        const empty = document.createElement("div");
        empty.className = "history-empty";
        empty.textContent = "No conversations yet";
        list.appendChild(empty);
        return;
    }

    chats.forEach((chat) => {
        const button = document.createElement("button");
        button.className = "history-item" + (chat.id === currentId ? " active" : "");
        button.dataset.chatId = chat.id;

        const icon = document.createElement("span");
        icon.className = "history-item-icon";
        icon.textContent = "💬";

        const title = document.createElement("span");
        title.className = "history-item-title";
        title.textContent = chat.title || "New chat";

        button.appendChild(icon);
        button.appendChild(title);

        button.addEventListener("click", () => openChat(chat.id));
        button.addEventListener("contextmenu", (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (typeof openChatContextMenu === "function") {
                openChatContextMenu(event.clientX, event.clientY, chat.id);
            }
        });

        list.appendChild(button);
    });
}


/* ------------------------------------------------------
   Welcome
   ------------------------------------------------------ */
function createWelcome() {
    const box = document.createElement("div");
    box.className = "welcome";
    box.innerHTML = `
        <div class="big-logo">R</div>
        <div class="welcome-title">How can I help you?</div>
        <div class="welcome-subtitle">Ask anything and start a conversation with Rhea.</div>
        <div class="suggestions">
            <button class="suggestion" data-text="Explain quantum computing in simple terms">
                <span class="suggestion-title">Explain something</span>
                <span class="suggestion-text">Break down a complex topic</span>
            </button>
            <button class="suggestion" data-text="Write a Python program for a useful desktop app">
                <span class="suggestion-title">Write some code</span>
                <span class="suggestion-text">Build or debug a program</span>
            </button>
            <button class="suggestion" data-text="Give me some creative project ideas">
                <span class="suggestion-title">Brainstorm ideas</span>
                <span class="suggestion-text">Explore creative possibilities</span>
            </button>
            <button class="suggestion" data-text="Help me make a plan for learning a new skill">
                <span class="suggestion-title">Make a plan</span>
                <span class="suggestion-text">Turn a goal into steps</span>
            </button>
        </div>
    `;
    box.querySelectorAll(".suggestion").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById("messageInput");
            if (input) input.value = button.dataset.text;
            resizeInput();
            sendMessage();
        });
    });
    return box;
}


/* ------------------------------------------------------
   Message DOM
   ------------------------------------------------------ */
function createMessage(role, text, index) {
    const wrapper = document.createElement("div");
    wrapper.className = "message " + role;
    if (typeof index === "number") wrapper.dataset.msgIndex = String(index);

    if (role === "user") {
        const bubble = document.createElement("div");
        bubble.className = "user-bubble";
        bubble.innerHTML = escapeHTML(text).replace(/\n/g, "<br>");
        wrapper.appendChild(bubble);

        const actions = document.createElement("div");
        actions.className = "message-actions user-actions";

        const edit = document.createElement("button");
        edit.className = "message-action";
        edit.textContent = "✎";
        edit.title = "Edit & resend";
        edit.addEventListener("click", () => {
            if (typeof window.editMessage === "function") {
                window.editMessage(index);
            }
        });
        actions.appendChild(edit);
        wrapper.appendChild(actions);

        return wrapper;
    }

    // AI message
    const avatar = document.createElement("div");
    avatar.className = "ai-avatar";
    avatar.textContent = "R";

    const content = document.createElement("div");
    content.className = "ai-content";

    const textBox = document.createElement("div");
    textBox.className = "ai-text";
    textBox.innerHTML = formatAI(text);

    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copy = document.createElement("button");
    copy.className = "message-action";
    copy.textContent = "⧉";
    copy.title = "Copy";
    copy.addEventListener("click", () => {
        if (typeof copyText === "function") copyText(text, copy);
    });

    const regenerate = document.createElement("button");
    regenerate.className = "message-action";
    regenerate.textContent = "↻";
    regenerate.title = "Regenerate";
    regenerate.addEventListener("click", regenerateLast);

    actions.appendChild(copy);
    actions.appendChild(regenerate);
    content.appendChild(textBox);
    content.appendChild(actions);
    wrapper.appendChild(avatar);
    wrapper.appendChild(content);

    requestAnimationFrame(() => {
        if (typeof bindCodeCopyButtons === "function") {
            bindCodeCopyButtons(textBox);
        }
    });

    return wrapper;
}


function renderMessages() {
    const inner = document.getElementById("chatInner");
    if (!inner) return;
    inner.innerHTML = "";
    if (!messages.length) {
        inner.appendChild(createWelcome());
        return;
    }
    const fragment = document.createDocumentFragment();
    messages.forEach((message, idx) => {
        fragment.appendChild(createMessage(message.role, message.text, idx));
    });
    inner.appendChild(fragment);
    scrollBottom(false);
}


function addMessage(role, text) {
    const inner = document.getElementById("chatInner");
    if (!inner) return;
    const welcome = inner.querySelector(".welcome");
    if (welcome) welcome.remove();
    const idx = messages.length - 1;
    inner.appendChild(createMessage(role, text, idx));
    requestAnimationFrame(() => scrollBottom(true));
}


/* ------------------------------------------------------
   Typing / scroll
   ------------------------------------------------------ */
function showTyping() {
    hideTyping();
    const inner = document.getElementById("chatInner");
    if (!inner) return;
    const wrapper = document.createElement("div");
    wrapper.className = "message ai";
    wrapper.id = "typing";
    wrapper.innerHTML = `
        <div class="ai-avatar">R</div>
        <div class="ai-content">
            <div class="typing">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    inner.appendChild(wrapper);
    requestAnimationFrame(() => scrollBottom(true));
}


function hideTyping() {
    const typing = document.getElementById("typing");
    if (typing) typing.remove();
}


function scrollBottom(smooth) {
    const chat = document.getElementById("chat");
    if (!chat) return;
    chat.scrollTo({
        top: chat.scrollHeight,
        behavior: smooth ? "smooth" : "auto"
    });
}


/* ------------------------------------------------------
   Send
   ------------------------------------------------------ */
function sendMessage() {
    if (generating) return;
    const input = document.getElementById("messageInput");
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    resizeInput();

    messages.push({ role: "user", text: text });
    addMessage("user", text);

    _aiResponsePersisted = false;
    beginGeneration();

    _persistMessageAsync("user", text);

    whenBridgeReady((bridge) => {
        bridge.sendMessage(text, model);
    });
}


/* ------------------------------------------------------
   Generation state
   ------------------------------------------------------ */
function beginGeneration() {
    generating = true;
    resetStreamState();
    _aiResponsePersisted = false;
    if (typeof _startThinkingClock === "function") _startThinkingClock();

    const sendBtn = document.getElementById("sendButton");
    if (sendBtn) sendBtn.style.display = "none";
    const stopBtn = document.getElementById("stopButton");
    if (stopBtn) stopBtn.style.display = "flex";

    showTyping();
}


function endGeneration() {
    generating = false;
    const sendBtn = document.getElementById("sendButton");
    if (sendBtn) sendBtn.style.display = "flex";
    const stopBtn = document.getElementById("stopButton");
    if (stopBtn) stopBtn.style.display = "none";
}


function resetStreamState() {
    streamBuffer = "";
    streamTarget = null;
    streamStarted = false;
}


/* ------------------------------------------------------
   Streaming callbacks
   ------------------------------------------------------ */
function onResponseChunk(text) {
    if (!generating) return;
    if (!text) return;

    if (!streamStarted) {
        streamStarted = true;
        streamTarget = _startStreamingMessage();
    }

    streamBuffer += text;

    if (streamTarget) {
        streamTarget.innerHTML = formatAI(streamBuffer);
        if (typeof bindCodeCopyButtons === "function") {
            bindCodeCopyButtons(streamTarget);
        }
        requestAnimationFrame(() => scrollBottom(true));
    }
}


function onResponseDone(fullText) {
    if (!generating) return;

    if (!streamStarted) {
        endGeneration();
        messages.push({ role: "ai", text: fullText });
        _replaceTypingWithMessage(fullText);
        _persistAIIfNeeded(fullText);
        return;
    }

    endGeneration();

    const finalText = (fullText && fullText.trim()) ? fullText : streamBuffer;
    messages.push({ role: "ai", text: finalText });

    if (streamTarget) {
        _attachMessageActions(streamTarget, finalText);
    }

    _persistAIIfNeeded(finalText);
    streamTarget = null;
}


function _startStreamingMessage() {
    const typing = document.getElementById("typing");

    let wrapper;
    if (typing) {
        const preservedThought = typing.querySelector(".ai-thought");
        if (preservedThought) preservedThought.remove();

        wrapper = document.createElement("div");
        wrapper.className = "message ai";

        const avatar = document.createElement("div");
        avatar.className = "ai-avatar";
        avatar.textContent = "R";

        const content = document.createElement("div");
        content.className = "ai-content";
        if (preservedThought) content.appendChild(preservedThought);

        const textBox = document.createElement("div");
        textBox.className = "ai-text";
        content.appendChild(textBox);

        wrapper.appendChild(avatar);
        wrapper.appendChild(content);
        typing.replaceWith(wrapper);
    } else {
        const inner = document.getElementById("chatInner");
        wrapper = document.createElement("div");
        wrapper.className = "message ai";

        const avatar = document.createElement("div");
        avatar.className = "ai-avatar";
        avatar.textContent = "R";

        const content = document.createElement("div");
        content.className = "ai-content";

        const textBox = document.createElement("div");
        textBox.className = "ai-text";
        content.appendChild(textBox);

        wrapper.appendChild(avatar);
        wrapper.appendChild(content);
        inner.appendChild(wrapper);
    }

    return wrapper.querySelector(".ai-text");
}


function _replaceTypingWithMessage(text) {
    const typing = document.getElementById("typing");
    if (!typing) {
        addMessage("ai", text);
        return;
    }

    const preservedThought = typing.querySelector(".ai-thought");
    if (preservedThought) preservedThought.remove();

    const fresh = createMessage("ai", text);
    if (preservedThought) {
        const content = fresh.querySelector(".ai-content");
        if (content) content.insertBefore(preservedThought, content.firstChild);
    }
    typing.replaceWith(fresh);
    requestAnimationFrame(() => scrollBottom(true));
}


function _attachMessageActions(textBox, text) {
    const content = textBox.parentElement;
    if (!content) return;
    if (content.querySelector(".message-actions")) return;

    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copy = document.createElement("button");
    copy.className = "message-action";
    copy.textContent = "⧉";
    copy.title = "Copy";
    copy.addEventListener("click", () => {
        if (typeof copyText === "function") copyText(text, copy);
    });

    const regenerate = document.createElement("button");
    regenerate.className = "message-action";
    regenerate.textContent = "↻";
    regenerate.title = "Regenerate";
    regenerate.addEventListener("click", regenerateLast);

    actions.appendChild(copy);
    actions.appendChild(regenerate);
    content.appendChild(actions);
}


function _persistAIIfNeeded(text) {
    if (_aiResponsePersisted) return;
    _aiResponsePersisted = true;
    _persistMessageAsync("ai", text);
}


/* ------------------------------------------------------
   Synthesis stream
   ------------------------------------------------------ */
let _synthesisStarted = false;
let _synthesisBuffer = "";
let _synthesisTarget = null;


function _handleSynthesisChunk(chunk) {
    if (!chunk) return;
    if (!generating) return;

    if (!_synthesisStarted) {
        _synthesisStarted = true;
        _startSynthesisMessage();
    }

    _synthesisBuffer += chunk;
    if (_synthesisTarget) {
        _synthesisTarget.innerHTML = formatAI(_synthesisBuffer);
        if (typeof bindCodeCopyButtons === "function") {
            bindCodeCopyButtons(_synthesisTarget);
        }
        requestAnimationFrame(() => scrollBottom(true));
    }
}


function _startSynthesisMessage() {
    const typing = document.getElementById("typing");
    if (!typing) return;

    const preservedThought = typing.querySelector(".ai-thought");
    if (preservedThought) preservedThought.remove();

    const wrapper = document.createElement("div");
    wrapper.className = "message ai";

    const avatar = document.createElement("div");
    avatar.className = "ai-avatar";
    avatar.textContent = "R";

    const content = document.createElement("div");
    content.className = "ai-content";
    if (preservedThought) content.appendChild(preservedThought);

    const textBox = document.createElement("div");
    textBox.className = "ai-text";
    content.appendChild(textBox);

    wrapper.appendChild(avatar);
    wrapper.appendChild(content);

    typing.replaceWith(wrapper);
    _synthesisTarget = textBox;
}


function _finalizeSynthesis() {
    if (!_synthesisStarted) return;
    if (_synthesisTarget) {
        _attachMessageActions(_synthesisTarget, _synthesisBuffer);
    }
    _synthesisStarted = false;
    _synthesisBuffer = "";
    _synthesisTarget = null;
}


/* ------------------------------------------------------
   Non-stream / error finalization
   ------------------------------------------------------ */
function onResponseReady(text) {
    if (!generating) {
        if (text && !_aiResponsePersisted) {
            messages.push({ role: "ai", text: text });
            _persistAIIfNeeded(text);
        }
        return;
    }

    if (_synthesisStarted) {
        _finalizeSynthesis();
        endGeneration();
        messages.push({ role: "ai", text: text });
        _persistAIIfNeeded(text);
        return;
    }

    endGeneration();
    messages.push({ role: "ai", text: text });
    _replaceTypingWithMessage(text);
    _persistAIIfNeeded(text);
}


function onResponseError(message) {
    endGeneration();
    resetStreamState();

    const text = "⚠️ " + message;
    messages.push({ role: "ai", text: text });
    _replaceTypingWithMessage(text);
    _persistAIIfNeeded(text);
}


function onModelChanged(name) {}


/* ------------------------------------------------------
   Stop / regenerate
   ------------------------------------------------------ */
function stopGeneration() {
    if (generating) {
        whenBridgeReady((bridge) => bridge.stopGeneration());
    }
    generating = false;
    const sendBtn = document.getElementById("sendButton");
    if (sendBtn) sendBtn.style.display = "flex";
    const stopBtn = document.getElementById("stopButton");
    if (stopBtn) stopBtn.style.display = "none";
    hideTyping();
    resetStreamState();
}


function regenerateLast() {
    if (generating) return;
    let lastUser = null;
    for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].role === "user") {
            lastUser = messages[i].text;
            break;
        }
    }
    if (!lastUser) return;
    while (messages.length && messages[messages.length - 1].role === "ai") {
        messages.pop();
    }
    renderMessages();
    _aiResponsePersisted = false;
    beginGeneration();
    whenBridgeReady((bridge) => bridge.sendMessage(lastUser, model));
}


/* ------------------------------------------------------
   Input / sidebar / misc UI
   ------------------------------------------------------ */
function resizeInput() {
    const input = document.getElementById("messageInput");
    if (!input) return;
    input.style.height = "auto";
    const natural = input.scrollHeight;
    const clamped = Math.max(42, Math.min(natural, 120));
    input.style.height = clamped + "px";
}


function focusInput() {
    requestAnimationFrame(() => {
        const input = document.getElementById("messageInput");
        if (input) input.focus();
    });
}


function updateSidebar() {
    const sb = document.getElementById("sidebar");
    if (sb) sb.classList.toggle("closed", !sidebarVisible);
}


function toggleSidebar() {
    sidebarVisible = !sidebarVisible;
    updateSidebar();
    savePreferences();
}


function closeMenus() {
    const mm = document.getElementById("modelMenu");
    if (mm) mm.classList.remove("open");
    const more = document.getElementById("moreMenu");
    if (more) more.classList.remove("open");
    if (typeof closeChatContextMenu === "function") closeChatContextMenu();
}


function updateSettingsUI() {
    const light = document.body.classList.contains("light");
    const darkBtn = document.getElementById("darkButton");
    if (darkBtn) darkBtn.classList.toggle("active", !light);
    const lightBtn = document.getElementById("lightButton");
    if (lightBtn) lightBtn.classList.toggle("active", light);
    const cs = document.getElementById("compactSwitch");
    if (cs) cs.classList.toggle("active", compactEnabled);
    const es = document.getElementById("enterSwitch");
    if (es) es.classList.toggle("active", enterEnabled);
}


function setTheme(theme) {
    document.body.classList.toggle("light", theme === "light");
    savePreferences();
    updateSettingsUI();
}


function _toggleCompact() {
    compactEnabled = !compactEnabled;
    document.body.classList.toggle("compact", compactEnabled);
    savePreferences();
    updateSettingsUI();
}


function _toggleEnter() {
    enterEnabled = !enterEnabled;
    savePreferences();
    updateSettingsUI();
}


/* ------------------------------------------------------
   Toast
   ------------------------------------------------------ */
let _toastTimer = null;
function _toast(message) {
    let el = document.getElementById("rheaToast");
    if (!el) {
        el = document.createElement("div");
        el.id = "rheaToast";
        el.className = "rhea-toast";
        document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("show");
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}


/* ------------------------------------------------------
   Event bindings (core only)
   ------------------------------------------------------ */
(function _bindCoreEvents() {
    const sendBtn = document.getElementById("sendButton");
    if (sendBtn) sendBtn.addEventListener("click", sendMessage);

    const stopBtn = document.getElementById("stopButton");
    if (stopBtn) stopBtn.addEventListener("click", stopGeneration);

    const attachBtn = document.getElementById("attachButton");
    if (attachBtn) {
        attachBtn.addEventListener("click", () => {
            whenBridgeReady((bridge) => bridge.attachRequested());
        });
    }

    const msgInput = document.getElementById("messageInput");
    if (msgInput) {
        msgInput.addEventListener("input", resizeInput);
        msgInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey && enterEnabled) {
                event.preventDefault();
                sendMessage();
            }
        });
    }

    const settingsOverlay = document.getElementById("settingsOverlay");
    if (settingsOverlay) {
        settingsOverlay.addEventListener("click", (event) => {
            if (event.target === settingsOverlay) {
                settingsOverlay.classList.remove("open");
            }
        });
    }

    const searchOverlay = document.getElementById("searchOverlay");
    if (searchOverlay) {
        searchOverlay.addEventListener("click", (event) => {
            if (event.target === searchOverlay) {
                searchOverlay.classList.remove("open");
            }
        });
    }

    document.querySelectorAll("[data-close]").forEach((button) => {
        button.addEventListener("click", () => {
            const target = document.getElementById(button.dataset.close);
            if (target) target.classList.remove("open");
        });
    });
})();


/* ------------------------------------------------------
   Boot
   ------------------------------------------------------ */
loadPreferences();
renderHistory();
renderMessages();
requestAnimationFrame(() => resizeInput());
_setupBridge();