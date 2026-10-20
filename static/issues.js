const ISSUE_CATEGORIES = ['hardware', 'software', 'product_experience', 'process', 'delivery', 'operations', 'other'];
const ISSUE_PRIORITIES = ['critical', 'high', 'medium', 'low'];
const ISSUE_STATUSES = ['open', 'triaged', 'in_progress', 'blocked', 'pending_review', 'closed'];
const ISSUE_COPY = {
  en: {title:'Top Issues',newIssue:'New issue',search:'Search issues by ID, title, owner…',showDeleted:'Show deleted',rank:'Rank',issue:'Issue',category:'Category',priority:'Priority',status:'Status',owner:'Owner',dueDate:'Due',project:'Project',loading:'Loading issues…',empty:'No issues match these filters.',loadError:'Could not load issues.',allCategories:'All categories',allStatuses:'All statuses',allOwners:'All owners',allPriorities:'All priorities',allAttention:'All attention',unassigned:'Unassigned',overdue:'Overdue',stale:'Stale (14+ days)',unranked:'Unranked',noProject:'No project',selectUser:'Select a known human user',noUsers:'No known human users found.',login:'Login',formNew:'Create issue',formEdit:'Edit issue',details:'Issue details',titleField:'Title',introduction:'Introduction',content:'Content',raisedBy:'Raised by',raisedDate:'Raised date',resolutionCriteria:'Resolution criteria',resolution:'Resolution',dueDateField:'Due date',categoryField:'Category',priorityField:'Priority',rankField:'Rank (0 = unranked)',statusField:'Status',ownerField:'Owner',projectField:'Project',workstreamField:'Workstream',tasksField:'Related tasks',bugsField:'Related bugs',none:'None',save:'Save',cancel:'Cancel',edit:'Edit',delete:'Delete',restore:'Restore',confirmDelete:'Move this issue to the bin?',comments:'Comments',commentPlaceholder:'Add a comment…',send:'Send',noComments:'No comments yet.',commentError:'Could not load comments.',required:'Title and content are required.',closedNeedsResolution:'Closed issues require resolution criteria and a resolution.',chooseUser:'Select a known human user before writing.',saved:'Issue saved.',deleted:'Issue moved to the bin.',restored:'Issue restored.',requestFailed:'Request failed.',detail:'Details',linked:'Linked items',noDue:'—',apiUnavailable:'Related item choices could not be loaded.',hardware:'Hardware',software:'Software',product_experience:'Product experience',process:'Process',delivery:'Delivery',operations:'Operations',other:'Other',critical:'Critical',high:'High',medium:'Medium',low:'Low',open:'Open',triaged:'Triaged',in_progress:'In progress',blocked:'Blocked',pending_review:'Pending review',closed:'Closed'},
  zh: {title:'重点问题',newIssue:'新建问题',search:'搜索编号、标题、负责人…',showDeleted:'显示已删除',rank:'排名',issue:'问题',category:'类别',priority:'优先级',status:'状态',owner:'负责人',dueDate:'截止日期',project:'项目',loading:'正在加载问题…',empty:'没有符合条件的问题。',loadError:'无法加载问题。',allCategories:'全部类别',allStatuses:'全部状态',allOwners:'全部负责人',allPriorities:'全部优先级',allAttention:'全部关注项',unassigned:'未分配',overdue:'已逾期',stale:'停滞（14 天及以上）',unranked:'未排名',noProject:'无项目',selectUser:'选择已知的人类用户',noUsers:'没有找到已知的人类用户。',login:'登录',formNew:'新建问题',formEdit:'编辑问题',details:'问题详情',titleField:'标题',introduction:'简介',content:'内容',raisedBy:'提出人',raisedDate:'提出日期',resolutionCriteria:'解决标准',resolution:'解决方案',dueDateField:'截止日期',categoryField:'类别',priorityField:'优先级',rankField:'排名（0 = 未排名）',statusField:'状态',ownerField:'负责人',projectField:'项目',workstreamField:'工作流',tasksField:'关联任务',bugsField:'关联缺陷',none:'无',save:'保存',cancel:'取消',edit:'编辑',delete:'删除',restore:'恢复',confirmDelete:'将此问题移入回收站？',comments:'评论',commentPlaceholder:'添加评论…',send:'发送',noComments:'暂无评论。',commentError:'无法加载评论。',required:'标题和内容为必填项。',closedNeedsResolution:'已关闭的问题必须填写解决标准和解决方案。',chooseUser:'写入前请先选择已知的人类用户。',saved:'问题已保存。',deleted:'问题已移入回收站。',restored:'问题已恢复。',requestFailed:'请求失败。',detail:'详情',linked:'关联项',noDue:'—',apiUnavailable:'无法加载关联项选项。',hardware:'硬件',software:'软件',product_experience:'产品体验',process:'流程',delivery:'交付',operations:'运营',other:'其他',critical:'严重',high:'高',medium:'中',low:'低',open:'待处理',triaged:'已分诊',in_progress:'进行中',blocked:'受阻',pending_review:'待审核',closed:'已关闭'}
};
let issues = [];
let users = [];
let projects = [];
let workstreams = [];
let tasks = [];
let bugs = [];
let referenceErrors = [];
let currentUser = localStorage.getItem('kanban-user') || '';
let activeIssue = null;
let loadingError = '';
let pendingUserAction = null;
let issueSyncStatus = null;

