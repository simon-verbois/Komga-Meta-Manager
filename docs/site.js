// Every image link and the full screenshot gallery also work without JavaScript.
const dialog = document.querySelector("#preview");
const previewImage = document.querySelector("#preview-image");
const previewCaption = document.querySelector("#preview-caption");
let opener;
if (typeof dialog?.showModal === "function") {
  document.querySelectorAll("[data-preview]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      opener = link;
      previewImage.src = link.href;
      previewImage.alt = link.querySelector("img").alt;
      previewCaption.textContent = previewImage.alt;
      dialog.showModal();
    });
  });
  dialog.querySelector("button").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => {
    previewImage.removeAttribute("src");
    opener?.focus({ preventScroll: true });
  });
}

const tablist = document.querySelector(".gallery-controls");
const tabs = Array.from(tablist?.querySelectorAll('[role="tab"]') ?? []);
function selectTab(tab) {
  tabs.forEach((item) => {
    const selected = item === tab;
    item.setAttribute("aria-selected", String(selected));
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute("aria-controls")).hidden = !selected;
  });
}
if (tabs.length) {
  document.querySelectorAll("[data-gallery-panel]").forEach((panel) => {
    panel.setAttribute("role", "tabpanel");
    panel.tabIndex = 0;
  });
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      let next;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
      if (event.key === "Home") next = tabs[0];
      if (event.key === "End") next = tabs[tabs.length - 1];
      if (next) {
        event.preventDefault();
        selectTab(next);
        next.focus();
      }
    });
  });
  selectTab(tabs[0]);
  tablist.hidden = false;
}

const copyButton = document.querySelector(".copy-button");
const copyMessages = {
  en: ["Copied. Save it as compose.yml in a new folder.", "Copy is unavailable here. Select the configuration above and copy it manually."],
  fr: ["Copié. Enregistrez le contenu dans compose.yml dans un nouveau dossier.", "La copie est indisponible ici. Sélectionnez la configuration ci-dessus et copiez-la manuellement."],
  nl: ["Gekopieerd. Sla dit op als compose.yml in een nieuwe map.", "Kopiëren is hier niet beschikbaar. Selecteer de configuratie hierboven en kopieer deze handmatig."],
  de: ["Kopiert. Speichere den Inhalt als compose.yml in einem neuen Ordner.", "Kopieren ist hier nicht verfügbar. Markiere die Konfiguration oben und kopiere sie manuell."],
  es: ["Copiado. Guárdalo como compose.yml en una carpeta nueva.", "La copia no está disponible aquí. Selecciona la configuración anterior y cópiala manualmente."],
};
const messages = copyMessages[document.documentElement.lang] ?? copyMessages.en;
if (navigator.clipboard?.writeText && copyButton) {
  copyButton.hidden = false;
  copyButton.addEventListener("click", async () => {
    const status = document.querySelector(".copy-status");
    try {
      await navigator.clipboard.writeText(document.querySelector("#compose-code").textContent);
      status.textContent = messages[0];
    } catch {
      status.textContent = messages[1];
    }
  });
}

const languagePicker = document.querySelector(".language-picker");
languagePicker?.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    languagePicker.open = false;
    languagePicker.querySelector("summary").focus();
  }
});
document.addEventListener("click", (event) => {
  if (languagePicker?.open && !languagePicker.contains(event.target)) languagePicker.open = false;
});
