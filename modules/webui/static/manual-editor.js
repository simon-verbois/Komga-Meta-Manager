/* Manual edits are saved in KMM and wait in Review; Komga changes only when the user publishes. */
(() => {
  const dialog = document.getElementById('overwrite-dialog');
  if (!dialog) return;
  const messages = JSON.parse(dialog.dataset.editorMessages);
  const text = (key, values = {}) => Object.entries(values).reduce(
    (value, [name, replacement]) => value.replaceAll(`{${name}}`, replacement), messages[key] || key,
  );
  const libraryId = encodeURIComponent(dialog.dataset.libraryId);
  const form = document.getElementById('manual-editor-form');
  const feedback = document.getElementById('manual-feedback');
  const loading = document.getElementById('manual-loading');
  const reload = document.getElementById('manual-reload');
  const apply = document.getElementById('manual-apply');
  const coverInput = document.getElementById('manual-cover');
  const coverAllBooks = document.getElementById('manual-cover-all-books');
  const coverPreview = document.getElementById('manual-cover-preview');
  const provider = document.getElementById('manual-provider-disclosure');
  const skipSection = document.getElementById('manual-skip-section');
  const skip = document.getElementById('manual-skip');
  const skipStatus = document.getElementById('manual-skip-status');
  let baseline, selection, opener, busy = false, generation = 0, coverUrl;
  const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const lines = value => [...new Set(value.split('\n').map(line => line.trim()).filter(Boolean))].sort();
  const input = name => form.elements.namedItem(name);
  const endpoint = `/libraries/${libraryId}/manual`;
  function showFeedback(message, kind = 'error') {
    feedback.className = `alert alert-${kind}`;
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    feedback.scrollIntoView({block: 'nearest'});
  }
  function draft() {
    if (!baseline) return {};
    const changes = {};
    for (const [name, previous] of Object.entries(baseline.values)) {
      if (['writers', 'pencillers'].includes(name)) {
        if (input(`change_${name}`).checked) changes[name] = lines(input(name).value);
        continue;
      }
      let value;
      if (name === 'links') {
        const raw = Array.from(document.querySelectorAll('.manual-link-row'), row => ({
          label: row.querySelector('[data-link-label]').value,
          url: row.querySelector('[data-link-url]').value,
        }));
        if (equal(raw, previous)) continue;
        value = raw.map(link => ({label: link.label.trim(), url: link.url.trim()}));
      } else {
        const raw = input(name).value;
        const original = Array.isArray(previous) ? previous.join('\n') : (previous ?? '');
        if (raw === original) continue;
        if (['genres', 'tags'].includes(name)) value = lines(raw);
        else value = name === 'summary' ? raw : name === 'reading_direction' ? (raw || null) : raw.trim();
      }
      if (!equal(value, previous)) changes[name] = value;
    }
    return changes;
  }
  const hasDraft = () => baseline && (Object.keys(draft()).length > 0 || coverInput.files.length > 0 || coverAllBooks.checked);
  function releaseCover() {
    if (coverUrl) URL.revokeObjectURL(coverUrl);
    coverUrl = null;
  }
  function currentCover() {
    releaseCover();
    coverPreview.hidden = false;
    coverPreview.src = `/libraries/${libraryId}/${baseline.entity}/${encodeURIComponent(baseline.id)}/thumbnail?v=${Date.now()}`;
  }
  coverPreview.addEventListener('error', () => { coverPreview.hidden = true; });
  function addLink(link = {label: '', url: ''}) {
    const row = document.createElement('div');
    row.className = 'manual-link-row';
    for (const [name, value] of Object.entries(link)) {
      const label = document.createElement('label');
      label.textContent = text(name === 'label' ? 'link_label' : 'link_url');
      const field = document.createElement('input');
      field.type = name === 'url' ? 'url' : 'text';
      field.required = true;
      field.value = value;
      field.setAttribute(name === 'label' ? 'data-link-label' : 'data-link-url', '');
      label.append(field);
      row.append(label);
    }
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'button button-secondary button-small';
    remove.textContent = text('remove_link');
    remove.addEventListener('click', () => row.remove());
    row.append(remove);
    document.getElementById('manual-links').append(row);
  }
  document.getElementById('manual-add-link').addEventListener('click', () => addLink());
  function populate(current) {
    baseline = current;
    form.reset();
    for (const section of form.querySelectorAll('[data-editor-field]')) {
      const supported = Object.hasOwn(current.values, section.dataset.editorField);
      section.hidden = !supported;
      section.querySelectorAll('input, textarea, select, button').forEach(control => { control.disabled = !supported; });
    }
    document.getElementById('manual-links').replaceChildren();
    for (const [name, value] of Object.entries(current.values)) {
      if (name === 'links') value.forEach(link => addLink(link));
      else input(name).value = Array.isArray(value) ? value.join('\n') : (value ?? '');
    }
    for (const role of ['writers', 'pencillers']) {
      input(role).disabled = true;
      document.querySelector(`[data-mixed-for="${role}"]`).hidden = !current.mixed[role];
    }
    document.querySelectorAll('[data-lock-for]').forEach(badge => {
      const locked = current.locks[badge.dataset.lockFor];
      badge.hidden = !locked;
      const control = input(badge.dataset.lockFor);
      if (locked) control?.setAttribute('aria-description', text('locked'));
      else control?.removeAttribute('aria-description');
    });
    document.getElementById('manual-item-title').textContent = current.title;
    document.getElementById('manual-kind').textContent = text(current.entity === 'books' ? 'kind_book' : 'kind_series');
    document.getElementById('manual-scope').textContent = text(current.entity === 'books' ? 'scope_book' : 'scope_series');
    document.getElementById('manual-provider-scope').textContent = text(current.entity === 'books' ? 'provider_scope_book' : 'provider_scope_series');
    document.getElementById('manual-author-scope').textContent = current.entity === 'books'
      ? text('author_scope_book') : text('author_scope_series', {n: current.book_count});
    document.getElementById('manual-clear-cover').hidden = true;
    document.getElementById('manual-cover-books-section').hidden = current.entity === 'books';
    coverAllBooks.disabled = current.entity === 'books' || !current.book_count;
    document.getElementById('manual-cover-books-count').textContent = current.book_count
      ? text('cover_books_count', {n: current.book_count}) : text('cover_no_books');
    currentCover();
  }
  async function load() {
    const active = ++generation;
    baseline = null;
    form.hidden = true;
    feedback.hidden = true;
    reload.hidden = true;
    loading.hidden = false;
    provider.hidden = true;
    skipSection.hidden = true;
    document.getElementById('manual-item-title').textContent = opener?.querySelector('.book-title')?.textContent || '';
    const params = new URLSearchParams({series_id: selection.series_id});
    if (selection.book_id) params.set('book_id', selection.book_id);
    try {
      const response = await fetch(`${endpoint}?${params}`, {redirect: 'error'});
      const result = await response.json();
      if (active !== generation || !dialog.open) return;
      if (!response.ok) throw new Error(result.error || 'manual.connection');
      populate(result);
      form.hidden = false;
      provider.hidden = false;
      skipSection.hidden = false;
      document.getElementById('manual-title').focus();
    } catch (error) {
      if (active !== generation || !dialog.open) return;
      // API errors contain translation keys; network errors use the connection fallback.
      const key = error.message?.replace(/^manual\./, '');
      showFeedback(messages[key] || text('connection'));
      reload.hidden = false;
    } finally {
      if (active === generation) loading.hidden = true;
    }
  }
  function open(button) {
    opener = button;
    selection = {series_id: button.dataset.seriesId, book_id: button.dataset.bookId || ''};
    document.getElementById('overwrite-series-id').value = selection.series_id;
    document.getElementById('overwrite-book-id').value = selection.book_id;
    document.getElementById('source-refresh-form').reset();
    skip.checked = button.dataset.skipped === '1';
    skipStatus.textContent = '';
    if (!dialog.open) dialog.showModal();
    dialog.querySelector('.drawer-body').scrollTop = 0;
    load();
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-overwrite]');
    if (button) open(button);
  });
  const visibleCards = () => Array.from(document.querySelectorAll('[data-overwrite]'))
    .filter(button => !button.closest('.book-card')?.hidden);
  dialog.querySelectorAll('[data-editor-step]').forEach(stepButton => stepButton.addEventListener('click', () => {
    if (busy) return;
    if (hasDraft() && !window.confirm(text('discard_confirm'))) return;
    const cards = visibleCards();
    const index = cards.indexOf(opener);
    const next = cards[(index + Number(stepButton.dataset.editorStep) + cards.length) % cards.length];
    if (next) open(next);
  }));
  function close() {
    if (busy) return;
    if (hasDraft() && !window.confirm(text('discard_confirm'))) return;
    generation++;
    dialog.close();
  }
  dialog.querySelector('[data-close-editor]').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.addEventListener('close', () => {
    releaseCover();
    const replacement = Array.from(document.querySelectorAll('[data-overwrite]')).find(button =>
      button.dataset.seriesId === selection?.series_id && (button.dataset.bookId || '') === selection?.book_id);
    (opener?.isConnected ? opener : replacement)?.focus();
  });
  reload.addEventListener('click', () => {
    if (!hasDraft() || window.confirm(text('discard_confirm'))) load();
  });
  window.addEventListener('beforeunload', event => {
    if (dialog.open && hasDraft()) { event.preventDefault(); event.returnValue = ''; }
  });
  form.addEventListener('change', event => {
    for (const role of ['writers', 'pencillers']) {
      if (event.target.name === `change_${role}`) input(role).disabled = !event.target.checked;
    }
  });
  coverInput.addEventListener('change', () => {
    releaseCover();
    const file = coverInput.files[0];
    document.getElementById('manual-clear-cover').hidden = !file;
    if (!file) return currentCover();
    if (file.size > 20 * 1024 * 1024) showFeedback(text('cover_invalid'));
    coverUrl = URL.createObjectURL(file);
    coverPreview.hidden = false;
    coverPreview.src = coverUrl;
  });
  document.getElementById('manual-clear-cover').addEventListener('click', () => {
    coverInput.value = '';
    document.getElementById('manual-clear-cover').hidden = true;
    currentCover();
  });
  function refreshLibrary() {
    htmx.ajax('GET', `/libraries/${libraryId}/content`, {target: '#library-content', swap: 'innerHTML'}).then(() => {
      // Keep the editor attached to the refreshed card so previous/next still work.
      const replacement = Array.from(document.querySelectorAll('[data-overwrite]')).find(button =>
        button.dataset.seriesId === selection?.series_id && (button.dataset.bookId || '') === selection?.book_id);
      if (replacement) opener = replacement;
    });
  }
  async function save() {
    if (busy || !baseline || !form.reportValidity()) return;
    const changes = draft();
    if (!Object.keys(changes).length && !coverInput.files.length && !coverAllBooks.checked) { showFeedback(text('empty'), 'info'); return; }
    const payload = {...selection, changes, baseline, cover_all_books: coverAllBooks.checked,
      lock_fields: input('manual-lock-fields').checked, mode: 'apply'};
    const data = new FormData();
    data.set('edit', JSON.stringify(payload));
    if (coverInput.files[0]) data.set('cover', coverInput.files[0]);
    const disabled = Array.from(form.elements, control => [control, control.disabled]);
    busy = true;
    disabled.forEach(([control]) => { control.disabled = true; });
    dialog.querySelector('[data-close-editor]').disabled = true;
    provider.inert = true;
    form.setAttribute('aria-busy', 'true');
    showFeedback(text('saving'), 'info');
    try {
      const response = await fetch(endpoint, {method: 'POST', body: data, redirect: 'error'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'manual.connection');
      if (result.current) baseline = result.current;
      if (result.cover_applied) { coverInput.value = ''; document.getElementById('manual-clear-cover').hidden = true; }
      if (!result.failed.length && !result.refresh_failed) {
        populate(result.current);
        showFeedback(text('saved'), 'success');
      } else showFeedback(text(result.refresh_failed ? 'refresh_failed' : result.applied.length ? 'partial' : 'failed'));
      if (result.refresh_failed) { baseline = null; reload.hidden = false; }
      if (result.applied.length) refreshLibrary();
    } catch (error) {
      const key = error.message?.replace(/^manual\./, '');
      showFeedback(messages[key] || text('connection'));
      if (['conflict', 'reload'].includes(key)) reload.hidden = false;
    } finally {
      busy = false;
      disabled.forEach(([control, wasDisabled]) => { control.disabled = wasDisabled; });
      // Author replacements stay opt-in after a successful save.
      for (const role of ['writers', 'pencillers']) input(role).disabled = !input(`change_${role}`).checked;
      dialog.querySelector('[data-close-editor]').disabled = false;
      provider.inert = false;
      form.removeAttribute('aria-busy');
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); save(); });
  skip.addEventListener('change', async () => {
    const wanted = skip.checked;
    const data = new FormData();
    data.set('series_name', opener?.dataset.seriesName || '');
    data.set('skip', wanted ? '1' : '0');
    skip.disabled = true;
    try {
      const response = await fetch(`/libraries/${libraryId}/skip`, {method: 'POST', body: data, redirect: 'error'});
      if (!response.ok) throw new Error();
      skipStatus.textContent = text(wanted ? 'skip_on' : 'skip_off');
      document.querySelectorAll(`[data-overwrite][data-series-id="${CSS.escape(selection.series_id)}"]`).forEach(button => {
        button.dataset.skipped = wanted ? '1' : '0';
        button.closest('.book-card').dataset.skipped = wanted ? '1' : '0';
      });
    } catch {
      skip.checked = !wanted;
      skipStatus.textContent = text('skip_failed');
    } finally {
      skip.disabled = false;
    }
  });
})();
