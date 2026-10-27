/* Compile trusted repository JSX and evaluate synthetic states, without a DOM,
   network, Homarr credentials, React effects or production application code. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { transformSync } = require('../tests/homarr-render/node_modules/esbuild');
const root = path.resolve(__dirname, '../examples/integrations');
const variants = [
  ['oldest-waiting', 'oldest-waiting', null],
  ['movies-leaving-soon', 'leaving-soon', 'Movies'],
  ['tv-leaving-soon', 'leaving-soon', 'TV'],
];
const components = ['Stack', 'Text', 'Group', 'Anchor', 'Image'];
function h(type, props, ...children) {
  return {type, props: props || {}, children: children.flat(Infinity).filter(x => x !== null && x !== false && x !== undefined)};
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...tree.children.flatMap(nodes)];
}
function text(tree) {
  return typeof tree === 'object' ? tree.children.map(text).join('') : String(tree ?? '');
}
let checks = 0;
for (const [name, view, library] of variants) {
  const source = fs.readFileSync(path.join(root, `homarr-${name}-compact-template.example.jsx`), 'utf8');
  const compiled = transformSync(source, {loader: 'jsx', jsxFactory: 'h', target: 'es2020'}).code;
  const run = new Function('h', ...components, 'data', 'status', `return ${compiled}`);
  const render = (titles, status = {ok: true, loading: false}) => run(h, ...components, {titles}, {titles: status});
  const items = Array.from({length: 12}, (_, i) => ({
    title: `Fixture title ${i + 1}`, library: library || (i % 2 ? 'TV' : 'Movies'),
    stage: view === 'oldest-waiting' ? 'waiting' : 'holding',
    since: '2026-12-10T11:30:59.123', estimated_removal_stage_at: '2026-12-17T11:30:59.123',
    poster_url: i === 1 || i === 3 ? null : 'http://fixture.invalid/poster.png',
    jellyfin_url: i === 2 || i === 3 ? null : 'http://fixture.invalid/jellyfin',
  }));
  const data = {schema_version: 1, status: 'advisory_only', view, items, total_records: 12, truncated: true};
  if (library) data.library_filter = library;
  const tree = render(data);
  const all = nodes(tree); const displayed = text(tree);
  assert(displayed.includes('Fixture title 10') && !displayed.includes('Fixture title 11'));
  assert(displayed.includes(view === 'oldest-waiting' ? '12/10/2026 11:30' : '12/17/2026 11:30'));
  assert(displayed.includes('Showing 10 of 12 tracking records.'));
  const anchors = all.filter(x => x.type === 'Anchor');
  assert.equal(anchors.length, 7);
  assert(anchors.every(x => x.children.length === 1 && x.children[0].type === 'Image'));
  assert(!displayed.includes('Open in Jellyfin'));
  for (const state of [{ok: false, loading: false}, {ok: true, loading: true}]) {
    const unavailable = text(render(data, state));
    assert(!unavailable.includes('Fixture title') && !unavailable.includes('Showing 10'));
  }
  assert(text(render({...data, schema_version: 99})).includes('unavailable'));
  assert(text(render({...data, items: null})).includes('unavailable'));
  assert(!text(render({...data, items: []})).includes('Fixture title'));
  if (library) assert(text(render({...data, library_filter: library === 'TV' ? 'Movies' : 'TV'})).includes('unavailable'));
  const missing = structuredClone(data); missing.items[0].since = null; missing.items[0].estimated_removal_stage_at = null;
  assert(text(render(missing)).includes('Date unavailable'));
  checks += 1;
}
console.log(JSON.stringify({status: 'compact_templates_render_verified', variants: checks,
  verification_scope: 'jsx_compilation_and_synthetic_render_tree', homarr_visual_rendering_verified: false,
  network_collection_performed: false, production_changes_performed: false}));
