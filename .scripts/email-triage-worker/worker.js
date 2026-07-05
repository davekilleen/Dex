/**
 * email-triage — Cloudflare Worker
 * Classifies incoming emails using rule-based logic.
 *
 * Required Worker Secrets (set via `wrangler secret put`):
 *   MCP_SECRET – Bearer token for auth
 */

const CATEGORIES = {
  urgent: "Requires immediate action or response",
  follow_up: "Action needed but not urgent",
  fyi: "Informational, no action needed",
  ignore: "Can be safely ignored or archived"
};

// ─── Rule-Based Classification ────────────────────────────────────────────

/**
 * Default triage rules. Customize for your workflow.
 */
const DEFAULT_RULES = {
  urgent: [
    {
      patterns: ["URGENT", "CRITICAL", "EMERGENCY", "DOWN", "OUTAGE"],
      confidence: 0.95
    },
    {
      from_patterns: ["oncall@", "alerts@", "emergency@"],
      confidence: 0.9
    },
    {
      subject_patterns: ["production.*down", "database.*error", "service.*outage"],
      confidence: 0.95
    },
    {
      body_patterns: ["immediate action", "right now", "asap", "call me"],
      confidence: 0.85
    }
  ],
  follow_up: [
    {
      patterns: ["please review", "feedback needed", "input required", "approval", "decision"],
      confidence: 0.9
    },
    {
      patterns: ["by end of day", "by tomorrow", "deadline", "due date"],
      confidence: 0.85
    },
    {
      from_patterns: ["manager@", "boss@", "cto@", "ceo@"],
      patterns: ["review", "check", "look at"],
      confidence: 0.8
    },
    {
      subject_patterns: ["for your review", "action required", "response needed"],
      confidence: 0.9
    }
  ],
  fyi: [
    {
      patterns: ["FYI", "heads up", "just so you know", "announcement", "update"],
      confidence: 0.85
    },
    {
      subject_patterns: ["schedule", "policy", "news", "announcement"],
      confidence: 0.8
    },
    {
      from_patterns: ["news@", "updates@", "admin@"],
      confidence: 0.8
    },
    {
      patterns: ["please find attached", "for your information"],
      confidence: 0.75
    }
  ],
  ignore: [
    {
      from_patterns: ["newsletter@", "promotions@", "marketing@", "noreply@", "no-reply@"],
      confidence: 0.95
    },
    {
      subject_patterns: ["unsubscribe", "promotional", "sale", "offer"],
      confidence: 0.9
    },
    {
      patterns: ["click here to unsubscribe", "marketing email"],
      confidence: 0.95
    },
    {
      from_patterns: ["mail-delivery-failed@", "mailer-daemon@", "postmaster@"],
      confidence: 0.9
    }
  ]
};

/**
 * Check if text matches any pattern in patterns array
 */
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

/**
 * Check if email matches a rule
 */
function ruleMatches(email, rule) {
  const textBody = `${email.subject || ""} ${email.body || ""}`;
  const from = (email.from || "").toLowerCase();
  const to = (email.to || "").toLowerCase();

  // Check patterns (subject + body)
  if (rule.patterns && matchPatterns(textBody, rule.patterns)) {
    return true;
  }

  // Check from patterns
  if (rule.from_patterns && matchPatterns(from, rule.from_patterns)) {
    return true;
  }

  // Check to patterns
  if (rule.to_patterns && matchPatterns(to, rule.to_patterns)) {
    return true;
  }

  // Check subject patterns
  if (rule.subject_patterns && matchPatterns(email.subject || "", rule.subject_patterns)) {
    return true;
  }

  // Check body patterns
  if (rule.body_patterns && matchPatterns(email.body || "", rule.body_patterns)) {
    return true;
  }

  return false;
}

/**
 * Classify email using rule-based logic
 */
function classifyEmail(email, rules = DEFAULT_RULES) {
  // Check each category in order: urgent → follow_up → fyi → ignore
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

  // Default fallback
  return {
    category: "fyi",
    confidence: 0.5,
    reasoning: "No rules matched, defaulting to FYI",
    method: "rule-based"
  };
}

/**
 * Validate Bearer token from Authorization header
 */
function validateAuth(request, mcp_secret) {
  const auth = request.headers.get("Authorization");
  if (!auth || !auth.startsWith("Bearer ")) {
    return false;
  }
  const token = auth.slice(7);
  return token === mcp_secret;
}

/**
 * Handle POST /ingest-email
 */
async function handleIngestEmail(request, env) {
  if (!validateAuth(request, env.MCP_SECRET)) {
    return new Response("Unauthorized", { status: 401 });
  }

  let email;
  try {
    email = await request.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
      status: 400,
      headers: { "content-type": "application/json" },
    });
  }

  // Validate required fields (at least one of subject or body)
  if (!email.subject && !email.body) {
    return new Response(
      JSON.stringify({
        error: "Missing required fields: at least subject or body required",
      }),
      {
        status: 400,
        headers: { "content-type": "application/json" },
      }
    );
  }

  try {
    const classification = classifyEmail(email, DEFAULT_RULES);

    return new Response(
      JSON.stringify({
        email_id: email.email_id || null,
        subject: email.subject || "(no subject)",
        from: email.from || "unknown",
        to: email.to || "unknown",
        classification,
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );
  } catch (error) {
    console.error("Triage error:", error);
    return new Response(
      JSON.stringify({
        error: "Failed to classify email",
        message: error.message,
      }),
      {
        status: 500,
        headers: { "content-type": "application/json" },
      }
    );
  }
}

/**
 * Handle GET / (health check)
 */
function handleRoot() {
  return new Response(
    JSON.stringify({
      service: "email-triage",
      status: "ok",
      categories: CATEGORIES,
    }),
    {
      status: 200,
      headers: { "content-type": "application/json" },
    }
  );
}

/**
 * Main worker fetch handler
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return handleRoot();
    }

    if (request.method === "POST" && url.pathname === "/ingest-email") {
      return await handleIngestEmail(request, env);
    }

    return new Response("Not found", { status: 404 });
  },
};
