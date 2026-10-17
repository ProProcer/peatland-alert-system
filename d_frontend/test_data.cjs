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
  console.log('PASS: matched snapshots, rejection of mixed data, missing outputs, isolated dataset requests and failure handling.');
})().catch(error => { console.error(error); process.exitCode = 1; });
