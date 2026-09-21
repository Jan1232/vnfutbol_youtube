import React from 'react';
import {Composition} from 'remotion';
import {ShortsDraft, type ShortsDraftProps} from './ShortsDraft';

const DEFAULT_PROPS: ShortsDraftProps = {
  videoSlug: 'granit-xhaka-covid-certificate-short',
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ShortsDraft"
        component={ShortsDraft}
        durationInFrames={30}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={DEFAULT_PROPS}
        calculateMetadata={({props}) => {
          const bundle = props.bundle;
          if (!bundle) {
            throw new Error(
              'ShortsDraft requires props.bundle. Use remotion/scripts/render-draft.mjs to load timeline/montage assets before render.',
            );
          }
          return {
            durationInFrames: bundle.durationInFrames,
            fps: bundle.fps,
            width: bundle.width,
            height: bundle.height,
            props,
          };
        }}
      />
    </>
  );
};
