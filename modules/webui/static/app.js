/* Shared interaction behavior. Metadata processing stays on the server. */
(() => {
  const body = document.body;
  const menu = document.getElementById("menu-toggle");
  const navigation = document.getElementById("sidebar-navigation");
  menu?.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    menu.setAttribute("aria-expanded", String(open));
    navigation.classList.toggle("is-open", open);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu?.getAttribute("aria-expanded") === "true") {
      menu.setAttribute("aria-expanded", "false");
      navigation.classList.remove("is-open");
      menu.focus();
    }
  });
  document.querySelectorAll("[data-secret]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.secret);
      const visible = input.type === "password";
      input.type = visible ? "text" : "password";
      button.textContent = visible ? body.dataset.hide : body.dataset.show;
      button.setAttribute("aria-pressed", String(visible));
    });
  });
  document.querySelectorAll("[data-reveal-select]").forEach((select) => {
    select.addEventListener("change", () => {
      document.getElementById(select.dataset.revealSelect).hidden = select.value !== select.dataset.revealValue;
    });
  });

  // Unsaved changes: show them in the save bar and warn before leaving.
  document.querySelectorAll('[data-numbering-form]').forEach((form) => {
    const list = form.querySelector('.numbering-books');
    const status = form.querySelector('[data-numbering-status]');
    const updatePositions = () => {
      const rows = Array.from(list.querySelectorAll('[data-numbering-book]'));
      rows.forEach((row, index) => {
        const position = row.querySelector('[data-numbering-position]');
        position.textContent = position.dataset.label.replace('{n}', String(index + 1));
        row.querySelector('[data-numbering-move="-1"]').disabled = index === 0;
        row.querySelector('[data-numbering-move="1"]').disabled = index === rows.length - 1;
      });
      return rows;
    };
    list.addEventListener('click', (event) => {
      const button = event.target.closest('[data-numbering-move]');
      if (!button) return;
      const row = button.closest('[data-numbering-book]');
      const up = button.dataset.numberingMove === '-1';
      const neighbor = up ? row.previousElementSibling : row.nextElementSibling;
      if (!neighbor) return;
      const number = row.querySelector('[data-book-number]');
      const otherNumber = neighbor.querySelector('[data-book-number]');
      [number.value, otherNumber.value] = [otherNumber.value, number.value];
      list.insertBefore(up ? row : neighbor, up ? neighbor : row);
      const rows = updatePositions();
      const focusTarget = button.disabled ? row.querySelector('[data-numbering-move]:not(:disabled)') : button;
      (focusTarget || number).focus();
      status.textContent = status.dataset.moved.replace('{title}', () => row.dataset.bookTitle)
        .replace('{n}', String(rows.indexOf(row) + 1));
      form.dispatchEvent(new Event('kmm:reordered'));
    });
    form.querySelector('[data-numbering-fill]')?.addEventListener('click', () => {
      const first = form.querySelector('#numbering-first');
      const fields = Array.from(form.querySelectorAll('[data-book-number]'));
      const start = Number(first.value);
      if (!first.value.trim() || !Number.isInteger(start) || start < 0 || start + fields.length - 1 > 999999) {
        status.textContent = status.dataset.invalid;
        first.focus();
        return;
      }
      fields.forEach((field, index) => { field.value = String(start + index); });
      form.dispatchEvent(new Event('input', { bubbles: true }));
      status.textContent = status.dataset.filled;
    });
    const selectedBook = new URLSearchParams(window.location.search).get('book');
    const selectedRow = Array.from(list.querySelectorAll('[data-numbering-book]'))
      .find((row) => row.dataset.bookId === selectedBook);
    if (selectedRow) {
      // Fragment navigation runs after deferred scripts; focus once it finishes.
      window.addEventListener('load', () => requestAnimationFrame(() => {
        selectedRow.querySelector('[data-book-number]').focus({ preventScroll: true });
        selectedRow.scrollIntoView({ block: 'center' });
      }), { once: true });
    }
  });

  let submitting = false;
  const dirtyForms = new Set();
  document.querySelectorAll("[data-dirty-form]").forEach((form) => {
    const original = JSON.stringify(Array.from(new FormData(form)));
    const bar = form.querySelector(".save-bar");
    const status = form.querySelector("[data-save-status]");
    const originalText = status?.textContent;
    const check = () => {
      const dirty = JSON.stringify(Array.from(new FormData(form))) !== original;
      dirty ? dirtyForms.add(form) : dirtyForms.delete(form);
      bar?.classList.toggle("dirty", dirty);
      if (status) {
        status.textContent = dirty ? body.dataset.unsaved : originalText;
        status.setAttribute("role", "status");
      }
    };
    form.addEventListener("input", check);
    form.addEventListener("change", check);
    form.addEventListener("kmm:reordered", check);
  });
  window.addEventListener("beforeunload", (event) => {
    if (!submitting && dirtyForms.size) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  // Confirmation for actions that change Komga or discard work.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    let message = form.dataset.confirm;
    if (form.id === "publish-form") {
      const selected = document.querySelectorAll("[data-review-select]:checked").length;
      if (selected) message = form.dataset.confirmSelected.replace("{n}", selected);
    }
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }
    if (form.method === "post" && !form.hasAttribute("hx-post")) {
      submitting = true;
      const button = event.submitter || form.querySelector('button[type="submit"]');
      if (button) {
        // Disable after the browser captured the submitter's name and value.
        setTimeout(() => { button.disabled = true; button.setAttribute("aria-busy", "true"); });
        if (form.hasAttribute("data-dirty-form") && !button.name) button.textContent = body.dataset.saving;
      }
    }
  });

  const errorSummary = document.querySelector("[data-form-error]");
  if (errorSummary) {
    errorSummary.focus();
    // A failed field can live inside a disclosure panel.
    document.querySelectorAll("#main-content details").forEach((detail) => { detail.open = true; });
  }

  function localizeTimes() {
    document.querySelectorAll("time[data-local-time]").forEach((time) => {
      const value = time.getAttribute("datetime");
      // SQLite audit timestamps have no offset and are stored in UTC.
      const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + "Z";
      const date = new Date(normalized);
      if (!Number.isNaN(date.getTime())) {
        time.textContent = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
        time.title = date.toISOString();
      }
    });
  }
  const feedback = document.getElementById("request-feedback");
  body.addEventListener("htmx:beforeRequest", () => { feedback.hidden = true; });
  body.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.xhr.status === 401 || /\/login$/.test(event.detail.xhr.responseURL)) {
      event.detail.shouldSwap = false;
      window.location.assign("/login");
    }
  });
  ["htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach((name) => {
    body.addEventListener(name, () => { feedback.hidden = false; });
  });
  body.addEventListener("htmx:afterSwap", (event) => {
    localizeTimes();
    applyBookView();
    if (event.target.id === "exec-log-lines" && document.getElementById("follow-log")?.checked) {
      const viewer = document.getElementById("exec-log-container");
      viewer.scrollTop = viewer.scrollHeight;
    }
  });

  const logFilters = document.querySelectorAll("[data-refresh-log]");
  if (logFilters.length) {
    try {
      const saved = JSON.parse(localStorage.getItem("kmm-log-levels"));
      const allowed = new Set(Array.from(logFilters, (input) => input.value));
      if (Array.isArray(saved) && saved.every((level) => allowed.has(level))) {
        logFilters.forEach((input) => { input.checked = saved.includes(input.value); });
      }
    } catch { /* Filters work even when browser storage is unavailable. */ }
    logFilters.forEach((input) => {
      input.addEventListener("change", () => {
        try {
          localStorage.setItem("kmm-log-levels", JSON.stringify(
            Array.from(logFilters).filter((item) => item.checked).map((item) => item.value),
          ));
        } catch { /* Keep the current selection for this page. */ }
        htmx.trigger(document.getElementById("exec-log-lines"), "load");
      });
    });
  }

  // Review: publish the selected series, or everything when nothing is selected.
  const publishButton = document.querySelector("[data-publish-button]");
  function updatePublishLabel() {
    if (!publishButton) return;
    const selected = document.querySelectorAll("[data-review-select]:checked").length;
    publishButton.querySelector("span").textContent = selected
      ? publishButton.dataset.labelSelected.replace("{n}", selected)
      : publishButton.dataset.labelAll;
  }
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-review-select]")) updatePublishLabel();
  });
  updatePublishLabel();
  document.querySelectorAll("[data-review-expand]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".review-series-details").forEach((details) => {
        details.open = button.dataset.reviewExpand === "true";
      });
    });
  });

  // Library content: search, filter and sort happen in the browser.
  function applyBookView() {
    const grid = document.querySelector("[data-book-grid]");
    if (!grid) return;
    const query = (document.querySelector("[data-book-search]")?.value || "").trim().toLocaleLowerCase();
    const filter = document.querySelector("[data-book-filter]")?.value || "";
    const sort = document.querySelector("[data-book-sort]")?.value || "title";
    const cards = Array.from(grid.children);
    cards.sort((a, b) => {
      if (sort === "books") return Number(b.dataset.books) - Number(a.dataset.books) || a.dataset.sortTitle.localeCompare(b.dataset.sortTitle);
      const order = a.dataset.sortTitle.localeCompare(b.dataset.sortTitle);
      return sort === "title-desc" ? -order : order;
    });
    let visible = 0;
    cards.forEach((card) => {
      card.hidden = !card.dataset.bookTitle.includes(query) || (filter && card.dataset[filter] !== "1");
      if (!card.hidden) visible++;
      grid.append(card);
    });
    const count = document.getElementById("book-count");
    if (count) count.textContent = (visible === 1 ? count.dataset.templateOne : count.dataset.templateMany).replace("{n}", visible);
    document.getElementById("book-no-matches").hidden = visible > 0;
  }
  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-book-search]")) applyBookView();
  });
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-book-filter], [data-book-sort]")) applyBookView();
  });

  // Sources: reorder with buttons; the hidden inputs follow the visible order.
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-move]");
    if (!button) return;
    const row = button.closest(".source-row");
    const list = row.parentElement;
    const sibling = button.dataset.move === "up" ? row.previousElementSibling : row.nextElementSibling;
    if (!sibling) return;
    if (button.dataset.move === "up") list.insertBefore(row, sibling);
    else list.insertBefore(sibling, row);
    Array.from(list.children).forEach((item, index) => { item.querySelector(".source-rank").textContent = index + 1; });
    button.focus();
    row.closest("form")?.dispatchEvent(new Event("kmm:reordered"));
  });

  // Connection: check the address and key before saving.
  document.querySelector("[data-test-connection]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const form = button.closest("form");
    const result = form.querySelector("[data-test-result]");
    const data = new FormData(form);
    result.className = "help";
    result.textContent = button.dataset.testing;
    button.disabled = true;
    try {
      const response = await fetch("/config/komga/libraries", { method: "POST", body: data, redirect: "error" });
      const payload = await response.json();
      if (response.ok) {
        result.className = "help success-text";
        result.textContent = button.dataset.ok.replace("{n}", payload.libraries.length)
          .replace("{names}", payload.libraries.map((lib) => lib.name).join(", "));
      } else {
        result.className = "help error-text";
        result.textContent = response.status === 422 ? button.dataset.invalid : button.dataset.fail;
      }
    } catch {
      result.className = "help error-text";
      result.textContent = button.dataset.fail;
    } finally {
      button.disabled = false;
    }
  });

  localizeTimes();
})();

// Account menu and missing covers.
(() => {
  document.addEventListener("error", (event) => {
    if (event.target.matches?.(".book-cover img, .review-thumb, .cover-compare")) event.target.hidden = true;
  }, true);
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".user-menu")) {
      document.querySelectorAll(".user-menu[open]").forEach((menu) => { menu.open = false; });
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelectorAll(".user-menu[open]").forEach((menu) => {
      menu.open = false;
      menu.querySelector("summary").focus();
    });
  });
})();
