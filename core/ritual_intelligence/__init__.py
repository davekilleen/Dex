"""Local-first Ritual Intelligence runtime for Dex."""

from .db import (
    DatabaseCorruptError,
    DatabaseReadOnlyError,
    RitualIntelligenceError,
    VaultStateError,
)
from .service import RitualIntelligenceService, ensure_runtime_ready

__all__ = [
    "DatabaseCorruptError",
    "DatabaseReadOnlyError",
    "RitualIntelligenceError",
    "RitualIntelligenceService",
    "VaultStateError",
    "ensure_runtime_ready",
]
