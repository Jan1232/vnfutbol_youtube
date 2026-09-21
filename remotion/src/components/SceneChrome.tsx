import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';

export type SceneAssets = {
  mascotPath: string | null;
  mediaPath: string | null;
  mediaKind: 'photo' | 'graphic' | 'none';
};

const SAFE = {
  top: 120,
  bottom: 220,
  side: 48,
};

function mediaSrc(src: string): string {
  if (/^(https?:|data:|blob:)/i.test(src)) {
    return src;
  }
  if (pathIsAbsolute(src)) {
    return src;
  }
  return staticFile(src.replace(/^\/+/, ''));
}

function pathIsAbsolute(src: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(src) || src.startsWith('\\\\') || src.startsWith('file:');
}

function MediaFill({
  src,
  fit,
}: {
  src: string;
  fit: 'cover' | 'contain';
}) {
  return (
    <Img
      src={mediaSrc(src)}
      style={{
        width: '100%',
        height: '100%',
        objectFit: fit,
        objectPosition: 'center top',
      }}
    />
  );
}

function Mascot({src, style}: {src: string; style?: React.CSSProperties}) {
  return (
    <Img
      src={mediaSrc(src)}
      style={{
        width: '100%',
        height: '100%',
        objectFit: 'contain',
        objectPosition: 'center bottom',
        ...style,
      }}
    />
  );
}

export function SceneLayout({
  layout,
  assets,
  animation,
  durationInFrames,
}: {
  layout: string;
  assets: SceneAssets;
  animation: string;
  durationInFrames: number;
}) {
  const frame = useCurrentFrame();
  const t = durationInFrames <= 1 ? 0 : frame / (durationInFrames - 1);

  let opacity = 1;
  let translateX = 0;
  let translateY = 0;
  let scale = 1;

  if (animation === 'fade') {
    opacity = interpolate(frame, [0, Math.min(12, durationInFrames)], [0, 1], {
      extrapolateRight: 'clamp',
    });
  } else if (animation === 'slideUp') {
    translateY = interpolate(frame, [0, Math.min(14, durationInFrames)], [36, 0], {
      extrapolateRight: 'clamp',
    });
    opacity = interpolate(frame, [0, Math.min(10, durationInFrames)], [0, 1], {
      extrapolateRight: 'clamp',
    });
  } else if (animation === 'shake') {
    translateX = Math.sin(frame / 2.2) * 4;
  } else if (animation === 'panLeft') {
    translateX = interpolate(t, [0, 1], [10, -10]);
    scale = interpolate(t, [0, 1], [1.04, 1.0]);
  } else if (animation === 'panRight') {
    translateX = interpolate(t, [0, 1], [-10, 10]);
    scale = interpolate(t, [0, 1], [1.04, 1.0]);
  }

  const motion: React.CSSProperties = {
    opacity,
    transform: `translate(${translateX}px, ${translateY}px) scale(${scale})`,
  };

  const shell: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    background: '#0B1224',
    overflow: 'hidden',
  };

  if (layout === 'full') {
    return (
      <div style={shell}>
        <div style={{...motion, position: 'absolute', inset: 0}}>
          {assets.mediaPath ? (
            <MediaFill
              src={assets.mediaPath}
              fit={assets.mediaKind === 'graphic' ? 'contain' : 'cover'}
            />
          ) : null}
        </div>
      </div>
    );
  }

  if (layout === 'mascot-center') {
    return (
      <div style={shell}>
        {assets.mediaPath ? (
          <div
            style={{
              position: 'absolute',
              left: SAFE.side,
              right: SAFE.side,
              top: SAFE.top,
              height: '42%',
              opacity: 0.92,
              ...motion,
            }}
          >
            <MediaFill
              src={assets.mediaPath}
              fit={assets.mediaKind === 'graphic' ? 'contain' : 'cover'}
            />
          </div>
        ) : null}
        {assets.mascotPath ? (
          <div
            style={{
              position: 'absolute',
              left: '12%',
              right: '12%',
              bottom: SAFE.bottom - 40,
              height: '52%',
              ...motion,
            }}
          >
            <Mascot src={assets.mascotPath} />
          </div>
        ) : null}
      </div>
    );
  }

  const mascotLeft = layout === 'mascot-left-media-right';
  return (
    <div style={shell}>
      <div
        style={{
          position: 'absolute',
          top: SAFE.top,
          bottom: SAFE.bottom,
          left: SAFE.side,
          right: SAFE.side,
          display: 'flex',
          flexDirection: 'row',
          gap: 18,
          ...motion,
        }}
      >
        <div style={{flex: 1, position: 'relative', minWidth: 0}}>
          {mascotLeft
            ? assets.mascotPath && <Mascot src={assets.mascotPath} />
            : assets.mediaPath && (
                <MediaFill
                  src={assets.mediaPath}
                  fit={assets.mediaKind === 'graphic' ? 'contain' : 'cover'}
                />
              )}
        </div>
        <div style={{flex: 1, position: 'relative', minWidth: 0}}>
          {mascotLeft
            ? assets.mediaPath && (
                <MediaFill
                  src={assets.mediaPath}
                  fit={assets.mediaKind === 'graphic' ? 'contain' : 'cover'}
                />
              )
            : assets.mascotPath && <Mascot src={assets.mascotPath} />}
        </div>
      </div>
    </div>
  );
}

export function OverlayBadge({text}: {text: string | null}) {
  if (!text) {
    return null;
  }
  return (
    <div
      style={{
        position: 'absolute',
        top: 150,
        left: 56,
        right: 56,
        display: 'flex',
        justifyContent: 'center',
        pointerEvents: 'none',
        zIndex: 5,
      }}
    >
      <div
        style={{
          background: 'rgba(129, 22, 45, 0.92)',
          color: '#fff',
          fontSize: 42,
          fontWeight: 800,
          letterSpacing: 1,
          padding: '14px 28px',
          borderRadius: 12,
          textAlign: 'center',
          lineHeight: 1.15,
          maxWidth: '100%',
          fontFamily: 'Arial, Helvetica, sans-serif',
        }}
      >
        {text}
      </div>
    </div>
  );
}

export function CaptionBar({
  chunks,
  absoluteFrame,
  fps,
}: {
  chunks: {text: string; startSec: number; endSec: number}[];
  absoluteFrame: number;
  fps: number;
}) {
  const t = absoluteFrame / fps;
  const active = chunks.find((c) => t >= c.startSec && t < c.endSec);
  if (!active) {
    return null;
  }
  return (
    <div
      style={{
        position: 'absolute',
        left: 48,
        right: 48,
        bottom: 260,
        zIndex: 6,
        display: 'flex',
        justifyContent: 'center',
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          background: 'rgba(8, 12, 24, 0.82)',
          color: '#FFFFFF',
          fontSize: 52,
          fontWeight: 800,
          lineHeight: 1.2,
          padding: '18px 26px',
          borderRadius: 14,
          textAlign: 'center',
          maxWidth: '100%',
          fontFamily: 'Arial, Helvetica, sans-serif',
          textShadow: '0 2px 0 rgba(0,0,0,0.55)',
        }}
      >
        {active.text}
      </div>
    </div>
  );
}
