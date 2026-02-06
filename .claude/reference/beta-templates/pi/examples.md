# Pi Examples - Copy and Try

Real prompts you can use right now. Copy any of these and run them.

---

## Deep Dive: Building a Commitment Extractor

This walkthrough shows Pi's real power - iterative development through conversation. We'll build a tool that finds commitments you've made across meetings, then enhance it step by step.

### The Conversation Flow

**Turn 1 - Initial Request:**

```
Build me a tool that scans my meeting notes and extracts commitments I've made -
things like "I'll send you", "I'll follow up", "Let me get back to you on"
```

**Pi's Response:**

Pi asks clarifying questions:
- "Should I look at all meetings or just recent ones?"
- "Do you want to track the status of these commitments?"
- "What format do you want the output in?"

You respond:
```
Just the last 14 days. Don't track status yet, just list them with the meeting
they came from. Simple markdown list is fine.
```

Pi generates the first version and you can immediately test it.

---

**Turn 2 - First Enhancement:**

```
Also track who the commitment was made to. Pull that from the meeting attendees
or from context like "I'll send Sarah the..."
```

Pi updates the tool. Now each commitment shows:
- The commitment text
- The meeting it came from
- Who you made it to

---

**Turn 3 - Add Urgency Flagging:**

```
Flag any commitments over 7 days old that might be overdue. Show them at the top
with a warning.
```

Pi adds age calculation and priority sorting.

---

**Turn 4 - Expand Sources:**

```
Also detect commitments in my Slack exports if I have any in 00-Inbox/Slack/
```

Pi extends the file scanning to include Slack exports with appropriate pattern matching for that format.

---

**Turn 5 - Add Summary:**

```
Add a summary at the top showing commitment count by person - who am I
over-committed to?
```

Pi adds aggregation logic and a summary section.

---

### What Pi Generated

After these iterations, here's the kind of extension Pi creates:

**Note:** This example shows the conceptual approach. Modern Pi extensions use native MCP tools instead of the bridge pattern shown here.

