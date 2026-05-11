"""Compatibility alias for legacy jobs.slack_bot imports."""

from integrations.slack import bot as _impl
import sys as _sys

_sys.modules[__name__] = _impl
