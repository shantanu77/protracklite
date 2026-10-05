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
    if (day?.dataset.canLogEffort === 'true') day.click();
  }
  root.querySelectorAll('[data-work-log-date]').forEach((button) => button.addEventListener('click', () => openDay(button.dataset.workLogDate)));
  find('[data-work-log]').addEventListener('click', () => {
    const days = Array.from(root.querySelectorAll('[data-dashboard-leave-day][data-can-log-effort="true"]'));
    if (days.length) days.at(-1).click();
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
