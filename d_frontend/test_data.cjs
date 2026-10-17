const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/app.js', 'utf8');
const entries = Object.entries({ features: 'features.json', cells: 'cells.geojson', risk: 'risk.json', dispatch: 'dispatch.json' }).map(([kind, file]) => [kind, { data: JSON.parse(fs.readFileSync(__dirname + '/mocks/' + file, 'utf8')) }]);
let requests = [];
const context = {
  fetch: async url => { requests.push(url); return { ok: true, json: async () => [] }; },
};
vm.createContext(context);
context.project = ([lon, lat]) => [256 * 64 * (lon + 180) / 360, 256 * 64 * (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2];
vm.runInContext(source.slice(source.indexOf('function polygonPath('), source.indexOf('async function loadPeatland(')), context);
const peat = JSON.parse(fs.readFileSync(__dirname + '/assets/peatland.geojson', 'utf8'));
for (const feature of peat.features) {
  context.geometry = feature.geometry;
  const paths = vm.runInContext('peatGeometryPaths(geometry)', context);
  assert(paths.length > 0, 'Every peat feature must produce a visible path');
  assert(paths.every(path => path.startsWith('M') && !/NaN|undefined|Infinity/.test(path)));
}
context.geometry = { type: 'GeometryCollection', geometries: [peat.features[0].geometry, { type: 'LineString', coordinates: [[114, -2], [115, -2]] }] };
assert(vm.runInContext('peatGeometryPaths(geometry).length', context) > 0, 'Collections must retain polygon parts');
console.log(`PASS: ${peat.features.length} actual peat features produce finite SVG paths; mixed geometry collections supported.`);
vm.runInContext(source.slice(source.indexOf('async function loadFeed('), source.indexOf('function render()')), context);
context.entries = entries;
vm.runInContext('validateFeedSet(entries)', context);
const bad = structuredClone(entries);
bad.find(([key]) => key === 'risk')[1].data[0].ts = '2026-10-15T00:00:00Z';
context.entries = bad;
assert.throws(() => vm.runInContext('validateFeedSet(entries)', context), /snapshot/);
(async () => {
  context.dataset = { base: '/demo/replay/', files: ['features.json', 'cells.geojson'] };
  const missing = await vm.runInContext("loadFeed('risk.json', dataset)", context);
  assert.equal(missing.data.length, 0);
  assert.equal(missing.url, null);
  assert.equal(requests.length, 0, 'Missing predictions must not request mocks');
  await vm.runInContext("loadFeed('features.json', dataset)", context);
  assert.deepEqual(requests, ['/demo/replay/features.json']);
  context.fetch = async () => ({ ok: false, status: 500 });
  await assert.rejects(vm.runInContext("loadFeed('features.json', dataset)", context), /HTTP 500/);
  await assert.rejects(vm.runInContext("loadFeed('features.json', null)", context), /33-cell dataset/);
  const select = { children: [], replaceChildren() { this.children = []; }, append(node) { this.children.push(node); } };
  context.document = { querySelector: () => select };
  context.element = (_, text) => ({ textContent: text });
  context.fetch = async () => ({ ok: true, json: async () => ({ datasets: [{ id: 'real', label: '9 cells' }, { id: 'coverage', label: '33 cells' }, { id: 'mock', label: 'Mock' }] }) });
  await vm.runInContext('discoverDatasets()', context);
  assert.equal(select.children.length, 1);
  assert.equal(select.value, 'coverage');
  assert.equal(select.disabled, true);
  const snapshot = JSON.parse(fs.readFileSync(__dirname + '/assets/coverage-snapshot.json', 'utf8'));
  const paths = [];
  context.fetch = async url => {
    paths.push(url);
    return url === '/demo/catalog.json' ? { ok: false, status: 404 } : { ok: true, json: async () => snapshot };
  };
  await vm.runInContext('discoverDatasets()', context);
  assert.equal(context.activeDataset.id, 'coverage');
  const bundledCells = await vm.runInContext("loadFeed('cells.geojson', activeDataset)", context);
  const bundledRisk = await vm.runInContext("loadFeed('risk.json', activeDataset)", context);
  assert.equal(bundledCells.data.features.length, 33);
  assert.equal(bundledRisk.data.length, 99);
  assert.deepEqual(paths, ['/demo/catalog.json', 'assets/coverage-snapshot.json']);
  for (const [filename, payload] of Object.entries(snapshot.feeds)) assert.deepEqual(payload, JSON.parse(fs.readFileSync(__dirname + '/../data/demo/central_coverage/' + filename, 'utf8')));
  console.log('PASS: plain static-server fallback loads the exact real 33-cell snapshot and 99 predictions, without mock data.');
  console.log('PASS: interface exposes only the 33-cell coverage dataset and never falls back to mocks.');
  console.log('PASS: matched snapshots, rejection of mixed data, missing outputs, isolated dataset requests and failure handling.');
})().catch(error => { console.error(error); process.exitCode = 1; });
