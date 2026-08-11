"""Modular runtime for ComfyUI Easy Panel.

The top-level :mod:`easy_panel` module remains the compatibility facade and
command-line entry point.  New code lives in this package so features can be
tested and evolved independently without changing the user's launch command.
"""

APP_VERSION = "2.0.0"

__all__ = ["APP_VERSION"]
