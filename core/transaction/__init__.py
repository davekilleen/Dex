"""The Dex transaction core: crash-safe back-up → apply → verify → undo.

The substrate shared by the v1→v2 migrator, the split updater, and the
catalog/lifecycle engine. Every write is authorized by the portable-vault
ownership contract; every state transition is journaled before it takes
effect; every transaction can be rolled back byte-exactly.

Design: ``docs/transaction-core-design.md``.
"""

from core.transaction.lock import LockBusyError, LockContentionError, acquire_owned_lock

__all__ = [
    "LockBusyError",
    "LockContentionError",
    "acquire_owned_lock",
]
