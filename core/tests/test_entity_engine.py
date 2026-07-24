from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import core.entity_engine as entity_engine
import core.entity_engine.write as entity_write
from core.entity_engine import (
    create_page_if_absent,
    ensure_region,
    fingerprint_page,
    mutate_page,
    render_update_log,
)


def _frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8-sig").split("---", 2)[1])


def test_composite_mutation_uses_one_atomic_replace(
    tmp_path: Path, monkeypatch
) -> None:
    page = tmp_path / "Jane.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Jane Doe\n"
        "company: Old Co\n"
        "dex_pinned: {}\n"
        "dex_last_written: {type: person, name: Jane Doe, company: Old Co}\n"
        "---\n"
        "# Jane Doe\n\n"
        "## Notes\n\n"
        "User-authored note.\n",
        encoding="utf-8",
    )
    base_fingerprint = fingerprint_page(page)
    real_atomic_replace = entity_write._atomic_replace
    replace_calls = []

    def counting_replace(path: Path, content: bytes) -> None:
        replace_calls.append((path, content))
        real_atomic_replace(path, content)

    monkeypatch.setattr(entity_write, "_atomic_replace", counting_replace)

    result = mutate_page(
        page,
        base_fingerprint,
        field_changes={"company": "New Co"},
        ensure_regions=("update-log", "relationships"),
        region_projections={"update-log": "- projected once"},
    )

    text = page.read_text(encoding="utf-8")
    assert result.status == "updated"
    assert result.changed is True
    assert len(replace_calls) == 1
    assert _frontmatter(page)["company"] == "New Co"
    assert text.index("## Relationships") < text.index("## Update Log")
    assert text.count("- projected once") == 1
    assert "User-authored note." in text


def test_composite_mutation_can_preserve_a_legacy_body_rewrite(
    tmp_path: Path,
) -> None:
    page = tmp_path / "Legacy.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Legacy Person\n"
        "last_interaction: 2026-01-01\n"
        "dex_pinned: {}\n"
        "dex_last_written: {last_interaction: 2026-01-01}\n"
        "---\n"
        "# Legacy Person\n\n"
        "## Meetings\n\n"
        "- Older meeting\n",
        encoding="utf-8",
    )
    replacement = page.read_text(encoding="utf-8").replace(
        "## Meetings\n",
        "## Meetings\n"
        "- [Roadmap](00-Inbox/Meetings/roadmap.md) — 2026-07-10\n",
    )

    result = mutate_page(
        page,
        fingerprint_page(page),
        replacement_content=replacement,
        field_changes={"last_interaction": "2026-07-10"},
    )

    assert result.status == "updated"
    text = page.read_text(encoding="utf-8")
    assert "last_interaction: '2026-07-10'" in text
    assert "- [Roadmap](00-Inbox/Meetings/roadmap.md) — 2026-07-10" in text
    assert "- Older meeting" in text


def test_fingerprint_mismatch_returns_conflict_without_clobber(
    tmp_path: Path, monkeypatch
) -> None:
    page = tmp_path / "Racing.md"
    page.write_text("# Original\n", encoding="utf-8")
    stale_fingerprint = fingerprint_page(page)
    page.write_text("# User edit wins\n", encoding="utf-8")

    def unexpected_replace(_path: Path, _content: bytes) -> None:
        raise AssertionError("conflicting mutation must not replace the page")

    monkeypatch.setattr(entity_write, "_atomic_replace", unexpected_replace)

    result = mutate_page(
        page,
        stale_fingerprint,
        field_changes={"type": "person", "name": "Racing"},
    )

    assert result.status == "conflict"
    assert result.changed is False
    assert page.read_text(encoding="utf-8") == "# User edit wins\n"


def test_guard_reread_detects_edit_after_transformation_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    page = tmp_path / "Racing.md"
    page.write_text("# Original\n", encoding="utf-8")
    base_fingerprint = fingerprint_page(page)
    real_build_mutation = entity_write._build_mutation

    def build_then_race(*args, **kwargs):
        transformed = real_build_mutation(*args, **kwargs)
        page.write_text("# Intervening user edit\n", encoding="utf-8")
        return transformed

    def unexpected_replace(_path: Path, _content: bytes) -> None:
        raise AssertionError("guard mismatch must not replace the page")

    monkeypatch.setattr(entity_write, "_build_mutation", build_then_race)
    monkeypatch.setattr(entity_write, "_atomic_replace", unexpected_replace)

    result = mutate_page(
        page,
        base_fingerprint,
        field_changes={"type": "person", "name": "Racing"},
    )

    assert result.status == "conflict"
    assert result.changed is False
    assert page.read_text(encoding="utf-8") == "# Intervening user edit\n"


