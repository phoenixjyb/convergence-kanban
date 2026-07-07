// ══════════════════════════════════════════════════════════════════════════
// Bug Tracker — Full client logic
// ══════════════════════════════════════════════════════════════════════════

const BUG_STATUSES = ['open', 'investigating', 'fixing', 'fix_complete', 'to_verify', 'resolved', 'closed', 'wontfix'];
const BUG_SEVERITIES = ['critical', 'high', 'medium', 'low'];
const PIPELINE_STATUSES = ['open', 'investigating', 'fixing', 'fix_complete', 'to_verify', 'resolved', 'closed'];

let allBugs = [];
let allProjects = [];
let allUsers = [];
let filteredBugs = [];
let _savedBugFilters = JSON.parse(localStorage.getItem('kanban-bug-filters') || '{}');
let currentView = _savedBugFilters.view || 'pipeline';
let currentSevFilter = _savedBugFilters.severity || 'all';
let currentUser = localStorage.getItem('kanban-user') || '';
let bugTaskCache = {}; // bug_id -> [tasks]

// ── Utility ──────────────────────────────────────────────────────────────
function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _humanSize(bytes) {
  if (!bytes || bytes < 1024) return (bytes || 0) + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function api(url, method = 'GET', body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (currentUser) opts.headers['X-Kanban-User'] = currentUser;
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Restore theme
  const savedTheme = localStorage.getItem('kanban-theme');
  if (savedTheme === 'light') {
    document.documentElement.classList.add('light');
    document.getElementById('themeBtn').textContent = '🌙';
  }
  // Restore lang
  if (currentLang !== 'en') {
    document.getElementById('langBtn').textContent = 'EN';
  }
  // Restore user
  if (currentUser) {
    document.getElementById('userBtn').textContent = currentUser;
  }
  // Restore font size
  applyFontSize(localStorage.getItem('kanban-font-size') || 'md');
  applyI18n();
  await loadData();
  // Restore saved bug filters after data is loaded and filters populated
  if (_savedBugFilters.status) document.getElementById('filterStatus').value = _savedBugFilters.status;
  if (_savedBugFilters.project) document.getElementById('filterProject').value = _savedBugFilters.project;
  if (_savedBugFilters.assignee) document.getElementById('filterAssignee').value = _savedBugFilters.assignee;
  if (_savedBugFilters.search) document.getElementById('bugSearch').value = _savedBugFilters.search;
  if (_savedBugFilters.severity && _savedBugFilters.severity !== 'all') {
    document.querySelectorAll('.sev-stat').forEach(el => {
      el.classList.toggle('active', el.dataset.sev === _savedBugFilters.severity);
    });
  }
  if (_savedBugFilters.view && _savedBugFilters.view !== 'pipeline') setView(_savedBugFilters.view);
  // Support ?search= URL param from kanban cross-link
  const urlSearch = new URLSearchParams(window.location.search).get('search');
  if (urlSearch) document.getElementById('bugSearch').value = urlSearch;
  applyBugFilters();
});

async function loadData() {
  try {
    [allBugs, allProjects, allUsers] = await Promise.all([
      api('/api/bugs'),
      api('/api/projects'),
      api('/api/users'),
    ]);
  } catch (e) {
    console.error('Failed to load data:', e);
    allBugs = []; allProjects = []; allUsers = [];
  }
  populateFilters();
  applyBugFilters();
}

// ── Filters ──────────────────────────────────────────────────────────────
function populateFilters() {
  const projSelect = document.getElementById('filterProject');
  const assigneeSelect = document.getElementById('filterAssignee');

  // Projects
  const projHtml = '<option value="">' + t('projects') + ': All</option>' +
    allProjects.map(p => `<option value="${p.id}">${esc(p.name_en)}</option>`).join('');
  projSelect.innerHTML = projHtml;

  // Assignees (unique from bugs)
  const assignees = [...new Set(allBugs.map(b => b.assignee).filter(Boolean))].sort();
  assigneeSelect.innerHTML = '<option value="">' + t('assignee') + ': All</option>' +
    assignees.map(a => `<option value="${esc(a)}">${esc(a)}</option>`).join('');

  // Update status filter i18n
  const statusSelect = document.getElementById('filterStatus');
  const statusVal = statusSelect.value;
  statusSelect.innerHTML = `<option value="">${t('status')}: All</option>` +
    BUG_STATUSES.map(s => `<option value="${s}" ${s === statusVal ? 'selected' : ''}>${t(s)}</option>`).join('');
}

