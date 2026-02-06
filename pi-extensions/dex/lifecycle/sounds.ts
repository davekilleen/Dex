/**
 * Notification Sounds Module
 * Provides audio feedback for Dex events
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// macOS system sounds
const SOUNDS = {
  ping: "/System/Library/Sounds/Ping.aiff",
  pop: "/System/Library/Sounds/Pop.aiff",
  glass: "/System/Library/Sounds/Glass.aiff",
  basso: "/System/Library/Sounds/Basso.aiff",
  hero: "/System/Library/Sounds/Hero.aiff",
  submarine: "/System/Library/Sounds/Submarine.aiff",
};

/**
 * Play a system sound
 */
export async function playSound(
  pi: ExtensionAPI,
  sound: keyof typeof SOUNDS = "ping"
): Promise<void> {
  try {
    const soundPath = SOUNDS[sound];
    await pi.exec("afplay", [soundPath], { timeout: 3000 });
  } catch (e) {
    // Sound playback failed - likely not on macOS or sound file missing
    // Fail silently
  }
}

/**
 * Set up sound notifications for agent events
 */
export function setupSounds(pi: ExtensionAPI): void {
  // Play sound when agent finishes working
  pi.on("agent_end", async (_event, ctx) => {
    await playSound(pi, "ping");
  });
}
