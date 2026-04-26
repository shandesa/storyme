"""
core/log_config.py
==================
Centralised logging configuration for StoryMe backend.

Global control via environment variables:
    LOG_LEVEL           Root level (default: INFO)
                        Values: DEBUG | INFO | WARNING | ERROR | CRITICAL

Per-module overrides via LOG_LEVEL_{MODULE}:
    LOG_LEVEL_FACE_BLEND      default: DEBUG
    LOG_LEVEL_FACE_PIPELINE   default: DEBUG
    LOG_LEVEL_IMAGE_SERVICE   default: DEBUG
    LOG_LEVEL_GENERATE        default: DEBUG   (generate.py + generate_async.py)
    LOG_LEVEL_GENERATION_MODE default: DEBUG
    LOG_LEVEL_GENERATION_SVC  default: INFO    (generation_service.py)
    LOG_LEVEL_SESSION_STORE   default: INFO
    LOG_LEVEL_STORY_SERVICE   default: INFO
    LOG_LEVEL_AUTH            default: INFO
    LOG_LEVEL_AZURE           default: WARNING (suppress verbose Azure SDK)

Example .env:
    LOG_LEVEL=DEBUG
    LOG_LEVEL_AZURE=ERROR
    LOG_LEVEL_FACE_BLEND=DEBUG

Usage — call once at server startup (server.py):
    from core.log_config import configure_logging
    configure_logging()

All modules just use:
    import logging
    logger = logging.getLogger(__name__)

The name-to-level mapping is applied automatically by configure_logging().
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional


# ─── Module logger name → env-var mapping ─────────────────────────────────────
_MODULE_OVERRIDES: dict[str, str] = {
    # image generation core
    "services.face_blend_service":   "LOG_LEVEL_FACE_BLEND",
    "services.face_pipeline_service":"LOG_LEVEL_FACE_PIPELINE",
    "services.image_service":        "LOG_LEVEL_IMAGE_SERVICE",
    "services.generation_mode":      "LOG_LEVEL_GENERATION_MODE",
    "services.generation_service":   "LOG_LEVEL_GENERATION_SVC",
    "services.story_service":        "LOG_LEVEL_STORY_SERVICE",
    "services.email_service":        "LOG_LEVEL_EMAIL",
    "services.pdf_service":          "LOG_LEVEL_PDF",
    "services.quality_evaluator":    "LOG_LEVEL_QUALITY",
    # routes
    "routes.generate":               "LOG_LEVEL_GENERATE",
    "routes.generate_async":         "LOG_LEVEL_GENERATE",
    "routes.generate_v2":            "LOG_LEVEL_GENERATE",
    "routes.generate_v3":            "LOG_LEVEL_GENERATE",
    "routes.print_orders":           "LOG_LEVEL_ORDERS",
    "routes.auth":                   "LOG_LEVEL_AUTH",
    # core
    "core.session_store":            "LOG_LEVEL_SESSION_STORE",
    "core.storage":                  "LOG_LEVEL_STORAGE",
    "core.user_store":               "LOG_LEVEL_USER_STORE",
    # Azure SDK (very verbose at DEBUG/INFO)
    "azure":                         "LOG_LEVEL_AZURE",
    "azure.core":                    "LOG_LEVEL_AZURE",
    "azure.core.pipeline":           "LOG_LEVEL_AZURE",
}

# ─── Defaults when env var is not set ─────────────────────────────────────────
# ── DEVELOPMENT MODE: all modules at DEBUG ──────────────────────────────────
# Set LOG_LEVEL_AZURE=WARNING in production to silence the Azure SDK noise.
# Set LOG_LEVEL=INFO in production to reduce overall verbosity.
_ENV_DEFAULTS: dict[str, str] = {
    "LOG_LEVEL_FACE_BLEND":      "DEBUG",
    "LOG_LEVEL_FACE_PIPELINE":   "DEBUG",
    "LOG_LEVEL_IMAGE_SERVICE":   "DEBUG",
    "LOG_LEVEL_GENERATION_MODE": "DEBUG",
    "LOG_LEVEL_GENERATION_SVC":  "DEBUG",
    "LOG_LEVEL_GENERATE":        "DEBUG",
    "LOG_LEVEL_ORDERS":          "DEBUG",
    "LOG_LEVEL_AUTH":            "DEBUG",
    "LOG_LEVEL_SESSION_STORE":   "DEBUG",
    "LOG_LEVEL_STORAGE":         "DEBUG",
    "LOG_LEVEL_USER_STORE":      "DEBUG",
    "LOG_LEVEL_EMAIL":           "DEBUG",
    "LOG_LEVEL_PDF":             "DEBUG",
    "LOG_LEVEL_QUALITY":         "DEBUG",
    "LOG_LEVEL_AZURE":           "WARNING",   # keep Azure SDK quiet even in dev
}


def _resolve_level(env_var: str, fallback: str = "INFO") -> int:
    raw = os.environ.get(env_var, _ENV_DEFAULTS.get(env_var, fallback))
    lvl = logging.getLevelName(raw.upper())
    return lvl if isinstance(lvl, int) else logging.INFO


def configure_logging() -> None:
    """
    Configure root logger and per-module overrides.
    Safe to call multiple times — idempotent.
    """
    root_level = _resolve_level("LOG_LEVEL", "DEBUG")

    # ── Root handler ──────────────────────────────────────────────────────────
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. uvicorn set it up) — just adjust levels
        root.setLevel(root_level)
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(root_level)
        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(fmt)
        root.addHandler(handler)
        root.setLevel(root_level)

    # ── Per-module overrides ───────────────────────────────────────────────────
    for module_name, env_var in _MODULE_OVERRIDES.items():
        level = _resolve_level(env_var, "INFO")
        logging.getLogger(module_name).setLevel(level)

    logging.getLogger(__name__).info(
        "Logging configured — root=%s | face_blend=%s | generate=%s | azure=%s",
        logging.getLevelName(root_level),
        logging.getLevelName(_resolve_level("LOG_LEVEL_FACE_BLEND")),
        logging.getLevelName(_resolve_level("LOG_LEVEL_GENERATE")),
        logging.getLevelName(_resolve_level("LOG_LEVEL_AZURE")),
    )


def get_effective_level(module_name: str) -> str:
    """Return the effective log level name for a given logger."""
    return logging.getLevelName(logging.getLogger(module_name).getEffectiveLevel())
