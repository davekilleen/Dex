import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Pendo brand colors
const PENDO_BLACK = "#000000";
const PENDO_WHITE = "#FFFFFF";
const PENDO_PINK = "#FF4081";
const PENDO_GRAY = "#A0A0A0";

export const TitleScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo/icon animation
  const logoScale = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 200 },
  });

  // Title fade and slide
  const titleOpacity = interpolate(frame, [15, 35], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(frame, [15, 35], [30, 0], {
    extrapolateRight: "clamp",
  });

  // Subtitle fade
  const subtitleOpacity = interpolate(frame, [35, 55], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Value props
  const propsOpacity = interpolate(frame, [55, 75], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: PENDO_BLACK,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        gap: 20,
      }}
    >
      {/* Logo/Icon */}
      <div
        style={{
          transform: `scale(${logoScale})`,
          fontSize: 80,
          marginBottom: 20,
        }}
      >
        🧠
      </div>

      {/* Main Title */}
      <h1
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 72,
          fontWeight: 600,
          color: PENDO_WHITE,
          margin: 0,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          letterSpacing: "-2px",
        }}
      >
        Dex
      </h1>

      {/* Subtitle */}
      <p
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 32,
          fontWeight: 400,
          color: PENDO_GRAY,
          margin: 0,
          opacity: subtitleOpacity,
        }}
      >
        Your AI <span style={{ color: PENDO_PINK }}>Chief of Staff</span>
      </p>

      {/* Value props */}
      <div
        style={{
          display: "flex",
          gap: 30,
          marginTop: 30,
          opacity: propsOpacity,
        }}
      >
        {["Handles cognitive overhead", "Remembers what you forget", "Surfaces what matters"].map((prop, i) => (
          <div
            key={i}
            style={{
              backgroundColor: "rgba(255, 64, 129, 0.1)",
              padding: "10px 20px",
              borderRadius: 8,
              border: `1px solid ${PENDO_PINK}40`,
            }}
          >
            <span
              style={{
                fontFamily: "Sora, system-ui, -apple-system, sans-serif",
                fontSize: 18,
                color: PENDO_WHITE,
              }}
            >
              {prop}
            </span>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
