#!/bin/bash
# Retired (DEX-249): AppleScript "every event of" loaded the whole calendar
# and timed out. Deletion goes through calendar_eventkit.py (one-day query).
# This helper stays so an old dispatch still fails fast instead of hanging.
echo "calendar_delete_event.sh is retired; use calendar_eventkit.py delete" >&2
exit 2
