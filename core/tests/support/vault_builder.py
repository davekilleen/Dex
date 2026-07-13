"""Build deliberately messy, disposable Dex vaults for parser tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MessyVault:
    root: Path
    tasks: Path
    profile: Path
    people_dir: Path
    people_index: Path
    meeting_intel_dir: Path
    half_written_transcript: Path
    ritual_title: str
    content_files: tuple[Path, ...]


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def build_messy_vault(tmp_root: Path, *, file_count: int = 25) -> MessyVault:
    """Create a parameterized vault beneath a caller-owned temporary directory."""
    if file_count < 0:
        raise ValueError("file_count must be non-negative")

    root = tmp_root / "messy vault – 東京"
    root.mkdir(parents=True, exist_ok=True)
    system = root / "System"
    system.mkdir()
    profile = _write(
        system / "user-profile.yaml",
        'name: ""\nrole: ""\ncompany: ""\nemail_domain: "example.com"\n',
    )

    content_files = []
    imports = root / "00-Inbox" / "Messy Imports"
    for index in range(file_count):
        suffix = "café notes" if index % 2 == 0 else "東京 follow up"
        target = imports / f"{index:04d} {suffix}.md"
        if index % 3 == 0:
            content = f"---\ntitle: Half written {index}\ntags: [import, unfinished\n# fragment {index}\n- ["
        else:
            content = f"# Imported note {index} — {suffix}\n\nText with emoji 🧭 and trailing field:\nowner:"
        content_files.append(_write(target, content))

    task_lines = ["# Tasks", "", "## P1 — Now"]
    task_count = max(250, file_count * 8)
    for index in range(1, task_count + 1):
        if index % 41 == 0:
            task_lines.extend(("", "## P1 — Now"))
        label = "café follow-up" if index % 2 else "東京 planning"
        checked = "x" if index % 7 == 0 else " "
        task_lines.append(f"- [{checked}] {label} {index} ^task-20260713-{index:03d}")
        if index % 11 == 0:
            task_lines.append("  - Due: not-a-date | Pillar: | Project:")
    task_lines.extend(("", "## P2 — Later", "- [ ]", "- [", "## P2 — Later"))
    tasks = _write(root / "03-Tasks" / "Tasks.md", "\n".join(task_lines) + "\n")

    people_dir = root / "05-Areas" / "People"
    _write(
        people_dir / "External" / "Zoë Example.md",
        "---\ntype: person\nname: Zoë Example\nemails: [zoe@example.com]\n---\n\n# Zoë Example\n\n## Notes\nUseful context.\n",
    )
    _write(
        people_dir / "External" / "Malformed YAML – 東京.md",
        "---\nname: [Malformed Person\nemails: [fixture@example.org\n---\n\n# Recovered Person\n\n**Email:** recovered@example.com\n## Notes\nRecovered from legacy fields.\n",
    )
    _write(
        people_dir / "Internal" / "Half Written.md",
        "# Half Written\n\n**Role:** Engineer\n**Email:** fixture@example.com\n## Notes\n- unfinished",
    )

    ritual_title = "Planning sync – 東京"
    meeting_intel_dir = root / "06-Resources" / "Intel" / "Meeting_Intel"
    (meeting_intel_dir / "raw").mkdir(parents=True)
    (meeting_intel_dir / "summaries").mkdir()
    half_written_transcript = _write(
        meeting_intel_dir / "incoming" / f"{ritual_title}.md",
        "Decision: keep the unicode filename\nAction: reconcile the rough note\nSpeaker: [unfinished",
    )

    return MessyVault(
        root=root,
        tasks=tasks,
        profile=profile,
        people_dir=people_dir,
        people_index=system / "People_Index.json",
        meeting_intel_dir=meeting_intel_dir,
        half_written_transcript=half_written_transcript,
        ritual_title=ritual_title,
        content_files=tuple(content_files),
    )
