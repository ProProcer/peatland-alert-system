// Exercise the actual SVG renderer without network requests or changed data files.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.clientWidth = 900; this.clientHeight = 650; }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === 'id') nodes.set('#' + value, this);
    if (key === 'data-cell-width') this.dataset.cellWidth = value;
  }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  addEventListener() {}
  querySelectorAll(selector) { return this.children.flatMap(child => [child, ...child.querySelectorAll(selector)]).filter(child => '.' + child.attrs.class === selector); }
}
for (const id of ['#map', '#map-detail', '#map-tile-status']) nodes.set(id, new Node('div'));
const document = {
  querySelector: selector => nodes.get(selector),
  querySelectorAll: selector => nodes.get('#map').querySelectorAll(selector),
  createElementNS: (_, tag) => new Node(tag),
};
const context = { document, window: { devicePixelRatio: 1 }, clearTimeout() {}, setTimeout() {} };
vm.createContext(context);
const source = fs.readFileSync(__dirname + '/app.js', 'utf8');
vm.runInContext(source.slice(0, source.indexOf('const mapElement =')), context);
const mock = Object.fromEntries(Object.entries({ features: 'features.json', cells: 'cells.geojson', risk: 'risk.json' }).map(([kind, filename]) => [kind, { data: JSON.parse(fs.readFileSync(__dirname + '/mocks/' + filename, 'utf8')) }]));
const peat = JSON.parse(fs.readFileSync(__dirname + '/assets/peatland.geojson', 'utf8'));
context.testFeeds = mock;
context.testPeat = peat;
vm.runInContext('feeds = testFeeds; peatlandPaths = testPeat.features.flatMap(f => peatGeometryPaths(f.geometry)); provincePaths = peatGeometryPaths(testPeat.scope_boundary);', context);
const palette = { LOW: '#32945b', MODERATE: '#e9c643', HIGH: '#e78b38', CRITICAL: '#d64b57' };
function check(horizon) {
  vm.runInContext(`renderMap(${horizon})`, context);
  const rendered = nodes.get('#map').querySelectorAll('.map-cell');
  for (const cell of rendered) {
    const id = cell.attrs['aria-label'].split(':')[0];
    const risk = context.testFeeds.risk.data.find(row => row.cell_id === id && row.horizon_h === horizon);
    assert.equal(cell.attrs.fill, risk ? palette[risk.risk_level] : '#bdcdb8');
  }
  const layer = nodes.get('#map').children.find(node => node.attrs['clip-path'] === 'url(#peatland-clip)');
  assert.equal(layer.attrs['clip-path'], 'url(#peatland-clip)', 'Risk fills must stay inside mapped peat');
  assert.equal(nodes.get('#map-tiles').attrs['clip-path'], undefined, 'Grayscale context must remain visible beyond peatland');
  assert.equal(nodes.get('#map').children.at(-1).attrs.class, 'province-boundary', 'Province border must stay above the clipped map layers');
  return rendered;
}
assert(check(24).some(cell => cell.attrs.fill === palette.HIGH), 'HIGH must render orange');
assert(check(48).some(cell => cell.attrs.fill === palette.CRITICAL), 'Changing horizon must update CRITICAL to red');
check(72);
for (const [level, score] of [['LOW', .34], ['MODERATE', .35], ['HIGH', .6], ['CRITICAL', .8]]) {
  context.testFeeds.risk.data = [{ ...mock.risk.data[0], cell_id: mock.features.data[0].cell_id, horizon_h: 24, risk_level: level, risk_score: score }];
  assert.equal(check(24)[0].attrs.fill, palette[level]);
}
context.testFeeds.risk.data = [];
assert(check(24).every(cell => cell.attrs.fill === '#bdcdb8'), 'Missing predictions must not show a risk color');
context.testFeeds = {
  features: { data: JSON.parse(fs.readFileSync(__dirname + '/../data/demo/role_a_replay/features.json', 'utf8')) },
  cells: { data: JSON.parse(fs.readFileSync(__dirname + '/../data/demo/role_a_replay/cells.geojson', 'utf8')) },
  risk: { data: [] },
};
vm.runInContext('feeds = testFeeds; renderMap(48)', context);
const centers = nodes.get('#map').children.find(node => node.attrs.class === 'cell-centers');
assert.equal(centers.attrs['clip-path'], undefined, 'Center markers must not be clipped to peat');
assert.equal(centers.children.length, 33, 'All 33 actual replay centers must be rendered');
assert(centers.children.every(marker => marker.attrs.role === 'button' && marker.attrs.tabindex === '0'));
console.log('PASS: all 33 replay center markers render outside the peat clip with keyboard access.');
const coverageFolder = __dirname + '/../data/demo/central_coverage/';
if (fs.existsSync(coverageFolder + 'risk.json')) {
  context.testFeeds = Object.fromEntries(Object.entries({ features: 'features.json', cells: 'cells.geojson', risk: 'risk.json' }).map(([kind, file]) => [kind, { data: JSON.parse(fs.readFileSync(coverageFolder + file, 'utf8')) }]));
  vm.runInContext('feeds = testFeeds', context);
  for (const horizon of [24, 48, 72]) assert.equal(check(horizon).length, 33);
  assert.equal(context.testFeeds.risk.data.length, 99);
  console.log('PASS: all 33 spread-out cells render the matching risk color across all 99 predictions.');
}
console.log('PASS: actual map renderer uses orange for HIGH, red for CRITICAL, updates all horizons, clips fills to peatland, and leaves missing predictions neutral.');
