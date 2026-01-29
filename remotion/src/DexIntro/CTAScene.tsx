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

export const CTAScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 100 },
  });

  const subtextOpacity = interpolate(frame, [25, 40], [0, 1], {
    extrapolateRight: "clamp",
  });

  const bulletOpacity = interpolate(frame, [40, 55], [0, 1], {
    extrapolateRight: "clamp",
  });

  const urlOpacity = interpolate(frame, [55, 70], [0, 1], {
    extrapolateRight: "clamp",
  });

  const podcastOpacity = interpolate(frame, [70, 85], [0, 1], {
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
      {/* Main CTA */}
      <h2
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 52,
          fontWeight: 600,
          color: PENDO_WHITE,
          margin: 0,
          transform: `scale(${scale})`,
          textAlign: "center",
        }}
      >
        The Year of the <span style={{ color: PENDO_PINK }}>Personal OS</span>
      </h2>

      {/* Subtext */}
      <p
        style={{
          fontFamily: "Sora, system-ui, -apple-system, sans-serif",
          fontSize: 28,
          color: PENDO_GRAY,
          margin: 0,
          opacity: subtextOpacity,
        }}
      >
        Time to build yours.
      </p>

      {/* Bullets */}
      <div
        style={{
          display: "flex",
          gap: 40,
          marginTop: 15,
          opacity: bulletOpacity,
        }}
      >
        {["30 minutes to setup", "No coding required", "31 roles supported"].map((item, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ color: PENDO_PINK, fontSize: 20 }}>✓</span>
            <span
              style={{
                fontFamily: "Sora, system-ui, -apple-system, sans-serif",
                fontSize: 18,
                color: PENDO_WHITE,
              }}
            >
              {item}
            </span>
          </div>
        ))}
      </div>

      {/* GitHub URL */}
      <div
        style={{
          backgroundColor: "rgba(30, 30, 30, 0.9)",
          padding: "15px 35px",
          borderRadius: 8,
          opacity: urlOpacity,
          marginTop: 10,
          border: `1px solid ${PENDO_GRAY}40`,
        }}
      >
        <span
          style={{
            fontFamily: "monospace",
            fontSize: 24,
            color: PENDO_PINK,
          }}
        >
          github.com/davekilleen/dex
        </span>
      </div>

      {/* Vibe PM Podcast */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginTop: 15,
          opacity: podcastOpacity,
        }}
      >
        <span style={{ fontSize: 24 }}>🎙️</span>
        <span
          style={{
            fontFamily: "Sora, system-ui, -apple-system, sans-serif",
            fontSize: 20,
            color: PENDO_GRAY,
          }}
        >
          Watch the demo on{" "}
          <span style={{ color: PENDO_PINK, fontWeight: 600 }}>The Vibe PM Podcast</span>
        </span>
      </div>
    </AbsoluteFill>
  );
};
