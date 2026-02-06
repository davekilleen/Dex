/**
 * Company Context Module
 * Looks up and formats company/account page context for injection
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { CompanyContext } from "./types.js";

// Cache for performance
let companyIndexCache: Record<string, string> | null = null;
let cacheTime = 0;
const CACHE_TTL = 60000; // 1 minute

/**
 * Build an index of company names to file paths
 */
export async function buildCompanyIndex(vaultRoot: string): Promise<Record<string, string>> {
  if (companyIndexCache && Date.now() - cacheTime < CACHE_TTL) {
    return companyIndexCache;
  }

  const index: Record<string, string> = {};
  const companiesDir = path.join(vaultRoot, "05-Areas", "Companies");

  if (!fs.existsSync(companiesDir)) {
    return index;
  }

  try {
    const files = fs.readdirSync(companiesDir);
    for (const file of files) {
      if (!file.endsWith(".md")) continue;

      const fileName = file.replace(".md", "");
      const spacedName = fileName.replace(/_/g, " ");
      const filePath = path.join(companiesDir, file);

      index[spacedName.toLowerCase()] = filePath;
      index[fileName.toLowerCase()] = filePath;
    }
  } catch (e) {
    // Skip if can't read
  }

  companyIndexCache = index;
  cacheTime = Date.now();
  return index;
}

/**
 * Clear the company index cache
 */
export function clearCompanyCache(): void {
  companyIndexCache = null;
  cacheTime = 0;
}

/**
 * Look up a company by name and return context
 */
export async function lookupCompany(name: string, vaultRoot: string): Promise<CompanyContext | null> {
  const index = await buildCompanyIndex(vaultRoot);
  const normalizedName = name.toLowerCase().trim();

  const filePath = index[normalizedName];
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }

  try {
    const content = fs.readFileSync(filePath, "utf-8");
    return parseCompanyPage(content, filePath);
  } catch (e) {
    return null;
  }
}

/**
 * Parse a company page and extract key information
 */
function parseCompanyPage(content: string, filePath: string): CompanyContext {
  const fileName = path.basename(filePath, ".md");

  const context: CompanyContext = {
    name: fileName.replace(/_/g, " "),
    status: null,
    industry: null,
    stage: null,
    keyContacts: [],
    recentActivity: [],
    notes: [],
    filePath,
  };

  // Parse YAML frontmatter
  if (content.startsWith("---")) {
    const endIndex = content.indexOf("---", 3);
    if (endIndex !== -1) {
      const frontmatter = content.slice(3, endIndex);

      const statusMatch = frontmatter.match(/status:\s*["']?([^"'\n]+)["']?/);
      if (statusMatch) context.status = statusMatch[1].trim();

      const industryMatch = frontmatter.match(/industry:\s*["']?([^"'\n]+)["']?/);
      if (industryMatch) context.industry = industryMatch[1].trim();

      const stageMatch = frontmatter.match(/stage:\s*["']?([^"'\n]+)["']?/);
      if (stageMatch) context.stage = stageMatch[1].trim();

      const nameMatch = frontmatter.match(/name:\s*["']?([^"'\n]+)["']?/);
      if (nameMatch) context.name = nameMatch[1].trim();
    }
  }

  // Extract key contacts section
  const contactsMatch = content.match(/## (?:Key Contacts|Contacts|Stakeholders)\n([\s\S]*?)(?=\n##|$)/i);
  if (contactsMatch) {
    const contactLines = contactsMatch[1]
      .trim()
      .split("\n")
      .filter((line) => line.startsWith("- "))
      .map((line) => line.slice(2).trim())
      .filter((line) => line.length > 0);
    context.keyContacts = contactLines.slice(0, 5);
  }

  // Extract recent activity section
  const activityMatch = content.match(/## (?:Recent Activity|Activity|Timeline)\n([\s\S]*?)(?=\n##|$)/i);
  if (activityMatch) {
    const activityLines = activityMatch[1]
      .trim()
      .split("\n")
      .filter((line) => line.startsWith("- "))
      .map((line) => line.slice(2).trim())
      .filter((line) => line.length > 0);
    context.recentActivity = activityLines.slice(0, 3);
  }

  // Extract notes section
  const notesMatch = content.match(/## (?:Notes|Context|Background)\n([\s\S]*?)(?=\n##|$)/i);
  if (notesMatch) {
    const noteLines = notesMatch[1]
      .trim()
      .split("\n")
      .filter((line) => line.startsWith("- "))
      .map((line) => line.slice(2).trim())
      .filter((line) => line.length > 0);
    context.notes = noteLines.slice(0, 3);
  }

  return context;
}

/**
 * Find company mentions in text
 */
export async function findCompanyMentions(text: string, vaultRoot: string): Promise<string[]> {
  const index = await buildCompanyIndex(vaultRoot);
  const found: Set<string> = new Set();
  const textLower = text.toLowerCase();

  for (const [name, _path] of Object.entries(index)) {
    // Match company names (typically multi-word or capitalized)
    const searchName = name.replace(/_/g, " ");
    if (searchName.length > 3 && textLower.includes(searchName)) {
      found.add(name);
    }
  }

  return Array.from(found);
}

/**
 * Find company references in file content
 */
export function findCompanyRefsInContent(content: string, vaultRoot: string): string[] {
  const refs: Set<string> = new Set();

  // Wiki links to Companies folder
  const wikiLinkPattern = /\[\[(?:Companies)\/([^\]|]+)/g;
  let match;
  while ((match = wikiLinkPattern.exec(content)) !== null) {
    refs.add(match[1].replace(/_/g, " ").toLowerCase());
  }

  // File path references
  const fileRefPattern = /Companies\/([A-Za-z0-9_-]+)(?:\.md)?/g;
  while ((match = fileRefPattern.exec(content)) !== null) {
    refs.add(match[1].replace(/_/g, " ").toLowerCase());
  }

  return Array.from(refs);
}

/**
 * Format company contexts for injection
 */
export function formatCompanyContext(companies: CompanyContext[]): string {
  if (companies.length === 0) return "";

  const lines: string[] = ["## Referenced Companies"];

  for (const company of companies) {
    lines.push(`\n### ${company.name}`);

    const metaItems: string[] = [];
    if (company.status) metaItems.push(`Status: ${company.status}`);
    if (company.industry) metaItems.push(`Industry: ${company.industry}`);
    if (company.stage) metaItems.push(`Stage: ${company.stage}`);
    
    if (metaItems.length > 0) {
      lines.push(`- **${metaItems.join(" | ")}**`);
    }

    if (company.keyContacts.length > 0) {
      lines.push(`- **Key contacts:** ${company.keyContacts.slice(0, 3).join(", ")}`);
    }

    if (company.recentActivity.length > 0) {
      lines.push(`- **Recent activity:**`);
      company.recentActivity.slice(0, 2).forEach((activity) => {
        lines.push(`  - ${activity}`);
      });
    }

    if (company.notes.length > 0) {
      lines.push(`- **Notes:**`);
      company.notes.slice(0, 2).forEach((note) => {
        lines.push(`  - ${note}`);
      });
    }
  }

  return lines.join("\n");
}
