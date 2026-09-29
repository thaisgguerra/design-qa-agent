"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const t = I18N.t;
const msg = I18N.msg;

const COLORS = { green: "#4BD398", pool: "#20C8C8", yellow: "#E9E55A", pink: "#FB7082" };

let serverConfig = { mode: "ai", figma: true };
let lastResult = null;

function band(score) {
  const i = score >= 90 ? 0 : score >= 75 ? 1 : score >= 50 ? 2 : 3;
  const [label, title] = t("band")[i];
  return { label, title, color: [COLORS.green, COLORS.pool, COLORS.yellow, COLORS.pink][i] };
}

/* ------------------------------------------------ language */
["flag-us.svg", "flag-br.svg"].forEach((src) => { new Image().src = src; });  // no flash on the first switch
function applyLanguage() {
  I18N.apply();
  document.title = t("title");
  const btn = $("#lang-btn");
  btn.innerHTML = `<img src="${t("lang_toggle_flag")}" alt="" class="flag">${esc(t("lang_toggle"))}`;
  btn.setAttribute("aria-label", t("lang_toggle_label"));
  renderBanner();
  $$(".drop.has-file").forEach((d) => d.showFile && d.showFile());
  if (lastResult && !$("#result").hidden) render(lastResult, false);
}
$("#lang-btn").addEventListener("click", () => {
  I18N.setLang(I18N.lang === "pt" ? "en" : "pt");
  applyLanguage();
});

/* ------------------------------------------------ setup */
// With the Python server (web/app.py) the page uses its API. Without it (GitHub Pages) there is no
// /api, so the measured check runs right here in the browser with engine.js.
let browserMode = false;
let showBanner = false;

function renderBanner() {
  if (!showBanner) return;
  const b = $("#setup-warning");
  b.classList.add("info");
  b.innerHTML = t("banner_how") + (browserMode ? "<br>" + t("banner_browser") : "");
  b.hidden = false;
  $("#loading-hint").textContent = t("loading_fast");
  $("#loading-hint").removeAttribute("data-i18n");
}

function enterBrowserMode() {
  browserMode = true;
  showBanner = true;
  serverConfig = { mode: "browser", figma: false };
  renderBanner();
  $$(".input-card").forEach((card) => {
    $(".seg", card).hidden = true;
    card.dataset.mode = "file";
    $(".mode-link", card).hidden = true;
    $(".mode-file", card).hidden = false;
  });
  $(".tip").hidden = true;
}

fetch("api/config").then((r) => {
  if (!r.ok) throw new Error("no server");
  return r.json();
}).then((c) => {
  serverConfig = c;
  if (c.mode === "free") { showBanner = true; renderBanner(); }
}).catch(enterBrowserMode);

/* ------------------------------------------------ input cards */
function linkKind(url) {
  const u = url.trim().toLowerCase();
  if (!u) return null;
  if (u.includes("figma.com/")) return { label: "Figma", warn: !serverConfig.figma && t("chip_figma_token") };
  if (u.includes("drive.google.com") || u.includes("docs.google.com")) {
    if (u.includes("/folders/")) return { label: t("chip_folder"), warn: t("chip_folder_warn") };
    return { label: "Google Drive" };
  }
  if (/^https?:\/\/\S+\.\S+/.test(u) || /^\S+\.\S+\/\S*/.test(u)) return { label: t("chip_direct") };
  return { label: t("chip_not_link"), warn: true };
}

