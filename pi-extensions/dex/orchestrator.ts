/**
 * Dex Smart Orchestrator
 * 
 * The brain that decides when to spawn sub-agents and how to coordinate them.
 * Enables parallel processing for complex Dex operations.
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { StringEnum } from "@mariozechner/pi-ai";
import { Text, Container } from "@mariozechner/pi-tui";

const VAULT_PATH = process.env.VAULT_PATH || "/Users/dave/Claudesidian";

// ============================================================================
// TYPES
// ============================================================================

interface SubagentResult {
  agent: string;
  task: string;
  output: string;
  exitCode: number;
  durationMs: number;
}

interface OrchestratedResult {
  strategy: string;
  results: SubagentResult[];
  mergedOutput: string;
  totalDurationMs: number;
}

// ============================================================================
// TASK COMPLEXITY ANALYSIS
// ============================================================================

type TaskComplexity = "simple" | "medium" | "complex";
type TaskType = "lookup" | "task_op" | "planning" | "analysis" | "meeting_prep" | "review";

function analyzeTaskComplexity(prompt: string): { complexity: TaskComplexity; type: TaskType } {
  const promptLower = prompt.toLowerCase();
  
  // Simple lookups
  if (promptLower.match(/^(what|who|when|where|how many|list|show|get|find)\b/)) {
    if (promptLower.length < 50) {
      return { complexity: "simple", type: "lookup" };
    }
  }
  
  // Task operations
  if (promptLower.includes("create task") || promptLower.includes("mark") || promptLower.includes("complete")) {
    return { complexity: "simple", type: "task_op" };
  }
  
  // Meeting prep (medium - needs multiple sources)
  if (promptLower.includes("meeting") && (promptLower.includes("prep") || promptLower.includes("prepare"))) {
    return { complexity: "medium", type: "meeting_prep" };
  }
  
  // Daily/weekly planning (complex - needs parallelism)
  if (promptLower.includes("daily plan") || promptLower.includes("plan my day")) {
    return { complexity: "complex", type: "planning" };
  }
  
  if (promptLower.includes("week") && (promptLower.includes("review") || promptLower.includes("plan"))) {
    return { complexity: "complex", type: "planning" };
  }
  
  // Reviews (complex)
  if (promptLower.includes("review") || promptLower.includes("reflect")) {
    return { complexity: "complex", type: "review" };
  }
  
  // Analysis requests
  if (promptLower.includes("analyze") || promptLower.includes("assessment") || promptLower.includes("evaluate")) {
    return { complexity: "complex", type: "analysis" };
  }
  
  // Default: medium
  return { complexity: "medium", type: "lookup" };
}

// ============================================================================
// SUB-AGENT EXECUTION
// ============================================================================

async function runSubagent(
  agentName: string,
  task: string,
  signal?: AbortSignal
): Promise<SubagentResult> {
  const startTime = Date.now();
  
  return new Promise((resolve) => {
    const args = [
      "--mode", "json",
      "-p",
      "--no-session",
      `Task: ${task}`
    ];
    
    const proc = spawn("pi", args, {
      cwd: VAULT_PATH,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"]
    });
    
    let output = "";
    let stderr = "";
    
    proc.stdout.on("data", (data) => {
      const text = data.toString();
      // Parse JSON events, extract assistant messages
      try {
        const lines = text.split("\n").filter((l: string) => l.trim());
        for (const line of lines) {
          const event = JSON.parse(line);
          if (event.type === "message_end" && event.message?.role === "assistant") {
            for (const part of event.message.content || []) {
              if (part.type === "text") {
                output += part.text + "\n";
              }
            }
          }
        }
      } catch {
        // Not JSON, just accumulate
        output += text;
      }
    });
    
    proc.stderr.on("data", (data) => {
      stderr += data.toString();
    });
    
    proc.on("close", (code) => {
      resolve({
        agent: agentName,
        task,
        output: output.trim() || stderr.trim() || "(no output)",
        exitCode: code || 0,
        durationMs: Date.now() - startTime
      });
    });
    
    proc.on("error", () => {
      resolve({
        agent: agentName,
        task,
        output: stderr || "Process error",
        exitCode: 1,
        durationMs: Date.now() - startTime
      });
    });
    
    if (signal) {
      signal.addEventListener("abort", () => {
        proc.kill("SIGTERM");
      }, { once: true });
    }
  });
}

async function runParallelSubagents(
  tasks: Array<{ agent: string; task: string }>,
  signal?: AbortSignal
): Promise<SubagentResult[]> {
  const promises = tasks.map(t => runSubagent(t.agent, t.task, signal));
  return Promise.all(promises);
}

// ============================================================================
// ORCHESTRATION STRATEGIES
// ============================================================================

async function orchestrateDailyPlan(signal?: AbortSignal): Promise<OrchestratedResult> {
  const startTime = Date.now();
  
  // Parallel scouts
  const results = await runParallelSubagents([
    { agent: "dex-calendar-scout", task: "Analyze today's calendar - meetings, free blocks, prep needs" },
    { agent: "dex-task-scout", task: "Analyze task backlog - P0, P1, overdue, in-progress tasks" },
    { agent: "dex-week-scout", task: "Assess week progress - priority status, commitments, risks" },
  ], signal);
  
  // Merge results into comprehensive context
  let mergedOutput = "# Daily Planning Context (Gathered in Parallel)\n\n";
  
  for (const result of results) {
    mergedOutput += `## From ${result.agent}\n\n`;
    mergedOutput += result.output + "\n\n";
    mergedOutput += "---\n\n";
  }
  
  mergedOutput += "## Synthesis Needed\n\n";
  mergedOutput += "Based on the above context, generate a focused daily plan with:\n";
  mergedOutput += "1. Today's shape and recommended work types\n";
  mergedOutput += "2. Top 3 focus items aligned to week priorities\n";
  mergedOutput += "3. Meeting prep checklist\n";
  mergedOutput += "4. Heads-up for any risks\n";
  
  return {
    strategy: "parallel_daily_plan",
    results,
    mergedOutput,
    totalDurationMs: Date.now() - startTime
  };
}

async function orchestrateMeetingPrep(
  meetingName: string,
  attendees: string[],
  signal?: AbortSignal
): Promise<OrchestratedResult> {
  const startTime = Date.now();
  
  const tasks: Array<{ agent: string; task: string }> = [
    { agent: "dex-task-scout", task: `Find all tasks related to "${meetingName}" or involving: ${attendees.join(", ")}` }
  ];
  
  // Add people scout if we have attendees
  if (attendees.length > 0) {
    tasks.push({
      agent: "dex-people-scout",
      task: `Gather context for these people: ${attendees.join(", ")}`
    });
  }
  
  // Add general context scout
  tasks.push({
    agent: "dex-scout",
    task: `Find recent notes and context related to "${meetingName}"`
  });
  
  const results = await runParallelSubagents(tasks, signal);
  
  let mergedOutput = `# Meeting Prep: ${meetingName}\n\n`;
  mergedOutput += `**Attendees:** ${attendees.join(", ") || "Unknown"}\n\n`;
  
  for (const result of results) {
    mergedOutput += `## ${result.agent} Findings\n\n`;
    mergedOutput += result.output + "\n\n";
  }
  
  mergedOutput += "## Prep Checklist\n\n";
  mergedOutput += "Based on the above, here's what to prepare:\n";
  mergedOutput += "- [ ] Review key context\n";
  mergedOutput += "- [ ] Address open items with attendees\n";
  mergedOutput += "- [ ] Prepare discussion points\n";
  
  return {
    strategy: "parallel_meeting_prep",
    results,
    mergedOutput,
    totalDurationMs: Date.now() - startTime
  };
}

async function orchestrateWeekReview(signal?: AbortSignal): Promise<OrchestratedResult> {
  const startTime = Date.now();
  
  const results = await runParallelSubagents([
    { agent: "dex-task-scout", task: "Review all tasks completed this week and what's still open" },
    { agent: "dex-week-scout", task: "Full week progress report - all priorities, achievements, gaps" },
    { agent: "dex-scout", task: "Find this week's meeting notes and key discussions" },
  ], signal);
  
  let mergedOutput = "# Week Review Context\n\n";
  
  for (const result of results) {
    mergedOutput += `## From ${result.agent}\n\n`;
    mergedOutput += result.output + "\n\n";
  }
  
  mergedOutput += "## Synthesis Needed\n\n";
  mergedOutput += "Generate a week review with:\n";
  mergedOutput += "1. What was accomplished (celebrate wins)\n";
  mergedOutput += "2. What didn't get done (understand why)\n";
  mergedOutput += "3. Key learnings and patterns\n";
  mergedOutput += "4. Recommendations for next week\n";
  
  return {
    strategy: "parallel_week_review",
    results,
    mergedOutput,
    totalDurationMs: Date.now() - startTime
  };
}

// ============================================================================
// TOOL REGISTRATION
// ============================================================================

const SmartWorkParams = Type.Object({
  request: Type.String({ description: "What you want to accomplish" }),
  force_parallel: Type.Optional(Type.Boolean({ description: "Force parallel processing even for simple tasks" }))
});

export function registerOrchestratorTools(pi: ExtensionAPI) {
  
  pi.registerTool({
    name: "dex_smart_work",
    label: "Smart Work",
    description: "Intelligent task executor - automatically parallelizes complex operations using sub-agents. Use for daily planning, meeting prep, reviews, and complex analysis.",
    parameters: SmartWorkParams,
    
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const { complexity, type } = analyzeTaskComplexity(params.request);
      
      // For simple tasks, just return guidance
      if (complexity === "simple" && !params.force_parallel) {
        return {
          content: [{ type: "text", text: `This is a simple ${type} request. Handle directly without sub-agents.` }],
          details: { complexity, type, skipped: true }
        };
      }
      
      // Stream progress
      onUpdate?.({ 
        content: [{ type: "text", text: `Orchestrating ${complexity} ${type} request...` }],
        details: { stage: "starting" }
      });

      // Show progress indicator if UI available (Phase 5)
      let progressIndicator = null;
      if (ctx.hasUI) {
        try {
          const { ProgressIndicator } = await import("./ui/progress-indicator.js");
          const scouts = [
            { name: "calendar-scout", status: "pending" as const, progress: 0 },
            { name: "task-scout", status: "pending" as const, progress: 0 },
            { name: "week-scout", status: "pending" as const, progress: 0 },
          ];
          progressIndicator = new ProgressIndicator(scouts, ctx.ui.theme, {
            title: `Smart Work: ${type}`,
            showEstimate: true,
          });
          
          ctx.ui.setWidget("dex-progress", (tui, theme) => ({
            render: (w) => progressIndicator!.render(w),
            invalidate: () => progressIndicator!.invalidate(),
          }));
        } catch (error) {
          console.log("[Dex] Could not load progress indicator:", error);
        }
      }
      
      let result: OrchestratedResult;
      
      // Route to appropriate orchestration strategy
      if (type === "planning" && params.request.toLowerCase().includes("daily")) {
        onUpdate?.({ 
          content: [{ type: "text", text: "Spawning parallel scouts for daily planning..." }],
          details: { stage: "spawning" }
        });
        result = await orchestrateDailyPlan(signal);
        
      } else if (type === "meeting_prep") {
        // Extract meeting name and attendees from request
        const meetingMatch = params.request.match(/meeting\s+(?:with\s+)?([^,]+)/i);
        const meetingName = meetingMatch?.[1]?.trim() || "Meeting";
        const attendees = params.request.match(/with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:,?\s+(?:and\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)/gi);
        const attendeeList = attendees ? attendees[0].replace(/^with\s+/i, "").split(/,?\s+(?:and\s+)?/) : [];
        
        onUpdate?.({ 
          content: [{ type: "text", text: `Preparing for meeting: ${meetingName}...` }],
          details: { stage: "spawning", meeting: meetingName }
        });
        result = await orchestrateMeetingPrep(meetingName, attendeeList, signal);
        
      } else if (type === "review" || (type === "planning" && params.request.toLowerCase().includes("week"))) {
        onUpdate?.({ 
          content: [{ type: "text", text: "Spawning scouts for week review..." }],
          details: { stage: "spawning" }
        });
        result = await orchestrateWeekReview(signal);
        
      } else {
        // Generic parallel gathering
        onUpdate?.({ 
          content: [{ type: "text", text: "Gathering context in parallel..." }],
          details: { stage: "spawning" }
        });
        
        const results = await runParallelSubagents([
          { agent: "dex-scout", task: params.request },
          { agent: "dex-task-scout", task: `Find tasks related to: ${params.request}` }
        ], signal);
        
        let mergedOutput = "# Gathered Context\n\n";
        for (const r of results) {
          mergedOutput += `## From ${r.agent}\n\n${r.output}\n\n`;
        }
        
        result = {
          strategy: "parallel_generic",
          results,
          mergedOutput,
          totalDurationMs: results.reduce((sum, r) => sum + r.durationMs, 0)
        };
      }
      
      // Clear progress indicator (Phase 5)
      if (progressIndicator && ctx.hasUI) {
        ctx.ui.setWidget("dex-progress", undefined);
      }

      // Report timing
      const avgTime = result.results.length > 0 
        ? Math.round(result.results.reduce((sum, r) => sum + r.durationMs, 0) / result.results.length)
        : 0;
      
      const successCount = result.results.filter(r => r.exitCode === 0).length;
      
      return {
        content: [{ type: "text", text: result.mergedOutput }],
        details: {
          strategy: result.strategy,
          agentsUsed: result.results.map(r => r.agent),
          successCount,
          totalAgents: result.results.length,
          totalDurationMs: result.totalDurationMs,
          avgAgentDurationMs: avgTime
        }
      };
    },
    
    renderCall(args, theme) {
      const preview = args.request.length > 60 ? args.request.slice(0, 60) + "..." : args.request;
      return new Text(
        theme.fg("toolTitle", theme.bold("smart_work ")) +
        theme.fg("accent", `"${preview}"`),
        0, 0
      );
    },
    
    renderResult(result, { expanded }, theme) {
      const details = result.details as any;
      
      if (details?.skipped) {
        return new Text(theme.fg("dim", "Simple request - handled directly"), 0, 0);
      }
      
      let text = theme.fg("success", "✓ ") +
        theme.fg("toolTitle", details?.strategy || "orchestrated") +
        theme.fg("dim", ` (${details?.successCount}/${details?.totalAgents} agents, ${details?.totalDurationMs}ms)`);
      
      if (expanded && details?.agentsUsed) {
        for (const agent of details.agentsUsed) {
          text += `\n  ${theme.fg("accent", agent)}`;
        }
      }
      
      return new Text(text, 0, 0);
    }
  });
  
  // Convenience command for daily planning
  pi.registerCommand("plan", {
    description: "Generate smart daily plan with parallel scouts",
    handler: async (args, ctx) => {
      ctx.ui.notify("Spawning parallel scouts for daily planning...", "info");
      // Trigger the orchestrated planning via tool call
      // For now, just inform user to use the tool
      ctx.ui.notify("Run: dex_smart_work 'plan my day'", "info");
    }
  });
}
