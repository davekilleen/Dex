import { Composition } from "remotion";
import { DexIntro } from "./DexIntro";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Dex Intro Video - 21.5 seconds at 30fps */}
      <Composition
        id="DexIntro"
        component={DexIntro}
        durationInFrames={645}
        fps={30}
        width={1920}
        height={1080}
      />

      {/* LinkedIn format - square */}
      <Composition
        id="DexIntro-Square"
        component={DexIntro}
        durationInFrames={645}
        fps={30}
        width={1080}
        height={1080}
      />

      {/* Vertical format for shorts/reels */}
      <Composition
        id="DexIntro-Vertical"
        component={DexIntro}
        durationInFrames={645}
        fps={30}
        width={1080}
        height={1920}
      />
    </>
  );
};