$$(".input-card").forEach((card) => {
  const input = $("input[type=url]", card);
  const chips = $(".chip-row", card);
  const drop = $(".drop", card);
  const file = $("input[type=file]", drop);

  $$(".seg-btn", card).forEach((btn) => btn.addEventListener("click", () => {
    $$(".seg-btn", card).forEach((b) => { b.classList.toggle("is-on", b === btn); b.setAttribute("aria-selected", b === btn); });
    card.dataset.mode = btn.dataset.mode;
    $(".mode-link", card).hidden = btn.dataset.mode !== "link";
    $(".mode-file", card).hidden = btn.dataset.mode !== "file";
  }));

  input.addEventListener("input", () => {
    const k = linkKind(input.value);
    chips.innerHTML = k ? `<span class="chip ${k.warn ? "warn" : ""}">${esc(k.label)}${typeof k.warn === "string" ? ` · ${esc(k.warn)}` : ""}</span>` : "";
  });

  drop.showFile = () => {
    const f = file.files[0];
    if (!f) return;
    drop.classList.add("has-file");
    const size = f.size > 1e6 ? `${(f.size / 1e6).toFixed(1)} MB` : `${Math.round(f.size / 1e3)} KB`;
    const thumb = f.type.startsWith("image/") ? `<img class="drop-thumb" alt="" src="${URL.createObjectURL(f)}">` : "";
    [...drop.childNodes].forEach((n) => { if (n !== file) n.remove(); });
    drop.insertAdjacentHTML("beforeend", `${thumb}<span class="drop-text"><strong>${esc(f.name)}</strong></span><span class="drop-hint">${size} · ${esc(t("drop_change"))}</span>`);
  };
  file.addEventListener("change", drop.showFile);
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, () => drop.classList.add("is-over")));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("is-over")));
});

/* ------------------------------------------------ submit */
const form = $("#form");
const errorBox = $("#form-error");
let loadingTimer = null;

function showError(text) {
  errorBox.textContent = text;
  errorBox.hidden = false;
  errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

function slotData(slot) {
  const card = $(`.input-card[data-slot="${slot}"]`);
  const mode = card.dataset.mode || "link";
  if (mode === "file") {
    const f = $("input[type=file]", card).files[0];
    return f ? { file: f } : null;
  }
  const url = $("input[type=url]", card).value.trim();
  return url ? { url } : null;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.hidden = true;
  const art = slotData("art");
  const brand = slotData("brand");
  if (!art) return showError(t("err_no_art"));
  if (!brand) return showError(t("err_no_brand"));

  if (browserMode) {
    setLoading(true, true);
    try {
      const data = await BrandEngine.check(art.file, brand.file, (m) => { $("#loading-msg").textContent = msg(m); });
      setLoading(false);
      render(data);
    } catch (err) {
      console.error(err);
      setLoading(false);
      showError(err.message || t("err_generic"));
    }
    return;
  }

  const fd = new FormData();
  if (art.file) fd.append("art_file", art.file); else fd.append("art_url", art.url);
  if (brand.file) fd.append("brand_file", brand.file); else fd.append("brand_url", brand.url);
  fd.append("notes", form.elements.notes.value);

  setLoading(true);
  try {
    const res = await fetch("api/analyze", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({ error: t("err_status", { status: res.status }) }));
    if (!res.ok || data.error) throw new Error(data.error || t("err_generic"));
    setLoading(false);
    render(data);
  } catch (err) {
    setLoading(false);
    showError(err.message === "Failed to fetch" ? t("err_server") : err.message);
  }
});

