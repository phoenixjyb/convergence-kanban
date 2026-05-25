// ══════════════════════════════════════════════════════════════════════════
// Analytics Dashboard — Vanilla JS + Canvas 2D charts
// ══════════════════════════════════════════════════════════════════════════

// ── Utility ──────────────────────────────────────────────────────────────
function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function refreshDashboard() {
  if (typeof applyI18n === 'function') applyI18n();
  refreshAll();
}

// ── Chart color constants ─────────────────────────────────────────────────
const CHART_COLORS = {
  todo:      '#556677',
  doing:     '#4facfe',
  in_review: '#fbbf24',
  done:      '#00ddb3',
  blocked:   '#ff4757',
  accent:    '#00ddb3',
  grid:      'rgba(255,255,255,0.06)',
  text:      '#dfe6ed',
  text2:     '#8899aa',
};

const CHART_COLORS_LIGHT = {
  todo:      '#94a3b8',
  doing:     '#2563eb',
  in_review: '#d97706',
  done:      '#059669',
  blocked:   '#dc2626',
  accent:    '#059669',
  grid:      'rgba(0,0,0,0.08)',
  text:      '#111827',
  text2:     '#374151',
};

function C() {
  return document.documentElement.classList.contains('light') ? CHART_COLORS_LIGHT : CHART_COLORS;
}

// ── State ─────────────────────────────────────────────────────────────────
let currentDays = 30;
let currentUser = localStorage.getItem('kanban-user') || '';
let allProjects = [];
let allUsers = [];
let tooltipEl = null;

// ── API helper ────────────────────────────────────────────────────────────
async function api(url) {
  const opts = { headers: {} };
  if (currentUser) opts.headers['X-Kanban-User'] = currentUser;
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

// ── Data fetchers ─────────────────────────────────────────────────────────
async function fetchAnalytics(days) {
  return api('/api/analytics?days=' + days);
}

async function fetchBugTrends(days) {
  return api('/api/analytics/bugs?days=' + days);
}

async function fetchWorkload() {
  return api('/api/analytics/workload');
}

async function fetchBlockerAging() {
  return api('/api/analytics/blockers');
}

async function fetchActivity(limit, entityType, actor) {
  const params = new URLSearchParams();
  params.set('limit', limit || 200);
  if (entityType) params.set('entity_type', entityType);
  if (actor) params.set('actor', actor);
  return api('/api/analytics/activity?' + params.toString());
}

// ── Canvas helpers ────────────────────────────────────────────────────────
function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  return { ctx, w: rect.width, h: rect.height, dpr };
}

function drawGridLines(ctx, x0, y0, w, h, steps, colors) {
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  for (let i = 0; i <= steps; i++) {
    const y = y0 + (h / steps) * i;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x0 + w, y);
    ctx.stroke();
  }
}

function truncateLabel(text, maxLen) {
  if (!text) return '';
  return text.length > maxLen ? text.substring(0, maxLen - 1) + '\u2026' : text;
}

// ── Tooltip ───────────────────────────────────────────────────────────────
function ensureTooltip() {
  if (!tooltipEl) {
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'chart-tooltip';
    document.body.appendChild(tooltipEl);
  }
  return tooltipEl;
}

function showTooltip(x, y, label, value) {
  const tip = ensureTooltip();
  tip.innerHTML = '<div class="chart-tooltip-label">' + esc(label) + '</div><div class="chart-tooltip-value">' + esc(String(value)) + '</div>';
  tip.classList.add('visible');
  tip.style.left = (x + 12) + 'px';
  tip.style.top = (y - 10) + 'px';
}

function hideTooltip() {
  if (tooltipEl) tooltipEl.classList.remove('visible');
}

