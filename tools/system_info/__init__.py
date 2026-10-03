# tools/system_info/__init__.py
"""
system_info tool package.

The discovery layer imports `tools.system_info.tool` and reads its
TOOL symbol. Nothing else in the codebase imports this package
directly.
"""

from tools.system_info.tool import TOOL

__all__ = ["TOOL"]