"""
Dex Productivity Integrations

Connect Notion, Slack, and Google Workspace to Dex for richer context.
"""

from .detect import KNOWN_PACKAGES, RECOMMENDED, detect_all_integrations, detect_integration, format_detection_report
from .post_update_check import (
    check_new_integrations_available,
    check_upgradeable_integrations,
    get_post_update_integration_message,
    should_show_integration_prompt,
)

__all__ = [
    # Detection
    'detect_all_integrations',
    'detect_integration', 
    'format_detection_report',
    'RECOMMENDED',
    'KNOWN_PACKAGES',
    # Post-update
    'get_post_update_integration_message',
    'should_show_integration_prompt',
    'check_new_integrations_available',
    'check_upgradeable_integrations',
]