ISSUE_COPY.en.needsDetails = 'Feishu submissions awaiting details';
ISSUE_COPY.zh.needsDetails = '飞书待补全的问题';
ISSUE_COPY.en.missingFields = 'Missing';
ISSUE_COPY.zh.missingFields = '缺少';
ISSUE_COPY.en.untitled = 'Untitled';
ISSUE_COPY.zh.untitled = '未填写标题';
ISSUE_COPY.en.syncUnavailable = 'Feishu sync status unavailable.';
ISSUE_COPY.zh.syncUnavailable = '暂时无法获取飞书同步状态。';
ISSUE_COPY.en.syncErrors = 'Feishu sync errors';
ISSUE_COPY.zh.syncErrors = '飞书同步错误';

function issueSyncNotice(status) {
  if (!status) return issueText('syncUnavailable');
  const info = status.tables?.issues;
  if (!info?.configured) return '';
  const lines = [];
  if (info.errors) lines.push(`${issueText('syncErrors')}: ${info.errors}`);
  if (info.needs_details) {
    lines.push(`${issueText('needsDetails')}: ${info.needs_details}`);
    for (const row of info.pending_details || []) {
      const fields = (row.missing_fields || []).map(field => field === 'Title' ? issueText('titleField') : issueText('content'));
      lines.push(`${row.title || issueText('untitled')} — ${issueText('missingFields')}: ${fields.join(', ')}`);
    }
  }
  return lines.join('\n');
}
function renderIssueSyncNotice() {
  const node = document.getElementById('syncNotice');
  node.textContent = issueSyncNotice(issueSyncStatus);
  node.style.whiteSpace = 'pre-line';
  node.hidden = !node.textContent;
}

function issueText(key) { return ISSUE_COPY[currentLang === 'zh' ? 'zh' : 'en'][key] || key; }
function issueEsc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function issueLabel(value) {
  if (!value) return issueText('none');
  const key = String(value);
  const known = [...ISSUE_CATEGORIES, ...ISSUE_PRIORITIES, ...ISSUE_STATUSES, 'unassigned', 'overdue', 'stale'];
  if (known.includes(key)) return issueText(key);
  return key.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
}
function issueApi(url, method = 'GET', body) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (currentUser) headers['X-Kanban-User'] = currentUser;
  return fetch(url, {method, headers, ...(body === undefined ? {} : {body: JSON.stringify(body)})}).then(async response => {
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || result.message || `${response.status} ${response.statusText}`);
    }
    if (response.status === 204) return null;
    return response.json();
  });
}
function isHuman() { return users.some(user => user.name === currentUser && user.role === 'human'); }

