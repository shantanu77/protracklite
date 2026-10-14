(() => {
  'use strict';
  const root = document.querySelector('[data-manager-dashboard]');
  if (!root) return;
  const dialog = root.querySelector('[data-manager-dialog]');
  const rows = [...root.querySelectorAll('[data-manager-member]')];
  let timer;
  const status = message => {
    const node = root.querySelector('[data-manager-status]');
    node.textContent = message;
    node.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { node.hidden = true; }, 4000);
  };
  root.querySelectorAll('[data-manager-filter]').forEach(button => {
    button.addEventListener('click', () => {
      const filter = button.dataset.managerFilter;
      root.querySelectorAll('[data-manager-filter]').forEach(tab => tab.setAttribute('aria-pressed', String(tab === button)));
      let count = 0;
      root.querySelectorAll('[data-manager-alert]').forEach(item => {
        item.hidden = filter !== 'all' && item.dataset.managerAlert !== filter;
        if (!item.hidden) count++;
      });
      root.querySelector('[data-manager-attention-empty]').hidden = count > 0;
    });
  });
  root.querySelector('[data-manager-search]').addEventListener('input', event => {
    const term = event.target.value.trim().toLocaleLowerCase();
    let count = 0;
    rows.forEach(row => {
      row.hidden = !row.dataset.search.includes(term);
      if (!row.hidden) count++;
    });
    root.querySelector('[data-manager-members-empty]').hidden = count > 0;
    root.querySelector('[data-manager-member-count]').textContent = `${count} of ${rows.length} members`;
  });
  root.querySelector('[data-manager-definitions]').addEventListener('click', () => dialog.showModal());
  root.querySelector('[data-manager-close]').addEventListener('click', () => dialog.close());
  root.querySelector('[data-manager-export]').addEventListener('click', () => {
    const data = JSON.parse(root.querySelector('#manager-export-data').textContent);
    const visibleIds = new Set(rows.filter(row => !row.hidden).map(row => Number(row.dataset.memberId)));
    const quote = value => {
      let text = value == null ? '' : String(value);
      // Neutralize spreadsheet formulas in names and department labels.
      if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
      return `"${text.replaceAll('"', '""')}"`;
    };
    const csv = [
      ['Name', 'Department', 'Remaining estimated hours', 'Remaining available hours', 'Missing estimates', 'Open tasks', 'Overdue tasks', 'Logged hours through yesterday', 'Elapsed available hours', 'Goal achievement percent'],
      ...data.filter(row => visibleIds.has(row.id)).map(row => [row.name, row.department, row.planned, row.available, row.missing_estimates, row.open, row.overdue, row.logged, row.elapsed, row.goal?.progress]),
    ].map(row => row.map(quote).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\ufeff', csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'manager-team-snapshot.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('Exported the team members visible in this table.');
  });
})();
