import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {CaptionBar, OverlayBadge, SceneLayout} from './components/SceneChrome';
import type {ShortsBundle} from './types';

export type ShortsDraftProps = {
  videoSlug: string;
  repoRoot?: string;
  bundle?: ShortsBundle;
};

function audioSrc(src: string): string {
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  if (/^[a-zA-Z]:[\\/]/.test(src) || src.startsWith('\\\\')) return src;
  return staticFile(src.replace(/^\/+/, ''));
}

export const ShortsDraft: React.FC<ShortsDraftProps> = ({bundle}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  if (!bundle) {
    return <AbsoluteFill style={{backgroundColor: '#0B1224'}} />;
  }

  return (
    <AbsoluteFill style={{backgroundColor: '#0B1224'}}>
      <Audio src={audioSrc(bundle.narrationPath)} />
      {bundle.scenes.map((scene) => {
        const from = Math.round(scene.startSec * fps);
        const durationInFrames = Math.max(1, Math.round(scene.durationSec * fps));
        return (
          <Sequence key={scene.id} from={from} durationInFrames={durationInFrames} name={scene.id}>
            <AbsoluteFill>
              <SceneLayout
                layout={scene.layout}
                animation={scene.animation}
                durationInFrames={durationInFrames}
                assets={{
                  mascotPath: scene.mascotPath,
                  mediaPath: scene.mediaPath,
                  mediaKind: scene.mediaKind,
                }}
              />
              <OverlayBadge text={scene.overlayText} />
              <CaptionBar chunks={scene.captions} absoluteFrame={frame} fps={fps} />
            </AbsoluteFill>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