document.addEventListener('DOMContentLoaded', initIssues);
async function initIssues() {
  document.getElementById('langBtn').textContent = currentLang === 'en' ? '中文' : 'EN';
  const savedTheme = localStorage.getItem('kanban-theme');
  if (savedTheme === 'light') { document.documentElement.classList.add('light'); document.getElementById('themeBtn').textContent = '🌙'; }
  setUserButton();
  document.getElementById('langBtn').addEventListener('click', toggleIssueLang);
  document.getElementById('themeBtn').addEventListener('click', toggleIssueTheme);
  document.getElementById('userBtn').addEventListener('click', openUserPicker);
  document.getElementById('newIssueBtn').addEventListener('click', () => openIssueForm());
  document.getElementById('refreshBtn').addEventListener('click', loadIssues);
  document.getElementById('closeDialogBtn').addEventListener('click', closeDialog);
  document.getElementById('closeUserBtn').addEventListener('click', closeUserPicker);
  document.getElementById('dialogBackdrop').addEventListener('click', event => { if (event.target.id === 'dialogBackdrop') closeDialog(); });
  document.getElementById('userBackdrop').addEventListener('click', event => { if (event.target.id === 'userBackdrop') closeUserPicker(); });
  document.getElementById('deletedToggle').addEventListener('change', loadIssues);
  ['searchInput','categoryFilter','statusFilter','ownerFilter','priorityFilter','attentionFilter'].forEach(id => {
    document.getElementById(id).addEventListener(id === 'searchInput' ? 'input' : 'change', renderIssues);
  });
  document.getElementById('issueRows').addEventListener('click', event => {
    const restoreButton = event.target.closest('[data-restore-id]');
    if (restoreButton) { event.stopPropagation(); restoreIssue({id: restoreButton.dataset.restoreId}); return; }
    const row = event.target.closest('[data-issue-id]');
    if (row) openIssueDetail(row.dataset.issueId);
  });
  document.getElementById('issueRows').addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { const row = event.target.closest('[data-issue-id]'); if (row) { event.preventDefault(); openIssueDetail(row.dataset.issueId); } }
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeDialog(); closeUserPicker(); } });
  translateIssues();
  await loadReferenceData();
  await loadIssues();
}
function translateIssues() {
  document.querySelectorAll('[data-copy]').forEach(node => { node.textContent = issueText(node.dataset.copy); });
  document.querySelectorAll('[data-placeholder]').forEach(node => { node.placeholder = issueText(node.dataset.placeholder); });
  document.title = `${issueText('title')} — ConvergenceKanban`;
  document.getElementById('langBtn').textContent = currentLang === 'en' ? '中文' : 'EN';
  populateFilters();
  renderIssues();
  renderIssueSyncNotice();
}
function toggleIssueLang() {
  currentLang = currentLang === 'en' ? 'zh' : 'en';
  localStorage.setItem('kanban-lang', currentLang);
  translateIssues();
  if (activeIssue) openIssueDetail(activeIssue.id);
}
function toggleIssueTheme() {
  const light = document.documentElement.classList.toggle('light');
  localStorage.setItem('kanban-theme', light ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = light ? '🌙' : '☀️';
}
function setUserButton() { document.getElementById('userBtn').textContent = currentUser || issueText('login'); }
async function loadReferenceData() {
  const requests = [
    ['users','/api/users'], ['projects','/api/projects'], ['workstreams','/api/workstreams'], ['tasks','/api/tasks'], ['bugs','/api/bugs']
  ];
  const results = await Promise.all(requests.map(async ([key,url]) => {
    try { return [key, await issueApi(url)]; } catch (error) { return [key, [], error]; }
  }));
  referenceErrors = results.filter(([, , error]) => error).map(([key,,error]) => `${key}: ${error.message}`);
  results.forEach(([key,data]) => { windowIssueSet(key, Array.isArray(data) ? data : []); });
  const userFailure = results.find(([key,,error]) => key === 'users' && error);
  if (userFailure) showPageError(`${issueText('chooseUser')} ${userFailure[2].message}`);
  populateFilters();
}
function windowIssueSet(key, data) {
  if (key === 'users') users = data;
  if (key === 'projects') projects = data;
  if (key === 'workstreams') workstreams = data;
  if (key === 'tasks') tasks = data;
  if (key === 'bugs') bugs = data;
}
async function loadIssues() {
  setPageStatus(issueText('loading'));
  loadingError = '';
  try {
    const query = document.getElementById('deletedToggle').checked ? '?include_deleted=true' : '';
    const [result, sync] = await Promise.all([
      issueApi(`/api/issues${query}`),
      issueApi('/api/sync/status').catch(() => null),
    ]);
    issueSyncStatus = sync;
    issues = Array.isArray(result) ? result : (Array.isArray(result?.items) ? result.items : []);
    setPageStatus('');
    if (referenceErrors.length) showPageError(`${issueText('apiUnavailable')} ${referenceErrors.join('; ')}`);
    else document.getElementById('pageError').hidden = true;
  } catch (error) {
    issues = [];
    loadingError = `${issueText('loadError')} ${error.message}`;
    showPageError(loadingError);
    setPageStatus('');
  }
  populateFilters();
  renderIssues();
  renderIssueSyncNotice();
}
function showPageError(message) {
  const el = document.getElementById('pageError'); el.textContent = message; el.hidden = false;
  if (!document.getElementById('dialogBackdrop').hidden) {
    let error = document.getElementById('dialogError');
    if (!error) {
      error = document.createElement('p'); error.id = 'dialogError'; error.className = 'issues-message error-message'; error.setAttribute('role', 'alert');
      document.getElementById('dialogBody').prepend(error);
    }
    error.textContent = message;
    error.scrollIntoView({block:'nearest'});
  }
}
function setPageStatus(message) { const el = document.getElementById('pageStatus'); el.textContent = message; el.hidden = !message; }
function setOptions(select, firstLabel, items, selected = '') {
  const prior = selected || select.value;
  select.innerHTML = `<option value="">${issueEsc(firstLabel)}</option>` + items.map(value => `<option value="${issueEsc(value)}">${issueEsc(issueLabel(value))}</option>`).join('');
  if ([...select.options].some(option => option.value === prior)) select.value = prior;
}
function populateFilters() {
  const category = document.getElementById('categoryFilter');
  const status = document.getElementById('statusFilter');
  const priority = document.getElementById('priorityFilter');
  if (!category) return;
  setOptions(category, issueText('allCategories'), ISSUE_CATEGORIES);
  setOptions(status, issueText('allStatuses'), ISSUE_STATUSES);
  setOptions(priority, issueText('allPriorities'), ISSUE_PRIORITIES);
  const attention = document.getElementById('attentionFilter');
  setOptions(attention, issueText('allAttention'), ['unassigned', 'overdue', 'stale']);
  const owner = document.getElementById('ownerFilter');
  const owners = [...new Set(issues.map(issue => issue.owner).filter(Boolean))].sort();
  setOptions(owner, issueText('allOwners'), owners);
}
function renderIssues() {
  const body = document.getElementById('issueRows');
  if (!body) return;
  const query = document.getElementById('searchInput').value.trim().toLowerCase();
  const category = document.getElementById('categoryFilter').value;
  const status = document.getElementById('statusFilter').value;
  const owner = document.getElementById('ownerFilter').value;
  const priority = document.getElementById('priorityFilter').value;
  const attention = document.getElementById('attentionFilter').value;
  const filtered = issues.filter(issue => {
    const text = [issue.display_id, issue.title, issue.introduction, issue.content, issue.owner, issue.raised_by].join(' ').toLowerCase();
    return (!query || text.includes(query)) && (!category || issue.category === category) && (!status || issue.status === status) && (!owner || issue.owner === owner) && (!priority || issue.priority === priority) && issueMatchesAttention(issue, attention);
  });
  document.getElementById('issueCount').textContent = String(filtered.length);
  if (loadingError) { body.innerHTML = `<tr><td colspan="8" class="table-empty error-text">${issueEsc(loadingError)}</td></tr>`; return; }
  if (!filtered.length) { body.innerHTML = `<tr><td colspan="8" class="table-empty">${issueEsc(issueText('empty'))}</td></tr>`; return; }
  body.innerHTML = filtered.map(issue => `<tr data-issue-id="${issueEsc(issue.id)}" class="issue-row ${issue.deleted_at ? 'is-deleted' : ''}" tabindex="0" aria-label="${issueEsc(issue.display_id)} ${issueEsc(issue.title)}">
    <td class="rank-cell">${issue.rank > 0 ? `<span class="rank-number">${issueEsc(issue.rank)}</span>` : `<span class="unranked">${issueEsc(issueText('unranked'))}</span>`}</td>
    <td class="issue-title-cell"><span class="issue-id">${issueEsc(issue.display_id || `#${issue.id}`)}</span><strong>${issueEsc(issue.title)}</strong>${issue.deleted_at ? `<span class="deleted-marker">${issueEsc(issueText('showDeleted'))}</span>${isHuman() ? `<button type="button" class="row-restore" data-restore-id="${issueEsc(issue.id)}">${issueEsc(issueText('restore'))}</button>` : ''}` : ''}</td>
    <td>${issueEsc(issueLabel(issue.category))}</td><td><span class="priority-value priority-${issueEsc(issue.priority)}">${issueEsc(issueLabel(issue.priority))}</span></td>
    <td><span class="status-value status-${issueEsc(issue.status)}">${issueEsc(issueLabel(issue.status))}</span></td><td>${issueEsc(issue.owner || issueText('none'))}</td>
    <td class="mono">${issueEsc(issue.due_date || issueText('noDue'))}</td><td>${issueEsc(projectName(issue.project_id) || issueText('noProject'))}</td>
  </tr>`).join('');
}
function shanghaiDate(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit'}).formatToParts(now);
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}
function issueTimestamp(value) {
  if (typeof value !== 'string' || !value.trim()) return NaN;
  const normalized = value.trim().replace(' ', 'T');
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const dateTime = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(normalized);
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(normalized);
  if (dateOnly) return Date.parse(`${normalized}T00:00:00+08:00`);
  if (dateTime && !zoned) return Date.parse(`${normalized}+08:00`);
  return Date.parse(normalized);
}
function issueMatchesAttention(issue, filter, now = new Date()) {
  if (!filter) return true;
  if (issue.deleted_at || issue.status === 'closed') return false;
  if (filter === 'unassigned') return !String(issue.owner || '').trim();
  if (filter === 'overdue') {
    return /^\d{4}-\d{2}-\d{2}$/.test(issue.due_date || '') && issue.due_date < shanghaiDate(now);
  }
  if (filter === 'stale') {
    const updated = issueTimestamp(issue.updated_at || issue.created_at);
    return Number.isFinite(updated) && updated <= now.getTime() - 14 * 24 * 60 * 60 * 1000;
  }
  return true;
}
function projectName(id) { const project = projects.find(item => String(item.id) === String(id)); return project ? (currentLang === 'zh' ? project.name_zh || project.name_en : project.name_en || project.name_zh || project.name || project.title || project.id) : ''; }
function openDialog(title, body) {
  document.getElementById('dialogTitle').textContent = title;
  const container = document.getElementById('dialogBody');
  container.replaceChildren();
  if (typeof body === 'string') container.innerHTML = body;
  else container.append(body);
  document.getElementById('dialogBackdrop').hidden = false;
  document.querySelector('.issue-dialog').scrollTop = 0;
}
function closeDialog() { document.getElementById('dialogBackdrop').hidden = true; activeIssue = null; }
async function openIssueDetail(id) {
  try {
    const row = issues.find(issue => String(issue.id) === String(id));
    if (row?.deleted_at) return;
    const issue = await issueApi(`/api/issues/${encodeURIComponent(id)}`);
    activeIssue = issue || row;
    const item = activeIssue;
    openDialog(item.title || issueText('details'), `<div class="issue-detail">
      <div class="detail-kicker">${issueEsc(item.display_id || '')}</div>
      <div class="detail-meta"><span>${issueEsc(issueLabel(item.category))}</span><span>${issueEsc(issueLabel(item.priority))}</span><span>${issueEsc(issueLabel(item.status))}</span><span>${issueEsc(issueText('rank'))}: ${item.rank > 0 ? issueEsc(item.rank) : issueEsc(issueText('unranked'))}</span></div>
      ${detailField('introduction', item.introduction)}${detailField('content', item.content)}
      <div class="detail-grid">${detailField('raisedBy', item.raised_by)}${detailField('raisedDate', item.raised_date)}${detailField('owner', item.owner)}${detailField('dueDate', item.due_date)}${detailField('project', projectName(item.project_id))}${detailField('workstreamField', workstreamName(item.workstream_id))}${detailField('resolutionCriteria', item.resolution_criteria)}${detailField('resolution', item.resolution)}</div>
      ${detailField('tasksField', (item.task_ids || []).map(id => tasks.find(row => row.id === id)?.title_en || id).join('\n'))}
      ${detailField('bugsField', (item.bug_ids || []).map(id => { const row = bugs.find(bug => bug.id === id); return row ? `${row.display_id}: ${row.title}` : id; }).join('\n'))}
      <section class="comment-section"><h3>${issueEsc(issueText('comments'))}</h3><div id="commentList" class="comment-list">…</div>${isHuman() ? `<form id="commentForm" class="comment-form"><textarea name="body" maxlength="5000" required placeholder="${issueEsc(issueText('commentPlaceholder'))}"></textarea><button class="btn btn-sm btn-primary" type="submit">${issueEsc(issueText('send'))}</button></form>` : ''}</section>
      <footer class="detail-actions">${isHuman() && !item.deleted_at ? `<button class="btn btn-sm" id="editIssueBtn">${issueEsc(issueText('edit'))}</button><button class="btn btn-sm danger-btn" id="deleteIssueBtn">${issueEsc(issueText('delete'))}</button>` : ''}${isHuman() && item.deleted_at ? `<button class="btn btn-sm" id="restoreIssueBtn">${issueEsc(issueText('restore'))}</button>` : ''}</footer>
    </div>`);
    loadComments(item.id);
    const edit = document.getElementById('editIssueBtn'); if (edit) edit.addEventListener('click', () => openIssueForm(item));
    const del = document.getElementById('deleteIssueBtn'); if (del) del.addEventListener('click', () => deleteIssue(item));
    const restore = document.getElementById('restoreIssueBtn'); if (restore) restore.addEventListener('click', () => restoreIssue(item));
    const form = document.getElementById('commentForm'); if (form) form.addEventListener('submit', submitComment);
  } catch (error) { showPageError(`${issueText('requestFailed')} ${error.message}`); }
}
function detailField(key, value) { return `<div class="detail-field"><span>${issueEsc(issueText(key))}</span><div>${issueEsc(value || issueText('none'))}</div></div>`; }
function workstreamName(id) { const item = workstreams.find(row => String(row.id) === String(id)); return item ? item.title_en || item.title_zh || item.name || item.name_en || item.title || item.id : ''; }
async function loadComments(id) {
  const container = document.getElementById('commentList');
  try {
    const result = await issueApi(`/api/comments/issue/${encodeURIComponent(id)}`);
    const comments = Array.isArray(result) ? result : (result?.comments || []);
    container.innerHTML = comments.length ? comments.map(comment => `<article class="comment"><header><strong>${issueEsc(comment.actor || comment.user || comment.author || '')}</strong><time>${issueEsc(comment.created_at || '')}</time></header><p>${issueEsc(comment.body || '')}</p></article>`).join('') : `<p class="muted">${issueEsc(issueText('noComments'))}</p>`;
  } catch (error) { container.textContent = `${issueText('commentError')} ${error.message}`; }
}
async function submitComment(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!requireHuman(() => form.requestSubmit())) return;
  const body = new FormData(form).get('body').toString().trim();
  if (!body || !activeIssue) return;
  try { await issueApi(`/api/comments/issue/${encodeURIComponent(activeIssue.id)}`, 'POST', {body}); await loadComments(activeIssue.id); form.reset(); }
  catch (error) { showPageError(`${issueText('requestFailed')} ${error.message}`); }
}
function requireHuman(retry = null) {
  if (isHuman()) return true;
  pendingUserAction = retry;
  openUserPicker(issueText('chooseUser'));
  return false;
}
function field(label, control, wide = false) { return `<label class="form-field ${wide ? 'field-wide' : ''}"><span>${issueEsc(issueText(label))}</span>${control}</label>`; }
function input(name, value = '', type = 'text', attrs = '') { return `<input name="${name}" type="${type}" value="${issueEsc(value)}" ${attrs}>`; }
function localDateToday() { const today = new Date(); today.setMinutes(today.getMinutes() - today.getTimezoneOffset()); return today.toISOString().slice(0,10); }
function selectControl(name, values, selected = '', first = null, multiple = false) {
  const options = values.map(item => { const value = typeof item === 'object' ? item.value : item; const label = typeof item === 'object' ? item.label : issueLabel(item); const isSelected = multiple ? (selected || []).map(String).includes(String(value)) : String(selected ?? '') === String(value); return `<option value="${issueEsc(value)}" ${isSelected ? 'selected' : ''}>${issueEsc(label)}</option>`; }).join('');
  return `<select name="${name}" ${multiple ? 'multiple size="5"' : ''}>${first === null ? '' : `<option value="">${issueEsc(first)}</option>`}${options}</select>`;
}
function openIssueForm(issue = null) {
  if (!requireHuman(() => openIssueForm(issue))) return;
  if (referenceErrors.length) { showPageError(issueText('apiUnavailable')); return; }
  const editing = Boolean(issue);
  const wsRows = workstreams.filter(row => !issue?.project_id || String(row.project_id) === String(issue.project_id));
  const projectOptions = [{value:'',label:issueText('none')}, ...projects.map(row => ({value:row.id,label:(currentLang === 'zh' && row.name_zh) || row.name_en || row.name || row.title || row.id}))];
  const workstreamOptions = [{value:'',label:issueText('none')}, ...wsRows.map(row => ({value:row.id,label:row.title_en || row.title_zh || row.name || row.name_en || row.title || row.id}))];
  const taskOptions = tasks.map(row => ({value:row.id,label:`${row.display_id || row.id} · ${row.title || row.title_en || row.name || ''}`}));
  const bugOptions = bugs.map(row => ({value:row.id,label:`${row.display_id || row.id} · ${row.title || ''}`}));
  const ownerOptions = [{value:'',label:issueText('none')}, ...users.filter(user => user.role === 'human').map(user => ({value:user.name,label:user.display_name || user.name}))];
  if (issue?.owner && !ownerOptions.some(option => option.value === issue.owner)) ownerOptions.push({value:issue.owner,label:issue.owner});
  // Preserve references that are no longer in active-item lookups.
  for (const [options, selected] of [[projectOptions, [issue?.project_id]], [workstreamOptions, [issue?.workstream_id]], [taskOptions, issue?.task_ids || []], [bugOptions, issue?.bug_ids || []]]) {
    for (const id of selected) if (id && !options.some(option => option.value === id)) options.push({value:id,label:id});
  }
  const markup = `<form id="issueForm" class="issue-form">
    ${field('titleField', input('title', issue?.title || '', 'text', 'required maxlength="500"'))}
    ${field('categoryField', selectControl('category', ISSUE_CATEGORIES, issue?.category || 'other'))}
    ${field('priorityField', selectControl('priority', ISSUE_PRIORITIES, issue?.priority || 'medium'))}
    ${field('statusField', selectControl('status', ISSUE_STATUSES, issue?.status || 'open'))}
    ${field('rankField', input('rank', issue?.rank ?? 0, 'number', 'min="0" step="1"'))}
    ${field('ownerField', selectControl('owner', ownerOptions, issue?.owner || ''))}
    ${field('raisedBy', input('raised_by', issue?.raised_by || currentUser, 'text', 'readonly'))}
    ${field('raisedDate', input('raised_date', issue?.raised_date || localDateToday(), 'date', 'required'))}
    ${field('dueDateField', input('due_date', issue?.due_date || '', 'date'))}
    ${field('projectField', selectControl('project_id', projectOptions, issue?.project_id ?? ''), false)}
    ${field('workstreamField', selectControl('workstream_id', workstreamOptions, issue?.workstream_id ?? ''), false)}
    ${field('introduction', `<textarea name="introduction" rows="2" maxlength="5000">${issueEsc(issue?.introduction || '')}</textarea>`, true)}
    ${field('content', `<textarea name="content" rows="5" required>${issueEsc(issue?.content || '')}</textarea>`, true)}
    ${field('resolutionCriteria', `<textarea name="resolution_criteria" rows="3">${issueEsc(issue?.resolution_criteria || '')}</textarea>`, true)}
    ${field('resolution', `<textarea name="resolution" rows="3">${issueEsc(issue?.resolution || '')}</textarea>`, true)}
    ${field('tasksField', selectControl('task_ids', taskOptions, issue?.task_ids || [], null, true), true)}
    ${field('bugsField', selectControl('bug_ids', bugOptions, issue?.bug_ids || [], null, true), true)}
    ${referenceErrors.length ? `<p class="form-note">${issueEsc(issueText('apiUnavailable'))} ${issueEsc(referenceErrors.join('; '))}</p>` : ''}
    <footer class="form-actions"><button class="btn" type="button" id="cancelIssueBtn">${issueEsc(issueText('cancel'))}</button><button class="btn btn-primary" type="submit">${issueEsc(issueText('save'))}</button></footer>
  </form>`;
  openDialog(issueText(editing ? 'formEdit' : 'formNew'), markup);
  const form = document.getElementById('issueForm');
  form.elements.project_id.addEventListener('change', () => {
    const selection = form.elements.workstream_id.value;
    const filtered = workstreams.filter(row => !form.elements.project_id.value || String(row.project_id) === form.elements.project_id.value);
    form.elements.workstream_id.innerHTML = `<option value="">${issueEsc(issueText('none'))}</option>` + filtered.map(row => `<option value="${issueEsc(row.id)}">${issueEsc(row.title_en || row.title_zh || row.name || row.name_en || row.title || row.id)}</option>`).join('');
    if (filtered.some(row => String(row.id) === selection)) form.elements.workstream_id.value = selection;
  });
  document.getElementById('cancelIssueBtn').addEventListener('click', closeDialog);
  form.addEventListener('submit', event => saveIssue(event, issue));
}
async function saveIssue(event, issue) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!requireHuman(() => form.requestSubmit())) return;
  const data = new FormData(form);
  const value = name => data.get(name)?.toString().trim() || '';
  const payload = {
    title: value('title'), category: value('category'), priority: value('priority'), rank: Number(value('rank') || 0),
    status: value('status'), owner: value('owner'), raised_by: value('raised_by') || currentUser, raised_date: value('raised_date'),
    due_date: value('due_date') || null, introduction: value('introduction'), content: value('content'),
    resolution_criteria: value('resolution_criteria'), resolution: value('resolution'),
    project_id: value('project_id') || null, workstream_id: value('workstream_id') || null,
    task_ids: [...form.elements.task_ids.selectedOptions].map(option => option.value),
    bug_ids: [...form.elements.bug_ids.selectedOptions].map(option => option.value)
  };
  if (!payload.title || !payload.content) { showPageError(issueText('required')); return; }
  if (payload.rank < 0 || !Number.isInteger(payload.rank)) { showPageError(issueText('rankField')); return; }
  if (payload.status === 'closed' && (!payload.resolution.trim() || !payload.resolution_criteria.trim())) { showPageError(issueText('closedNeedsResolution')); return; }
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    if (issue) {
      const changes = Object.fromEntries(Object.entries(payload).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(issue[key] ?? null)));
      if (Object.keys(changes).length) await issueApi(`/api/issues/${encodeURIComponent(issue.id)}`, 'PUT', changes);
    }
    else await issueApi('/api/issues', 'POST', payload);
    closeDialog(); setPageStatus(issueText('saved')); await loadIssues(); setTimeout(() => setPageStatus(''), 3000);
  } catch (error) { showPageError(`${issueText('requestFailed')} ${error.message}`); }
  finally { submit.disabled = false; }
}
async function deleteIssue(issue) {
  if (!requireHuman(() => deleteIssue(issue)) || !confirm(issueText('confirmDelete'))) return;
  try { await issueApi(`/api/issues/${encodeURIComponent(issue.id)}`, 'DELETE'); closeDialog(); setPageStatus(issueText('deleted')); await loadIssues(); }
  catch (error) { showPageError(`${issueText('requestFailed')} ${error.message}`); }
}
async function restoreIssue(issue) {
  if (!requireHuman(() => restoreIssue(issue))) return;
  try { await issueApi(`/api/issues/${encodeURIComponent(issue.id)}/restore`, 'POST', {}); closeDialog(); setPageStatus(issueText('restored')); await loadIssues(); }
  catch (error) { showPageError(`${issueText('requestFailed')} ${error.message}`); }
}
function openUserPicker(message = '') {
  const options = document.getElementById('userOptions');
  const humans = users.filter(user => user.role === 'human');
  options.innerHTML = humans.length ? humans.map(user => `<button class="user-option ${user.name === currentUser ? 'selected' : ''}" type="button" data-user="${issueEsc(user.name)}"><strong>${issueEsc(user.display_name || user.name)}</strong><span>${issueEsc(user.name)}</span></button>`).join('') : `<p>${issueEsc(issueText('noUsers'))}</p>`;
  options.querySelectorAll('[data-user]').forEach(button => button.addEventListener('click', () => {
    currentUser = button.dataset.user;
    localStorage.setItem('kanban-user', currentUser);
    setUserButton(); closeUserPicker(); document.getElementById('userError').hidden = true;
    renderIssues();
    const action = pendingUserAction; pendingUserAction = null;
    if (action) action();
    else if (activeIssue) openIssueDetail(activeIssue.id);
  }));
  const error = document.getElementById('userError');
  error.textContent = message; error.hidden = !message;
  document.getElementById('userBackdrop').hidden = false;
}
function closeUserPicker() { document.getElementById('userBackdrop').hidden = true; }
