/**
 * Context Injection Module
 * Orchestrates all context injection for Dex
 * 
 * This module provides ENHANCED context injection for Pi users.
 * It supplements (not replaces) the Claude CLI hooks that work for
 * Cursor and Claude Desktop users.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import {
  lookupPerson,
  findPersonMentions,
  findPersonRefsInContent,
  formatPersonContext,
} from "./person.js";
import {
  lookupCompany,
  findCompanyMentions,
  findCompanyRefsInContent,
  formatCompanyContext,
} from "./company.js";
import {
  findTaskReferences,
  formatTaskContext,
} from "./task.js";
import type { PersonContext, CompanyContext, TaskContext } from "./types.js";

/**
 * Set up all context injection handlers
 */
export function setupContextInjection(pi: ExtensionAPI, vaultRoot: string): void {
  // ============================================================
  // PROACTIVE CONTEXT INJECTION (Pi-exclusive enhancement)
  // Fires BEFORE the LLM sees the user's message
  // ============================================================
  pi.on("before_agent_start", async (event, ctx) => {
    const prompt = event.prompt;
    const contexts: string[] = [];
    const sources: string[] = [];

    try {
      // 1. Find and inject person context
      const personMentions = await findPersonMentions(prompt, vaultRoot);
      if (personMentions.length > 0) {
        const personContexts = await Promise.all(
          personMentions.slice(0, 5).map((name) => lookupPerson(name, vaultRoot))
        );
        const validPersons = personContexts.filter((p): p is PersonContext => p !== null);
        if (validPersons.length > 0) {
          contexts.push(formatPersonContext(validPersons));
          sources.push(...validPersons.map((p) => `People: ${p.name}`));
        }
      }

      // 2. Find and inject company context
      const companyMentions = await findCompanyMentions(prompt, vaultRoot);
      if (companyMentions.length > 0) {
        const companyContexts = await Promise.all(
          companyMentions.slice(0, 3).map((name) => lookupCompany(name, vaultRoot))
        );
        const validCompanies = companyContexts.filter((c): c is CompanyContext => c !== null);
        if (validCompanies.length > 0) {
          contexts.push(formatCompanyContext(validCompanies));
          sources.push(...validCompanies.map((c) => `Companies: ${c.name}`));
        }
      }

      // 3. Find and inject task context
      const taskRefs = await findTaskReferences(prompt, vaultRoot);
      if (taskRefs.length > 0) {
        contexts.push(formatTaskContext(taskRefs));
        sources.push(`Tasks: ${taskRefs.length} referenced`);
      }

      // Return injected context if any found
      if (contexts.length > 0) {
        const fullContext = [
          "<dex_context>",
          "<!-- Automatically injected context from Dex vault -->",
          "",
          contexts.join("\n\n"),
          "",
          "</dex_context>",
        ].join("\n");

        // Log what we injected (visible in debug mode)
        if (sources.length > 0) {
          console.error(`[Dex] Injected context: ${sources.join(", ")}`);
        }

        return {
          message: {
            customType: "dex-context",
            content: fullContext,
            display: false, // Silent injection - don't show in chat
          },
        };
      }
    } catch (e) {
      // Don't fail the whole request if context injection fails
      console.error(`[Dex] Context injection error: ${e}`);
    }

    return undefined;
  });

  // ============================================================
  // REACTIVE CONTEXT INJECTION
  // Fires when reading files that reference people/companies
  // This supplements the Claude CLI hooks
  // ============================================================
  pi.on("tool_result", async (event, ctx) => {
    // Only handle successful read operations
    if (event.toolName !== "read" || event.isError) {
      return undefined;
    }

    const filePath = (event as any).input?.path || "";
    
    // Skip if reading a person/company page directly (avoid recursion)
    if (filePath.includes("/People/") || filePath.includes("/Companies/")) {
      return undefined;
    }

    // Extract text content from the result
    const textContent = event.content
      .filter((c): c is { type: "text"; text: string } => c.type === "text")
      .map((c) => c.text)
      .join("\n");

    if (!textContent) {
      return undefined;
    }

    try {
      const contexts: string[] = [];
      const sources: string[] = [];

      // Find person references in the file content
      const personRefs = findPersonRefsInContent(textContent, vaultRoot);
      if (personRefs.length > 0) {
        const personContexts = await Promise.all(
          personRefs.slice(0, 5).map((ref) => lookupPerson(ref, vaultRoot))
        );
        const validPersons = personContexts.filter((p): p is PersonContext => p !== null);
        if (validPersons.length > 0) {
          contexts.push(formatPersonContext(validPersons));
          sources.push(`People in file: ${validPersons.map((p) => p.name).join(", ")}`);
        }
      }

      // Find company references in the file content
      const companyRefs = findCompanyRefsInContent(textContent, vaultRoot);
      if (companyRefs.length > 0) {
        const companyContexts = await Promise.all(
          companyRefs.slice(0, 3).map((ref) => lookupCompany(ref, vaultRoot))
        );
        const validCompanies = companyContexts.filter((c): c is CompanyContext => c !== null);
        if (validCompanies.length > 0) {
          contexts.push(formatCompanyContext(validCompanies));
          sources.push(`Companies in file: ${validCompanies.map((c) => c.name).join(", ")}`);
        }
      }

      // Inject context for next turn if we found any
      if (contexts.length > 0) {
        const fullContext = [
          "<referenced_context>",
          `<!-- Context from entities referenced in ${filePath} -->`,
          "",
          contexts.join("\n\n"),
          "",
          "</referenced_context>",
        ].join("\n");

        pi.sendMessage(
          {
            customType: "dex-context-reactive",
            content: fullContext,
            display: false,
          },
          { deliverAs: "nextTurn" }
        );

        console.error(`[Dex] Reactive context: ${sources.join(", ")}`);
      }
    } catch (e) {
      console.error(`[Dex] Reactive context error: ${e}`);
    }

    return undefined;
  });
}

// Re-export types for convenience
export type { PersonContext, CompanyContext, TaskContext } from "./types.js";
