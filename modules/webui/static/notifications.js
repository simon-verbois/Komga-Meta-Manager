/* Shared transient feedback. Form validation and durable page state stay in context. */
(() => {
  const region = document.getElementById('notification-region');
  if (!region) return;
  const active = new Set();
  const queue = [];
  const defaults = { success: 6000, info: 6000, warning: 10000, error: 10000 };

  function placeRegion() {
    const host = Array.from(document.querySelectorAll('dialog[open]')).at(-1) || document.body;
    if (region.parentElement !== host) host.append(region);
  }
  function showNext() {
    while (active.size < 3 && queue.length) show(queue.shift());
  }
  function show(item) {
    placeRegion();
    const toast = document.createElement('div');
    toast.className = `toast alert alert-${item.kind}`;
    toast.setAttribute('role', item.kind === 'error' ? 'alert' : 'status');
    toast.setAttribute('aria-atomic', 'true');
    toast.dataset.notificationKind = item.kind;
    const symbol = document.getElementById(item.kind === 'success' ? 'notification-success-icon' : 'notification-info-icon');
    toast.append(symbol.content.cloneNode(true));
    const message = document.createElement('div');
    message.className = 'toast-message';
    message.textContent = item.message;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'button button-icon button-quiet toast-close';
    close.setAttribute('aria-label', region.dataset.dismiss);
    close.append(document.getElementById('notification-close-icon').content.cloneNode(true));
    toast.append(message, close);
    const opener = document.activeElement;
    let remaining = item.duration;
    let started;
    let timer;
    const paused = new Set(document.hidden ? ['hidden'] : []);
    function dismiss() {
      clearTimeout(timer);
      const focused = toast.contains(document.activeElement);
      toast.remove();
      active.delete(entry);
      showNext();
      if (focused) {
        const target = region.querySelector('button') || (opener?.isConnected ? opener : null);
        target?.focus({ preventScroll: true });
      }
    }
    function resume(reason) {
      paused.delete(reason);
      if (paused.size || timer) return;
      started = performance.now();
      timer = setTimeout(dismiss, remaining);
    }
    function pause(reason) {
      if (timer) {
        clearTimeout(timer);
        timer = null;
        remaining = Math.max(0, remaining - (performance.now() - started));
      }
      paused.add(reason);
    }
    const entry = { pause, resume };
    active.add(entry);
    toast.addEventListener('pointerenter', () => pause('pointer'));
    toast.addEventListener('pointerleave', () => resume('pointer'));
    toast.addEventListener('focusin', () => pause('focus'));
    toast.addEventListener('focusout', event => {
      if (!toast.contains(event.relatedTarget)) resume('focus');
    });
    close.addEventListener('click', dismiss);
    region.append(toast);
    resume('initial');
  }
  function notify(message, kind = 'info') {
    if (!message?.trim()) return;
    kind = Object.hasOwn(defaults, kind) ? kind : 'info';
    // Repeated background request failures update the existing notice instead of flooding the screen.
    if (Array.from(region.querySelectorAll('.toast')).some(toast =>
      toast.dataset.notificationKind === kind && toast.querySelector('.toast-message').textContent === message)) return;
    if (queue.some(item => item.kind === kind && item.message === message)) return;
    queue.push({ message, kind, duration: defaults[kind] });
    showNext();
  }
  function collect(root = document) {
    root.querySelectorAll('[data-toast]').forEach(seed => {
      notify(seed.textContent.trim(), seed.dataset.toast);
      seed.remove();
    });
  }
  window.KMM = { ...window.KMM, notify };
  collect();
  document.body.addEventListener('htmx:afterSwap', event => collect(event.target));
  document.addEventListener('visibilitychange', () => {
    active.forEach(entry => document.hidden ? entry.pause('hidden') : entry.resume('hidden'));
  });
  new MutationObserver(placeRegion).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['open'] });
})();
