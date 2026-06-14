# Copyright (c) 2026 Kevin Landers. SPDX-License-Identifier: MIT
"""Runtime version string for logulator."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("logulator")
except PackageNotFoundError:
    __version__ = "dev"
