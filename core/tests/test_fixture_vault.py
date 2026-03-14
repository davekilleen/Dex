"""Verify the fixture vault has the expected PARA structure."""

from pathlib import Path

EXPECTED_DIRS = [
    "00-Inbox",
    "00-Inbox/Meetings",
    "00-Inbox/Ideas",
    "00-Inbox/Daily_Plans",
    "01-Quarter_Goals",
    "02-Week_Priorities",
    "03-Tasks",
    "04-Projects",
    "05-Areas",
    "05-Areas/People",
    "05-Areas/People/Internal",
    "05-Areas/People/External",
    "05-Areas/Companies",
    "05-Areas/Career",
    "05-Areas/Career/Evidence",
    "06-Resources",
    "07-Archives",
    "System",
]

EXPECTED_FILES = [
    "System/user-profile.yaml",
    "System/pillars.yaml",
    "03-Tasks/Tasks.md",
    "05-Areas/People/Internal/Alice_Smith.md",
    "05-Areas/People/External/Bob_Jones.md",
]


class TestFixtureVaultStructure:
    """The fixture vault must mirror a real Dex vault."""

    def test_para_directories_exist(self, fixture_vault: Path):
        for d in EXPECTED_DIRS:
            assert (fixture_vault / d).is_dir(), f"Missing directory: {d}"

    def test_seed_files_exist(self, fixture_vault: Path):
        for f in EXPECTED_FILES:
            assert (fixture_vault / f).is_file(), f"Missing file: {f}"

    def test_user_profile_is_valid_yaml(self, fixture_vault: Path):
        import yaml

        data = yaml.safe_load((fixture_vault / "System/user-profile.yaml").read_text())
        assert data["name"] == "Test User"
        assert "email_domain" in data

    def test_tasks_file_has_tasks(self, fixture_vault: Path):
        content = (fixture_vault / "03-Tasks/Tasks.md").read_text()
        assert "^task-" in content
