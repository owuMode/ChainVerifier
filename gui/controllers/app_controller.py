# gui/controllers/app_controller.py
"""
AppController — top-level wiring between AppContext and the GUI.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject

from app.dependencies import AppContext
from applog.logger import get_logger
from database.repositories import (
    ConversationsRepository,
    MessagesRepository,
)
from gui.web.bridge import GuiBridge
from gui.web.history_bridge import HistoryBridge
from gui.web.memory_bridge import MemoryBridge
from gui.web.permission_bridge import PermissionBridge
from gui.web.provider_bridge import ProviderBridge
from gui.web.settings_bridge import SettingsBridge
from gui.web.task_tracker import TaskTracker
from gui.web.tasks_bridge import TasksBridge
from gui.web.window import ChatWindow

log = get_logger("gui.controllers.app")


class AppController(QObject):

    def __init__(
        self,
        *,
        window: ChatWindow,
        ctx: AppContext,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)

        self._window = window
        self._ctx = ctx

        chat_service = _safe_get(ctx, "chat_service")
        agent = _safe_get(ctx, "agent")
        classifier = _safe_get(ctx, "classifier")
        tasks = _safe_get(ctx, "task_manager")
        task_repo = _safe_get(ctx, "task_repository")
        audit = _safe_get(ctx, "audit")
        modes = _safe_get(ctx, "modes")
        bus = _safe_get(ctx, "event_bus")
        provider_manager = _safe_get(ctx, "provider_manager")
        secrets = _safe_get(ctx, "secrets")
        broker = _safe_get(ctx, "permission_broker")
        memory_manager = _safe_get(ctx, "memory_manager")
        memory_extractor_factory = _safe_get(ctx, "memory_extractor_factory")
        memory_repo = _safe_get(ctx, "memory_repository")
        prompts = _safe_get(ctx, "prompts")

        if ctx.database is None:
            raise RuntimeError("AppController requires an open database on AppContext.")

        conversations_repo = ConversationsRepository(ctx.database)
        messages_repo = MessagesRepository(ctx.database)

        bridge = GuiBridge(
            chat_service=chat_service,
            agent=agent,
            classifier=classifier,
            tasks=tasks,
            config=ctx.config,
            modes=modes,
            memory_extractor_factory=memory_extractor_factory,
            messages_repo=messages_repo,
            memory_manager=memory_manager,
            permission_broker=broker,
            parent=self,
        )

        history_bridge = HistoryBridge(
            conversations_repo=conversations_repo,
            messages_repo=messages_repo,
            parent=self,
        )

        provider_bridge = None
        if secrets is not None and provider_manager is not None:
            provider_bridge = ProviderBridge(
                config=ctx.config,
                secrets=secrets,
                provider_manager=provider_manager,
                parent=self,
            )

        tasks_bridge = None
        if tasks is not None and task_repo is not None and audit is not None:
            tasks_bridge = TasksBridge(
                tasks=tasks,
                task_repo=task_repo,
                audit_repo=audit,
                agent=agent,
                parent=self,
            )

        settings_bridge = SettingsBridge(
            config=ctx.config,
            path_manager=ctx.paths,
            storage_manager=ctx.storage,
            platform_service=ctx.platform,
            parent=self,
        )

        permission_bridge = None
        if broker is not None and bus is not None:
            permission_bridge = PermissionBridge(
                broker=broker,
                bus=bus,
                parent=self,
            )

        memory_bridge = None
        if memory_manager is not None:
            memory_bridge = MemoryBridge(
                memory_manager=memory_manager,
                config=ctx.config,
                parent=self,
            )

            try:
                if provider_manager is not None and prompts is not None and memory_repo is not None:
                    from memory.consolidator import MemoryConsolidator
                    provider = provider_manager.active()
                    model_name = getattr(agent, "_default_model", None)
                    if not model_name:
                        model_name = str(
                            ctx.config.get("providers.openai_compatible.default_model")
                            or "gpt-4o-mini"
                        )
                    consolidator = MemoryConsolidator(
                        provider=provider,
                        prompts=prompts,
                        repo=memory_repo,
                    )
                    memory_bridge.set_consolidator(consolidator, model_name)
                    log.info("consolidator wired", extra={"model": model_name})
                else:
                    log.info(
                        "consolidator not wired (missing provider/prompts/repo)",
                        extra={
                            "has_provider_manager": provider_manager is not None,
                            "has_prompts": prompts is not None,
                            "has_memory_repo": memory_repo is not None,
                        },
                    )
            except Exception:
                log.exception("could not wire consolidator")

        task_tracker = TaskTracker(bus, parent=self) if bus is not None else None

        window.attach_bridges(
            bridge=bridge,
            history_bridge=history_bridge,
            provider_bridge=provider_bridge,
            tasks_bridge=tasks_bridge,
            settings_bridge=settings_bridge,
            permission_bridge=permission_bridge,
            memory_bridge=memory_bridge,
            task_tracker=task_tracker,
        )

        log.info(
            "AppController wired",
            extra={
                "has_chat_service": chat_service is not None,
                "has_agent": agent is not None,
                "has_provider_bridge": provider_bridge is not None,
                "has_tasks_bridge": tasks_bridge is not None,
                "has_settings_bridge": settings_bridge is not None,
                "has_permission_bridge": permission_bridge is not None,
                "has_memory_bridge": memory_bridge is not None,
                "has_memory_extractor_factory": memory_extractor_factory is not None,
                "has_task_tracker": task_tracker is not None,
            },
        )


def _safe_get(ctx: AppContext, key: str):
    try:
        return ctx.get(key)
    except KeyError:
        return None