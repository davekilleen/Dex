"""Room presence card: local photo/title/company, empty stays empty, share needs yes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.lifecycle import service
from core.room_presence import local_card, room_view
from core.transaction.engine import PlanRejected


def _vault(tmp_path: Path, *, name: str = "Maya") -> Path:
    vault = tmp_path / "vault"
    system = vault / "System"
    system.mkdir(parents=True)
    (system / "user-profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "role": "Should not become a title",
                "company": "Should not leak from onboarding",
                "capabilities": {"career": {"enabled": True}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (vault / "05-Areas" / "Career" / "Evidence").mkdir(parents=True)
    (vault / "05-Areas" / "Career" / "Evidence" / "README.md").write_text(
        "# Career\n",
        encoding="utf-8",
    )
    return vault


def _profile(vault: Path) -> dict:
    return yaml.safe_load((vault / "System" / "user-profile.yaml").read_text(encoding="utf-8"))


def test_profile_fields_save_locally(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    original = (vault / "System" / "user-profile.yaml").read_text(encoding="utf-8")

    previewed = service.build_and_preview_room_presence(
        vault,
        {
            "photo": "System/maya.png",
            "title": "Product designer",
            "company": "Northwind",
        },
    )

    assert (vault / "System" / "user-profile.yaml").read_text(encoding="utf-8") == original
    assert previewed["preview"]["shared"] is False
    assert previewed["preview"]["card"] == {
        "photo": "System/maya.png",
        "title": "Product designer",
        "company": "Northwind",
    }

    executed = service.execute_approved_room_presence(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    saved = _profile(vault)
    assert local_card(saved) == previewed["preview"]["card"]
    assert saved["name"] == "Maya"
    assert executed["receipt"]["purpose"] == "room-presence"
    assert [write["path"] for write in executed["receipt"]["files_written"]] == [
        "System/user-profile.yaml"
    ]
    assert room_view(saved, "design-sync") == {
        "room": "design-sync",
        "shared": False,
        "card": None,
    }


def test_empty_is_empty_not_a_placeholder_name(tmp_path: Path) -> None:
    vault = _vault(tmp_path, name="Maya")

    previewed = service.build_and_preview_room_presence(
        vault,
        {"photo": "", "title": "  ", "company": None},
    )
    service.execute_approved_room_presence(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    saved = _profile(vault)
    card = local_card(saved)
    assert card == {"photo": "", "title": "", "company": ""}
    assert "Maya" not in card.values()
    assert "Should not become a title" not in card.values()
    assert saved["name"] == "Maya"

    share = service.build_and_preview_room_presence_share(vault, "design-sync")
    service.execute_approved_room_presence_share(
        vault,
        share["preview"],
        share["approval_token"],
        "yes",
    )
    visible = room_view(_profile(vault), "design-sync")
    assert visible["shared"] is True
    assert visible["card"] == {"photo": "", "title": "", "company": ""}
    assert visible["card"]["title"] == ""
    assert "Maya" not in visible["card"].values()


def test_sharing_still_requires_a_yes(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    saved = service.build_and_preview_room_presence(
        vault,
        {"photo": "System/maya.png", "title": "Product designer", "company": ""},
    )
    service.execute_approved_room_presence(
        vault,
        saved["preview"],
        saved["approval_token"],
    )
    share = service.build_and_preview_room_presence_share(vault, "design-sync")
    original = (vault / "System" / "user-profile.yaml").read_bytes()

    for consent in ("", "ok", "true", "05-Areas/Career", True):
        with pytest.raises(PlanRejected, match="sharing still requires a yes"):
            service.execute_approved_room_presence_share(
                vault,
                share["preview"],
                share["approval_token"],
                consent,  # type: ignore[arg-type]
            )
        assert (vault / "System" / "user-profile.yaml").read_bytes() == original
        assert room_view(_profile(vault), "design-sync")["shared"] is False

    with pytest.raises(PlanRejected, match="approval does not match"):
        service.execute_approved_room_presence_share(
            vault,
            share["preview"],
            "0" * 64,
            "yes",
        )
    assert room_view(_profile(vault), "design-sync")["shared"] is False


def test_folders_never_grant_audience(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    saved = service.build_and_preview_room_presence(
        vault,
        {"photo": "System/maya.png", "title": "Product designer", "company": ""},
    )
    service.execute_approved_room_presence(
        vault,
        saved["preview"],
        saved["approval_token"],
    )

    profile = _profile(vault)
    assert profile["capabilities"]["career"]["enabled"] is True
    assert (vault / "05-Areas" / "Career" / "Evidence" / "README.md").is_file()
    visible = room_view(profile, "career")
    assert visible == {"room": "career", "shared": False, "card": None}
    with pytest.raises(PlanRejected, match="not a folder path"):
        service.build_and_preview_room_presence_share(vault, "05-Areas/Career")


def test_maya_adds_a_photo_and_title_and_a_room_sees_the_card_not_a_folder_tree(
    tmp_path: Path,
) -> None:
    maya = _vault(tmp_path, name="Maya")
    previewed = service.build_and_preview_room_presence(
        maya,
        {
            "photo": "System/maya.png",
            "title": "Product designer",
            "company": "",
        },
    )
    service.execute_approved_room_presence(
        maya,
        previewed["preview"],
        previewed["approval_token"],
    )

    before_yes = room_view(_profile(maya), "design-sync")
    assert before_yes["shared"] is False
    assert before_yes["card"] is None

    share = service.build_and_preview_room_presence_share(maya, "design-sync")
    assert share["preview"]["consent_required"] == "yes"
    assert "folders" not in share["preview"]
    assert "05-Areas" not in str(share["preview"]["visible_after_yes"])
    service.execute_approved_room_presence_share(
        maya,
        share["preview"],
        share["approval_token"],
        "yes",
    )

    other_person_sees = room_view(_profile(maya), "design-sync")
    assert other_person_sees == {
        "room": "design-sync",
        "shared": True,
        "card": {
            "photo": "System/maya.png",
            "title": "Product designer",
            "company": "",
        },
    }
    assert set(other_person_sees["card"]) == {"photo", "title", "company"}
    assert "folders" not in other_person_sees
    assert "Career" not in other_person_sees
    assert other_person_sees["card"]["company"] == ""
