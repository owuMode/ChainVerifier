"use strict";

/* =========================================================
   MARKDOWN RENDERER (mini, safe, no external deps)
   =========================================================
   Supports headings, bold/italic, inline code, fenced code
   blocks, lists, blockquotes, hr, links, tables.
   Fenced code blocks get syntax highlighting via highlight.js
   when available.
   ========================================================= */


function renderMarkdown(raw) {
    if (raw === null || raw === undefined) return "";
    let text = String(raw);
    text = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    // 1. Extract fenced code blocks.
    const codeBlocks = [];
    text = text.replace(/```([a-zA-Z0-9_+\-]*)\n([\s\S]*?)```/g, (m, lang, code) => {
        const idx = codeBlocks.length;
        codeBlocks.push({ lang: lang || "", code: code });
        return `\u0000CODEBLOCK${idx}\u0000`;
    });

    const lines = text.split("\n");
    const out = [];
    let i = 0;

    while (i < lines.length) {
        let line = lines[i];

        const codeMatch = line.match(/^\u0000CODEBLOCK(\d+)\u0000\s*$/);
        if (codeMatch) {
            const idx = parseInt(codeMatch[1], 10);
            out.push(_renderCodeBlock(codeBlocks[idx]));
            i++;
            continue;
        }

        if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
            out.push('<hr class="md-hr">');
            i++;
            continue;
        }

        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            const level = heading[1].length;
            const content = _inlineFormat(heading[2]);
            out.push(`<h${level} class="md-h${level}">${content}</h${level}>`);
            i++;
            continue;
        }

        if (/^\s*>\s?/.test(line)) {
            const quoteLines = [];
            while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
                quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
                i++;
            }
            const content = quoteLines.map(_inlineFormat).join("<br>");
            out.push(`<blockquote class="md-quote">${content}</blockquote>`);
            continue;
        }

        if (/^\s*[-*•]\s+/.test(line)) {
            const items = [];
            while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*[-*•]\s+/, ""));
                i++;
            }
            out.push(
                '<ul class="md-ul">' +
                items.map(it => `<li>${_inlineFormat(it)}</li>`).join("") +
                '</ul>'
            );
            continue;
        }

        if (/^\s*\d+[.)]\s+/.test(line)) {
            const items = [];
            while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
                i++;
            }
            out.push(
                '<ol class="md-ol">' +
                items.map(it => `<li>${_inlineFormat(it)}</li>`).join("") +
                '</ol>'
            );
            continue;
        }

        if (/^\s*\|.*\|\s*$/.test(line) &&
            i + 1 < lines.length &&
            /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
            const tableLines = [];
            while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
                tableLines.push(lines[i]);
                i++;
            }
            out.push(_renderTable(tableLines));
            continue;
        }

        if (line.trim() === "") { i++; continue; }

        const paraLines = [];
        while (i < lines.length) {
            const l = lines[i];
            if (l.trim() === "") break;
            if (/^\u0000CODEBLOCK\d+\u0000\s*$/.test(l)) break;
            if (/^(#{1,6})\s+/.test(l)) break;
            if (/^\s*[-*•]\s+/.test(l)) break;
            if (/^\s*\d+[.)]\s+/.test(l)) break;
            if (/^\s*>\s?/.test(l)) break;
            if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(l)) break;
            if (/^\s*\|.*\|\s*$/.test(l)) break;
            paraLines.push(l);
            i++;
        }
        if (paraLines.length) {
            out.push(`<p class="md-p">${paraLines.map(_inlineFormat).join("<br>")}</p>`);
        }
    }

    return out.join("");
}


/* =========================================================
   Helpers
   ========================================================= */

function _inlineFormat(text) {
    if (!text) return "";

    let s = _escapeHTML(text);

    const inlineCodes = [];
    s = s.replace(/`([^`]+)`/g, (m, code) => {
        const idx = inlineCodes.length;
        inlineCodes.push(code);
        return `\u0001INLINECODE${idx}\u0001`;
    });

    s = s.replace(/\*\*([^\*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^\*])\*([^\*\n]+)\*(?!\*)/g, "$1<em>$2</em>");

    s = s.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );

    s = s.replace(/\u0001INLINECODE(\d+)\u0001/g, (m, idx) => {
        const code = inlineCodes[parseInt(idx, 10)];
        return `<code class="md-inline-code">${code}</code>`;
    });

    return s;
}


function _renderCodeBlock(block) {
    const lang = String(block.lang || "").trim().toLowerCase();
    const code = String(block.code || "");
    const escaped = _escapeHTML(code);
    const langLabel = lang ? `<span class="md-code-lang">${_escapeHTML(lang)}</span>` : "";
    const copyId = "codecopy_" + Math.random().toString(36).slice(2, 8);

    // Apply syntax highlighting if available and language is known
    // (or auto-detect when no language given).
    let highlighted = escaped;
    const hasHljs = (typeof window !== "undefined") && window.hljs;

    if (hasHljs) {
        try {
            let result = null;
            if (lang && window.hljs.getLanguage && window.hljs.getLanguage(lang)) {
                result = window.hljs.highlight(code, { language: lang, ignoreIllegals: true });
            } else if (!lang) {
                result = window.hljs.highlightAuto(code);
            }
            if (result && typeof result.value === "string") {
                // hljs.highlight returns already-escaped HTML.
                highlighted = result.value;
            }
        } catch (e) {
            // Keep the escaped fallback.
            highlighted = escaped;
        }
    }

    const langClass = lang ? ` language-${_escapeHTML(lang)}` : "";
    const hljsClass = hasHljs ? " hljs" : "";

    return (
        '<div class="md-code-block">' +
          '<div class="md-code-header">' +
            langLabel +
            `<button class="md-code-copy" data-copy-target="${copyId}" title="Copy">⧉</button>` +
          '</div>' +
          `<pre class="md-code-pre" id="${copyId}"><code class="${hljsClass.trim()}${langClass}">${highlighted}</code></pre>` +
        '</div>'
    );
}


function _renderTable(lines) {
    const header = _splitRow(lines[0]);
    const rows = lines.slice(2).map(_splitRow);

    let html = '<table class="md-table"><thead><tr>';
    for (const h of header) {
        html += `<th>${_inlineFormat(h)}</th>`;
    }
    html += '</tr></thead><tbody>';
    for (const r of rows) {
        html += "<tr>";
        for (let c = 0; c < header.length; c++) {
            html += `<td>${_inlineFormat(r[c] || "")}</td>`;
        }
        html += "</tr>";
    }
    html += "</tbody></table>";
    return html;
}


function _splitRow(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map(c => c.trim());
}


function _escapeHTML(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* =========================================================
   Copy buttons for code blocks
   ========================================================= */

function bindCodeCopyButtons(container) {
    if (!container) return;
    container.querySelectorAll(".md-code-copy").forEach(btn => {
        if (btn.dataset.bound === "1") return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const targetId = btn.dataset.copyTarget;
            const pre = document.getElementById(targetId);
            if (!pre) return;
            const code = pre.querySelector("code");
            const text = (code ? code.textContent : pre.textContent) || "";
            if (typeof copyText === "function") {
                copyText(text, btn);
            } else {
                // Fallback if chat_copy.js is not loaded yet.
                navigator.clipboard.writeText(text).then(() => {
                    const old = btn.textContent;
                    btn.textContent = "✓";
                    setTimeout(() => { btn.textContent = old; }, 700);
                }).catch(() => {});
            }
        });
    });
}