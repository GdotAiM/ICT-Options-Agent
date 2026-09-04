#!/usr/bin/env node
/**
 * archify-diagrams.mjs — Automated architecture diagram generator
 *
 * Regenerates all 4 interactive HTML diagrams from JSON specs.
 *
 * Usage:
 *   node archify-diagrams.mjs              # regenerate all diagrams
 *   node archify-diagrams.mjs --validate   # validate specs only
 */

import { spawnSync } from 'child_process';
import { readdirSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const PROJECT_ROOT = dirname(__filename);
const DIAGRAMS_DIR = join(PROJECT_ROOT, 'docs', 'diagrams');
const ARCHIFY = join(process.env.HOME || '', '.claude', 'skills', 'archify', 'bin', 'archify.mjs');

// ── Ensure diagrams dir exists ────────────────────────────────────────────────
if (!existsSync(DIAGRAMS_DIR)) {
  mkdirSync(DIAGRAMS_DIR, { recursive: true });
  console.log(`Created ${DIAGRAMS_DIR}`);
}

// ── Diagram specs (hand-authored, source of truth) ───────────────────────────
const DIAGRAMS = [
  { name: 'agent-architecture', type: 'architecture', quality: 'showcase' },
  { name: 'agent-workflow',     type: 'workflow',     quality: 'showcase' },
  { name: 'agent-sequence',     type: 'sequence',     quality: 'showcase' },
  { name: 'agent-dataflow',     type: 'dataflow',     quality: 'standard' },
];

function run(cmd, args) {
  const result = spawnSync('node', [ARCHIFY, cmd, ...args], {
    encoding: 'utf8',
    cwd: PROJECT_ROOT,
    stdio: ['pipe', 'pipe', 'pipe']
  });
  try { return JSON.parse(result.stdout); }
  catch { return { ok: false, raw: result.stdout }; }
}

// ── Main ─────────────────────────────────────────────────────────────────────
const validateOnly = process.argv.includes('--validate');

let pass = 0, fail = 0;

for (const { name, type, quality } of DIAGRAMS) {
  const jsonPath = join(DIAGRAMS_DIR, `${name}.json`);
  const htmlPath = join(DIAGRAMS_DIR, `${name}.html`);

  if (!existsSync(jsonPath)) {
    console.error(`  [SKIP] ${name} — spec not found: ${jsonPath}`);
    fail++;
    continue;
  }

  const subcmd = validateOnly ? 'validate' : 'deliver';
  const args = [type, jsonPath];
  if (!validateOnly) args.push(htmlPath);
  args.push('--quality', quality, '--json');

  const result = run(subcmd, args);
  const errs = result.diagnostics?.filter(d => d.severity === 'error')?.length ?? 0;

  if (result.ok && errs === 0) {
    const size = validateOnly ? '' : ` | ${(result.artifactBytes ?? 0).toLocaleString()}B`;
    console.log(`  [PASS] ${name}.html${size}`);
    pass++;
  } else {
    console.log(`  [FAIL] ${name} (${errs} errors)`);
    fail++;
  }
}

console.log(`\n${pass}/${pass + fail} diagrams ${validateOnly ? 'validated' : 'generated'} successfully.`);
if (fail > 0) process.exit(1);
