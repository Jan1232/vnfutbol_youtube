import * as fs from 'node:fs';
import * as path from 'node:path';

export type Overlay = {text?: string; style?: string} | null;

export type TimelineScene = {
  id: string;
  start: number;
  duration: number;
  layout: string;
  animation?: string;
  voiceIds?: string[];
  visual?: {
    type?: string;
    asset?: string;
    supportingAsset?: string;
  };
  overlay?: Overlay;
};

export type Timeline = {
  version: number;
  fps: number;
  width: number;
  height: number;
  totalDuration: number;
  draft?: boolean;
  scenes: TimelineScene[];
};

export type PathsItem = {
  slot: string;
  source: string;
  mode?: string;
  assetId?: string;
  pointer?: string;
};

export type PathsManifest = {
  version: number;
  video: string;
  items: PathsItem[];
};

export type VoiceSegment = {
  id: string;
  text?: string;
  ttsText?: string;
  startMs?: number;
  endMs?: number;
  status?: string;
};

export type VoiceJson = {
  version: number;
  segments: VoiceSegment[];
};

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

const SUPPORTED_LAYOUTS = new Set([
  'mascot-left-media-right',
  'media-left-mascot-right',
  'mascot-center',
  'full',
]);

const SUPPORTED_ANIMATIONS = new Set([
  'shake',
  'panLeft',
  'fade',
  'slideUp',
  'hardCut',
  'panRight',
]);

export function repoRootFromCwd(cwd = process.cwd()): string {
  return path.resolve(cwd);
}

export function videoDir(repoRoot: string, slug: string): string {
  return path.join(repoRoot, 'videos', slug);
}

function readJson<T>(filePath: string): T {
  return JSON.parse(fs.readFileSync(filePath, 'utf8')) as T;
}

function mustExist(filePath: string, label: string): string {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    throw new Error(`MISSING_ASSET ${label}: ${filePath}`);
  }
  return path.resolve(filePath);
}

function resolveRepoPath(repoRoot: string, relOrAbs: string): string {
  if (path.isAbsolute(relOrAbs)) {
    return path.resolve(relOrAbs);
  }
  return path.resolve(repoRoot, relOrAbs);
}

function slotMap(paths: PathsManifest): Map<string, PathsItem> {
  const map = new Map<string, PathsItem>();
  for (const item of paths.items) {
    map.set(item.slot.replace(/\\/g, '/'), item);
  }
  return map;
}

function resolveSlotFile(
  repoRoot: string,
  videoRoot: string,
  slots: Map<string, PathsItem>,
  slot: string,
  label: string,
): string {
  const item = slots.get(slot);
  const candidates: string[] = [];
  if (item?.source) {
    candidates.push(resolveRepoPath(repoRoot, item.source));
  }
  candidates.push(path.join(videoRoot, 'montage', slot));
  for (const candidate of candidates) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return path.resolve(candidate);
    }
  }
  throw new Error(
    `MISSING_ASSET ${label} (slot=${slot}). Checked: ${candidates.join(' | ')}`,
  );
}

function chunkPhrase(text: string, minWords = 2, maxWords = 6): string[] {
  const words = text
    .replace(/\s+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean);
  if (words.length === 0) {
    return [];
  }
  const chunks: string[] = [];
  let i = 0;
  while (i < words.length) {
    const remaining = words.length - i;
    let take = Math.min(maxWords, remaining);
    if (remaining > maxWords && remaining - maxWords < minWords) {
      take = Math.max(minWords, remaining - minWords);
    }
    if (take < minWords && remaining >= minWords) {
      take = minWords;
    }
    chunks.push(words.slice(i, i + take).join(' '));
    i += take;
  }
  return chunks;
}

function captionsForScene(
  scene: TimelineScene,
  voiceById: Map<string, VoiceSegment>,
): CaptionChunk[] {
  const ids = scene.voiceIds ?? [];
  const chunks: CaptionChunk[] = [];
  for (const id of ids) {
    const seg = voiceById.get(id);
    if (!seg) {
      continue;
    }
    const text = (seg.text || seg.ttsText || '').trim();
    if (!text) {
      continue;
    }
    const startSec = (seg.startMs ?? scene.start * 1000) / 1000;
    const endSec = (seg.endMs ?? (scene.start + scene.duration) * 1000) / 1000;
    const phrases = chunkPhrase(text);
    if (phrases.length === 0) {
      continue;
    }
    const span = Math.max(0.05, endSec - startSec);
    const each = span / phrases.length;
    phrases.forEach((phrase, index) => {
      chunks.push({
        text: phrase,
        startSec: startSec + index * each,
        endSec: startSec + (index + 1) * each,
      });
    });
  }
  return chunks;
}

function supportingIsGraphic(assetId: string | undefined): boolean {
  if (!assetId) {
    return false;
  }
  return (
    assetId.startsWith('stat-') ||
    assetId.startsWith('text-') ||
    assetId.startsWith('news-') ||
    assetId.startsWith('map-')
  );
}

