# gui/resources/loader.py

from __future__ import annotations

from pathlib import Path

_RESOURCES_DIR = Path(__file__).resolve().parent

_HTML_FILE = _RESOURCES_DIR / "chat.html"

_CSS_FILE = _RESOURCES_DIR / "chat.css"
_MODE_CSS_FILE = _RESOURCES_DIR / "chat_mode.css"
_PROVIDERS_CSS_FILE = _RESOURCES_DIR / "chat_providers.css"
_TASKS_CSS_FILE = _RESOURCES_DIR / "chat_tasks.css"
_SETTINGS_CSS_FILE = _RESOURCES_DIR / "chat_settings.css"
_PERMISSION_CSS_FILE = _RESOURCES_DIR / "chat_permission.css"
_MEMORY_CSS_FILE = _RESOURCES_DIR / "chat_memory.css"
_MARKDOWN_CSS_FILE = _RESOURCES_DIR / "chat_markdown.css"
_DIALOGS_CSS_FILE = _RESOURCES_DIR / "chat_dialogs.css"
_EDIT_CSS_FILE = _RESOURCES_DIR / "chat_edit.css"
_HIGHLIGHT_CSS_FILE = _RESOURCES_DIR / "highlight_theme.css"

_JS_FILE = _RESOURCES_DIR / "chat.js"
_EDIT_JS_FILE = _RESOURCES_DIR / "chat_edit.js"
_COPY_JS_FILE = _RESOURCES_DIR / "chat_copy.js"
_THOUGHT_JS_FILE = _RESOURCES_DIR / "chat_thought.js"
_MENUS_JS_FILE = _RESOURCES_DIR / "chat_menus.js"
_MARKDOWN_JS_FILE = _RESOURCES_DIR / "chat_markdown.js"
_DIALOGS_JS_FILE = _RESOURCES_DIR / "chat_dialogs.js"
_MODE_JS_FILE = _RESOURCES_DIR / "chat_mode.js"
_PROVIDERS_JS_FILE = _RESOURCES_DIR / "chat_providers.js"
_TASKS_JS_FILE = _RESOURCES_DIR / "chat_tasks.js"
_SETTINGS_JS_FILE = _RESOURCES_DIR / "chat_settings.js"
_PERMISSION_JS_FILE = _RESOURCES_DIR / "chat_permission.js"
_MEMORY_JS_FILE = _RESOURCES_DIR / "chat_memory.js"

_QWEBCHANNEL_FILE = _RESOURCES_DIR / "qwebchannel.js"
_HIGHLIGHT_JS_FILE = _RESOURCES_DIR / "highlight.min.js"


def load_chat_html() -> str:
    html = _read(_HTML_FILE)

    html = html.replace("/*{{CSS}}*/", _read(_CSS_FILE))
    html = html.replace("/*{{MODE_CSS}}*/", _read(_MODE_CSS_FILE))
    html = html.replace("/*{{PROVIDERS_CSS}}*/", _read(_PROVIDERS_CSS_FILE))
    html = html.replace("/*{{TASKS_CSS}}*/", _read(_TASKS_CSS_FILE))
    html = html.replace("/*{{SETTINGS_CSS}}*/", _read(_SETTINGS_CSS_FILE))
    html = html.replace("/*{{PERMISSION_CSS}}*/", _read(_PERMISSION_CSS_FILE))
    html = html.replace("/*{{MEMORY_CSS}}*/", _read(_MEMORY_CSS_FILE))
    html = html.replace("/*{{EDIT_CSS}}*/", _read(_EDIT_CSS_FILE))
    html = html.replace("/*{{MARKDOWN_CSS}}*/", _read(_MARKDOWN_CSS_FILE))
    html = html.replace("/*{{DIALOGS_CSS}}*/", _read(_DIALOGS_CSS_FILE))
    html = html.replace("/*{{HIGHLIGHT_CSS}}*/", _read(_HIGHLIGHT_CSS_FILE))

    # highlight.js first, then qwebchannel + markdown + dialogs + core.
    highlight_scripts = _read(_HIGHLIGHT_JS_FILE)
    html = html.replace("/*{{HIGHLIGHT_JS}}*/", highlight_scripts)

    core_scripts = (
        _read(_QWEBCHANNEL_FILE)
        + "\n\n"
        + _read(_MARKDOWN_JS_FILE)
        + "\n\n"
        + _read(_DIALOGS_JS_FILE)
        + "\n\n"
        + _read(_JS_FILE)
    )
    html = html.replace("/*{{JS}}*/", core_scripts)

    html = html.replace("/*{{EDIT_JS}}*/", _read(_EDIT_JS_FILE))
    html = html.replace("/*{{COPY_JS}}*/", _read(_COPY_JS_FILE))
    html = html.replace("/*{{THOUGHT_JS}}*/", _read(_THOUGHT_JS_FILE))
    html = html.replace("/*{{MENUS_JS}}*/", _read(_MENUS_JS_FILE))

    html = html.replace("/*{{MODE_JS}}*/", _read(_MODE_JS_FILE))
    html = html.replace("/*{{PROVIDERS_JS}}*/", _read(_PROVIDERS_JS_FILE))
    html = html.replace("/*{{TASKS_JS}}*/", _read(_TASKS_JS_FILE))
    html = html.replace("/*{{SETTINGS_JS}}*/", _read(_SETTINGS_JS_FILE))
    html = html.replace("/*{{PERMISSION_JS}}*/", _read(_PERMISSION_JS_FILE))
    html = html.replace("/*{{MEMORY_JS}}*/", _read(_MEMORY_JS_FILE))

    return html


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"GUI resource missing: {path}")
    return path.read_text(encoding="utf-8")