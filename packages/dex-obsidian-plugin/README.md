# Dex panel for Obsidian (read-only, local)

Open your Dex folder in Obsidian and see today's brief. Under that brief,
Decided lately shows recorded decision words from your own files, each naming
the note and the date, without typing. Type a topic to look for a specific
decision. Type a person's name to see who they are from your own files. When
nothing is there, or nothing matches, one honest sentence says so. This panel
does not edit notes, run Dex commands, or use the internet.

This is an unreleased local install. It has not been submitted to the Obsidian
community store.

## What I need from you

1. Open Obsidian.
2. Choose **File → Open folder as vault** and select your Dex folder.
3. Copy this folder into your Dex folder at `.obsidian/plugins/dex-readonly`.
4. Turn off **Restricted Mode**.
5. Enable **Dex** under community plugins.
6. Look at the Dex panel on the right. Today's brief should be there. Under
   it, Decided lately shows recorded decisions without typing. Type a topic
   if you want a specific match. Type a person's name to see who they are.
   If nothing is there, or nothing matches, one honest sentence says so.

You can copy the folder by hand, or from the Dex checkout run:

```sh
python3 -m core.obsidian_panel install --vault /path/to/your/Dex
```

That copy only places the panel files. It does not change your notes.

## What this does not do

- It does not edit, create, or delete notes.
- It does not add Dex commands.
- It does not call the internet.
- It does not go to the Obsidian community store.
- It does not add VS Code or Kiro files. That piece is later.
- It does not grant a ChatGPT Work folder. That leftover stays on the desktop journey.