def test_ensure_region_upgrades_legacy_page_in_order_and_is_idempotent() -> None:
    legacy = "\ufeff# Legacy Person\n\n## Notes\n\nUser text stays here.\n"

    with_update_log = ensure_region(legacy, "update-log")
    upgraded = ensure_region(with_update_log, "relationships")

    assert upgraded.startswith("\ufeff")
    assert upgraded.index("## Relationships") < upgraded.index("## Update Log")
    assert upgraded.count("<!-- dex:auto:relationships -->") == 1
    assert upgraded.count("<!-- dex:auto:update-log -->") == 1
    assert ensure_region(ensure_region(upgraded, "update-log"), "relationships") == upgraded
    assert "User text stays here." in upgraded


def test_composite_projection_preserves_unmanaged_text_under_existing_heading(
    tmp_path: Path,
) -> None:
    page = tmp_path / "Legacy.md"
    page.write_text(
        "# Legacy\n\n"
        "## Relationships\n\n"
        "User-authored relationship context.\n\n"
        "## Notes\n\n"
        "Keep me too.\n",
        encoding="utf-8",
    )

    result = mutate_page(
        page,
        fingerprint_page(page),
        ensure_regions=("relationships",),
        region_projections={"relationships": "- projected relationship"},
    )

    text = page.read_text(encoding="utf-8")
    assert result.status == "updated"
    assert "User-authored relationship context." in text
    assert "- projected relationship" in text
    assert text.index("- projected relationship") < text.index(
        "User-authored relationship context."
    )


def test_update_log_renderer_combines_every_reconstructible_fact_deterministically() -> None:
    touches = [
        {
            "ts": "2026-07-22T10:00:00Z",
            "type": "meeting",
            "direction": "none",
            "source": {"id": "meeting-2", "title": "Roadmap"},
        }
    ]
    relationship_provenance = [
        {
            "recorded_at": "2026-07-21T09:00:00Z",
            "type": "reports_to",
            "target": "05-Areas/People/Internal/Alex.md",
            "source": {"id": "meeting-1", "title": "Weekly 1:1"},
        }
    ]
    creation_metadata = {
        "created_at": "2026-07-20T08:00:00Z",
        "source": {"id": "ritual", "title": "Ritual Intelligence"},
    }

    expected = (
        "- 2026-07-20 — created — Ritual Intelligence [ritual]\n"
        "- 2026-07-21 — relationship · reports_to — "
        "05-Areas/People/Internal/Alex.md — Weekly 1:1 [meeting-1]\n"
        "- 2026-07-22 — meeting · two-way — Roadmap [meeting-2]"
    )
    assert (
        render_update_log(
            touches=touches,
            relationship_provenance=relationship_provenance,
            creation_metadata=creation_metadata,
        )
        == expected
    )
    assert (
        render_update_log(
            touches=list(reversed(touches)),
            relationship_provenance=list(reversed(relationship_provenance)),
            creation_metadata=dict(reversed(tuple(creation_metadata.items()))),
        )
        == expected
    )


def test_relationship_intent_uses_one_atomic_write_with_region_and_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    page = tmp_path / "Related.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Related Person\n"
        "dex_pinned: {}\n"
        "dex_last_written: {type: person, name: Related Person}\n"
        "---\n"
        "# Related Person\n",
        encoding="utf-8",
    )
    real_atomic_replace = entity_write._atomic_replace
    replace_calls = []

    def counting_replace(path: Path, content: bytes) -> None:
        replace_calls.append((path, content))
        real_atomic_replace(path, content)

    monkeypatch.setattr(entity_write, "_atomic_replace", counting_replace)

    result = entity_engine.mutate_relationships(
        page,
        fingerprint_page(page),
        {
            "kind": "relationship",
            "relationships": [
                {
                    "type": "works_at",
                    "target_id": "05-Areas/Companies/Acme.md",
                    "target_ref": "[[Acme]]",
                    "source": {
                        "kind": "domain-match",
                        "id": "acme.test",
                        "date": "2026-07-23",
                    },
                    "confidence": "suggested",
                }
            ],
        },
    )

    text = page.read_text(encoding="utf-8")
    frontmatter = _frontmatter(page)
    assert result.status == "updated"
    assert len(replace_calls) == 1
    assert frontmatter["relationships"] == [
        {
            "type": "works_at",
            "target": "[[Acme]]",
            "status": "suggested",
            "source": {"kind": "domain-match", "id": "acme.test"},
            "date": "2026-07-23",
        }
    ]
    assert frontmatter["dex_last_written"]["relationships"] == frontmatter[
        "relationships"
    ]
    assert (
        "<!-- dex:auto:relationships -->\n"
        "### works_at\n"
        "- [[Acme]] (suggested)\n"
        "<!-- /dex:auto -->"
    ) in text
    assert (
        "<!-- dex:auto:update-log -->\n"
        "- 2026-07-23 — relationship · works_at — [[Acme]]\n"
        "<!-- /dex:auto -->"
    ) in text


