#!/usr/bin/env python3
"""
Bridge between Node.js Slack bot and work_server.py functions.
Usage: python3 work-bridge.py <function_name> [json_args]
Returns: JSON to stdout
"""

import json
import os
import sys
from pathlib import Path

# Set up paths
VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).resolve().parent.parent.parent))
os.environ["VAULT_PATH"] = str(VAULT_PATH)

# Add core/mcp to Python path so we can import work_server
sys.path.insert(0, str(VAULT_PATH / "core" / "mcp"))

from work_server import (
    get_week_progress_data,
    get_commitments_due_data,
    get_meeting_context_data,
    get_calendar_capacity_data,
    lookup_person_data,
    get_all_tasks,
    query_meeting_cache_data,
)


FUNCTIONS = {
    "get_week_progress": get_week_progress_data,
    "get_commitments_due": get_commitments_due_data,
    "get_meeting_context": get_meeting_context_data,
    "get_calendar_capacity": get_calendar_capacity_data,
    "lookup_person": lookup_person_data,
    "get_all_tasks": get_all_tasks,
    "query_meetings": query_meeting_cache_data,
}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": f"Usage: work-bridge.py <{'|'.join(FUNCTIONS.keys())}> [json_args]"}))
        sys.exit(1)

    func_name = sys.argv[1]
    if func_name not in FUNCTIONS:
        print(json.dumps({"error": f"Unknown function: {func_name}. Available: {list(FUNCTIONS.keys())}"}))
        sys.exit(1)

    args = {}
    if len(sys.argv) > 2:
        try:
            args = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON args: {e}"}))
            sys.exit(1)

    try:
        result = FUNCTIONS[func_name](**args)
        print(json.dumps(result, default=str, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
