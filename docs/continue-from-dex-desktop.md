# Continue from Dex Desktop

This page is for people who have been using the Dex desktop app and want to keep working with their notes in open-source Dex. Maybe your beta build is expiring, maybe you just want to run everything yourself. Either way, this is the door out, and it was built to be walked through.

## The promise

Your notes never move and are never converted. They are plain text files in folders you already own, and they stay exactly where they are, byte for byte. This process adds the open-source Dex machinery around your folders. It does not touch what is inside them.

## What you need

- Your vault folder (the desktop app created it; the app's "Your data" panel shows where it is)
- Claude Code, which is Anthropic's assistant app for your computer
- A Claude subscription of your own. If you already pay for Claude, Claude Code costs nothing extra. If not, it is roughly 20 dollars a month. Dex itself is free for your own use.

## The steps

1. Quit the Dex desktop app.
2. Install Claude Code from the Anthropic website and sign in with your own Claude account.
3. Open Terminal (press Cmd and Space, type Terminal, press Enter).
4. Paste the one-line command the desktop app shows you in the "Your data" panel, then press Enter. The command already contains your vault location, the exact release to fetch, and the seal to check it against. It looks like this shape:

   ```
   bash adopt-vault.sh --vault <your vault folder> --tag <release tag> --checksum <sha256>
   ```

5. When it finishes, open Claude Code in your vault folder and ask Dex something only your notes would know, like "what do my notes say about my current projects?" If it answers from your own notes, the handover worked.

The first time you talk to Dex it will confirm your name, role, and pillars from the profile your vault already has. It will not interview you again.

## What the command actually does

It fetches a sealed copy of open-source Dex pinned to one exact release, checks the seal (a SHA-256 checksum) before opening anything, and only then copies in the machinery: the engine code, the skills, and the configuration templates. It places these around your folders, never inside your content folders, and it never modifies or deletes a file that already exists. If a file would collide with one of yours, yours wins and the skip is recorded. Every action is written to a log that lives outside your vault, so there is always an exact record of what was added.

## If something goes wrong

Run the same command again. It is safe to repeat: it checks what is already in place, fetches a fresh verified copy only if something is missing, and completes only the missing pieces. It never duplicates and never overwrites your content. If the download fails or the seal does not match, nothing is copied at all and your vault is left exactly as it was.

If it still does not work after a second try, your notes are fine and untouched. Open an issue on the Dex GitHub repository and include the adoption log it printed at the end.
