"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const COLORS = { green: "#4BD398", pool: "#20C8C8", yellow: "#E9E55A", pink: "#FB7082" };
const SEV_LABEL = { critico: "Crítico", importante: "Importante", ajuste: "Ajuste" };
const CAT_LABEL = { logo: "Logo", cores: "Cores", tipografia: "Tipografia", composicao: "Composição", elementos: "Elementos gráficos", linguagem: "Tom de voz" };
const LOADING_MSGS = [
  "Lendo o manual de marca…", "Separando a paleta oficial…", "Medindo as cores da arte…",
  "Conferindo o respiro do logo…", "Checando as fontes…", "Olhando a composição…", "Escrevendo o feedback…",
];

let serverConfig = { mode: "ai", figma: true };
let lastResult = null;

function band(score) {
  if (score >= 90) return { label: "Na mosca!", color: COLORS.green, title: "Essa arte está com a cara da marca." };
  if (score >= 75) return { label: "Quase lá", color: COLORS.pool, title: "Bem alinhada, com alguns ajustes." };
  if (score >= 50) return { label: "Precisa de ajustes", color: COLORS.yellow, title: "Tem desvios que o cliente vai notar." };
  return { label: "Fora da marca", color: COLORS.pink, title: "A arte se afastou bastante do manual." };
}

/* ------------------------------------------------ setup */
// With the Python server (web/app.py) the page uses its API. Without it (GitHub Pages) there is no
// /api, so the free mode runs right here in the browser with engine.js.
let browserMode = false;

function freeBanner(extra = "") {
  const b = $("#setup-warning");
  b.classList.add("info");
  b.innerHTML = "<strong>Modo gratuito.</strong> A comparação mede as cores, o logo (presença, cor e respiro) e as fontes, quando a arte é PDF. Composição e tom de voz só entram no modo com IA." + extra;
  b.hidden = false;
  $("#loading-hint").textContent = "Leva só alguns segundos.";
}

function enterBrowserMode() {
  browserMode = true;
  serverConfig = { mode: "browser", figma: false };
  freeBanner(" <br>Tudo roda no seu navegador: os arquivos não saem do seu computador. Aqui só dá para enviar arquivos, não links.");
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
  if (c.mode === "free") freeBanner();
}).catch(enterBrowserMode);

/* ------------------------------------------------ input cards */
function linkKind(url) {
  const u = url.trim().toLowerCase();
  if (!u) return null;
  if (u.includes("figma.com/")) return { label: "Figma", warn: !serverConfig.figma && "precisa de token do Figma no servidor" };
  if (u.includes("drive.google.com") || u.includes("docs.google.com")) {
    if (u.includes("/folders/")) return { label: "Pasta do Drive", warn: "use o link do arquivo, não da pasta" };
    return { label: "Google Drive" };
  }
  if (/^https?:\/\/\S+\.\S+/.test(u) || /^\S+\.\S+\/\S*/.test(u)) return { label: "Link direto" };
  return { label: "Isso não parece um link", warn: true };
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

  const showFile = () => {
    const f = file.files[0];
    if (!f) return;
    drop.classList.add("has-file");
    const size = f.size > 1e6 ? `${(f.size / 1e6).toFixed(1)} MB` : `${Math.round(f.size / 1e3)} KB`;
    const thumb = f.type.startsWith("image/") ? `<img class="drop-thumb" alt="" src="${URL.createObjectURL(f)}">` : "";
    [...drop.childNodes].forEach((n) => { if (n !== file) n.remove(); });
    drop.insertAdjacentHTML("beforeend", `${thumb}<span class="drop-text"><strong>${esc(f.name)}</strong></span><span class="drop-hint">${size} · clique para trocar</span>`);
  };
  file.addEventListener("change", showFile);
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, () => drop.classList.add("is-over")));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("is-over")));
});

/* ------------------------------------------------ submit */
const form = $("#form");
const errorBox = $("#form-error");
let loadingTimer = null;

function showError(msg) {
  errorBox.textContent = msg;
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
  if (!art) return showError("Falta a arte: cole um link ou escolha um arquivo no passo 1.");
  if (!brand) return showError("Falta o manual de marca: cole um link ou escolha um arquivo no passo 2.");

  if (browserMode) {
    setLoading(true, true);
    try {
      const data = await BrandEngine.check(art.file, brand.file, (msg) => { $("#loading-msg").textContent = msg; });
      setLoading(false);
      render(data);
    } catch (err) {
      console.error(err);
      setLoading(false);
      showError(err.message || "Não foi possível analisar.");
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
    const data = await res.json().catch(() => ({ error: `O servidor respondeu com erro ${res.status}.` }));
    if (!res.ok || data.error) throw new Error(data.error || "Não foi possível analisar.");
    setLoading(false);
    render(data);
  } catch (err) {
    setLoading(false);
    showError(err.message === "Failed to fetch" ? "Não consegui falar com o servidor. Ele está rodando?" : err.message);
  }
});