// ── Burndown Chart ────────────────────────────────────────────────────────
function drawBurndown(canvas, data) {
  const emptyEl = document.getElementById('burndownEmpty');
  if (!data || data.length === 0) {
    canvas.style.display = 'none';
    emptyEl.classList.remove('hidden');
    return;
  }
  canvas.style.display = 'block';
  emptyEl.classList.add('hidden');

  const { ctx, w, h } = setupCanvas(canvas);
  const colors = C();
  const pad = { top: 20, right: 20, bottom: 36, left: 50 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  // Extract series
  const dates = data.map(d => d.date);
  const totals = data.map(d => d.totals ? d.totals.total : 0);
  const dones = data.map(d => d.totals ? d.totals.done : 0);
  const maxVal = Math.max(...totals, 1);
  const gridSteps = 5;

  // Grid
  drawGridLines(ctx, pad.left, pad.top, cw, ch, gridSteps, colors);

  // Y-axis labels
  ctx.font = '11px "Fira Code", monospace';
  ctx.fillStyle = colors.text2;
  ctx.textAlign = 'right';
  for (let i = 0; i <= gridSteps; i++) {
    const val = Math.round(maxVal * (1 - i / gridSteps));
    const y = pad.top + (ch / gridSteps) * i;
    ctx.fillText(String(val), pad.left - 8, y + 4);
  }

  // X-axis labels
  ctx.textAlign = 'center';
  const labelStep = Math.max(1, Math.floor(dates.length / 8));
  for (let i = 0; i < dates.length; i += labelStep) {
    const x = pad.left + (cw / Math.max(dates.length - 1, 1)) * i;
    const label = dates[i].substring(5); // MM-DD
    ctx.fillText(label, x, h - 8);
  }

  function yPos(val) {
    return pad.top + ch - (val / maxVal) * ch;
  }
  function xPos(i) {
    return pad.left + (cw / Math.max(dates.length - 1, 1)) * i;
  }

  // Area fill for done
  ctx.beginPath();
  ctx.moveTo(xPos(0), yPos(0));
  for (let i = 0; i < dones.length; i++) {
    ctx.lineTo(xPos(i), yPos(dones[i]));
  }
  ctx.lineTo(xPos(dones.length - 1), yPos(0));
  ctx.closePath();
  ctx.fillStyle = isLight() ? 'rgba(0, 168, 132, 0.12)' : 'rgba(0, 221, 179, 0.1)';
  ctx.fill();

  // Total line
  drawLine(ctx, totals, maxVal, pad, cw, ch, colors.text2, 2);

  // Done line
  drawLine(ctx, dones, maxVal, pad, cw, ch, colors.accent, 2.5);

  // Legend
  ctx.font = '11px "Outfit", sans-serif';
  const legendY = pad.top + 6;
  ctx.fillStyle = colors.text2;
  ctx.fillRect(w - pad.right - 140, legendY - 4, 8, 3);
  ctx.fillText(t('total'), w - pad.right - 126, legendY);
  ctx.fillStyle = colors.accent;
  ctx.fillRect(w - pad.right - 70, legendY - 4, 8, 3);
  ctx.fillText(t('done'), w - pad.right - 56, legendY);

  // Hover
  setupLineHover(canvas, dates, [
    { label: t('total'), values: totals, color: colors.text2 },
    { label: t('done'), values: dones, color: colors.accent },
  ], pad, cw, ch, maxVal);
}

function drawLine(ctx, values, maxVal, pad, cw, ch, color, lineWidth) {
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  for (let i = 0; i < values.length; i++) {
    const x = pad.left + (cw / Math.max(values.length - 1, 1)) * i;
    const y = pad.top + ch - (values[i] / maxVal) * ch;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function setupLineHover(canvas, dates, series, pad, cw, ch, maxVal) {
  canvas.onmousemove = function(e) {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const n = dates.length;
    if (n < 1) return;
    const step = cw / Math.max(n - 1, 1);
    const idx = Math.round((mx - pad.left) / step);
    if (idx < 0 || idx >= n) { hideTooltip(); return; }
    const parts = series.map(s => s.label + ': ' + s.values[idx]);
    showTooltip(e.clientX, e.clientY, dates[idx], parts.join('  |  '));
  };
  canvas.onmouseleave = hideTooltip;
}

// ── Bug Trends Chart ──────────────────────────────────────────────────────
function drawBugTrends(canvas, data) {
  const emptyEl = document.getElementById('bugTrendsEmpty');
  if (!data || (data.opened.length === 0 && data.closed.length === 0)) {
    canvas.style.display = 'none';
    emptyEl.classList.remove('hidden');
    return;
  }
  canvas.style.display = 'block';
  emptyEl.classList.add('hidden');

  const { ctx, w, h } = setupCanvas(canvas);
  const colors = C();
  const pad = { top: 20, right: 20, bottom: 36, left: 40 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  // Merge dates
  const dateSet = new Set();
  data.opened.forEach(d => dateSet.add(d.date));
  data.closed.forEach(d => dateSet.add(d.date));
  const dates = [...dateSet].sort();
  if (dates.length === 0) return;

  const openedMap = {};
  data.opened.forEach(d => openedMap[d.date] = d.count);
  const closedMap = {};
  data.closed.forEach(d => closedMap[d.date] = d.count);

  const openedVals = dates.map(d => openedMap[d] || 0);
  const closedVals = dates.map(d => closedMap[d] || 0);
  const maxVal = Math.max(...openedVals, ...closedVals, 1);
  const gridSteps = 4;

  drawGridLines(ctx, pad.left, pad.top, cw, ch, gridSteps, colors);

  // Y-axis
  ctx.font = '10px "Fira Code", monospace';
  ctx.fillStyle = colors.text2;
  ctx.textAlign = 'right';
  for (let i = 0; i <= gridSteps; i++) {
    const val = Math.round(maxVal * (1 - i / gridSteps));
    const y = pad.top + (ch / gridSteps) * i;
    ctx.fillText(String(val), pad.left - 6, y + 4);
  }

  // X-axis
  ctx.textAlign = 'center';
  const labelStep = Math.max(1, Math.floor(dates.length / 6));
  for (let i = 0; i < dates.length; i += labelStep) {
    const x = pad.left + (cw / Math.max(dates.length - 1, 1)) * i;
    ctx.fillText(dates[i].substring(5), x, h - 8);
  }

  // Lines
  const redColor = isLight() ? '#ef4444' : '#ff4757';
  const greenColor = isLight() ? '#00a884' : '#00ddb3';
  drawLine(ctx, openedVals, maxVal, pad, cw, ch, redColor, 2);
  drawLine(ctx, closedVals, maxVal, pad, cw, ch, greenColor, 2);

  // Legend
  ctx.font = '10px "Outfit", sans-serif';
  ctx.fillStyle = redColor;
  ctx.fillRect(pad.left + 8, pad.top + 4, 8, 3);
  ctx.fillText(t('opened'), pad.left + 44, pad.top + 9);
  ctx.fillStyle = greenColor;
  ctx.fillRect(pad.left + 78, pad.top + 4, 8, 3);
  ctx.fillText(t('resolved'), pad.left + 120, pad.top + 9);

  setupLineHover(canvas, dates, [
    { label: t('opened'), values: openedVals },
    { label: t('resolved'), values: closedVals },
  ], pad, cw, ch, maxVal);
}

// ── Workload Chart ────────────────────────────────────────────────────────
function drawWorkload(canvas, data) {
  const emptyEl = document.getElementById('workloadEmpty');
  if (!data || data.length === 0) {
    canvas.style.display = 'none';
    emptyEl.classList.remove('hidden');
    return;
  }
  canvas.style.display = 'block';
  emptyEl.classList.add('hidden');

  // Sort by total desc, limit to top 12
  data.sort((a, b) => b.total - a.total);
  if (data.length > 12) data = data.slice(0, 12);

  const { ctx, w, h } = setupCanvas(canvas);
  const colors = C();
  const pad = { top: 14, right: 20, bottom: 10, left: 100 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const maxVal = Math.max(...data.map(d => d.total), 1);
  const barH = Math.min(22, ch / data.length - 4);
  const gap = (ch - barH * data.length) / Math.max(data.length - 1, 1);
  const statuses = ['done', 'in_review', 'doing', 'todo', 'blocked'];

  for (let i = 0; i < data.length; i++) {
    const d = data[i];
    const y = pad.top + i * (barH + gap);

    // Label
    ctx.font = '11px "Outfit", sans-serif';
    ctx.fillStyle = colors.text2;
    ctx.textAlign = 'right';
    ctx.fillText(truncateLabel(d.assignee, 14), pad.left - 8, y + barH / 2 + 4);

    // Stacked bar
    let xOff = pad.left;
    for (const st of statuses) {
      const val = d[st] || 0;
      if (val === 0) continue;
      const barW = (val / maxVal) * cw;
      ctx.fillStyle = colors[st] || colors.text2;
      ctx.beginPath();
      roundRect(ctx, xOff, y, barW, barH, 3);
      ctx.fill();
      xOff += barW + 1;
    }

    // Total count
    ctx.font = '10px "Fira Code", monospace';
    ctx.fillStyle = colors.text2;
    ctx.textAlign = 'left';
    ctx.fillText(String(d.total), xOff + 6, y + barH / 2 + 4);
  }

  // Hover
  canvas.onmousemove = function(e) {
    const rect = canvas.getBoundingClientRect();
    const my = e.clientY - rect.top;
    for (let i = 0; i < data.length; i++) {
      const y = pad.top + i * (barH + gap);
      if (my >= y && my <= y + barH) {
        const d = data[i];
        const parts = statuses.filter(s => d[s] > 0).map(s => t(s) + ': ' + d[s]);
        showTooltip(e.clientX, e.clientY, d.assignee, parts.join(' | '));
        return;
      }
    }
    hideTooltip();
  };
  canvas.onmouseleave = hideTooltip;
}

// ── Blocker Aging Chart ───────────────────────────────────────────────────
function drawBlockerAging(canvas, data) {
  const emptyEl = document.getElementById('blockerEmpty');
  if (!data || data.length === 0) {
    canvas.style.display = 'none';
    emptyEl.classList.remove('hidden');
    return;
  }
  canvas.style.display = 'block';
  emptyEl.classList.add('hidden');

  // Limit to 10, sort by age desc
  data.sort((a, b) => b.age_hours - a.age_hours);
  if (data.length > 10) data = data.slice(0, 10);

  const { ctx, w, h } = setupCanvas(canvas);
  const colors = C();
  const pad = { top: 14, right: 40, bottom: 10, left: 110 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  const maxAge = Math.max(...data.map(d => d.age_hours), 1);
  const barH = Math.min(20, ch / data.length - 4);
  const gap = (ch - barH * data.length) / Math.max(data.length - 1, 1);

  for (let i = 0; i < data.length; i++) {
    const d = data[i];
    const y = pad.top + i * (barH + gap);
    const barW = (d.age_hours / maxAge) * cw;

    // Label
    ctx.font = '10px "Outfit", sans-serif';
    ctx.fillStyle = colors.text2;
    ctx.textAlign = 'right';
    ctx.fillText(truncateLabel(d.description_en || d.id, 16), pad.left - 8, y + barH / 2 + 4);

    // Bar color by severity
    let barColor;
    if (d.age_hours > 96) barColor = isLight() ? '#ef4444' : '#ff4757';
    else if (d.age_hours > 48) barColor = isLight() ? '#ea580c' : '#ff8c42';
    else if (d.age_hours > 24) barColor = isLight() ? '#d97706' : '#fbbf24';
    else barColor = isLight() ? '#00a884' : '#00ddb3';

    ctx.fillStyle = barColor;
    ctx.beginPath();
    roundRect(ctx, pad.left, y, Math.max(barW, 2), barH, 3);
    ctx.fill();

    // Age label
    ctx.font = '10px "Fira Code", monospace';
    ctx.fillStyle = colors.text2;
    ctx.textAlign = 'left';
    const ageLabel = d.age_hours >= 24
      ? Math.round(d.age_hours / 24) + 'd'
      : Math.round(d.age_hours) + 'h';
    ctx.fillText(ageLabel, pad.left + barW + 6, y + barH / 2 + 4);
  }

  // Hover
  canvas.onmousemove = function(e) {
    const rect = canvas.getBoundingClientRect();
    const my = e.clientY - rect.top;
    for (let i = 0; i < data.length; i++) {
      const y = pad.top + i * (barH + gap);
      if (my >= y && my <= y + barH) {
        const d = data[i];
        const ageStr = d.age_hours >= 24
          ? Math.round(d.age_hours / 24) + ' days'
          : Math.round(d.age_hours) + ' hours';
        showTooltip(e.clientX, e.clientY,
          (d.project || '') + ' / ' + (d.workstream || ''),
          esc(d.description_en || '') + ' (' + ageStr + ')');
        return;
      }
    }
    hideTooltip();
  };
  canvas.onmouseleave = hideTooltip;
}

// ── Round rect helper ─────────────────────────────────────────────────────
function roundRect(ctx, x, y, w, h, r) {
  if (w < 2 * r) r = w / 2;
  if (h < 2 * r) r = h / 2;
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
}

// ── Gantt Chart ──────────────────────────────────────────────────────────
let _ganttDashboard = [];
let _ganttSelectedProjects = new Set(); // empty = all

function initGanttFilters() {
  const container = document.getElementById('ganttProjectChips');
  if (!container || !allProjects.length) return;

  // Build "All" chip + per-project chips
  let html = '<span class="gantt-chip active" data-project="" onclick="toggleGanttProject(this)">'
    + t('allProjects') + '</span>';
  for (const p of allProjects) {
    const color = p.color || '#00ddb3';
    html += '<span class="gantt-chip" data-project="' + p.id + '" onclick="toggleGanttProject(this)">'
      + '<span class="chip-dot" style="background:' + color + '"></span>'
      + esc(p.name_en || p.name_zh || '?') + '</span>';
  }
  container.innerHTML = html;
}

function toggleGanttProject(chip) {
  const pid = chip.dataset.project;
  const container = document.getElementById('ganttProjectChips');
  const allChip = container.querySelector('[data-project=""]');

  if (pid === '') {
    // Clicked "All" — deselect everything else
    _ganttSelectedProjects.clear();
    container.querySelectorAll('.gantt-chip').forEach(c => c.classList.remove('active'));
    allChip.classList.add('active');
  } else {
    // Toggle specific project
    allChip.classList.remove('active');
    if (_ganttSelectedProjects.has(pid)) {
      _ganttSelectedProjects.delete(pid);
      chip.classList.remove('active');
    } else {
      _ganttSelectedProjects.add(pid);
      chip.classList.add('active');
    }
    // If none selected, revert to "All"
    if (_ganttSelectedProjects.size === 0) {
      allChip.classList.add('active');
    }
  }

  updateGanttWsFilter();
  refreshGantt();
}

function updateGanttWsFilter() {
  const sel = document.getElementById('ganttWsFilter');
  const prev = sel.value;
  let wsOptions = '<option value="">' + t('allWorkstreams') + '</option>';

  for (const p of _ganttDashboard) {
    if (_ganttSelectedProjects.size > 0 && !_ganttSelectedProjects.has(p.id)) continue;
    for (const ws of p.workstreams) {
      const label = esc(ws.title_en || ws.title_zh || '?');
      wsOptions += '<option value="' + ws.id + '">' + label + '</option>';
    }
  }
  sel.innerHTML = wsOptions;
  // Restore previous selection if still available
  if (prev && sel.querySelector('option[value="' + prev + '"]')) {
    sel.value = prev;
  }
}

async function fetchGanttTasks() {
  _ganttDashboard = await api('/api/dashboard');
  const wsFilter = document.getElementById('ganttWsFilter')
    ? document.getElementById('ganttWsFilter').value : '';
  const tasks = [];
  for (const p of _ganttDashboard) {
    if (_ganttSelectedProjects.size > 0 && !_ganttSelectedProjects.has(p.id)) continue;
    for (const ws of p.workstreams) {
      if (wsFilter && ws.id !== wsFilter) continue;
      for (const t of ws.tasks) {
        if (t.start_date || t.due_date) {
          tasks.push({
            title: t.title_en || t.title_zh || '?',
            start: t.start_date || t.due_date,
            end: t.due_date || t.start_date,
            status: t.status,
            assignee: t.assignee || '',
            project: p.name_en || p.name_zh,
            projectColor: p.color || '#00ddb3',
            ws: ws.title_en || ws.title_zh,
            wsId: ws.id,
          });
        }
      }
    }
  }
  // Sort by start date
  tasks.sort((a, b) => a.start.localeCompare(b.start));
  return tasks;
}

async function refreshGantt() {
  try {
    const tasks = await fetchGanttTasks();
    drawGantt(document.getElementById('ganttCanvas'), tasks);
  } catch (e) {
    console.error('refreshGantt error:', e);
  }
}

function drawGantt(canvas, tasks) {
  const emptyEl = document.getElementById('ganttEmpty');
  if (!tasks || tasks.length === 0) {
    canvas.style.display = 'none';
    emptyEl.classList.remove('hidden');
    return;
  }
  canvas.style.display = '';
  emptyEl.classList.add('hidden');

  const colors = C();
  const statusColors = {
    todo: colors.todo, doing: colors.doing, in_review: colors.in_review,
    done: colors.done, blocked: colors.blocked,
  };

  const rowH = 28;
  const padLeft = 160;
  const padRight = 20;
  const padTop = 30;
  const totalH = padTop + tasks.length * rowH + 10;

  // Set canvas height based on task count
  const wrap = document.getElementById('ganttWrap');
  const wrapW = wrap.clientWidth;
  canvas.style.width = wrapW + 'px';
  canvas.style.height = totalH + 'px';

  const dpr = window.devicePixelRatio || 1;
  canvas.width = wrapW * dpr;
  canvas.height = totalH * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const chartW = wrapW - padLeft - padRight;

  // Find date range
  let minDate = tasks[0].start;
  let maxDate = tasks[0].end;
  for (const t of tasks) {
    if (t.start < minDate) minDate = t.start;
    if (t.end > maxDate) maxDate = t.end;
  }

  // Extend range by 1 day on each side
  const minD = new Date(minDate);
  const maxD = new Date(maxDate);
  minD.setDate(minD.getDate() - 1);
  maxD.setDate(maxD.getDate() + 1);
  const totalDays = Math.max(1, (maxD - minD) / 86400000);

  function dateToX(dateStr) {
    const d = new Date(dateStr);
    const dayOff = (d - minD) / 86400000;
    return padLeft + (dayOff / totalDays) * chartW;
  }

  // Draw background
  ctx.fillStyle = 'transparent';
  ctx.clearRect(0, 0, wrapW, totalH);

  // Draw today line
  const today = new Date().toISOString().slice(0, 10);
  const todayX = dateToX(today);
  if (todayX >= padLeft && todayX <= padLeft + chartW) {
    ctx.strokeStyle = colors.accent;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(todayX, padTop - 5);
    ctx.lineTo(todayX, totalH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = colors.accent;
    ctx.font = '10px Fira Code, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Today', todayX, padTop - 8);
  }

  // Draw date headers
  ctx.fillStyle = colors.text2;
  ctx.font = '10px Fira Code, monospace';
  ctx.textAlign = 'center';
  const stepDays = totalDays <= 14 ? 1 : totalDays <= 60 ? 7 : 14;
  const curD = new Date(minD);
  while (curD <= maxD) {
    const ds = curD.toISOString().slice(0, 10);
    const x = dateToX(ds);
    // Draw tick
    ctx.strokeStyle = colors.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, totalH);
    ctx.stroke();
    // Label
    ctx.fillStyle = colors.text2;
    const label = ds.slice(5); // MM-DD
    ctx.fillText(label, x, padTop - 2);
    curD.setDate(curD.getDate() + stepDays);
  }

  // Alternating row backgrounds (drawn first, behind bars)
  for (let i = 0; i < tasks.length; i++) {
    if (i % 2 === 0) {
      ctx.fillStyle = colors.grid;
      ctx.globalAlpha = 0.3;
      ctx.fillRect(padLeft, padTop + i * rowH, chartW, rowH);
      ctx.globalAlpha = 1;
    }
  }

  // Draw task bars
  for (let i = 0; i < tasks.length; i++) {
    const t = tasks[i];
    const y = padTop + i * rowH;
    const x1 = dateToX(t.start);
    const x2 = dateToX(t.end);
    const barW = Math.max(x2 - x1, 6);
    const barH = 18;
    const barY = y + (rowH - barH) / 2;

    // Task label (left side)
    ctx.fillStyle = colors.text;
    ctx.font = '11px Outfit, sans-serif';
    ctx.textAlign = 'right';
    const label = truncateLabel(t.title, 20);
    ctx.fillText(label, padLeft - 8, barY + barH / 2 + 4);

    // Bar
    const barColor = statusColors[t.status] || colors.todo;
    ctx.fillStyle = barColor;
    ctx.globalAlpha = t.status === 'done' ? 0.5 : 0.85;
    roundRect(ctx, x1, barY, barW, barH, 3);
    ctx.fill();
    ctx.globalAlpha = 1;

    // Assignee label inside bar if wide enough
    if (barW > 60 && t.assignee) {
      ctx.fillStyle = '#fff';
      ctx.font = '9px Fira Code, monospace';
      ctx.textAlign = 'left';
      ctx.fillText(truncateLabel(t.assignee, 12), x1 + 4, barY + barH / 2 + 3);
    }
  }

  // Update subtitle
  const sub = document.getElementById('ganttSubtitle');
  sub.textContent = tasks.length + ' ' + t('tasks');
}

// ── Activity Timeline ─────────────────────────────────────────────────────
function renderActivity(data) {
  const container = document.getElementById('activityTimeline');
  if (!data || data.length === 0) {
    container.innerHTML = '<div class="chart-empty">' + t('noComments') + '</div>';
    return;
  }

  const botPatterns = ['claude', 'bot', 'agent', 'worker', 'cron'];

  let html = '';
  for (const item of data) {
    const actor = item.actor || 'system';
    const isBot = botPatterns.some(p => actor.toLowerCase().includes(p));
    const isSystem = actor === 'system' || actor === 'cron';
    const badgeClass = isSystem ? 'actor-system' : (isBot ? 'actor-bot' : '');

    html += '<div class="activity-item">'
      + '<span class="activity-timestamp">' + esc(formatTimestamp(item.created_at)) + '</span>'
      + '<span class="activity-actor-badge ' + badgeClass + '">' + esc(actor) + '</span>'
      + '<div class="activity-body">'
      + '<span class="activity-action"><span class="action-verb">' + esc(item.action) + '</span> '
      + esc(item.entity_type || '')
      + '</span>'
      + '<span class="activity-entity-type">' + esc(item.entity_type || '') + '</span>'
      + (item.detail ? '<div class="activity-detail">' + esc(item.detail) + '</div>' : '')
      + '</div>'
      + '</div>';
  }
  container.innerHTML = html;
}

function formatTimestamp(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    const pad2 = n => String(n).padStart(2, '0');
    return (d.getMonth() + 1) + '/' + pad2(d.getDate())
      + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  } catch {
    return ts;
  }
}

// ── Light theme detection ─────────────────────────────────────────────────
function isLight() {
  return document.documentElement.classList.contains('light');
}

// ── Theme toggle ──────────────────────────────────────────────────────────
function toggleTheme() {
  const root = document.documentElement;
  root.classList.toggle('light');
  const isLt = root.classList.contains('light');
  localStorage.setItem('kanban-theme', isLt ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = isLt ? '\uD83C\uDF19' : '\u2600\uFE0F';
  refreshAll();
}

// ── Font Size ───────────────────────────────────────────────────────────
const _fontSizes = ['sm', 'md', 'lg', 'xl', 'xxl'];
const _fontLabels = { sm: 'A\u2081', md: 'A\u2082', lg: 'A\u2083', xl: 'A\u2084', xxl: 'A\u2085' };
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
  if (btn) btn.textContent = _fontLabels[size] || 'A\u2082';
}

// ── User picker ───────────────────────────────────────────────────────────
async function showUserPicker() {
  if (allUsers.length === 0) {
    try { allUsers = await api('/api/users'); } catch { allUsers = []; }
  }
  const modal = document.getElementById('userModal');
  const content = document.getElementById('userModalContent');
  const userList = allUsers.filter(u => u.role === 'human')
    .map(u => '<button class="btn btn-sm" style="margin:4px" onclick="pickUser(\'' + esc(u.name) + '\')">' + esc(u.display_name || u.name) + '</button>')
    .join('');

  content.innerHTML = '<h3 style="margin-bottom:12px">' + t('selectUser') + '</h3>'
    + '<input type="text" id="userNameInput" class="bug-search" placeholder="' + t('userName') + '" style="margin-bottom:12px;width:100%" value="' + esc(currentUser) + '">'
    + '<div style="margin-bottom:12px">' + userList + '</div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end">'
    + '<button class="btn btn-sm" onclick="document.getElementById(\'userModal\').classList.add(\'hidden\')">' + t('cancel') + '</button>'
    + '<button class="btn btn-sm btn-primary" onclick="pickUser(document.getElementById(\'userNameInput\').value)">' + t('save') + '</button>'
    + '</div>';
  modal.classList.remove('hidden');
}

function pickUser(name) {
  currentUser = (name || '').trim();
  localStorage.setItem('kanban-user', currentUser);
  document.getElementById('userBtn').textContent = currentUser || 'login';
  document.getElementById('userModal').classList.add('hidden');
}

// ── Date range ────────────────────────────────────────────────────────────
function setRange(days) {
  currentDays = days;
  document.querySelectorAll('.range-pill').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.days) === days);
  });
  refreshAll();
}

