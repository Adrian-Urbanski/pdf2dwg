"use strict";

(() => {
  const MAX_PARALLEL = 3;        // tyle plików jednej osoby konwertuje się naraz
  const POLL_MS = 900;
  const BUSY_RETRY_MS = 5000;
  const SETTINGS_KEY = "pdf2dwg-settings";

  const $ = (sel, root = document) => root.querySelector(sel);
  const form = $("#settings");
  const list = $("#files");
  const template = $("#file-template");
  // tryb (DWG albo tylko DXF) serwer wpisuje w klasę <html>; reszta przychodzi z /api/info
  let info = { dwg_available: !document.documentElement.classList.contains("mode-dxf"),
    dwg_versions: ["R2018"], max_upload_mb: 50, max_pages: 100, retention_minutes: 30 };
  let active = 0;
  let nextId = 1;
  const items = [];

  // --- pomocnicze ------------------------------------------------------------------

  const plural = (n, one, few, many) => {
    if (n === 1) return one;
    const d = n % 10, h = n % 100;
    return d >= 2 && d <= 4 && (h < 12 || h > 14) ? few : many;
  };
  const fmtNumber = (n) => n.toLocaleString("pl-PL");
  const fmtSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${fmtNumber(Math.round(bytes / 1024))} KB`;
    return `${(bytes / 1024 / 1024).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} MB`;
  };
  const capitalize = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const isPdf = (file) => file.type === "application/pdf" || /\.pdf$/i.test(file.name);

  // --- ustawienia ------------------------------------------------------------------

  function collectOptions() {
    const data = new FormData(form);
    for (const box of form.querySelectorAll('input[type="checkbox"]')) {
      data.set(box.name, box.checked ? "1" : "0");
    }
    return data;
  }

  function saveSettings() {
    const values = {};
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") values[el.name] = el.checked;
      else if (el.type === "radio") { if (el.checked) values[el.name] = el.value; }
      else values[el.name] = el.value;
    }
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(values)); } catch (_) { /* brak pamięci przeglądarki */ }
  }

  function restoreSettings() {
    let values;
    try { values = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null"); } catch (_) { values = null; }
    if (!values) return;
    for (const el of form.elements) {
      if (!el.name || !(el.name in values)) continue;
      if (el.type === "checkbox") el.checked = Boolean(values[el.name]);
      else if (el.type === "radio") el.checked = el.value === values[el.name] && !el.disabled;
      else if (el.tagName === "SELECT") {
        if ([...el.options].some((o) => o.value === values[el.name])) el.value = values[el.name];
      } else if (el.name !== "pages") el.value = values[el.name];
    }
  }

  function updateFormatUi() {
    const fmt = form.elements.format.value;
    $("#field-dwg-version").hidden = fmt !== "dwg";
  }

  async function loadInfo() {
    try {
      const resp = await fetch("/api/info");
      if (resp.ok) info = await resp.json();
    } catch (_) { /* zostają wartości domyślne */ }

    const select = $("#dwg-version");
    select.textContent = "";
    for (const v of [...info.dwg_versions].reverse()) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = `AutoCAD ${v.slice(1)}${v === "R2018" ? "+" : ""}`;
      select.append(opt);
    }
    if (info.source_url) {
      const link = $("#source-link");
      link.href = info.source_url;
      link.hidden = false;
    }
    if (info.contact) {
      const link = $("#contact-link");
      link.href = info.contact.includes("@") && !info.contact.startsWith("mailto:") ? `mailto:${info.contact}` : info.contact;
      link.hidden = false;
    }
    restoreSettings();
    if (!info.dwg_available) {              // tryb tylko DXF: wybór formatu jest ukryty
      form.querySelector('input[name="format"][value="dwg"]').disabled = true;
      form.querySelector('input[name="format"][value="dxf"]').checked = true;
    }
    updateFormatUi();
  }

  // --- karta pliku -----------------------------------------------------------------

  function render(item) {
    const el = item.el;
    const st = item.state;
    el.dataset.state = st === "done" ? "done" : st === "error" ? "error" : "working";
    $(".status-text", el).textContent = item.statusText;

    const progress = $(".progress", el);
    const bar = $(".progress span", el);
    progress.hidden = !(st === "uploading" || st === "queued" || st === "running");
    progress.classList.toggle("indeterminate", st === "queued" || st === "running");
    bar.style.width = st === "uploading" ? `${item.uploadPct}%` : "";

    const img = $(".thumb img", el);
    if (item.previewUrl && img.getAttribute("src") !== item.previewUrl) {
      img.src = item.previewUrl;
      img.hidden = false;
    }

    const download = $(".download", el);
    const result = item.result;
    if (st === "done" && result && !item.expired) {
      const ext = result.download.name.split(".").pop().toUpperCase();
      download.href = `/api/jobs/${item.jobId}/download`;
      download.textContent = `Pobierz ${ext}`;
      download.title = `${result.download.name} (${fmtSize(result.download.size)})`;
      download.hidden = false;
    } else {
      download.hidden = true;
      download.removeAttribute("href");
    }
    $(".retry", el).hidden = !item.convertible || !(st === "error" || (st === "done" && item.expired));

    const summary = $(".summary", el);
    if (st === "done" && result) {
      const converted = result.pages.filter((p) => !p.skipped);
      const total = converted.reduce((sum, p) => sum + p.total, 0);
      const counts = {};
      for (const p of converted) for (const [k, v] of Object.entries(p.entities)) counts[k] = (counts[k] || 0) + v;
      const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${fmtNumber(v)}`).join(", ");
      summary.textContent = `${converted.length} ${plural(converted.length, "strona", "strony", "stron")} · ` +
        `${fmtNumber(total)} ${plural(total, "obiekt", "obiekty", "obiektów")}` + (top ? ` · ${top}` : "");
      summary.hidden = false;
    } else {
      summary.hidden = true;
    }

    const warnBox = $(".warnings", el);
    const warnings = collectWarnings(result);
    warnBox.hidden = warnings.length === 0;
    if (warnings.length) {
      $("summary", warnBox).textContent = `Uwagi (${warnings.length})`;
      const ul = $("ul", warnBox);
      ul.textContent = "";
      for (const w of warnings) {
        const li = document.createElement("li");
        li.textContent = w;
        ul.append(li);
      }
    }
    updateListHead();
  }

  function collectWarnings(result) {
    if (!result) return [];
    const out = [...(result.warnings || [])];
    const pages = result.pages || [];
    for (const p of pages) {
      for (const w of p.warnings) out.push(pages.length > 1 ? `strona ${p.number}: ${w}` : w);
    }
    return out.map(capitalize);
  }

  function setState(item, state, text) {
    item.state = state;
    item.statusText = text;
    render(item);
  }

  function updateListHead() {
    const visible = items.length > 0;
    $("#list-head").hidden = !visible;
    const done = items.filter((i) => i.state === "done" && !i.expired);
    $("#download-all").hidden = done.length < 2;
  }

  // --- przesyłanie i odpytywanie ----------------------------------------------------

  function addFiles(fileList) {
    const maxBytes = info.max_upload_mb * 1024 * 1024;
    for (const file of fileList) {
      const el = template.content.firstElementChild.cloneNode(true);
      const item = { id: nextId++, file, el, state: "waiting", statusText: "", uploadPct: 0, jobId: null,
        result: null, previewUrl: null, expired: false, xhr: null, timer: null, expireTimer: null };
      $(".file-name", el).textContent = file.name;
      $(".file-name", el).title = file.name;
      $(".file-size", el).textContent = fmtSize(file.size);
      $(".remove", el).addEventListener("click", () => removeItem(item));
      $(".retry", el).addEventListener("click", () => requeue(item));
      item.convertible = isPdf(file) && file.size <= maxBytes;
      items.push(item);
      list.prepend(el);
      if (!isPdf(file)) setState(item, "error", "To nie jest plik PDF");
      else if (file.size > maxBytes) setState(item, "error", `Plik jest za duży (limit ${info.max_upload_mb} MB)`);
      else setState(item, "waiting", "Czeka na swoją kolej…");
    }
    pump();
  }

  function pump() {
    while (active < MAX_PARALLEL) {
      const next = items.find((i) => i.state === "waiting");
      if (!next) break;
      active++;
      start(next).finally(() => { active--; pump(); });
    }
  }

  function upload(item, data) {
    return new Promise((resolve) => {
      const xhr = new XMLHttpRequest();
      item.xhr = xhr;
      xhr.open("POST", "/api/jobs");
      xhr.responseType = "json";
      xhr.upload.addEventListener("progress", (e) => {
        if (!e.lengthComputable) return;
        item.uploadPct = Math.round((e.loaded / e.total) * 100);
        setState(item, "uploading", `Wysyłanie… ${item.uploadPct} %`);
      });
      xhr.addEventListener("load", () => resolve({ status: xhr.status, body: xhr.response || {} }));
      xhr.addEventListener("error", () => resolve({ status: 0, body: {} }));
      xhr.addEventListener("abort", () => resolve({ status: -1, body: {} }));
      xhr.send(data);
    });
  }

  async function start(item) {
    const data = collectOptions();
    data.append("file", item.file, item.file.name);
    item.uploadPct = 0;
    setState(item, "uploading", "Wysyłanie…");
    const { status, body } = await upload(item, data);
    item.xhr = null;
    if (!items.includes(item)) return;              // usunięty w trakcie
    if (status === 202) {
      item.jobId = body.id;
      setState(item, "queued", "W kolejce…");
      await poll(item);
      return;
    }
    if (status === 429 || status === 503) {
      setState(item, "error", `${capitalize(body.error || "serwer jest zajęty")} — ponowię za chwilę`);
      item.timer = setTimeout(() => { if (items.includes(item)) { setState(item, "waiting", "Czeka na swoją kolej…"); pump(); } },
        BUSY_RETRY_MS);
      return;
    }
    const message = status === 0 ? "Brak połączenia z serwerem" : capitalize(body.error || `Błąd serwera (${status})`);
    setState(item, "error", message);
  }

  async function poll(item) {
    while (items.includes(item)) {
      let job;
      try {
        const resp = await fetch(`/api/jobs/${item.jobId}`, { cache: "no-store" });
        if (resp.status === 404) { setState(item, "error", "Zadanie wygasło — konwertuj ponownie"); return; }
        job = await resp.json();
      } catch (_) {
        await sleep(POLL_MS * 3);
        continue;
      }
      if (job.preview && !item.previewUrl) item.previewUrl = `/api/jobs/${item.jobId}/preview.png`;
      if (job.status === "done") {
        item.result = job.result;
        item.expired = false;
        setState(item, "done", job.result.download.name.toLowerCase().endsWith(".zip")
          ? `Gotowe — ${job.result.files.length} pliki w archiwum ZIP` : "Gotowe");
        scheduleExpiry(item, job.expires_in);
        return;
      }
      if (job.status === "error") {
        item.result = job.result;
        setState(item, "error", capitalize(job.error));
        return;
      }
      if (job.status === "queued") {
        setState(item, "queued", job.position > 1 ? `W kolejce — pozycja ${job.position}` : "W kolejce…");
      } else {
        setState(item, "running", "Konwersja…");
      }
      await sleep(POLL_MS);
    }
  }

  function scheduleExpiry(item, seconds) {
    clearTimeout(item.expireTimer);
    if (seconds == null) return;
    item.expireTimer = setTimeout(() => {
      item.expired = true;
      setState(item, "done", "Plik wygasł i został usunięty z serwera");
    }, Math.max(0, seconds - 5) * 1000);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function forgetJob(item) {
    if (item.jobId) fetch(`/api/jobs/${item.jobId}`, { method: "DELETE" }).catch(() => {});
    item.jobId = null;
  }

  function removeItem(item) {
    const idx = items.indexOf(item);
    if (idx >= 0) items.splice(idx, 1);
    if (item.xhr) item.xhr.abort();
    clearTimeout(item.timer);
    clearTimeout(item.expireTimer);
    forgetJob(item);
    item.el.remove();
    updateListHead();
  }

  function requeue(item) {
    if (!item.convertible) return;
    if (["uploading", "queued", "running", "waiting"].includes(item.state)) return;
    clearTimeout(item.timer);
    clearTimeout(item.expireTimer);
    forgetJob(item);
    item.result = null;
    item.expired = false;
    setState(item, "waiting", "Czeka na swoją kolej…");
    pump();
  }

  function downloadAll() {
    const done = items.filter((i) => i.state === "done" && !i.expired);
    done.forEach((item, n) => {
      setTimeout(() => {
        const a = document.createElement("a");
        a.href = `/api/jobs/${item.jobId}/download`;
        a.download = "";
        document.body.append(a);
        a.click();
        a.remove();
      }, n * 600);
    });
  }

  // --- zdarzenia -------------------------------------------------------------------

  const dropzone = $("#dropzone");
  const input = $("#file-input");
  input.addEventListener("change", () => {
    if (input.files.length) addFiles([...input.files]);
    input.value = "";
  });

  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => {
    if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
    dragDepth++;
    dropzone.classList.add("dragover");
  });
  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropzone.classList.remove("dragover");
  });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    dropzone.classList.remove("dragover");
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) {
      addFiles(files);
      $("#list-head").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });

  form.addEventListener("change", () => { updateFormatUi(); saveSettings(); });
  form.addEventListener("submit", (e) => e.preventDefault());
  $("#reconvert-all").addEventListener("click", () => items.forEach(requeue));
  $("#download-all").addEventListener("click", downloadAll);

  // ostrzeżenie przed zamknięciem karty w trakcie konwersji
  window.addEventListener("beforeunload", (e) => {
    if (items.some((i) => ["uploading", "queued", "running"].includes(i.state))) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  loadInfo();
})();
