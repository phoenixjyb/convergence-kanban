// ── ConvergenceKanban — Frontend ─────────────────────────────────────────
const API = '';  // same origin

let dashboardData = [];
let expandedProjects = new Set(JSON.parse(localStorage.getItem('kanban-expanded') || '[]'));
let currentUser = localStorage.getItem('kanban-user') || '';
let viewMode = localStorage.getItem('kanban-view') || 'list';
let boardProject = localStorage.getItem('kanban-board-project') || '';
let swimlaneMode = localStorage.getItem('kanban-swimlane') || '';
let showAbandoned = localStorage.getItem('kanban-show-abandoned') === '1';
let filters = JSON.parse(localStorage.getItem('kanban-filters') || '{"search":"","status":"","statuses":[],"assignee":"","priority":"","dateFrom":"","dateTo":""}');

// ── API helpers ──────────────────────────────────────────────────────────
async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (currentUser) opts.headers['X-Kanban-User'] = currentUser;
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    if (resp.status === 401) {
      showToast('Please log in first / 请先登录', 'warning');
      showUserPicker();
      throw new Error('Login required');
    }
    const err = await resp.text();
    throw new Error(`API ${method} ${path}: ${resp.status} ${err}`);
  }
  return resp.json();
}

async function apiUpload(path, file) {
  const form = new FormData();
  form.append('file', file);
  const opts = { method: 'POST', headers: {}, body: form };
  if (currentUser) opts.headers['X-Kanban-User'] = currentUser;
  const resp = await fetch(API + path, opts);
  if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);
  return resp.json();
}

function formatMinutes(m) {
  if (!m) return '';
  const h = Math.floor(m / 60);
  const mins = m % 60;
  return h > 0 ? (mins > 0 ? `${h}h ${mins}m` : `${h}h`) : `${mins}m`;
}

function formatBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/(1024*1024)).toFixed(1) + ' MB';
}

// ── User picker ─────────────────────────────────────────────────────────
function showUserPicker() {
  const loggedIn = !!currentUser;
  showModal(`
    <h2>${t('selectUser')}</h2>
    ${loggedIn ? `<div style="margin-bottom:12px;padding:8px 12px;background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.2);border-radius:6px;font-size:0.85rem">
      Logged in as: <strong>${esc(currentUser)}</strong>
      <button class="btn btn-sm" style="margin-left:12px;color:var(--danger)" onclick="logoutUser()">Logout</button>
    </div>` : ''}
    <div id="userList" style="margin-bottom:12px"></div>
    <div style="border-top:1px solid var(--border);padding-top:10px;margin-top:10px">
      <div class="form-actions">
        <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      </div>
    </div>
    <div style="border-top:1px solid var(--border);padding-top:8px;margin-top:10px;font-size:0.78rem;color:var(--text3)">
      Tip: Send <strong>login</strong> to the Feishu bot for one-click login / 发送 <strong>登录</strong> 给飞书机器人一键登录
    </div>
  `);
  loadUserList();
}

async function loadUserList() {
  try {
    const users = await api('/api/users');
    const el = document.getElementById('userList');
    if (users.length) {
      const humanUsers = users.filter(u => u.role !== 'bot');
      el.innerHTML = '<div style="font-size:0.8rem;color:var(--text3);margin-bottom:6px">' + t('existingUsers') + ':</div>' +
        humanUsers.map(u => {
          const active = u.name === currentUser ? 'background:var(--accent);color:#000;' : '';
          return `<button class="btn btn-sm" style="margin:2px;${active}" onclick="pickUser('${esc(u.name)}','${esc(u.display_name || u.name)}')">${u.display_name || u.name}</button>`;
        }).join('');
    }
  } catch(e) { /* ignore */ }
}

function pickUser(name, displayName) {
  currentUser = name;
  localStorage.setItem('kanban-user', name);
  document.getElementById('userBtn').textContent = displayName;
  document.getElementById('notifBtn').style.display = '';
  closeModal();
  refreshDashboard();
}

function logoutUser() {
  currentUser = '';
  localStorage.removeItem('kanban-user');
  document.getElementById('userBtn').textContent = t('login');
  document.getElementById('notifBtn').style.display = 'none';
  closeModal();
  refreshDashboard();
}

async function createAndSetUser() {
  const name = document.getElementById('userNameInput').value.trim();
  if (!name) return showToast(t('nameRequired'), 'warning');
  currentUser = name;
  localStorage.setItem('kanban-user', name);
  await api('/api/users', 'POST', { name, display_name: name });
  document.getElementById('userBtn').textContent = name;
  document.getElementById('notifBtn').style.display = '';
  closeModal();
}

// ── Members / Users ──────────────────────────────────────────────────────
async function showMembers() {
  const users = await api('/api/users');
  // Count tasks per user from dashboard data
  const taskCounts = {};
  for (const p of dashboardData) {
    for (const ws of p.workstreams) {
      for (const task of ws.tasks) {
        if (!task.assignee) continue;
        if (!taskCounts[task.assignee]) taskCounts[task.assignee] = { doing: 0, done: 0, total: 0 };
        taskCounts[task.assignee].total++;
        if (task.status === 'done' || task.status === 'abandoned') taskCounts[task.assignee].done++;
        else if (task.status === 'doing' || task.status === 'in_review') taskCounts[task.assignee].doing++;
      }
    }
  }

  const cards = users.map(u => {
    const stats = taskCounts[u.name] || { doing: 0, done: 0, total: 0 };
    return `
    <div class="member-card">
      <div style="display:flex;justify-content:space-between;align-items:start">
        <div>
          <div class="member-name">${esc(u.display_name || u.name)}</div>
          <div style="font-size:0.72rem;color:var(--text3);font-family:var(--font-mono)">@${esc(u.name)}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="member-role role-${u.role}">${t(u.role)}</span>
          <button class="btn-ghost" onclick="event.stopPropagation();showEditMember('${u.id}')" title="${t('edit')}">✏</button>
        </div>
      </div>
      <div class="member-stats">
        <span>${t('tasksDoing')}: <strong>${stats.doing}</strong></span>
        <span>${t('tasksDone')}: <strong>${stats.done}</strong></span>
        <span>${t('tasks')}: <strong>${stats.total}</strong></span>
      </div>
      <div style="margin-top:6px;font-size:0.68rem;color:var(--text3)">
        ${u.feishu_open_id ? '✓ ' + t('feishuLinked') : ''}
        ${u.created_at ? ' · ' + t('joined') + ': ' + esc(u.created_at.substring(0, 10)) : ''}
      </div>
    </div>`;
  }).join('');

  showModal(`
    <h2>👥 ${t('members')} (${users.length})</h2>
    <div class="member-grid">${cards || `<p style="color:var(--text3)">${t('noMembers')}</p>`}</div>
    <div class="form-actions"><button class="btn" onclick="closeModal()">${t('close')}</button></div>
  `);
}

async function showEditMember(userId) {
  const users = await api('/api/users');
  const u = users.find(x => x.id === userId);
  if (!u) return;

  showModal(`
    <h2>${t('editMember')}: ${esc(u.name)}</h2>
    <div class="form-group"><label>${t('displayName')}</label><input id="memberDisplayName" value="${esc(u.display_name || u.name)}"></div>
    <div class="form-group"><label>${t('role')}</label>
      <select id="memberRole">
        <option value="human" ${u.role==='human'?'selected':''}>${t('human')}</option>
        <option value="bot" ${u.role==='bot'?'selected':''}>${t('bot')}</option>
      </select>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="showMembers()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="updateMember('${userId}')">${t('save')}</button>
    </div>
  `);
}

async function updateMember(userId) {
  await api(`/api/users/${userId}`, 'PUT', {
    display_name: document.getElementById('memberDisplayName').value,
    role: document.getElementById('memberRole').value,
  });
  showMembers();
}

// ── Notification Preferences ─────────────────────────────────────────────
async function showNotificationPrefs() {
  if (!currentUser) return showToast(t('login'), 'warning');
  // Resolve user ID from name
  const users = await api('/api/users');
  const u = users.find(x => x.name === currentUser);
  if (!u) return showToast('User not found', 'error');
  const prefs = await api(`/api/users/${u.id}/notifications`);

  const checked = v => v ? 'checked' : '';
  showModal(`
    <h2>🔔 ${t('notificationPrefs')}</h2>
    <div class="form-group" style="display:flex;justify-content:space-between;align-items:center">
      <label>${t('overdueAlerts')}</label>
      <input type="checkbox" id="notifOverdue" ${checked(prefs.overdue)}>
    </div>
    <div class="form-group" style="display:flex;justify-content:space-between;align-items:center">
      <label>${t('staleAlerts')}</label>
      <input type="checkbox" id="notifStale" ${checked(prefs.stale)}>
    </div>
    <div class="form-group" style="display:flex;justify-content:space-between;align-items:center">
      <label>${t('blockerAlerts')}</label>
      <input type="checkbox" id="notifBlocker" ${checked(prefs.blocker)}>
    </div>
    <div class="form-group" style="display:flex;justify-content:space-between;align-items:center">
      <label>${t('digestAlerts')}</label>
      <input type="checkbox" id="notifDigest" ${checked(prefs.digest)}>
    </div>
    <div class="form-group" style="display:flex;justify-content:space-between;align-items:center">
      <label>${t('staleDays')}</label>
      <input type="number" id="notifStaleDays" value="${prefs.stale_days || 3}" min="1" max="90" style="width:80px">
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveNotificationPrefs('${u.id}')">${t('save')}</button>
    </div>
  `);
}

async function saveNotificationPrefs(userId) {
  await api(`/api/users/${userId}/notifications`, 'PUT', {
    overdue: document.getElementById('notifOverdue').checked ? 1 : 0,
    stale: document.getElementById('notifStale').checked ? 1 : 0,
    blocker: document.getElementById('notifBlocker').checked ? 1 : 0,
    digest: document.getElementById('notifDigest').checked ? 1 : 0,
    stale_days: parseInt(document.getElementById('notifStaleDays').value) || 3,
  });
  showToast(t('notificationsSaved'), 'success');
  closeModal();
}

// ── Bin (trash) view ────────────────────────────────────────────────────
async function showBin() {
  const data = await api('/api/bin');
  const types = ['projects', 'workstreams', 'tasks', 'blockers'];
  const totalCount = types.reduce((s, tp) => s + data[tp].length, 0);

  let html = `<h2>${t('bin')} (${totalCount})</h2>`;
  if (totalCount === 0) {
    html += `<p style="color:var(--text3);padding:20px">${t('binEmpty')}</p>`;
  } else {
    for (const type of types) {
      if (!data[type].length) continue;
      html += `<h3 style="margin:12px 0 6px;font-size:0.85rem;color:var(--text2);text-transform:uppercase">${t(type)} (${data[type].length})</h3>`;
      for (const item of data[type]) {
        const label = item.name_en || item.title_en || item.description_en || item.id;
        html += `<div class="task-item">
          <span class="task-text" style="flex:1">${esc(label)}</span>
          <span style="font-size:0.7rem;color:var(--text3)">${item.deleted_at}</span>
          <button class="btn btn-sm" onclick="restoreItem('${type}','${item.id}')">${t('restore')}</button>
          <button class="btn btn-sm btn-danger" onclick="purgeItem('${type}','${item.id}')">${t('purge')}</button>
        </div>`;
      }
    }
  }
  html += `<div class="form-actions"><button class="btn" onclick="closeModal()">${t('close')}</button></div>`;
  showModal(html);
}

async function restoreItem(type, id) {
  await api(`/api/${type}/${id}/restore`, 'POST');
  await refreshDashboard();
  showBin();
}

async function purgeItem(type, id) {
  if (!confirm(t('confirmPurge'))) return;
  await api(`/api/${type}/${id}/purge`, 'DELETE');
  showBin();
}

// ── Stats bar ───────────────────────────────────────────────────────────
function renderStatsBar() {
  let totalTasks = 0, doneTasks = 0, doingTasks = 0, activeBlockers = 0, totalProjects = dashboardData.length;
  let overdueTasks = 0;
  const today = new Date().toISOString().slice(0, 10);
  for (const p of dashboardData) {
    for (const ws of p.workstreams) {
      totalTasks += ws.task_stats.total;
      doneTasks += ws.task_stats.done;
      doingTasks += (ws.task_stats.doing || 0);
      activeBlockers += ws.blockers.length;
      for (const t of ws.tasks) {
        if (t.due_date && t.due_date < today && t.status !== 'done' && t.status !== 'abandoned') overdueTasks++;
      }
    }
  }
  const pct = totalTasks > 0 ? Math.round(doneTasks / totalTasks * 100) : 0;
  document.getElementById('statsBar').innerHTML = `
    <div class="stat-card"><div class="stat-value">${totalProjects}</div><div class="stat-label">${t('projects')}</div></div>
    <div class="stat-card"><div class="stat-value">${totalTasks}</div><div class="stat-label">${t('tasks')}</div></div>
    <div class="stat-card"><div class="stat-value">${doingTasks}</div><div class="stat-label">${t('doing')}</div></div>
    <div class="stat-card stat-done"><div class="stat-value">${doneTasks}</div><div class="stat-label">${t('done')}</div></div>
    <div class="stat-card stat-completion"><div class="stat-value">${pct}%</div><div class="stat-label">${t('completion')}</div>
      <div class="progress-bar" style="width:100%;margin-top:4px"><div class="progress-fill" style="width:${pct}%"></div></div>
    </div>
    <div class="stat-card ${activeBlockers > 0 ? 'stat-blocked' : ''}"><div class="stat-value">${activeBlockers}</div><div class="stat-label">${t('activeBlockers')}</div></div>
    ${overdueTasks > 0 ? `<div class="stat-card stat-blocked"><div class="stat-value">${overdueTasks}</div><div class="stat-label">${t('overdue')}</div></div>` : ''}
  `;
}

// ── Filters ─────────────────────────────────────────────────────────────
function initFilters() {
  if (!filters.statuses) filters.statuses = [];
  if (!filters.dateFrom) filters.dateFrom = '';
  if (!filters.dateTo) filters.dateTo = '';
  document.getElementById('filterSearch').value = filters.search;
  document.getElementById('filterPriority').value = filters.priority;
  document.getElementById('filterSearch').placeholder = t('searchTasks');
  document.getElementById('filterDateFrom').value = filters.dateFrom;
  document.getElementById('filterDateTo').value = filters.dateTo;
  // Restore multi-select status checkboxes
  const checks = document.querySelectorAll('#statusDropdown input[type="checkbox"]');
  checks.forEach(cb => { cb.checked = filters.statuses.includes(cb.value); });
  updateStatusBtnLabel();
  loadFilterPresets();
}