// ── Project filter ────────────────────────────────────────────────────────
async function loadProjects() {
  try {
    allProjects = await api('/api/projects');
  } catch {
    allProjects = [];
  }
  const sel = document.getElementById('projectFilter');
  sel.innerHTML = '<option value="">' + t('allProjects') + '</option>'
    + allProjects.map(p => '<option value="' + p.id + '">' + esc(p.name_en) + '</option>').join('');
}

function getSelectedProject() {
  return document.getElementById('projectFilter').value;
}

// ── Filter snapshot data by project ───────────────────────────────────────
function filterSnapshotsByProject(snapshots, projectId) {
  if (!projectId) return snapshots;
  return snapshots.map(s => {
    if (!s.projects || !s.projects[projectId]) {
      return { date: s.date, totals: { total: 0, todo: 0, doing: 0, in_review: 0, done: 0, blocked: 0, active_blockers: 0 } };
    }
    const p = s.projects[projectId];
    return {
      date: s.date,
      totals: {
        total: (p.todo || 0) + (p.doing || 0) + (p.in_review || 0) + (p.done || 0) + (p.blocked || 0),
        todo: p.todo || 0, doing: p.doing || 0, in_review: p.in_review || 0,
        done: p.done || 0, blocked: p.blocked || 0,
        active_blockers: p.active_blockers || 0,
      }
    };
  });
}

