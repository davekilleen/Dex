"""
Tests for Commitment Detection MCP Server

Run with: pytest core/mcp/tests/test_commitment_server.py -v
"""

import pytest
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from commitment_server import (
    detect_commitment_type,
    extract_deadline,
    extract_person_name,
    match_to_vault_context,
    generate_commitment_id,
    load_queue,
    save_queue,
    INBOUND_PATTERNS,
    OUTBOUND_PATTERNS,
    DEADLINE_PATTERNS,
)


class TestCommitmentDetection:
    """Test commitment pattern detection."""
    
    def test_detect_inbound_direct_request(self):
        """Test detecting direct requests."""
        examples = [
            "Can you review this PR?",
            "Could you please send me the report?",
            "Would you take a look at this?",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type == "inbound", f"Failed for: {text}"
            assert pattern == "direct_request", f"Wrong pattern for: {text}"
    
    def test_detect_inbound_need_input(self):
        """Test detecting input requests."""
        examples = [
            "Need your input on the design",
            "Needs your review before we ship",
            "Could use your feedback on this",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type == "inbound", f"Failed for: {text}"
            assert pattern == "need_input", f"Wrong pattern for: {text}"
    
    def test_detect_inbound_assignment(self):
        """Test detecting assignments."""
        examples = [
            "Assigned to you",
            "Assigning this to you",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type == "inbound", f"Failed for: {text}"
    
    def test_detect_outbound_promise(self):
        """Test detecting promises."""
        examples = [
            "I'll send that over tomorrow",
            "I will review it this afternoon",
            "I'm going to update the doc",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type == "outbound", f"Failed for: {text}"
            assert pattern == "promise", f"Wrong pattern for: {text}"
    
    def test_detect_outbound_followup(self):
        """Test detecting follow-up promises."""
        examples = [
            "I'll get back to you on that",
            "I'll follow up with the team",
            "I'll send the numbers later",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type == "outbound", f"Failed for: {text}"
    
    def test_detect_outbound_agreement(self):
        """Test detecting agreements."""
        examples = [
            "Sure, I'll handle it",
            "Yes, I can do that",
            "Sure I'll take care of it",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type == "outbound", f"Failed for: {text}"
    
    def test_no_commitment_detected(self):
        """Test that non-commitments return None."""
        examples = [
            "The weather is nice today",
            "Here's the report you requested",
            "Meeting notes from yesterday",
            "Thanks for the update!",
        ]
        for text in examples:
            comm_type, pattern = detect_commitment_type(text)
            assert comm_type is None, f"False positive for: {text}"


class TestDeadlineExtraction:
    """Test deadline extraction."""
    
    def test_extract_today(self):
        """Test extracting today deadline."""
        examples = ["by end of day", "by eod", "by EOD please"]
        for text in examples:
            deadline, dtype = extract_deadline(text)
            assert deadline == datetime.now().strftime("%Y-%m-%d"), f"Failed for: {text}"
            assert dtype == "today"
    
    def test_extract_tomorrow(self):
        """Test extracting tomorrow deadline."""
        examples = ["by tomorrow", "tomorrow morning"]
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        for text in examples:
            deadline, dtype = extract_deadline(text)
            assert deadline == tomorrow, f"Failed for: {text}"
            assert dtype == "tomorrow"
    
    def test_extract_this_week(self):
        """Test extracting this week deadline."""
        examples = ["by end of week", "by eow", "by EOW"]
        for text in examples:
            deadline, dtype = extract_deadline(text)
            assert deadline is not None, f"Failed for: {text}"
            assert dtype == "this_week"
    
    def test_extract_day_of_week(self):
        """Test extracting specific day deadline."""
        deadline, dtype = extract_deadline("by Friday")
        assert deadline is not None
        assert dtype == "day_of_week"
        # Verify it's actually a Friday
        parsed = datetime.strptime(deadline, "%Y-%m-%d")
        assert parsed.weekday() == 4  # Friday
    
    def test_extract_urgent(self):
        """Test extracting urgent deadline."""
        examples = ["ASAP", "urgent", "urgently needed"]
        today = datetime.now().strftime("%Y-%m-%d")
        for text in examples:
            deadline, dtype = extract_deadline(text)
            assert deadline == today, f"Failed for: {text}"
            assert dtype == "urgent"
    
    def test_no_deadline(self):
        """Test that non-deadline text returns None."""
        examples = [
            "Can you review this?",
            "The project is going well",
        ]
        for text in examples:
            deadline, dtype = extract_deadline(text)
            assert deadline is None, f"False positive for: {text}"


class TestPersonExtraction:
    """Test person name extraction."""
    
    def test_extract_at_mention(self):
        """Test extracting @mention."""
        assert extract_person_name("@dave can you review this?", "Slack") == "dave"
        assert extract_person_name("Hey @sarah_chen what do you think?", "Slack") == "sarah_chen"
    
    def test_extract_from_prefix(self):
        """Test extracting name from message prefix."""
        assert extract_person_name("John Smith: Here's the update", "Slack") == "John Smith"
    
    def test_extract_from_email_header(self):
        """Test extracting from email header."""
        assert extract_person_name("From: Sarah Chen\nSubject: Review needed", "Gmail") == "Sarah Chen"
    
    def test_no_person(self):
        """Test when no person is detectable."""
        assert extract_person_name("The project deadline is Friday", "Slack") is None


class TestContextMatching:
    """Test vault context matching."""
    
    @patch('commitment_server.list_people_pages')
    @patch('commitment_server.list_projects')
    def test_match_person(self, mock_projects, mock_people):
        """Test matching to person pages."""
        mock_people.return_value = [
            {"name": "Sarah Chen", "path": "05-Areas/People/Internal/Sarah_Chen.md", "type": "internal"},
            {"name": "John Smith", "path": "05-Areas/People/External/John_Smith.md", "type": "external"},
        ]
        mock_projects.return_value = []
        
        matches = match_to_vault_context("Can Sarah review this?")
        assert matches["person_page"] == "05-Areas/People/Internal/Sarah_Chen.md"
    
    @patch('commitment_server.list_people_pages')
    @patch('commitment_server.list_projects')
    def test_match_project(self, mock_projects, mock_people):
        """Test matching to projects."""
        mock_people.return_value = []
        mock_projects.return_value = [
            {"name": "Q1 Pricing Refresh", "path": "04-Projects/Q1_Pricing_Refresh.md", "keywords": ["pricing", "refresh"]},
            {"name": "Website Redesign", "path": "04-Projects/Website_Redesign.md", "keywords": ["website", "redesign"]},
        ]
        
        matches = match_to_vault_context("Can you review the pricing proposal?")
        assert matches["project"] == "04-Projects/Q1_Pricing_Refresh.md"
    
    @patch('commitment_server.list_people_pages')
    @patch('commitment_server.list_projects')
    def test_match_both(self, mock_projects, mock_people):
        """Test matching person and project."""
        mock_people.return_value = [
            {"name": "Sarah Chen", "path": "05-Areas/People/Internal/Sarah_Chen.md", "type": "internal"},
        ]
        mock_projects.return_value = [
            {"name": "Q1 Pricing", "path": "04-Projects/Q1_Pricing.md", "keywords": ["pricing"]},
        ]
        
        matches = match_to_vault_context("Sarah needs to review the pricing deck")
        assert matches["person_page"] is not None
        assert matches["project"] is not None


class TestQueueOperations:
    """Test queue file operations."""
    
    def test_generate_unique_ids(self, tmp_path, monkeypatch):
        """Test that commitment IDs are unique."""
        # Use temp queue file
        queue_file = tmp_path / "commitment_queue.json"
        monkeypatch.setattr('commitment_server.QUEUE_FILE', queue_file)
        
        id1 = generate_commitment_id()
        
        # Add to queue
        queue = load_queue()
        queue["commitments"].append({"id": id1})
        save_queue(queue)
        
        id2 = generate_commitment_id()
        
        assert id1 != id2
        assert id1.startswith("comm-")
        assert id2.startswith("comm-")
    
    def test_load_empty_queue(self, tmp_path, monkeypatch):
        """Test loading non-existent queue."""
        queue_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr('commitment_server.QUEUE_FILE', queue_file)
        
        queue = load_queue()
        assert queue["version"] == 1
        assert queue["commitments"] == []
    
    def test_save_and_load_queue(self, tmp_path, monkeypatch):
        """Test round-trip save/load."""
        queue_file = tmp_path / "test_queue.json"
        monkeypatch.setattr('commitment_server.QUEUE_FILE', queue_file)
        
        queue = {
            "version": 1,
            "last_scan": "2026-02-04T12:00:00",
            "commitments": [
                {"id": "comm-20260204-001", "type": "inbound", "raw_text": "Test"}
            ],
            "stats": {"total_detected": 1}
        }
        
        save_queue(queue)
        loaded = load_queue()
        
        assert loaded["version"] == 1
        assert len(loaded["commitments"]) == 1
        assert loaded["commitments"][0]["id"] == "comm-20260204-001"


class TestPatternCoverage:
    """Test pattern coverage for real-world examples."""
    
    def test_slack_messages(self):
        """Test patterns against real Slack-style messages."""
        slack_examples = [
            ("hey can you take a look at this PR when you get a chance?", "inbound"),
            ("@dave need your sign-off on the budget", "inbound"),
            ("I'll ping the eng team about this", "outbound"),
            ("sure, I'll get that to you by EOD", "outbound"),
            ("The standup is at 9am", None),  # Not a commitment
        ]
        
        for text, expected_type in slack_examples:
            comm_type, _ = detect_commitment_type(text)
            assert comm_type == expected_type, f"Failed for: {text}"
    
    def test_email_messages(self):
        """Test patterns against email-style messages."""
        email_examples = [
            ("Please review the attached proposal and let me know your thoughts", "inbound"),
            ("Could you forward this to the team?", "inbound"),
            ("I will send you the updated numbers tomorrow", "outbound"),
            ("Thank you for your email", None),  # Not a commitment
        ]
        
        for text, expected_type in email_examples:
            comm_type, _ = detect_commitment_type(text)
            assert comm_type == expected_type, f"Failed for: {text}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_text(self):
        """Test empty string handling."""
        assert detect_commitment_type("") == (None, None)
        assert extract_deadline("") == (None, None)
        assert extract_person_name("", "Slack") is None
    
    def test_case_insensitivity(self):
        """Test case-insensitive matching."""
        assert detect_commitment_type("CAN YOU REVIEW THIS?")[0] == "inbound"
        assert detect_commitment_type("I'LL SEND IT OVER")[0] == "outbound"
        assert extract_deadline("BY EOD")[1] == "today"
    
    def test_special_characters(self):
        """Test handling of special characters."""
        # Should still detect patterns with punctuation
        assert detect_commitment_type("Can you review this??? 🙏")[0] == "inbound"
        assert detect_commitment_type("I'll send it! Thanks!")[0] == "outbound"
    
    def test_multiline_text(self):
        """Test multiline text handling."""
        text = """Hey team,

Can you review this proposal?

Thanks,
Sarah"""
        assert detect_commitment_type(text)[0] == "inbound"


# Integration test (requires ScreenPipe running)
@pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="Integration tests disabled"
)
class TestIntegration:
    """Integration tests requiring ScreenPipe."""
    
    @pytest.mark.asyncio
    async def test_screenpipe_query(self):
        """Test querying ScreenPipe."""
        from commitment_server import query_screenpipe
        
        end_time = datetime.now().isoformat()
        start_time = (datetime.now() - timedelta(hours=1)).isoformat()
        
        results = await query_screenpipe(start_time, end_time)
        # Just verify we get a list back (may be empty)
        assert isinstance(results, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
