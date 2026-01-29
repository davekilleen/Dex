import { AbsoluteFill, Sequence } from "remotion";
import { ProblemScene } from "./ProblemScene";
import { TitleScene } from "./TitleScene";
import { DayInLifeScene } from "./DayInLifeScene";
import { SelfUpgradeScene } from "./SelfUpgradeScene";
import { CTAScene } from "./CTAScene";

export const DexIntro: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      {/* Problem: 0-180 frames (6 seconds) - slower flood, let it land */}
      <Sequence from={0} durationInFrames={180}>
        <ProblemScene />
      </Sequence>

      {/* Title + Value Props: 180-285 frames (3.5 seconds) */}
      <Sequence from={180} durationInFrames={105}>
        <TitleScene />
      </Sequence>

      {/* Day in Life: 285-420 frames (4.5 seconds) */}
      <Sequence from={285} durationInFrames={135}>
        <DayInLifeScene />
      </Sequence>

      {/* Self-Upgrading System: 420-555 frames (4.5 seconds) */}
      <Sequence from={420} durationInFrames={135}>
        <SelfUpgradeScene />
      </Sequence>

      {/* CTA: 555-645 frames (3 seconds) */}
      <Sequence from={555} durationInFrames={90}>
        <CTAScene />
      </Sequence>
    </AbsoluteFill>
  );
};
