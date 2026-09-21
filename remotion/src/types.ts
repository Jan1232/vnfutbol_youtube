export type Overlay = {text?: string; style?: string} | null;

export type CaptionChunk = {
  text: string;
  startSec: number;
  endSec: number;
};

export type ResolvedScene = {
  id: string;
  startSec: number;
  durationSec: number;
  layout: string;
  animation: string;
  overlayText: string | null;
  mascotPath: string | null;
  mediaPath: string | null;
  mediaKind: 'photo' | 'graphic' | 'none';
  captions: CaptionChunk[];
};

export type ShortsBundle = {
  videoSlug: string;
  repoRoot: string;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  totalDurationSec: number;
  narrationPath: string;
  scenes: ResolvedScene[];
  assetCount: number;
  fallbacks: {
    layouts: string[];
    animations: string[];
  };
};
