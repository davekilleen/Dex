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

export const ProblemScene: React.FC = () => {
  const frame = useCurrentFrame();

  // Notifications flooding in animation - slower cascade
  const notification1Y = interpolate(frame, [0, 35], [-100, 80], {
    extrapolateRight: "clamp",
  });
  const notification2Y = interpolate(frame, [20, 55], [-100, 160], {
    extrapolateRight: "clamp",
  });
  const notification3Y = interpolate(frame, [40, 75], [-100, 240], {
    extrapolateRight: "clamp",
  });

  // Let notifications sit for a moment before fading
  const notificationsOpacity = interpolate(frame, [95, 115], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Main text fade in - after notifications fade
  const textOpacity = interpolate(frame, [110, 130], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const subTextOpacity = interpolate(frame, [135, 155], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: PENDO_BLACK,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
      }}
    >
      {/* Flooding notifications */}
      <div style={{ opacity: notificationsOpacity, position: "absolute" }}>
        {[
          { y: notification1Y, text: "🤖 New AI tool launched..." },
          { y: notification2Y, text: "📧 AI newsletter: 47 unread" },
          { y: notification3Y, text: "🎬 Must-watch AI demo..." },
        ].map((notif, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              left: "50%",
              transform: `translateX(-50%) translateY(${notif.y}px)`,
              backgroundColor: "rgba(30, 30, 30, 0.95)",
              padding: "12px 24px",
              borderRadius: 8,
              border: `1px solid ${PENDO_GRAY}40`,
              whiteSpace: "nowrap",
            }}
          >
            <span
              style={{
                fontFamily: "Sora, system-ui, -apple-system, sans-serif",
                fontSize: 20,
                color: PENDO_GRAY,
              }}
            >
              {notif.text}
            </span>
          </div>
        ))}
      </div>

      {/* Overwhelm emoji */}
      <div
        style={{
          opacity: textOpacity,
          fontSize: 72,
          marginBottom: 20,
        }}
      >
        🤯
      </div>

      {/* Main message */}
      <div
        style={{
          opacity: textOpacity,
          textAlign: "center",
          maxWidth: 900,
        }}
      >
        <h2
          style={{
            fontFamily: "Sora, system-ui, -apple-system, sans-serif",
            fontSize: 48,
            fontWeight: 600,
            color: PENDO_WHITE,
            margin: 0,
            lineHeight: 1.2,
          }}
        >
          You're <span style={{ color: PENDO_PINK }}>barely scratching</span> the surface.
        </h2>
      </div>

      <p
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 26,
          color: PENDO_GRAY,
          marginTop: 25,
          opacity: subTextOpacity,
          textAlign: "center",
        }}
      >
        Most people use AI as a slightly smarter search engine.
      </p>
    </AbsoluteFill>
  );
};
