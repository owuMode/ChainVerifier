# security/redaction.py
"""
Redaction — re-exported from applog so security and logging share
exactly one implementation (spec §52, §109.32).

Do not add a second implementation here. Any change must go into
applog/redaction.py so both call sites stay in lockstep.
"""

from __future__ import annotations

from applog.redaction import REDACTED, redact_mapping, redact_value

__all__ = ["REDACTED", "redact_mapping", "redact_value"]