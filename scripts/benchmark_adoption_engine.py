#!/usr/bin/env python3
"""E16 performance gate for adoption over a synthetic large vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("VAULT_PATH", str(REPO_ROOT))

from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity
from core.lifecycle.engine import (
    execute_adoption,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import ReleaseCatalog
from core.lifecycle.plan import build_adoption_plan
from core.lifecycle.preview import build_adoption_preview
from core.utils.doctor import ADOPTION_GROUP_IDS, DoctorContext, collect_adoption_report

DEFAULT_BUDGET = REPO_ROOT / "core/lifecycle/performance-budget-v1.json"
BENCHMARK_ITEM = "benchmark-adoption"
BENCHMARK_PATH = ".claude/skills/benchmark-adoption/SKILL.md"
BENCHMARK_PAYLOAD = b"# benchmark adoption payload\n"
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
T = TypeVar("T")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def create_synthetic_vault(root: Path, file_count: int) -> ReleaseCatalog:
    """Create exactly ``file_count`` ordinary user files plus release evidence."""
    benchmark_root = root / "04-Resources" / "adoption-benchmark"
    benchmark_root.mkdir(parents=True)
    shard_count = min(256, max(1, (file_count + 999) // 1000))
    shard_paths = [benchmark_root / f"shard-{index:03d}" for index in range(shard_count)]
    for shard in shard_paths:
        shard.mkdir()
    payload = b"synthetic vault entry\n"
    for index in range(file_count):
        target = shard_paths[index % shard_count] / f"file-{index:06d}.md"
        target.write_bytes(payload)

    manifest = f"{BENCHMARK_PATH}\n".encode()
    _write(root / "System/.installed-files.manifest", manifest)
    document = with_catalog_identity(
        {
            "catalog_version": 1,
            "release": {
                "version": "1.67.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.67.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": [
                {
                    "id": BENCHMARK_ITEM,
                    "kind": "skill",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": BENCHMARK_PATH,
                            "sha256": hashlib.sha256(BENCHMARK_PAYLOAD).hexdigest(),
                            "ownership_class": "brain",
                        }
                    ],
                    "dependencies": [],
                    "capabilities": [],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": f"rewind:{BENCHMARK_ITEM}@1.0.0",
                    },
                }
            ],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    _write(root / "System/.release-catalog.json", canonical_catalog_bytes(document))
    return ReleaseCatalog.from_dict(document)


def _timed(operation: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter()
    result = operation()
    return result, time.perf_counter() - started


def _peak_rss_bytes() -> int | None:
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (AttributeError, OSError, ValueError):
        return None
    return int(rss if sys.platform == "darwin" else rss * 1024)


def _load_budgets(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"could not load performance budget {path}: {error}") from error
    if not isinstance(raw, dict) or raw.get("budget_version") != 1:
        raise ValueError(f"performance budget {path} is not version 1")
    if type(raw.get("files")) is not int or raw["files"] <= 0:
        raise ValueError(f"performance budget {path} files must be a positive integer")
    seconds = raw.get("seconds")
    required = {
        "build_inventory",
        "build_adoption_plan",
        "collect_adoption_report",
        "adoption_and_rewind",
        "total_measured",
    }
    if not isinstance(seconds, dict) or set(seconds) != required:
        raise ValueError(f"performance budget {path} has the wrong seconds stages")
    if any(type(value) not in {int, float} or value <= 0 for value in seconds.values()):
        raise ValueError(f"performance budget {path} seconds must be positive numbers")
    return raw


def run_benchmark(file_count: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="dex-adoption-benchmark-") as temporary:
        vault = Path(temporary) / "vault"
        vault.mkdir()
        catalog = create_synthetic_vault(vault, file_count)

        inventory, inventory_seconds = _timed(
            lambda: build_inventory(vault, catalog=catalog)
        )
        plan, plan_seconds = _timed(lambda: build_adoption_plan(catalog, inventory))
        context = DoctorContext(
            vault,
            vault,
            Path(temporary) / "home",
            datetime(2026, 7, 21, tzinfo=timezone.utc),
        )
        adoption_report, doctor_seconds = _timed(
            lambda: collect_adoption_report(context)
        )

        def adopt_and_rewind():
            preview = build_adoption_preview(
                catalog,
                inventory,
                plan,
                (BENCHMARK_ITEM,),
                lambda _path: BENCHMARK_PAYLOAD,
            )
            receipt = execute_adoption(
                vault,
                preview,
                preview.sha256,
                lambda _path: BENCHMARK_PAYLOAD,
            )
            rewind = rewind_adoption(
                vault,
                receipt,
                rewind_acknowledgement_token(receipt),
            )
            return receipt, rewind

        (receipt, rewind), cycle_seconds = _timed(adopt_and_rewind)
        seconds = {
            "adoption_and_rewind": cycle_seconds,
            "build_adoption_plan": plan_seconds,
            "build_inventory": inventory_seconds,
            "collect_adoption_report": doctor_seconds,
        }
        seconds["total_measured"] = sum(seconds.values())
        return {
            "counts": {
                "adopted_files": len(receipt.files_written),
                "catalog_items": len(catalog.items),
                "doctor_groups": len(adoption_report.groups),
                "inventory_entries": len(inventory.entries),
                "rewound_files": len(rewind.files_restored),
                "synthetic_files": file_count,
            },
            "peak_rss_bytes": _peak_rss_bytes(),
            "seconds": {key: round(value, 6) for key, value in sorted(seconds.items())},
        }


def _budget_failures(result: dict[str, object], budgets: dict[str, object]) -> list[str]:
    measured = result["seconds"]
    allowed = budgets["seconds"]
    assert isinstance(measured, dict) and isinstance(allowed, dict)
    return [
        f"{stage} took {float(measured[stage]):.3f}s (budget {float(allowed[stage]):.3f}s)"
        for stage in sorted(allowed)
        if float(measured[stage]) > float(allowed[stage])
    ]


def _count_failures(result: dict[str, object], requested_files: int) -> list[str]:
    counts = result["counts"]
    assert isinstance(counts, dict)
    expected = {
        "adopted_files": 1,
        "catalog_items": 1,
        "doctor_groups": len(ADOPTION_GROUP_IDS),
        "rewound_files": 1,
        "synthetic_files": requested_files,
    }
    failures = [
        f"{name} was {counts.get(name)!r}, expected {value}"
        for name, value in expected.items()
        if counts.get(name) != value
    ]
    if not isinstance(counts.get("inventory_entries"), int) or counts["inventory_entries"] < requested_files:
        failures.append(
            f"inventory_entries was {counts.get('inventory_entries')!r}, expected at least {requested_files}"
        )
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark inventory, planning, Doctor, adoption, and rewind"
    )
    parser.add_argument(
        "--files",
        type=int,
        default=100_000,
        help="number of synthetic user files (default: 100000)",
    )
    parser.add_argument(
        "--budget-file",
        type=Path,
        default=DEFAULT_BUDGET,
        help="versioned JSON performance budget",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.files <= 0 or args.files > 190_000:
        print("--files must be between 1 and 190000", file=sys.stderr)
        return 2
    try:
        budgets = _load_budgets(args.budget_file)
        if args.files > int(budgets["files"]):
            raise ValueError(
                f"requested {args.files} files exceeds the calibrated {budgets['files']}-file budget"
            )
        result = run_benchmark(args.files)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Adoption benchmark could not run: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    count_failures = _count_failures(result, args.files)
    if count_failures:
        print(
            "Adoption benchmark produced unexpected counts: "
            + "; ".join(count_failures)
            + ".",
            file=sys.stderr,
        )
        return 1
    failures = _budget_failures(result, budgets)
    if failures:
        print(
            "Performance budget exceeded: " + "; ".join(failures) + ".",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
