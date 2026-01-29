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

const moments = [
  {
    time: "7:30am",
    icon: "☀️",
    action: "/daily-plan",
    result: "Today's Three priorities. Won't let you overcommit.",
  },
  {
    time: "10am",
    icon: "📞",
    action: "Before a call",
    result: "Full context on who you're meeting. What you owe them.",
  },
  {
    time: "5:30pm",
    icon: "🌙",
    action: "/daily-review",
    result: "What happened. What the system learned. Tomorrow's prep.",
  },
];

export const DayInLifeScene: React.FC = () => {
  const frame = useCurrentFrame();

  const headerOpacity = interpolate(frame, [0, 15], [0, 1], {
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
          marginBottom: 50,
          opacity: headerOpacity,
        }}
      >
        A Day With Your <span style={{ color: PENDO_PINK }}>Chief of Staff</span>
      </h2>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 25,
          maxWidth: 900,
        }}
      >
        {moments.map((moment, index) => {
          const delay = 15 + index * 30;
          const slideIn = interpolate(frame, [delay, delay + 15], [-40, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const opacity = interpolate(frame, [delay, delay + 15], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });

          return (
            <div
              key={index}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 20,
                transform: `translateX(${slideIn}px)`,
                opacity,
                backgroundColor: "rgba(30, 30, 30, 0.8)",
                padding: "20px 25px",
                borderRadius: 12,
                borderLeft: `3px solid ${PENDO_PINK}`,
              }}
            >
              {/* Time + Icon */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  minWidth: 140,
                }}
              >
                <span style={{ fontSize: 28 }}>{moment.icon}</span>
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 18,
                    color: PENDO_GRAY,
                  }}
                >
                  {moment.time}
                </span>
              </div>

              {/* Action */}
              <div
                style={{
                  backgroundColor: `${PENDO_PINK}20`,
                  padding: "6px 14px",
                  borderRadius: 6,
                  minWidth: 140,
                }}
              >
                <span
                  style={{
                    fontFamily: "monospace",
                    fontSize: 16,
                    color: PENDO_PINK,
                  }}
                >
                  {moment.action}
                </span>
              </div>

              {/* Result */}
              <span
                style={{
                  fontFamily: "Sora, system-ui, -apple-system, sans-serif",
                  fontSize: 20,
                  color: PENDO_WHITE,
                  flex: 1,
                }}
              >
                {moment.result}
              </span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
