# tools/datetime/__init__.py
"""
datetime tool package.

The discovery layer imports `tools.datetime.tool` and reads its TOOL
symbol. Nothing else in the codebase imports this package directly.
"""

from tools.datetime.tool import TOOL

__all__ = ["TOOL"]