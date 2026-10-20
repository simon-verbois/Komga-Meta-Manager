/* Source templates prepare the form. Only an explicit save persists library settings. */
(() => {
  const select = document.querySelector('[data-source-template]');
  if (!select) return;
  const form = select.closest('form');
  const list = form.querySelector('[data-source-list]');
  const rows = Array.from(list.children);
  const status = form.querySelector('[data-source-status]');
  const add = form.querySelector('[data-add-source]');
  const addButton = form.querySelector('[data-add-source-button]');
  const templates = JSON.parse(form.querySelector('[data-source-template-data]').textContent);
  function refresh() {
    const visible = Array.from(list.children).filter(row => row.dataset.sourceSelected === 'true');
    visible.forEach((row, i) => {
      row.querySelector('.source-rank').textContent = i + 1;
      row.querySelector('[data-move="up"]').disabled = i === 0;
      row.querySelector('[data-move="down"]').disabled = i === visible.length - 1;
    });
    rows.forEach(row => {
      const chosen = row.dataset.sourceSelected === 'true';
      const option = Array.from(add.options).find(item => item.value === row.dataset.source);
      if (option) option.disabled = chosen;
    });
    addButton.disabled = !add.value || add.selectedOptions[0].disabled;
    form.querySelector('[data-source-empty]').hidden = visible.length > 0;
  }
  function activate(row, selected) {
    row.dataset.sourceSelected = String(selected);
    row.hidden = !selected;
    row.querySelectorAll('input, select').forEach(control => { control.disabled = !selected; });
  }
  select.addEventListener('change', () => {
    form.querySelector('[data-apply-template]').disabled = !select.value;
    const remove = form.querySelector('[data-delete-template]');
    remove.disabled = select.selectedOptions[0]?.dataset.personal !== 'true';
    remove.hidden = remove.disabled;
    const update = form.querySelector('[data-update-template]');
    update.disabled = remove.disabled;
    update.hidden = remove.hidden;
  });
  form.querySelector('[data-apply-template]').addEventListener('click', () => {
    const template = templates[select.value];
    if (!template) return;
    rows.forEach(row => activate(row, false));
    template.providers.slice().sort((a, b) => a.priority - b.priority).forEach(source => {
      const row = rows.find(item => item.dataset.source === source.name);
      if (!row) return;
      activate(row, true);
      list.append(row);
      for (const [suffix, value] of Object.entries({enabled: source.enabled ?? true,
        min_score: source.min_score ?? 80, preferred_language: source.preferred_language ?? 'en',
        allow_adult: source.allow_adult ?? false, cache_ttl: source.cache?.ttl_hours ?? 168})) {
        const input = row.querySelector(`[name="${source.name}_${suffix}"]`);
        if (!input) continue;
        if (input.type === 'checkbox') input.checked = Boolean(value);
        else {
          if (input instanceof HTMLSelectElement && !Array.from(input.options).some(option => option.value === value)) {
            input.add(new Option(value, value));
          }
          input.value = value;
        }
      }
    });
    window.KMM.notify(status.dataset.applied, 'info');
    refresh();
    form.dispatchEvent(new Event('kmm:reordered'));
  });
  add.addEventListener('change', refresh);
  addButton.addEventListener('click', () => {
    const row = rows.find(item => item.dataset.source === add.value);
    if (!row) return;
    activate(row, true);
    row.querySelector('[role="switch"]').checked = true;
    list.append(row);
    add.value = '';
    refresh();
    row.querySelector('[role="switch"]').focus();
    form.dispatchEvent(new Event('kmm:reordered'));
  });
  list.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-source]');
    if (remove) {
      activate(remove.closest('.source-row'), false);
      refresh();
      add.focus();
      form.dispatchEvent(new Event('kmm:reordered'));
    }
    // The shared reorder handler runs on document; refresh after it has moved the row.
    if (event.target.closest('[data-move]')) queueMicrotask(refresh);
  });
  refresh();
})();