def test_relationship_intent_rejects_unknown_type_before_writing(
    tmp_path: Path,
) -> None:
    page = tmp_path / "Related.md"
    page.write_text("# Related\n", encoding="utf-8")
    original = page.read_bytes()

    with pytest.raises(ValueError, match="unknown relationship type"):
        entity_engine.mutate_relationships(
            page,
            fingerprint_page(page),
            {
                "kind": "relationship",
                "relationships": [
                    {
                        "type": "owns",
                        "target_id": None,
                        "target_ref": "[[Acme]]",
                        "source": {
                            "kind": "manual",
                            "id": "manual-1",
                            "date": "2026-07-23",
                        },
                        "confidence": "suggested",
                    }
                ],
            },
        )

    assert page.read_bytes() == original


def test_confirm_touch_render_and_resync_preserve_confirmed_edge_and_tombstones(
    tmp_path: Path,
) -> None:
    page = tmp_path / "Confirmed.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Confirmed Person\n"
        "relationships:\n"
        "- type: works_at\n"
        "  target: '[[Acme]]'\n"
        "  status: suggested\n"
        "  source: {kind: domain-match, id: acme.test}\n"
        "  date: '2026-07-23'\n"
        "dex_pinned: {relationships: user}\n"
        "dex_last_written:\n"
        "  relationships:\n"
        "  - type: works_at\n"
        "    target: '[[Acme]]'\n"
        "    status: suggested\n"
        "    source: {kind: domain-match, id: acme.test}\n"
        "    date: '2026-07-23'\n"
        "dex_dismissed_relationships:\n"
        "- {key: 'related_to::[[dismissed]]', date: '2026-07-24'}\n"
        "---\n"
        "# Confirmed Person\n",
        encoding="utf-8",
    )

    confirmed = entity_engine.mutate_relationships(
        page,
        fingerprint_page(page),
        {
            "kind": "confirm_relationship",
            "edge_key": "works_at::[[acme]]",
        },
    )
    assert confirmed.status == "updated"

    touched = mutate_page(
        page,
        fingerprint_page(page),
        field_changes={
            "last_touched": "2026-07-24",
            "touches": [{"ts": "2026-07-24", "type": "meeting"}],
        },
    )
    assert touched.status == "updated"

    resynced = entity_engine.mutate_relationships(
        page,
        fingerprint_page(page),
        {
            "kind": "relationship",
            "relationships": [
                {
                    "type": "works_at",
                    "target_ref": "[[Acme]]",
                    "source": {
                        "kind": "domain-match",
                        "id": "new-evidence",
                        "date": "2026-07-24",
                    },
                    "confidence": "suggested",
                },
                {
                    "type": "related_to",
                    "target_ref": "[[Beta]]",
                    "source": {
                        "kind": "co-attendance",
                        "id": "meeting-2",
                        "date": "2026-07-24",
                    },
                    "confidence": "suggested",
                },
            ],
        },
    )
    assert resynced.status == "updated"
    frontmatter = _frontmatter(page)
    assert [
        (edge["type"], edge["target"], edge["status"])
        for edge in frontmatter["relationships"]
    ] == [
        ("works_at", "[[Acme]]", "confirmed"),
        ("related_to", "[[Beta]]", "suggested"),
    ]
    assert frontmatter["dex_dismissed_relationships"] == [
        {"key": "related_to::[[dismissed]]", "date": "2026-07-24"}
    ]
    assert "relationships" not in frontmatter["dex_pinned"]
    assert "- [[Acme]]\n" in page.read_text(encoding="utf-8")


def test_dismiss_then_identical_evidence_resync_cannot_resurrect(
    tmp_path: Path,
) -> None:
    page = tmp_path / "Dismiss.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "relationships:\n"
        "- type: works_at\n"
        "  target: '[[Acme]]'\n"
        "  status: suggested\n"
        "  source: {kind: domain-match, id: acme.test}\n"
        "  date: '2026-07-23'\n"
        "dex_pinned: {}\n"
        "dex_last_written:\n"
        "  relationships:\n"
        "  - type: works_at\n"
        "    target: '[[Acme]]'\n"
        "    status: suggested\n"
        "    source: {kind: domain-match, id: acme.test}\n"
        "    date: '2026-07-23'\n"
        "---\n"
        "# Dismiss\n",
        encoding="utf-8",
    )

    dismissed = entity_engine.mutate_relationships(
        page,
        fingerprint_page(page),
        {
            "kind": "dismiss_relationship",
            "edge_key": "works_at::[[acme]]",
            "date": "2026-07-24",
        },
    )
    assert dismissed.status == "updated"

    resynced = entity_engine.mutate_relationships(
        page,
        fingerprint_page(page),
        {
            "kind": "relationship",
            "relationships": [
                {
                    "type": "works_at",
                    "target_ref": "[[Acme]]",
                    "source": {
                        "kind": "domain-match",
                        "id": "acme.test",
                        "date": "2026-07-24",
                    },
                    "confidence": "suggested",
                }
            ],
        },
    )
    assert resynced.status == "noop"
    frontmatter = _frontmatter(page)
    assert frontmatter["relationships"] == []
    assert frontmatter["dex_dismissed_relationships"] == [
        {"key": "works_at::[[acme]]", "date": "2026-07-24"}
    ]