function populateAssigneeFilter() {
  const assignees = new Set();
  for (const p of dashboardData) {
    for (const ws of p.workstreams) {
      for (const task of ws.tasks) {
        if (task.assignee) assignees.add(task.assignee);
      }
    }
  }
  const sel = document.getElementById('filterAssignee');
  const current = filters.assignee;
  sel.innerHTML = `<option value="">${t('allAssignees')}</option>` +
    [...assignees].sort().map(a => `<option value="${esc(a)}" ${a === current ? 'selected' : ''}>${esc(a)}</option>`).join('');
}

function toggleStatusDropdown() {
  document.getElementById('statusDropdown').classList.toggle('hidden');
}

function applyStatusMultiSelect() {
  const checks = document.querySelectorAll('#statusDropdown input[type="checkbox"]:checked');
  filters.statuses = [...checks].map(cb => cb.value);
  filters.status = '';  // clear legacy single-select
  updateStatusBtnLabel();
  applyFilters();
}

function updateStatusBtnLabel() {
  const btn = document.getElementById('filterStatusBtn');
  if (filters.statuses && filters.statuses.length > 0) {
    btn.textContent = filters.statuses.map(s => t(s)).join(', ');
  } else {
    btn.textContent = t('allStatuses');
  }
}

function applyFilters() {
  filters.search = document.getElementById('filterSearch').value;
  filters.assignee = document.getElementById('filterAssignee').value;
  filters.priority = document.getElementById('filterPriority').value;
  filters.dateFrom = document.getElementById('filterDateFrom').value;
  filters.dateTo = document.getElementById('filterDateTo').value;
  localStorage.setItem('kanban-filters', JSON.stringify(filters));
  const active = filters.search || (filters.statuses && filters.statuses.length) ||
    filters.assignee || filters.priority || filters.dateFrom || filters.dateTo;
  document.getElementById('clearFiltersBtn').style.display = active ? '' : 'none';
  renderDashboard();
}

function clearFilters() {
  filters = { search: '', status: '', statuses: [], assignee: '', priority: '', dateFrom: '', dateTo: '' };
  localStorage.setItem('kanban-filters', JSON.stringify(filters));
  document.getElementById('filterSearch').value = '';
  document.getElementById('filterAssignee').value = '';
  document.getElementById('filterPriority').value = '';
  document.getElementById('filterDateFrom').value = '';
  document.getElementById('filterDateTo').value = '';
  document.querySelectorAll('#statusDropdown input[type="checkbox"]').forEach(cb => { cb.checked = false; });
  updateStatusBtnLabel();
  document.getElementById('clearFiltersBtn').style.display = 'none';
  document.getElementById('filterPreset').value = '';
  renderDashboard();
}

function filterTasks(tasks) {
  return tasks.filter(t => {
    // Multi-status filter
    if (filters.statuses && filters.statuses.length > 0) {
      if (!filters.statuses.includes(t.status)) return false;
    } else if (filters.status && t.status !== filters.status) {
      return false;  // legacy single-select fallback
    }
    if (filters.assignee && t.assignee !== filters.assignee) return false;
    // Search — title, notes, and blocker descriptions
    if (filters.search) {
      const s = filters.search.toLowerCase();
      const match = (t.title_en || '').toLowerCase().includes(s) ||
                    (t.title_zh || '').toLowerCase().includes(s) ||
                    (t.notes || '').toLowerCase().includes(s);
      if (!match) return false;
    }
    // Date range — overlap check
    if (filters.dateFrom) {
      const taskEnd = t.due_date || t.start_date;
      if (taskEnd && taskEnd < filters.dateFrom) return false;
    }
    if (filters.dateTo) {
      const taskStart = t.start_date || t.due_date;
      if (taskStart && taskStart > filters.dateTo) return false;
    }
    return true;
  });
}

function filterWorkstreamByPriority(ws) {
  if (filters.priority && ws.priority !== filters.priority) return false;
  // If search is active, also check blocker descriptions
  if (filters.search) {
    const s = filters.search.toLowerCase();
    const blockerMatch = (ws.blockers || []).some(b =>
      (b.description_en || '').toLowerCase().includes(s) ||
      (b.description_zh || '').toLowerCase().includes(s)
    );
    if (blockerMatch) return true;  // keep workstream if blocker matches
  }
  return true;
}

// ── Filter Presets ──────────────────────────────────────────────────────
function getFilterPresets() {
  return JSON.parse(localStorage.getItem('kanban-filter-presets') || '[]');
}

function loadFilterPresets() {
  const presets = getFilterPresets();
  const sel = document.getElementById('filterPreset');
  if (!sel) return;
  sel.innerHTML = `<option value="">${t('filterPresets')}</option>` +
    presets.map((p, i) => `<option value="${i}">${esc(p.name)}</option>`).join('') +
    (presets.length ? `<option value="__delete">${t('deletePreset')}</option>` : '');
}

function saveFilterPreset() {
  const name = prompt(t('presetName'));
  if (!name) return;
  const presets = getFilterPresets();
  presets.push({ name, filters: {...filters} });
  localStorage.setItem('kanban-filter-presets', JSON.stringify(presets));
  loadFilterPresets();
}

function loadFilterPreset() {
  const sel = document.getElementById('filterPreset');
  const val = sel.value;
  if (val === '__delete') { deleteFilterPreset(); sel.value = ''; return; }
  if (val === '') return;
  const presets = getFilterPresets();
  const preset = presets[parseInt(val)];
  if (!preset) return;
  Object.assign(filters, preset.filters);
  if (!filters.statuses) filters.statuses = [];
  if (!filters.dateFrom) filters.dateFrom = '';
  if (!filters.dateTo) filters.dateTo = '';
  localStorage.setItem('kanban-filters', JSON.stringify(filters));
  initFilters();
  renderDashboard();
}

function deleteFilterPreset() {
  const presets = getFilterPresets();
  if (!presets.length) return;
  const name = prompt(t('presetName') + ' (' + presets.map(p => p.name).join(', ') + ')');
  if (!name) return;
  const idx = presets.findIndex(p => p.name === name);
  if (idx >= 0) {
    presets.splice(idx, 1);
    localStorage.setItem('kanban-filter-presets', JSON.stringify(presets));
  }
  loadFilterPresets();
}

// ── View toggle ─────────────────────────────────────────────────────────
function toggleViewMode() {
  viewMode = viewMode === 'list' ? 'board' : 'list';
  localStorage.setItem('kanban-view', viewMode);
  updateViewBtn();
  renderDashboard();
}

function updateViewBtn() {
  document.getElementById('viewBtn').textContent = viewMode === 'list' ? '☰' : '▦';
  document.getElementById('viewBtn').title = viewMode === 'list' ? t('boardView') : t('listView');
}

// ── Swimlane toggle ─────────────────────────────────────────────────────
function toggleSwimlane() {
  const cycle = ['', 'assignee', 'priority'];
  const idx = cycle.indexOf(swimlaneMode);
  swimlaneMode = cycle[(idx + 1) % cycle.length];
  localStorage.setItem('kanban-swimlane', swimlaneMode);
  renderDashboard();
}

function swimlaneBtnLabel() {
  if (swimlaneMode === 'assignee') return `≡ ${t('byAssignee')}`;
  if (swimlaneMode === 'priority') return `≡ ${t('byPriority')}`;
  return `≡ ${t('swimlane')}`;
}

function toggleShowAbandoned() {
  showAbandoned = !showAbandoned;
  localStorage.setItem('kanban-show-abandoned', showAbandoned ? '1' : '0');
  renderDashboard();
}

function groupCardsBySwimlane(cards) {
  const groups = {};
  const otherLabel = swimlaneMode === 'assignee' ? t('unassigned') : t('other');
  for (const card of cards) {
    let key;
    if (swimlaneMode === 'assignee') {
      key = card.assignee || '';
    } else {
      key = card.priority || '';
    }
    const label = key || otherLabel;
    if (!groups[label]) groups[label] = [];
    groups[label].push(card);
  }
  // Sort groups: named groups first alphabetically, then the "other/unassigned" group last
  const sortedKeys = Object.keys(groups).sort((a, b) => {
    if (a === otherLabel) return 1;
    if (b === otherLabel) return -1;
    if (swimlaneMode === 'priority') {
      const order = { critical: 0, high: 1, medium: 2, low: 3 };
      return (order[a] ?? 99) - (order[b] ?? 99);
    }
    return a.localeCompare(b);
  });
  return sortedKeys.map(k => ({ label: k, cards: groups[k] }));
}

// ── Dashboard rendering ──────────────────────────────────────────────────
async function refreshDashboard() {
  try {
    dashboardData = await api('/api/dashboard');
    renderStatsBar();
    populateAssigneeFilter();
    renderDashboard();
    updateConflictBadge();
  } catch (e) {
    console.error('Failed to refresh:', e);
  }
}

async function updateConflictBadge() {
  try {
    const cc = await api('/api/sync-conflicts/count');
    const btn = document.getElementById('conflictBtn');
    if (btn) {
      if (cc.unresolved > 0) {
        btn.style.display = '';
        document.getElementById('conflictCount').textContent = cc.unresolved;
      } else {
        btn.style.display = 'none';
      }
    }
  } catch(e) {}
}

async function renderDashboard() {
  const el = document.getElementById('dashboard');
  if (!dashboardData.length) {
    el.innerHTML = `<div style="text-align:center;padding:80px 20px;color:var(--text3)">
      <div style="font-size:3rem;margin-bottom:16px;opacity:0.5">📋</div>
      <p style="font-size:1.2rem;margin-bottom:8px">${t('noProjects')}</p>
      <p style="font-size:0.85rem;margin-bottom:16px">Create your first project to get started</p>
      <button class="btn btn-primary" onclick="showAddProject()">+ ${t('addProject')}</button>
    </div>`;
    applyI18n();
    return;
  }
  let hasContent;
  if (viewMode === 'board') {
    hasContent = renderBoardView(el);
  } else {
    hasContent = renderListView(el);
  }
  // Cross-search bugs when search finds no tasks (works in both views)
  if (!hasContent && filters.search) {
    await crossSearchBugs(el, filters.search);
  }
  applyI18n();
}

function renderListView(el) {
  const hasFilters = filters.search || filters.status || filters.assignee || filters.priority;
  let html = '';
  for (const p of dashboardData) {
    const filteredWs = p.workstreams.filter(ws => {
      if (!filterWorkstreamByPriority(ws)) return false;
      if (hasFilters && (filters.search || filters.status || filters.assignee)) {
        const ft = filterTasks(ws.tasks);
        if (ft.length === 0 && filters.search) return false;
      }
      return true;
    });
    if (hasFilters && filteredWs.length === 0) continue;
    html += renderProject(p, filteredWs);
  }
  el.innerHTML = html || `<div style="text-align:center;padding:40px;color:var(--text3)">${t('noResults')}</div>`;
  return !!html;
}

