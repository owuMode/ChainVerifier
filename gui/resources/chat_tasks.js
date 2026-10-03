"use strict";

/* =========================================================
   TASK HISTORY PAGE
   ========================================================= */

let tasksbridge = null;

let currentPage = "chat";
let tasksFilter = "all";
let tasksList = [];
let openTaskId = null;


/* =========================================================
   BRIDGE BINDING
   ========================================================= */

function _bindTasksBridge() {
    if (!window._rheaChannel || !window._rheaChannel.objects) {
        setTimeout(_bindTasksBridge, 40);
        return;
    }

    tasksbridge = window._rheaChannel.objects.tasksbridge || null;

    if (!tasksbridge) {
        setTimeout(_bindTasksBridge, 40);
        return;
    }

    _setupTasksUI();

    if (typeof tasksbridge.tasksChanged.connect === "function") {
        tasksbridge.tasksChanged.connect(() => {
            if (currentPage === "tasks") {
                if (openTaskId) {
                    openTaskDetail(openTaskId);
                } else {
                    refreshTasks();
                }
            }
        });
    }
}


/* =========================================================
   PAGE SWITCH
   ========================================================= */

function showPage(page) {
    if (page !== "chat" && page !== "tasks") return;

    currentPage = page;

    document.body.classList.toggle("showing-tasks", page === "tasks");

    document.querySelectorAll(".sidebar-nav-button").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.page === page);
    });

    if (page === "tasks") {
        refreshTasks();
    }
}


/* =========================================================
   TASK LIST
   ========================================================= */

async function refreshTasks() {
    if (!tasksbridge) return;

    try {
        const raw = await bridgeCall(tasksbridge, "listTasksJson", tasksFilter);
        tasksList = JSON.parse(raw || "[]");
    } catch (e) {
        console.error("listTasksJson failed", e);
        tasksList = [];
    }

    renderTaskList();
}


function renderTaskList() {
    const container = document.getElementById("tasksList");
    if (!container) return;

    openTaskId = null;

    if (!tasksList.length) {
        container.innerHTML = `
            <div class="tasks-empty">
                <div class="tasks-empty-icon">📋</div>
                <div>No tasks yet. Try Agent mode to run one.</div>
            </div>
        `;
        return;
    }

    container.innerHTML = "";
    tasksList.forEach(t => container.appendChild(renderTaskRow(t)));
}


function renderTaskRow(task) {
    const row = document.createElement("div");
    row.className = "task-row";
    row.dataset.taskId = task.task_id;
    row.dataset.status = task.status;

    const statusIcon = document.createElement("div");
    statusIcon.className = "task-row-status";
    statusIcon.textContent = _statusIcon(task.status);

    const info = document.createElement("div");
    info.className = "task-row-info";

    const title = document.createElement("div");
    title.className = "task-row-title";
    title.textContent = task.goal || "(no goal)";

    const meta = document.createElement("div");
    meta.className = "task-row-meta";

    const timeSpan = document.createElement("span");
    timeSpan.textContent = _formatTime(task.created_at);

    const stepSpan = document.createElement("span");
    stepSpan.textContent = `Step ${task.current_step} / ${task.max_steps}`;

    meta.appendChild(timeSpan);
    meta.appendChild(stepSpan);

    info.appendChild(title);
    info.appendChild(meta);

    const badge = document.createElement("span");
    badge.className = "task-row-badge";
    badge.textContent = _statusLabel(task.status);

    row.appendChild(statusIcon);
    row.appendChild(info);
    row.appendChild(badge);

    row.addEventListener("click", () => openTaskDetail(task.task_id));
    return row;
}


/* =========================================================
   TASK DETAIL
   ========================================================= */

async function openTaskDetail(taskId) {
    if (!tasksbridge) return;

    openTaskId = taskId;

    let data;
    try {
        const raw = await bridgeCall(tasksbridge, "getTaskJson", taskId);
        data = JSON.parse(raw || "{}");
    } catch (e) {
        console.error("getTaskJson failed", e);
        return;
    }

    if (!data.task) {
        openTaskId = null;
        refreshTasks();
        return;
    }

    renderTaskDetail(data);
}


