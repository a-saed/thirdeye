import React from "react";
import { Composition, Folder } from "remotion";
import { FPS, H, W } from "./theme";
import { SHOWCASE_FRAMES, Showcase } from "./Showcase";
import { MapIntro } from "./scenes/MapIntro";
import { HowWeKnow } from "./scenes/HowWeKnow";
import { Compare } from "./scenes/Compare";
import { Search } from "./scenes/Search";
import { Sources } from "./scenes/Sources";
import { End } from "./scenes/End";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Showcase" component={Showcase} width={W} height={H} fps={FPS} durationInFrames={SHOWCASE_FRAMES} />
    <Folder name="Scenes">
      <Composition id="MapIntro" component={MapIntro} width={W} height={H} fps={FPS} durationInFrames={210} />
      <Composition id="HowWeKnow" component={HowWeKnow} width={W} height={H} fps={FPS} durationInFrames={345} />
      <Composition id="Compare" component={Compare} width={W} height={H} fps={FPS} durationInFrames={195} />
      <Composition id="Search" component={Search} width={W} height={H} fps={FPS} durationInFrames={150} />
      <Composition id="Sources" component={Sources} width={W} height={H} fps={FPS} durationInFrames={150} />
      <Composition id="End" component={End} width={W} height={H} fps={FPS} durationInFrames={180} />
    </Folder>
  </>
);
