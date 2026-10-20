/* Manual book ordering in Review. Pointer gestures never publish to Komga. */
(() => {
  let saving = false;
  let gesture = null;
  let suppressClick = false;
  const rowsOf = (list) => Array.from(list.querySelectorAll(':scope > [data-order-book-id]'));
  const handlesOf = (list) => list.querySelectorAll('[data-order-handle]');
  const closeMenus = () => {
    document.querySelectorAll('[data-order-menu]').forEach((menu) => { menu.hidden = true; });
    document.querySelectorAll('[data-order-handle]').forEach((handle) => handle.setAttribute('aria-expanded', 'false'));
  };
  const statusOf = (list) => list.closest('[data-series-id]').querySelector('[data-order-status]');
  const focusBook = (list, id) => rowsOf(list).find((row) => row.dataset.orderBookId === id)
    ?.querySelector('[data-order-handle]').focus({ preventScroll: true });

  async function save(list, original, movedId, openBooks) {
    const order = rowsOf(list).map((row) => row.dataset.orderBookId);
    if (order.every((id, index) => id === original[index].dataset.orderBookId)) return;
    saving = true;
    closeMenus();
    const article = list.closest('[data-series-id]');
    const selected = article.querySelector('[data-review-select]').checked;
    const expanded = article.querySelector('.review-series-details').open;
    const publish = document.querySelector('[data-publish-button]');
    if (publish) publish.disabled = true;
    handlesOf(list).forEach((handle) => { handle.disabled = true; });
    list.setAttribute('aria-busy', 'true');
    statusOf(list).textContent = list.dataset.saving;
    let failure = list.dataset.failed;
    let confirmed = false;
    try {
      const response = await fetch(list.dataset.reorderUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order, version: list.dataset.version }),
      });
      if (!response.ok) {
        const result = await response.json();
        failure = result.error || failure;
        throw new Error('Order rejected');
      }
      const documentCopy = new DOMParser().parseFromString(await response.text(), 'text/html');
      const replacement = Array.from(documentCopy.querySelectorAll('[data-series-id]'))
        .find((group) => group.dataset.seriesId === article.dataset.seriesId);
      if (!replacement) throw new Error('Missing updated series');
      replacement.querySelector('[data-review-select]').checked = selected;
      replacement.querySelector('.review-series-details').open = expanded;
      replacement.querySelectorAll('.review-book').forEach((details) => {
        details.open = openBooks.get(details.dataset.bookId) || false;
      });
      const movedRow = rowsOf(replacement.querySelector('[data-review-order]'))
        .find((row) => row.dataset.orderBookId === movedId);
      const previousY = rowsOf(list).find((row) => row.dataset.orderBookId === movedId)?.getBoundingClientRect().top;
      article.replaceWith(replacement);
      const count = documentCopy.querySelector('[data-review-summary-count]');
      if (count) document.querySelector('[data-review-summary-count]').textContent = count.textContent;
      const newList = replacement.querySelector('[data-review-order]');
      statusOf(newList).textContent = newList.dataset.saved;
      if (movedRow && previousY !== undefined) window.scrollBy(0, movedRow.getBoundingClientRect().top - previousY);
      focusBook(newList, movedId);
      confirmed = true;
    } catch {
      original.forEach((row) => list.append(row));
      list.querySelectorAll('.review-book').forEach((details) => {
        details.open = openBooks.get(details.dataset.bookId) || false;
      });
      // A lost response may follow a successful save. Require a refresh instead
      // of offering a second mutation against an unconfirmed baseline.
      statusOf(list).textContent = failure;
      statusOf(list).classList.add('error-text');
    } finally {
      saving = false;
      list.removeAttribute('aria-busy');
      if (publish) publish.disabled = !confirmed;
    }
  }

  const openState = (list) => new Map(Array.from(list.querySelectorAll('.review-book'))
    .map((details) => [details.dataset.bookId, details.open]));

  function moveOne(handle, direction) {
    if (saving || gesture) return;
    const row = handle.closest('[data-order-book-id]');
    const list = row.parentElement;
    const neighbor = direction < 0 ? row.previousElementSibling : row.nextElementSibling;
    if (!neighbor) return;
    const original = rowsOf(list);
    const opened = openState(list);
    list.insertBefore(direction < 0 ? row : neighbor, direction < 0 ? neighbor : row);
    void save(list, original, row.dataset.orderBookId, opened);
  }

  function placeRow(state) {
    const bounds = state.list.getBoundingClientRect();
    if (state.x < bounds.left || state.x > bounds.right) return;
    const before = rowsOf(state.list).find((row) => row !== state.row
      && state.y < row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2);
    if (state.row.nextElementSibling !== (before || null)) {
      state.list.insertBefore(state.row, before || null);
      state.handle.setPointerCapture(state.pointer);
    }
  }

  function animateDrag() {
    if (!gesture?.dragging) return;
    const state = gesture;
    const edge = 60;
    const speed = state.y < edge ? -12 : state.y > window.innerHeight - edge ? 12 : 0;
    if (speed) window.scrollBy(0, speed);
    placeRow(state);
    state.frame = requestAnimationFrame(animateDrag);
  }

  function startDrag(state) {
    state.dragging = true;
    closeMenus();
    state.list.querySelectorAll('.review-book').forEach((details) => { details.open = false; });
    const bounds = state.row.getBoundingClientRect();
    state.ghost = state.row.cloneNode(true);
    state.ghost.removeAttribute('id');
    state.ghost.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
    state.ghost.classList.add('review-drag-ghost');
    state.ghost.setAttribute('aria-hidden', 'true');
    state.ghost.inert = true;
    Object.assign(state.ghost.style, { width: `${bounds.width}px`, left: `${bounds.left}px`, top: `${state.y - 25}px` });
    document.body.append(state.ghost);
    state.row.classList.add('is-dragged');
    state.frame = requestAnimationFrame(animateDrag);
  }

  function finishDrag(cancelled) {
    const state = gesture;
    if (!state) return;
    gesture = null;
    cancelAnimationFrame(state.frame);
    state.ghost?.remove();
    state.row.classList.remove('is-dragged');
    if (state.handle.hasPointerCapture(state.pointer)) state.handle.releasePointerCapture(state.pointer);
    if (!state.dragging) return;
    suppressClick = true;
    setTimeout(() => { suppressClick = false; }, 0);
    const bounds = state.list.getBoundingClientRect();
    if (cancelled || state.x < bounds.left || state.x > bounds.right || state.y < bounds.top || state.y > bounds.bottom) {
      state.original.forEach((row) => state.list.append(row));
    }
    state.list.querySelectorAll('.review-book').forEach((details) => {
      details.open = state.opened.get(details.dataset.bookId) || false;
    });
    focusBook(state.list, state.row.dataset.orderBookId);
    if (!cancelled) void save(state.list, state.original, state.row.dataset.orderBookId, state.opened);
  }

  document.addEventListener('pointerdown', (event) => {
    const handle = event.target.closest('[data-order-handle]');
    if (!handle || handle.disabled || saving || gesture || !event.isPrimary || event.button !== 0) return;
    const row = handle.closest('[data-order-book-id]');
    const list = row.parentElement;
    gesture = { handle, row, list, pointer: event.pointerId, original: rowsOf(list), opened: openState(list),
      startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, dragging: false };
    handle.setPointerCapture(event.pointerId);
  });
  document.addEventListener('pointermove', (event) => {
    if (!gesture || event.pointerId !== gesture.pointer) return;
    gesture.x = event.clientX;
    gesture.y = event.clientY;
    if (!gesture.dragging && Math.hypot(gesture.x - gesture.startX, gesture.y - gesture.startY) > 6) startDrag(gesture);
    if (gesture.dragging) {
      event.preventDefault();
      gesture.ghost.style.top = `${gesture.y - 25}px`;
      placeRow(gesture);
    }
  });
  document.addEventListener('pointerup', (event) => {
    if (gesture?.pointer === event.pointerId) finishDrag(false);
  });
  document.addEventListener('pointercancel', (event) => {
    if (gesture?.pointer === event.pointerId) finishDrag(true);
  });
  document.addEventListener('lostpointercapture', (event) => {
    if (gesture?.pointer === event.pointerId) finishDrag(true);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      finishDrag(true);
      event.target.closest('[data-order-book-id]')?.querySelector('[data-order-handle]').focus();
      closeMenus();
      return;
    }
    const handle = event.target.closest('[data-order-handle]');
    if (handle && ['ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      moveOne(handle, event.key === 'ArrowUp' ? -1 : 1);
    }
  });
  document.addEventListener('click', (event) => {
    const handle = event.target.closest('[data-order-handle]');
    if (handle) {
      if (suppressClick || saving || handle.disabled) return;
      const menu = handle.parentElement.querySelector('[data-order-menu]');
      const opening = menu.hidden;
      closeMenus();
      menu.hidden = !opening;
      handle.setAttribute('aria-expanded', String(opening));
      return;
    }
    const step = event.target.closest('[data-order-step]');
    if (step) {
      moveOne(step.closest('[data-order-book-id]').querySelector('[data-order-handle]'), Number(step.dataset.orderStep));
      return;
    }
    closeMenus();
  });
  window.addEventListener('beforeunload', (event) => {
    if (saving) { event.preventDefault(); event.returnValue = ''; }
  });
})();
