/**
 * Dex Smart Model Router
 * 
 * Automatically selects the optimal model based on task complexity.
 * Saves costs on simple operations, ensures quality on complex ones.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// ============================================================================
// TASK CLASSIFICATION
// ============================================================================

type ModelTier = "fast" | "balanced" | "powerful";

interface TaskClassification {
  tier: ModelTier;
  reason: string;
  suggestedModel?: string;
}

const FAST_PATTERNS = [
  /^(what|who|when|where|how many|list|show|get|find)\b/i,
  /^(create task|add task|mark|complete)\b/i,
  /^(search|look up|check)\b/i,
  /^(status|tasks|today|calendar)\b/i,
];

const POWERFUL_PATTERNS = [
  /\b(analyze|assessment|evaluate|review)\b/i,
  /\b(plan|strategy|prioritize)\b/i,
  /\b(write|draft|compose|create.*document)\b/i,
  /\b(explain|why|how does|reasoning)\b/i,
  /\b(complex|detailed|comprehensive)\b/i,
  /\b(career|promotion|growth)\b/i,
  /\b(compare|contrast|trade-?offs)\b/i,
];

function classifyTask(prompt: string): TaskClassification {
  const promptLower = prompt.toLowerCase();
  const promptLength = prompt.length;
  
  // Very short prompts are usually simple
  if (promptLength < 30) {
    for (const pattern of FAST_PATTERNS) {
      if (pattern.test(prompt)) {
        return { tier: "fast", reason: "Simple lookup/operation" };
      }
    }
  }
  
  // Check for powerful patterns
  for (const pattern of POWERFUL_PATTERNS) {
    if (pattern.test(promptLower)) {
      return { tier: "powerful", reason: "Complex analysis/planning required" };
    }
  }
  
  // Long prompts usually need more capability
  if (promptLength > 200) {
    return { tier: "powerful", reason: "Complex multi-part request" };
  }
  
  // Default to balanced
  return { tier: "balanced", reason: "Standard request" };
}

// Model preferences by tier
const TIER_MODELS: Record<ModelTier, string[]> = {
  fast: ["claude-haiku-3-5", "claude-3-haiku", "gpt-4o-mini"],
  balanced: ["claude-sonnet-4-5", "claude-3-5-sonnet", "gpt-4o"],
  powerful: ["claude-sonnet-4-5", "claude-3-5-sonnet", "claude-3-opus"]
};

// ============================================================================
// EXTENSION REGISTRATION
// ============================================================================

export function registerModelRouter(pi: ExtensionAPI) {
  let autoRouting = true; // Can be toggled
  let lastModelSwitch: { from: string; to: string; reason: string } | null = null;
  
  pi.on("before_agent_start", async (event, ctx) => {
    if (!autoRouting) return {};
    
    const classification = classifyTask(event.prompt);
    const currentModel = ctx.model;
    
    // Determine target model based on tier
    const preferredModels = TIER_MODELS[classification.tier];
    
    // Try to find a matching model in the registry
    for (const modelId of preferredModels) {
      const model = ctx.modelRegistry.find("anthropic", modelId);
      if (model) {
        // Only switch if different
        if (currentModel?.id !== model.id) {
          const success = await pi.setModel(model);
          if (success) {
            lastModelSwitch = {
              from: currentModel?.id || "unknown",
              to: model.id,
              reason: classification.reason
            };
            
            // Update status to show model switch
            if (ctx.hasUI) {
              ctx.ui.setStatus("dex-model", `🔀 ${model.id.split("-").slice(-2).join("-")}`);
            }
          }
        }
        break;
      }
    }
    
    return {};
  });
  
  // Command to toggle auto-routing
  pi.registerCommand("auto-model", {
    description: "Toggle automatic model routing based on task complexity",
    handler: async (args, ctx) => {
      autoRouting = !autoRouting;
      ctx.ui.notify(
        `Auto model routing: ${autoRouting ? "ON" : "OFF"}`,
        autoRouting ? "success" : "info"
      );
    }
  });
  
  // Command to see last model switch
  pi.registerCommand("model-info", {
    description: "Show info about the last automatic model switch",
    handler: async (args, ctx) => {
      if (lastModelSwitch) {
        ctx.ui.notify(
          `Last switch: ${lastModelSwitch.from} → ${lastModelSwitch.to}\n` +
          `Reason: ${lastModelSwitch.reason}`,
          "info"
        );
      } else {
        ctx.ui.notify("No automatic model switches yet", "info");
      }
    }
  });
}
