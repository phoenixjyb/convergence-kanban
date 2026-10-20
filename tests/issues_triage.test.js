const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const source = fs.readFileSync('static/issues.js', 'utf8');
const context = {
  Date,
  Intl,
  localStorage: {getItem: () => ''},
  document: {addEventListener() {}},
  currentLang: 'en'
};
vm.createContext(context);
vm.runInContext(`${source}\nglobalThis.triage = {issueMatchesAttention, issueTimestamp, issueText, issueLabel, issueSyncNotice};`, context);
const {issueMatchesAttention, issueTimestamp, issueText, issueLabel} = context.triage;

test('sync notice distinguishes incomplete submissions from errors in both languages', () => {
  const status = {tables: {issues: {configured: true, needs_details: 1, errors: 0, pending_details: [{title: '<Outdoor>', missing_fields: ['Issue Content']}]}}};
  context.currentLang = 'en';
  assert.match(context.triage.issueSyncNotice(status), /awaiting details: 1/);
  assert.match(context.triage.issueSyncNotice(status), /<Outdoor>.*Missing: Content/);
  context.currentLang = 'zh';
  assert.match(context.triage.issueSyncNotice(status), /待补全的问题: 1/);
  assert.match(context.triage.issueSyncNotice(status), /缺少: 内容/);
  assert.equal(context.triage.issueSyncNotice({tables: {issues: {configured: true, errors: 0}}}), '');
  assert.equal(context.triage.issueSyncNotice({tables: {issues: {configured: false}}}), '');
  assert.match(context.triage.issueSyncNotice(null), /无法获取/);
  assert.match(context.triage.issueSyncNotice({tables: {issues: {configured: true, errors: 2}}}), /同步错误: 2/);
  assert.match(source, /node\.textContent = issueSyncNotice/);
  context.currentLang = 'en';
});

test('attention labels are bilingual', () => {
  assert.equal(issueText('allAttention'), 'All attention');
  assert.equal(issueLabel('unassigned'), 'Unassigned');
  context.currentLang = 'zh';
  assert.equal(issueText('allAttention'), '全部关注项');
  assert.equal(issueLabel('overdue'), '已逾期');
  assert.equal(issueLabel('stale'), '停滞（14 天及以上）');
});

test('unassigned ignores whitespace and attention excludes closed or archived issues', () => {
  const base = {owner: '  ', status: 'open'};
  assert.equal(issueMatchesAttention(base, 'unassigned'), true);
  assert.equal(issueMatchesAttention({...base, status: 'closed'}, 'unassigned'), false);
  assert.equal(issueMatchesAttention({...base, deleted_at: '2026-01-01'}, 'unassigned'), false);
  assert.equal(issueMatchesAttention({...base, owner: 'alice'}, 'unassigned'), false);
});

test('overdue is strictly before the Asia/Shanghai calendar date', () => {
  const now = new Date('2026-10-14T15:30:00Z'); // 2026-10-14 23:30 in Shanghai
  assert.equal(issueMatchesAttention({status: 'open', due_date: '2026-10-13'}, 'overdue', now), true);
  assert.equal(issueMatchesAttention({status: 'open', due_date: '2026-10-14'}, 'overdue', now), false);
  assert.equal(issueMatchesAttention({status: 'open', due_date: '2026-10-15'}, 'overdue', now), false);
  assert.equal(issueMatchesAttention({status: 'open', due_date: '2026-10-13', deleted_at: 'x'}, 'overdue', now), false);
  assert.equal(issueMatchesAttention({status: 'closed', due_date: '2026-10-13'}, 'overdue', now), false);
});

test('stale threshold uses Shanghai for zone-less timestamps and excludes future timestamps', () => {
  const now = new Date('2026-10-14T04:00:00Z');
  assert.equal(issueTimestamp('2026-09-30 12:00:00'), Date.parse('2026-09-30T12:00:00+08:00'));
  assert.equal(issueMatchesAttention({status: 'open', updated_at: '2026-09-30 12:00:00'}, 'stale', now), true);
  assert.equal(issueMatchesAttention({status: 'open', updated_at: '2026-09-30 13:00:00'}, 'stale', now), false);
  assert.equal(issueMatchesAttention({status: 'open', updated_at: '2026-10-15 12:00:00'}, 'stale', now), false);
  assert.equal(issueMatchesAttention({status: 'open', updated_at: '2026-09-01 00:00:00', deleted_at: 'x'}, 'stale', now), false);
  assert.equal(issueMatchesAttention({status: 'closed', updated_at: '2026-09-01 00:00:00'}, 'stale', now), false);
});