async function crossSearchBugs(el, search) {
  const s = search.toLowerCase();
  try {
    const bugs = await api('/api/bugs');
    const matched = bugs.filter(b => {
      const haystack = `${b.id} ${b.title} ${b.description || ''} ${b.reporter || ''} ${b.assignee || ''}`.toLowerCase();
      return haystack.includes(s);
    });
    if (matched.length > 0) {
      el.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text3)">
        <div style="margin-bottom:12px">${t('noResults')}</div>
        <div style="color:var(--accent);font-size:0.9rem">
          Found <strong>${matched.length}</strong> matching bug(s):
        </div>
        <div style="margin:12px auto;max-width:500px;text-align:left">
          ${matched.slice(0, 5).map(b => `<div style="padding:6px 10px;margin:4px 0;background:var(--bg2);border-radius:var(--radius-sm);border:1px solid rgba(255,255,255,0.06);cursor:pointer" onclick="window.location.href='/bugs?search=${encodeURIComponent(search)}'">
            <span style="color:var(--text)">${esc(b.title)}</span>
            <span style="font-family:var(--font-mono);font-size:0.72rem;color:var(--text3);margin-left:8px">${esc(b.id)}</span>
            <span style="font-size:0.72rem;padding:1px 6px;border-radius:3px;background:rgba(255,140,66,0.12);color:var(--orange);margin-left:4px">${esc(b.status)}</span>
          </div>`).join('')}
        </div>
        <a href="/bugs?search=${encodeURIComponent(search)}" style="color:var(--accent);font-size:0.85rem">View all on Bug Tracker &rarr;</a>
      </div>`;
    }
  } catch(e) { /* ignore cross-search errors */ }
}

function renderProject(p, filteredWs) {
  const expanded = expandedProjects.has(p.id);
  const wsCount = p.workstreams.length;
  const doneCount = p.stats.done;
  const blockedCount = p.stats.blocked;
  const inProgCount = p.stats.in_progress;
  const tp = p.task_progress || {total:0, done:0, pct:0};

  return `
  <div class="project-card" style="border-left-color:${p.color}">
    <div class="project-header" onclick="toggleProject('${p.id}')">
      <div>
        <span class="project-title">${tField(p, 'name')}</span>
        ${p.description ? `<span style="color:var(--text3);font-size:0.8rem;margin-left:12px">${esc(p.description)}</span>` : ''}
      </div>
      <div class="project-stats">
        <span class="stat">${wsCount} ${t('workstreams')}</span>
        ${inProgCount ? `<span class="stat" style="color:var(--blue)">●${inProgCount}</span>` : ''}
        ${blockedCount ? `<span class="stat" style="color:var(--red)">⚠${blockedCount}</span>` : ''}
        <span class="stat" style="color:var(--green)">✓${doneCount}/${wsCount}</span>
        ${tp.total ? `<span class="progress-indicator" title="${tp.done}/${tp.total} tasks done"><span class="progress-bar"><span class="progress-fill" style="width:${tp.pct}%"></span></span><span class="progress-text">${tp.pct}%</span></span>` : ''}
        <span style="font-size:0.9rem">${expanded ? '▼' : '▶'}</span>
      </div>
    </div>
    ${expanded ? `
    <div class="project-body">
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn btn-sm btn-primary" onclick="event.stopPropagation();showAddWorkstream('${p.id}')">${t('addWorkstream')}</button>
        <button class="btn btn-sm" onclick="event.stopPropagation();showEditProject('${p.id}')">${t('edit')}</button>
        <button class="btn btn-sm" onclick="event.stopPropagation();showImportDialog('${p.id}')">${t('importStatus')}</button>
      </div>
      ${(filteredWs || p.workstreams).length ? renderWorkstreamTable(filteredWs || p.workstreams) : `<p style="color:var(--text3);font-size:0.85rem">${t('noWorkstreams')}</p>`}
    </div>` : ''}
  </div>`;
}

function renderWorkstreamTable(workstreams) {
  return `<table class="ws-table">
    <thead><tr>
      <th style="width:24px"></th>
      <th>${t('title')}</th>
      <th>${t('owner')}</th>
      <th>${t('priority')}</th>
      <th>${t('status')}</th>
      <th>${t('progress')}</th>
      <th>${t('blockers')}</th>
    </tr></thead>
    <tbody id="wsSortContainer-${workstreams[0]?.project_id || ''}">${workstreams.map(renderWorkstreamRow).join('')}</tbody>
  </table>`;
}

function renderWorkstreamRow(ws) {
  const hasFilters = filters.search || filters.status || filters.assignee;
  const tasks = hasFilters ? filterTasks(ws.tasks) : ws.tasks;
  const total = hasFilters ? tasks.length : ws.task_stats.total;
  const done = hasFilters ? tasks.filter(t => t.status === 'done' || t.status === 'abandoned').length : ws.task_stats.done;
  const pct = total > 0 ? Math.round(done / total * 100) : 0;
  const blockerCount = ws.blockers.length;

  return `<tr data-sort-id="${ws.id}" draggable="true"
    ondragstart="sortDragStart(event,'${ws.id}','workstreams')"
    ondragover="sortDragOver(event,this)" ondragleave="sortDragLeave(event,this)"
    ondrop="sortDrop(event,'${ws.id}','wsSortContainer-${ws.project_id}')"
    onclick="showWorkstreamDetail('${ws.id}')">
    <td class="drag-handle-cell" onclick="event.stopPropagation()"><span class="drag-handle" title="Drag to reorder">⠿</span></td>
    <td data-label="${t('title')}"><strong>${tField(ws, 'title')}</strong></td>
    <td data-label="${t('owner')}" style="color:var(--text2)">${esc(ws.owner) || '—'}</td>
    <td data-label="${t('priority')}"><span class="priority-${ws.priority}">${t(ws.priority)}</span></td>
    <td data-label="${t('status')}"><span class="badge badge-${ws.status}">${t(ws.status)}</span></td>
    <td data-label="${t('progress')}">
      ${total > 0 ? `${done}/${total}
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>` : '—'}
    </td>
    <td data-label="${t('blockers')}">${blockerCount > 0 ? `<span style="color:var(--red)">⚠ ${blockerCount}</span>` : '✓'}</td>
  </tr>`;
}

// ── Board View ──────────────────────────────────────────────────────────
function renderBoardView(el) {
  // Project tabs
  if (!boardProject || !dashboardData.find(p => p.id === boardProject)) {
    boardProject = dashboardData[0].id;
  }
  const tabs = dashboardData.map(p =>
    `<button class="board-tab ${p.id === boardProject ? 'active' : ''}" onclick="switchBoardProject('${p.id}')">${tField(p, 'name')}</button>`
  ).join('');

  const project = dashboardData.find(p => p.id === boardProject);
  const columns = { todo: [], doing: [], in_review: [], done: [], blocked: [], abandoned: [] };

  for (const ws of project.workstreams) {
    if (!filterWorkstreamByPriority(ws)) continue;
    const tasks = filterTasks(ws.tasks);
    for (const task of tasks) {
      const col = columns[task.status] || columns.todo;
      col.push({ ...task, _wsTitle: tField(ws, 'title'), _wsColor: project.color });
    }
  }

  const colNames = { todo: t('todo'), doing: t('doing'), in_review: t('in_review'), done: t('done'), blocked: t('blocked'), abandoned: t('abandoned') };
  const colColors = { todo: 'var(--text3)', doing: 'var(--blue)', in_review: 'var(--orange)', done: 'var(--green)', blocked: 'var(--red)', abandoned: 'var(--text3)' };

  // Parse WIP limits
  const wipLimits = (() => { try { return JSON.parse(project.wip_limits || '{}'); } catch { return {}; } })();

  const swimBtn = `<button class="board-tab swimlane-btn ${swimlaneMode ? 'active' : ''}" onclick="toggleSwimlane()" title="${t('swimlane')}">${swimlaneBtnLabel()}</button>`;
  const wipBtn = `<button class="board-tab" onclick="showWipConfig('${project.id}')" title="${t('wipLimit')}">⚙ WIP</button>`;
  const abandonedBtn = `<button class="board-tab ${showAbandoned ? 'active' : ''}" onclick="toggleShowAbandoned()" title="${t('showAbandoned')}">${showAbandoned ? '☑' : '☐'} ${t('abandoned')}</button>`;
  let boardHtml = `<div class="board-tabs">${tabs}${swimBtn}${wipBtn}${abandonedBtn}</div><div class="board-container">`;
  const abandonedFilterActive = filters.statuses && filters.statuses.includes('abandoned');
  for (const [status, cards] of Object.entries(columns)) {
    if (status === 'abandoned' && !showAbandoned && !abandonedFilterActive) continue;
    let cardsHtml;
    if (swimlaneMode && cards.length > 0) {
      const groups = groupCardsBySwimlane(cards);
      cardsHtml = groups.map(g =>
        `<div class="swimlane-divider"><span>${esc(g.label)}</span></div>` +
        g.cards.map(c => renderBoardCard(c)).join('')
      ).join('');
    } else {
      cardsHtml = cards.map(c => renderBoardCard(c)).join('');
    }
    const wipLimit = wipLimits[status];
    const wipExceeded = wipLimit && cards.length > wipLimit;
    const wipBadge = wipLimit
      ? `<span class="wip-badge${wipExceeded ? ' wip-exceeded' : ''}">${cards.length}/${wipLimit}</span>`
      : `<span class="board-count">${cards.length}</span>`;
    boardHtml += `
    <div class="board-column${wipExceeded ? ' wip-over' : ''}" ondragover="event.preventDefault();this.classList.add('drag-over')" ondragleave="this.classList.remove('drag-over')" ondrop="boardDrop(event,'${status}');this.classList.remove('drag-over')">
      <div class="board-column-header" style="border-bottom-color:${colColors[status]}">
        <span>${colNames[status]}</span>${wipBadge}
      </div>
      <div class="board-cards">
        ${cardsHtml}
      </div>
    </div>`;
  }
  boardHtml += '</div>';
  el.innerHTML = boardHtml;
  const totalCards = Object.values(columns).reduce((sum, c) => sum + c.length, 0);
  return totalCards > 0;
}

function _dueBadge(task) {
  if (!task.due_date || task.status === 'done' || task.status === 'abandoned') return '';
  const due = new Date(task.due_date + 'T23:59:59');
  const now = new Date();
  const days = Math.ceil((due - now) / 86400000);
  if (days < 0) return `<span class="due-badge due-overdue" title="Overdue by ${-days}d">🔴 ${-days}d overdue</span>`;
  if (days <= 2) return `<span class="due-badge due-soon" title="Due in ${days}d">🟡 ${days}d left</span>`;
  return '';
}

function renderBoardCard(task) {
  const prioColors = { critical: 'var(--red)', high: 'var(--orange)', medium: 'var(--yellow)', low: 'var(--text3)' };
  const prioColor = prioColors[task.priority] || prioColors.medium;
  const dueBadge = _dueBadge(task);
  return `
  <div class="board-card" draggable="true" ondragstart="boardDragStart(event,'${task.id}')" data-task-id="${task.id}" ${task.notes ? `title="${esc(task.notes.substring(0, 200))}"` : ''}>
    <div class="board-card-header">
      <span class="board-card-ws">${esc(task._wsTitle)}</span>
      <span class="board-card-prio" style="color:${prioColor}">●</span>
    </div>
    <div class="board-card-title" onclick="event.stopPropagation();showTaskDetail('${task.id}')" style="cursor:pointer">${tField(task, 'title')}</div>
    ${task.subtask_count > 0 ? `<div style="font-size:0.7rem;color:var(--text2)">☐ ${task.subtask_done}/${task.subtask_count}</div>` : ''}
    <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:0.7rem">
      ${dueBadge}
      ${(task.dependencies||[]).some(d=>d.dep_status!=='done' && d.dep_status!=='abandoned') ? `<span style="color:var(--red);cursor:pointer" onclick="event.stopPropagation();showTaskDeps('${task.id}')">🔗 ${t('blocked')}</span>` : ''}
      ${task.time_logged ? `<span style="color:var(--green);cursor:pointer" onclick="event.stopPropagation();showTimeLog('${task.id}')">⏱${formatMinutes(task.time_logged)}</span>` : ''}
      <span style="color:var(--text2);cursor:pointer" onclick="event.stopPropagation();showTaskAttachments('${task.id}')">📎${task.attachment_count || 0}</span>
    </div>
    ${task.assignee ? `<div class="board-card-assignee">@${esc(task.assignee)}</div>` : ''}
    <div class="board-card-actions">
      <select class="task-status-select" onchange="boardMoveTask('${task.id}',this.value)" onclick="event.stopPropagation()">
        ${['todo','doing','in_review','done','blocked','abandoned'].map(s => `<option value="${s}" ${task.status===s?'selected':''}>${t(s)}</option>`).join('')}
      </select>
    </div>
  </div>`;
}

function switchBoardProject(pid) {
  boardProject = pid;
  localStorage.setItem('kanban-board-project', pid);
  renderDashboard();
}

async function showWipConfig(pid) {
  const limits = await api(`/api/projects/${pid}/wip-limits`);
  const statuses = ['todo', 'doing', 'in_review', 'done', 'blocked', 'abandoned'];
  const rows = statuses.map(s =>
    `<div class="form-row" style="align-items:center;gap:8px">
      <label style="min-width:80px">${t(s)}</label>
      <input id="wip-${s}" type="number" min="0" max="99" value="${limits[s] || ''}" placeholder="∞" style="width:70px">
    </div>`
  ).join('');
  showModal(`
    <h2>⚙ ${t('wipLimit')}</h2>
    <p style="color:var(--text3);font-size:0.85rem;margin-bottom:12px">Set max tasks per column (0 or empty = no limit)</p>
    ${rows}
    <div class="form-actions">
      <button class="btn btn-primary" onclick="saveWipConfig('${pid}')">${t('save')}</button>
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
    </div>`);
}

async function saveWipConfig(pid) {
  const limits = {};
  for (const s of ['todo', 'doing', 'in_review', 'done', 'blocked', 'abandoned']) {
    const v = parseInt(document.getElementById(`wip-${s}`).value);
    if (v > 0) limits[s] = v;
  }
  await api(`/api/projects/${pid}/wip-limits`, 'PUT', { limits });
  closeModal();
  showToast('WIP limits saved', 'success');
  await refreshDashboard();
}

let _dragTaskId = '';
function boardDragStart(ev, taskId) {
  _dragTaskId = taskId;
  ev.dataTransfer.effectAllowed = 'move';
  ev.target.classList.add('dragging');
  setTimeout(() => ev.target.classList.remove('dragging'), 0);
}

async function boardDrop(ev, newStatus) {
  ev.preventDefault();
  if (!_dragTaskId) return;
  await api(`/api/tasks/${_dragTaskId}`, 'PUT', { status: newStatus });
  _dragTaskId = '';
  await refreshDashboard();
}

async function boardMoveTask(taskId, newStatus) {
  const result = await api(`/api/tasks/${taskId}`, 'PUT', { status: newStatus });
  if (result.warnings && result.warnings.length > 0) {
    showToast(t('depWarning') + ': ' + result.warnings.join(', '), 'warning');
  }
  await refreshDashboard();
}

// ── Project expand/collapse ──────────────────────────────────────────────
function toggleProject(pid) {
  if (expandedProjects.has(pid)) expandedProjects.delete(pid);
  else expandedProjects.add(pid);
  localStorage.setItem('kanban-expanded', JSON.stringify([...expandedProjects]));
  renderDashboard();
}

// ── Modal helpers ────────────────────────────────────────────────────────
function showModal(html) {
  document.getElementById('modalContent').innerHTML = html;
  document.getElementById('modal').classList.remove('hidden');
  requestAnimationFrame(() => {
    const el = document.querySelector('#modalContent input, #modalContent select, #modalContent button');
    if (el) el.focus();
  });
}
function closeModal() {
  document.getElementById('modal').classList.add('hidden');
}

// ── Add/Edit Project ─────────────────────────────────────────────────────
function showAddProject() {
  showModal(`
    <h2>${t('newProject')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('nameEn')}</label><input id="pNameEn" placeholder="e.g. My Project"></div>
      <div class="form-group"><label>${t('nameZh')}</label><input id="pNameZh" placeholder="例如：示例项目"></div>
    </div>
    <div class="form-group"><label>${t('description')}</label><input id="pDesc"></div>
    <div class="form-group"><label>${t('color')}</label><input id="pColor" type="color" value="#00ddb3"></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveProject()">${t('save')}</button>
    </div>
  `);
}

async function saveProject() {
  const body = {
    name_en: document.getElementById('pNameEn').value,
    name_zh: document.getElementById('pNameZh').value,
    description: document.getElementById('pDesc').value,
    color: document.getElementById('pColor').value,
  };
  if (!body.name_en.trim()) return showToast(t('nameRequired'), 'warning');
  try {
    await api('/api/projects', 'POST', body);
    closeModal();
    refreshDashboard();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function showEditProject(pid) {
  const p = dashboardData.find(x => x.id === pid);
  if (!p) return;
  showModal(`
    <h2>${t('editProject')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('nameEn')}</label><input id="pNameEn" value="${esc(p.name_en)}"></div>
      <div class="form-group"><label>${t('nameZh')}</label><input id="pNameZh" value="${esc(p.name_zh)}"></div>
    </div>
    <div class="form-group"><label>${t('description')}</label><input id="pDesc" value="${esc(p.description)}"></div>
    <div class="form-group"><label>${t('color')}</label><input id="pColor" type="color" value="${p.color}"></div>
    <div class="form-actions">
      <button class="btn btn-danger" onclick="deleteProject('${pid}')">${t('delete')}</button>
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="updateProject('${pid}')">${t('save')}</button>
    </div>
  `);
}

async function updateProject(pid) {
  await api(`/api/projects/${pid}`, 'PUT', {
    name_en: document.getElementById('pNameEn').value,
    name_zh: document.getElementById('pNameZh').value,
    description: document.getElementById('pDesc').value,
    color: document.getElementById('pColor').value,
  });
  closeModal();
  refreshDashboard();
}

async function deleteProject(pid) {
  if (!confirm(t('confirmDelete'))) return;
  await api(`/api/projects/${pid}`, 'DELETE');
  closeModal();
  refreshDashboard();
}

// ── Add/Edit Workstream ──────────────────────────────────────────────────
function showAddWorkstream(projectId) {
  showModal(`
    <h2>${t('newWorkstream')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="wTitleEn"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="wTitleZh"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('owner')}</label><input id="wOwner"></div>
      <div class="form-group"><label>${t('priority')}</label>
        <select id="wPriority">
          <option value="critical">${t('critical')}</option>
          <option value="high">${t('high')}</option>
          <option value="medium" selected>${t('medium')}</option>
          <option value="low">${t('low')}</option>
        </select>
      </div>
      <div class="form-group"><label>${t('status')}</label>
        <select id="wStatus">
          <option value="planned">${t('planned')}</option>
          <option value="in-progress">${t('in-progress')}</option>
          <option value="blocked">${t('blocked')}</option>
          <option value="review">${t('review')}</option>
          <option value="done">${t('done')}</option>
          <option value="stable">${t('stable')}</option>
        </select>
      </div>
    </div>
    <div class="form-group"><label>${t('summaryEn')}</label><textarea id="wSummaryEn" rows="3"></textarea></div>
    <div class="form-group"><label>${t('summaryZh')}</label><textarea id="wSummaryZh" rows="2"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveWorkstream('${projectId}')">${t('save')}</button>
    </div>
  `);
}

async function saveWorkstream(projectId) {
  await api('/api/workstreams', 'POST', {
    project_id: projectId,
    title_en: document.getElementById('wTitleEn').value,
    title_zh: document.getElementById('wTitleZh').value,
    owner: document.getElementById('wOwner').value,
    priority: document.getElementById('wPriority').value,
    status: document.getElementById('wStatus').value,
    summary_en: document.getElementById('wSummaryEn').value,
    summary_zh: document.getElementById('wSummaryZh').value,
  });
  closeModal();
  refreshDashboard();
}

// ── Workstream Detail ────────────────────────────────────────────────────
async function showWorkstreamDetail(wid) {
  let ws = null;
  for (const p of dashboardData) {
    ws = p.workstreams.find(w => w.id === wid);
    if (ws) break;
  }
  if (!ws) return;

  const statusOptions = ['planned','in-progress','blocked','review','done','stable']
    .map(s => `<option value="${s}" ${ws.status===s?'selected':''}>${t(s)}</option>`).join('');
  const priorityOptions = ['critical','high','medium','low']
    .map(p => `<option value="${p}" ${ws.priority===p?'selected':''}>${t(p)}</option>`).join('');

  showModal(`
    <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:16px">
      <h2>${tField(ws, 'title')}</h2>
      <div style="display:flex;gap:6px">
        <select class="task-status-select" onchange="quickUpdateWs('${wid}','status',this.value)">${statusOptions}</select>
        <select class="task-status-select" onchange="quickUpdateWs('${wid}','priority',this.value)">${priorityOptions}</select>
        <button class="btn btn-sm" onclick="showEditWorkstream('${wid}')">${t('edit')}</button>
      </div>
    </div>

    ${ws.owner ? `<p style="font-size:0.85rem;color:var(--text2);margin-bottom:8px">${t('owner')}: <strong>${esc(ws.owner)}</strong></p>` : ''}

    <div class="ws-detail-summary">${tField(ws, 'summary') || '—'}</div>

    <!-- Blockers -->
    <div class="ws-detail-section">
      <h3>⚠ ${t('blockers')} (${ws.blockers.length})</h3>
      ${ws.blockers.length ? ws.blockers.map(b => `
        <div class="blocker-item">
          <div style="flex:1">
            <div>${tField(b, 'description')}</div>
            ${b.assignee ? `<div style="font-size:0.75rem;color:var(--text2);margin-top:2px">@${esc(b.assignee)}</div>` : ''}
            ${b.notes ? `<div style="font-size:0.75rem;color:var(--text3);margin-top:2px">${esc(b.notes)}</div>` : ''}
          </div>
          <button class="btn-ghost" onclick="showEditBlocker('${b.id}','${wid}')">✎</button>
          <button class="btn-ghost blocker-resolve" onclick="resolveBlocker('${b.id}','${wid}')">✓ ${t('resolve')}</button>
        </div>
      `).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noBlockers')}</p>`}
      <button class="btn btn-sm" style="margin-top:8px" onclick="showAddBlocker('${wid}')">${t('addBlocker')}</button>
    </div>

    <!-- Tasks -->
    <div class="ws-detail-section">
      <h3>📋 ${t('tasks')} (${ws.task_stats.done}/${ws.task_stats.total})</h3>
      <div id="taskSortContainer">
      ${ws.tasks.length ? ws.tasks.map(t => renderTaskItem(t)).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noTasks')}</p>`}
      </div>
      <button class="btn btn-sm" style="margin-top:8px" onclick="showAddTask('${wid}')">${t('addTask')}</button>
      <button class="btn btn-sm" style="margin-top:8px;margin-left:4px" onclick="showApplyTemplate('${wid}')">${t('fromTemplate')}</button>
      <button class="btn btn-sm" style="margin-top:8px;margin-left:4px" onclick="saveAsTemplate('${wid}')">${t('saveAsTemplate')}</button>
    </div>

    <!-- Attachments -->
    <div class="ws-detail-section">
      <h3>📎 ${t('attachments')}</h3>
      <div id="wsAttachments"></div>
      <input type="file" id="wsFileInput" style="display:none" onchange="uploadFile('workstream','${wid}','wsAttachments')">
      <button class="btn btn-sm" style="margin-top:8px" onclick="document.getElementById('wsFileInput').click()">${t('addAttachment')}</button>
    </div>

    <!-- Recurring Tasks -->
    <div class="ws-detail-section">
      <h3>🔄 ${t('recurringTasks')}</h3>
      <div id="recurringList"></div>
      <button class="btn btn-sm" style="margin-top:8px" onclick="showAddRecurring('${wid}')">${t('addRecurring')}</button>
    </div>

    <!-- Comments / Activity Timeline -->
    <div class="ws-detail-section">
      <h3>${t('comments')}</h3>
      <div id="wsComments" style="max-height:200px;overflow-y:auto"></div>
      <div style="display:flex;gap:8px;margin-top:8px">
        <textarea id="commentInput" rows="2" style="flex:1;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--bg3);border-radius:var(--radius);font-size:0.85rem;font-family:inherit" placeholder="${t('addComment')}..."></textarea>
        <button class="btn btn-sm btn-primary" onclick="postComment('workstream','${wid}','wsComments')" style="align-self:flex-end">${t('send')}</button>
      </div>
    </div>
  `);
  loadComments('workstream', wid, 'wsComments');
  loadAttachments('workstream', wid, 'wsAttachments');
  loadRecurringTasks(wid, 'recurringList');
}

function renderTaskItem(task, isSubtask = false) {
  const isDone = task.status === 'done';
  const statusOpts = ['todo','doing','in_review','done','blocked','abandoned']
    .map(s => `<option value="${s}" ${task.status===s?'selected':''}>${t(s)}</option>`).join('');
  const hasSubtasks = task.subtask_count > 0;
  const subtaskInfo = hasSubtasks ? `<span class="subtask-badge" onclick="event.stopPropagation();toggleSubtasks('${task.id}','${task.workstream_id}')" title="${t('subtasks')}">${task.subtask_done}/${task.subtask_count}</span>` : '';
  const deps = task.dependencies || [];
  const unmetDeps = deps.filter(d => d.dep_status !== 'done' && d.dep_status !== 'abandoned');
  const depInfo = deps.length > 0 ? `<span class="dep-badge${unmetDeps.length ? ' dep-unmet' : ''}" onclick="event.stopPropagation();showTaskDeps('${task.id}')" title="${t('dependencies')}">🔗${deps.length}</span>` : '';
  const timeInfo = task.time_logged ? `<span class="time-badge" onclick="event.stopPropagation();showTimeLog('${task.id}')" title="${t('timeLogged')}">⏱${formatMinutes(task.time_logged)}</span>` : '';
  const attachInfo = `<span class="attach-badge" onclick="event.stopPropagation();showTaskAttachments('${task.id}')" title="${t('attachments')}" style="cursor:pointer">📎${task.attachment_count || 0}</span>`;
  const dueInfo = _dueBadge(task);

  return `<div class="task-wrapper" data-task-id="${task.id}" data-sort-id="${task.id}"
    ${!isSubtask ? `draggable="true" ondragstart="sortDragStart(event,'${task.id}','tasks')" ondragover="sortDragOver(event,this)" ondragleave="sortDragLeave(event,this)" ondrop="sortDrop(event,'${task.id}','taskSortContainer')"` : ''}>
    <div class="task-item ${isSubtask ? 'subtask-item' : ''}">
      ${!isSubtask ? `<input type="checkbox" class="bulk-check" onclick="toggleTaskSelect('${task.id}',event)" ${selectedTasks.has(task.id)?'checked':''} style="margin-right:2px">` : ''}
      ${!isSubtask ? '<span class="drag-handle" title="Drag to reorder">⠿</span>' : ''}
      <span class="task-check" onclick="toggleTaskDone('${task.id}','${task.workstream_id}','${task.status}')">${isDone ? '☑' : '☐'}</span>
      <span class="task-text ${isDone?'done':''}" onclick="event.stopPropagation();showTaskDetail('${task.id}')" style="cursor:pointer">${tField(task, 'title')}</span>
      ${subtaskInfo}${depInfo}${timeInfo}${attachInfo}${dueInfo}
      ${task.assignee ? `<span class="task-assignee">@${esc(task.assignee)}</span>` : ''}
      <select class="task-status-select" onchange="updateTaskStatus('${task.id}','${task.workstream_id}',this.value)">${statusOpts}</select>
      ${!isSubtask ? `<button class="btn-ghost" onclick="event.stopPropagation();showAddSubtask('${task.id}','${task.workstream_id}')" title="${t('addSubtask')}">+</button>` : ''}
      <button class="btn-ghost" onclick="event.stopPropagation();deleteTask('${task.id}','${task.workstream_id}')" title="${t('delete')}">🗑</button>
    </div>
    ${!isSubtask ? `<div id="subtasks-${task.id}" class="subtask-list" style="display:none"></div>` : ''}
  </div>`;
}

// ── Task Detail ───────────────────────────────────────────────────────────
async function showTaskDetail(taskId) {
  let task = null, wsTitle = '', projectName = '';
  for (const p of dashboardData) {
    for (const ws of p.workstreams) {
      const found = ws.tasks.find(t => t.id === taskId);
      if (found) { task = found; wsTitle = tField(ws, 'title'); projectName = tField(p, 'name'); break; }
    }
    if (task) break;
  }
  if (!task) return;

  const statusOpts = ['todo','doing','in_review','done','blocked','abandoned']
    .map(s => `<option value="${s}" ${task.status===s?'selected':''}>${t(s)}</option>`).join('');
  const prioOpts = ['critical','high','medium','low']
    .map(p => `<option value="${p}" ${task.priority===p?'selected':''}>${t(p)}</option>`).join('');

  showModal(`
    <div class="task-detail-header">
      <h2>${tField(task, 'title')}</h2>
      <div style="display:flex;gap:6px;flex-shrink:0">
        <button class="btn btn-sm" onclick="showEditTask('${task.id}','${task.workstream_id}')">${t('edit')}</button>
        <button class="btn btn-sm btn-danger" onclick="deleteTask('${task.id}','${task.workstream_id}')">${t('delete')}</button>
      </div>
    </div>

    <div class="task-detail-meta">
      <div class="meta-item"><span class="meta-label">${t('status')}</span>
        <select class="task-status-select" onchange="updateTaskStatus('${task.id}','${task.workstream_id}',this.value);showTaskDetail('${task.id}')">${statusOpts}</select>
      </div>
      <div class="meta-item"><span class="meta-label">${t('priority')}</span>
        <select class="task-status-select" onchange="updateTaskPriority('${task.id}',this.value);showTaskDetail('${task.id}')">${prioOpts}</select>
      </div>
      ${task.assignee ? `<div class="meta-item"><span class="meta-label">${t('assignee')}</span> <span style="color:var(--accent);font-family:var(--font-mono)">@${esc(task.assignee)}</span></div>` : ''}
      ${task.start_date ? `<div class="meta-item"><span class="meta-label">${t('startDate')}</span> ${esc(task.start_date)}</div>` : ''}
      ${task.due_date ? `<div class="meta-item"><span class="meta-label">${t('dueDate')}</span> ${esc(task.due_date)}</div>` : ''}
    </div>

    <div style="font-size:0.75rem;color:var(--text3);margin-bottom:12px">${esc(projectName)} / ${esc(wsTitle)}</div>

    ${task.notes ? `<div class="task-detail-notes">${esc(task.notes)}</div>` : ''}

    <!-- Dependencies -->
    <div class="ws-detail-section">
      <h3>🔗 ${t('dependencies')} ${(task.dependencies||[]).length ? '(' + (task.dependencies||[]).length + ')' : ''}</h3>
      ${(task.dependencies||[]).length ? (task.dependencies||[]).map(d => `
        <div class="dep-item ${(d.dep_status !== 'done' && d.dep_status !== 'abandoned') ? 'dep-unmet' : 'dep-met'}">
          <span style="flex:1">${esc(d.dep_title || d.depends_on_id)}</span>
          <span class="badge badge-${d.dep_status === 'done' ? 'done' : d.dep_status === 'abandoned' ? 'abandoned' : 'planned'}">${t(d.dep_status || 'todo')}</span>
        </div>`).join('') : ''}
      <button class="btn btn-sm" style="margin-top:6px" onclick="showTaskDeps('${task.id}')">${t('addDependency')}</button>
    </div>

    <!-- Time Tracking -->
    <div class="ws-detail-section">
      <h3>⏱ ${t('timeTracking')} ${task.time_logged ? '(' + formatMinutes(task.time_logged) + ')' : ''}</h3>
      <button class="btn btn-sm" onclick="showTimeLog('${task.id}')">${t('logTime')}</button>
    </div>

    <!-- Attachments -->
    <div class="ws-detail-section">
      <h3>📎 ${t('attachments')} (${task.attachment_count || 0})</h3>
      <div id="taskDetailAttachments"></div>
      <input type="file" id="taskDetailFileInput" style="display:none" onchange="uploadFile('task','${task.id}','taskDetailAttachments')">
      <button class="btn btn-sm" style="margin-top:6px" onclick="document.getElementById('taskDetailFileInput').click()">${t('addAttachment')}</button>
    </div>

    <!-- Comments -->
    <div class="ws-detail-section">
      <h3>${t('comments')}</h3>
      <div id="taskDetailComments" style="max-height:200px;overflow-y:auto"></div>
      <div style="display:flex;gap:8px;margin-top:8px">
        <textarea id="commentInput" rows="2" style="flex:1;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--bg3);border-radius:var(--radius-sm);font-size:0.85rem;font-family:inherit" placeholder="${t('addComment')}..."></textarea>
        <button class="btn btn-sm btn-primary" onclick="postComment('task','${task.id}','taskDetailComments')" style="align-self:flex-end">${t('send')}</button>
      </div>
    </div>
  `);
  loadAttachments('task', task.id, 'taskDetailAttachments');
  loadComments('task', task.id, 'taskDetailComments');
}

async function showEditTask(tid, wid) {
  let task = null;
  for (const p of dashboardData) for (const ws of p.workstreams) {
    const found = ws.tasks.find(t => t.id === tid);
    if (found) { task = found; break; }
  }
  if (!task) return;

  const prioOpts = ['critical','high','medium','low']
    .map(p => `<option value="${p}" ${task.priority===p?'selected':''}>${t(p)}</option>`).join('');

  showModal(`
    <h2>${t('editTask')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="tTitleEn" value="${esc(task.title_en || '')}"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="tTitleZh" value="${esc(task.title_zh || '')}"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('assignee')}</label><input id="tAssignee" value="${esc(task.assignee || '')}"></div>
      <div class="form-group"><label>${t('priority')}</label><select id="tPriority">${prioOpts}</select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('startDate')}</label><input id="tStart" type="date" value="${task.start_date || ''}"></div>
      <div class="form-group"><label>${t('dueDate')}</label><input id="tDue" type="date" value="${task.due_date || ''}"></div>
    </div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="tNotes" rows="3">${esc(task.notes || '')}</textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="showTaskDetail('${tid}')">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="updateTask('${tid}','${wid}')">${t('save')}</button>
    </div>
  `);
}

async function updateTask(tid, wid) {
  await api(`/api/tasks/${tid}`, 'PUT', {
    title_en: document.getElementById('tTitleEn').value,
    title_zh: document.getElementById('tTitleZh').value,
    assignee: document.getElementById('tAssignee').value,
    priority: document.getElementById('tPriority').value,
    start_date: document.getElementById('tStart').value || null,
    due_date: document.getElementById('tDue').value || null,
    notes: document.getElementById('tNotes').value,
  });
  await refreshDashboard();
  showTaskDetail(tid);
}

async function updateTaskPriority(tid, priority) {
  await api(`/api/tasks/${tid}`, 'PUT', { priority });
  await refreshDashboard();
}

// ── Subtasks ──────────────────────────────────────────────────────────────
async function toggleSubtasks(taskId, wid) {
  const el = document.getElementById(`subtasks-${taskId}`);
  if (el.style.display !== 'none') {
    el.style.display = 'none';
    return;
  }
  const subtasks = await api(`/api/tasks/${taskId}/subtasks`);
  el.innerHTML = subtasks.map(st => renderTaskItem(st, true)).join('') ||
    `<div style="padding:4px 0 4px 28px;font-size:0.8rem;color:var(--text3)">${t('noSubtasks')}</div>`;
  el.style.display = 'block';
}

function showAddSubtask(parentId, wid) {
  showModal(`
    <h2>${t('addSubtask')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="tTitleEn"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="tTitleZh"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('assignee')}</label><input id="tAssignee"></div>
      <div class="form-group"><label>${t('dueDate')}</label><input id="tDue" type="date"></div>
    </div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="tNotes" rows="2"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveSubtask('${parentId}','${wid}')">${t('save')}</button>
    </div>
  `);
}

async function saveSubtask(parentId, wid) {
  await api('/api/tasks', 'POST', {
    workstream_id: wid,
    parent_task_id: parentId,
    title_en: document.getElementById('tTitleEn').value,
    title_zh: document.getElementById('tTitleZh').value,
    assignee: document.getElementById('tAssignee').value,
    due_date: document.getElementById('tDue').value || null,
    notes: document.getElementById('tNotes').value,
  });
  closeModal();
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

async function toggleTaskDone(tid, wid, currentStatus) {
  const newStatus = currentStatus === 'done' ? 'todo' : 'done';
  await api(`/api/tasks/${tid}`, 'PUT', { status: newStatus });
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

async function updateTaskStatus(tid, wid, status) {
  const result = await api(`/api/tasks/${tid}`, 'PUT', { status });
  if (result.warnings && result.warnings.length > 0) {
    showToast(t('depWarning') + ': ' + result.warnings.join(', '), 'warning');
  }
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

async function deleteTask(tid, wid) {
  await api(`/api/tasks/${tid}`, 'DELETE');
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

async function quickUpdateWs(wid, field, value) {
  await api(`/api/workstreams/${wid}`, 'PUT', { [field]: value });
  await refreshDashboard();
}

async function resolveBlocker(bid, wid) {
  await api(`/api/blockers/${bid}/resolve`, 'PUT');
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

// ── Edit Workstream ──────────────────────────────────────────────────────
function showEditWorkstream(wid) {
  let ws = null;
  for (const p of dashboardData) {
    ws = p.workstreams.find(w => w.id === wid);
    if (ws) break;
  }
  if (!ws) return;

  showModal(`
    <h2>${t('editWorkstream')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="wTitleEn" value="${esc(ws.title_en)}"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="wTitleZh" value="${esc(ws.title_zh)}"></div>
    </div>
    <div class="form-group"><label>${t('owner')}</label><input id="wOwner" value="${esc(ws.owner)}"></div>
    <div class="form-group"><label>${t('summaryEn')}</label><textarea id="wSummaryEn" rows="3">${esc(ws.summary_en)}</textarea></div>
    <div class="form-group"><label>${t('summaryZh')}</label><textarea id="wSummaryZh" rows="2">${esc(ws.summary_zh)}</textarea></div>
    <div class="form-actions">
      <button class="btn btn-danger" onclick="deleteWorkstream('${wid}')">${t('delete')}</button>
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="updateWorkstream('${wid}')">${t('save')}</button>
    </div>
  `);
}

async function updateWorkstream(wid) {
  await api(`/api/workstreams/${wid}`, 'PUT', {
    title_en: document.getElementById('wTitleEn').value,
    title_zh: document.getElementById('wTitleZh').value,
    owner: document.getElementById('wOwner').value,
    summary_en: document.getElementById('wSummaryEn').value,
    summary_zh: document.getElementById('wSummaryZh').value,
  });
  closeModal();
  refreshDashboard();
}

async function deleteWorkstream(wid) {
  if (!confirm(t('confirmDelete'))) return;
  await api(`/api/workstreams/${wid}`, 'DELETE');
  closeModal();
  refreshDashboard();
}

// ── Add Task ─────────────────────────────────────────────────────────────
function showAddTask(wid) {
  showModal(`
    <h2>${t('newTask')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="tTitleEn"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="tTitleZh"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('assignee')}</label><input id="tAssignee"></div>
      <div class="form-group"><label>${t('startDate')}</label><input id="tStart" type="date"></div>
      <div class="form-group"><label>${t('dueDate')}</label><input id="tDue" type="date"></div>
    </div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="tNotes" rows="2"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveTask('${wid}')">${t('save')}</button>
    </div>
  `);
}

async function saveTask(wid) {
  await api('/api/tasks', 'POST', {
    workstream_id: wid,
    title_en: document.getElementById('tTitleEn').value,
    title_zh: document.getElementById('tTitleZh').value,
    assignee: document.getElementById('tAssignee').value,
    start_date: document.getElementById('tStart').value || null,
    due_date: document.getElementById('tDue').value || null,
    notes: document.getElementById('tNotes').value,
  });
  closeModal();
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

// ── Add Blocker ──────────────────────────────────────────────────────────
function showAddBlocker(wid) {
  showModal(`
    <h2>${t('newBlocker')}</h2>
    <div class="form-group"><label>${t('descEn')}</label><textarea id="bDescEn" rows="2"></textarea></div>
    <div class="form-group"><label>${t('descZh')}</label><textarea id="bDescZh" rows="2"></textarea></div>
    <div class="form-group"><label>${t('assignee')}</label><input id="bAssignee" placeholder="${t('assignee')}"></div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="bNotes" rows="2"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveBlocker('${wid}')">${t('save')}</button>
    </div>
  `);
}

async function saveBlocker(wid) {
  await api('/api/blockers', 'POST', {
    workstream_id: wid,
    description_en: document.getElementById('bDescEn').value,
    description_zh: document.getElementById('bDescZh').value,
    assignee: document.getElementById('bAssignee').value,
    notes: document.getElementById('bNotes').value,
  });
  closeModal();
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

// ── Edit Blocker ─────────────────────────────────────────────────────────
function showEditBlocker(bid, wid) {
  // Find blocker in dashboard data
  let blocker = null;
  for (const p of dashboardData) for (const ws of p.workstreams) {
    const b = ws.blockers.find(x => x.id === bid);
    if (b) { blocker = b; break; }
  }
  if (!blocker) { showToast('Blocker not found', 'error'); return; }
  showModal(`
    <h2>${t('editBlocker') || 'Edit Blocker'}</h2>
    <div class="form-group"><label>${t('descEn')}</label><textarea id="bDescEn" rows="2">${esc(blocker.description_en || '')}</textarea></div>
    <div class="form-group"><label>${t('descZh')}</label><textarea id="bDescZh" rows="2">${esc(blocker.description_zh || '')}</textarea></div>
    <div class="form-group"><label>${t('assignee')}</label><input id="bAssignee" value="${esc(blocker.assignee || '')}"></div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="bNotes" rows="3">${esc(blocker.notes || '')}</textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="updateBlocker('${bid}','${wid}')">${t('save')}</button>
    </div>
  `);
}

async function updateBlocker(bid, wid) {
  await api(`/api/blockers/${bid}`, 'PUT', {
    description_en: document.getElementById('bDescEn').value,
    description_zh: document.getElementById('bDescZh').value,
    assignee: document.getElementById('bAssignee').value,
    notes: document.getElementById('bNotes').value,
  });
  closeModal();
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

// ── Import dialog ────────────────────────────────────────────────────────
function showImportDialog(projectId) {
  showModal(`
    <h2>${t('importStatus')}</h2>
    <div class="form-group">
      <label>${t('jsonLabel')}</label>
      <textarea id="importJson" rows="10" style="font-family:monospace;font-size:0.8rem"></textarea>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="doImport('${projectId}')">${t('import')}</button>
    </div>
  `);
}

async function doImport(projectId) {
  try {
    const data = JSON.parse(document.getElementById('importJson').value);
    const result = await api('/api/import/session-status', 'POST', { project_id: projectId, data });
    showToast(t('imported') + ' ' + result.imported + ' ' + t('importWorkstreams'), 'success');
    closeModal();
    refreshDashboard();
  } catch (e) {
    showToast('Import error: ' + e.message, 'error');
  }
}

// ── Activity panel ───────────────────────────────────────────────────────
async function toggleActivity() {
  const panel = document.getElementById('activityPanel');
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden')) {
    const items = await api('/api/activity?limit=50');
    document.getElementById('activityList').innerHTML = items.map(a => `
      <div class="activity-item">
        <span class="activity-action">${esc(a.actor)}</span> ${esc(a.action)} ${esc(a.entity_type)}
        ${a.detail ? `<br><span style="color:var(--text3)">${esc(a.detail.substring(0, 80))}</span>` : ''}
        <div class="activity-time">${esc(a.created_at)}</div>
      </div>
    `).join('') || `<p style="color:var(--text3);padding:20px">${t('noActivity')}</p>`;
  }
}

// ── Bug Reports ─────────────────────────────────────────────────────────
const BUG_STATUSES = ['open','investigating','fixing','fix_complete','to_verify','resolved','closed','wontfix'];
const BUG_SEVERITIES = ['critical','high','medium','low'];

async function showBugList() {
  const bugs = await api('/api/bugs');
  const projects = await api('/api/projects');
  const projMap = Object.fromEntries(projects.map(p => [p.id, p.name_en]));

  let rows = '';
  if (bugs.length === 0) {
    rows = `<p style="color:var(--text3);padding:20px">${t('noBugs')}</p>`;
  } else {
    rows = bugs.map(b => {
      const sevClass = b.severity === 'critical' ? 'sev-critical' : b.severity === 'high' ? 'sev-high' : '';
      const proj = b.project_id ? projMap[b.project_id] || '' : '';
      return `<div class="bug-item" onclick="showBugDetail('${b.id}')">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="severity-badge sev-${esc(b.severity)}">${t(b.severity)}</span>
          <span style="flex:1;font-weight:500">${esc(b.title)}</span>
          <span class="status-pill status-pill-${esc(b.status)}">${t(b.status)}</span>
        </div>
        <div style="font-size:0.75rem;color:var(--text3);margin-top:4px">
          ${proj ? esc(proj) + ' · ' : ''}${esc(b.reporter) || '?'} · ${esc(b.created_at?.substring(0,10)) || ''}
          ${b.workstream_id ? ' · ' + t('bugLinked') : ''}
        </div>
      </div>`;
    }).join('');
  }

  showModal(`
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2>🐛 ${t('bugReport')}</h2>
      <button class="btn btn-primary btn-sm" onclick="showAddBug()">+ ${t('newBug')}</button>
    </div>
    <div style="max-height:60vh;overflow-y:auto">${rows}</div>
    <div class="form-actions"><button class="btn" onclick="closeModal()">${t('close')}</button></div>
  `);
}

async function showAddBug() {
  const projects = await api('/api/projects');
  const projOpts = projects.map(p => `<option value="${p.id}">${esc(p.name_en)}</option>`).join('');
  const sevOpts = BUG_SEVERITIES.map(s => `<option value="${s}" ${s==='medium'?'selected':''}>${t(s)}</option>`).join('');

  showModal(`
    <h2>🐛 ${t('newBug')}</h2>
    <div class="form-group"><label>${t('title')}</label><input id="bugTitle"></div>
    <div class="form-group"><label>${t('description')}</label><textarea id="bugDesc" rows="3"></textarea></div>
    <div class="form-row">
      <div class="form-group"><label>${t('severity')}</label><select id="bugSev">${sevOpts}</select></div>
      <div class="form-group"><label>${t('projects')}</label><select id="bugProj"><option value="">--</option>${projOpts}</select></div>
    </div>
    <div class="form-group"><label>${t('environment')}</label><input id="bugEnv" placeholder="e.g. AGX Orin (unit-A), Ubuntu 22.04"></div>
    <div class="form-group"><label>${t('stepsToReproduce')}</label><textarea id="bugSteps" rows="3"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="showBugList()">${t('cancel')}</button>
      <button class="btn btn-primary" onclick="saveBug()">${t('save')}</button>
    </div>
  `);
}

async function saveBug() {
  const title = document.getElementById('bugTitle').value.trim();
  if (!title) return showToast(t('titleRequired'), 'warning');
  const result = await api('/api/bugs', 'POST', {
    title,
    description: document.getElementById('bugDesc').value,
    severity: document.getElementById('bugSev').value,
    project_id: document.getElementById('bugProj').value || null,
    environment: document.getElementById('bugEnv').value,
    steps_to_reproduce: document.getElementById('bugSteps').value,
    reporter: currentUser,
  });
  // After creating, show AI suggestions
  showBugDetail(result.id);
}

async function showBugDetail(bugId) {
  const bug = await api(`/api/bugs/${bugId}`);
  const statusOpts = BUG_STATUSES.map(s =>
    `<option value="${s}" ${s===bug.status?'selected':''}>${t(s)}</option>`
  ).join('');

  let linkedInfo = '';
  if (bug.workstream_name) linkedInfo += `<div>📎 ${t('linkToWorkstream')}: <strong>${esc(bug.workstream_name)}</strong></div>`;
  if (bug.task_name) linkedInfo += `<div>📎 ${t('linkToTask')}: <strong>${esc(bug.task_name)}</strong></div>`;

  showModal(`
    <h2>🐛 ${esc(bug.title)}</h2>
    <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">
      <span class="severity-badge sev-${esc(bug.severity)}">${esc(bug.severity)}</span>
      <select onchange="updateBugStatus('${bugId}',this.value)" style="font-size:0.85rem">${statusOpts}</select>
      <span style="color:var(--text3);font-size:0.8rem">${esc(bug.reporter)} · ${esc(bug.created_at?.substring(0,10))}</span>
    </div>
    ${bug.description ? `<div style="margin-bottom:8px">${esc(bug.description)}</div>` : ''}
    ${bug.environment ? `<div style="font-size:0.85rem;color:var(--text2);margin-bottom:4px">🖥 ${esc(bug.environment)}</div>` : ''}
    ${bug.steps_to_reproduce ? `<div style="font-size:0.85rem;white-space:pre-wrap;background:var(--bg2);padding:8px;border-radius:6px;margin-bottom:8px">${esc(bug.steps_to_reproduce)}</div>` : ''}
    ${linkedInfo ? `<div style="margin:8px 0;padding:8px;background:var(--bg2);border-radius:6px">${linkedInfo}</div>` : ''}
    <!-- Attachments -->
    <div class="ws-detail-section" style="margin-top:12px">
      <h3>📎 ${t('attachments')}</h3>
      <div id="bugAttachments"></div>
      <input type="file" id="bugFileInput" style="display:none" onchange="uploadFile('bug','${bugId}','bugAttachments')">
      <button class="btn btn-sm" style="margin-top:8px" onclick="document.getElementById('bugFileInput').click()">${t('addAttachment')}</button>
    </div>
    <div id="bugSuggestions" style="margin-top:12px"></div>
    <div class="form-actions">
      <button class="btn" onclick="showBugList()">${t('close')}</button>
      <button class="btn btn-primary" onclick="loadBugSuggestions('${bugId}')">${t('suggestLinks')}</button>
      <button class="btn btn-danger" onclick="if(confirm(t('confirmDelete'))){api('/api/bugs/${bugId}','DELETE').then(()=>showBugList())}">${t('delete')}</button>
    </div>
  `);
  loadAttachments('bug', bugId, 'bugAttachments');
}

async function updateBugStatus(bugId, status) {
  await api(`/api/bugs/${bugId}`, 'PUT', { status });
}

async function loadBugSuggestions(bugId) {
  const el = document.getElementById('bugSuggestions');
  el.innerHTML = `<p style="color:var(--text3)">${t('analyzing')}</p>`;
  const suggestions = await api(`/api/bugs/${bugId}/suggest-links`);

  let html = `<h3 style="font-size:0.9rem;margin-bottom:8px">${t('suggestedLinks')}</h3>`;

  if (!suggestions.workstreams.length && !suggestions.tasks.length) {
    html += `<p style="color:var(--text3)">${t('noSuggestions')}</p>`;
  } else {
    if (suggestions.workstreams.length) {
      html += `<div style="margin-bottom:8px"><strong>${t('workstreams')}:</strong></div>`;
      html += suggestions.workstreams.map(ws =>
        `<div class="suggestion-item" style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;margin:2px 0;background:var(--bg2);border-radius:4px">
          <span>${esc(ws.project_name)} / ${esc(ws.title)} <span style="color:var(--text3)">(score: ${ws.score})</span></span>
          <button class="btn btn-sm" onclick="linkBug('${bugId}','workstream_id','${ws.id}')">${t('link')}</button>
        </div>`
      ).join('');
    }
    if (suggestions.tasks.length) {
      html += `<div style="margin:8px 0 4px"><strong>${t('tasks')}:</strong></div>`;
      html += suggestions.tasks.map(task =>
        `<div class="suggestion-item" style="display:flex;justify-content:space-between;align-items:center;padding:4px 8px;margin:2px 0;background:var(--bg2);border-radius:4px">
          <span>${esc(task.project_name)} / ${esc(task.title)} <span style="color:var(--text3)">(score: ${task.score})</span></span>
          <button class="btn btn-sm" onclick="linkBug('${bugId}','task_id','${task.id}')">${t('link')}</button>
        </div>`
      ).join('');
    }
  }
  el.innerHTML = html;
}

async function linkBug(bugId, field, targetId) {
  const update = {};
  update[field] = targetId;
  await api(`/api/bugs/${bugId}`, 'PUT', update);
  showBugDetail(bugId);
}


// ── Util ─────────────────────────────────────────────────────────────────
function esc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }

// ── Theme toggle (A1) ───────────────────────────────────────────────────
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

// ── CSV Export (A3) ─────────────────────────────────────────────────────
function exportCSV() {
  const headers = ['Project','Workstream','Task','Assignee','Status','Priority','Start Date','Due Date','Notes'];
  const rows = [headers.join(',')];
  for (const p of dashboardData) {
    for (const ws of p.workstreams) {
      for (const task of ws.tasks) {
        rows.push([
          `"${(p.name_en||'').replace(/"/g,'""')}"`,
          `"${(ws.title_en||'').replace(/"/g,'""')}"`,
          `"${(task.title_en||'').replace(/"/g,'""')}"`,
          `"${(task.assignee||'').replace(/"/g,'""')}"`,
          task.status, ws.priority,
          task.start_date||'', task.due_date||'',
          `"${(task.notes||'').replace(/"/g,'""')}"`
        ].join(','));
      }
    }
  }
  const blob = new Blob(['\uFEFF' + rows.join('\n')], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `kanban-export-${new Date().toISOString().slice(0,10)}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

// ── Keyboard Shortcuts (A2) ─────────────────────────────────────────────
function showShortcutHelp() {
  const shortcuts = [
    ['/', t('shortcutSearch')], ['N', t('shortcutNewProject')],
    ['R', t('shortcutRefresh')], ['A', t('shortcutActivity')],
    ['B', t('shortcutBugs')], ['V', t('shortcutView')],
    ['T', 'Toggle theme'], ['F', 'Cycle font size'],
    ['Esc', t('shortcutClose')], ['?', t('shortcuts')],
  ];
  showModal(`<h2>${t('shortcuts')}</h2>
    <table class="shortcut-table">${shortcuts.map(([k,d]) =>
      `<tr><td><kbd>${k}</kbd></td><td>${esc(d)}</td></tr>`).join('')}
    </table>
    <div class="form-actions"><button class="btn" onclick="closeModal()">${t('close')}</button></div>`);
}

document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('modal');
  if (!modal.classList.contains('hidden')) {
    if (e.key === 'Escape') closeModal();
    return;
  }
  const tag = document.activeElement?.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
    if (e.key === 'Escape') document.activeElement.blur();
    return;
  }
  switch (e.key) {
    case '/': e.preventDefault(); document.getElementById('filterSearch').focus(); break;
    case 'n': case 'N': showAddProject(); break;
    case 'r': case 'R': refreshDashboard(); break;
    case 'a': case 'A': toggleActivity(); break;
    case 'b': case 'B': showBugList(); break;
    case 'v': case 'V': toggleViewMode(); break;
    case 't': case 'T': toggleTheme(); break;
    case 'f': case 'F': cycleFontSize(); break;
    case '?': showShortcutHelp(); break;
  }
});

// ── Bulk Operations (B3) ────────────────────────────────────────────────
let selectedTasks = new Set();

function toggleTaskSelect(taskId, e) {
  e.stopPropagation();
  if (selectedTasks.has(taskId)) selectedTasks.delete(taskId);
  else selectedTasks.add(taskId);
  updateBulkBar();
}

function updateBulkBar() {
  const bar = document.getElementById('bulkBar');
  if (selectedTasks.size > 0) {
    bar.style.display = 'flex';
    document.getElementById('bulkCount').textContent = `${selectedTasks.size} ${t('selected')}`;
  } else {
    bar.style.display = 'none';
  }
}

function bulkApplyStatus() {
  const status = document.getElementById('bulkStatus').value;
  if (!status) return;
  bulkAction('update', {status});
}

async function bulkAction(action, fields) {
  if (!selectedTasks.size) return;
  if (action === 'delete' && !confirm(t('confirmDelete'))) return;
  await api('/api/tasks/bulk', 'POST', {task_ids: [...selectedTasks], action, fields});
  bulkClear();
  await refreshDashboard();
}

function bulkClear() {
  selectedTasks.clear();
  updateBulkBar();
  document.querySelectorAll('.bulk-check').forEach(cb => cb.checked = false);
}

// ── Comments / Activity Timeline (B1) ───────────────────────────────────
async function loadComments(entityType, entityId, containerId) {
  try {
    const data = await api(`/api/comments/${entityType}/${entityId}`);
    const items = [
      ...data.comments.map(c => ({...c, _type:'comment'})),
      ...data.activity.map(a => ({...a, _type:'activity', body: `${a.action}: ${a.detail||''}`})),
    ].sort((a,b) => a.created_at.localeCompare(b.created_at));
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!items.length) { el.innerHTML = `<div style="color:var(--text3);font-size:0.8rem">${t('noComments')}</div>`; return; }
    el.innerHTML = items.map(it => it._type === 'comment'
      ? `<div class="comment-item"><span class="comment-author">${esc(it.author)}</span> <span class="comment-time">${it.created_at}</span><div>${esc(it.body)}</div></div>`
      : `<div class="activity-timeline-item">${esc(it.actor||'system')} ${esc(it.body)} <span class="comment-time">${it.created_at}</span></div>`
    ).join('');
    el.scrollTop = el.scrollHeight;
  } catch(e) { console.error('loadComments', e); }
}

async function postComment(entityType, entityId, containerId) {
  const input = document.getElementById('commentInput');
  const body = input.value.trim();
  if (!body) return;
  await api(`/api/comments/${entityType}/${entityId}`, 'POST', {body});
  input.value = '';
  loadComments(entityType, entityId, containerId);
}

// ── Drag-and-Drop Reorder (B2) ──────────────────────────────────────────
let _sortDragId = '';
let _sortDragType = '';

function sortDragStart(e, id, type) {
  _sortDragId = id;
  _sortDragType = type;
  e.dataTransfer.effectAllowed = 'move';
  const row = e.target.closest('.task-item') || e.target.closest('tr');
  row?.classList.add('dragging');
}

function sortDragOver(e, targetEl) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  // Show drop indicator
  document.querySelectorAll('.drag-over-above,.drag-over-below').forEach(el => el.classList.remove('drag-over-above','drag-over-below'));
  const rect = targetEl.getBoundingClientRect();
  const mid = rect.top + rect.height / 2;
  targetEl.classList.add(e.clientY < mid ? 'drag-over-above' : 'drag-over-below');
}

function sortDragLeave(e, targetEl) {
  targetEl.classList.remove('drag-over-above', 'drag-over-below');
}

async function sortDrop(e, targetId, containerId) {
  e.preventDefault();
  document.querySelectorAll('.drag-over-above,.drag-over-below,.dragging').forEach(el =>
    el.classList.remove('drag-over-above','drag-over-below','dragging'));
  if (!_sortDragId || _sortDragId === targetId) return;
  const container = document.getElementById(containerId);
  if (!container) return;
  const ids = [...container.querySelectorAll('[data-sort-id]')].map(el => el.dataset.sortId);
  const fromIdx = ids.indexOf(_sortDragId);
  const toIdx = ids.indexOf(targetId);
  if (fromIdx < 0 || toIdx < 0) return;
  ids.splice(fromIdx, 1);
  ids.splice(toIdx, 0, _sortDragId);
  const items = ids.map((id, i) => ({id, sort_order: i * 10}));
  await api(`/api/${_sortDragType}/reorder`, 'PUT', {items});
  _sortDragId = '';
  await refreshDashboard();
}

// ── Templates (B1) ──────────────────────────────────────────────────────
async function saveAsTemplate(wid) {
  let ws = null;
  for (const p of dashboardData) {
    ws = p.workstreams.find(w => w.id === wid);
    if (ws) break;
  }
  if (!ws) return;
  const name = prompt(t('templateName'), tField(ws, 'title') + ' Template');
  if (!name) return;
  const structure = ws.tasks.map(task => ({
    title_en: task.title_en, title_zh: task.title_zh || '',
    status: 'todo', assignee: task.assignee || '',
    notes: task.notes || '', subtasks: []
  }));
  await api('/api/templates', 'POST', { name, project_id: ws.project_id, structure });
  showToast(t('templateSaved'), 'success');
}

async function showApplyTemplate(wid) {
  const templates = await api('/api/templates');
  if (!templates.length) { showToast(t('noTemplates'), 'info'); return; }
  let html = `<h2>${t('applyTemplate')}</h2>`;
  html += templates.map(tmpl =>
    `<div class="task-item" style="cursor:pointer" onclick="applyTemplate('${tmpl.id}','${wid}')">
      <span class="task-text"><strong>${esc(tmpl.name)}</strong>
        <span style="color:var(--text3);font-size:0.8rem">(${tmpl.structure.length} ${t('tasks')})</span>
      </span>
      <button class="btn-ghost btn-danger" onclick="event.stopPropagation();deleteTemplate('${tmpl.id}')" title="${t('delete')}">🗑</button>
    </div>`
  ).join('');
  html += `<div class="form-actions"><button class="btn" onclick="closeModal()">${t('cancel')}</button></div>`;
  showModal(html);
}

async function applyTemplate(templateId, wid) {
  await api(`/api/templates/${templateId}/apply`, 'POST', { workstream_id: wid });
  closeModal();
  await refreshDashboard();
  showWorkstreamDetail(wid);
}

async function deleteTemplate(templateId) {
  if (!confirm(t('confirmDelete'))) return;
  await api(`/api/templates/${templateId}`, 'DELETE');
  closeModal();
}

// ── Analytics (B2) ──────────────────────────────────────────────────────
async function showAnalytics() {
  showModal(`
    <h2>${t('analytics')}</h2>
    <div style="margin-bottom:12px">
      <select id="analyticsDays" onchange="refreshAnalytics()" class="filter-select" style="width:auto">
        <option value="7">7 ${t('days')}</option>
        <option value="14">14 ${t('days')}</option>
        <option value="30" selected>30 ${t('days')}</option>
        <option value="90">90 ${t('days')}</option>
      </select>
    </div>
    <div id="analyticsContent" style="min-height:200px">
      <p style="color:var(--text3)">${t('loading')}...</p>
    </div>
    <div class="form-actions" style="margin-top:12px">
      <button class="btn btn-sm" onclick="captureSnapshot()">${t('captureSnapshot')}</button>
      <button class="btn" onclick="closeModal()">${t('close')}</button>
    </div>
  `);
  refreshAnalytics();
}

async function captureSnapshot() {
  await api('/api/analytics/snapshot', 'POST');
  refreshAnalytics();
}

async function refreshAnalytics() {
  const days = document.getElementById('analyticsDays')?.value || 30;
  const el = document.getElementById('analyticsContent');
  if (!el) return;

  // Compute live stats
  const statusCounts = { todo: 0, doing: 0, in_review: 0, done: 0, blocked: 0, abandoned: 0 };
  const assigneeCounts = {};
  for (const p of dashboardData) {
    for (const ws of p.workstreams) {
      for (const task of ws.tasks) {
        statusCounts[task.status] = (statusCounts[task.status] || 0) + 1;
        if (task.assignee) assigneeCounts[task.assignee] = (assigneeCounts[task.assignee] || 0) + 1;
      }
    }
  }

  let html = '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px">';
  html += `<div style="flex:1;min-width:200px"><h3 style="font-size:0.85rem;margin-bottom:8px;color:var(--text2)">${t('statusDistribution')}</h3><canvas id="statusPie" width="200" height="200"></canvas></div>`;
  html += `<div style="flex:1;min-width:250px"><h3 style="font-size:0.85rem;margin-bottom:8px;color:var(--text2)">${t('tasksByAssignee')}</h3><canvas id="assigneeBar" width="300" height="200"></canvas></div>`;
  html += '</div>';
  html += `<div><h3 style="font-size:0.85rem;margin-bottom:8px;color:var(--text2)">${t('burndown')}</h3><canvas id="burndownChart" width="600" height="250" style="width:100%;max-width:600px"></canvas></div>`;
  el.innerHTML = html;

  drawPieChart('statusPie', statusCounts);
  drawBarChart('assigneeBar', assigneeCounts);

  try {
    const snapshots = await api(`/api/analytics?days=${days}`);
    if (snapshots.length) {
      drawBurndown('burndownChart', snapshots);
    } else {
      document.getElementById('burndownChart').parentElement.innerHTML +=
        `<p style="color:var(--text3);font-size:0.8rem">${t('noSnapshots')}</p>`;
    }
  } catch (e) { console.error('Analytics:', e); }
}

function drawPieChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const colors = { todo: '#8899aa', doing: '#4facfe', in_review: '#fbbf24', done: '#00ddb3', blocked: '#ff4757', abandoned: '#5a6470' };
  const total = Object.values(data).reduce((s, v) => s + v, 0);
  if (total === 0) return;
  let startAngle = -Math.PI / 2;
  const cx = 100, cy = 100, r = 80;
  for (const [status, count] of Object.entries(data)) {
    if (count === 0) continue;
    const sliceAngle = (count / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, startAngle, startAngle + sliceAngle);
    ctx.fillStyle = colors[status] || '#666';
    ctx.fill();
    const midAngle = startAngle + sliceAngle / 2;
    const lx = cx + Math.cos(midAngle) * (r * 0.6);
    const ly = cy + Math.sin(midAngle) * (r * 0.6);
    ctx.fillStyle = '#fff';
    ctx.font = '11px Outfit, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`${t(status)} ${count}`, lx, ly);
    startAngle += sliceAngle;
  }
}

function drawBarChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return;
  const maxVal = Math.max(...entries.map(e => e[1]));
  const barH = 20, gap = 6, leftPad = 80;
  canvas.height = entries.length * (barH + gap) + 10;
  const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#e2e8f0';
  entries.forEach(([name, count], i) => {
    const y = i * (barH + gap) + 5;
    const barW = (count / maxVal) * (canvas.width - leftPad - 40);
    ctx.fillStyle = '#00ddb3';
    ctx.fillRect(leftPad, y, barW, barH);
    ctx.fillStyle = textColor;
    ctx.font = '11px Outfit, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(name, leftPad - 6, y + 15);
    ctx.textAlign = 'left';
    ctx.fillText(count.toString(), leftPad + barW + 4, y + 15);
  });
}

function drawBurndown(canvasId, snapshots) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const pad = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  const remaining = snapshots.map(s => s.totals.total - s.totals.done);
  const maxR = Math.max(...remaining, 1);
  const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text2').trim() || '#94a3b8';

  // Axes
  ctx.strokeStyle = '#1a2530';
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, h - pad.bottom);
  ctx.lineTo(w - pad.right, h - pad.bottom);
  ctx.stroke();

  // Line
  ctx.strokeStyle = '#00ddb3';
  ctx.lineWidth = 2;
  ctx.beginPath();
  snapshots.forEach((s, i) => {
    const x = pad.left + (i / Math.max(snapshots.length - 1, 1)) * plotW;
    const y = pad.top + (1 - remaining[i] / maxR) * plotH;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Dots
  ctx.fillStyle = '#00ddb3';
  snapshots.forEach((s, i) => {
    const x = pad.left + (i / Math.max(snapshots.length - 1, 1)) * plotW;
    const y = pad.top + (1 - remaining[i] / maxR) * plotH;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  // X-axis labels
  ctx.fillStyle = textColor;
  ctx.font = '10px Outfit, sans-serif';
  ctx.textAlign = 'center';
  const step = Math.max(1, Math.floor(snapshots.length / 6));
  snapshots.forEach((s, i) => {
    if (i % step === 0 || i === snapshots.length - 1) {
      const x = pad.left + (i / Math.max(snapshots.length - 1, 1)) * plotW;
      ctx.fillText(s.date.substring(5), x, h - pad.bottom + 15);
    }
  });

  // Y-axis labels
  ctx.textAlign = 'right';
  ctx.fillText(maxR.toString(), pad.left - 6, pad.top + 10);
  ctx.fillText('0', pad.left - 6, h - pad.bottom);
}

// ── Mobile helpers ───────────────────────────────────────────────────────
function toggleMobileMenu() {
  document.getElementById('headerActions').classList.toggle('mobile-open');
}
function toggleFilterBar() {
  document.getElementById('filterBar').classList.toggle('mobile-hidden');
}
// Close dropdowns on outside click
document.addEventListener('click', (e) => {
  // Status multi-select dropdown
  const dd = document.getElementById('statusDropdown');
  const btn = document.getElementById('filterStatusBtn');
  if (dd && !dd.classList.contains('hidden') && !dd.contains(e.target) && e.target !== btn) {
    dd.classList.add('hidden');
  }
  // Mobile menu
  const actions = document.getElementById('headerActions');
  const hamburger = document.getElementById('hamburgerBtn');
  if (actions && actions.classList.contains('mobile-open') && !actions.contains(e.target) && e.target !== hamburger) {
    actions.classList.remove('mobile-open');
  }
});

// ── Task Dependencies ────────────────────────────────────────────────────
async function showTaskDeps(taskId) {
  const data = await api(`/api/tasks/${taskId}/dependencies`);
  const allTasks = [];
  for (const p of dashboardData) for (const ws of p.workstreams) for (const t of ws.tasks) allTasks.push(t);
  const task = allTasks.find(t => t.id === taskId);
  const taskTitle = task ? tField(task, 'title') : taskId;

  const renderDep = (d, canRemove) => `
    <div class="dep-item ${(d.status !== 'done' && d.status !== 'abandoned') ? 'dep-unmet' : 'dep-met'}">
      <span style="flex:1">${tField(d, 'title') || esc(d.title_en)} <span class="badge badge-${d.status === 'done' ? 'done' : d.status === 'abandoned' ? 'abandoned' : d.status === 'in_review' ? 'in_review' : d.status === 'doing' ? 'in-progress' : 'planned'}">${t(d.status)}</span></span>
      ${canRemove ? `<button class="btn-ghost" onclick="removeDep('${taskId}','${d.dep_id}')">✕</button>` : ''}
    </div>`;

  showModal(`
    <h2>🔗 ${t('dependencies')}: ${esc(taskTitle)}</h2>
    <div class="ws-detail-section">
      <h3>${t('blockedBy')}</h3>
      ${data.blocked_by.length ? data.blocked_by.map(d => renderDep(d, true)).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noDependencies')}</p>`}
    </div>
    <div class="ws-detail-section">
      <h3>${t('blocks')}</h3>
      ${data.blocks.length ? data.blocks.map(d => renderDep(d, false)).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noDependencies')}</p>`}
    </div>
    <div class="ws-detail-section">
      <h3>${t('relatedTo')}</h3>
      ${data.related.length ? data.related.map(d => renderDep(d, true)).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noDependencies')}</p>`}
    </div>
    <div class="ws-detail-section">
      <h3>${t('addDependency')}</h3>
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <select id="depTypeSelect" class="filter-select" style="min-width:120px">
          <option value="blocked_by">${t('blockedBy')}</option>
          <option value="related">${t('relatedTo')}</option>
        </select>
        <input id="depSearchInput" class="filter-input" placeholder="${t('searchTask')}" oninput="filterDepResults()" style="flex:1">
      </div>
      <div id="depSearchResults" style="max-height:150px;overflow-y:auto;font-size:0.85rem">
        ${allTasks.filter(t => t.id !== taskId).map(t => `
          <div class="dep-search-item" data-title="${esc(t.title_en || '').toLowerCase()}" data-title-zh="${esc(t.title_zh || '').toLowerCase()}" style="display:flex;align-items:center;gap:8px;padding:4px 8px;cursor:pointer;border-radius:var(--radius)" onclick="addDep('${taskId}','${t.id}')">
            <span style="flex:1">${tField(t,'title')}</span><span style="font-size:0.7rem;color:var(--text3)">${t.status}</span>
          </div>`).join('')}
      </div>
    </div>
  `);
}

function filterDepResults() {
  const q = document.getElementById('depSearchInput').value.toLowerCase();
  document.querySelectorAll('.dep-search-item').forEach(el => {
    const matchEn = el.dataset.title.includes(q);
    const matchZh = (el.dataset.titleZh || '').includes(q);
    el.style.display = (matchEn || matchZh) ? '' : 'none';
  });
}

async function addDep(taskId, dependsOnId) {
  const depType = document.getElementById('depTypeSelect')?.value || 'blocked_by';
  await api(`/api/tasks/${taskId}/dependencies`, 'POST', { depends_on_id: dependsOnId, dep_type: depType });
  await refreshDashboard();
  showTaskDeps(taskId);
}

async function removeDep(taskId, depId) {
  await api(`/api/tasks/${taskId}/dependencies/${depId}`, 'DELETE');
  await refreshDashboard();
  showTaskDeps(taskId);
}

// ── Time Tracking ────────────────────────────────────────────────────────
async function showTimeLog(taskId) {
  const entries = await api(`/api/tasks/${taskId}/time`);
  const allTasks = [];
  for (const p of dashboardData) for (const ws of p.workstreams) for (const t of ws.tasks) allTasks.push(t);
  const task = allTasks.find(t => t.id === taskId);
  const taskTitle = task ? tField(task, 'title') : taskId;
  const total = entries.reduce((s, e) => s + e.minutes, 0);

  showModal(`
    <h2>⏱ ${t('timeTracking')}: ${esc(taskTitle)}</h2>
    <div class="time-summary">
      <div class="time-summary-card"><div class="time-val">${formatMinutes(total)}</div><div class="time-label">${t('totalTime')}</div></div>
      <div class="time-summary-card"><div class="time-val">${entries.length}</div><div class="time-label">${t('entries')}</div></div>
    </div>
    <div style="margin-bottom:12px">
      ${entries.length ? entries.map(e => `
        <div class="time-entry">
          <span class="time-duration">${formatMinutes(e.minutes)}</span>
          <span class="time-user">@${esc(e.user_name)}</span>
          <span class="time-desc">${esc(e.description)}</span>
          <span style="color:var(--text3);font-size:0.7rem">${e.date}</span>
          <button class="btn-ghost" onclick="deleteTimeEntry('${e.id}','${taskId}')">🗑</button>
        </div>`).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noTimeEntries')}</p>`}
    </div>
    <h3 style="font-size:0.85rem;margin-bottom:8px">${t('logTime')}</h3>
    <div class="form-row">
      <div class="form-group"><label>${t('timeDuration')} (${t('minutes')})</label><input id="timeMinutes" type="number" min="1" value="30"></div>
      <div class="form-group"><label>${t('timeDate')}</label><input id="timeDate" type="date" value="${new Date().toISOString().slice(0,10)}"></div>
    </div>
    <div class="form-group"><label>${t('timeDescription')}</label><input id="timeDesc" placeholder="${t('timeDescription')}"></div>
    <div class="form-actions"><button class="btn btn-primary" onclick="logTimeEntry('${taskId}')">${t('logTime')}</button></div>
  `);
}

async function logTimeEntry(taskId) {
  const minutes = parseInt(document.getElementById('timeMinutes').value) || 0;
  if (minutes <= 0) return;
  const description = document.getElementById('timeDesc').value;
  const date = document.getElementById('timeDate').value;
  await api(`/api/tasks/${taskId}/time`, 'POST', { minutes, description, date });
  await refreshDashboard();
  showTimeLog(taskId);
}

async function deleteTimeEntry(eid, taskId) {
  if (!confirm(t('confirmDelete'))) return;
  await api(`/api/time-entries/${eid}`, 'DELETE');
  await refreshDashboard();
  showTimeLog(taskId);
}

// ── File Attachments ─────────────────────────────────────────────────────
async function loadAttachments(entityType, entityId, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  try {
    const items = await api(`/api/attachments/${entityType}/${entityId}`);
    el.innerHTML = items.length ? items.map(a => `
      <div class="attachment-item">
        <span class="attachment-icon">📄</span>
        <a class="attachment-name" href="/api/attachments/download/${a.id}" target="_blank">${esc(a.original_name)}</a>
        <span class="attachment-size">${formatBytes(a.size_bytes)}</span>
        <span style="color:var(--text3);font-size:0.7rem">@${esc(a.uploader)}</span>
        <button class="btn-ghost" onclick="deleteAttachment('${a.id}','${entityType}','${entityId}','${containerId}')">🗑</button>
      </div>`).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noAttachments')}</p>`;
  } catch(e) { el.innerHTML = ''; }
}

async function uploadFile(entityType, entityId, containerId) {
  const input = document.querySelector(`#${containerId}`).parentElement.querySelector('input[type="file"]');
  if (!input || !input.files[0]) return;
  const file = input.files[0];
  if (file.size > 20 * 1024 * 1024) { showToast(t('fileTooLarge'), 'error'); return; }
  await apiUpload(`/api/attachments/${entityType}/${entityId}`, file);
  input.value = '';
  loadAttachments(entityType, entityId, containerId);
}

async function deleteAttachment(aid, entityType, entityId, containerId) {
  if (!confirm(t('confirmDelete'))) return;
  await api(`/api/attachments/${aid}`, 'DELETE');
  loadAttachments(entityType, entityId, containerId);
}

async function showTaskAttachments(taskId) {
  const allTasks = [];
  for (const p of dashboardData) for (const ws of p.workstreams) for (const tk of ws.tasks) allTasks.push(tk);
  const task = allTasks.find(tk => tk.id === taskId);
  const taskTitle = task ? tField(task, 'title') : taskId;
  showModal(`
    <h2>📎 ${t('attachments')}: ${esc(taskTitle)}</h2>
    <div id="taskAttachments"></div>
    <input type="file" id="taskFileInput" style="display:none" onchange="uploadFile('task','${taskId}','taskAttachments')">
    <button class="btn btn-sm" style="margin-top:8px" onclick="document.getElementById('taskFileInput').click()">${t('addAttachment')}</button>
  `);
  loadAttachments('task', taskId, 'taskAttachments');
}

// ── Recurring Tasks ──────────────────────────────────────────────────────
async function loadRecurringTasks(wid, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  try {
    const items = await api(`/api/recurring-tasks?workstream_id=${wid}`);
    const days = [t('monday'),t('tuesday'),t('wednesday'),t('thursday'),t('friday'),t('saturday'),t('sunday')];
    el.innerHTML = items.length ? items.map(r => `
      <div class="recurring-item ${r.active ? '' : 'inactive'}">
        <span style="flex:1">${tField(r, 'title') || esc(r.title_en)}</span>
        <span class="recurring-schedule">${t(r.schedule)}${r.day_of_week !== null ? ' · ' + days[r.day_of_week] : ''}${r.day_of_month !== null ? ' · ' + r.day_of_month : ''}</span>
        ${r.assignee ? `<span style="font-size:0.7rem;color:var(--accent2)">@${esc(r.assignee)}</span>` : ''}
        <span style="font-size:0.65rem;color:var(--text3)">${r.next_due ? t('nextDue') + ': ' + r.next_due : ''}${r.last_created ? ' · ' + t('lastCreated') + ': ' + r.last_created : ''}</span>
        <button class="btn-ghost" onclick="showEditRecurring('${r.id}','${wid}')" title="${t('edit')}">✏</button>
        <button class="btn-ghost" onclick="toggleRecurringActive('${r.id}',${r.active ? 0 : 1},'${wid}')" title="${r.active ? t('recurringPaused') : t('recurringActive')}">${r.active ? '⏸' : '▶'}</button>
        <button class="btn-ghost" onclick="deleteRecurring('${r.id}','${wid}')">🗑</button>
      </div>`).join('') : `<p style="color:var(--text3);font-size:0.85rem">${t('noRecurring')}</p>`;
  } catch(e) { el.innerHTML = ''; }
}

function showAddRecurring(wid) {
  const days = [t('monday'),t('tuesday'),t('wednesday'),t('thursday'),t('friday'),t('saturday'),t('sunday')];
  showModal(`
    <h2>🔄 ${t('addRecurring')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="recTitle"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="recTitleZh"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('assignee')}</label><input id="recAssignee"></div>
      <div class="form-group"><label>${t('schedule')}</label>
        <select id="recSchedule" onchange="toggleRecFields()">
          <option value="daily">${t('daily')}</option>
          <option value="weekly" selected>${t('weekly')}</option>
          <option value="biweekly">${t('biweekly')}</option>
          <option value="monthly">${t('monthly')}</option>
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" id="recDowGroup"><label>${t('dayOfWeek')}</label>
        <select id="recDow">${days.map((d,i) => `<option value="${i}" ${i===0?'selected':''}>${d}</option>`).join('')}</select>
      </div>
      <div class="form-group" id="recDomGroup" style="display:none"><label>${t('dayOfMonth')}</label>
        <input id="recDom" type="number" min="1" max="28" value="1">
      </div>
    </div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="recNotes" rows="2" style="width:100%;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--bg3);border-radius:var(--radius);font-family:inherit"></textarea></div>
    <div class="form-actions"><button class="btn btn-primary" onclick="saveRecurring('${wid}')">${t('save')}</button></div>
  `);
}

function toggleRecFields() {
  const sched = document.getElementById('recSchedule').value;
  document.getElementById('recDowGroup').style.display = (sched === 'weekly' || sched === 'biweekly') ? '' : 'none';
  document.getElementById('recDomGroup').style.display = sched === 'monthly' ? '' : 'none';
}

async function saveRecurring(wid, editId) {
  const schedule = document.getElementById('recSchedule').value;
  const body = {
    title_en: document.getElementById('recTitle').value,
    title_zh: document.getElementById('recTitleZh')?.value || '',
    assignee: document.getElementById('recAssignee').value,
    notes: document.getElementById('recNotes').value,
    schedule,
    day_of_week: (schedule === 'weekly' || schedule === 'biweekly') ? parseInt(document.getElementById('recDow').value) : null,
    day_of_month: schedule === 'monthly' ? parseInt(document.getElementById('recDom').value) : null,
  };
  if (!body.title_en) return;
  if (editId) {
    await api(`/api/recurring-tasks/${editId}`, 'PUT', body);
  } else {
    body.workstream_id = wid;
    await api('/api/recurring-tasks', 'POST', body);
  }
  closeModal();
  showWorkstreamDetail(wid);
}

async function toggleRecurringActive(rid, active, wid) {
  await api(`/api/recurring-tasks/${rid}`, 'PUT', { active });
  showWorkstreamDetail(wid);
}

async function deleteRecurring(rid, wid) {
  if (!confirm(t('confirmDelete'))) return;
  await api(`/api/recurring-tasks/${rid}`, 'DELETE');
  showWorkstreamDetail(wid);
}

async function showEditRecurring(rid, wid) {
  const items = await api(`/api/recurring-tasks?workstream_id=${wid}`);
  const r = items.find(x => x.id === rid);
  if (!r) return;
  const days = [t('monday'),t('tuesday'),t('wednesday'),t('thursday'),t('friday'),t('saturday'),t('sunday')];
  const isWeekly = r.schedule === 'weekly' || r.schedule === 'biweekly';
  const isMonthly = r.schedule === 'monthly';
  showModal(`
    <h2>🔄 ${t('edit')} ${t('recurringTasks')}</h2>
    <div class="form-row">
      <div class="form-group"><label>${t('titleEn')}</label><input id="recTitle" value="${esc(r.title_en)}"></div>
      <div class="form-group"><label>${t('titleZh')}</label><input id="recTitleZh" value="${esc(r.title_zh || '')}"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>${t('assignee')}</label><input id="recAssignee" value="${esc(r.assignee || '')}"></div>
      <div class="form-group"><label>${t('schedule')}</label>
        <select id="recSchedule" onchange="toggleRecFields()">
          ${['daily','weekly','biweekly','monthly'].map(s => `<option value="${s}" ${r.schedule===s?'selected':''}>${t(s)}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" id="recDowGroup" style="${isWeekly ? '' : 'display:none'}"><label>${t('dayOfWeek')}</label>
        <select id="recDow">${days.map((d,i) => `<option value="${i}" ${r.day_of_week===i?'selected':''}>${d}</option>`).join('')}</select>
      </div>
      <div class="form-group" id="recDomGroup" style="${isMonthly ? '' : 'display:none'}"><label>${t('dayOfMonth')}</label>
        <input id="recDom" type="number" min="1" max="28" value="${r.day_of_month || 1}">
      </div>
    </div>
    <div class="form-group"><label>${t('notes')}</label><textarea id="recNotes" rows="2" style="width:100%;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--bg3);border-radius:var(--radius);font-family:inherit">${esc(r.notes || '')}</textarea></div>
    <div class="form-actions"><button class="btn btn-primary" onclick="saveRecurring('${wid}','${rid}')">${t('save')}</button></div>
  `);
}

// ── Sync Conflicts ───────────────────────────────────────────────────────
async function showConflicts() {
  const conflicts = await api('/api/sync-conflicts?resolved=false');
  showModal(`
    <h2>⚡ ${t('syncConflicts')}</h2>
    ${conflicts.length ? `
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn btn-sm" onclick="resolveAllConflicts('local')">${t('useAllLocal')}</button>
        <button class="btn btn-sm" onclick="resolveAllConflicts('remote')">${t('useAllFeishu')}</button>
      </div>
      ${conflicts.map(c => {
        const typeLabel = c.entity_type === 'task' ? '📋' : c.entity_type === 'blocker' ? '⚠' : '🐛';
        const localTime = c.local_updated ? c.local_updated.substring(5, 16) : '';
        const remoteTime = c.remote_updated ? c.remote_updated.substring(5, 16) : '';
        return `
        <div class="conflict-item">
          <div class="conflict-entity">
            <span class="badge" style="font-size:0.7rem;padding:1px 6px">${typeLabel} ${esc(c.entity_type)}</span>
            ${esc(c.entity_title || c.entity_id)} — <strong>${esc(c.field_name)}</strong>
          </div>
          <div class="conflict-values">
            <div class="conflict-local">
              <strong>${t('localValue')}:</strong> ${esc(c.local_value)}
              ${localTime ? `<div style="font-size:0.65rem;color:var(--text3);margin:2px 0">${localTime}</div>` : ''}
              <button class="btn btn-sm" style="margin-top:4px" onclick="resolveConflict('${c.id}','local')">${t('useLocal')}</button>
            </div>
            <div class="conflict-remote">
              <strong>${t('feishuValue')}:</strong> ${esc(c.remote_value)}
              ${remoteTime ? `<div style="font-size:0.65rem;color:var(--text3);margin:2px 0">${remoteTime}</div>` : ''}
              <button class="btn btn-sm" style="margin-top:4px" onclick="resolveConflict('${c.id}','remote')">${t('useFeishu')}</button>
            </div>
          </div>
          <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
            <input id="manual-${c.id}" class="filter-input" style="flex:1" value="${esc(c.local_value)}" placeholder="${t('manualValue')}">
            <button class="btn btn-sm" onclick="document.getElementById('manual-${c.id}').value='${esc(c.remote_value)}'" title="Pre-fill Feishu value" style="font-size:0.7rem">← ${t('feishuValue')}</button>
            <button class="btn btn-sm btn-primary" onclick="resolveConflict('${c.id}','manual',document.getElementById('manual-${c.id}').value)">${t('useCustom')}</button>
          </div>
        </div>`;
      }).join('')}
    ` : `<p style="color:var(--text3)">${t('noConflicts')}</p>`}
  `);
}

async function resolveConflict(cid, resolution, manualValue) {
  const body = { resolution };
  if (resolution === 'manual') body.manual_value = manualValue;
  await api(`/api/sync-conflicts/${cid}/resolve`, 'PUT', body);
  await refreshDashboard();
  showConflicts();
}

async function resolveAllConflicts(resolution) {
  if (!confirm(t('confirmDelete'))) return;
  await api('/api/sync-conflicts/resolve-all', 'POST', { resolution });
  await refreshDashboard();
  showConflicts();
}

// ── Init ─────────────────────────────────────────────────────────────────
if (localStorage.getItem('kanban-theme') === 'light') {
  document.documentElement.classList.add('light');
  document.getElementById('themeBtn').textContent = '🌙';
}
// ── Feishu login token handler ───────────────────────────────────────────
(async function handleLoginToken() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('login_token');
  if (!token) return;
  try {
    const resp = await fetch(API + '/api/auth/login?token=' + encodeURIComponent(token));
    if (!resp.ok) {
      const err = await resp.text();
      showToast('Login failed: ' + err, 'error');
      return;
    }
    const data = await resp.json();
    currentUser = data.user_name;
    localStorage.setItem('kanban-user', data.user_name);
    document.getElementById('userBtn').textContent = data.display_name || data.user_name;
    document.getElementById('notifBtn').style.display = '';
    showToast('Logged in as ' + (data.display_name || data.user_name), 'success');
    // Clean URL
    window.history.replaceState({}, '', window.location.pathname);
    refreshDashboard();
  } catch (e) {
    showToast('Login error: ' + e.message, 'error');
  }
})();

applyFontSize(localStorage.getItem('kanban-font-size') || 'md');
document.getElementById('langBtn').textContent = currentLang === 'en' ? '中文' : 'EN';
document.getElementById('userBtn').textContent = currentUser || t('login');
if (currentUser) document.getElementById('notifBtn').style.display = '';
updateViewBtn();
initFilters();
refreshDashboard();
// Auto-refresh with toggle
let _autoRefreshEnabled = localStorage.getItem('kanban-auto-refresh') !== 'off';
let _autoRefreshTimer = null;

function startAutoRefresh() {
  if (_autoRefreshTimer) clearInterval(_autoRefreshTimer);
  _autoRefreshTimer = setInterval(refreshDashboard, 30000);
}
function stopAutoRefresh() {
  if (_autoRefreshTimer) { clearInterval(_autoRefreshTimer); _autoRefreshTimer = null; }
}
function toggleAutoRefresh() {
  _autoRefreshEnabled = !_autoRefreshEnabled;
  localStorage.setItem('kanban-auto-refresh', _autoRefreshEnabled ? 'on' : 'off');
  if (_autoRefreshEnabled) { startAutoRefresh(); } else { stopAutoRefresh(); }
  const btn = document.getElementById('autoRefreshBtn');
  if (btn) btn.textContent = _autoRefreshEnabled ? '⟳ ON' : '⟳ OFF';
}
if (_autoRefreshEnabled) startAutoRefresh();