```typescript
// .pi/extensions/commitment-extractor.ts
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

interface Commitment {
  text: string;
  source: string;
  sourceType: 'meeting' | 'slack';
  date: Date;
  madeTo: string | null;
  ageInDays: number;
}

export async function extractCommitments(): Promise<void> {
  const dex = new DexBridge();
  const commitments: Commitment[] = [];

  // Pattern matching for commitment language
  const commitmentPatterns = [
    /I'll\s+(?:send|get|follow up|check|look into|schedule|set up|prepare|draft|review)\s+(.+?)(?:\.|$)/gi,
    /Let me\s+(?:get back to you|follow up|check|look into|send)\s+(.+?)(?:\.|$)/gi,
    /I can\s+(?:send|get|have|prepare)\s+(?:that|this|it)\s+(?:to you|over)\s+(.+?)(?:\.|$)/gi,
    /I'll\s+(?:have|get)\s+(?:that|this|it)\s+(?:to you|done|ready)\s+(.+?)(?:\.|$)/gi,
    /action item[:\s]+I\s+(.+?)(?:\.|$)/gi,
  ];

  // Scan meeting notes from last 14 days
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - 14);

  const meetingNotes = await dex.getMeetingNotes({ since: cutoffDate });

  for (const meeting of meetingNotes) {
    const content = await dex.readFile(meeting.path);
    const attendees = extractAttendees(content);

    for (const pattern of commitmentPatterns) {
      const matches = content.matchAll(pattern);
      for (const match of matches) {
        const commitmentText = match[0];
        const madeTo = inferRecipient(commitmentText, attendees);

        commitments.push({
          text: commitmentText.trim(),
          source: meeting.title,
          sourceType: 'meeting',
          date: meeting.date,
          madeTo,
          ageInDays: daysSince(meeting.date),
        });
      }
    }
  }

  // Also scan Slack exports if present
  const slackFiles = await dex.glob('00-Inbox/Slack/**/*.md');
  for (const slackFile of slackFiles) {
    const content = await dex.readFile(slackFile);
    const fileDate = extractDateFromPath(slackFile);

    if (fileDate >= cutoffDate) {
      for (const pattern of commitmentPatterns) {
        const matches = content.matchAll(pattern);
        for (const match of matches) {
          commitments.push({
            text: match[0].trim(),
            source: slackFile,
            sourceType: 'slack',
            date: fileDate,
            madeTo: inferRecipientFromSlack(content, match.index),
            ageInDays: daysSince(fileDate),
          });
        }
      }
    }
  }

  // Sort: overdue first, then by date
  commitments.sort((a, b) => {
    if (a.ageInDays > 7 && b.ageInDays <= 7) return -1;
    if (b.ageInDays > 7 && a.ageInDays <= 7) return 1;
    return b.date.getTime() - a.date.getTime();
  });

  // Generate output
  outputResults(commitments);
}

function outputResults(commitments: Commitment[]): void {
  // Summary by person
  const byPerson: Record<string, number> = {};
  for (const c of commitments) {
    const key = c.madeTo || 'Unknown';
    byPerson[key] = (byPerson[key] || 0) + 1;
  }

  console.log('## Commitment Summary\n');
  console.log('| Person | Count |');
  console.log('|--------|-------|');
  for (const [person, count] of Object.entries(byPerson).sort((a, b) => b[1] - a[1])) {
    console.log(`| ${person} | ${count} |`);
  }

  // Overdue section
  const overdue = commitments.filter(c => c.ageInDays > 7);
  if (overdue.length > 0) {
    console.log('\n## Potentially Overdue\n');
    for (const c of overdue) {
      console.log(`- **${c.ageInDays} days ago** - ${c.text}`);
      console.log(`  - Source: ${c.source} (${c.sourceType})`);
      if (c.madeTo) console.log(`  - Made to: ${c.madeTo}`);
    }
  }

  // Recent commitments
  const recent = commitments.filter(c => c.ageInDays <= 7);
  if (recent.length > 0) {
    console.log('\n## Recent Commitments\n');
    for (const c of recent) {
      console.log(`- ${c.text}`);
      console.log(`  - Source: ${c.source} | ${c.ageInDays} days ago`);
      if (c.madeTo) console.log(`  - Made to: ${c.madeTo}`);
    }
  }
}

// Helper functions
function extractAttendees(content: string): string[] {
  const attendeeMatch = content.match(/Attendees?:\s*(.+?)(?:\n|$)/i);
  if (attendeeMatch) {
    return attendeeMatch[1].split(/[,;]/).map(s => s.trim());
  }
  return [];
}

function inferRecipient(text: string, attendees: string[]): string | null {
  // Check for explicit names in the commitment
  for (const attendee of attendees) {
    const firstName = attendee.split(/\s/)[0];
    if (text.toLowerCase().includes(firstName.toLowerCase())) {
      return attendee;
    }
  }
  // Check for "you" when there's a single other attendee
  if (text.includes('you') && attendees.length === 1) {
    return attendees[0];
  }
  return null;
}

function inferRecipientFromSlack(content: string, matchIndex: number): string | null {
  // Look for @mentions near the commitment
  const context = content.slice(Math.max(0, matchIndex - 100), matchIndex + 200);
  const mentionMatch = context.match(/@(\w+)/);
  return mentionMatch ? mentionMatch[1] : null;
}

function daysSince(date: Date): number {
  const now = new Date();
  return Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
}

function extractDateFromPath(path: string): Date {
  const dateMatch = path.match(/(\d{4}-\d{2}-\d{2})/);
  return dateMatch ? new Date(dateMatch[1]) : new Date();
}
```

---

### The Iteration Advantage

Notice what just happened:

| Traditional Development | Pi Development |
|------------------------|----------------|
| 1. Write spec | 1. "Build me a thing" |
| 2. Set up project | 2. Test it |
| 3. Write code | 3. "Also add X" |
| 4. Debug | 4. Test it |
| 5. Add feature, repeat | 5. "Now do Y too" |

**Time to first working version:** ~2 minutes vs ~30+ minutes

