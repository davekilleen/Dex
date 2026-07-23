---
name: manage-capabilities
description: "Turn optional Dex rooms/features on or off without deleting any content. Use when the user says 'turn off X', 'enable the career room', 'hide a feature I don't use'. Not for diagnosing breakage; use `dex-doctor`. Not for a full role restructure; use `reset`."
disable-model-invocation: true
---

# Manage Dex rooms

Use this skill when the user wants to see, enable, or disable an optional room.

The available room ids and their folders, skills, MCPs, and features come from
the portable-vault capability registry. Do not invent another room or manually
copy a folder.

## Change a room

Read the available room ids from the registry:

```bash
"$VAULT_PATH/.venv/bin/python" "$VAULT_PATH/core/capabilities.py" --list
```

Confirm the requested registry room and state, then run:

```bash
"$VAULT_PATH/.venv/bin/python" "$VAULT_PATH/core/capabilities.py" <room-id> <on-or-off> --vault "$VAULT_PATH"
```

Report the command's JSON result in plain language.

Enabling provisions the room's declared folders and skills. Disabling removes
only release-owned active skill copies and stops room-specific write surfaces.
It never deletes or moves anything inside the user's Career, Companies, or
Quarter Goals folders. Existing room content stays exactly where it is and will
be available again if the room is re-enabled.
