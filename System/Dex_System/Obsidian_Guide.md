# Using Dex with Obsidian

Obsidian is a free markdown editor with powerful graph visualization. It's completely optional, but many users love seeing their knowledge as a connected graph.

**New to Obsidian?** Watch this [beginner's guide (5 min)](https://www.youtube.com/watch?v=gafuqdKwD_U) to see what it can do.

## What You Get with Obsidian

**Graph View:** See your entire knowledge system as connected nodes
- People you've met
- Projects you're working on  
- Companies you interact with
- Meetings and their connections

**Wiki Links:** Click any reference to jump instantly
- `[[John_Doe]]` → Opens John's person page
- `[[04-Projects/Mobile_App]]` → Opens project page
- `[[2026-01-28 - API Review]]` → Opens meeting note

**Search and Backlinks:** See everywhere a person/project is mentioned

## Installation

1. Download Obsidian (free): https://obsidian.md
2. Open your Dex vault: File → Open Folder → Select your Dex directory
3. Enable Obsidian mode: Run `/dex-obsidian-setup` in Cursor/Claude

## Obsidian vs Terminal/Cursor

Both are first-class experiences:

| Feature | Obsidian | Terminal/Cursor |
|---------|----------|----------------|
| Graph visualization | ✅ Yes | ❌ No |
| Clickable navigation | ✅ Wiki links | ⚡ File search |
| File editing | ✅ WYSIWYG | ✅ Plain text |
| AI integration | ❌ Limited | ✅ Native |
| Speed | ⚡ Fast | ⚡⚡ Faster |

**Recommendation:** Use both! Obsidian for visual navigation and reading, Cursor/Claude for AI-powered workflows.

## Setting Up Later

Already using Dex without Obsidian? No problem.

Run `/dex-obsidian-setup` and we'll:
1. Enable wiki link formatting
2. Convert your existing notes (1-2 min for most vaults)
3. Generate Obsidian config (optional)
4. Start the sync daemon (optional)

Migration is safe and reversible.

## Tips for Obsidian Users

### Graph View Filters

Focus on specific areas:
- Right-click nodes to filter by type
- Use search to highlight specific connections
- Adjust depth to see more or fewer connections

### Keyboard Shortcuts

- `Cmd/Ctrl + O` - Quick open (fuzzy file search)
- `Cmd/Ctrl + G` - Open graph view
- `Cmd/Ctrl + Shift + B` - Toggle backlinks pane
- `Cmd/Ctrl + E` - Toggle edit/preview mode

### Recommended Plugins

Consider these community plugins for enhanced Dex experience:
- **Dataview** - Create dynamic task lists and tables
- **Calendar** - Visual calendar view of daily notes
- **Recent Files** - Quick access to recent notes

## Task Syncing

If you enable the sync daemon (via `/dex-obsidian-setup`):
- Check a task box in Obsidian → syncs to Tasks.md, person pages, meeting notes
- Check a task in Cursor → syncs to Obsidian
- Works bidirectionally, zero maintenance

## Troubleshooting

**Wiki links not working?**
- Make sure `obsidian_mode: true` in `System/user-profile.yaml`
- Re-run `/dex-obsidian-setup` to convert existing files

**Graph view showing too many connections?**
- Use filters to focus on specific types (People, Projects)
- Adjust depth slider to reduce clutter

**Sync daemon not working?**
- Check `System/obsidian-sync.log` for errors
- Restart: `launchctl unload ~/Library/LaunchAgents/com.dex.obsidian-sync.plist && launchctl load ~/Library/LaunchAgents/com.dex.obsidian-sync.plist`

## Additional Resources

- [Obsidian Help](https://help.obsidian.md)
- [Obsidian Community Forums](https://forum.obsidian.md)
- [Graph View Guide](https://help.obsidian.md/Plugins/Graph+view)
