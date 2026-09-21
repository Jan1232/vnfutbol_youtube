#!/usr/bin/env node
/**
 * Plain JS port of remotion/src/lib/loadBundle.ts for Node CLI (no TS loader required).
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

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

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function mustExist(filePath, label) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    throw new Error(`MISSING_ASSET ${label}: ${filePath}`);
  }
  return path.resolve(filePath);
}

function resolveRepoPath(repoRoot, relOrAbs) {
  if (path.isAbsolute(relOrAbs)) return path.resolve(relOrAbs);
  return path.resolve(repoRoot, relOrAbs);
}

function resolveSlotFile(repoRoot, videoRoot, slots, slot, label) {
  const item = slots.get(slot);
  const candidates = [];
  if (item?.source) candidates.push(resolveRepoPath(repoRoot, item.source));
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

function chunkPhrase(text, minWords = 2, maxWords = 6) {
  const words = text.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  if (!words.length) return [];
  const chunks = [];
  let i = 0;
  while (i < words.length) {
    const remaining = words.length - i;
    let take = Math.min(maxWords, remaining);
    if (remaining > maxWords && remaining - maxWords < minWords) {
      take = Math.max(minWords, remaining - minWords);
    }
    if (take < minWords && remaining >= minWords) take = minWords;
    chunks.push(words.slice(i, i + take).join(' '));
    i += take;
  }
  return chunks;
}

function captionsForScene(scene, voiceById) {
  const chunks = [];
  for (const id of scene.voiceIds || []) {
    const seg = voiceById.get(id);
    if (!seg) continue;
    const text = (seg.text || seg.ttsText || '').trim();
    if (!text) continue;
    const startSec = (seg.startMs ?? scene.start * 1000) / 1000;
    const endSec = (seg.endMs ?? (scene.start + scene.duration) * 1000) / 1000;
    const phrases = chunkPhrase(text);
    if (!phrases.length) continue;
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

function supportingIsGraphic(assetId) {
  if (!assetId) return false;
  return (
    assetId.startsWith('stat-') ||
    assetId.startsWith('text-') ||
    assetId.startsWith('news-') ||
    assetId.startsWith('map-')
  );
}

export function loadShortsBundleJs(repoRoot, videoSlug) {
  const root = path.resolve(repoRoot);
  const vdir = path.join(root, 'videos', videoSlug);
  const timeline = readJson(mustExist(path.join(vdir, 'scenes', 'timeline.json'), 'timeline.json'));
  const paths = readJson(mustExist(path.join(vdir, 'montage', 'paths.json'), 'montage/paths.json'));
  const voice = readJson(mustExist(path.join(vdir, 'audio', 'voice.json'), 'audio/voice.json'));

  if (!timeline.totalDuration || timeline.totalDuration <= 0) {
    throw new Error('timeline.totalDuration missing or invalid');
  }

  const slots = new Map(paths.items.map((item) => [item.slot.replace(/\\/g, '/'), item]));
  const voiceById = new Map(voice.segments.map((s) => [s.id, s]));
  const fps = timeline.fps || 30;
  const width = timeline.width || 1080;
  const height = timeline.height || 1920;
  const totalDurationSec = timeline.totalDuration;
  const durationInFrames = Math.max(1, Math.round(totalDurationSec * fps));
  const narrationPath = resolveSlotFile(root, vdir, slots, 'audio/narration.wav', 'narration');

  const fallbackLayouts = [];
  const fallbackAnimations = [];
  const scenes = [];
  let assetCount = 1;

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
    let mascotPath = null;
    let mediaPath = null;
    let mediaKind = 'none';

    if (visualType === 'MASCOT' || scene.visual?.asset?.startsWith('mascot-')) {
      mascotPath = resolveSlotFile(root, vdir, slots, `mascot/${scene.id}.png`, `mascot ${scene.id}`);
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
        let found = null;
        for (const [slot, item] of slots.entries()) {
          if (!slot.startsWith('photos/')) continue;
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
          for (const item of paths.items) {
            if (item.source && item.source.includes(supportId)) {
              found = mustExist(resolveRepoPath(root, item.source), `photo ${supportId}`);
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
    fallbacks: {layouts: fallbackLayouts, animations: fallbackAnimations},
  };
}
