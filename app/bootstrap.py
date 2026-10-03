# app/bootstrap.py
"""
Bootstrap — startup sequence.

Multi-provider wiring:
  * Registers every provider preset that has an API key.
  * The active provider comes from config (`providers.active`).
  * All chat/agent flows go through a single ResilientProvider that
    walks the router's candidate chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.dependencies import AppContext
from applog.logger import configure_logging, get_logger
from config.configuration_service import ConfigurationService
from core.agent.agent import Agent
from core.agent.cache import PlanCache, SynthesisCache
from core.agent.executor import Executor
from core.agent.planner import Planner
from core.agent.recovery import Recovery
from core.agent.synthesizer import Synthesizer
from core.agent.verifier import Verifier
from core.events.bus import EventBus
from core.events.events import EventType
from core.events.handlers import AuditBridge
from core.services.chat_service import ChatService
from core.services.classifier import Classifier
from core.services.conversation_context import ConversationContext
from core.services.expander import ShortMessageExpander
from core.services.mode import ModeService
from core.tasks.manager import TaskManager
from core.tasks.repository import TaskRepository
from database.manager import DatabaseManager
from database.repositories import (
    AuditRepository,
    ConversationsRepository,
    MessagesRepository,
    SettingsRepository,
)
from memory.cache import ClassifierCache, EmbeddingCache
from memory.embeddings import EmbeddingService
from memory.manager import MemoryManager
from memory.repositories import MemoryRepository
from native import NativeBridge
from prompts.manager import PromptManager
from providers.adapters.openai_compatible import OpenAICompatibleProvider
from providers.base.capabilities import Capability, ModelCapabilities
from providers.health import ProviderHealth
from providers.manager import ProviderManager
from providers.presets import PRESETS, by_key
from providers.routing.resilient import ResilientProvider
from providers.routing.router import ModelRouter
from security.permission_broker import PermissionBroker
from security.policies import PolicyEngine
from security.secrets import Secrets
from sysinfo.path_manager import PathManager
from sysinfo.platform_service import get_platform_service
from sysinfo.storage_manager import StorageManager
from tools.registry import ToolRegistry, discover_tools


def bootstrap() -> AppContext:
    platform_service = get_platform_service()
    if not platform_service.is_windows():
        raise RuntimeError(
            f"AIProduct requires Windows. Detected: {platform_service.info.os_name}"
        )

    path_manager = PathManager(platform_service)
    storage = StorageManager(path_manager)
    root = storage.prepare_default()

    configure_logging(path_manager.paths().logs_dir)
    log = get_logger("bootstrap")
    log.info(
        "storage ready",
        extra={"root": str(root), "custom": path_manager.is_custom()},
    )

    project_root = Path(__file__).resolve().parent.parent
    defaults_path = project_root / "config" / "defaults" / "defaults.yaml"
    config = ConfigurationService(defaults_path)

    # Database
    db_path = path_manager.database_file()
    migrations_dir = project_root / "database" / "migrations"
    db = DatabaseManager(
        db_path=db_path,
        migrations_dir=migrations_dir,
        busy_timeout_ms=config.get("database.busy_timeout_ms", 5000),
        journal_mode=config.get("database.journal_mode", "WAL"),
    )
    db.open()

    settings_repo = SettingsRepository(db)
    config.attach_settings_repository(settings_repo)

    # Security
    secrets = Secrets(path_manager.paths().runtime_dir / "secrets")
    policies = PolicyEngine()
    audit = AuditRepository(db)

    # Event bus
    event_bus = EventBus()
    AuditBridge(audit, db).attach(event_bus)

    # Permission broker
    permission_broker = PermissionBroker(
        event_bus, timeout_s=60.0, config=config
    )

    # Task manager
    task_repo = TaskRepository(db)
    task_manager = TaskManager(task_repo, event_bus)

    # Prompts
    prompts_root = project_root / "prompts"
    prompts = PromptManager(prompts_root)
    log.info("prompt manager ready", extra={"root": str(prompts_root)})

    # Native bridge
    native_bridge = NativeBridge(project_root)
    if native_bridge.is_available():
        log.info(
            "native bridge ready",
            extra={
                "native_version": native_bridge.native_version(),
                "capabilities": sorted(native_bridge.capabilities().keys()),
            },
        )
    else:
        log.info(
            "native bridge not available",
            extra={"reason": native_bridge.load_error()},
        )

    # Tools
    tools_root = project_root / "tools"
    tool_registry = ToolRegistry()
    discover_tools(tools_root, tool_registry)
    tool_registry.seal()
    log.info(
        "tool registry ready",
        extra={"count": len(tool_registry), "ids": tool_registry.tool_ids()},
    )

    # ---- Providers (multi) --------------------------------------
    provider_manager = ProviderManager()
    registered_providers: list[str] = []

    for preset in PRESETS:
        key = preset.key
        api_key = ""
        try:
            api_key = secrets.get("provider", key) or ""
        except Exception:
            api_key = ""

        if not api_key:
            continue
        if preset.adapter != "openai_compatible":
            continue

        provider_manager.register(
            key,
            lambda k=key, p=preset: _build_openai_compatible(
                provider_id=k,
                preset=p,
                secrets=secrets,
                config=config,
            ),
        )
        registered_providers.append(key)

    active_key = str(config.get("providers.active") or "").strip()
    if active_key and active_key in registered_providers:
        try:
            provider_manager.set_active(active_key)
        except Exception:
            log.exception("could not set active provider")
    elif registered_providers:
        try:
            provider_manager.set_active(registered_providers[0])
        except Exception:
            log.exception("could not set default active provider")

    log.info(
        "provider manager ready",
        extra={
            "registered": sorted(registered_providers),
            "active": provider_manager.active_id(),
        },
    )

    # Provider health + router + resilient provider
    provider_health = ProviderHealth(db, cooldown_s=60)
    router = ModelRouter(
        provider_manager=provider_manager,
        config=config,
        health=provider_health,
    )
    resilient = ResilientProvider(
        router=router,
        health=provider_health,
        provider_id="resilient",
    )

    # Local caches
    embedding_cache = EmbeddingCache(db, memory_lru_size=512)
    classifier_cache = ClassifierCache(db, memory_lru_size=512)

    # Agent caches
    cache_cfg_enabled = bool(config.get("agent.cache.enabled", True))
    cache_ttl = int(config.get("agent.cache.ttl_seconds", 3600))
    plan_cache = PlanCache(
        db, ttl_seconds=cache_ttl if cache_cfg_enabled else 0
    )
    synth_cache = SynthesisCache(
        db, ttl_seconds=cache_ttl if cache_cfg_enabled else 0
    )
    log.info(
        "agent caches ready",
        extra={"enabled": cache_cfg_enabled, "ttl": cache_ttl},
    )

    # Memory
    memory_repo = MemoryRepository(db)
    embedding_service = EmbeddingService(
        provider_manager=provider_manager,
        config=config,
        cache=embedding_cache,
    )
    memory_manager = MemoryManager(
        memory_repo,
        embedding_service=embedding_service,
    )
    log.info(
        "memory manager ready",
        extra={
            "count": memory_manager.count(),
            "embeddings_available": embedding_service.is_available(),
            "embedding_cache_size": embedding_cache.size(),
            "classifier_cache_size": classifier_cache.size(),
        },
    )

    # Mode service
    modes = ModeService(config)
    log.info("mode service ready", extra={"mode": modes.get().value})

    # Repositories (shared across ChatService, agent, etc.)
    messages_repo = MessagesRepository(db)
    conversations_repo = ConversationsRepository(db)

    # ---- Factory callables ------------------------------------------
    def _memory_enabled() -> bool:
        try:
            return bool(config.get("memory.enabled", True))
        except Exception:
            return True

    def _pick_model_for_flow(flow: str) -> str:
        """
        Return a sensible default model for a flow (fast vs strong).
        Uses the router so we get a real, available model.
        """
        try:
            cfg_key = f"providers.models.{provider_manager.active_id()}"
            models = config.get(cfg_key) if config is not None else None
            if isinstance(models, list) and models:
                if flow == "strong" and len(models) > 1:
                    return str(models[0])
                return str(models[-1])
        except Exception:
            pass
        try:
            primary = router.primary()
            if primary is not None:
                return primary.model
        except Exception:
            pass
        return "gpt-4o-mini"

    def agent_factory() -> Optional[Agent]:
        if not registered_providers:
            return None
        strong_model = _pick_model_for_flow("strong")
        return Agent(
            planner=Planner(
                resilient,
                tool_registry,
                prompts,
                memory_manager=memory_manager if _memory_enabled() else None,
                cache=plan_cache,
            ),
            executor=Executor(
                tool_registry,
                policies,
                event_bus,
                permission_broker=permission_broker,
            ),
            verifier=Verifier(tool_registry, event_bus),
            recovery=Recovery(),
            tasks=task_manager,
            default_model=strong_model,
            synthesizer=Synthesizer(resilient, prompts, cache=synth_cache),
            messages_repo=messages_repo,
        )

    def chat_factory() -> Optional[ChatService]:
        if not registered_providers:
            return None
        fast_model = _pick_model_for_flow("fast")
        context_service = ConversationContext(
            provider=resilient,
            prompts=prompts,
            model=fast_model,
            conversations_repo=conversations_repo,
            messages_repo=messages_repo,
        )
        expander = ShortMessageExpander(
            provider=resilient,
            prompts=prompts,
            model=fast_model,
        )
        return ChatService(
            resilient,
            prompts,
            model=fast_model,
            memory_manager=memory_manager if _memory_enabled() else None,
            conversation_context=context_service,
            expander=expander,
            config=config,
        )

    def classifier_factory() -> Optional[Classifier]:
        if not registered_providers:
            return None
        fast_model = _pick_model_for_flow("fast")
        return Classifier(
            resilient,
            tool_registry,
            model=fast_model,
            cache=classifier_cache,
        )

    def memory_extractor_factory():
        if not _memory_enabled():
            return None
        if not registered_providers:
            return None
        fast_model = _pick_model_for_flow("fast")
        try:
            from memory.extractor import MemoryExtractor
            return MemoryExtractor(resilient, prompts), fast_model
        except Exception:
            log.exception("memory_extractor_factory failed")
            return None

    agent = agent_factory()
    chat_service = chat_factory()
    classifier = classifier_factory()

    if agent is not None:
        log.info("agent ready")
    else:
        log.info("agent not initialized (no active provider configured)")

    ctx = AppContext(
        platform=platform_service,
        paths=path_manager,
        storage=storage,
        config=config,
        database=db,
        logger_ready=True,
    )
    ctx.put("secrets", secrets)
    ctx.put("policies", policies)
    ctx.put("audit", audit)
    ctx.put("event_bus", event_bus)
    ctx.put("permission_broker", permission_broker)
    ctx.put("memory_manager", memory_manager)
    ctx.put("memory_repository", memory_repo)
    ctx.put("embedding_service", embedding_service)
    ctx.put("embedding_cache", embedding_cache)
    ctx.put("classifier_cache", classifier_cache)
    ctx.put("plan_cache", plan_cache)
    ctx.put("synth_cache", synth_cache)
    ctx.put("task_manager", task_manager)
    ctx.put("task_repository", task_repo)
    ctx.put("messages_repo", messages_repo)
    ctx.put("conversations_repo", conversations_repo)
    ctx.put("prompts", prompts)
    ctx.put("native_bridge", native_bridge)
    ctx.put("tool_registry", tool_registry)
    ctx.put("provider_manager", provider_manager)
    ctx.put("provider_health", provider_health)
    ctx.put("router", router)
    ctx.put("resilient_provider", resilient)
    ctx.put("modes", modes)
    ctx.put("agent", agent)
    ctx.put("chat_service", chat_service)
    ctx.put("classifier", classifier)
    ctx.put("agent_factory", agent_factory)
    ctx.put("chat_factory", chat_factory)
    ctx.put("classifier_factory", classifier_factory)
    ctx.put("memory_extractor_factory", memory_extractor_factory)

    from app.lifecycle import register_shutdown_hook

    def _publish_shutdown(_ctx: AppContext) -> None:
        _ctx.get("event_bus").publish(
            EventType.APPLICATION_SHUTTING_DOWN,
            actor="system",
        )

    def _close_providers(_ctx: AppContext) -> None:
        _ctx.get("provider_manager").close()

    def _close_db(_ctx: AppContext) -> None:
        if _ctx.database is not None:
            _ctx.database.close()

    register_shutdown_hook("database.close", _close_db)
    register_shutdown_hook("providers.close", _close_providers)
    register_shutdown_hook("event_bus.application_shutting_down", _publish_shutdown)

    event_bus.publish(
        EventType.APPLICATION_STARTED,
        actor="system",
        payload={
            "root": str(root),
            "tools": tool_registry.tool_ids(),
            "providers": provider_manager.provider_ids(),
            "native_available": native_bridge.is_available(),
            "mode": modes.get().value,
        },
    )

    log.info("bootstrap complete")
    return ctx


# ----------------------------------------------------------------------
def _build_openai_compatible(
    *,
    provider_id: str,
    preset,
    secrets,
    config,
) -> OpenAICompatibleProvider:
    """
    Build an OpenAI-compatible provider for a given preset.
    """
    api_key = secrets.get("provider", provider_id) or ""
    base_url = str(
        config.get(f"providers.{provider_id}.base_url") or preset.base_url
    )

    config_models = config.get(f"providers.models.{provider_id}")
    if isinstance(config_models, list) and config_models:
        model_ids = [str(m).strip() for m in config_models if str(m).strip()]
    else:
        model_ids = [m.key for m in preset.models]

    models = tuple(
        ModelCapabilities(
            model_id=mid,
            capabilities=frozenset({
                Capability.STREAMING,
                Capability.TOOL_CALLING,
                Capability.STRUCTURED_OUTPUT,
            }),
            context_window=128_000,
            max_output_tokens=4_096,
        )
        for mid in model_ids
    )

    return OpenAICompatibleProvider(
        provider_id=provider_id,
        base_url=base_url,
        api_key=api_key,
        models=models,
    )