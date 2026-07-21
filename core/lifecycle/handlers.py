"""Declarative catalog handler registry; B1 performs no filesystem writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core import portable_contract
from core.lifecycle.model import CatalogError, CatalogFile, CatalogItem


class UnknownHandlerKind(CatalogError):
    """No closed handler exists for an item kind."""


class HandlerPlanRejected(CatalogError):
    """A handler cannot declare an ownership-safe plan."""


def _reject(message: str) -> None:
    raise HandlerPlanRejected(f"catalog handler state is UNKNOWN: {message}")


@dataclass(frozen=True)
class HandlerContext:
    """Caller-observed inputs; handlers never inspect or mutate a vault."""

    existing_paths: frozenset[str] = frozenset()
    acknowledgement_token: str | None = None


@dataclass(frozen=True)
class DeclaredOperation:
    operation: str
    target_path: str
    content_source: str
    expected_sha256: str | None
    ownership_class: str
    contract_action: str


@dataclass(frozen=True)
class HandlerPlan:
    item_id: str
    item_version: str
    hook: str
    operations: tuple[DeclaredOperation, ...]


class CatalogHandler(Protocol):
    kind: str

    def preview(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan: ...

    def apply(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan: ...

    def verify(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan: ...

    def rewind(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan: ...


class SkillHandler:
    """Declare plans for one catalog skill rooted at .claude/skills/<id>."""

    kind = "skill"

    def _checked_file(self, item: CatalogItem, file: CatalogFile, *, exists: bool) -> str:
        prefix = f".claude/skills/{item.id}/"
        if not file.path.startswith(prefix) or file.path == prefix:
            _reject(f"{file.path} is outside the item skill directory {prefix}")
        try:
            resolution = portable_contract.resolve(file.path)
        except portable_contract.ContractViolation as error:
            _reject(f"{file.path} is unclassified by the ownership contract: {error}")
        if resolution.denied:
            _reject(f"{file.path} is hard-denied by the ownership contract")
        if resolution.ownership != file.ownership_class:
            _reject(
                f"{file.path} declares {file.ownership_class} ownership but the contract says "
                f"{resolution.ownership}"
            )
        verdict = portable_contract.update_write_verdict(file.path, exists=exists)
        if not verdict.allowed:
            _reject(f"{file.path} is not write-authorized [{verdict.action}]")
        return verdict.action

    def _plan(self, item: CatalogItem, context: HandlerContext, hook: str) -> HandlerPlan:
        if item.kind != self.kind:
            _reject(f"skill handler cannot plan item kind {item.kind!r}")
        operation = "write" if hook in ("preview", "apply") else hook
        declared = []
        for file in item.files:
            action = self._checked_file(
                item,
                file,
                exists=file.path in context.existing_paths or hook in ("verify", "rewind"),
            )
            source = (
                f"receipt:{item.id}:{file.path}"
                if hook == "rewind"
                else f"release:{file.path}"
            )
            declared.append(
                DeclaredOperation(
                    operation,
                    file.path,
                    source,
                    None if hook == "rewind" else file.sha256,
                    file.ownership_class,
                    action,
                )
            )
        return HandlerPlan(item.id, item.version, hook, tuple(declared))

    def preview(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan:
        return self._plan(item, context, "preview")

    def apply(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan:
        return self._plan(item, context, "apply")

    def verify(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan:
        return self._plan(item, context, "verify")

    def rewind(self, item: CatalogItem, context: HandlerContext) -> HandlerPlan:
        if context.acknowledgement_token != item.rewind.token:
            _reject(f"rewind for {item.id} requires its exact per-item acknowledgement token")
        return self._plan(item, context, "rewind")


class HandlerRegistry:
    """Closed kind-to-handler resolver."""

    def __init__(self, handlers: tuple[CatalogHandler, ...]) -> None:
        self._handlers: dict[str, CatalogHandler] = {}
        for handler in handlers:
            if handler.kind in self._handlers:
                raise ValueError(f"duplicate catalog handler kind: {handler.kind}")
            self._handlers[handler.kind] = handler

    def resolve(self, kind: str) -> CatalogHandler:
        handler = self._handlers.get(kind)
        if handler is None:
            raise UnknownHandlerKind(
                f"catalog handler state is UNKNOWN: no registered handler for kind {kind!r}"
            )
        return handler

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


DEFAULT_REGISTRY = HandlerRegistry((SkillHandler(),))

__all__ = [
    "CatalogHandler",
    "DeclaredOperation",
    "DEFAULT_REGISTRY",
    "HandlerContext",
    "HandlerPlan",
    "HandlerPlanRejected",
    "HandlerRegistry",
    "SkillHandler",
    "UnknownHandlerKind",
]