function setLoading(on, manualMessages = false) {
  form.hidden = on;
  $("#loading").hidden = !on;
  $("#result").hidden = true;
  clearInterval(loadingTimer);
  if (on && manualMessages) {  // the browser engine reports its own steps
    $("#loading-msg").textContent = "Preparando…";
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (on) {
    let i = 0;
    const msg = $("#loading-msg");
    msg.textContent = LOADING_MSGS[0];
    loadingTimer = setInterval(() => {
      i = Math.min(i + 1, LOADING_MSGS.length - 1);
      msg.style.opacity = 0;
      setTimeout(() => { msg.textContent = LOADING_MSGS[i]; msg.style.opacity = 1; }, 250);
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

function findingCard(f) {
  return `<article class="card finding ${esc(f.severity)}">
    <div class="finding-top">
      <span class="sev ${esc(f.severity)}">${esc(SEV_LABEL[f.severity] || f.severity)}</span>
      <h4>${esc(f.title)}</h4>
      <span class="pill">${esc(CAT_LABEL[f.category] || f.category)}</span>
      ${lastResult.art.previews.length > 1 ? `<span class="pill">Imagem ${f.art_index}</span>` : ""}
    </div>
    <div class="fgrid">
      <div><b>O manual diz</b>${esc(f.guideline)}</div>
      <div><b>Na arte</b>${esc(f.observed)}</div>
      <div class="fix"><b>Como ajustar</b>${esc(f.suggestion)}</div>
    </div>
  </article>`;
}

function render(r) {
  lastResult = r;
  const score = r.score ?? 0;
  const b = band(score);

  $("#verdict").textContent = b.label;
  $("#verdict").style.background = b.color;
  $("#score-label").textContent = b.title;
  $("#summary").textContent = r.summary;
  $("#meta-row").innerHTML = [
    r.brand_name && `Marca: ${esc(r.brand_name)}`,
    `Arte: ${esc(r.art.name)}`,
    r.palette.adherence != null && `Paleta medida: ${r.palette.adherence}% nas cores oficiais`,
    r.mode !== "ai" && "Modo gratuito",
  ].filter(Boolean).map((t) => `<span class="meta">${t}</span>`).join("");

  $("#previews").innerHTML = r.art.previews.map((src, i) =>
    `<figure class="preview" style="margin:0"><img src="${src}" alt="Imagem ${i + 1} da arte">${r.art.previews.length > 1 ? `<span>${i + 1}</span>` : ""}</figure>`).join("");

  $("#cats").innerHTML = r.categories.map((c) => {
    const col = c.applicable ? band(c.score).color : "#CFCFCA";
    return `<div class="card cat ${c.applicable ? "" : "na"}">${ring(c.score, col, !c.applicable)}
      <div><h4>${esc(c.label)}</h4><p>${esc(c.applicable ? c.comment : `Não se aplica. ${c.comment}`)}</p></div></div>`;
  }).join("");

  const pal = r.palette;
  $("#palette").innerHTML =
    (pal.brand.length ? `<div class="pal-label"><span>Paleta oficial</span></div><div class="swatches">${pal.brand.map((p) =>
      `<div class="sw"><i style="background:${esc(p.hex)}"></i><small>${esc(p.name)}<br>${esc(p.hex)}</small></div>`).join("")}</div>`
      : `<p class="muted small" style="margin-top:12px">O manual não traz códigos de cor.</p>`) +
    `<div class="pal-label"><span>Cores medidas na arte</span>${pal.adherence != null ? `<span>${pal.adherence}% na paleta</span>` : ""}</div>
     <div class="art-colors">${pal.art.map((c) => `<div class="ac"><i style="background:${esc(c.hex)}"></i><span>${esc(c.hex)}</span>
       <span class="bar"><span style="width:${Math.max(3, c.share * 100)}%;background:${esc(c.hex)}"></span></span>
       ${c.nearest ? `<span class="tag ${c.match ? "ok" : "off"}" title="Diferença ΔE ${c.delta_e}">${c.match ? `✓ ${esc(c.nearest)}` : "fora da paleta"}</span>` : ""}
     </div>`).join("")}</div>`;

  $("#strengths").innerHTML = r.strengths.length
    ? r.strengths.map((s) => `<li>${esc(s)}</li>`).join("")
    : `<li class="none">Nada bateu com o manual nos critérios medidos.</li>`;

  $("#findings-count").textContent = r.findings.length;
  $("#findings").innerHTML = r.findings.length
    ? r.findings.map(findingCard).join("")
    : `<div class="card empty">Nenhum desvio encontrado. Pode mandar para o cliente! 🎉</div>`;
  $("#review").hidden = !r.to_review.length;
  $("#review-list").innerHTML = r.to_review.map(findingCard).join("");

  form.hidden = true;
  $("#result").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });

  // animate
  const donut = $("#donut-value");
  donut.style.stroke = b.color;
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
  const step = (t) => {
    const p = Math.min(1, (t - start) / dur);
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
    `# Brand Check: ${r.score}% na marca (${band(r.score).label})`,
    r.brand_name && `Marca: ${r.brand_name} · Arte: ${r.art.name}`, "", r.summary, "",
    "## Nota por critério",
    ...r.categories.map((c) => `- ${c.label}: ${c.applicable ? `${c.score}%` : "não se aplica"} (${c.comment})`),
    "", "## O que ajustar",
    ...(r.findings.length ? r.findings.map((f) =>
      `- [${SEV_LABEL[f.severity]}] ${f.title}\n  - Manual: ${f.guideline}\n  - Arte: ${f.observed}\n  - Ajuste: ${f.suggestion}`) : ["- Nada a ajustar."]),
    "", "## Pontos fortes", ...r.strengths.map((s) => `- ${s}`),
  ].filter((l) => l !== false && l !== undefined && l !== "");
  const text = lines.join("\n").replace(/\n## /g, "\n\n## ");
  try {
    await navigator.clipboard.writeText(text);
    $("#copy").textContent = "Copiado!";
  } catch {
    $("#copy").textContent = "Não deu para copiar";
  }
  setTimeout(() => { $("#copy").textContent = "Copiar relatório"; }, 2000);
});
