/* Keep job output live without replacing its controls or scroll container. */
(() => {
  const filters = document.querySelectorAll('[data-refresh-job-log]');
  const follow = document.getElementById('follow-job-log');
  const viewer = document.getElementById('job-log-container');
  if (!viewer) return;

  function followLatest() {
    if (follow.checked) viewer.scrollTop = viewer.scrollHeight;
  }

  try {
    const saved = JSON.parse(localStorage.getItem('kmm-job-log-levels'));
    const allowed = new Set(Array.from(filters, (input) => input.value));
    if (Array.isArray(saved) && saved.every((level) => allowed.has(level))) {
      filters.forEach((input) => { input.checked = saved.includes(input.value); });
    }
  } catch { /* Filtering also works without browser storage. */ }

  filters.forEach((input) => {
    input.addEventListener('change', () => {
      try {
        localStorage.setItem('kmm-job-log-levels', JSON.stringify(
          Array.from(filters).filter((item) => item.checked).map((item) => item.value),
        ));
      } catch { /* Keep the selection for this page. */ }
      htmx.trigger(document.getElementById('job-log-lines'), 'refresh');
    });
  });
  follow.addEventListener('change', followLatest);
  new ResizeObserver(followLatest).observe(viewer);
  document.body.addEventListener('htmx:afterSettle', (event) => {
    if (event.target.id === 'job-log-lines') followLatest();
  });
  // An initially closed disclosure cannot be scrolled until it opens.
  viewer.closest('details').addEventListener('toggle', followLatest);
})();
