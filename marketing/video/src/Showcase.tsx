import React from "react";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { MapIntro } from "./scenes/MapIntro";
import { HowWeKnow } from "./scenes/HowWeKnow";
import { Compare } from "./scenes/Compare";
import { Search } from "./scenes/Search";
import { Sources } from "./scenes/Sources";
import { End } from "./scenes/End";
import { Progress } from "./ui";

// Episode 0, the showcase: 4:5, made to work with the sound off.
// Audience: chain expansion managers (playbook decision, 2026-10-06).
// Scene lengths in seconds, kept in one place so SHOWCASE_FRAMES stays right.
export const SCENES = { intro: 7, how: 11.5, compare: 6.5, search: 5, sources: 5, end: 5 };
const T = 0.3; // crossfade

export const Showcase: React.FC = () => {
  const { fps } = useVideoConfig();
  const t = linearTiming({ durationInFrames: Math.round(T * fps) });
  return (
    <AbsoluteFill>
      <TransitionSeries>
        <TransitionSeries.Sequence name="Map intro" durationInFrames={Math.round(SCENES.intro * fps)} premountFor={fps}>
          <MapIntro />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={t} />
        <TransitionSeries.Sequence name="How we know" durationInFrames={Math.round(SCENES.how * fps)} premountFor={fps}>
          <HowWeKnow />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={t} />
        <TransitionSeries.Sequence name="Compare" durationInFrames={Math.round(SCENES.compare * fps)} premountFor={fps}>
          <Compare />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={t} />
        <TransitionSeries.Sequence name="Search" durationInFrames={Math.round(SCENES.search * fps)} premountFor={fps}>
          <Search />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={t} />
        <TransitionSeries.Sequence name="Sources" durationInFrames={Math.round(SCENES.sources * fps)} premountFor={fps}>
          <Sources />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={t} />
        <TransitionSeries.Sequence name="End" durationInFrames={Math.round(SCENES.end * fps)} premountFor={fps}>
          <End />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <Progress />
    </AbsoluteFill>
  );
};

export const SHOWCASE_FRAMES =
  Object.values(SCENES).reduce((n, s) => n + Math.round(s * 30), 0) - (Object.keys(SCENES).length - 1) * Math.round(T * 30);
