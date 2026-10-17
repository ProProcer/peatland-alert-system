const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const feeds = JSON.parse(fs.readFileSync(__dirname + '/assets/coverage-snapshot.json', 'utf8')).feeds;
class Element {
  constructor(tag, text, className) { Object.assign(this, {tag, textContent: text, className, children: [], style: {setProperty() {}}}); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
}
const nodes = new Map();
const context = {
  records: feeds['dispatch.json'], snapshot: {risk: feeds['risk.json']}, titles: {}, Intl, Date,
  $: id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); },
  el: (tag, text, cls) => new Element(tag, text, cls),
  timeline: () => context.records,
};
vm.createContext(context);
const source = fs.readFileSync(__dirname + '/response.js', 'utf8');
assert(source.includes('id="timeline-count"'), "Timeline event counter must exist in the rendered markup");
vm.runInContext(source.slice(source.indexOf('  function renderTimeline(){'), source.indexOf('  function renderList(){')), context);
const flatten = node => [node, ...node.children.flatMap(flatten)];
context.renderTimeline();
let output = flatten(nodes.get('response-timeline'));
assert.equal(output.filter(node => node.className === 'timeline-card').length, context.records.length);
assert.equal(output.filter(node => node.className?.startsWith('timeline-risk ')).length, context.records.length);
assert(output.filter(node => node.tag === 'time').every(node => node.textContent.includes('UTC')));
assert(output.filter(node => node.className === 'timeline-view').every(node => typeof node.onclick === 'function'));
context.snapshot.risk = [];
context.renderTimeline();
output = flatten(nodes.get('response-timeline'));
assert(output.filter(node => node.className?.startsWith('timeline-risk ')).every(node => node.textContent === 'Risk unavailable'));
context.records = [];
context.renderTimeline();
assert(nodes.get('response-timeline').children[0].textContent.includes('No incidents'));
console.log('PASS: timeline cards, risk indicators, UTC labels, response links and missing/empty states.');
