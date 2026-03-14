"""Persist raw transcript artifacts and derived summaries locally."""

from __future__ import annotations

from .meeting_intel_projection import ensure_meeting_intel_dirs


def summarize_transcript(raw_text: str) -> str:
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:240]
    return "Transcript captured."


def extract_action_items(raw_text: str) -> list[str]:
    items: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("action:") or stripped.startswith("- [ ]"):
            items.append(stripped.replace("- [ ]", "", 1).replace("Action:", "", 1).strip())
    return items


def extract_decisions(raw_text: str) -> list[str]:
    items: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("decision:"):
            items.append(stripped.replace("Decision:", "", 1).strip())
    return items


def write_transcript_artifact(source: str, transcript_id: str, title: str, raw_text: str) -> tuple[str, str, str]:
    raw_dir, summary_dir = ensure_meeting_intel_dirs()
    safe_title = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "" for ch in title).strip() or transcript_id
    raw_path = raw_dir / f"{transcript_id}-{safe_title}.md"
    summary_path = summary_dir / f"{transcript_id}-{safe_title}.md"
    summary_text = summarize_transcript(raw_text)

    raw_path.write_text(raw_text.strip() + "\n", encoding="utf-8")
    summary_path.write_text(f"# {title}\n\n{summary_text}\n", encoding="utf-8")
    return str(raw_path), str(summary_path), summary_text
