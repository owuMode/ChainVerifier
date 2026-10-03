# native/__init__.py
"""
Native package.

This package only re-exports the bridge. The compiled module.pyd is
loaded at runtime by NativeBridge and never imported directly by any
other Python code in the application.
"""

from native.bridge.native_bridge import NativeBridge, NativeBridgeError

__all__ = ["NativeBridge", "NativeBridgeError"]