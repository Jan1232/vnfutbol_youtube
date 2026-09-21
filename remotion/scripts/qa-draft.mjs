#!/usr/bin/env node
import * as fs from 'node:fs';
import * as path from 'node:path';
import {spawnSync} from 'node:child_process';

const slug = process.argv[2];
const outName = process.argv[3] || 'draft-v1.mp4';
if (!slug) {
  console.error('Usage: node remotion/scripts/qa-draft.mjs <video-slug> [output-name]');
  process.exit(2);
}

const repoRoot = path.resolve(process.cwd());
const outPath = path.join(repoRoot, 'videos', slug, 'renders', outName);
const timeline = JSON.parse(
  fs.readFileSync(path.join(repoRoot, 'videos', slug, 'scenes', 'timeline.json'), 'utf8'),
);
const metaPath = path.join(
  repoRoot,
  'videos',
  slug,
  'renders',
  `${path.parse(outName).name}.meta.json`,
);

const errors = [];
if (!fs.existsSync(outPath)) errors.push(`output missing: ${outPath}`);

let probe = null;
if (fs.existsSync(outPath)) {
  const ffprobe = spawnSync(
    'ffprobe',
    [
      '-v',
      'error',
      '-select_streams',
      'v:0',
      '-show_entries',
      'stream=width,height,r_frame_rate,avg_frame_rate',
      '-show_entries',
      'format=duration',
      '-of',
      'json',
      outPath,
    ],
    {encoding: 'utf8'},
  );
  if (ffprobe.status !== 0) {
    errors.push(`ffprobe failed: ${ffprobe.stderr || ffprobe.stdout}`);
  } else {
    probe = JSON.parse(ffprobe.stdout);
    const stream = (probe.streams || [])[0] || {};
    const width = Number(stream.width);
    const height = Number(stream.height);
    if (width !== 1080 || height !== 1920) {
      errors.push(`resolution ${width}x${height} != 1080x1920`);
    }
    const rate = stream.avg_frame_rate || stream.r_frame_rate || '0/1';
    const [a, b] = rate.split('/').map(Number);
    const fps = b ? a / b : Number(rate);
    if (Math.abs(fps - 30) > 0.51) errors.push(`fps ${fps} not ≈30`);
    const duration = Number(probe.format?.duration || 0);
    const expected = Number(timeline.totalDuration);
    if (Math.abs(duration - expected) > 0.2) {
      errors.push(`duration ${duration} not within ±0.2 of timeline ${expected}`);
    }
  }

  const audioProbe = spawnSync(
    'ffprobe',
    [
      '-v',
      'error',
      '-select_streams',
      'a:0',
      '-show_entries',
      'stream=codec_type',
      '-of',
      'csv=p=0',
      outPath,
    ],
    {encoding: 'utf8'},
  );
  if (audioProbe.status !== 0 || !String(audioProbe.stdout).includes('audio')) {
    errors.push('audio stream missing');
  }
}

if (fs.existsSync(metaPath)) {
  const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
  if (meta.fallbacks?.layouts?.length || meta.fallbacks?.animations?.length) {
    console.log('NOTE fallbacks', meta.fallbacks);
  }
}

if (errors.length) {
  console.error('QA FAIL');
  for (const e of errors) console.error(`- ${e}`);
  process.exit(1);
}

console.log('QA OK');
console.log(
  JSON.stringify(
    {
      output: path.relative(repoRoot, outPath).replace(/\\/g, '/'),
      expectedDuration: timeline.totalDuration,
      probeDuration: Number(probe?.format?.duration || 0),
      resolution: '1080x1920',
      fps: 30,
    },
    null,
    2,
  ),
);