// ── Refresh all ───────────────────────────────────────────────────────────
async function refreshAll() {
  const projectId = getSelectedProject();

  // Fetch all data in parallel
  const [snapshots, bugTrends, workload, blockers, ganttTasks] = await Promise.all([
    fetchAnalytics(currentDays).catch(() => []),
    fetchBugTrends(currentDays).catch(() => ({ opened: [], closed: [] })),
    fetchWorkload().catch(() => []),
    fetchBlockerAging().catch(() => []),
    fetchGanttTasks().catch(() => []),
  ]);

  const filteredSnapshots = filterSnapshotsByProject(snapshots, projectId);

  // Update subtitle
  const sub = document.getElementById('burndownSubtitle');
  if (filteredSnapshots.length > 0) {
    const latest = filteredSnapshots[filteredSnapshots.length - 1];
    if (latest.totals) {
      sub.textContent = latest.totals.done + '/' + latest.totals.total + ' ' + t('done');
    }
  } else {
    sub.textContent = '';
  }

  // Populate workstream filter after dashboard data is loaded
  updateGanttWsFilter();

  // Draw charts using requestAnimationFrame for smooth rendering
  requestAnimationFrame(() => {
    drawBurndown(document.getElementById('burndownCanvas'), filteredSnapshots);
    drawBugTrends(document.getElementById('bugTrendsCanvas'), bugTrends);
    drawWorkload(document.getElementById('workloadCanvas'), workload);
    drawBlockerAging(document.getElementById('blockerCanvas'), blockers);
    drawGantt(document.getElementById('ganttCanvas'), ganttTasks);
  });

  // Load activity separately
  loadActivity();
}