export function loadShortsBundle(repoRoot: string, videoSlug: string): ShortsBundle {
  const root = path.resolve(repoRoot);
  const vdir = videoDir(root, videoSlug);
  const timelinePath = path.join(vdir, 'scenes', 'timeline.json');
  const pathsPath = path.join(vdir, 'montage', 'paths.json');
  const voicePath = path.join(vdir, 'audio', 'voice.json');

  const timeline = readJson<Timeline>(mustExist(timelinePath, 'timeline.json'));
  const paths = readJson<PathsManifest>(mustExist(pathsPath, 'montage/paths.json'));
  const voice = readJson<VoiceJson>(mustExist(voicePath, 'audio/voice.json'));

  if (!timeline.totalDuration || timeline.totalDuration <= 0) {
    throw new Error('timeline.totalDuration missing or invalid');
  }

  const slots = slotMap(paths);
  const voiceById = new Map(voice.segments.map((s) => [s.id, s]));
  const fps = timeline.fps || 30;
  const width = timeline.width || 1080;
  const height = timeline.height || 1920;
  const totalDurationSec = timeline.totalDuration;
  const durationInFrames = Math.max(1, Math.round(totalDurationSec * fps));

  const narrationPath = resolveSlotFile(
    root,
    vdir,
    slots,
    'audio/narration.wav',
    'narration',
  );

  const fallbackLayouts: string[] = [];
  const fallbackAnimations: string[] = [];
  const scenes: ResolvedScene[] = [];
  let assetCount = 1; // narration

  for (const scene of timeline.scenes) {
    let layout = scene.layout || 'full';
    if (!SUPPORTED_LAYOUTS.has(layout)) {
      fallbackLayouts.push(`${scene.id}:${layout}->full`);
      layout = 'full';
    }
    let animation = scene.animation || 'hardCut';
    if (!SUPPORTED_ANIMATIONS.has(animation)) {
      fallbackAnimations.push(`${scene.id}:${animation}->hardCut`);
      animation = 'hardCut';
    }

    const visualType = scene.visual?.type || 'MASCOT';
    let mascotPath: string | null = null;
    let mediaPath: string | null = null;
    let mediaKind: 'photo' | 'graphic' | 'none' = 'none';

    if (visualType === 'MASCOT' || scene.visual?.asset?.startsWith('mascot-')) {
      mascotPath = resolveSlotFile(
        root,
        vdir,
        slots,
        `mascot/${scene.id}.png`,
        `mascot ${scene.id}`,
      );
      assetCount += 1;
    }

    const supportId = scene.visual?.supportingAsset;
    if (supportId) {
      if (supportingIsGraphic(supportId) || visualType === 'STAT' || visualType === 'TEXT') {
        mediaPath = resolveSlotFile(
          root,
          vdir,
          slots,
          `graphics/${scene.id}.png`,
          `graphic ${scene.id}`,
        );
        mediaKind = 'graphic';
      } else {
        // Photo: resolve via paths.json source (local only, no network)
        const photoSlots = [...slots.entries()].filter(([slot]) =>
          slot.startsWith('photos/'),
        );
        let found: string | null = null;
        for (const [slot, item] of photoSlots) {
          // Prefer slot whose source path or provenance mentions asset id, or generic mapping
          const source = item.source || '';
          if (
            source.includes(supportId) ||
            slot.includes(supportId.replace(/^player-/, '')) ||
            (supportId.includes('switzerland') && slot.includes('switzerland')) ||
            (supportId.includes('sunderland') && slot.includes('sunderland'))
          ) {
            found = resolveSlotFile(root, vdir, slots, slot, `photo ${supportId}`);
            break;
          }
        }
        if (!found) {
          // Fallback: prepared-assets path if present in paths sources containing supportId
          for (const item of paths.items) {
            if (item.source && item.source.includes(supportId)) {
              found = mustExist(
                resolveRepoPath(root, item.source),
                `photo ${supportId}`,
              );
              break;
            }
          }
        }
        if (!found) {
          throw new Error(
            `MISSING_ASSET photo for supportingAsset=${supportId} in ${scene.id}. ` +
              'Local third-party photo required before Remotion render (no network fetch).',
          );
        }
        mediaPath = found;
        mediaKind = 'photo';
      }
      assetCount += 1;
    } else if (visualType === 'STAT' || visualType === 'TEXT') {
      mediaPath = resolveSlotFile(
        root,
        vdir,
        slots,
        `graphics/${scene.id}.png`,
        `graphic ${scene.id}`,
      );
      mediaKind = 'graphic';
      assetCount += 1;
    }

    scenes.push({
      id: scene.id,
      startSec: scene.start,
      durationSec: scene.duration,
      layout,
      animation,
      overlayText: scene.overlay?.text ?? null,
      mascotPath,
      mediaPath,
      mediaKind,
      captions: captionsForScene(scene, voiceById),
    });
  }

  return {
    videoSlug,
    repoRoot: root,
    fps,
    width,
    height,
    durationInFrames,
    totalDurationSec,
    narrationPath,
    scenes,
    assetCount,
    fallbacks: {
      layouts: fallbackLayouts,
      animations: fallbackAnimations,
    },
  };
}