function setLoading(on, manualMessages = false) {
  form.hidden = on;
  $("#loading").hidden = !on;
  $("#result").hidden = true;
  clearInterval(loadingTimer);
  if (on && manualMessages) {  // the browser engine reports its own steps
    $("#loading-msg").textContent = t("preparing");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (on) {
    let i = 0;
    const el = $("#loading-msg");
    el.textContent = t("loading_msgs")[0];
    loadingTimer = setInterval(() => {
      i = Math.min(i + 1, t("loading_msgs").length - 1);
      el.style.opacity = 0;
      setTimeout(() => { el.textContent = t("loading_msgs")[i]; el.style.opacity = 1; }, 250);
    }, 5000);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

/* ------------------------------------------------ render */
function ring(score, color, na) {
  return `<div class="ring"><svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" class="t"/>
    <circle cx="32" cy="32" r="28" class="v" data-pct="${na ? 0 : score}" stroke="${color}"/></svg>
    <b>${na ? "–" : score}</b></div>`;
}

const sevLabel = (s) => t("sev")[s] || s;
const catLabel = (c) => t("cat")[c] || c;

function findingCard(f) {
  return `<article class="card finding ${esc(f.severity)}">
    <div class="finding-top">
      <span class="sev ${esc(f.severity)}">${esc(sevLabel(f.severity))}</span>
      <h4>${esc(msg(f.title))}</h4>
      <span class="pill">${esc(catLabel(f.category))}</span>
      ${lastResult.art.previews.length > 1 ? `<span class="pill">${esc(t("image_n", { n: f.art_index }))}</span>` : ""}
    </div>
    <div class="fgrid">
      <div><b>${esc(t("f_manual"))}</b>${esc(msg(f.guideline))}</div>
      <div><b>${esc(t("f_art"))}</b>${esc(msg(f.observed))}</div>
      <div class="fix"><b>${esc(t("f_fix"))}</b>${esc(msg(f.suggestion))}</div>
    </div>
  </article>`;
}

function render(r, animate = true) {
  lastResult = r;
  const score = r.score ?? 0;
  const b = band(score);

  $("#verdict").textContent = b.label;
  $("#verdict").style.background = b.color;
  $("#score-label").textContent = b.title;
  $("#summary").textContent = msg(r.summary);
  $("#meta-row").innerHTML = [
    r.brand_name && t("meta_brand", { v: r.brand_name }),
    t("meta_art", { v: r.art.name }),
    r.palette.adherence != null && t("meta_palette", { v: r.palette.adherence }),
  ].filter(Boolean).map((x) => `<span class="meta">${esc(x)}</span>`).join("");

  $("#previews").innerHTML = r.art.previews.map((src, i) =>
    `<figure class="preview" style="margin:0"><img src="${src}" alt="${esc(t("preview_alt", { n: i + 1 }))}">${r.art.previews.length > 1 ? `<span>${i + 1}</span>` : ""}</figure>`).join("");

  $("#cats").innerHTML = r.categories.map((c) => {
    const col = c.applicable ? band(c.score).color : "#CFCFCA";
    return `<div class="card cat ${c.applicable ? "" : "na"}">${ring(c.score, col, !c.applicable)}
      <div><h4>${esc(catLabel(c.key))}</h4><p>${esc(c.applicable ? msg(c.comment) : `${t("na")} ${msg(c.comment)}`)}</p></div></div>`;
  }).join("");

  const pal = r.palette;
  $("#palette").innerHTML =
    (pal.brand.length ? `<div class="pal-label"><span>${esc(t("pal_official"))}</span></div><div class="swatches">${pal.brand.map((p) =>
      `<div class="sw"><i style="background:${esc(p.hex)}"></i><small>${esc(p.name)}<br>${esc(p.hex)}</small></div>`).join("")}</div>`
      : `<p class="muted small" style="margin-top:12px">${esc(t("pal_no_codes"))}</p>`) +
    `<div class="pal-label"><span>${esc(t("pal_measured"))}</span>${pal.adherence != null ? `<span>${esc(t("pal_in", { v: pal.adherence }))}</span>` : ""}</div>
     <div class="art-colors">${pal.art.map((c) => `<div class="ac"><i style="background:${esc(c.hex)}"></i><span>${esc(c.hex)}</span>
       <span class="bar"><span style="width:${Math.max(3, c.share * 100)}%;background:${esc(c.hex)}"></span></span>
       ${c.nearest ? `<span class="tag ${c.match ? "ok" : "off"}" title="${esc(t("pal_delta", { v: c.delta_e }))}">${c.match ? `✓ ${esc(c.nearest)}` : esc(t("pal_off"))}</span>` : ""}
     </div>`).join("")}</div>`;

  $("#strengths").innerHTML = r.strengths.length
    ? r.strengths.map((s) => `<li>${esc(msg(s))}</li>`).join("")
    : `<li class="none">${esc(t("strengths_none"))}</li>`;

  $("#findings-count").textContent = r.findings.length;
  $("#findings").innerHTML = r.findings.length
    ? r.findings.map(findingCard).join("")
    : `<div class="card empty">${esc(t("findings_none"))}</div>`;
  $("#review").hidden = !r.to_review.length;
  $("#review-list").innerHTML = r.to_review.map(findingCard).join("");

  form.hidden = true;
  $("#result").hidden = false;

  const donut = $("#donut-value");
  donut.style.stroke = b.color;
  if (!animate) {  // language switch: redraw in place, no replay
    donut.style.strokeDasharray = `${(score / 100) * 502.65} 503`;
    $$(".ring .v").forEach((v) => { v.style.strokeDasharray = `${(v.dataset.pct / 100) * 175.9} 176`; });
    $("#score-num").textContent = score;
    return;
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
  donut.style.strokeDasharray = "0 503";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    donut.style.strokeDasharray = `${(score / 100) * 502.65} 503`;
    $$(".ring .v").forEach((v) => { v.style.strokeDasharray = `${(v.dataset.pct / 100) * 175.9} 176`; });
  }));
  countUp($("#score-num"), score);
  if (score >= 90) setTimeout(confetti, 700);
}

function countUp(el, to) {
  const start = performance.now(), dur = 1400;
  const step = (now) => {
    const p = Math.min(1, (now - start) / dur);
    el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ------------------------------------------------ confetti in brand colors */
function confetti() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const c = $("#confetti"), ctx = c.getContext("2d");
  c.width = innerWidth; c.height = innerHeight;
  const cols = ["#4BD398", "#FB7082", "#F8F695", "#20C8C8"];
  const parts = Array.from({ length: 140 }, () => ({
    x: innerWidth / 2 + (Math.random() - .5) * 200, y: innerHeight * .35,
    vx: (Math.random() - .5) * 14, vy: -Math.random() * 14 - 4,
    r: Math.random() * 6 + 4, c: cols[Math.floor(Math.random() * 4)], round: Math.random() > .5,
    a: Math.random() * Math.PI, va: (Math.random() - .5) * .3,
  }));
  let frames = 0;
  (function tick() {
    ctx.clearRect(0, 0, c.width, c.height);
    parts.forEach((p) => {
      p.vy += .35; p.x += p.vx; p.y += p.vy; p.vx *= .99; p.a += p.va;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c;
      if (p.round) { ctx.beginPath(); ctx.arc(0, 0, p.r / 1.6, 0, Math.PI * 2); ctx.fill(); }
      else ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2);
      ctx.restore();
    });
    if (++frames < 160) requestAnimationFrame(tick); else ctx.clearRect(0, 0, c.width, c.height);
  })();
}

/* ------------------------------------------------ actions */
$("#again").addEventListener("click", () => {
  $("#result").hidden = true;
  form.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
});

$("#copy").addEventListener("click", async () => {
  const r = lastResult;
  if (!r) return;
  const lines = [
    t("rep_title", { score: r.score, band: band(r.score).label }),
    r.brand_name && t("rep_meta", { brand: r.brand_name, art: r.art.name }), "", msg(r.summary), "",
    t("rep_cats"),
    ...r.categories.map((c) => `- ${catLabel(c.key)}: ${c.applicable ? `${c.score}%` : t("rep_na")} (${msg(c.comment)})`),
    "", t("rep_fix"),
    ...(r.findings.length ? r.findings.map((f) => t("rep_line", {
      sev: sevLabel(f.severity), title: msg(f.title), g: msg(f.guideline), o: msg(f.observed), s: msg(f.suggestion),
    })) : [t("rep_none")]),
    "", t("rep_strengths"), ...r.strengths.map((s) => `- ${msg(s)}`),
  ].filter((l) => l !== false && l !== undefined && l !== "");
  const text = lines.join("\n").replace(/\n## /g, "\n\n## ");
  const btn = $("#copy");
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = t("copied");
  } catch {
    btn.textContent = t("copy_fail");
  }
  setTimeout(() => { btn.textContent = t("copy"); }, 2000);
});

applyLanguage();
