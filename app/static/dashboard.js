/* Personal queue preferences and asynchronous attendance enrichment. */
(() => {
  'use strict';
  const root = document.querySelector('[data-work-dashboard]');
  if (!root) return;
  const find = (selector) => root.querySelector(selector);
  const rows = Array.from(root.querySelectorAll('[data-work-task]'));
  const tabs = Array.from(root.querySelectorAll('[role="tab"][data-work-view]'));
  const search = find('[data-work-search]');
  const project = find('[data-work-project]');
  const status = find('[data-work-status]');
  const storageKey = root.dataset.storageKey;
  let preferences = {};
  try { preferences = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (_) { /* Restricted storage keeps useful defaults. */ }
  let view = ['today', 'week', 'blocked', 'completed', 'all'].includes(preferences.view) ? preferences.view : 'today';
  let limit = view === 'today' ? 5 : 20;
  function remember() {
    try { localStorage.setItem(storageKey, JSON.stringify({ view, compact: root.classList.contains('is-compact') })); } catch (_) { /* Browsing can continue without persistence. */ }
  }
  const notes = {
    today: 'Overdue first, then due or starting today. Every task has a reason for being here.',
    week: 'Open work due this week or included in your saved weekly plan. Blockers remain visible.',
    blocked: 'Review the blocker, its next step and the people involved in task details.',
    completed: 'Work completed this week. The summary above uses your saved plan when one exists.',
    all: 'All open assignments and this week’s completions, across your projects.',
  };
  function render() {
    const query = search.value.trim().toLowerCase();
    const matches = rows.filter((row) => row.dataset.workViews.split(' ').includes(view)
      && (!project.value || row.dataset.workProjectId === project.value)
      && (!status.value || row.dataset.workTaskStatus === status.value)
      && (!query || row.dataset.workSearchText.includes(query)));
    const shown = new Set(matches.slice(0, limit));
    rows.forEach((row) => { row.hidden = !shown.has(row); });
    tabs.forEach((tab) => {
      const selected = tab.dataset.workView === view;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    find('#work-task-list').setAttribute('aria-labelledby', `work-tab-${view}`);
    find('[data-work-view-note]').textContent = notes[view];
    find('[data-work-empty]').hidden = matches.length > 0;
    const empty = find('[data-work-empty]');
    empty.querySelector('h3').textContent = query || project.value || status.value ? 'No matching tasks.' : 'You’re clear here.';
    empty.querySelector('p').textContent = query || project.value || status.value ? 'Try another search, project or status.' : 'Choose another view to plan your next step.';
    find('[data-work-results]').textContent = `${shown.size} of ${matches.length} task${matches.length === 1 ? '' : 's'} shown`;
    find('[data-work-more]').hidden = matches.length <= limit;
    remember();
  }
  function choose(next, scroll = true) {
    view = next;
    limit = next === 'today' ? 5 : 20;
    render();
    if (scroll) find('#work-queue').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }
  root.querySelectorAll('[data-work-view]').forEach((button) => button.addEventListener('click', () => choose(button.dataset.workView)));
  tabs.forEach((tab, index) => tab.addEventListener('keydown', (event) => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    choose(tabs[next].dataset.workView, false);
    tabs[next].focus();
  }));
  [search, project, status].forEach((field) => field.addEventListener(field === search ? 'input' : 'change', () => {
    limit = view === 'today' ? 5 : 20;
    render();
  }));
  find('[data-work-clear]').addEventListener('click', () => {
    search.value = ''; project.value = ''; status.value = ''; choose('all', false);
  });
  find('[data-work-more]').addEventListener('click', () => { limit += 20; render(); });
  const density = find('[data-work-density]');
  function applyDensity(compact) {
    root.classList.toggle('is-compact', compact);
    density.setAttribute('aria-pressed', String(compact));
    density.textContent = compact ? 'Comfortable view' : 'Compact view';
    remember();
  }
  applyDensity(Boolean(preferences.compact));
  density.addEventListener('click', () => applyDensity(!root.classList.contains('is-compact')));
  function openDay(date) {
    const day = root.querySelector(`[data-dashboard-leave-day][data-date="${date}"]`);
    if (day?.dataset.canLogEffort === 'true') day.dispatchEvent(new Event('work-add-effort'));
  }
  root.querySelectorAll('[data-work-log-date]').forEach((button) => button.addEventListener('click', () => openDay(button.dataset.workLogDate)));
  find('[data-work-log]').addEventListener('click', () => {
    const days = Array.from(root.querySelectorAll('[data-dashboard-leave-day][data-can-log-effort="true"]'));
    if (days.length) days.at(-1).dispatchEvent(new Event('work-add-effort'));
    else root.querySelector('[data-modal-open="dashboard-log-modal"]')?.click();
  });
  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-work-block-action]')) {
      const preview = document.getElementById('dashboard-view-modal');
      preview.classList.remove('is-open');
      preview.setAttribute('aria-hidden', 'true');
    }
    const trigger = event.target.closest('[data-modal-open="dashboard-view-modal"]');
    if (!trigger) return;
    try {
      const payload = JSON.parse(trigger.dataset.modalPayload);
      const link = document.querySelector('[data-work-detail-link]');
      if (link && payload._detailUrl?.startsWith('/')) {
        link.href = payload._detailUrl;
        const resume = document.querySelector('[data-work-resume-form]');
        resume.action = payload._detailUrl + '/resume';
        resume.hidden = payload._taskStatus !== 'stalled';
        const block = document.querySelector('[data-work-block-action]');
        block.hidden = ['closed', 'stalled'].includes(payload._taskStatus);
        block.dataset.modalPayload = JSON.stringify({ _action: payload._detailUrl + '/stall', task_name_text: payload.task_id_text + ' · ' + payload.task_name_text, stalled_reason: '', redirect_to: window.location.pathname });
      }
    } catch (_) { /* Task title and permanent ID remain valid links. */ }
  });
  document.addEventListener('task-created', (event) => {
    if (event.detail?.task_id) window.location.assign(`${window.location.pathname}?created_task_id=${encodeURIComponent(event.detail.task_id)}`);
  });

  const requestDialog = document.querySelector('[data-work-regularization-dialog]');
  const requestForm = requestDialog.querySelector('[data-work-request-form]');
  const requestDate = requestDialog.querySelector('[data-work-request-date]');
  const requestError = requestDialog.querySelector('[data-work-request-error]');
  let attendance = null;
  let attendanceRequest = null;
  let returnFocus = null;
  let submitting = false;
  function updateAttention(missingCount) {
    const count = Number(root.dataset.baseAttention) + missingCount;
    find('[data-work-attention-count]').textContent = count;
    find('[data-work-inbox-count]').textContent = `${count} action${count === 1 ? '' : 's'}`;
    if (find('[data-work-all-clear]')) find('[data-work-all-clear]').hidden = count > 0;
  }
  function showAttendance(data) {
    attendance = data;
    const record = find('[data-work-record]');
    if (record) record.hidden = true;
    if (data.status !== 'synced') {
      find('[data-work-attendance-mode]').textContent = 'Attendance unavailable';
      find('[data-work-check-in]').textContent = '—';
      find('[data-work-check-out]').textContent = '—';
      find('[data-work-freshness]').textContent = 'Unable to confirm your attendance. Open your profile to check or try again.';
      find('[data-work-attendance-retry]').hidden = false;
      find('[data-work-missing-notice]').hidden = true;
      updateAttention(0);
      return;
    }
    const today = data.today;
    if (record) {
      record.hidden = Boolean(today && (!today.is_open || today.mode_label === 'Office'));
      record.dataset.action = today?.is_open ? 'out' : 'in';
      record.textContent = today?.is_open ? 'Log out · Remote' : 'Log in · Remote';
    }
    find('[data-work-attendance-mode]').textContent = today ? `${today.mode_label}${today.attendance_location ? ' · ' + today.attendance_location : ''}` : 'No punch recorded yet today';
    find('[data-work-check-in]').textContent = today?.first_in_label || '—';
    find('[data-work-check-out]').textContent = today?.is_open ? 'Still working' : today?.last_out_label || '—';
    find('[data-work-freshness]').textContent = `Zoho checked ${data.synced_at}${data.leave_status !== 'synced' ? ' · Leave unavailable; missing-day reminders are paused.' : ''}`;
    find('[data-work-attendance-retry]').hidden = false;
    find('[data-work-attendance-retry]').textContent = 'Check again';
    find('[data-work-missing-notice]').hidden = !data.missing_count;
    find('[data-work-missing-title]').textContent = `${data.missing_count} attendance day${data.missing_count === 1 ? '' : 's'} missing`;
    find('[data-work-regularize]').hidden = !data.can_request;
    find('[data-work-manager-note]').hidden = data.can_request;
    find('[data-work-pending-notice]').hidden = !data.pending_count;
    find('[data-work-pending-text]').textContent = `${data.pending_count} remote regularization request${data.pending_count === 1 ? ' is' : 's are'} awaiting your manager’s approval.`;
    updateAttention(data.missing_count || 0);
    if (data.remaining_available_hours !== null) {
      root.querySelectorAll('[data-work-remaining-capacity]').forEach((node) => { node.textContent = Number(data.remaining_available_hours).toLocaleString(undefined, { maximumFractionDigits: 2 }); });
    }
    if (data.available_hours !== null) {
      root.querySelectorAll('[data-work-capacity]').forEach((node) => { node.textContent = Number(data.available_hours).toLocaleString(undefined, { maximumFractionDigits: 2 }); });
      find('[data-work-capacity-source]').textContent = 'After approved leave and holidays';
    }
  }
  async function loadAttendance() {
    if (attendanceRequest) return attendanceRequest;
    const controller = new AbortController();
    // The task queue never waits for this independent request.
    const timeout = setTimeout(() => controller.abort(), 65000);
    const retry = find('[data-work-attendance-retry]');
    retry.disabled = true;
    attendanceRequest = (async () => {
      try {
        const response = await fetch(root.dataset.attendanceUrl, { credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json' } });
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Attendance unavailable');
        showAttendance(await response.json());
      } catch (_) {
        showAttendance({ status: 'failed' });
      } finally {
        clearTimeout(timeout);
        retry.disabled = false;
        attendanceRequest = null;
      }
    })();
    return attendanceRequest;
  }
  find('[data-work-attendance-retry]').addEventListener('click', loadAttendance);
  find('[data-work-record]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget, message = find('[data-work-record-message]');
    button.disabled = true; message.textContent = 'Recording your attendance…';
    try {
      const response = await fetch(root.dataset.attendanceUrl + '/punch', {
        method: 'POST', body: new URLSearchParams({action: button.dataset.action}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Unable to record attendance. Please try again.');
      message.textContent = result.message;
      await loadAttendance();
    } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
  });
  find('[data-work-regularize]').addEventListener('click', (event) => {
    if (!attendance?.missing_dates?.length || !attendance.can_request) return;
    requestDate.replaceChildren(...attendance.missing_dates.filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date)).map((date) => {
      const option = document.createElement('option');
      option.value = date;
      option.textContent = new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
      return option;
    }));
    requestError.hidden = true;
    returnFocus = event.currentTarget;
    requestDialog.showModal();
  });
  requestDialog.querySelectorAll('[data-work-dialog-close]').forEach((button) => button.addEventListener('click', () => { if (!submitting) requestDialog.close(); }));
  requestDialog.addEventListener('cancel', (event) => { if (submitting) event.preventDefault(); });
  requestDialog.addEventListener('close', () => returnFocus?.focus());
  requestForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    const button = requestForm.querySelector('[type="submit"]');
    button.disabled = true;
    button.textContent = 'Sending…';
    requestError.hidden = true;
    try {
      const response = await fetch(requestForm.action, { method: 'POST', credentials: 'same-origin', body: new FormData(requestForm), headers: { Accept: 'application/json' } });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Unable to record your request. Please check your profile.');
      requestDialog.close();
      // Refresh server-confirmed pending states; do not count pending requests as worked.
      await loadAttendance();
    } catch (error) {
      requestError.hidden = false;
      requestError.textContent = error.message || 'Unable to submit. Please try again.';
    } finally {
      submitting = false;
      button.disabled = false;
      button.textContent = 'Send for approval';
    }
  });
  render();
  loadAttendance();
})();

