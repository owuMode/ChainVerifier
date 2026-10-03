# core/events/events.py
"""
Event catalogue (spec §45).

These strings are the *public contract* between producers (agent, tools,
services) and consumers (GUI, audit bridge, logging). Never invent an
event name inline — add it here.

The enum values are used verbatim as `events.event_type` in the DB.
Renaming an existing value is a breaking change: add a new one and
deprecate the old one via a migration if necessary.
"""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    # ---- conversation ----
    USER_MESSAGE = "USER_MESSAGE"
    AI_RESPONSE_STARTED = "AI_RESPONSE_STARTED"
    AI_RESPONSE_STREAM = "AI_RESPONSE_STREAM"
    AI_RESPONSE_COMPLETED = "AI_RESPONSE_COMPLETED"

    # ---- tasks ----
    TASK_CREATED = "TASK_CREATED"
    TASK_UPDATED = "TASK_UPDATED"
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"

    # ---- tools ----
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"

    # ---- synthesis (phase 3) ----
    SYNTHESIS_CHUNK = "SYNTHESIS_CHUNK"

    # ---- permissions ----
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # ---- voice ----
    VOICE_STARTED = "VOICE_STARTED"
    VOICE_STOPPED = "VOICE_STOPPED"

    # ---- memory ----
    MEMORY_CREATED = "MEMORY_CREATED"

    # ---- auth / license ----
    LICENSE_UPDATED = "LICENSE_UPDATED"

    # ---- settings ----
    SETTINGS_CHANGED = "SETTINGS_CHANGED"

    # ---- application lifecycle ----
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_SHUTTING_DOWN = "APPLICATION_SHUTTING_DOWN"


def is_valid_event_type(value: str) -> bool:
    try:
        EventType(value)
        return True
    except ValueError:
        return False