@pytest.mark.parametrize(
    ("status", "expected_targets"),
    [
        ("suggested", ["[[Acme Holdings]]"]),
        ("confirmed", ["[[Acme]]", "[[Acme Holdings]]"]),
    ],
)
def test_engine_retarget_intent_respects_per_edge_ownership(
    tmp_path: Path,
    status: str,
    expected_targets: list[str],
) -> None:
    page = tmp_path / "Retarget.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "relationships:\n"
        "- type: works_at\n"
        "  target: '[[Acme]]'\n"
        f"  status: {status}\n"
        "  source: {kind: domain-match, id: acme.test}\n"
        "  date: '2026-07-23'\n"
        "dex_pinned: {}\n"
        "dex_last_written:\n"
        "  relationships:\n"
        "  - type: works_at\n"
        "    target: '[[Acme]]'\n"
        f"    status: {status}\n"
        "    source: {kind: domain-match, id: acme.test}\n"
        "    date: '2026-07-23'\n"
        "---\n"
        "# Retarget\n",
        encoding="utf-8",
    )

    result = entity_engine.mutate_relationships(
        page,
        fingerprint_page(page),
        {
            "kind": "relationship",
            "removed_edge_keys": ["works_at::[[acme]]"],
            "relationships": [
                {
                    "type": "works_at",
                    "target_ref": "[[Acme Holdings]]",
                    "source": {
                        "kind": "domain-match",
                        "id": "holdings.test",
                        "date": "2026-07-24",
                    },
                    "confidence": "suggested",
                }
            ],
        },
    )

    assert result.status == "updated"
    frontmatter = _frontmatter(page)
    assert [edge["target"] for edge in frontmatter["relationships"]] == (
        expected_targets
    )
    assert "dex_dismissed_relationships" not in frontmatter


def test_composite_mutation_never_overwrites_pinned_fields(tmp_path: Path) -> None:
    page = tmp_path / "Pinned.md"
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Pat\n"
        "role: Founder\n"
        "company: Old Co\n"
        "dex_pinned: {role: user}\n"
        "dex_last_written: {type: person, name: Pat, role: Lead, company: Old Co}\n"
        "---\n"
        "# Pat\n",
        encoding="utf-8",
    )

    result = mutate_page(
        page,
        fingerprint_page(page),
        field_changes={"role": "CEO", "company": "New Co"},
    )

    frontmatter = _frontmatter(page)
    assert result.status == "updated"
    assert frontmatter["role"] == "Founder"
    assert frontmatter["company"] == "New Co"
    assert frontmatter["dex_pinned"] == {"role": "user"}


def test_create_page_if_absent_never_clobbers_existing_page(tmp_path: Path) -> None:
    page = tmp_path / "External" / "New_Person.md"

    created = create_page_if_absent(
        page,
        "# New Person\n",
        allowed_root=tmp_path,
    )
    existing = create_page_if_absent(
        page,
        "# Replacement\n",
        allowed_root=tmp_path,
    )

    assert created.status == "created"
    assert created.changed is True
    assert existing.status == "exists"
    assert existing.changed is False
    assert page.read_text(encoding="utf-8") == "# New Person\n"


def test_create_page_if_absent_refuses_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "People").symlink_to(outside, target_is_directory=True)

    result = create_page_if_absent(
        root / "People" / "Escaped.md",
        "# Must not escape\n",
        allowed_root=root,
    )

    assert result.status == "unsafe_path"
    assert result.changed is False
    assert not (outside / "Escaped.md").exists()


def test_mutate_page_refuses_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "Person.md"
    target.write_text("# Outside\n", encoding="utf-8")
    linked_parent = tmp_path / "People"
    linked_parent.symlink_to(outside, target_is_directory=True)

    result = mutate_page(
        linked_parent / "Person.md",
        fingerprint_page(target),
        field_changes={"type": "person", "name": "Changed"},
    )

    assert result.status == "unsafe_path"
    assert result.changed is False
    assert target.read_text(encoding="utf-8") == "# Outside\n"