function renderTaskDetail(data) {
    const container = document.getElementById("tasksList");
    if (!container) return;

    const t = data.task;

    container.innerHTML = "";

    const wrapper = document.createElement("div");
    wrapper.className = "task-detail";

    // --- header ---
    const header = document.createElement("div");
    header.className = "task-detail-header";

    const back = document.createElement("button");
    back.className = "task-detail-back";
    back.textContent = "←";
    back.title = "Back";
    back.addEventListener("click", () => {
        openTaskId = null;
        refreshTasks();
    });

    const titleBox = document.createElement("div");
    titleBox.className = "task-detail-title";

    const goal = document.createElement("div");
    goal.className = "task-detail-goal";
    goal.textContent = t.goal || "(no goal)";

    const meta = document.createElement("div");
    meta.className = "task-detail-meta";

    const statusSpan = document.createElement("span");
    statusSpan.textContent = `Status: ${_statusLabel(t.status)}`;

    const createdSpan = document.createElement("span");
    createdSpan.textContent = `Created: ${_formatTime(t.created_at)}`;

    const stepSpan = document.createElement("span");
    stepSpan.textContent = `Step ${t.current_step} / ${t.max_steps}`;

    meta.appendChild(statusSpan);
    meta.appendChild(createdSpan);
    meta.appendChild(stepSpan);

    titleBox.appendChild(goal);
    titleBox.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "task-detail-actions";
    actions.appendChild(_retryButton(t));
    if (!_isTerminal(t.status)) {
        actions.appendChild(_cancelButton(t));
    }
    if (_isTerminal(t.status)) {
        actions.appendChild(_deleteButton(t));
    }

    header.appendChild(back);
    header.appendChild(titleBox);
    header.appendChild(actions);
    wrapper.appendChild(header);

    // --- error ---
    if (t.error) {
        const sec = _section("Error");
        const box = document.createElement("div");
        box.className = "task-error-box";
        box.textContent = t.error;
        sec.appendChild(box);
        wrapper.appendChild(sec);
    }

    // --- result ---
    if (t.result) {
        const sec = _section("Result");
        const box = document.createElement("div");
        box.className = "task-result-box";
        box.textContent = t.result;
        sec.appendChild(box);
        wrapper.appendChild(sec);
    }

    // --- tool calls (built from events) ---
    if (Array.isArray(data.events) && data.events.length) {
        const toolGroups = _buildToolEventGroups(data.events);
        if (toolGroups.length) {
            const sec = _section("Tool calls");
            const list = document.createElement("div");
            list.className = "task-plan-list";
            toolGroups.forEach(tc => list.appendChild(_toolCallCard(tc)));
            sec.appendChild(list);
            wrapper.appendChild(sec);
        }
    }

    // --- plan ---
    if (Array.isArray(t.plan) && t.plan.length) {
        const sec = _section("Plan");
        const list = document.createElement("div");
        list.className = "task-plan-list";

        t.plan.forEach((step, i) => {
            list.appendChild(_planStep(i + 1, step));
        });

        sec.appendChild(list);
        wrapper.appendChild(sec);
    }

    // --- events ---
    if (Array.isArray(data.events) && data.events.length) {
        const sec = _section("Activity");
        const list = document.createElement("div");
        list.className = "task-events-list";

        data.events.forEach(e => {
            list.appendChild(_eventRow(e));
        });

        sec.appendChild(list);
        wrapper.appendChild(sec);
    }

    container.appendChild(wrapper);
}


function _section(title) {
    const sec = document.createElement("div");
    sec.className = "task-section";

    const t = document.createElement("div");
    t.className = "task-section-title";
    t.textContent = title;

    sec.appendChild(t);
    return sec;
}


function _planStep(index, step) {
    const row = document.createElement("div");
    row.className = "task-plan-step";

    const num = document.createElement("div");
    num.className = "task-plan-step-number";
    num.textContent = String(index);

    const body = document.createElement("div");
    body.className = "task-plan-step-body";

    const tool = document.createElement("div");
    tool.className = "task-plan-step-tool";
    tool.textContent = step.tool_id || "(unknown tool)";

    body.appendChild(tool);

    if (step.rationale) {
        const rat = document.createElement("div");
        rat.className = "task-plan-step-rationale";
        rat.textContent = step.rationale;
        body.appendChild(rat);
    }

    if (step.arguments && Object.keys(step.arguments).length) {
        const args = document.createElement("div");
        args.className = "task-plan-step-args";
        try {
            args.textContent = JSON.stringify(step.arguments, null, 2);
        } catch {
            args.textContent = String(step.arguments);
        }
        body.appendChild(args);
    }

    row.appendChild(num);
    row.appendChild(body);
    return row;
}


function _eventRow(event) {
    const row = document.createElement("div");
    row.className = "task-event-row";

    const type = document.createElement("span");
    type.className = "task-event-type";
    type.textContent = event.event_type;

    const time = document.createElement("span");
    time.className = "task-event-time";
    time.textContent = _formatTime(event.created_at);

    const payload = document.createElement("span");
    payload.className = "task-event-payload";
    try {
        payload.textContent = JSON.stringify(event.payload || {});
    } catch {
        payload.textContent = "";
    }

    row.appendChild(type);
    row.appendChild(time);
    row.appendChild(payload);
    return row;
}


/* =========================================================
   TOOL CALL CARDS (from events)
   ========================================================= */

function _buildToolEventGroups(events) {
    const byKey = new Map();
    for (const e of events) {
        const type = e.event_type || "";
        const payload = e.payload || {};
        if (!type.startsWith("TOOL_")) continue;
        const toolId = payload.tool_id || "tool";
        const step = payload.step_index ?? "?";
        const key = `${step}::${toolId}`;
        let entry = byKey.get(key);
        if (!entry) {
            entry = {
                tool_id: toolId,
                display_name: payload.display_name || toolId,
                step_index: step,
                status: "running",
                args: null,
                result: null,
                error: null,
            };
            byKey.set(key, entry);
        }
        if (type === "TOOL_STARTED") {
            entry.args = payload.arguments || null;
        } else if (type === "TOOL_COMPLETED") {
            entry.status = "ok";
            entry.result = payload.output || null;
        } else if (type === "TOOL_FAILED") {
            entry.status = "failed";
            entry.error = payload.error || payload.reason || "failed";
        }
    }
    return Array.from(byKey.values()).sort(
        (a, b) => (a.step_index || 0) - (b.step_index || 0)
    );
}