**Adding features:** One sentence vs finding files, understanding code, editing, testing

**When this shines:**
- Personal tools you'll iterate on frequently
- Exploratory analysis where requirements emerge
- Cross-cutting queries across your vault
- Quick dashboards and reports

**When to use Claude Code instead:**
- Mission-critical workflows (task syncing, calendar writes)
- Complex multi-step operations that must be deterministic
- Anything that modifies lots of files atomically

---

### Comparison Notes

| Aspect | Pi Approach | Traditional Approach |
|--------|-------------|---------------------|
| **Initial build** | 2-5 minutes | 30-60 minutes |
| **Add a feature** | "Also do X" - 30 seconds | Find code, modify, test - 10+ minutes |
| **Debug issues** | "It's doing X, I want Y" | Read code, trace logic, fix |
| **Understand what it does** | Ask Pi to explain | Read the code yourself |
| **Reliability** | Good (may need guidance) | High (deterministic) |
| **Customization** | Unlimited, conversational | Limited by your coding time |

---

## Getting Started Examples

### Your First Skill

Start simple. Build something you'll use tomorrow:

```
/pi-build a skill that shows my meetings for today with attendee names
```

**What Pi creates:** A skill called `/my-meetings-today` that pulls calendar data and formats it nicely.

**Try it:** After Pi finishes, run `/my-meetings-today`

---

### Improve What You Built

Not quite right? Iterate:

```
/pi-improve my-meetings-today to also show the meeting description and highlight external attendees
```

---

## Productivity Examples

### Meeting Commitment Extractor

See the deep dive above for the full walkthrough. Quick version:

```
/pi-build a skill that scans my recent meeting notes and extracts any commitments I made - things like "I'll do X" or "Let me follow up on Y" - and lists them with the meeting they came from
```

**What you get:** A skill that reads through `00-Inbox/Meetings/` and pulls out action items you said you'd do.

---

### Stale Relationship Finder

Find people you haven't connected with:

```
/pi-build a skill that shows me everyone in my People folder that I haven't had a meeting with in the last 30 days, sorted by how long it's been
```

**What you get:** A relationship maintenance tool that checks meeting history against your people pages.

---

### Focus Time Calculator

Understand your meeting load:

```
/pi-build a skill that analyzes my calendar for this week and tells me: total meeting hours, longest focus block, and days with the most meetings
```

**What you get:** A quick way to understand if you have time for deep work.

---

## Sales & Account Management

### Deal Health Dashboard

Quick view of your pipeline:

```
/pi-build a skill that scans my Projects folder for anything tagged as a deal and shows me: last activity date, next scheduled meeting, and any overdue tasks - highlight deals with no activity in 14+ days
```

---

### Pre-Call Briefing Generator

Never walk into a call unprepared:

```
/pi-build a skill called call-prep that takes a company name, finds their page in my vault, pulls recent meeting notes, open tasks, and key contacts, and gives me a one-page briefing I can review in 2 minutes
```

**Usage:** `/call-prep Acme Corp`

---

### Competitor Mention Tracker

Know when competitors come up:

```
/pi-build a skill that searches my meeting notes for mentions of [Competitor1, Competitor2, Competitor3] and shows me which meetings mentioned them and in what context
```

---

### Follow-Up Generator

Turn meeting notes into action:

```
/pi-build a skill that reads the most recent meeting note, extracts action items, identifies who owns each item, and drafts a follow-up email I can send
```

---

## Product & Strategy

### Feature Request Aggregator

Collect asks from across conversations:

```
/pi-build a skill that searches my meeting notes for phrases like "it would be great if", "we need", "can you add", "feature request" and compiles them into a categorized list with source meetings
```

---

### Decision Log

Track what was decided and when:

```
/pi-build a skill that scans meeting notes for decisions - look for phrases like "we decided", "the decision is", "going with", "agreed to" - and creates a running log with dates and context
```

---

### Stakeholder Sentiment Tracker

Gauge how conversations are going:

```
/pi-build a skill that analyzes my meeting notes with a specific person or company and summarizes the general sentiment over time - are things trending positive, negative, or neutral?
```

