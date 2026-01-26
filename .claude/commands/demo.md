# /demo Command

Toggle demo mode on/off, reset demo content, or check status.

## Usage

- `/demo on` - Enable demo mode
- `/demo off` - Disable demo mode
- `/demo status` - Check current mode
- `/demo reset` - Restore demo content to original state

## What Demo Mode Does

When demo mode is ON:
- Commands read/write from `System/Demo/` instead of your real vault
- You see pre-populated content for a fictional PM named "Alex Chen"
- Your real data is untouched
- Changes you make are sandboxed to the demo folder

When demo mode is OFF:
- Normal operation - commands use your real vault data

## Process

### For `/demo on`

1. Read `System/user-profile.yaml`
2. Set `demo_mode: true`
3. Write back to file
4. Confirm with message showing available demo commands

### For `/demo off`

1. Read `System/user-profile.yaml`
2. Set `demo_mode: false`
3. Write back to file
4. Confirm: "Demo mode disabled. You're now using your real vault data."

### For `/demo status`

1. Read `System/user-profile.yaml`
2. Check `demo_mode` value
3. Report current status

### For `/demo reset`

1. Check if `System/Demo/_original/` exists
2. If not, error: "Demo backup not found. Cannot reset."
3. If exists, copy all from `_original/` to parent Demo folder
4. Confirm: "Demo content reset!"

## Demo Content Overview

The demo vault represents a week in the life of Alex Chen, PM at TechCorp:

**Projects:** Mobile App Launch, Customer Portal Redesign, API Partner Program

**People:** Jordan Lee, Maya Patel, Sarah Chen, Tom Wilson, Lisa Park

**Tasks:** Pre-populated across P0-P3 priorities

**Meetings:** A week of realistic meeting notes
