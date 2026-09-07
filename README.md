# Dex by Dave — Your AI Chief of Staff

[![Latest release](https://img.shields.io/github/v/release/davekilleen/dex?label=release&color=2ea44f)](https://github.com/davekilleen/dex/releases) [![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue)](LICENSE)

**One personal Dex, built around your work.** Keep your priorities, people, meeting notes and tasks in a folder you own. Work with Dex through your AI app to plan the day, prepare for a meeting or follow through on a promise. Your saved work stays with your vault when you change apps.

Start here or at [heydex.ai](https://heydex.ai/). The [Dex Guide](https://heydex.ai/help/) walks through setup and everyday use; the steps below keep the same starting point in GitHub.

<p align="center">
  <img src="docs/assets/dex-hero.gif" alt="Example Dex planning conversation with connected work sources; available sources depend on your setup." width="960">
</p>

## 1. Choose your AI app

| Your app | Route today |
| --- | --- |
| **Claude Code, terminal or Code tab in the desktop app** | Established full-vault route and reference for Dex's automatic session behavior. Use the install below, then open your Dex folder in Claude Code. [Claude Code primer](#claude-code-primer). |
| **Cursor** | Established full-vault setup for prompted skills and configured tools. Use the install below or the [manual steps](#manual-setup-for-cursor). Do not assume Claude Code's hooks run in Cursor. |
| **Codex CLI/desktop and other new app integrations** | Portable package files are distributed in **v1.97.13**. Complete supported install, workflow, update and removal journeys remain **unverified**. [Developer preview and exact limits](docs/HARNESS-PORTABILITY.md); no supported new-app install is promised here yet. |

The AI app and the model it uses are separate choices. App subscriptions, usage limits and optional connected services have their own costs; check your provider before signing up.

## 2. Choose your vault

A **vault** is the folder containing your personal Dex notes and configuration.

**Already use Dex?** Open your existing folder in the app you already use. Keep your notes, profile and custom skills; changing apps is not a reason to create another vault or repeat onboarding. A new app must be granted access to that same folder before it can use your work.

**Starting fresh?** The established installer checks prerequisites and prepares `Documents/Dex`. Review its prompts before approving changes.

### Quick install (Claude Code or Cursor)

**Mac — Terminal:**

```bash
curl -fsSL https://heydex.ai/install.sh | bash
```

**Windows — PowerShell:**

```powershell
irm https://heydex.ai/install.ps1 | iex
```

Then open the Dex folder in Claude Code or Cursor and say **"hi"**. Dex guides you through your role and priorities. [Installation help](https://heydex.ai/install/). If setup stops, keep the error message and use the help below; some prerequisites may already have been installed.

## 3. Get one useful result

Ask: **"Plan my day from my priorities and tasks. Tell me which sources you can read."**

In the established setup, `/daily-plan` guides that workflow. Start with the notes you have; calendar, email and meeting services are optional connections. Dex should name missing sources rather than imply it checked them. Review the proposed plan and ask where it was saved.

Next try **"Brief me on this person from my notes"** or **"Help me capture the follow-up from this meeting."** Available tools determine whether Dex can save the result. The released portable plugin alone provides read-only context, not the full task or meeting workflow.

## How your app connects to Dex

Dex's bridge connects an app to the selected vault, exposes the tools it can use, and translates supported app events. Installing a plugin does not create a vault, connect accounts, start background jobs or prove that every workflow works in that app.

- **Automatic:** a configured and trusted app event runs the behavior.
- **On demand:** you ask for a registered tool or skill.
- **Guided:** Dex explains the steps that still need your participation.
- **Unavailable:** the installed surface cannot deliver that behavior.

These modes describe individual features, not whole apps. A package manifest or saved app selection is not proof of a successful session. See the [surface and capability guide](docs/HARNESS-PORTABILITY.md#capability-truth).

## Privacy and control

Your notes live in your vault. That does not mean all processing stays on your computer: your AI app may send the context it reads to its model provider, and optional integrations contact their services. Grant access to the folder and services you intend to use; a local plugin does not grant a web app access to your files.

Dex's update service previews product changes and protects personal content through its ownership rules. Use [the update and recovery guide](docs/Dex_System/Updating_Dex.md). Review feedback before sending it under the configured consent policy; app permissions and diagnostic metadata do not establish who you are or authorize wider access.

## Help, updates and leaving an app

- Ask **"Check my Dex setup"** or run `/dex-doctor` in your established full-vault setup. The four-tool portable plugin does not include Doctor.
- Ask **"Show me the Dex update preview"** or use `/dex-update` where the lifecycle service is available. Installing a plugin update and updating your vault are separate operations.
- Use [the help guide](https://heydex.ai/help/) for setup, or [report a bug](https://github.com/davekilleen/dex/issues) without posting private vault contents. The [feedback guide](https://heydex.ai/help/feedback.html) explains reporting.
- To stop using an app, close its Dex session and revoke its folder access or disable its plugin in that app. Keep the vault if you want your notes. Removing an app or plugin does not stop independently installed background jobs. New-app removal instructions remain pending native verification.

## Guides

- [System guide](docs/Dex_System/Dex_System_Guide.md): planning, meetings, people, tasks and reviews.
- [Why the workflows exist](docs/Dex_System/Dex_Jobs_to_Be_Done.md).
- [Background work](docs/Dex_System/Background_Processing_Guide.md), [memory ownership](docs/Dex_System/Memory_Ownership.md) and [Obsidian](docs/Dex_System/Obsidian_Guide.md).
- [Technical guide](docs/Dex_System/Dex_Technical_Guide.md), [architecture map](docs/architecture/DEX-CORE-MAP.md) and [release history](CHANGELOG.md).

## Claude Code primer

This is the Claude Code route, including the desktop app's **Code** surface. Ordinary Claude Desktop chat has a separate read-only extension preview; it does not inherit Code hooks.

Install Claude Code using [its official setup instructions](https://code.claude.com/docs/en/setup), sign in through the app, and open your Dex folder. From a terminal already in that folder:

```bash
claude
```

Use `/setup` for a new vault, `/daily-plan` for planning, and `/daily-review` to close the day. Existing users should keep their configured vault. Trusted Claude Code hooks supply session context and tool checks; disabled hooks, missing runtimes or permissions can prevent those behaviors. [Named sessions](docs/Dex_System/Named_Sessions_Guide.md) covers Claude-specific resume commands.

<details>
<summary>Manual Cursor setup and troubleshooting</summary>

## Manual setup for Cursor

Prefer to see every step, or the quick install hit a snag? This section does the same thing by hand.

### What You'll Need to Install (One-Time)

1. **[Cursor](https://cursor.com/)** - Download and install; check current account and usage requirements
2. **[Git](https://git-scm.com)** - Required for this manual repository setup
   - **Mac:** Installs automatically when needed (you'll see a prompt)
   - **Windows:** Download from [git-scm.com/download/win](https://git-scm.com/download/win)
3. **[Node.js](https://nodejs.org/)** - Download the "LTS" version and install (this enables the system's automation features)
4. **[Python 3.10+](https://www.python.org/downloads/)** - Download and install (required for MCP servers and task sync)
   - **Minimum version:** Python 3.10 or newer
   - **Windows users:** ⚠️ During installation, check the box "Add Python to PATH" - this is critical
   - **Mac users with old Python:** If you have Python 3.9 or older, download fresh from python.org

All installers walk you through setup with default options.

**Why Python 3.10+?** The MCP SDK (Model Context Protocol) requires Python 3.10 or newer. This powers the Work MCP server that enables task sync - task updates through its tools can synchronize related pages. Manual checkbox edits need the separately configured sync service.

**Mac users:** If this is your first time using command-line tools, macOS will prompt you to install "Command Line Developer Tools" during setup. Click **Install** when prompted - it's safe and required. Takes 2-3 minutes.

### About the Command Line

You'll use something called a "command line" (or "Terminal" on Mac, "PowerShell" on Windows) during setup. This is a text-based way to give your computer instructions - think of it as typing commands instead of clicking buttons.

**Don't worry if this feels unfamiliar.** You'll copy and paste a few commands, press Enter, and you're done. Takes less than 2 minutes.

### Check Your Setup (Optional)

Want to verify everything's ready? Open your command line:
- **Mac:** Press `Cmd+Space`, type "Terminal", press Enter
- **Windows:** Press `Win+R`, type "powershell", press Enter

Copy and paste this line **exactly as you see it**, then press Enter:

```bash
git --version
```

**You should see a response like:** `git version 2.x.x` (any version number is fine)

**If you see "command not found":** Download Git from [git-scm.com](https://git-scm.com), install it, then close and reopen your command line and try again.

---

Now copy and paste this line, then press Enter:

```bash
node --version
```

**You should see a response like:** `v18.x.x` or `v20.x.x` (must be version 18 or higher)

**If you see "command not found":** Download Node.js from [nodejs.org](https://nodejs.org), install it, then close and reopen your command line and try again.

---

Finally, check Python:

```bash
python3 --version
```

**Windows users:** Try `python --version` if `python3` doesn't work.

**You should see a response like:** `Python 3.10.x` or higher (3.11, 3.12, etc.)

**If you see Python 3.9 or older:** The MCP SDK requires Python 3.10+. Download and install a newer version:
- **Mac/Windows:** Download from [python.org](https://www.python.org/downloads/) (get the latest stable version)
- After installing, restart your terminal and check the version again

**If you see "command not found":**
- **Windows:** Python likely isn't in your PATH. Reinstall from [python.org](https://www.python.org/downloads/) and check "Add Python to PATH" during installation. Restart your terminal after.
- **Mac:** Download Python from [python.org](https://www.python.org/downloads/), install it, then restart your terminal.

**Why Python 3.10+ matters:** It powers the MCP servers that sync tasks everywhere. Check off a task in a meeting note → it updates in your Tasks.md, person pages, and project files automatically. Python 3.9 and older won't work - you need 3.10 or newer.

---

**That's the technical heavy lifting done.** If you got through that, the rest is straightforward - just clicking buttons and answering questions.

### Step 1: Get the Code into Cursor

1. Open **Cursor**
2. Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows) - this opens a search bar at the top
3. Type **"Git: Clone"** and press Enter
4. Paste this URL and press Enter:
   ```
   https://github.com/davekilleen/dex.git
   ```
5. Choose where to save it (your Documents folder works great)
6. Click **Open** when Cursor asks if you want to open the folder

**Can't get this working?** No problem:
1. Go to [github.com/davekilleen/dex](https://github.com/davekilleen/dex)
2. Click the green **Code** button → **Download ZIP**
3. Unzip to your Documents folder (the folder will be named `dex-main`)
4. In Cursor: **File → Open Folder** → select that `dex-main` folder

### Step 2: Run the Installer

The repository installer is a **Bash script**. Run it from the Dex folder you opened in Step 1.

- **Mac:** Open Cursor's **View → Terminal** in that folder.
- **Windows:** Use **Git Bash**, supplied by Git for Windows, in that folder. Select the Git Bash terminal profile in Cursor, or open Git Bash separately and navigate to the folder. PowerShell can run the version checks above, but cannot directly run this Bash installer. For the PowerShell installation route, use [Quick install](#quick-install-claude-code-or-cursor).

In the terminal selected above, run:

```bash
bash ./install.sh
```

**What's happening:** This installs the automation that makes Dex work (task sync, career tracking, meeting intelligence). Takes 1-2 minutes. You'll see text scrolling - that's normal.

**When it's done:** You'll see your cursor blinking again, ready for the next command.

**Your system Python stays clean:** The installer creates a project-local virtual environment (`.venv`) inside your vault and installs all Python dependencies there — your system, Homebrew, or pyenv Python is never modified. No global installs, and no `pipx` needed.

⚠️ **IMPORTANT: You're not done yet. Complete Step 3 below to finish setup.**

**Verify MCP servers:** Cursor should automatically detect `.mcp.json` and enable the MCP servers. Look for the MCP icon in Cursor's bottom panel - you should see server names with green checkmarks.

**If you see errors:** The most common issue is Python dependencies not landing in Dex's virtual environment. Use the commands for your operating system under [Python dependency troubleshooting](#all-platforms-could-not-install-python-dependencies). On **Mac**, those commands are:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r core/mcp/requirements.txt
```

Then restart Cursor.

<details>
<summary><strong>Use Google Calendar? Connect it so Dex shows your meetings (Mac)</strong></summary>

If you use **Google Calendar**, you can have Dex show your real meetings when you run `/daily-plan` or ask "what's on my calendar today?" Two steps, one-time setup (Mac only):

**Step 1 — Add Google to your Mac's Calendar app**
Open the **Calendar** app (the one that came with your Mac). In the menu bar, click **Calendar** → **Add Account…** → choose **Google** → sign in with your Google account. Your Google events will sync into Calendar. Dex reads from this app, so once Google is here, Dex sees your meetings.

**Step 2 — Let Cursor use your calendar**
Open **System Settings** → **Privacy & Security** → **Calendars**. Turn **Cursor** on, then click **Cursor** and choose **Full** access (not "Add Only") so Dex can read your events. If macOS pops up asking "Cursor would like to access your calendars", click **Allow**.

That's it. The installer already set up the rest on Mac. Your meetings—including recurring ones like weekly 1:1s—will show on the correct days in Dex.

**More detail and troubleshooting:** [Calendar_Setup.md](docs/Dex_System/Calendar_Setup.md) (in your vault after setup).
**On Windows?** Calendar connection is supported on Mac via Apple Calendar. We don't have Windows instructions in this repo yet.

</details>

⚠️ **IMPORTANT: Complete Step 3 now to configure your role - this is what makes Dex work.**

<details>
<summary><strong>Troubleshooting: Common Setup Issues</strong></summary>

### Mac: "Command Line Developer Tools" prompt

If you see a popup asking to install "Command Line Developer Tools":

1. **Click Install** - This is safe and necessary for git to work
2. **Wait 2-3 minutes** - The installer downloads and installs automatically
3. **Setup continues automatically** - Once tools are installed, the script resumes

This only happens once. Future updates won't need this.

**What if I accidentally clicked "Cancel"?**

Run this command, then run `./install.sh` again:

```bash
xcode-select --install
```

---

### Windows: "python is not recognized" or "pip is not recognized"

This means Python wasn't added to your PATH during installation.

**Fix:**

1. Uninstall Python (Control Panel → Programs)
2. Download fresh installer from [python.org](https://www.python.org/downloads/)
3. Run installer
4. ⚠️ **CHECK THE BOX: "Add Python to PATH"** (on first screen)
5. Complete installation
6. **Restart your terminal completely** (close and reopen)
7. Return to **Git Bash** in your Dex folder and run `bash ./install.sh` again

---

### Windows: "git is not recognized"

Git for Windows isn't installed.

**Fix:**

1. Download from [git-scm.com/download/win](https://git-scm.com/download/win)
2. Run installer with default options
3. **Restart your terminal**
4. Open **Git Bash** in your Dex folder and run `bash ./install.sh` again

---

### All Platforms: "Could not install Python dependencies"

The installer tries two methods automatically. If both fail, your pip version might be too old.

**Mac — reinstall into Dex's virtual environment:**

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r core/mcp/requirements.txt
```

**Windows — PowerShell, in your Dex folder:**

```powershell
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r core/mcp/requirements.txt
```

---

### MCP Servers Show Errors in Cursor

If you see red error indicators next to MCP server names in Cursor:

**"No server info found" error:**

This means the Python MCP servers can't start. Reinstall dependencies using the [commands for your operating system](#all-platforms-could-not-install-python-dependencies). The **Mac** commands are:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r core/mcp/requirements.txt
```

Then **restart Cursor completely** (Cmd+Q and reopen, or File → Quit).

**If you get "ERROR: Could not find a version that satisfies the requirement mcp":**

Your pip is too old. Run the pip upgrade command above first, then try installing packages again.

**"Command 'python' not found" error:**

Your `.mcp.json` might have the wrong Python command. Open `.mcp.json` in your vault and change all instances of:

```json
"command": "python"
```

to:

```json
"command": "python3"
```

(Or vice versa on Windows - use whichever command works in your terminal)

Then restart Cursor.

**Still not working?**

Check the MCP server output:
1. Click the error indicator in Cursor's MCP panel
2. Click "Show Output"
3. Look for the specific error message
4. Common issues: missing Python packages, wrong file paths, Python version too old

---

### Mac: Calendar empty, wrong dates, or "Calendar access denied"

If `/daily-plan` doesn't show your meetings, or your recurring meetings (e.g. weekly 1:1s) show on the wrong day or are missing:

1. **Add Google to the Calendar app** — Open **Calendar** (Mac's built-in app) → **Calendar** → **Add Account…** → **Google** → sign in. Dex reads from this app.
2. **Let Cursor see your calendar** — **System Settings** → **Privacy & Security** → **Calendars** → turn **Cursor** on, then click **Cursor** and set access to **Full** (not "Add Only"). Restart Cursor after changing it.
3. **If you skipped the installer or fixed Python yourself** — The installer normally sets up calendar support on Mac. If you didn't run it or installed packages by hand, in Terminal run: `.venv/bin/pip install -r core/mcp/requirements.txt`, then restart Cursor.

See **[Calendar_Setup.md](docs/Dex_System/Calendar_Setup.md)** for the full guide.

---

### Something else seems broken after setup?

Once Dex is running, ask it to run `/dex-doctor` — a whole-system checkup that tells you honestly what's working, what's switched off and what's broken, repairs what it can on its own, and guides you through the rest.

And if the problem turns out to be a bug in Dex itself, you don't need a command or the right words: just describe what happened ("the meeting sync is doing something weird"). Dex investigates on your machine, writes the bug report for you, and by default waits for your yes before anything leaves — never anything from your notes, meetings or conversations. It tells you when the fix ships. Details: [what a report can contain](https://heydex.ai/help/feedback.html) · [the checkup](https://heydex.ai/help/updating-troubleshooting.html#health-dex-doctor)

</details>

### Step 3: Tell Dex About Your Role

In Cursor, look for a **chat panel** (usually on the right side of the screen). This is where you talk to your chosen AI assistant.

**Here's exactly what to do:**

1. **Click inside the chat panel** where it says "Message..." or similar
2. **Type exactly this:** `/setup`
3. **Press Enter** - This invokes the setup skill
4. **Wait ~30 seconds** - First time setup needs to load everything (you'll see "Thinking..." while it works)
5. **Press Enter again** - Dex will now start asking questions
6. **Answer each question naturally:**
   - What's your role? (e.g., "CFO", "VP Sales", "Product Manager")
   - Company size?
   - What are your main focus areas?

Just type your answers like you're texting a colleague. Takes about 2 minutes total.

**When it's done:** You'll see confirmation that your workspace is configured. Your selected folders and workflows are tailored to your role. Check optional connections and jobs separately.

---


</details>

## Contributing and credits

[Contributions are welcome](CONTRIBUTING.md). An AI assistant can help prepare a change; review it and keep personal information out of the public repository.

Created by [Dave Killeen](https://www.linkedin.com/in/davekilleen/). Built with Claude; inspired by [Claudesidian](https://github.com/heyitsnoah/claudesidian). [The story behind Dex](https://www.youtube.com/watch?v=QcqBsxw9hQM) · [Video walkthrough](https://youtu.be/WaqgSvL-V10).

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Commercial use requires a separate written license; see [commercial licensing](COMMERCIAL_LICENSE.md).
