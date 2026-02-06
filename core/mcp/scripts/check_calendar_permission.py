#!/usr/bin/env python3
"""
Check and request calendar permissions for Dex.

This is a one-time setup step. Once granted, Python will have persistent
access to Calendar.app for fast EventKit queries.
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
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent)
    
    status_names = {
        0: "NotDetermined",
        1: "Restricted",
        2: "Denied",
        3: "Authorized"
    }
    
    print(f"Current calendar access: {status_names.get(status, 'Unknown')}")
    
    if status == 3:  # Authorized
        print("✅ Calendar access already granted!")
        print("   EventKit is ready for fast calendar queries (30x faster than AppleScript)")
        return 0
    
    elif status == 2:  # Denied
        print()
        print("❌ Calendar access was previously denied.")
        print()
        print("To enable fast calendar queries:")
        print("1. Open System Settings")
        print("2. Go to Privacy & Security > Calendars")
        print("3. Find 'Python' or 'python3' in the list")
        print("4. Enable the checkbox")
        print()
        print("Then run this script again to verify.")
        return 1
    
    elif status == 1:  # Restricted
        print()
        print("❌ Calendar access is restricted by system policies.")
        print("   This may be due to parental controls or enterprise MDM.")
        return 1
    
    else:  # NotDetermined (0)
        print()
        print("📋 Calendar access not yet requested.")
        print("   A permission dialog will appear...")
        print()
        
        access_granted = [None]
        
        def completion_handler(granted, error):
            access_granted[0] = granted
        
        store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, completion_handler)
        
        # Wait for user response (max 30 seconds)
        for i in range(300):
            if access_granted[0] is not None:
                break
            time.sleep(0.1)
            if i % 10 == 0:
                print(".", end="", flush=True)
        
        print()
        
        if access_granted[0]:
            print("✅ Calendar access granted!")
            print("   EventKit is ready for fast calendar queries.")
            return 0
        else:
            print("❌ Calendar access was not granted.")
            print("   Run this script again to retry, or grant access in System Settings.")
            return 1


if __name__ == "__main__":
    sys.exit(main())
