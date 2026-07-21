"""The release-catalog B1 contract, held at its public seams."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from core.lifecycle.catalog import (
    CatalogIdentityError,
    CatalogParseError,
    CatalogSchemaError,
    canonical_catalog_bytes,
    load_catalog,
    loads_catalog,
    validate_catalog_document,
    with_catalog_identity,
)
from core.lifecycle.handlers import (
    DEFAULT_REGISTRY,
    HandlerContext,
    HandlerPlanRejected,
    UnknownHandlerKind,
)
from core.lifecycle.model import AdoptionState, CatalogModelError, ReleaseCatalog

MANIFEST_BYTES = b".claude/skills/decision-log/SKILL.md\n"
MANIFEST_SHA256 = hashlib.sha256(MANIFEST_BYTES).hexdigest()
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def valid_document() -> dict[str, object]:
    document: dict[str, object] = {
        "catalog_version": 1,
        "release": {
            "version": "1.64.0",
            "channel": "release",
            "immutable_distribution_tag": "dist/release/v1.64.0-0123456",
            "source_commit": SOURCE_COMMIT,
            "manifest": {
                "path": "System/.installed-files.manifest",
                "sha256": MANIFEST_SHA256,
            },
        },
        "items": [
            {
                "id": "decision-log",
                "kind": "skill",
                "version": "1.0.0",
                "files": [
                    {
                        "path": ".claude/skills/decision-log/SKILL.md",
                        "sha256": "a" * 64,
                        "ownership_class": "brain",
                    }
                ],
                "dependencies": [],
                "capabilities": [],
                "rewind": {
                    "acknowledgement_required": True,
                    "token": "rewind:decision-log@1.0.0",
                },
            }
        ],
        "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
    }
    return with_catalog_identity(document)


def test_model_round_trip_is_byte_deterministic() -> None:
    document = valid_document()

    parsed = loads_catalog(json.dumps(document), manifest_bytes=MANIFEST_BYTES)
    encoded = canonical_catalog_bytes(parsed)
    reparsed = loads_catalog(encoded.decode("utf-8"), manifest_bytes=MANIFEST_BYTES)

    assert reparsed == parsed
    assert json.loads(encoded) == document
    assert encoded == canonical_catalog_bytes(reparsed)
    assert parsed.items[0].rewind.token == "rewind:decision-log@1.0.0"
    assert parsed.items[0].files[0].ownership_class == "brain"


def test_catalog_hash_binds_the_exact_canonical_payload() -> None:
    document = valid_document()

    assert document["integrity"]["catalog_sha256"] == (
        "b3f6f761c8df6e5c69ce19f3e3b2bdbafdf243c425e9f1d548dfbb3fb0b91213"
    )

    changed = copy.deepcopy(document)
    changed["items"][0]["files"][0]["sha256"] = "b" * 64
    with pytest.raises(CatalogIdentityError, match="UNKNOWN.*catalog_sha256"):
        loads_catalog(json.dumps(changed), manifest_bytes=MANIFEST_BYTES)


def test_release_identity_binds_tag_source_commit_and_manifest() -> None:
    document = valid_document()

    wrong_manifest = MANIFEST_BYTES + b"README.md\n"
    with pytest.raises(CatalogIdentityError, match="UNKNOWN.*manifest"):
        loads_catalog(json.dumps(document), manifest_bytes=wrong_manifest)

    wrong_tag = copy.deepcopy(document)
    wrong_tag["release"]["immutable_distribution_tag"] = "dist/release/v1.64.0-deadbee"
    wrong_tag = with_catalog_identity(wrong_tag)
    with pytest.raises(CatalogModelError, match="UNKNOWN.*source commit"):
        loads_catalog(json.dumps(wrong_tag), manifest_bytes=MANIFEST_BYTES)


def test_signature_envelopes_are_hash_bound_without_claiming_publisher_trust() -> None:
    document = valid_document()
    document["integrity"]["signatures"] = [
        {
            "algorithm": "ed25519",
            "key_id": "publisher-key-1",
            "signed_sha256": "0" * 64,
            "value": "opaque-signature-envelope",
        }
    ]
    document = with_catalog_identity(document)

    parsed = loads_catalog(json.dumps(document), manifest_bytes=MANIFEST_BYTES)
    assert parsed.integrity.signatures[0].signed_sha256 == parsed.integrity.catalog_sha256

    document["integrity"]["signatures"][0]["signed_sha256"] = "f" * 64
    with pytest.raises(CatalogModelError, match="UNKNOWN.*different catalog_sha256"):
        loads_catalog(json.dumps(document), manifest_bytes=MANIFEST_BYTES)


def test_load_catalog_checks_the_release_manifest_from_disk(tmp_path: Path) -> None:
    release_root = tmp_path / "release"
    manifest = release_root / "System/.installed-files.manifest"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(MANIFEST_BYTES)
    catalog_path = release_root / "core/lifecycle/catalog/release.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(valid_document()), encoding="utf-8")

    loaded = load_catalog(catalog_path, release_root=release_root)

    assert loaded.release.immutable_distribution_tag == "dist/release/v1.64.0-0123456"


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda d: d.update({"surprise": True}), CatalogSchemaError),
        (lambda d: d.update({"catalog_version": 2}), CatalogSchemaError),
        (lambda d: d["release"].update({"extra": "no"}), CatalogSchemaError),
        (lambda d: d["release"].update({"channel": "nightly"}), CatalogSchemaError),
        (lambda d: d["items"][0].update({"kind": 7}), CatalogSchemaError),
        (lambda d: d["items"][0]["files"][0].update({"sha256": "short"}), CatalogSchemaError),
        (lambda d: d["items"][0].update({"dependencies": ["decision-log"]}), CatalogSchemaError),
        (lambda d: d["items"][0]["rewind"].update({"acknowledgement_required": False}), CatalogSchemaError),
        (lambda d: d["integrity"].update({"signatures": [{"algorithm": "unknown"}]}), CatalogSchemaError),
    ],
)
def test_schema_fail_closed_matrix(mutation, error) -> None:
    document = valid_document()
    mutation(document)

    with pytest.raises(error, match="UNKNOWN"):
        validate_catalog_document(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["items"][0]["rewind"].update({"token": "yes"}),
        lambda d: d["items"].append(copy.deepcopy(d["items"][0])),
        lambda d: d["items"][0].update(
            {"dependencies": [{"item_id": "missing", "version": "1.0.0"}]}
        ),
        lambda d: d["items"][0].update({"capabilities": ["invented-room"]}),
        lambda d: d["items"][0].update({"version": "1.0.0-01"}),
        lambda d: d["items"][0]["files"][0].update({"path": ".."}),
    ],
)
def test_model_fail_closed_matrix(mutation) -> None:
    document = valid_document()
    mutation(document)
    document = with_catalog_identity(document)

    with pytest.raises(CatalogModelError, match="UNKNOWN"):
        ReleaseCatalog.from_dict(document)


def test_schema_required_rule_is_load_bearing() -> None:
    """E3 red-when-removed: deleting this schema rule makes the guard miss it."""
    document = valid_document()
    del document["items"][0]["kind"]

    with pytest.raises(CatalogSchemaError, match="required field.*kind"):
        validate_catalog_document(document)


@pytest.mark.parametrize(
    "text",
    [
        '{"catalog_version":1,"catalog_version":1}',
        '{"catalog_version":NaN}',
        "not-json",
    ],
)
def test_json_parser_refuses_ambiguous_or_non_standard_input(text: str) -> None:
    with pytest.raises(CatalogParseError, match="UNKNOWN"):
        loads_catalog(text, manifest_bytes=MANIFEST_BYTES)


def test_adoption_state_is_the_closed_receipt_vocabulary() -> None:
    assert {state.value for state in AdoptionState} == {
        "applied",
        "adopted",
        "rewound",
        "held-for-review",
        "customization-review-required",
        "external-reconciliation-pending",
        "needs-recheck",
        "skipped-by-user",
        "failed-rolled-back",
    }


def test_skill_handler_declares_contract_authorized_plans_without_writing(tmp_path: Path) -> None:
    item = ReleaseCatalog.from_dict(valid_document()).items[0]
    handler = DEFAULT_REGISTRY.resolve("skill")
    before = list(tmp_path.rglob("*"))

    preview = handler.preview(item, HandlerContext(existing_paths=frozenset()))
    apply = handler.apply(item, HandlerContext(existing_paths=frozenset()))
    verify = handler.verify(item, HandlerContext(existing_paths=frozenset()))
    rewind = handler.rewind(
        item,
        HandlerContext(acknowledgement_token="rewind:decision-log@1.0.0"),
    )

    assert [operation.target_path for operation in preview.operations] == [
        ".claude/skills/decision-log/SKILL.md"
    ]
    assert preview.operations[0].contract_action == "replace"
    assert apply.hook == "apply" and apply.operations[0].operation == "write"
    assert verify.hook == "verify" and verify.operations[0].operation == "verify"
    assert rewind.hook == "rewind" and rewind.operations[0].operation == "rewind"
    assert list(tmp_path.rglob("*")) == before == []


def test_registry_and_skill_handler_refuse_unknown_or_unsafe_work() -> None:
    with pytest.raises(UnknownHandlerKind, match="UNKNOWN.*mcp"):
        DEFAULT_REGISTRY.resolve("mcp")

    unknown_kind = valid_document()
    unknown_kind["items"][0]["kind"] = "mcp"
    unknown_kind = with_catalog_identity(unknown_kind)
    with pytest.raises(UnknownHandlerKind, match="UNKNOWN.*mcp"):
        loads_catalog(json.dumps(unknown_kind), manifest_bytes=MANIFEST_BYTES)

    item_document = valid_document()["items"][0]
    item_document["files"][0]["path"] = "core/not-a-skill.md"
    item = ReleaseCatalog.from_dict(with_catalog_identity({
        **valid_document(),
        "items": [item_document],
    })).items[0]
    handler = DEFAULT_REGISTRY.resolve("skill")
    with pytest.raises(HandlerPlanRejected, match="UNKNOWN.*skill directory"):
        handler.preview(item, HandlerContext())

    wrong_owner = valid_document()
    wrong_owner["items"][0]["files"][0]["ownership_class"] = "seed"
    wrong_owner_item = ReleaseCatalog.from_dict(with_catalog_identity(wrong_owner)).items[0]
    with pytest.raises(HandlerPlanRejected, match="UNKNOWN.*contract says brain"):
        handler.preview(wrong_owner_item, HandlerContext())

    valid_item = ReleaseCatalog.from_dict(valid_document()).items[0]
    with pytest.raises(HandlerPlanRejected, match="UNKNOWN.*acknowledgement"):
        handler.rewind(valid_item, HandlerContext(acknowledgement_token="wrong"))
