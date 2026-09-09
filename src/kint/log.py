"""Logging that never touches stdout (the MCP stdio transport owns stdout)."""

from __future__ import annotations

import logging
import sys

from . import paths

_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    lg = logging.getLogger("kint")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        fh = logging.FileHandler(paths.log_path())
        fh.setFormatter(fmt)
        lg.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    lg.addHandler(sh)
    _logger = lg
    return lg


def log(msg: str) -> None:
    get_logger().info(msg)
