"""
sing-box compatibility layer.

Domain rules for handling v2rayN's legacy config format
that sing-box >= 1.13 rejects. These rules are separated
from config patching so they survive refactoring.
"""

from adapters.compatibility.singbox import SingboxCompatibility

__all__ = ['SingboxCompatibility']
