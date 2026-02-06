/**
 * Dex Context Types
 * Shared type definitions for context injection modules
 */

export interface PersonContext {
  name: string;
  role: string | null;
  company: string | null;
  lastInteraction: string | null;
  openItems: string[];
  keyContext: string[];
  filePath: string;
}

export interface CompanyContext {
  name: string;
  status: string | null;
  industry: string | null;
  stage: string | null;
  keyContacts: string[];
  recentActivity: string[];
  notes: string[];
  filePath: string;
}

export interface TaskContext {
  id: string;
  title: string;
  status: "n" | "s" | "b" | "d"; // not-started, started, blocked, done
  priority: "P0" | "P1" | "P2" | "P3";
  pillar: string | null;
  dueDate: string | null;
  context: string | null;
}

export interface SearchResult {
  title: string;
  path: string;
  type: "person" | "company" | "project" | "task" | "meeting" | "note";
  excerpt: string;
  score: number;
}

export interface DexStatus {
  tasks: {
    open: number;
    total: number;
    overdue: number;
    p0Count: number;
  };
  events: number;
  inbox: number;
  lastSync: string | null;
}

export interface InjectedContext {
  type: "person" | "company" | "task" | "mixed";
  content: string;
  sources: string[];
}