(() => {
  const card = document.querySelector('[data-today-people]');
  if (!card) return;
  const list = card.querySelector('[data-people-list]'), meta = card.querySelector('[data-people-meta]');
  const refresh = card.querySelector('[data-people-refresh]'), expand = card.querySelector('[data-people-expand]');
  let data = null, expanded = false, timer;
  function render() {
    if (!data) return;
    clearTimeout(timer);
    list.replaceChildren();
    card.querySelector('[data-people-counts]').textContent = `${data.people.filter(p => p.office).length} in office · ${data.people.filter(p => p.leave).length} on leave`;
    const visible = data.people.slice(0, expanded ? undefined : 6);
    const leaveTags = card.querySelector('[data-people-leave-tags]');
    leaveTags.replaceChildren();
    card.querySelector('[data-people-leaves]').hidden = !visible.some(person => person.leave);
    for (const person of visible) {
      const leave = person.leave_count < 1 ? `Half-day leave${person.session === 1 ? ' · AM' : person.session === 2 ? ' · PM' : ''}` : 'On leave';
      if (person.leave) {
        const tag = document.createElement('span'); tag.className = 'wd-leave-tag';
        tag.textContent = person.name.trim().split(/\s+/)[0];
        if (person.leave_count < 1) tag.textContent += person.session === 1 ? ' · ½ AM' : person.session === 2 ? ' · ½ PM' : ' · ½';
        tag.title = `${person.name} · ${leave}`; tag.setAttribute('aria-label', tag.title); leaveTags.append(tag);
      }
      if (!person.office) continue;
      const row = document.createElement('li'), avatar = document.createElement('span'), name = document.createElement('strong'), badge = document.createElement('span');
      avatar.className = 'wd-people-avatar';
      const img = document.createElement('img');
      img.src = person.avatar || '/static/profile-placeholder.svg'; img.alt = `${person.name} profile picture`; img.loading = 'lazy';
      img.addEventListener('error', () => { img.src = '/static/profile-placeholder.svg'; }, {once: true}); avatar.append(img);
      name.textContent = person.name;
      badge.textContent = '🏢 Office today';
      badge.className = 'wd-people-badge'; row.append(avatar, name, badge); list.append(row);
    }
    expand.hidden = data.people.length <= 6;
    expand.textContent = expanded ? 'Show fewer' : `View all ${data.people.length} people`;
    expand.setAttribute('aria-expanded', String(expanded));
    const busy = data.status === 'running'; refresh.disabled = busy; refresh.textContent = busy ? 'Refreshing…' : 'Refresh';
    const stamp = card.querySelector('[data-people-sync]');
    stamp.textContent = data.synced_at ? `· ${data.synced_at}` : '';
    stamp.title = data.synced_at ? `Last shared refresh: ${data.synced_at}` : '';
    meta.textContent = [busy ? 'Refreshing…' : data.error,
      !data.synced_at ? 'Refresh to load today’s people.' : '',
      data.synced_at && !data.people.length ? 'No office attendance or approved leave recorded today.' : ''].filter(Boolean).join(' ');
    meta.hidden = !meta.textContent;
    if (busy) timer = setTimeout(load, 3000);
  }
  async function load() {
    clearTimeout(timer);
    try {
      const response = await fetch(card.dataset.url, {cache: 'no-store'});
      if (!response.ok) throw new Error();
      data = await response.json(); render();
    } catch (_) { meta.hidden = false; meta.textContent = 'Unable to load shared information. Please refresh to try again.'; refresh.disabled = false; refresh.textContent = 'Refresh'; }
  }
  refresh.addEventListener('click', async () => {
    refresh.disabled = true; refresh.textContent = 'Refreshing…';
    try {
      const response = await fetch(card.dataset.url + '/refresh', {method: 'POST'});
      if (!response.ok && response.status !== 409) throw new Error();
      await load();
    } catch (_) { meta.hidden = false; meta.textContent = 'Unable to start refresh. Please try again.'; refresh.disabled = false; refresh.textContent = 'Refresh'; }
  });
  expand.addEventListener('click', () => {expanded = !expanded; render();});
  load();
})();

