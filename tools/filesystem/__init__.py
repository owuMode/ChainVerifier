# tools/filesystem/__init__.py
"""
filesystem tool package.

The discovery layer imports `tools.filesystem.tool` and reads its
TOOL symbol.
"""

from tools.filesystem.tool import TOOL

__all__ = ["TOOL"]