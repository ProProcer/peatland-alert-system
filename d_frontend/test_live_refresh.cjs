const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/live-refresh.js', 'utf8');

async function scenario({ fail = false, conflict = false, disabled = false } = {}) {
  const controls = { hidden: true };
  const button = { addEventListener(_, callback) { this.click = callback; } };
  const message = {};
  const calls = [], events = [];
  let statusCalls = 0;
  const context = {
    document: { querySelector: selector => ({ '#live-refresh-controls': controls, '#live-refresh': button, '#live-refresh-status': message })[selector] },
    window: { dispatchEvent: event => events.push(event.type) },
    Event: class { constructor(type) { this.type = type; } },
    setTimeout: callback => callback(), Date,
    fetch: async (url, options) => {
      calls.push([url, options]);
      if (url === '/live/refresh') return { ok: !conflict, status: conflict ? 409 : 202, json: async () => ({ state: 'queued', error: 'Already running' }) };
      statusCalls++;
      return { ok: true, json: async () => disabled ? { state: 'disabled' } : statusCalls <= 2
        ? { state: 'ready', completed_at: 'before' }
        : fail ? { state: 'error', failed_at: 'new', error: 'Provider unavailable' }
        : { state: 'ready', completed_at: 'after' } };
    }
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(controls.hidden, disabled);
  if (disabled) return;
  await button.click();
  assert.equal(button.disabled, false);
  assert.equal(calls.find(([url]) => url === '/live/refresh')[1].method, 'POST');
  assert.deepEqual(events, fail ? [] : ['refresh-dashboard']);
  assert.match(message.textContent, fail ? /Provider unavailable/ : /Live data updated/);
}
(async () => {
  await scenario();
  await scenario({ conflict: true });
  await scenario({ fail: true });
  await scenario({ disabled: true });
  console.log('PASS: manual refresh requests ingestion, waits for completion, handles concurrent runs and errors, and stays hidden in demo mode.');
})().catch(error => { console.error(error); process.exitCode = 1; });