/* Inspect and correct the signed-in person's dated effort without creating duplicates. */
(() => {
  'use strict';
  const dialog = document.querySelector('[data-work-effort-dialog]');
  if (!dialog) return;
  const find = selector => dialog.querySelector(selector);
  const dayInput = find('[data-work-effort-date]');
  const summary = find('[data-work-effort-summary]');
  const list = find('[data-work-effort-entries]');
  const error = find('[data-work-effort-error]');
  const editForm = find('[data-work-effort-edit]');
  const saveError = find('[data-work-effort-save-error]');
  const previous = find('[data-work-effort-previous]');
  const next = find('[data-work-effort-next]');
  const add = find('[data-work-effort-add]');
  const today = dialog.dataset.today;
  let request = null;
  let generation = 0;
  let selected = null;
  let saving = false;
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function controls() {
    dayInput.disabled = Boolean(selected) || saving;
    previous.disabled = Boolean(selected) || saving;
    next.disabled = Boolean(selected) || saving || dayInput.value >= today;
    const card = document.querySelector(`[data-dashboard-leave-day][data-date="${dayInput.value}"]`);
    add.hidden = card?.dataset.canLogEffort !== 'true';
    add.disabled = Boolean(selected) || saving;
  }
  function cancelEdit() {
    selected = null;
    editForm.hidden = true;
    list.hidden = false;
    saveError.hidden = true;
    controls();
  }
  function edit(entry) {
    selected = entry;
    editForm.reset();
    editForm.elements.log_date.value = dayInput.value;
    editForm.elements.hours.value = entry.hours;
    editForm.elements.notes.value = entry.notes || '';
    find('[data-work-effort-edit-title]').textContent = `Edit ${entry.task_code} · ${entry.task_name}`;
    list.hidden = true;
    editForm.hidden = false;
    saveError.hidden = true;
    controls();
    editForm.elements.log_date.focus();
  }
  async function load(date) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    request?.abort();
    const current = ++generation;
    request = new AbortController();
    dayInput.value = date;
    cancelEdit();
    error.hidden = true;
    summary.textContent = 'Loading your effort entries…';
    list.replaceChildren();
    try {
      const response = await fetch(`${dialog.dataset.effortUrl}?log_date=${encodeURIComponent(date)}`, { credentials: 'same-origin', cache: 'no-store', signal: request.signal, headers: { Accept: 'application/json' } });
      if (!response.ok || response.redirected) throw new Error('Unable to load effort. Please check your connection or sign in again.');
      const data = await response.json();
      if (current !== generation) return;
      const label = new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
      summary.textContent = `${label} · ${data.total_hours}h across ${data.entries.length} ${data.entries.length === 1 ? 'entry' : 'entries'}`;
      if (!data.entries.length) list.append(element('p', 'No effort is recorded for this day.', 'wd-effort-empty'));
      data.entries.forEach(entry => {
        const article = element('article', null, 'wd-effort-entry');
        const head = element('div', null, 'wd-effort-entry-head');
        const title = element('a', `${entry.task_code} · ${entry.task_name}`);
        title.href = entry.task_url;
        head.append(title, element('strong', `${entry.hours}h`));
        article.append(head, element('small', `${entry.project} · ${entry.status.replaceAll('_', ' ')}`), element('p', entry.notes || 'No work notes recorded.'));
        const button = element('button', 'Edit date, hours & notes', 'wd-btn wd-small');
        button.type = 'button';
        button.addEventListener('click', () => edit(entry));
        article.append(button);
        list.append(article);
      });
    } catch (failure) {
      if (failure.name === 'AbortError' || current !== generation) return;
      summary.textContent = '';
      error.textContent = failure.message;
      error.hidden = false;
      const retry = element('button', 'Try again', 'wd-btn wd-small');
      retry.type = 'button';
      retry.addEventListener('click', () => load(date));
      list.append(retry);
    }
  }
  function open(date) {
    if (!dialog.open) dialog.showModal();
    load(date);
  }
  document.querySelectorAll('[data-dashboard-leave-day]').forEach(card => card.addEventListener('click', () => open(card.dataset.date)));
  document.querySelector('[data-work-effort-history]')?.addEventListener('click', () => open(today));
  find('[data-work-effort-close]').addEventListener('click', () => { if (!saving) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => { request?.abort(); generation++; });
  find('[data-work-effort-cancel]').addEventListener('click', cancelEdit);
  dayInput.addEventListener('change', () => { if (dayInput.validity.valid && dayInput.value) load(dayInput.value); });
  function moveDay(offset) {
    const date = new Date(`${dayInput.value}T12:00:00`);
    date.setDate(date.getDate() + offset);
    load(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`);
  }
  previous.addEventListener('click', () => moveDay(-1));
  next.addEventListener('click', () => moveDay(1));
  add.addEventListener('click', () => {
    const card = document.querySelector(`[data-dashboard-leave-day][data-date="${dayInput.value}"]`);
    dialog.close();
    card?.dispatchEvent(new Event('work-add-effort'));
  });
  editForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selected || saving || !editForm.reportValidity()) return;
    saving = true;
    controls();
    editForm.querySelectorAll('button').forEach(button => { button.disabled = true; });
    saveError.hidden = true;
    try {
      const response = await fetch(`${dialog.dataset.effortUrl}/${selected.id}`, {
        method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ log_date: editForm.elements.log_date.value, hours: editForm.elements.hours.value, notes: editForm.elements.notes.value, revision: selected.revision }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to save this effort entry.');
      // Reload the overview so both weeks' totals and remaining capacity reflect the correction.
      const url = new URL(window.location.href);
      url.search = '';
      url.searchParams.set('effort_date', data.date);
      url.searchParams.set('effort_saved', '1');
      window.location.assign(url.href);
    } catch (failure) {
      saveError.textContent = failure.message;
      saveError.hidden = false;
      saving = false;
      controls();
      editForm.querySelectorAll('button').forEach(button => { button.disabled = false; });
    }
  });
  const params = new URLSearchParams(window.location.search);
  if (params.has('effort_date') && /^\d{4}-\d{2}-\d{2}$/.test(params.get('effort_date'))) {
    open(params.get('effort_date'));
    if (params.get('effort_saved') === '1') {
      const notice = element('p', 'Effort updated. Your dashboard totals have been recalculated.', 'wd-effort-saved');
      find('.wd-effort-body').prepend(notice);
    }
  }
})();