function filterBySeverity(sev) {
  currentSevFilter = sev;
  document.querySelectorAll('.sev-stat').forEach(el => {
    el.classList.toggle('active', el.dataset.sev === sev);
  });
  applyBugFilters();
}

function applyBugFilters() {
  const search = (document.getElementById('bugSearch').value || '').toLowerCase();
  const project = document.getElementById('filterProject').value;
  const status = document.getElementById('filterStatus').value;
  const assignee = document.getElementById('filterAssignee').value;

  filteredBugs = allBugs.filter(b => {
    if (currentSevFilter !== 'all' && b.severity !== currentSevFilter) return false;
    if (project && b.project_id !== project) return false;
    if (status && b.status !== status) return false;
    if (assignee && b.assignee !== assignee) return false;
    if (search) {
      const haystack = `${b.id} ${b.title} ${b.description} ${b.reporter} ${b.assignee} ${b.environment} ${b.feature} ${b.device_id} ${b.issue_version}`.toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });

  // Persist bug filter state
  localStorage.setItem('kanban-bug-filters', JSON.stringify({
    severity: currentSevFilter,
    status: status,
    project: project,
    assignee: assignee,
    search: search,
    view: currentView,
  }));

  updateSeverityCounts();
  render();
}

function updateSeverityCounts() {
  // Use allBugs for "all" count, but filtered for severity-specific counts respects other filters
  const baseBugs = allBugs.filter(b => {
    const search = (document.getElementById('bugSearch').value || '').toLowerCase();
    const project = document.getElementById('filterProject').value;
    const status = document.getElementById('filterStatus').value;
    const assignee = document.getElementById('filterAssignee').value;
    if (project && b.project_id !== project) return false;
    if (status && b.status !== status) return false;
    if (assignee && b.assignee !== assignee) return false;
    if (search) {
      const haystack = `${b.id} ${b.title} ${b.description} ${b.reporter} ${b.assignee} ${b.environment} ${b.feature} ${b.device_id} ${b.issue_version}`.toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });

  document.getElementById('countAll').textContent = baseBugs.length;
  document.getElementById('totalBugCount').textContent = allBugs.length;
  for (const sev of BUG_SEVERITIES) {
    const id = 'count' + sev.charAt(0).toUpperCase() + sev.slice(1);
    document.getElementById(id).textContent = baseBugs.filter(b => b.severity === sev).length;
  }
}

// ── View toggle ──────────────────────────────────────────────────────────
function setView(view) {
  currentView = view;
  document.getElementById('viewPipeline').classList.toggle('active', view === 'pipeline');
  document.getElementById('viewList').classList.toggle('active', view === 'list');
  document.getElementById('pipelineView').style.display = view === 'pipeline' ? '' : 'none';
  document.getElementById('listView').style.display = view === 'list' ? '' : 'none';
  // Update persisted view
  try { const f = JSON.parse(localStorage.getItem('kanban-bug-filters') || '{}'); f.view = view; localStorage.setItem('kanban-bug-filters', JSON.stringify(f)); } catch(e) {}
  render();
}

// ── Render ────────────────────────────────────────────────────────────────
function render() {
  if (currentView === 'pipeline') renderPipeline();
  else renderList();
}

function renderPipeline() {
  const grouped = {};
  for (const s of PIPELINE_STATUSES) grouped[s] = [];

  for (const b of filteredBugs) {
    const bucket = (b.status === 'wontfix') ? 'closed' : b.status;
    if (grouped[bucket]) grouped[bucket].push(b);
  }

  for (const status of PIPELINE_STATUSES) {
    const container = document.getElementById('cards' + capitalize(status));
    const countEl = document.getElementById('pipe' + capitalize(status));
    const bugs = grouped[status];
    countEl.textContent = bugs.length;

    if (bugs.length === 0) {
      container.innerHTML = `<div class="pipeline-empty">${t('noBugs')}</div>`;
      continue;
    }
    container.innerHTML = bugs.map(b => renderBugCard(b)).join('');
  }
}

function renderBugCard(b) {
  const projName = allProjects.find(p => p.id === b.project_id)?.name_en || '';
  const isWontfix = b.status === 'wontfix';
  return `<div class="bug-card card-${esc(b.severity)}${isWontfix ? ' card-wontfix' : ''}"
               onclick="openBugPanel('${b.id}')">
    <div class="bug-card-title">${esc(b.title)}</div>
    <div class="bug-card-meta">
      <span class="bug-card-sev cs-${esc(b.severity)}">${t(b.severity)}</span>
      ${projName ? `<span class="bug-card-proj">${esc(projName)}</span>` : ''}
      ${b.feature ? `<span class="bug-card-feature">${esc(b.feature)}</span>` : ''}
      ${b.device_id ? `<span class="bug-device-badge">${esc(b.device_id)}</span>` : ''}
      ${(Array.isArray(b.issue_images) && b.issue_images.length) ? `<span class="bug-attach-count" title="${b.issue_images.length} attachment(s)">📎${b.issue_images.length}</span>` : ''}
      ${b.assignee ? `<span class="bug-card-assignee">${esc(b.assignee)}</span>` : ''}
    </div>
  </div>`;
}

function renderList() {
  const tbody = document.getElementById('bugTableBody');
  if (filteredBugs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8">
      <div class="empty-state"><div class="empty-icon">🐛</div>
      <div class="empty-text">${t('noBugs')}</div></div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = filteredBugs.map(b => {
    const projName = allProjects.find(p => p.id === b.project_id)?.name_en || '';
    const linkedCount = b.linked_tasks?.length || (b.task_id ? 1 : 0);
    return `<tr class="row-${esc(b.severity)}" onclick="openBugPanel('${b.id}')">
      <td><span class="table-sev">
        <span class="table-sev-dot sev-ind-${esc(b.severity)}"></span>
        ${t(b.severity)}
      </span></td>
      <td><span class="table-title">${esc(b.title)}</span></td>
      <td><span class="table-status ts-${esc(b.status)}">${t(b.status)}</span></td>
      <td><span class="table-assignee">${esc(b.assignee) || '—'}</span></td>
      <td>${esc(projName) || '—'}</td>
      <td><span class="table-feature">${esc(b.feature) || '—'}</span></td>
      <td>${linkedCount ? `<span class="table-tasks-count">${linkedCount}</span>` : '—'}</td>
      <td><span class="table-date">${esc(b.created_at?.substring(0, 10)) || ''}</span></td>
    </tr>`;
  }).join('');
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ── Bug detail panel ─────────────────────────────────────────────────────
async function openBugPanel(bugId) {
  const panel = document.getElementById('bugPanel');
  const content = document.getElementById('bugPanelContent');
  panel.classList.remove('hidden');

  content.innerHTML = '<div style="padding:60px;text-align:center;color:var(--text3)">' + t('loading') + '...</div>';

  let bug, linkedTasks, commentsData;
  try {
    [bug, linkedTasks, commentsData] = await Promise.all([
      api(`/api/bugs/${bugId}`),
      api(`/api/bugs/${bugId}/tasks`),
      api(`/api/comments/bug/${bugId}`),
    ]);
  } catch (e) {
    content.innerHTML = `<div style="padding:40px;color:var(--red)">Error: ${esc(e.message)}</div>`;
    return;
  }

  bugTaskCache[bugId] = linkedTasks;

  const projName = bug.project_name || allProjects.find(p => p.id === bug.project_id)?.name_en || '';
  const wsName = bug.workstream_name || '';

  const statusOpts = BUG_STATUSES.map(s =>
    `<option value="${s}" ${s === bug.status ? 'selected' : ''}>${t(s)}</option>`).join('');
  const sevOpts = BUG_SEVERITIES.map(s =>
    `<option value="${s}" ${s === bug.severity ? 'selected' : ''}>${t(s)}</option>`).join('');
  const assigneeOpts = '<option value="">—</option>' +
    allUsers.filter(u => u.role === 'human').map(u =>
      `<option value="${esc(u.name)}" ${u.name === bug.assignee ? 'selected' : ''}>${esc(u.display_name || u.name)}</option>`
    ).join('');

  const linkedTasksHtml = linkedTasks.length
    ? linkedTasks.map(lt => `
      <div class="linked-task-item">
        <span class="linked-task-status lts-${esc(lt.status)}"></span>
        <span class="linked-task-title">${esc(lt.title_en || lt.title_zh)}</span>
        <span class="linked-task-ws">${esc(lt.workstream_name || '')}</span>
        <button class="linked-task-unlink" onclick="unlinkTask('${bugId}','${lt.id}')" title="Unlink">✕</button>
      </div>`).join('')
    : `<div style="font-size:0.78rem;color:var(--text3);padding:4px 0">${t('noDependencies')}</div>`;

  content.innerHTML = `
    <button class="panel-close" onclick="closeBugPanel()">✕</button>

    <div class="panel-header">
      <div class="panel-title">${esc(bug.title)}</div>
      <div class="panel-meta">
        ${projName ? `<span class="panel-tag" style="background:var(--bg3);color:var(--text2)">${esc(projName)}</span>` : ''}
        ${wsName ? `<span class="panel-tag" style="background:var(--bg3);color:var(--text2)">${esc(wsName)}</span>` : ''}
        <span class="panel-tag" style="background:rgba(255,255,255,0.05);color:var(--text3);font-family:var(--font-mono);font-size:0.68rem">${esc(bug.id)}</span>
      </div>
    </div>

    <div class="panel-section">
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
        <div class="panel-field">
          <div class="panel-field-label">${t('status')}</div>
          <select class="panel-status-select" onchange="updateBug('${bugId}',{status:this.value})">${statusOpts}</select>
        </div>
        <div class="panel-field">
          <div class="panel-field-label">${t('severity')}</div>
          <select class="panel-sev-select" onchange="updateBug('${bugId}',{severity:this.value})">${sevOpts}</select>
        </div>
        <div class="panel-field">
          <div class="panel-field-label">${t('assignee')}</div>
          <select class="panel-assignee-select" onchange="updateBug('${bugId}',{assignee:this.value})">${assigneeOpts}</select>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">
        <div class="panel-field">
          <div class="panel-field-label">${t('reporter')}</div>
          <div class="panel-field-value mono">${esc(bug.reporter) || '—'}</div>
        </div>
        <div class="panel-field">
          <div class="panel-field-label">${t('created')}</div>
          <div class="panel-field-value mono">${esc(bug.created_at?.substring(0, 16)) || '—'}</div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:8px">
        ${bug.feature ? `<div class="panel-field">
          <div class="panel-field-label">${t('feature')}</div>
          <div class="panel-field-value">${esc(bug.feature)}</div>
        </div>` : ''}
        ${bug.repro_rate ? `<div class="panel-field">
          <div class="panel-field-label">${t('reproRate')}</div>
          <div class="panel-field-value">${esc(bug.repro_rate)}</div>
        </div>` : ''}
        ${bug.issue_time ? `<div class="panel-field">
          <div class="panel-field-label">${t('issueTime')}</div>
          <div class="panel-field-value mono">${esc(bug.issue_time)}</div>
        </div>` : ''}
        ${bug.device_id ? `<div class="panel-field">
          <div class="panel-field-label">${t('deviceId')}</div>
          <div class="panel-field-value"><span class="bug-device-badge">${esc(bug.device_id)}</span></div>
        </div>` : ''}
        ${bug.issue_version ? `<div class="panel-field">
          <div class="panel-field-label">${t('issueVersion')}</div>
          <div class="panel-field-value mono">${esc(bug.issue_version)}</div>
        </div>` : ''}
      </div>
    </div>

    ${bug.description ? `
    <div class="panel-section">
      <div class="panel-section-title">${t('description')}</div>
      <div class="panel-field-value">${esc(bug.description)}</div>
    </div>` : ''}

    ${bug.environment ? `
    <div class="panel-section">
      <div class="panel-section-title">${t('environment')}</div>
      <div class="panel-field-value mono">${esc(bug.environment)}</div>
    </div>` : ''}

    ${bug.steps_to_reproduce ? `
    <div class="panel-section">
      <div class="panel-section-title">${t('stepsToReproduce')}</div>
      <div class="panel-steps">${esc(bug.steps_to_reproduce)}</div>
    </div>` : ''}

    ${(Array.isArray(bug.issue_images) && bug.issue_images.length) ? `
    <div class="panel-section">
      <div class="panel-section-title">${t('issueImages')} (${bug.issue_images.length})</div>
      <div class="bug-attachments">
        ${bug.issue_images.map(att => `
          <a class="bug-attachment" target="_blank" rel="noopener"
             href="https://open.feishu.cn/open-apis/drive/v1/medias/${esc(att.file_token)}/download"
             title="${esc(att.name || att.file_token)}">
            <span class="bug-attachment-icon">${(att.type && att.type.startsWith('image/')) ? '🖼' : '📎'}</span>
            <span class="bug-attachment-name">${esc(att.name || att.file_token)}</span>
            ${att.size ? `<span class="bug-attachment-size">${_humanSize(att.size)}</span>` : ''}
          </a>
        `).join('')}
      </div>
      <div class="bug-attachment-hint">${t('attachmentsHint') || 'Opens in Feishu (requires login)'}</div>
    </div>` : ''}

    <div class="panel-section">
      <div class="panel-section-title">${t('linkToTask')} (${linkedTasks.length})</div>
      <div id="linkedTasksList">${linkedTasksHtml}</div>
      <div class="link-task-search">
        <input type="text" class="link-task-input" id="linkTaskSearch"
               placeholder="${t('searchTask')}" oninput="searchTasksToLink('${bugId}')">
      </div>
      <div id="linkTaskResults"></div>
    </div>

    <div class="panel-section">
      <div class="panel-section-title">${t('suggestedLinks')}</div>
      <div id="suggestedLinks">
        <button class="btn btn-sm" onclick="loadSuggestions('${bugId}')">${t('suggestLinks')}</button>
      </div>
    </div>

    <div class="panel-section">
      <div class="panel-section-title">${t('comments')} & ${t('activityTimeline')}</div>
      <div id="bugComments" style="max-height:260px;overflow-y:auto;margin-bottom:8px"></div>
      <div style="display:flex;gap:6px">
        <input type="text" id="bugCommentInput" class="link-task-input" placeholder="${t('addComment')}" style="flex:1"
               onkeydown="if(event.key==='Enter')postBugComment('${bugId}')">
        <button class="btn btn-sm btn-primary" onclick="postBugComment('${bugId}')">${t('send')}</button>
      </div>
    </div>

    <div class="panel-actions">
      <button class="btn btn-danger btn-sm" onclick="deleteBug('${bugId}')">${t('delete')}</button>
    </div>
  `;

  // Render comments + activity
  renderBugComments(commentsData);
}

function renderBugComments(data) {
  const el = document.getElementById('bugComments');
  if (!el) return;
  const items = [
    ...(data.comments || []).map(c => ({...c, _type:'comment'})),
    ...(data.activity || []).map(a => ({...a, _type:'activity', body: `${a.action}: ${a.detail||''}`})),
  ].sort((a,b) => (a.created_at||'').localeCompare(b.created_at||''));
  if (!items.length) {
    el.innerHTML = `<div style="color:var(--text3);font-size:0.8rem;padding:8px 0">${t('noComments')}</div>`;
    return;
  }
  el.innerHTML = items.map(it => it._type === 'comment'
    ? `<div style="padding:8px 10px;margin:4px 0;background:var(--bg2);border:1px solid rgba(255,255,255,0.04);border-radius:var(--radius-sm)">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px">
          <span style="font-weight:600;font-size:0.78rem;color:var(--accent-dim)">${esc(it.author)}</span>
          <span style="font-size:0.68rem;color:var(--text3);font-family:var(--font-mono)">${esc((it.created_at||'').substring(0,16))}</span>
        </div>
        <div style="font-size:0.82rem;color:var(--text);line-height:1.5;white-space:pre-wrap">${esc(it.body)}</div>
      </div>`
    : `<div style="padding:4px 10px;margin:2px 0;font-size:0.75rem;color:var(--text3)">
        <span style="font-weight:500">${esc(it.actor||'system')}</span> ${esc(it.body)}
        <span style="font-family:var(--font-mono);font-size:0.68rem;margin-left:6px">${esc((it.created_at||'').substring(0,16))}</span>
      </div>`
  ).join('');
  el.scrollTop = el.scrollHeight;
}

async function postBugComment(bugId) {
  const input = document.getElementById('bugCommentInput');
  const body = (input.value || '').trim();
  if (!body) return;
  try {
    await api(`/api/comments/bug/${bugId}`, 'POST', {body});
    input.value = '';
    const data = await api(`/api/comments/bug/${bugId}`);
    renderBugComments(data);
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  }
}

function closeBugPanel() {
  document.getElementById('bugPanel').classList.add('hidden');
}

// ── Bug CRUD ─────────────────────────────────────────────────────────────
async function updateBug(bugId, fields) {
  try {
    await api(`/api/bugs/${bugId}`, 'PUT', fields);
    // Refresh the bug in local cache
    const idx = allBugs.findIndex(b => b.id === bugId);
    if (idx >= 0) Object.assign(allBugs[idx], fields);
    applyBugFilters();
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

async function deleteBug(bugId) {
  if (!confirm(t('confirmDelete'))) return;
  try {
    await api(`/api/bugs/${bugId}`, 'DELETE');
    allBugs = allBugs.filter(b => b.id !== bugId);
    closeBugPanel();
    applyBugFilters();
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

function showCreateBug() {
  const projOpts = allProjects.map(p =>
    `<option value="${p.id}">${esc(p.name_en)}</option>`).join('');
  const sevOpts = BUG_SEVERITIES.map(s =>
    `<option value="${s}" ${s === 'medium' ? 'selected' : ''}>${t(s)}</option>`).join('');

  showModal(`
    <h2>${t('newBug')}</h2>
    <div class="form-group"><label>${t('title')}</label><input id="bugTitle"></div>
    <div class="form-group"><label>${t('description')}</label><textarea id="bugDesc" rows="3"></textarea></div>
    <div class="form-row">
      <div class="form-group"><label>${t('severity')}</label><select id="bugSev">${sevOpts}</select></div>
      <div class="form-group"><label>${t('projects')}</label><select id="bugProj"><option value="">—</option>${projOpts}</select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('assignee')}</label>
        <select id="bugAssignee"><option value="">—</option>${
          allUsers.filter(u => u.role === 'human').map(u =>
            `<option value="${esc(u.name)}">${esc(u.display_name || u.name)}</option>`
          ).join('')
        }</select>
      </div>
      <div class="form-group"><label>${t('environment')}</label><input id="bugEnv" placeholder="e.g. AGX Orin (unit-A), Ubuntu 22.04"></div>
    </div>
    <div class="form-group"><label>${t('stepsToReproduce')}</label><textarea id="bugSteps" rows="3"></textarea></div>
    <div class="form-row">
      <div class="form-group"><label>${t('feature')}</label><input id="bugFeature" placeholder="e.g. Navigation, Chassis"></div>
      <div class="form-group"><label>${t('reproRate')}</label><input id="bugReproRate" placeholder="e.g. 100%, sometimes"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('deviceId')}</label><input id="bugDeviceId" placeholder="e.g. 160, 162"></div>
      <div class="form-group"><label>${t('issueVersion')}</label><input id="bugIssueVersion" placeholder="e.g. v1.4.4"></div>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveBug()">${t('save')}</button>
    </div>
  `);
}

async function saveBug() {
  const title = document.getElementById('bugTitle').value.trim();
  if (!title) return showToast(t('titleRequired'), 'warning');
  try {
    const result = await api('/api/bugs', 'POST', {
      title,
      description: document.getElementById('bugDesc').value,
      severity: document.getElementById('bugSev').value,
      project_id: document.getElementById('bugProj').value || null,
      assignee: document.getElementById('bugAssignee').value || '',
      environment: document.getElementById('bugEnv').value,
      steps_to_reproduce: document.getElementById('bugSteps').value,
      feature: document.getElementById('bugFeature').value,
      repro_rate: document.getElementById('bugReproRate').value,
      device_id: document.getElementById('bugDeviceId').value,
      issue_version: document.getElementById('bugIssueVersion').value,
      reporter: currentUser,
    });
    closeModal();
    await loadData();
    openBugPanel(result.id);
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

// ── Task linking ─────────────────────────────────────────────────────────
let linkSearchTimeout = null;

async function searchTasksToLink(bugId) {
  const query = document.getElementById('linkTaskSearch').value.trim().toLowerCase();
  const resultsEl = document.getElementById('linkTaskResults');

  if (query.length < 2) {
    resultsEl.innerHTML = '';
    return;
  }

  clearTimeout(linkSearchTimeout);
  linkSearchTimeout = setTimeout(async () => {
    // Fetch all tasks and filter client-side (simple approach)
    try {
      const dashboard = await api('/api/dashboard');
      const linkedIds = new Set((bugTaskCache[bugId] || []).map(t => t.id));
      const results = [];

      for (const proj of dashboard) {
        for (const ws of proj.workstreams) {
          for (const task of ws.tasks) {
            if (linkedIds.has(task.id)) continue;
            const text = `${task.title_en} ${task.title_zh} ${task.assignee}`.toLowerCase();
            if (text.includes(query)) {
              results.push({ ...task, ws_title: ws.title_en, proj_name: proj.name_en });
            }
          }
        }
      }

      if (results.length === 0) {
        resultsEl.innerHTML = `<div style="font-size:0.75rem;color:var(--text3);padding:4px">${t('noResults')}</div>`;
      } else {
        resultsEl.innerHTML = results.slice(0, 8).map(r => `
          <div class="link-suggestion" onclick="linkTask('${bugId}','${r.id}')">
            <span class="linked-task-status lts-${esc(r.status)}"></span>
            <span class="link-suggestion-title">${esc(r.title_en || r.title_zh)}</span>
            <span class="link-suggestion-meta">${esc(r.proj_name)} / ${esc(r.ws_title)}</span>
          </div>
        `).join('');
      }
    } catch (e) {
      resultsEl.innerHTML = `<div style="color:var(--red);font-size:0.75rem">Error: ${esc(e.message)}</div>`;
    }
  }, 300);
}

async function linkTask(bugId, taskId) {
  try {
    await api(`/api/bugs/${bugId}/tasks`, 'POST', { task_ids: [taskId] });
    document.getElementById('linkTaskSearch').value = '';
    document.getElementById('linkTaskResults').innerHTML = '';
    openBugPanel(bugId); // Refresh panel
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

async function unlinkTask(bugId, taskId) {
  try {
    await api(`/api/bugs/${bugId}/tasks/${taskId}`, 'DELETE');
    openBugPanel(bugId); // Refresh panel
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

// ── AI suggestions ───────────────────────────────────────────────────────
async function loadSuggestions(bugId) {
  const el = document.getElementById('suggestedLinks');
  el.innerHTML = '<div style="color:var(--text3);font-size:0.78rem">' + t('analyzing') + '</div>';

  try {
    const suggestions = await api(`/api/bugs/${bugId}/suggest-links`);
    const linkedIds = new Set((bugTaskCache[bugId] || []).map(t => t.id));

    let html = '';
    if (suggestions.tasks.length) {
      const unlinked = suggestions.tasks.filter(t => !linkedIds.has(t.id));
      if (unlinked.length) {
        html += unlinked.slice(0, 6).map(task => `
          <div class="link-suggestion" onclick="linkTask('${bugId}','${task.id}')">
            <span class="link-suggestion-title">${esc(task.title)}</span>
            <span class="link-suggestion-meta">${esc(task.project_name)} (${task.score})</span>
          </div>
        `).join('');
      }
    }
    if (suggestions.workstreams.length) {
      html += suggestions.workstreams.slice(0, 3).map(ws => `
        <div class="link-suggestion" onclick="linkBugWorkstream('${bugId}','${ws.id}')">
          <span class="link-suggestion-title">${esc(ws.title)}</span>
          <span class="link-suggestion-meta">${esc(ws.project_name)} / ${t('workstreams')}</span>
        </div>
      `).join('');
    }
    if (!html) html = `<div style="font-size:0.78rem;color:var(--text3)">${t('noSuggestions')}</div>`;
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = `<div style="color:var(--red);font-size:0.78rem">Error: ${esc(e.message)}</div>`;
  }
}

async function linkBugWorkstream(bugId, wsId) {
  try {
    await api(`/api/bugs/${bugId}`, 'PUT', { workstream_id: wsId });
    const idx = allBugs.findIndex(b => b.id === bugId);
    if (idx >= 0) allBugs[idx].workstream_id = wsId;
    openBugPanel(bugId);
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

// ── Modal helpers ────────────────────────────────────────────────────────
function showModal(html) {
  document.getElementById('modalContent').innerHTML = html;
  document.getElementById('modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
}

// ── Theme toggle ─────────────────────────────────────────────────────────
function toggleTheme() {
  const isLight = document.documentElement.classList.toggle('light');
  localStorage.setItem('kanban-theme', isLight ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = isLight ? '🌙' : '☀️';
}

// ── Font Size ───────────────────────────────────────────────────────────
const _fontSizes = ['sm', 'md', 'lg', 'xl', 'xxl'];
const _fontLabels = { sm: 'A₁', md: 'A₂', lg: 'A₃', xl: 'A₄', xxl: 'A₅' };
const _fontClasses = ['font-sm', 'font-lg', 'font-xl', 'font-xxl'];

function cycleFontSize() {
  const cur = localStorage.getItem('kanban-font-size') || 'md';
  const idx = _fontSizes.indexOf(cur);
  const next = _fontSizes[(idx + 1) % _fontSizes.length];
  applyFontSize(next);
  localStorage.setItem('kanban-font-size', next);
}

function applyFontSize(size) {
  document.documentElement.classList.remove(..._fontClasses);
  if (size !== 'md') document.documentElement.classList.add('font-' + size);
  const btn = document.getElementById('fontSizeBtn');
  if (btn) btn.textContent = _fontLabels[size] || 'A₂';
}

// ── Language toggle ──────────────────────────────────────────────────────
function toggleLang() {
  currentLang = currentLang === 'en' ? 'zh' : 'en';
  localStorage.setItem('kanban-lang', currentLang);
  document.getElementById('langBtn').textContent = currentLang === 'en' ? '中文' : 'EN';
  applyI18n();
  populateFilters();
  applyBugFilters();
}

// ── User picker ──────────────────────────────────────────────────────────
async function showUserPicker() {
  let users = allUsers;
  if (!users.length) {
    try { users = await api('/api/users'); } catch (e) { users = []; }
  }
  const humanUsers = users.filter(u => u.role === 'human');

  const modal = document.getElementById('userModal');
  document.getElementById('userModalContent').innerHTML = `
    <h2>${t('selectUser')}</h2>
    <div class="form-group">
      <label>${t('userName')}</label>
      <input id="loginName" value="${esc(currentUser)}" placeholder="your.name">
    </div>
    ${humanUsers.length ? `
    <div class="form-group">
      <label>${t('existingUsers')}</label>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${humanUsers.map(u => `
          <button class="btn btn-sm" onclick="pickUser('${esc(u.name)}')">${esc(u.display_name || u.name)}</button>
        `).join('')}
      </div>
    </div>` : ''}
    <div class="form-actions">
      <button class="btn" onclick="document.getElementById('userModal').classList.add('hidden')">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="pickUser(document.getElementById('loginName').value.trim())">${t('login')}</button>
    </div>
  `;
  modal.classList.remove('hidden');
}

function pickUser(name) {
  if (!name) return;
  currentUser = name;
  localStorage.setItem('kanban-user', name);
  document.getElementById('userBtn').textContent = name;
  document.getElementById('userModal').classList.add('hidden');
}

// ── Keyboard shortcuts ───────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  // Escape closes panel/modal
  if (e.key === 'Escape') {
    if (!document.getElementById('bugPanel').classList.contains('hidden')) {
      closeBugPanel();
    } else if (!document.getElementById('modal').classList.contains('hidden')) {
      closeModal();
    } else if (!document.getElementById('userModal').classList.contains('hidden')) {
      document.getElementById('userModal').classList.add('hidden');
    }
    return;
  }
  // Don't trigger shortcuts when typing in inputs
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

  if (e.key === '/' || e.key === 'f' && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    document.getElementById('bugSearch').focus();
  }
  if (e.key === 'n' && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    showCreateBug();
  }
  if (e.key === '1') setView('pipeline');
  if (e.key === '2') setView('list');
  if (e.key === 'r' && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    loadData();
  }
});
