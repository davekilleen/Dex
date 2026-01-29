import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
} from "remotion";

// Pendo brand colors
const PENDO_BLACK = "#000000";
const PENDO_WHITE = "#FFFFFF";
const PENDO_PINK = "#FF4081";
const PENDO_GRAY = "#A0A0A0";

export const SelfUpgradeScene: React.FC = () => {
  const frame = useCurrentFrame();

  // Changelog pull animation
  const changelogOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });
  const changelogScale = interpolate(frame, [0, 15], [0.9, 1], {
    extrapolateRight: "clamp",
  });

  // Arrow animation
  const arrowOpacity = interpolate(frame, [30, 45], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Suggestion bubble
  const suggestionOpacity = interpolate(frame, [50, 70], [0, 1], {
    extrapolateRight: "clamp",
  });
  const suggestionY = interpolate(frame, [50, 70], [20, 0], {
    extrapolateRight: "clamp",
  });

  // Punchline
  const punchlineOpacity = interpolate(frame, [90, 110], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: PENDO_BLACK,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        padding: 60,
      }}
    >
      <h2
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 42,
          fontWeight: 600,
          color: PENDO_WHITE,
          marginBottom: 40,
          opacity: changelogOpacity,
        }}
      >
        The System That <span style={{ color: PENDO_PINK }}>Improves Itself</span>
      </h2>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 30,
          marginBottom: 30,
        }}
      >
        {/* Changelog box */}
        <div
          style={{
            backgroundColor: "rgba(30, 30, 30, 0.9)",
            padding: "20px 30px",
            borderRadius: 12,
            border: `1px solid ${PENDO_GRAY}40`,
            opacity: changelogOpacity,
            transform: `scale(${changelogScale})`,
          }}
        >
          <div style={{ fontSize: 14, color: PENDO_GRAY, marginBottom: 8, fontFamily: "Sora, system-ui, sans-serif" }}>
            Claude Code Changelog
          </div>
          <div style={{ fontFamily: "monospace", fontSize: 16, color: PENDO_GRAY }}>
            v1.0.47 - New capability...
          </div>
        </div>

        {/* Arrow */}
        <div
          style={{
            fontSize: 36,
            color: PENDO_PINK,
            opacity: arrowOpacity,
          }}
        >
          →
        </div>

        {/* Your system box */}
        <div
          style={{
            backgroundColor: `${PENDO_PINK}15`,
            padding: "20px 30px",
            borderRadius: 12,
            border: `1px solid ${PENDO_PINK}40`,
            opacity: arrowOpacity,
          }}
        >
          <div style={{ fontSize: 14, color: PENDO_GRAY, marginBottom: 8, fontFamily: "Sora, system-ui, sans-serif" }}>
            Your Dex System
          </div>
          <div style={{ fontFamily: "monospace", fontSize: 16, color: PENDO_PINK }}>
            /daily-plan, /review...
          </div>
        </div>
      </div>

      {/* AI suggestion bubble */}
      <div
        style={{
          backgroundColor: "rgba(30, 30, 30, 0.9)",
          padding: "20px 35px",
          borderRadius: 12,
          border: `1px solid ${PENDO_PINK}60`,
          maxWidth: 700,
          opacity: suggestionOpacity,
          transform: `translateY(${suggestionY}px)`,
        }}
      >
        <span
          style={{
            fontFamily: "Sora, system-ui, -apple-system, sans-serif",
            fontSize: 22,
            color: PENDO_WHITE,
            fontStyle: "italic",
          }}
        >
          "This new feature could make your morning intel faster. <span style={{ color: PENDO_PINK }}>Want me to implement it?</span>"
        </span>
      </div>

      {/* Punchline */}
      <p
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 24,
          fontWeight: 400,
          color: PENDO_GRAY,
          marginTop: 40,
          opacity: punchlineOpacity,
          textAlign: "center",
        }}
      >
        Your system evolves at the pace Claude evolves.
        <br />
        <span style={{ color: PENDO_PINK }}>You don't track releases. It does.</span>
      </p>
    </AbsoluteFill>
  );
};
