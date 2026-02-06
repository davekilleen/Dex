/**
 * Dex Commitment Detector
 * 
 * Detects promises and asks in conversations and suggests task creation.
 * Runs automatically after each agent turn.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// ============================================================================
// COMMITMENT PATTERNS
// ============================================================================

interface Commitment {
  type: "promise" | "ask" | "deadline";
  text: string;
  confidence: number;
  deadline?: string;
}

const PROMISE_PATTERNS = [
  /\b(i('ll|'ll| will))\s+(.{10,60})/gi,
  /\b(let me)\s+(.{10,60})/gi,
  /\b(i('m| am) going to)\s+(.{10,60})/gi,
  /\b(sure,?\s+i('ll|'ll| will))\s+(.{10,60})/gi,
  /\b(i can)\s+(.{10,60})/gi,
  /\b(i('ll|'ll| will) get that)\s+(.{10,40})/gi,
  /\b(i('ll|'ll| will) send)\s+(.{10,40})/gi,
  /\b(i('ll|'ll| will) follow up)\s+(.{10,40})/gi,
];

const ASK_PATTERNS = [
  /\b(can you)\s+(.{10,60})/gi,
  /\b(could you)\s+(.{10,60})/gi,
  /\b(would you mind)\s+(.{10,60})/gi,
  /\b(please)\s+(.{10,60})/gi,
  /\b(need you to)\s+(.{10,60})/gi,
  /\b(waiting on)\s+(.{10,60})/gi,
];

const DEADLINE_PATTERNS = [
  /\b(by|before)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)/gi,
  /\b(by|before)\s+(eod|end of day|cob|close of business)/gi,
  /\b(by|before)\s+(tomorrow|next week)/gi,
  /\b(asap|as soon as possible|urgent)/gi,
  /\b(by|before)\s+(\d{1,2}\/\d{1,2}|\d{4}-\d{2}-\d{2})/gi,
];

function detectCommitments(text: string): Commitment[] {
  const commitments: Commitment[] = [];
  
  // Detect promises (things the user committed to)
  for (const pattern of PROMISE_PATTERNS) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const fullMatch = match[0];
      commitments.push({
        type: "promise",
        text: fullMatch.trim(),
        confidence: 0.7
      });
    }
  }
  
  // Detect asks (things others asked of the user)
  for (const pattern of ASK_PATTERNS) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const fullMatch = match[0];
      commitments.push({
        type: "ask",
        text: fullMatch.trim(),
        confidence: 0.6
      });
    }
  }
  
  // Detect deadlines
  for (const pattern of DEADLINE_PATTERNS) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const fullMatch = match[0];
      commitments.push({
        type: "deadline",
        text: fullMatch.trim(),
        confidence: 0.8
      });
    }
  }
  
  // Deduplicate by text similarity
  const unique: Commitment[] = [];
  for (const c of commitments) {
    const isDupe = unique.some(u => 
      u.text.toLowerCase().includes(c.text.toLowerCase().slice(0, 20)) ||
      c.text.toLowerCase().includes(u.text.toLowerCase().slice(0, 20))
    );
    if (!isDupe) {
      unique.push(c);
    }
  }
  
  return unique;
}

function formatCommitmentSuggestions(commitments: Commitment[]): string {
  if (commitments.length === 0) return "";
  
  const promises = commitments.filter(c => c.type === "promise");
  const asks = commitments.filter(c => c.type === "ask");
  const deadlines = commitments.filter(c => c.type === "deadline");
  
  let output = "";
  
  if (promises.length > 0) {
    output += "💡 **Detected commitments you made:**\n";
    for (const p of promises.slice(0, 3)) {
      output += `  • "${p.text}"\n`;
    }
    output += "\n";
  }
  
  if (asks.length > 0) {
    output += "📋 **Things asked of you:**\n";
    for (const a of asks.slice(0, 3)) {
      output += `  • "${a.text}"\n`;
    }
    output += "\n";
  }
  
  if (deadlines.length > 0) {
    output += "⏰ **Deadlines mentioned:**\n";
    for (const d of deadlines.slice(0, 3)) {
      output += `  • ${d.text}\n`;
    }
    output += "\n";
  }
  
  output += "*Want me to create tasks for any of these?*";
  
  return output;
}

// ============================================================================
// EXTENSION REGISTRATION
// ============================================================================

export function registerCommitmentDetector(pi: ExtensionAPI) {
  let sessionCommitments: Commitment[] = [];
  
  // Detect commitments in user messages
  pi.on("input", async (event, ctx) => {
    const commitments = detectCommitments(event.text);
    
    if (commitments.length > 0) {
      sessionCommitments.push(...commitments);
    }
    
    return { action: "continue" };
  });
  
  // After agent completes, check if we should surface commitments
  pi.on("agent_end", async (event, ctx) => {
    // Only surface if we have significant commitments
    if (sessionCommitments.length >= 2) {
      const suggestions = formatCommitmentSuggestions(sessionCommitments);
      
      if (suggestions && ctx.hasUI) {
        ctx.ui.setWidget("dex-commitments", [
          "─── Dex Detected ───",
          suggestions
        ]);
      }
    }
  });
  
  // Clear on session switch
  pi.on("session_switch", async () => {
    sessionCommitments = [];
  });
  
  // Register a command to view detected commitments
  pi.registerCommand("commitments", {
    description: "Show commitments detected in this session",
    handler: async (args, ctx) => {
      if (sessionCommitments.length === 0) {
        ctx.ui.notify("No commitments detected yet", "info");
        return;
      }
      
      const suggestions = formatCommitmentSuggestions(sessionCommitments);
      ctx.ui.notify(suggestions, "info");
    }
  });
}
