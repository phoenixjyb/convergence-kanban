const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function createTracker() {
  const elements = new Map();
  const storage = new Map();
  const document = {
    addEventListener() {},
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', classList: {toggle() {}}});
      return elements.get(id);
    },
    querySelectorAll() { return []; }
  };
  const context = {
    console,
    document,
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value)
    },
    t: key => ({
      hold: 'On Hold',
      noBugs: 'No bugs reported.',
      status: 'Status',
      assignee: 'Assignee',
      severity: 'High'
    }[key] || key)
  };
  vm.createContext(context);
  const source = fs.readFileSync('static/bugs.js', 'utf8');
  vm.runInContext(`${source}
    globalThis.testApi = {
      BUG_STATUSES, PIPELINE_STATUSES, allBugs, allProjects, filteredBugs,
      populateFilters, renderPipeline, renderList, applyBugFilters,
      setBugs(value) { allBugs = value; },
      setView(value) { currentView = value; },
      getFiltered() { return filteredBugs; }
    };`, context);
  return {api: context.testApi, element: id => document.getElementById(id)};
}

const sampleBugs = [
  {id: 'RD-261014-001', status: 'hold', severity: 'high', title: 'Paused defect', reporter: 'agent', assignee: 'agent'},
  {id: 'BUG-261014-001', status: 'fixing', severity: 'medium', title: 'Active defect'},
  {id: 'BUG-261014-002', status: 'resolved', severity: 'low', title: 'Verified defect'}
];

test('hold is a selectable bug status and has a dedicated pipeline bucket', () => {
  const {api, element} = createTracker();
  api.setBugs(sampleBugs);
  api.populateFilters();
  api.applyBugFilters();

  assert.ok(api.BUG_STATUSES.includes('hold'));
  assert.ok(api.PIPELINE_STATUSES.includes('hold'));
  assert.match(element('filterStatus').innerHTML, /value="hold"[^>]*>On Hold/);
  assert.equal(element('pipeHold').textContent, 1);
  assert.match(element('cardsHold').innerHTML, /Paused defect/);
  assert.doesNotMatch(element('cardsResolved').innerHTML, /Paused defect/);
});

test('hold can be filtered and is labelled distinctly in list view', () => {
  const {api, element} = createTracker();
  api.setBugs(sampleBugs);
  api.populateFilters();
  api.setView('list');
  element('filterStatus').value = 'hold';
  api.applyBugFilters();

  assert.deepEqual(Array.from(api.getFiltered(), bug => bug.id), ['RD-261014-001']);
  assert.match(element('bugTableBody').innerHTML, /ts-hold[^>]*>On Hold/);
  assert.match(element('bugTableBody').innerHTML, /Paused defect/);
});