---

## Personal Productivity

### Morning Briefing

Start your day informed:

```
/pi-build a skill called morning-brief that shows me: today's meetings with attendees, overdue tasks, tasks due today, and any meetings I have with people I haven't met before
```

---

### Weekly Review Prep

Make weekly reviews easier:

```
/pi-build a skill that prepares my weekly review by showing: meetings I had this week, tasks I completed, tasks I added, and people I met with for the first time
```

---

### Energy Management

Track what drains vs. energizes you:

```
/pi-build a skill that lets me tag meetings as "energizing" or "draining" after they happen, stores this in the meeting note, and shows me patterns over time
```

---

### Learning Capture

Don't lose insights:

```
/pi-build a skill called capture-learning that takes a short note about something I learned, tags it with the source (meeting, article, conversation), and saves it to a Learnings file organized by month
```

**Usage:** `/capture-learning The key to good demos is starting with the customer's problem, not the product`

---

## Team & Management

### 1:1 Prep

Never waste a 1:1:

```
/pi-build a skill that takes a person's name, finds their page, shows: last 1:1 notes, open action items for them, open action items from them, and suggests topics based on recent activity
```

---

### Team Meeting Tracker

Know who's meeting with whom:

```
/pi-build a skill that analyzes my calendar for the past month and shows me meeting frequency between team members - who meets a lot, who might be siloed
```

---

### Feedback Collector

Gather feedback for reviews:

```
/pi-build a skill that searches my meeting notes and messages for feedback I've given or received about a specific person, organized by date
```

---

## Custom Workflows

### End of Day Ritual

Automate your shutdown routine:

```
/pi-build a workflow called end-of-day that: moves incomplete daily tasks to tomorrow, captures any quick notes I want to add, shows my first meeting tomorrow, and asks what I'm grateful for today
```

---

### Project Kickoff Template

Start projects consistently:

```
/pi-build a skill that creates a new project page with: standard sections (Overview, Goals, Stakeholders, Timeline, Risks), prompts me to fill in key info, and creates placeholder person pages for stakeholders I mention
```

---

### Meeting to Tasks Pipeline

Never lose action items:

```
/pi-build a workflow that runs after I add a meeting note, extracts action items, creates tasks in Tasks.md, links them to relevant people pages, and updates the meeting note to show the tasks were captured
```

---

## Advanced Examples

### Custom Alert System

Get notified about important patterns:

```
/pi-build a skill that runs daily and alerts me if: any deal has no meeting scheduled in next 14 days, any person marked as "key contact" hasn't been met in 30 days, or any project has overdue tasks
```

---

### Insight Synthesizer

Find patterns across meetings:

```
/pi-build a skill that takes a topic, searches all my meeting notes for mentions of that topic, and synthesizes the key points and evolution of thinking about it over time
```

**Usage:** `/synthesize pricing strategy`

---

### Role-Based Views

See your world through different lenses:

```
/pi-build a skill that shows me my vault from the perspective of [specific role] - what would they care about? What meetings matter? What tasks are relevant?
```

---

## Tips for Better Results

### Be Specific

Instead of:
```
/pi-build a meeting tool
```

Try:
```
/pi-build a skill that summarizes my meeting notes into 3 bullet points with action items clearly marked
```

### Name Things

Give your skill a name:
```
/pi-build a skill called quick-prep that...
```

This makes it easier to use and improve later.

### Describe the Output

Tell Pi what you want to see:
```
/pi-build a skill that shows results as a markdown table with columns for Name, Last Meeting, and Days Since
```

### Start Small, Then Iterate

Build the simplest version first:
```
/pi-build a skill that lists my tasks
```

Then enhance:
```
/pi-improve my-tasks to group by project and highlight overdue items
```

### Use Follow-Up Turns

Pi remembers context. After building something:
```
Actually, also include the due date if there is one
```

No need to re-explain the whole thing.

---

## Share What You Build

Created something useful? Share it in the beta channel! Include:
1. The prompt you used
2. What it does
3. Any iterations you made

Your best ideas might become built-in Dex features.
