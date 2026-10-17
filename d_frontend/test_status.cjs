const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Node {
  constructor() { this.children = []; this.style = {}; this.attrs = {}; this.textContent = ''; this.events = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
  scrollIntoView() {}
}
const nodes = new Map();
const context = { document: { querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, new Node()); return nodes.get(selector); } }, element(tag, text) { const node = new Node(); node.textContent = text; return node; }, activeDataset: { id: 'coverage' }, window: { matchMedia: () => ({ matches: false }) }, MouseEvent: class { constructor(type) { this.type = type; } } };
const folder = __dirname + '/../data/demo/central_coverage/';
context.feeds = Object.fromEntries(Object.entries({ features: 'features.json', cells: 'cells.geojson', risk: 'risk.json', dispatch: 'dispatch.json' }).map(([kind, file]) => [kind, { data: JSON.parse(fs.readFileSync(folder + file, 'utf8')) }]));
vm.createContext(context);
const source = fs.readFileSync(__dirname + '/app.js', 'utf8');
vm.runInContext(source.slice(source.indexOf('function renderStatus('), source.indexOf('function render()')), context);
for (const horizon of [24, 48, 72]) {
  vm.runInContext(`renderStatus(${horizon})`, context);
  const rows = context.feeds.risk.data.filter(row => row.horizon_h === horizon);
  for (const level of ['LOW', 'MODERATE', 'HIGH', 'CRITICAL']) assert.equal(nodes.get('#count-' + level.toLowerCase()).textContent, rows.filter(row => row.risk_level === level).length);
  assert.equal(nodes.get('#priority-list').children.length, 3);
  assert(nodes.get('#snapshot-time').textContent.includes('07:00 WIB'));
  const top = [...rows].sort((a, b) => b.risk_score - a.risk_score || a.cell_id.localeCompare(b.cell_id))[0];
  let selected = false, focused = false;
  context.document.querySelectorAll = () => [{ dataset: { cellId: top.cell_id }, dispatchEvent() { selected = true; }, focus() { focused = true; } }];
  nodes.get('#priority-list').children[0].events.click();
  assert(selected && focused, 'Watchlist must activate and focus the matching map center');
}
context.feeds.risk.data = [];
for (const row of context.feeds.features.data) { row.weather.sm_27_81 = null; row.derived.rain_24h_mm = null; }
vm.runInContext('renderStatus(48)', context);
assert.equal(nodes.get('#count-high').textContent, '—');
assert(nodes.get('#priority-list').children[0].textContent.includes('No predictions'));
console.log('PASS: status counts and watchlist update for all horizons; snapshot display uses WIB; missing forecasts are not shown as zero.');
