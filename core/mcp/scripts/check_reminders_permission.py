#!/usr/bin/env python3
"""
Check and request Reminders permissions for Dex.

Mirrors check_calendar_permission.py but for EKEntityTypeReminder.
Reminders uses a separate TCC permission from Calendar even though
both use EventKit.
"""

import sys
import time
try:
    import EventKit
except ImportError:
    print("❌ EventKit not installed. Run: pip3 install pyobjc-framework-EventKit")
    sys.exit(1)


def main():
    store = EventKit.EKEventStore.alloc().init()
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeReminder)

    status_names = {
        0: "NotDetermined",
        1: "Restricted",
        2: "Denied",
        3: "Authorized",
        4: "FullAccess",      # macOS 14+
        5: "WriteOnly",       # macOS 14+ (not applicable for Reminders)
    }

    print(f"Current Reminders access: {status_names.get(status, f'Unknown ({status})')}")

    if status in (3, 4):  # Authorized or FullAccess
        print("✅ Reminders access already granted!")
        print("   EventKit can read and write Reminders.")
        return 0

    elif status == 2:  # Denied
        print()
        print("❌ Reminders access was previously denied.")
        print()
        print("To enable Reminders integration:")
        print("1. Open System Settings")
        print("2. Go to Privacy & Security > Reminders")
        print("3. Find 'Python' or 'python3' in the list")
        print("4. Enable the checkbox")
        print()
        print("Then run this script again to verify.")
        return 1

    elif status == 1:  # Restricted
        print()
        print("❌ Reminders access is restricted by system policies.")
        print("   This may be due to parental controls or enterprise MDM.")
        return 1

    else:  # NotDetermined (0)
        print()
        print("📋 Reminders access not yet requested.")
        print("   A permission dialog will appear...")
        print()

        access_granted = [None]

        def completion_handler(granted, error):
            access_granted[0] = granted

        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeReminder, completion_handler
        )

        # Wait for user response (max 30 seconds)
        for i in range(300):
            if access_granted[0] is not None:
                break
            time.sleep(0.1)
            if i % 10 == 0:
                print(".", end="", flush=True)

        print()

        if access_granted[0]:
            print("✅ Reminders access granted!")
            print("   EventKit can now read and write Reminders.")
            return 0
        else:
            print("❌ Reminders access was not granted.")
            print("   Run this script again to retry, or grant access in System Settings.")
            return 1


if __name__ == "__main__":
    sys.exit(main())