async function loadActivity() {
  const entityType = document.getElementById('activityEntityType').value;
  const actor = document.getElementById('activityActor').value;
  try {
    const data = await fetchActivity(200, entityType, actor);
    renderActivity(data);

    // Populate actor filter if not already done
    const actorSel = document.getElementById('activityActor');
    if (actorSel.options.length <= 1 && data.length > 0) {
      const actors = [...new Set(data.map(d => d.actor).filter(Boolean))].sort();
      const current = actorSel.value;
      actorSel.innerHTML = '<option value="">' + t('allActors') + '</option>'
        + actors.map(a => '<option value="' + esc(a) + '"' + (a === current ? ' selected' : '') + '>' + esc(a) + '</option>').join('');
    }
  } catch (e) {
    document.getElementById('activityTimeline').innerHTML = '<div class="chart-empty">' + t('failedLoadActivity') + '</div>';
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Restore theme
  const savedTheme = localStorage.getItem('kanban-theme');
  if (savedTheme === 'light') {
    document.documentElement.classList.add('light');
    document.getElementById('themeBtn').textContent = '\uD83C\uDF19';
  }

  // Restore font size
  applyFontSize(localStorage.getItem('kanban-font-size') || 'md');

  // Restore lang
  if (typeof currentLang !== 'undefined' && currentLang !== 'en') {
    document.getElementById('langBtn').textContent = 'EN';
  }

  // Restore user
  if (currentUser) {
    document.getElementById('userBtn').textContent = currentUser;
  }

  if (typeof applyI18n === 'function') applyI18n();

  await loadProjects();
  initGanttFilters();
  refreshAll();

  // Resize handler for canvas redraw
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => refreshAll(), 250);
  });
});

