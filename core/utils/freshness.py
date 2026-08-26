"""Whether what the assistant knows is still true, per source.

The problem this addresses: context carries no freshness marker. A calendar read
from four hours ago and one from a minute ago sit side by side with identical
authority, so in a long session stale observations get used as though fresh.

Two deliberate boundaries, because they decide what this module can honestly do:

**Observations are recorded mechanically, not self-reported.** An assistant that
cannot notice its context is stale also cannot be trusted to record when it last
looked. The companion PostToolUse hook stamps a source the moment a tool that
reads it is called, so the ledger reflects what happened rather than what the
assistant believes happened.

**Staleness is a fact about the ledger, not about the assistant.** This module
answers "was `calendar` observed within its half-life", which is checkable. It
does not answer "does the assistant hold a stale belief", which is not.

The useful consequence is the artefact contract: `missing_for("daily-plan")`
returns the sources a daily plan requires and does not have fresh, and that is
enforceable from outside the assistant.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_RELATIVE = Path("System") / "knowledge-half-life.yaml"
LEDGER_RELATIVE = Path("System") / ".dex" / "observations.json"

NEVER = "never"
_DURATION = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[smhd])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class HalfLifeUnavailable(RuntimeError):
    """The configuration could not be read, so nothing can be judged stale.

    Deliberately distinct from "everything is fresh". A caller that cannot read
    the config knows nothing about freshness and must say so rather than
    reporting a clean result.
    """


def parse_duration(value: Any) -> float | None:
    """Seconds for a duration string, or None for ``never``.

    Raises ValueError on anything else, because a typo in a half-life should
    fail loudly rather than silently become "fresh forever".
    """
    if isinstance(value, str) and value.strip().lower() == NEVER:
        return None
    match = _DURATION.match(str(value))
    if not match:
        raise ValueError(f"not a duration: {value!r} (expected e.g. 30m, 4h, 2d, or never)")
    return float(match.group("value")) * _UNIT_SECONDS[match.group("unit").lower()]


@dataclass(frozen=True)
class Source:
    name: str
    half_life_seconds: float | None  # None means it never decays

    @property
    def decays(self) -> bool:
        return self.half_life_seconds is not None


@dataclass(frozen=True)
class Config:
    sources: dict[str, Source]
    artefacts: dict[str, tuple[str, ...]]

    def source(self, name: str) -> Source | None:
        return self.sources.get(name)


def load_config(vault_root: Path) -> Config:
    """Read the half-life declaration. Raises when it cannot be trusted."""
    path = vault_root / CONFIG_RELATIVE
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as error:
        raise HalfLifeUnavailable(f"no half-life config at {CONFIG_RELATIVE}") from error
    except Exception as error:  # noqa: BLE001 - surfaced as one honest failure
        raise HalfLifeUnavailable(f"half-life config unreadable: {error}") from error

    if not isinstance(raw, dict):
        raise HalfLifeUnavailable("half-life config is not a mapping")

    sources: dict[str, Source] = {}
    for name, body in (raw.get("sources") or {}).items():
        if not isinstance(body, dict) or "half_life" not in body:
            raise HalfLifeUnavailable(f"source {name!r} has no half_life")
        try:
            seconds = parse_duration(body["half_life"])
        except ValueError as error:
            raise HalfLifeUnavailable(f"source {name!r}: {error}") from error
        sources[str(name)] = Source(str(name), seconds)

    artefacts: dict[str, tuple[str, ...]] = {}
    for name, body in (raw.get("artefacts") or {}).items():
        required = (body or {}).get("requires_fresh") or []
        unknown = [s for s in required if s not in sources]
        if unknown:
            # A contract naming a source that does not exist would silently
            # never be satisfiable, which is worse than refusing to load.
            raise HalfLifeUnavailable(f"artefact {name!r} requires unknown source(s): {unknown}")
        artefacts[str(name)] = tuple(str(s) for s in required)

    return Config(sources=sources, artefacts=artefacts)


def _ledger_path(vault_root: Path) -> Path:
    return vault_root / LEDGER_RELATIVE


def read_ledger(vault_root: Path) -> dict[str, float]:
    """Last observation time per source. A missing ledger is empty, not an error."""
    try:
        data = json.loads(_ledger_path(vault_root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def observe(vault_root: Path, source: str, *, at: float | None = None) -> None:
    """Record that a source was just read. Written atomically."""
    import os

    path = _ledger_path(vault_root)
    ledger = read_ledger(vault_root)
    ledger[source] = time.time() if at is None else at
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Losing one observation is survivable; failing a prompt over it is not.
        return


def age_seconds(vault_root: Path, source: str, *, now: float | None = None) -> float | None:
    """How long since a source was observed, or None if it never has been."""
    seen = read_ledger(vault_root).get(source)
    if seen is None:
        return None
    return (time.time() if now is None else now) - seen


def is_fresh(config: Config, vault_root: Path, source: str, *, now: float | None = None) -> bool:
    """Whether a source counts as freshly observed.

    An unknown source is not fresh: a caller asking about something the config
    does not describe should get the cautious answer, not a confident one.
    """
    declared = config.source(source)
    if declared is None:
        return False
    if not declared.decays:
        return True
    age = age_seconds(vault_root, source, now=now)
    if age is None:
        return False
    return age <= (declared.half_life_seconds or 0)


def missing_for(config: Config, vault_root: Path, artefact: str, *, now: float | None = None) -> tuple[str, ...]:
    """Sources this artefact requires fresh and does not have.

    An unknown artefact returns nothing rather than raising: not every output
    needs a contract, and inventing a requirement would be worse than having none.
    """
    required = config.artefacts.get(artefact)
    if not required:
        return ()
    return tuple(s for s in required if not is_fresh(config, vault_root, s, now=now))


def report(config: Config, vault_root: Path, artefact: str, *, now: float | None = None) -> dict[str, Any]:
    """Everything a Sources block needs, in one call."""
    required = config.artefacts.get(artefact, ())
    rows = []
    for name in required:
        age = age_seconds(vault_root, name, now=now)
        rows.append(
            {
                "source": name,
                "observed_seconds_ago": age,
                "fresh": is_fresh(config, vault_root, name, now=now),
                "state": "NOT OBSERVED" if age is None else "fresh" if is_fresh(config, vault_root, name, now=now) else "STALE",
            }
        )
    return {"artefact": artefact, "sources": rows, "missing": list(missing_for(config, vault_root, artefact, now=now))}
