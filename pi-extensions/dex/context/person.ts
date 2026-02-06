/**
 * Person Context Module
 * Looks up and formats person page context for injection
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { PersonContext } from "./types.js";

const PEOPLE_SUBDIRS = ["Internal", "External", "CPO_Network"];

// Cache for performance
let personIndexCache: Record<string, string> | null = null;
let cacheTime = 0;
const CACHE_TTL = 60000; // 1 minute

/**
 * Build an index of person names to file paths
 */
export async function buildPersonIndex(vaultRoot: string): Promise<Record<string, string>> {
  // Return cached if fresh
  if (personIndexCache && Date.now() - cacheTime < CACHE_TTL) {
    return personIndexCache;
  }

  const index: Record<string, string> = {};
  const peopleDir = path.join(vaultRoot, "05-Areas", "People");

  if (!fs.existsSync(peopleDir)) {
    return index;
  }

  for (const subdir of PEOPLE_SUBDIRS) {
    const dirPath = path.join(peopleDir, subdir);
    if (!fs.existsSync(dirPath)) continue;

    try {
      const files = fs.readdirSync(dirPath);
      for (const file of files) {
        if (!file.endsWith(".md")) continue;

        const fileName = file.replace(".md", "");
        const spacedName = fileName.replace(/_/g, " ");
        const filePath = path.join(dirPath, file);

        // Index by multiple variations for matching
        index[spacedName.toLowerCase()] = filePath;
        index[fileName.toLowerCase()] = filePath;
        
        // Also index first name only for common cases
        const firstName = spacedName.split(" ")[0];
        if (firstName && firstName.length > 2) {
          // Only if not ambiguous (check if already exists)
          if (!index[firstName.toLowerCase()]) {
            index[firstName.toLowerCase()] = filePath;
          }
        }
      }
    } catch (e) {
      // Skip directories we can't read
    }
  }

  personIndexCache = index;
  cacheTime = Date.now();
  return index;
}

/**
 * Clear the person index cache (useful for testing or manual refresh)
 */
export function clearPersonCache(): void {
  personIndexCache = null;
  cacheTime = 0;
}

/**
 * Look up a person by name and return their context
 */
export async function lookupPerson(name: string, vaultRoot: string): Promise<PersonContext | null> {
  const index = await buildPersonIndex(vaultRoot);
  const normalizedName = name.toLowerCase().trim();
  
  const filePath = index[normalizedName];
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }

  try {
    const content = fs.readFileSync(filePath, "utf-8");
    return parsePersonPage(content, filePath);
  } catch (e) {
    return null;
  }
}

/**
 * Parse a person page and extract key information
 */
function parsePersonPage(content: string, filePath: string): PersonContext {
  const fileName = path.basename(filePath, ".md");
  
  const context: PersonContext = {
    name: fileName.replace(/_/g, " "),
    role: null,
    company: null,
    lastInteraction: null,
    openItems: [],
    keyContext: [],
    filePath,
  };

  // Parse YAML frontmatter
  if (content.startsWith("---")) {
    const endIndex = content.indexOf("---", 3);
    if (endIndex !== -1) {
      const frontmatter = content.slice(3, endIndex);

      const roleMatch = frontmatter.match(/role:\s*["']?([^"'\n]+)["']?/);
      if (roleMatch) context.role = roleMatch[1].trim();

      const companyMatch = frontmatter.match(/company:\s*["']?([^"'\n]+)["']?/);
      if (companyMatch) context.company = companyMatch[1].trim();

      const lastMatch = frontmatter.match(/last_interaction:\s*["']?([^"'\n]+)["']?/);
      if (lastMatch) context.lastInteraction = lastMatch[1].trim();

      const nameMatch = frontmatter.match(/name:\s*["']?([^"'\n]+)["']?/);
      if (nameMatch) context.name = nameMatch[1].trim();
    }
  }

  // Extract open action items (unchecked checkboxes)
  const actionItemRegex = /^- \[ \] (.+)$/gm;
  let match;
  while ((match = actionItemRegex.exec(content)) !== null) {
    const item = match[1].replace(/\*\*/g, "").trim();
    if (item.length > 0) {
      context.openItems.push(item);
    }
  }

  // Extract key context section if present
  const keyContextMatch = content.match(/## (?:Key Context|Context|Notes)\n([\s\S]*?)(?=\n##|$)/i);
  if (keyContextMatch) {
    const keyLines = keyContextMatch[1]
      .trim()
      .split("\n")
      .filter((line) => line.startsWith("- "))
      .map((line) => line.slice(2).trim())
      .filter((line) => line.length > 0);
    context.keyContext = keyLines.slice(0, 5); // Limit to 5 items
  }

  return context;
}

/**
 * Find person mentions in text
 */
export async function findPersonMentions(text: string, vaultRoot: string): Promise<string[]> {
  const index = await buildPersonIndex(vaultRoot);
  const found: Set<string> = new Set();
  const textLower = text.toLowerCase();

  for (const [name, _path] of Object.entries(index)) {
    // Only match names with spaces (full names) to avoid false positives
    if (name.includes(" ") || name.includes("_")) {
      const searchName = name.replace(/_/g, " ");
      if (textLower.includes(searchName)) {
        found.add(name);
      }
    }
  }

  return Array.from(found);
}

/**
 * Find person references in file content (links and mentions)
 */
export function findPersonRefsInContent(content: string, vaultRoot: string): string[] {
  const refs: Set<string> = new Set();

  // Pattern 1: Wiki links to People folder
  const wikiLinkPattern = /\[\[(?:People\/)?(?:Internal|External|CPO_Network)\/([^\]|]+)/g;
  let match;
  while ((match = wikiLinkPattern.exec(content)) !== null) {
    refs.add(match[1].replace(/_/g, " ").toLowerCase());
  }

  // Pattern 2: File path references
  const fileRefPattern = /People\/(?:Internal|External|CPO_Network)\/([A-Za-z0-9_-]+)(?:\.md)?/g;
  while ((match = fileRefPattern.exec(content)) !== null) {
    refs.add(match[1].replace(/_/g, " ").toLowerCase());
  }

  return Array.from(refs);
}

/**
 * Format person contexts for injection into LLM context
 */
export function formatPersonContext(people: PersonContext[]): string {
  if (people.length === 0) return "";

  const lines: string[] = ["## Referenced People"];

  for (const person of people) {
    lines.push(`\n### ${person.name}`);
    
    const roleLine = [person.role, person.company].filter(Boolean).join(" @ ");
    if (roleLine) {
      lines.push(`- **Role:** ${roleLine}`);
    }

    if (person.lastInteraction) {
      lines.push(`- **Last interaction:** ${person.lastInteraction}`);
    }

    if (person.openItems.length > 0) {
      lines.push(`- **Open items:** ${person.openItems.length}`);
      person.openItems.slice(0, 3).forEach((item) => {
        const truncated = item.length > 80 ? item.substring(0, 80) + "..." : item;
        lines.push(`  - ${truncated}`);
      });
      if (person.openItems.length > 3) {
        lines.push(`  - _(${person.openItems.length - 3} more...)_`);
      }
    }

    if (person.keyContext.length > 0) {
      lines.push(`- **Key context:**`);
      person.keyContext.slice(0, 3).forEach((ctx) => {
        lines.push(`  - ${ctx}`);
      });
    }
  }

  return lines.join("\n");
}
