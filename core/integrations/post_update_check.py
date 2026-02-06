#!/usr/bin/env python3
"""
Post-Update Integration Check

Runs after /dex-update to:
1. Detect new integration features
2. Check if user has existing MCP configs that could be upgraded
3. Offer setup for new integrations

Called by dex-update skill after successful update.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

from .detect import detect_all_integrations, RECOMMENDED, format_detection_report


def check_new_integrations_available() -> Tuple[bool, str]:
    """
    Check if the update includes new integration features.
    Returns (has_new_features, announcement_text).
    """
    # Get current detection status
    result = detect_all_integrations()
    
    # Build announcement
    lines = []
    new_features = []
    
    # Check which integrations are NOT yet configured
    if not result["notion"]["installed"]:
        new_features.append(("Notion", "Search your workspace, pull docs into meeting prep"))
    
    if not result["slack"]["installed"]:
        new_features.append(("Slack", "Search conversations, get context about people"))
    
    if not result["google"]["installed"]:
        new_features.append(("Google", "Gmail search, email context in person pages"))
    
    if not new_features:
        return False, ""
    
    lines.append("## 🔌 New: Productivity Integrations")
    lines.append("")
    lines.append("This update includes integrations for your favorite tools:")
    lines.append("")
    
    for name, desc in new_features:
        lines.append(f"- **{name}** — {desc}")
    
    lines.append("")
    lines.append("**Set up now?** These are optional but unlock powerful features like:")
    lines.append("- \"What did Sarah say about the Q1 budget?\" → Searches Slack")
    lines.append("- Meeting prep pulls relevant docs from Notion")
    lines.append("- Person pages show email/Slack history")
    lines.append("")
    lines.append("Run `/integrate-notion`, `/integrate-slack`, or `/integrate-google` to set up.")
    
    return True, "\n".join(lines)


def check_upgradeable_integrations() -> Tuple[bool, str]:
    """
    Check if user has integrations that could be upgraded to Dex recommended.
    Returns (has_upgrades, announcement_text).
    """
    result = detect_all_integrations()
    
    if not result["any_upgradeable"]:
        return False, ""
    
    lines = ["## 🔄 Integration Upgrade Available"]
    lines.append("")
    lines.append("You have some integrations that could be upgraded to Dex recommended packages:")
    lines.append("")
    
    for service, status in [("Notion", result["notion"]), 
                            ("Slack", result["slack"]), 
                            ("Google", result["google"])]:
        if status["installed"] and not status["is_dex_recommended"]:
            rec = RECOMMENDED.get(service.lower(), {})
            lines.append(f"### {service}")
            lines.append(f"- **Current:** {status['package']}")
            lines.append(f"- **Recommended:** {rec.get('package', 'N/A')}")
            lines.append(f"- **Benefits:** {', '.join(rec.get('benefits', []))}")
            lines.append("")
    
    lines.append("**Options:**")
    lines.append("1. **Keep existing** — Your current setup works fine")
    lines.append("2. **Upgrade** — Run `/integrate-{service}` to switch to recommended")
    lines.append("")
    
    return True, "\n".join(lines)


def get_post_update_integration_message() -> str:
    """
    Get the full post-update integration message.
    Called by /dex-update after successful update.
    """
    messages = []
    
    # Check for new integrations
    has_new, new_msg = check_new_integrations_available()
    if has_new:
        messages.append(new_msg)
    
    # Check for upgradeable integrations
    has_upgrades, upgrade_msg = check_upgradeable_integrations()
    if has_upgrades:
        messages.append(upgrade_msg)
    
    if not messages:
        return ""
    
    return "\n\n---\n\n".join(messages)


def should_show_integration_prompt() -> bool:
    """Check if we should prompt user about integrations."""
    result = detect_all_integrations()
    
    # Show prompt if:
    # 1. No integrations configured at all, OR
    # 2. Some integrations could be upgraded
    
    has_any = result["any_installed"]
    has_all = (result["notion"]["installed"] and 
               result["slack"]["installed"] and 
               result["google"]["installed"])
    has_upgradeable = result["any_upgradeable"]
    
    # Show if missing some OR has upgradeable
    return not has_all or has_upgradeable


if __name__ == "__main__":
    # Test the post-update check
    print("=== Post-Update Integration Check ===\n")
    
    msg = get_post_update_integration_message()
    if msg:
        print(msg)
    else:
        print("No integration messages to show.")
    
    print("\n=== Detection Report ===\n")
    result = detect_all_integrations()
    print(format_detection_report(result))
