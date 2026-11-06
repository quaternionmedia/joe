// Every spec is a step of its lane, and every step names what checks it.
//
// A lane is a page under docs/paths/, and a spec belongs to the lane whose
// tag it carries (`@music-page` for docs/paths/music-page.md). A step names
// what checks it on lines of its own:
//
//   - spec: <a Playwright spec's whole title>
//   - test: tests/<file>.py::<test function>
//
// The check fails when a spec carries no lane or two, when two specs share a
// title, when a page names a spec or test that does not exist or a spec of
// another lane, and when a spec is not named on its lane's page exactly once.
// `npm run check:paths` runs it.

import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(fileURLToPath(import.meta.url), '..', '..', '..');
const pages = join(root, 'docs', 'paths');

function listedSpecs() {
  const out = execFileSync(process.execPath,
    [join(root, 'node_modules', '@playwright', 'test', 'cli.js'), 'test', '--list', '--reporter=json'],
    { cwd: root, encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 });
  const specs = [];
  const walk = suite => {
    for (const spec of suite.specs || []) {
      specs.push({ title: spec.title, tags: spec.tags || [], at: `${spec.file}:${spec.line}` });
    }
    for (const inner of suite.suites || []) walk(inner);
  };
  for (const suite of JSON.parse(out).suites) walk(suite);
  return specs;
}

export function check({ specs, lanes, read = name => readFileSync(join(root, name), 'utf-8'), exists = name => existsSync(join(root, name)) }) {
  const problems = [];
  const laneTags = new Map(Object.keys(lanes).map(lane => [`@${lane}`, lane]));
  const byTitle = new Map();
  for (const spec of specs) {
    const own = spec.tags.map(tag => tag.startsWith('@') ? tag : `@${tag}`).filter(tag => laneTags.has(tag));
    if (own.length !== 1) {
      problems.push(`${spec.at} "${spec.title}" carries ${own.length ? 'two lanes' : 'no lane'}: ${[...laneTags.keys()].join(', ')}`);
      continue;
    }
    if (byTitle.has(spec.title)) {
      problems.push(`${spec.at} "${spec.title}" has the title of ${byTitle.get(spec.title).at}: a page names a spec by its title`);
      continue;
    }
    byTitle.set(spec.title, { ...spec, lane: laneTags.get(own[0]), named: 0 });
  }

  for (const [lane, text] of Object.entries(lanes)) {
    text.split('\n').forEach((line, i) => {
      const m = line.match(/^\s*- (spec|test): (.+?)\s*$/);
      if (!m) return;
      const where = `docs/paths/${lane}.md:${i + 1}`;
      if (m[1] === 'spec') {
        const spec = byTitle.get(m[2]);
        if (!spec) problems.push(`${where} names a spec there is none of: "${m[2]}"`);
        else if (spec.lane !== lane) problems.push(`${where} names a spec of the ${spec.lane} lane: "${m[2]}"`);
        else spec.named += 1;
      } else {
        const [file, name] = m[2].split('::');
        if (!name || !exists(file)) problems.push(`${where} names a test file there is none of: ${m[2]}`);
        else if (!new RegExp(`^(async )?def ${name}\\(`, 'm').test(read(file))) problems.push(`${where} names a test there is none of: ${m[2]}`);
      }
    });
  }

  for (const spec of byTitle.values()) {
    if (spec.named === 0) problems.push(`${spec.at} "${spec.title}" is a step of no page: name it on docs/paths/${spec.lane}.md`);
    if (spec.named > 1) problems.push(`${spec.at} "${spec.title}" is named ${spec.named} times on docs/paths/${spec.lane}.md`);
  }
  return problems;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  // Every page but the index is a lane.
  const lanes = Object.fromEntries((existsSync(pages) ? readdirSync(pages) : [])
    .filter(f => f.endsWith('.md') && f !== 'README.md')
    .map(f => [f.slice(0, -3), readFileSync(join(pages, f), 'utf-8')]));
  const specs = listedSpecs();
  const problems = check({ specs, lanes });
  if (problems.length) {
    console.error(problems.join('\n'));
    console.error(`\n${problems.length} problem(s); docs/paths/README.md says how a step names its checks.`);
    process.exit(1);
  }
  console.log(`${specs.length} specs, each a step of one of ${Object.keys(lanes).length} lanes in docs/paths/`);
}
