# gui/web/provider_bridge.py
"""
ProviderBridge — Python <-> JS boundary for provider and model management.

Phase 3: multi-provider aware + getCurrentModel validation.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, Slot

from applog.logger import get_logger
from providers.presets import PRESETS, by_key

log = get_logger("gui.web.provider_bridge")


class ProviderBridge(QObject):
    providerChanged = Signal(str)
    apiKeyChanged = Signal(str)
    modelChanged = Signal(str)

    def __init__(
        self,
        *,
        config,
        secrets,
        provider_manager,
        provider_health=None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._secrets = secrets
        self._providers = provider_manager
        self._health = provider_health

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------
    @Slot(result=str)
    def listProvidersJson(self) -> str:
        active = self._active_key()
        payload = []
        for preset in PRESETS:
            payload.append({
                "key": preset.key,
                "name": preset.name,
                "base_url": preset.base_url,
                "docs_url": preset.docs_url,
                "has_api_key": self._has_api_key(preset.key),
                "is_active": preset.key == active,
                "is_registered": preset.key in self._providers.provider_ids(),
            })
        return json.dumps(payload, ensure_ascii=False)

    @Slot(result=str)
    def getActiveProviderJson(self) -> str:
        key = self._active_key()
        preset = by_key(key) if key else None
        payload: dict[str, Any] = {
            "key": key,
            "name": preset.name if preset else "",
            "base_url": preset.base_url if preset else "",
        }
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str, result=bool)
    def setActiveProvider(self, key: str) -> bool:
        key = str(key).strip()
        preset = by_key(key)
        if preset is None:
            log.warning("setActiveProvider: unknown provider", extra={"key": key})
            return False

        if not self._has_api_key(key):
            log.warning(
                "setActiveProvider: no api key configured",
                extra={"key": key},
            )
            return False

        try:
            self._config.set("providers.active", key)
        except Exception:
            log.exception("setActiveProvider: config write failed")
            return False

        if key not in self._providers.provider_ids():
            try:
                self._register_provider(key, preset)
            except Exception:
                log.exception("setActiveProvider: register failed")

        try:
            self._providers.set_active(key)
        except Exception:
            log.exception("setActiveProvider: manager switch failed")

        if self._health is not None:
            try:
                self._health.clear_provider(key)
            except Exception:
                pass

        # If the currently stored model is not valid for this provider,
        # reset it to the provider's default.
        try:
            stored = self._config.get("providers.current_model")
            stored_str = str(stored).strip() if stored else ""
            valid_ids = self._valid_model_ids_for(key, preset)
            if stored_str and stored_str not in valid_ids:
                # Fall back to the provider's default model.
                default_id = valid_ids[0] if valid_ids else ""
                self._config.set("providers.current_model", default_id)
        except Exception:
            log.exception("setActiveProvider: could not reset current model")

        self.providerChanged.emit(key)
        log.info("active provider saved", extra={"key": key})
        return True

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def listModelsJson(self, provider_key: str) -> str:
        key = str(provider_key).strip()
        preset = by_key(key)
        if preset is None:
            return "[]"

        model_ids = self._valid_model_ids_for(key, preset)

        payload = [
            {
                "id": mid,
                "name": mid,
                "description": "",
                "is_default": i == 0,
            }
            for i, mid in enumerate(model_ids)
        ]
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str)
    def setCurrentModel(self, model_id: str) -> None:
        model_id = str(model_id).strip()
        if not model_id:
            return
        try:
            self._config.set("providers.current_model", model_id)
        except Exception:
            log.exception("setCurrentModel failed")
            return
        self.modelChanged.emit(model_id)

    @Slot(result=str)
    def getCurrentModel(self) -> str:
        """
        Return the current model id, but ONLY if it is valid for the
        active provider. Otherwise return the active provider's default.
        """
        active = self._active_key()
        preset = by_key(active) if active else None

        stored = self._config.get("providers.current_model")
        stored_str = str(stored).strip() if stored else ""

        if preset is not None:
            valid_ids = self._valid_model_ids_for(active, preset)
            if stored_str and stored_str in valid_ids:
                return stored_str
            return valid_ids[0] if valid_ids else ""

        return stored_str

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------
    @Slot(str, result=bool)
    def hasApiKey(self, provider_key: str) -> bool:
        return self._has_api_key(provider_key)

    @Slot(str, result=str)
    def getMaskedApiKey(self, provider_key: str) -> str:
        value = self._read_api_key(provider_key)
        if not value:
            return ""
        if len(value) <= 4:
            return "••••"
        return "••••" + value[-4:]

    @Slot(str, str, result=bool)
    def setApiKey(self, provider_key: str, value: str) -> bool:
        key = str(provider_key).strip()
        preset = by_key(key)
        if preset is None:
            return False
        value = str(value).strip()
        if not value:
            return False

        try:
            self._secrets.set("provider", key, value)
        except Exception:
            log.exception("setApiKey failed", extra={"key": key})
            return False

        if key not in self._providers.provider_ids():
            try:
                self._register_provider(key, preset)
            except Exception:
                log.exception("setApiKey: register failed")

        if self._health is not None:
            try:
                self._health.clear_provider(key)
            except Exception:
                pass

        self.apiKeyChanged.emit(key)
        log.info("api key stored", extra={"key": key})
        return True

    @Slot(str, result=bool)
    def deleteApiKey(self, provider_key: str) -> bool:
        key = str(provider_key).strip()
        preset = by_key(key)
        if preset is None:
            return False
        try:
            self._secrets.delete("provider", key)
        except Exception:
            log.exception("deleteApiKey failed", extra={"key": key})
            return False

        try:
            self._providers.unregister(key)
        except Exception:
            log.exception("deleteApiKey: unregister failed")

        try:
            if str(self._config.get("providers.active") or "") == key:
                self._config.set("providers.active", "")
        except Exception:
            pass

        if self._health is not None:
            try:
                self._health.clear_provider(key)
            except Exception:
                pass

        self.apiKeyChanged.emit(key)
        log.info("api key deleted", extra={"key": key})
        return True

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------
    @Slot(str, result=str)
    def testConnection(self, provider_key: str) -> str:
        key = str(provider_key).strip()
        preset = by_key(key)
        if preset is None:
            return json.dumps({"ok": False, "message": "Unknown provider"})

        if not self._has_api_key(key):
            return json.dumps({"ok": False, "message": "No API key configured"})

        try:
            from gui.web.provider_factory import build_provider_for_key
            provider = build_provider_for_key(
                key, config=self._config, secrets=self._secrets,
            )
            provider.validate_connection()
            return json.dumps({"ok": True, "message": "Connected"})
        except Exception as exc:
            log.warning(
                "testConnection failed",
                extra={"key": key, "error": str(exc)},
            )
            return json.dumps({"ok": False, "message": str(exc)[:200]})

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _active_key(self) -> str:
        return str(self._config.get("providers.active") or "").strip()

    def _has_api_key(self, provider_key: str) -> bool:
        return bool(self._read_api_key(provider_key))

    def _read_api_key(self, provider_key: str) -> str:
        try:
            return self._secrets.get("provider", str(provider_key)) or ""
        except Exception:
            log.exception("could not read api key", extra={"key": provider_key})
            return ""

    def _valid_model_ids_for(self, key: str, preset) -> list[str]:
        """
        Config override wins if present, otherwise use the preset list.
        """
        cfg_key = f"providers.models.{key}"
        try:
            cfg_models = self._config.get(cfg_key)
        except Exception:
            cfg_models = None

        if isinstance(cfg_models, list) and cfg_models:
            return [str(m).strip() for m in cfg_models if str(m).strip()]

        return [m.key for m in preset.models]

    def _register_provider(self, key: str, preset) -> None:
        from app.bootstrap import _build_openai_compatible
        self._providers.register(
            key,
            lambda k=key, p=preset: _build_openai_compatible(
                provider_id=k,
                preset=p,
                secrets=self._secrets,
                config=self._config,
            ),
        )