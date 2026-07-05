#!/usr/bin/env node

/**
 * Test script for email-triage worker
 * Tests rule-based classification locally
 * Run: node test.js
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load the rules
const rulesPath = path.join(__dirname, "rules.json");
const rules = JSON.parse(fs.readFileSync(rulesPath, "utf-8"));

// Copy the classification logic from worker.js
function matchPatterns(text, patterns) {
  if (!patterns || patterns.length === 0) return false;
  return patterns.some(p => {
    try {
      return new RegExp(p, "i").test(text);
    } catch (e) {
      return false;
    }
  });
}

function ruleMatches(email, rule) {
  const textBody = `${email.subject || ""} ${email.body || ""}`;
  const from = (email.from || "").toLowerCase();
  const to = (email.to || "").toLowerCase();

  if (rule.patterns && matchPatterns(textBody, rule.patterns)) {
    return true;
  }
  if (rule.from_patterns && matchPatterns(from, rule.from_patterns)) {
    return true;
  }
  if (rule.to_patterns && matchPatterns(to, rule.to_patterns)) {
    return true;
  }
  if (rule.subject_patterns && matchPatterns(email.subject || "", rule.subject_patterns)) {
    return true;
  }
  if (rule.body_patterns && matchPatterns(email.body || "", rule.body_patterns)) {
    return true;
  }

  return false;
}

function classifyEmail(email, rules) {
  const categoryOrder = ["urgent", "follow_up", "fyi", "ignore"];

  for (const category of categoryOrder) {
    const categoryRules = rules[category] || [];

    for (const rule of categoryRules) {
      if (ruleMatches(email, rule)) {
        return {
          category,
          confidence: rule.confidence || 0.8,
          reasoning: rule.reason || `Matched ${category} rules`,
          method: "rule-based"
        };
      }
    }
  }

  return {
    category: "fyi",
    confidence: 0.5,
    reasoning: "No rules matched, defaulting to FYI",
    method: "rule-based"
  };
}

// Test cases
const testCases = [
  {
    name: "Urgent email — production issue",
    email: {
      from: "oncall@example.com",
      to: "eng-team@example.com",
      subject: "CRITICAL: Production database down",
      body: "Our main database is down. All transactions failing. Immediate action required.",
    },
    expectedCategory: "urgent",
  },
  {
    name: "Follow-up email — decision needed",
    email: {
      from: "manager@example.com",
      to: "you@example.com",
      subject: "Q3 roadmap review — need your input",
      body: "Can you review the attached Q3 roadmap and provide feedback by EOD? We need to finalize priorities.",
    },
    expectedCategory: "follow_up",
  },
  {
    name: "FYI email — announcement",
    email: {
      from: "news@example.com",
      to: "all@example.com",
      subject: "New office holiday schedule",
      body: "Please see attached for the updated 2026 holiday schedule. All offices closed on these dates.",
    },
    expectedCategory: "fyi",
  },
  {
    name: "Ignore email — newsletter",
    email: {
      from: "newsletter@tech-news.com",
      to: "you@example.com",
      subject: "Weekly Tech News Digest",
      body: "This week in tech: New AI models, framework updates, industry news. Read more on our site.",
    },
    expectedCategory: "ignore",
  },
  {
    name: "Urgent email — service outage",
    email: {
      from: "alerts@monitoring.com",
      subject: "Service outage detected",
      body: "Multiple services are down. Immediate action required.",
    },
    expectedCategory: "urgent",
  },
];

function runTests() {
  console.log("🧪 Email Triage Worker — Rule-Based Test Suite");
  console.log(`   Rules loaded: ${rulesPath}`);
  console.log(`   Categories: ${Object.keys(rules).join(", ")}`);

  let passed = 0;
  let total = testCases.length;

  for (const testCase of testCases) {
    const result = classifyEmail(testCase.email, rules);
    const category = result.category;
    const confidence = (result.confidence * 100).toFixed(0);

    const isCorrect = category === testCase.expectedCategory;
    const icon = isCorrect ? "✅" : "⚠️";

    console.log(`\n${icon} ${testCase.name}`);
    console.log(`   Classified: ${category} (${confidence}% confidence)`);
    console.log(`   Reasoning: ${result.reasoning}`);

    if (!isCorrect) {
      console.log(`   Expected: ${testCase.expectedCategory}`);
    } else {
      passed++;
    }
  }

  console.log(`\n${"─".repeat(50)}`);
  console.log(`📊 Results: ${passed}/${total} tests passed`);

  if (passed === total) {
    console.log("✅ All tests passed!");
    process.exit(0);
  } else {
    console.log(`⚠️ ${total - passed} test(s) may need rule adjustments`);
    process.exit(1);
  }
}

runTests();
