#!/usr/bin/env node
import * as fs from 'node:fs';
import * as path from 'node:path';
import {spawnSync} from 'node:child_process';
import {loadShortsBundleJs} from './load-bundle.mjs';

function ensureLinkOrCopy(src, dest) {
  fs.mkdirSync(path.dirname(dest), {recursive: true});
  if (fs.existsSync(dest)) fs.rmSync(dest);
  try {
    fs.linkSync(src, dest);
  } catch {
    fs.copyFileSync(src, dest);
  }
}

function toPublicRel(slug, kind, name) {
  return path.posix.join('shorts-draft', slug, kind, name);
}

function stageBundle(repoRoot, bundle) {
  const slug = bundle.videoSlug;
  const publicRoot = path.join(repoRoot, 'public', 'shorts-draft', slug);
  if (fs.existsSync(publicRoot)) {
    fs.rmSync(publicRoot, {recursive: true, force: true});
  }

  const staged = structuredClone(bundle);
  const narrName = 'narration' + path.extname(bundle.narrationPath);
  const narrPublic = toPublicRel(slug, 'audio', narrName);
  ensureLinkOrCopy(bundle.narrationPath, path.join(repoRoot, 'public', narrPublic));
  staged.narrationPath = narrPublic;

  for (const scene of staged.scenes) {
    if (scene.mascotPath) {
      const name = `${scene.id}.png`;
      const rel = toPublicRel(slug, 'mascot', name);
      ensureLinkOrCopy(scene.mascotPath, path.join(repoRoot, 'public', rel));
      scene.mascotPath = rel;
    }
    if (scene.mediaPath) {
      const ext = path.extname(scene.mediaPath) || '.png';
      const name = `${scene.id}${ext}`;
      const kind = scene.mediaKind === 'graphic' ? 'graphics' : 'photos';
      const rel = toPublicRel(slug, kind, name);
      ensureLinkOrCopy(scene.mediaPath, path.join(repoRoot, 'public', rel));
      scene.mediaPath = rel;
    }
  }
  return staged;
}

const slug = process.argv[2];
const outName = process.argv[3] || 'draft-v1.mp4';
if (!slug) {
  console.error('Usage: node remotion/scripts/render-draft.mjs <video-slug> [output-name]');
  process.exit(2);
}

const repoRoot = path.resolve(process.cwd());
const entry = path.join(repoRoot, 'remotion', 'src', 'index.ts');
const outDir = path.join(repoRoot, 'videos', slug, 'renders');
fs.mkdirSync(outDir, {recursive: true});
const outPath = path.join(outDir, outName);
const propsPath = path.join(outDir, `${path.parse(outName).name}.props.json`);
const metaPath = path.join(outDir, `${path.parse(outName).name}.meta.json`);

const loaded = loadShortsBundleJs(repoRoot, slug);
const bundle = stageBundle(repoRoot, loaded);
const props = {videoSlug: slug, repoRoot, bundle};
fs.writeFileSync(propsPath, JSON.stringify(props), 'utf8');
fs.writeFileSync(
  metaPath,
  JSON.stringify(
    {
      videoSlug: slug,
      composition: 'ShortsDraft',
      output: path.relative(repoRoot, outPath).replace(/\\/g, '/'),
      totalDurationSec: bundle.totalDurationSec,
      durationInFrames: bundle.durationInFrames,
      fps: bundle.fps,
      width: bundle.width,
      height: bundle.height,
      assetCount: loaded.assetCount,
      captions: true,
      fallbacks: bundle.fallbacks,
      publicStaging: `public/shorts-draft/${slug}`,
    },
    null,
    2,
  ),
  'utf8',
);

console.log(
  `BUNDLE scenes=${bundle.scenes.length} assets=${loaded.assetCount} duration=${bundle.totalDurationSec}s frames=${bundle.durationInFrames}`,
);
if (bundle.fallbacks.layouts.length || bundle.fallbacks.animations.length) {
  console.log('FALLBACKS', JSON.stringify(bundle.fallbacks));
}

const remotionCli = path.join(repoRoot, 'node_modules', '@remotion', 'cli', 'remotion-cli.js');
const result = spawnSync(
  process.execPath,
  [
    remotionCli,
    'render',
    entry,
    'ShortsDraft',
    outPath,
    '--props',
    propsPath,
    '--codec',
    'h264',
    '--image-format',
    'jpeg',
    '--overwrite',
  ],
  {stdio: 'inherit', cwd: repoRoot},
);
if (result.status !== 0) process.exit(result.status || 1);
console.log(`OK render ${outPath}`);