function _toolCallCard(tc) {
    const row = document.createElement("div");
    row.className = "task-plan-step";

    const icon = document.createElement("div");
    icon.className = "task-plan-step-number";
    icon.textContent = tc.status === "ok" ? "✓" : tc.status === "failed" ? "✕" : "…";

    const body = document.createElement("div");
    body.className = "task-plan-step-body";

    const tool = document.createElement("div");
    tool.className = "task-plan-step-tool";
    tool.textContent = tc.display_name || tc.tool_id || "tool";
    body.appendChild(tool);

    if (tc.args) {
        const pre = document.createElement("div");
        pre.className = "task-plan-step-args";
        try { pre.textContent = JSON.stringify(tc.args, null, 2); } catch {}
        body.appendChild(pre);
    }

    if (tc.result) {
        const pre = document.createElement("div");
        pre.className = "task-plan-step-args";
        try { pre.textContent = JSON.stringify(tc.result, null, 2); } catch {}
        body.appendChild(pre);
    }

    if (tc.error) {
        const err = document.createElement("div");
        err.className = "task-plan-step-rationale";
        err.style.color = "var(--danger)";
        err.textContent = tc.error;
        body.appendChild(err);
    }

    row.appendChild(icon);
    row.appendChild(body);
    return row;
}


/* =========================================================
   ACTION BUTTONS
   ========================================================= */

function _retryButton(task) {
    const btn = document.createElement("button");
    btn.className = "task-action primary";
    btn.textContent = "Retry";
    btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
            const newId = await bridgeCall(tasksbridge, "retryTask", task.task_id);
            if (newId) {
                openTaskDetail(newId);
            } else {
                btn.disabled = false;
            }
        } catch (e) {
            console.error("retryTask failed", e);
            btn.disabled = false;
        }
    });
    return btn;
}


function _cancelButton(task) {
    const btn = document.createElement("button");
    btn.className = "task-action danger";
    btn.textContent = "Cancel";
    btn.addEventListener("click", async () => {
        if (!confirm("Cancel this running task?")) return;
        btn.disabled = true;
        try {
            const ok = await bridgeCall(tasksbridge, "cancelTask", task.task_id);
            if (!ok) btn.disabled = false;
        } catch (e) {
            console.error("cancelTask failed", e);
            btn.disabled = false;
        }
    });
    return btn;
}


function _deleteButton(task) {
    const btn = document.createElement("button");
    btn.className = "task-action danger";
    btn.textContent = "Delete";
    btn.addEventListener("click", async () => {
        if (!confirm("Delete this task from history?")) return;
        btn.disabled = true;
        try {
            const ok = await bridgeCall(tasksbridge, "deleteTask", task.task_id);
            if (ok) {
                openTaskId = null;
                refreshTasks();
            } else {
                btn.disabled = false;
            }
        } catch (e) {
            console.error("deleteTask failed", e);
            btn.disabled = false;
        }
    });
    return btn;
}


/* =========================================================
   HELPERS
   ========================================================= */

function _statusIcon(status) {
    switch (status) {
        case "COMPLETED": return "✓";
        case "FAILED": return "✕";
        case "CANCELLED": return "⊘";
        case "EXECUTING": return "⚙";
        case "PLANNING": return "◐";
        case "VERIFYING": return "◑";
        case "OBSERVING": return "◎";
        case "RECOVERING": return "↻";
        case "UNDERSTANDING": return "◔";
        default: return "○";
    }
}


function _statusLabel(status) {
    if (!status) return "—";
    return status.charAt(0) + status.slice(1).toLowerCase();
}


function _isTerminal(status) {
    return status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
}


function _formatTime(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        const now = new Date();
        const diff = (now - d) / 1000;
        if (diff < 60) return "just now";
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
        return d.toLocaleDateString();
    } catch {
        return iso;
    }
}


/* =========================================================
   EVENTS
   ========================================================= */

function _setupTasksUI() {
    document.querySelectorAll(".sidebar-nav-button").forEach(btn => {
        btn.addEventListener("click", () => showPage(btn.dataset.page));
    });

    document.querySelectorAll(".tasks-filter").forEach(btn => {
        btn.addEventListener("click", () => {
            tasksFilter = btn.dataset.filter || "all";
            document.querySelectorAll(".tasks-filter").forEach(b => {
                b.classList.toggle("active", b.dataset.filter === tasksFilter);
            });
            refreshTasks();
        });
    });
}


/* =========================================================
   STARTUP
   ========================================================= */

_bindTasksBridge();