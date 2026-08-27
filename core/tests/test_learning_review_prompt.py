"""Pending-learnings nudge counts the real open backlog, not only last week's pending.

The daily prompt must see captured / noted / partially fixed / in-progress
(and pending) in Session_Learnings files of any age. Closed statuses stay out.
The reminder file keeps the existing Count line and /dex-whats-new next step.
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SOURCE = REPO_ROOT / ".scripts" / "learning-review-prompt.sh"
SESSION_START = REPO_ROOT / ".claude" / "hooks" / "session-start.sh"

# Same extraction session-start.sh uses on learning-review-pending.md.
SESSION_START_COUNT = re.compile(r"^\*\*Count:\*\* ([0-9]*)", re.MULTILINE)


def _vault_with_script(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    scripts = vault / ".scripts"
    scripts.mkdir(parents=True)
    dest = scripts / "learning-review-prompt.sh"
    shutil.copyfile(SCRIPT_SOURCE, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR)
    return vault


def _write_learnings(vault: Path, filename: str, statuses: list[str]) -> None:
    learnings = vault / "System" / "Session_Learnings"
    learnings.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, status in enumerate(statuses, start=1):
        blocks.append(
            "\n".join(
                [
                    f"## [12:{index:02d}] - Fixture learning {index}",
                    "",
                    f"**What happened:** Fixture situation {index}",
                    f"**Why it matters:** Fixture impact {index}",
                    f"**Suggested fix:** Fixture fix {index}",
                    f"**Status:** {status}",
                    "",
                ]
            )
        )
    (learnings / filename).write_text("\n---\n".join(blocks), encoding="utf-8")


def _run_prompt(vault: Path) -> subprocess.CompletedProcess[str]:
    script = vault / ".scripts" / "learning-review-prompt.sh"
    return subprocess.run(
        ["bash", str(script)],
        cwd=vault,
        text=True,
        capture_output=True,
        check=True,
    )


def _prompt_path(vault: Path) -> Path:
    return vault / "System" / "learning-review-pending.md"


def _count_from_prompt(prompt: str) -> str:
    match = SESSION_START_COUNT.search(prompt)
    assert match is not None, prompt
    return match.group(1)


def test_shell_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT_SOURCE)], check=True)


def test_session_start_still_reads_count_from_the_existing_line() -> None:
    text = SESSION_START.read_text(encoding="utf-8")
    assert 'grep "^\\*\\*Count:\\*\\*" "$LEARNING_PENDING"' in text
    assert "Pending Learnings Review" in text
    assert "/dex-whats-new --learnings" in text


def test_named_backlog_statuses_and_older_files_meet_threshold(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    _write_learnings(vault, "2025-01-15.md", ["captured"])
    _write_learnings(vault, "2025-06-02.md", ["noted"])
    _write_learnings(vault, "2024-11-30.md", ["partially fixed"])
    _write_learnings(vault, "2025-12-01.md", ["in-progress"])
    _write_learnings(vault, "2026-08-20.md", ["pending"])

    _run_prompt(vault)

    prompt = _prompt_path(vault).read_text(encoding="utf-8")
    assert _count_from_prompt(prompt) == "5"
    assert "**Count:** 5 pending learnings" in prompt
    assert "/dex-whats-new --learnings" in prompt
    assert "from the past week" not in prompt


def test_old_captured_with_four_recent_pending_is_no_longer_invisible(
    tmp_path: Path,
) -> None:
    vault = _vault_with_script(tmp_path)
    _write_learnings(vault, "2026-08-21.md", ["pending", "pending"])
    _write_learnings(vault, "2026-08-22.md", ["pending", "pending"])
    _write_learnings(vault, "2025-03-01.md", ["captured"])

    _run_prompt(vault)

    prompt = _prompt_path(vault).read_text(encoding="utf-8")
    assert _count_from_prompt(prompt) == "5"


def test_closed_statuses_never_count_even_when_many_and_old(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    _write_learnings(
        vault,
        "2024-01-01.md",
        ["implemented", "won't-fix", "done", "resolved", "archived", "complete"],
    )
    _write_learnings(vault, "2026-08-26.md", ["pending"] * 4)

    _run_prompt(vault)

    assert not _prompt_path(vault).exists()


def test_four_open_stays_quiet(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    _write_learnings(vault, "2025-01-01.md", ["captured", "noted"])
    _write_learnings(vault, "2026-08-01.md", ["partially fixed", "in-progress"])

    _run_prompt(vault)

    assert not _prompt_path(vault).exists()


def test_readme_status_lines_are_skipped(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    _write_learnings(vault, "README.md", ["pending"] * 5)
    _write_learnings(vault, "2026-08-20.md", ["pending"] * 4)

    _run_prompt(vault)

    assert not _prompt_path(vault).exists()


def test_body_text_pending_without_status_line_does_not_count(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    learnings = vault / "System" / "Session_Learnings"
    learnings.mkdir(parents=True)
    (learnings / "2026-08-20.md").write_text(
        "\n".join(
            [
                "## [12:01] - Fixture learning",
                "",
                "**What happened:** The word pending appears in the body.",
                "**Why it matters:** False positives would inflate the nudge.",
                "**Suggested fix:** Keep counting Status lines only.",
                "**Status:** implemented",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write_learnings(vault, "2026-08-21.md", ["pending"] * 4)

    _run_prompt(vault)

    assert not _prompt_path(vault).exists()


def test_hyphen_and_space_variants_and_case_fold(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    _write_learnings(vault, "2025-02-01.md", ["Pending"])
    _write_learnings(vault, "2025-02-02.md", ["CAPTURED"])
    _write_learnings(vault, "2025-02-03.md", ["partially-fixed"])
    _write_learnings(vault, "2025-02-04.md", ["in progress"])
    _write_learnings(vault, "2025-02-05.md", ["  noted  "])

    _run_prompt(vault)

    prompt = _prompt_path(vault).read_text(encoding="utf-8")
    assert _count_from_prompt(prompt) == "5"


def test_missing_learnings_dir_exits_quietly(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    result = _run_prompt(vault)
    assert result.returncode == 0
    assert not _prompt_path(vault).exists()


def test_existing_prompt_is_removed_when_backlog_drops(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    prompt = _prompt_path(vault)
    prompt.parent.mkdir(parents=True)
    prompt.write_text("stale prompt\n", encoding="utf-8")
    _write_learnings(vault, "2026-08-20.md", ["pending"] * 2)

    _run_prompt(vault)

    assert not prompt.exists()


def test_crlf_and_eof_without_newline_still_count(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    learnings = vault / "System" / "Session_Learnings"
    learnings.mkdir(parents=True)
    crlf = "\r\n".join(
        [
            "## [12:01] - Fixture learning",
            "",
            "**Status:** captured",
            "",
            "## [12:02] - Fixture learning two",
            "",
            "**Status:** noted",
            "",
        ]
    )
    (learnings / "2025-04-01.md").write_bytes(crlf.encode("utf-8"))
    (learnings / "2025-04-02.md").write_text(
        "## [12:03] - Fixture learning three\n**Status:** pending",
        encoding="utf-8",
    )
    (learnings / "2025-04-03.md").write_text(
        "**Status:** in-progress\n**Status:** partially fixed\n",
        encoding="utf-8",
    )

    _run_prompt(vault)

    prompt = _prompt_path(vault).read_text(encoding="utf-8")
    assert _count_from_prompt(prompt) == "5"


def test_indented_status_line_is_not_a_learning(tmp_path: Path) -> None:
    vault = _vault_with_script(tmp_path)
    learnings = vault / "System" / "Session_Learnings"
    learnings.mkdir(parents=True)
    (learnings / "2026-08-20.md").write_text(
        "  **Status:** pending\n" * 5,
        encoding="utf-8",
    )

    _run_prompt(vault)

    assert not _prompt_path(vault).exists()
