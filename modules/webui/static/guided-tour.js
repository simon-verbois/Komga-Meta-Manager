/* A read-only introduction; opening the tour never submits forms or starts jobs. */
(() => {
  const dialog = document.getElementById("guided-tour");
  if (!dialog) return;
  const steps = Array.from(dialog.querySelectorAll("[data-tour-step]"));
  const back = dialog.querySelector("[data-tour-back]");
  const next = dialog.querySelector("[data-tour-next]");
  const progress = document.getElementById("tour-progress");
  const welcome = document.querySelector("[data-tour-welcome]");
  const storageKey = "kmm-guided-tour-v1";
  let index = 0;
  let opener;

  function dismissWelcome() {
    if (welcome) welcome.hidden = true;
    try { localStorage.setItem(storageKey, "seen"); } catch { /* The tour also works without storage. */ }
  }

  function showStep() {
    steps.forEach((step, position) => {
      step.hidden = position !== index;
      step.querySelector("h2").id = position === index ? "tour-title" : "";
      step.querySelector(".tour-description").id = position === index ? "tour-description" : "";
    });
    progress.textContent = dialog.dataset.progress.replace("{current}", index + 1).replace("{total}", steps.length);
    dialog.querySelector(".tour-track span").style.width = `${(index + 1) / steps.length * 100}%`;
    back.disabled = index === 0;
    next.textContent = index === steps.length - 1 ? dialog.dataset.finish : dialog.dataset.next;
    steps[index].querySelector("h2").focus({ preventScroll: true });
    dialog.scrollTop = 0;
  }

  document.querySelectorAll("[data-tour-start]").forEach((button) => {
    button.addEventListener("click", () => {
      opener = button;
      index = 0;
      showStep();
      dialog.showModal();
      document.body.classList.add("tour-open");
      steps[index].querySelector("h2").focus({ preventScroll: true });
    });
  });
  back.addEventListener("click", () => { if (index > 0) { index--; showStep(); } });
  next.addEventListener("click", () => {
    if (index === steps.length - 1) dialog.close();
    else { index++; showStep(); }
  });
  dialog.querySelector("[data-tour-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const controls = Array.from(dialog.querySelectorAll("button:not(:disabled), a[href]"))
      .filter((control) => control.getClientRects().length);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || !controls.includes(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener("close", () => {
    document.body.classList.remove("tour-open");
    dismissWelcome();
    // The welcome card may now be hidden; the navigation entry stays available.
    const target = opener?.closest("[data-tour-welcome]")
      ? document.querySelector(".sidebar [data-tour-start]") : opener;
    const menu = document.getElementById("menu-toggle");
    (target?.getClientRects().length ? target : menu)?.focus();
  });
  welcome?.querySelector("[data-tour-dismiss]").addEventListener("click", () => {
    dismissWelcome();
    document.getElementById("main-content").focus();
  });
  try {
    if (welcome) welcome.hidden = localStorage.getItem(storageKey) === "seen";
  } catch {
    if (welcome) welcome.hidden = false;
  }
})();
