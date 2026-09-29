/* Brand Check free mode, running entirely in the browser (used on GitHub Pages, where there is no server).
   A port of designqa/brand_free.py: same rules, same thresholds, same result shape, so render() in app.js
   shows both the same way. Files never leave the user's computer.

   Libraries are loaded on first use: pdf.js (reads the manual) and OpenCV.js (finds the logo). */
"use strict";

const BrandEngine = (() => {
  const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/";
  const OPENCV = "https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js";

  const CATEGORIES = [
    ["logo", "Logo", 0.25], ["cores", "Cores", 0.25], ["tipografia", "Tipografia", 0.20],
    ["composicao", "Composição e respiro", 0.15], ["elementos", "Elementos gráficos", 0.10], ["linguagem", "Tom de voz", 0.05],
  ];
  const SEVERITIES = ["critico", "importante", "ajuste"];
  const MATCH_DELTA_E = 12, MIN_SHARE_FINDING = 0.05;
  const LOGO_MIN_SCORE = 0.40, LOGO_MIN_SEPARATION = 0.5;
  const MAX_ART_PAGES = 6, MAX_EDGE = 1568;
  const HEADERS = new Set(["cores", "cor", "paleta", "paleta de cores", "cores da marca", "colors", "colours", "color", "palette"]);
  const CLEAR = [[/um\s+ter[çc]o|1\s*\/\s*3|one\s+third/i, 1 / 3], [/metade|1\s*\/\s*2|half/i, 1 / 2],
    [/um\s+quarto|1\s*\/\s*4|one\s+quarter/i, 1 / 4], [/dobro|2x/i, 2]];
  const CLEAR_CTX = /clear\s*space|clearspace|espa[çc]o\s+livre|[áa]rea\s+(de\s+)?prote[çc][ãa]o|[áa]rea\s+livre/i;
  const GENERIC_FONTS = new Set(["arial", "helvetica", "times", "timesnewroman", "courier", "symbol", "zapfdingbats", "calibri"]);

  /* ------------------------------------------------ loading */
  const loaded = {};
  function loadScript(src) {
    return loaded[src] ||= new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = src; s.async = true; s.onload = ok;
      s.onerror = () => fail(new Error("Não consegui carregar uma biblioteca da internet. Confira a conexão."));
      document.head.appendChild(s);
    });
  }
  async function pdfjs() {
    await loadScript(PDFJS + "pdf.min.js");
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.js";
    return window.pdfjsLib;
  }
  // The OpenCV.js module object has its own .then(), so it is never returned from a promise directly:
  // a promise resolving to it would keep "unwrapping" it forever and freeze the page. It travels in a box.
  let cvReady = null;
  function opencvBox() {
    return cvReady ||= loadScript(OPENCV).then(() => new Promise((ok) => {
      const c = window.cv;
      if (c.Mat) return ok({ cv: c });
      const prev = c.onRuntimeInitialized;
      c.onRuntimeInitialized = () => { if (prev) prev(); ok({ cv: c }); };
    }));
  }

  /* ------------------------------------------------ canvas helpers */
  const canvas = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
  function fit(src, maxEdge, white = true, upscale = false) {
    const w0 = src.width, h0 = src.height;
    const f = upscale ? maxEdge / Math.max(w0, h0) : Math.min(1, maxEdge / Math.max(w0, h0));
    const c = canvas(Math.max(1, Math.round(w0 * f)), Math.max(1, Math.round(h0 * f)));
    const ctx = c.getContext("2d", { willReadFrequently: true });
    if (white) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height); }
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(src, 0, 0, c.width, c.height);
    return c;
  }
  const pixels = (c) => c.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, c.width, c.height).data;

  async function fileToImage(file) {
    try { return await createImageBitmap(file); } catch {
      return await new Promise((ok, fail) => {
        const img = new Image();
        img.onload = () => ok(img);
        img.onerror = () => fail(new Error(`“${file.name}” não é uma imagem nem um PDF. Use PNG, JPG, WEBP ou PDF.`));
        img.src = URL.createObjectURL(file);
      });
    }
  }

  /* ------------------------------------------------ sources */
  async function load(file) {
    if (file.size > 30 * 1024 * 1024) throw new Error(`O arquivo “${file.name}” passa de 30 MB. Exporte uma versão mais leve.`);
    const buf = await file.arrayBuffer();
    const head = new TextDecoder().decode(new Uint8Array(buf.slice(0, 5)));
    if (head === "%PDF-") {
      const lib = await pdfjs();
      try {
        const doc = await lib.getDocument({ data: new Uint8Array(buf) }).promise;
        return { name: file.name, pdf: doc };
      } catch { throw new Error(`Não consegui abrir o PDF “${file.name}”.`); }
    }
    return { name: file.name, images: [await fileToImage(file)] };
  }

  async function asImages(src, maxPages, maxEdge = MAX_EDGE) {
    if (src.images) return src.images.slice(0, maxPages).map((i) => fit(i, maxEdge));
    const out = [];
    for (let n = 1; n <= Math.min(maxPages, src.pdf.numPages); n++) {
      const page = await src.pdf.getPage(n);
      const vp0 = page.getViewport({ scale: 1 });
      const vp = page.getViewport({ scale: maxEdge / Math.max(vp0.width, vp0.height) });
      const c = canvas(Math.round(vp.width), Math.round(vp.height));
      const ctx = c.getContext("2d", { willReadFrequently: true });
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
      await page.render({ canvasContext: ctx, viewport: vp }).promise;
      out.push(c);
    }
    return out;
  }

  /* ------------------------------------------------ color science */
  const hex = (r, g, b) => "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("").toUpperCase();
  const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.replace("#", "").padStart(6, "0").slice(i - 1, i + 1), 16));
  function lab([r, g, b]) {
    const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    [r, g, b] = [lin(r), lin(g), lin(b)];
    const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, y = 0.2126 * r + 0.7152 * g + 0.0722 * b,
      z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
  }
  const deltaE = (a, b) => { const p = lab(a), q = lab(b); return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]); };

  function medianCut(data, n) {
    const px = [];
    for (let i = 0; i < data.length; i += 4) px.push([data[i], data[i + 1], data[i + 2]]);
    let boxes = [px];
    while (boxes.length < n) {
      let best = -1, bestRange = -1, ch = 0;
      boxes.forEach((b, i) => {
        if (b.length < 2) return;
        for (let c = 0; c < 3; c++) {
          let lo = 255, hi = 0;
          for (const p of b) { if (p[c] < lo) lo = p[c]; if (p[c] > hi) hi = p[c]; }
          if (hi - lo > bestRange) { bestRange = hi - lo; best = i; ch = c; }
        }
      });
      if (best < 0 || bestRange === 0) break;
      const b = boxes[best].sort((p, q) => p[ch] - q[ch]);
      const mid = b.length >> 1;
      boxes.splice(best, 1, b.slice(0, mid), b.slice(mid));
    }
    return boxes.filter((b) => b.length).map((b) => {
      const s = [0, 0, 0];
      for (const p of b) { s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; }
      return { rgb: s.map((v) => Math.round(v / b.length)), count: b.length };
    });
  }

  function dominantColors(images, n = 8) {
    const all = [];
    for (const img of images) all.push(...medianCut(pixels(fit(img, 240)), n));
    all.sort((a, b) => b.count - a.count);
    const merged = [];
    for (const c of all) {
      const m = merged.find((x) => deltaE(x.rgb, c.rgb) < 6);
      if (m) m.count += c.count; else merged.push({ ...c });
    }
    const total = merged.reduce((s, c) => s + c.count, 0) || 1;
    return merged.slice(0, n).filter((c) => c.count / total >= 0.01)
      .map((c) => ({ hex: hex(...c.rgb), share: Math.round((c.count / total) * 1000) / 1000 }));
  }

  function paletteCheck(artColors, palette) {
    const valid = palette.filter((p) => /^#?[0-9A-Fa-f]{6}$/.test(p.hex)).map((p) => ({ name: p.name, hex: "#" + p.hex.replace("#", "").toUpperCase() }));
    if (!valid.length) return { brand: [], art: artColors, adherence: null };
    let matched = 0;
    const art = artColors.map((c) => {
      let near = valid[0], de = Infinity;
      for (const p of valid) { const d = deltaE(rgb(c.hex), rgb(p.hex)); if (d < de) { de = d; near = p; } }
      const ok = de <= MATCH_DELTA_E;
      if (ok) matched += c.share;
      return { ...c, nearest: near.name, nearest_hex: near.hex, delta_e: Math.round(de * 10) / 10, match: ok };
    });
    return { brand: valid, art, adherence: Math.round(100 * matched) };
  }

  /* ------------------------------------------------ read the manual */
  function colorName(segment) {
    for (const raw of segment.split("\n")) {
      const line = raw.trim();
      if (line.length >= 3 && line.length <= 30 && !/\d|#|:|%/.test(line) && !HEADERS.has(line.toLowerCase()) && !/[.,]$/.test(line)) return line;
    }
    return "";
  }

  function paletteFromText(text) {
    let matches = [...text.matchAll(/#([0-9A-Fa-f]{6})\b/g)].map((m) => ["#" + m[1].toUpperCase(), m]);
    if (!matches.length) {
      matches = [...text.matchAll(/R\s*[:=]?\s*(\d{1,3})\s*[,;/\n ]+\s*G\s*[:=]?\s*(\d{1,3})\s*[,;/\n ]+\s*B\s*[:=]?\s*(\d{1,3})/g)]
        .filter((m) => Math.max(+m[1], +m[2], +m[3]) <= 255).map((m) => [hex(+m[1], +m[2], +m[3]), m]);
    }
    const found = new Map();
    let prevEnd = 0;
    for (const [h, m] of matches) {
      const start = Math.max(prevEnd, text.lastIndexOf("\f", m.index) + 1, m.index - 600);
      if (!found.has(h)) found.set(h, colorName(text.slice(start, m.index)));
      prevEnd = m.index + m[0].length;
    }
    return [...found].map(([h, n]) => ({ name: n || h, hex: h }));
  }

  const fontFamily = (name) => name.split("+").pop().split(/[-,]/)[0].replace(/(MT|PS|Std|Pro)$/, "").replace(/([a-z])([A-Z])/g, "$1 $2").trim();

  async function readPdf(doc, { wantLogo = true } = {}) {
    const lib = window.pdfjsLib;
    const texts = [], fonts = new Map(), imgs = new Map();
    for (let n = 1; n <= doc.numPages; n++) {
      const page = await doc.getPage(n);
      const tc = await page.getTextContent();
      texts.push(tc.items.map((it) => it.str + (it.hasEOL ? "\n" : "")).join(""));
      const ops = n <= 12 || !wantLogo ? await page.getOperatorList() : null;
      if (!ops) continue;
      for (const it of tc.items) {  // real font names are only known after the operator list loaded them
        let f = null;
        try { f = page.commonObjs.get(it.fontName); } catch { /* not loaded */ }
        if (f && f.name && !/^Type3/.test(f.name)) fonts.set(fontFamily(f.name), (fonts.get(fontFamily(f.name)) || 0) + it.str.trim().length);
      }
      if (!wantLogo) continue;
      for (let i = 0; i < ops.fnArray.length; i++) {
        if (ops.fnArray[i] !== lib.OPS.paintImageXObject) continue;
        const id = ops.argsArray[i][0];
        const obj = await new Promise((ok) => { try { page.objs.get(id, ok); } catch { ok(null); } });
        if (!obj || obj.width * obj.height <= 40000) continue;
        const key = `${obj.width}x${obj.height}`;
        const e = imgs.get(key) || { count: 0, obj };
        e.count++; imgs.set(key, e);
      }
    }
    const total = [...fonts.values()].reduce((a, b) => a + b, 0) || 1;
    const fontList = [...fonts].sort((a, b) => b[1] - a[1]).filter(([f, c]) => f && c / total > 0.05).slice(0, 4).map(([f]) => f);

    let logo = null;
    const ranked = [...imgs.values()].sort((a, b) => b.count - a.count || b.obj.width * b.obj.height - a.obj.width * a.obj.height);
    for (const { obj } of ranked) {
      const c = imageObjToCanvas(obj);
      if (c && hasTransparency(c)) { logo = trimAlpha(c); break; }
    }
    return { text: texts.join("\f"), fonts: fontList, logo };
  }

  function imageObjToCanvas(obj) {
    const c = canvas(obj.width, obj.height), ctx = c.getContext("2d", { willReadFrequently: true });
    if (obj.bitmap) { ctx.drawImage(obj.bitmap, 0, 0); return c; }
    if (!obj.data) return null;
    const id = ctx.createImageData(obj.width, obj.height), d = obj.data;
    if (d.length === obj.width * obj.height * 4) id.data.set(d);
    else if (d.length === obj.width * obj.height * 3) {
      for (let i = 0, j = 0; i < d.length; i += 3, j += 4) { id.data[j] = d[i]; id.data[j + 1] = d[i + 1]; id.data[j + 2] = d[i + 2]; id.data[j + 3] = 255; }
    } else return null;
    ctx.putImageData(id, 0, 0);
    return c;
  }
  function hasTransparency(c) {
    const d = pixels(fit(c, 200, false));
    let t = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] < 40) t++;
    return t > d.length / 4 * 0.05;
  }
  function trimAlpha(c) {
    const d = pixels(c);
    let x0 = c.width, y0 = c.height, x1 = -1, y1 = -1;
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
      if (d[(y * c.width + x) * 4 + 3] > 40) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return null;
    const out = canvas(x1 - x0 + 1, y1 - y0 + 1);
    out.getContext("2d").drawImage(c, -x0, -y0);
    return out;
  }

  async function readManual(src) {
    const prof = { name: src.name.replace(/\.(pdf|png|jpe?g|webp|avif)$/i, ""), palette: [], paletteSource: "", fonts: [], logo: null, clearspace: null, notes: [] };
    if (src.pdf) {
      const { text, fonts, logo } = await readPdf(src.pdf);
      prof.palette = paletteFromText(text);
      prof.fonts = fonts;
      prof.logo = logo;
      const re = new RegExp(CLEAR_CTX.source, "gi");
      let m;
      while ((m = re.exec(text))) {
        const win = text.slice(m.index, m.index + 500);
        const hit = CLEAR.find(([rx]) => rx.test(win));
        if (hit) { prof.clearspace = hit[1]; break; }
      }
    }
    if (prof.palette.length) prof.paletteSource = "manual";
    else {
      const pages = await asImages(src, 20, 800);
      prof.palette = dominantColors(pages, 10).filter((c) => c.share > 0.02).map((c) => ({ name: "Cor do manual", hex: c.hex }));
      prof.paletteSource = "estimada";
      prof.notes.push("O manual não traz códigos de cor escritos; a paleta foi estimada pelas cores das páginas.");
    }
    return prof;
  }

  /* ------------------------------------------------ find the logo (OpenCV) */
  function edges(cv, mat) {
    const chans = new cv.MatVector();
    const acc = new cv.Mat();
    if (mat.channels() === 1) chans.push_back(mat); else cv.split(mat, chans);
    const n = Math.min(3, chans.size());
    for (let i = 0; i < n; i++) {
      const e = new cv.Mat();
      cv.Canny(chans.get(i), e, 60, 160);
      if (i === 0) e.copyTo(acc); else cv.max(acc, e, acc);
      e.delete();
    }
    chans.delete();
    const f = new cv.Mat();
    acc.convertTo(f, cv.CV_32F);
    cv.GaussianBlur(f, f, new cv.Size(5, 5), 0);
    acc.delete();
    return f;
  }

  function maskMat(cv, logo, w, h) {
    const c = canvas(w, h);
    c.getContext("2d").drawImage(logo, 0, 0, w, h);
    const d = pixels(c), m = new cv.Mat(h, w, cv.CV_8UC1);
    for (let i = 0; i < w * h; i++) m.data[i] = d[i * 4 + 3] > 128 ? 255 : 0;
    return m;
  }

  function findLogo(cv, art, logo) {
    const work = fit(art, 1000, true, true);  // same working size for every art
    const f = work.width / art.width;
    const src = cv.imread(work);
    const artE = edges(cv, src);
    src.delete();
    const alpha = maskMat(cv, logo, logo.width, logo.height);
    let best = null;
    const W = work.width, H = work.height;
    for (let k = 0; k < 26; k++) {
      const frac = 0.06 * (0.8 / 0.06) ** (k / 25);
      const tw = Math.floor(W * frac), th = Math.floor((tw * logo.height) / logo.width);
      if (tw < 24 || th < 16 || tw >= W || th >= H) continue;
      const small = new cv.Mat();
      cv.resize(alpha, small, new cv.Size(tw, th), 0, 0, cv.INTER_AREA);
      const tpl = edges(cv, small);
      small.delete();
      const mean = new cv.Mat(), std = new cv.Mat();
      cv.meanStdDev(tpl, mean, std);
      const flat = std.doubleAt(0, 0) < 1e-3;
      mean.delete(); std.delete();
      if (!flat) {
        const res = new cv.Mat();
        cv.matchTemplate(artE, tpl, res, cv.TM_CCOEFF_NORMED);
        const mm = cv.minMaxLoc(res);
        if (!best || mm.maxVal > best.score) best = { score: mm.maxVal, box: [mm.maxLoc.x, mm.maxLoc.y, tw, th] };
        res.delete();
      }
      tpl.delete();
    }
    artE.delete(); alpha.delete();
    if (!best || best.score < LOGO_MIN_SCORE) return null;

    const [x, y, w, h] = best.box.map((v) => Math.round(v / f));
    // verify on a fixed-size crop: a real logo is one color standing out from its background
    const sw = 240, sh = Math.max(20, Math.round((240 * h) / Math.max(1, w)));
    const crop = canvas(sw, sh);
    crop.getContext("2d").drawImage(art, x, y, w, h, 0, 0, sw, sh);
    const px = pixels(crop);
    const m = maskMat(cv, logo, sw, sh), inside = new cv.Mat(), dil = new cv.Mat();
    const k3 = cv.Mat.ones(3, 3, cv.CV_8U);
    cv.erode(m, inside, k3, new cv.Point(-1, -1), 2);
    cv.dilate(m, dil, k3, new cv.Point(-1, -1), 3);
    const ins = [[], [], []], out = [[], [], []];
    for (let i = 0; i < sw * sh; i++) {
      const bucket = inside.data[i] ? ins : !dil.data[i] ? out : null;
      if (bucket) for (let c = 0; c < 3; c++) bucket[c].push(px[i * 4 + c]);
    }
    [m, inside, dil, k3].forEach((o) => o.delete());
    if (ins[0].length < 20 || out[0].length < 20) return null;
    const stats = (a) => { const mu = a.reduce((s, v) => s + v, 0) / a.length; return [mu, Math.sqrt(a.reduce((s, v) => s + (v - mu) ** 2, 0) / a.length)]; };
    let sep = 0;
    for (let c = 0; c < 3; c++) {
      const [mi, si] = stats(ins[c]), [mo, so] = stats(out[c]);
      sep = Math.max(sep, Math.abs(mi - mo) / (si + so + 1));
    }
    if (sep < LOGO_MIN_SEPARATION) return null;
    const median = (a) => { const s = [...a].sort((p, q) => p - q); return s[s.length >> 1]; };
    return { score: Math.round(best.score * 100) / 100, separation: Math.round(sep * 100) / 100, box: [x, y, w, h],
      color: hex(median(ins[0]), median(ins[1]), median(ins[2])) };
  }

  /* ------------------------------------------------ the check */
  const finding = (title, category, severity, guideline, observed, suggestion, art_index = 1, confidence = 0.9) =>
    ({ title, category, severity, guideline, observed, suggestion, art_index, confidence });
  const frac = (v) => ({ [1 / 3]: "1/3", [1 / 2]: "1/2", [1 / 4]: "1/4", 2: "2x" })[v] || v.toFixed(2);

  function overall(categories) {
    const used = categories.filter((c) => c.applicable);
    const tw = used.reduce((s, c) => s + c.weight, 0);
    return tw ? Math.round(used.reduce((s, c) => s + c.weight * c.score, 0) / tw) : null;
  }

  async function check(artFile, brandFile, progress = () => {}) {
    const t0 = performance.now();
    progress("Lendo o manual de marca…");
    const [art, brand] = [await load(artFile), await load(brandFile)];
    const prof = await readManual(brand);
    progress("Medindo as cores da arte…");
    const artImgs = await asImages(art, MAX_ART_PAGES);
    if (!artImgs.length) throw new Error("A arte não tem nenhuma página.");
    const cats = Object.fromEntries(CATEGORIES.map(([k]) => [k, { applicable: false, score: 0, comment: "" }]));
    const findings = [], review = [], strengths = [];

    // ---- colors
    const colors = dominantColors(artImgs);
    const pal = paletteCheck(colors, prof.palette);
    if (pal.adherence != null) {
      cats.cores = { applicable: true, score: pal.adherence,
        comment: `${pal.adherence}% da área da arte usa cores da paleta` + (prof.paletteSource === "estimada" ? " (paleta estimada)." : " oficial.") };
      const off = pal.art.filter((c) => !c.match && c.share >= MIN_SHARE_FINDING);
      if (off.length) {
        const total = off.reduce((s, c) => s + c.share, 0);
        findings.push(finding(`${off.length} cor(es) fora da paleta (${Math.round(total * 100)}% da arte)`, "cores",
          total >= 0.2 ? "importante" : "ajuste",
          "Paleta oficial: " + pal.brand.map((p) => `${p.name} ${p.hex}`).join(", ") + ".",
          off.map((c) => `${c.hex} (${Math.round(c.share * 100)}%, mais perto de ${c.nearest})`).join("; ") + ".",
          "Troque essas cores pela cor oficial mais próxima. Se forem sombras de foto ou render, pode ignorar.",
          1, prof.paletteSource === "manual" ? 0.9 : 0.5));
      }
      if (pal.adherence >= 85) strengths.push("As cores da arte estão dentro da paleta da marca.");
      const used = new Map();  // every official color the art uses, with its share of the area
      for (const c of pal.art) if (c.match) { const k = `${c.nearest} ${c.nearest_hex}`; used.set(k, (used.get(k) || 0) + c.share); }
      for (const [k, v] of [...used].sort((a, b) => b[1] - a[1])) strengths.push(`Usa a cor oficial ${k} (${Math.round(v * 100)}% da arte).`);
    }

    // ---- logo
    if (prof.logo) {
      progress("Procurando o logo na arte…");
      const { cv } = await opencvBox();
      const hits = artImgs.map((img, i) => [i + 1, findLogo(cv, img, prof.logo)]).filter(([, h]) => h);
      if (!hits.length) {
        review.push(finding("Não encontrei o logo na arte", "logo", "ajuste",
          "O logo do manual foi procurado em todas as imagens da arte.", "Nenhuma área parecida com o logo.",
          "Se a peça deveria ter logo, confira se ele está lá e sem distorção. Logos muito pequenos, inclinados ou em versão diferente podem não ser reconhecidos.",
          1, 0.4));
      } else {
        let score = 100;
        const comments = [];
        const matched = ["Logo da marca presente na arte" + (hits.length > 1 ? ` (${hits.length} imagens).` : ".")];
        for (const [i, h] of hits) {
          const img = artImgs[i - 1];
          const [x, y, w, hh] = h.box;
          if (prof.clearspace) {
            const need = prof.clearspace * w, gap = Math.min(x, y, img.width - (x + w), img.height - (y + hh));
            if (gap < need * 0.9) {
              score -= 30;
              findings.push(finding("Logo sem a área de proteção", "logo", "critico",
                `O manual pede um respiro de ${frac(prof.clearspace)} da largura do logo em volta dele.`,
                `O logo está a ${Math.max(0, gap)}px da borda; o mínimo seria ${Math.round(need)}px.`,
                "Afaste o logo da borda ou diminua o tamanho dele.", i));
            } else {
              comments.push("respeita a área de proteção");
              matched.push(`Logo com a área de proteção de ${frac(prof.clearspace)} respeitada.`);
            }
          }
          if (h.color && prof.palette.length) {
            let near = prof.palette[0], de = Infinity;
            for (const p of prof.palette) { const d = deltaE(rgb(h.color), rgb(p.hex)); if (d < de) { de = d; near = p; } }
            if (de > 15) {
              const sure = de > 30;
              if (sure) score -= 25;
              (sure ? findings : review).push(finding("Logo numa cor fora da paleta", "logo", sure ? "importante" : "ajuste",
                "O logo deve usar uma das cores oficiais da marca.",
                `O logo aparece em ${h.color}; a cor oficial mais próxima é ${near.name} ${near.hex}.`,
                `Aplique o logo em ${near.hex} ou em outra versão prevista no manual. Se a arte for foto ou render, a luz pode explicar a diferença.`,
                i, sure ? 0.8 : 0.45));
            } else {
              comments.push(`na cor ${near.name}`);
              matched.push(`Logo na cor oficial ${near.name} ${near.hex}.`);
            }
          }
        }
        cats.logo = { applicable: true, score: Math.max(0, score),
          comment: "Logo encontrado" + (hits.length > 1 ? ` em ${hits.length} imagens` : "") + (comments.length ? `, ${[...new Set(comments)].join(", ")}.` : ".") };
        strengths.unshift(...new Set(matched));  // logo first: it is what clients notice first
      }
    }

    // ---- typography (only PDFs carry font names)
    if (prof.fonts.length && art.pdf) {
      const { fonts: artFonts } = await readPdf(art.pdf, { wantLogo: false });
      const key = (f) => f.toLowerCase().replace(/ /g, "");
      const brandKeys = new Set(prof.fonts.map(key));
      const ok = artFonts.filter((f) => brandKeys.has(key(f)));
      const off = artFonts.filter((f) => !ok.includes(f) && !GENERIC_FONTS.has(key(f)));
      if (artFonts.length) {
        cats.tipografia = { applicable: true, score: Math.round((100 * ok.length) / Math.max(1, ok.length + off.length)), comment: `Fontes da arte: ${artFonts.join(", ")}.` };
        for (const f of off) findings.push(finding(`Fonte fora da marca: ${f}`, "tipografia", "importante",
          `O manual usa ${prof.fonts.join(", ")}.`, `A arte usa ${f}.`, `Troque ${f} por ${prof.fonts[0]}.`));
        for (const f of ok) strengths.push(`Usa a fonte da marca ${f}.`);
      }
    }
    if (!cats.tipografia.applicable) cats.tipografia.comment = "Só dá para conferir fontes quando a arte e o manual são PDFs com fontes identificáveis.";
    for (const k of ["composicao", "elementos", "linguagem"]) cats[k].comment = "Precisa de análise com IA.";
    if (!cats.logo.comment) cats.logo.comment = prof.logo ? "Não encontrei o logo na arte." : "Não consegui extrair o logo do manual.";

    const categories = CATEGORIES.map(([key, label, weight]) => ({ key, label, weight, ...cats[key] }));
    findings.sort((a, b) => SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity));
    const score = overall(categories);
    const measured = categories.filter((c) => c.applicable).map((c) => c.label.toLowerCase());
    const crit = findings.filter((f) => f.severity === "critico").length;
    let summary = score == null ? "Não consegui medir nada nessa arte."
      : `Medi ${measured.join(", ")}. ` + (findings.length ? `${findings.length} ponto(s) para ajustar` + (crit ? `, ${crit} crítico(s).` : ".") : "Nada fora do manual nesses critérios.");
    if (prof.notes.length) summary += " " + prof.notes.join(" ");

    return {
      mode: "browser", brand_name: prof.name, summary, score, categories, findings, to_review: review,
      strengths: strengths.slice(0, 8), brand_fonts: prof.fonts, palette: pal, model: "medicao", cost_usd: 0,
      seconds: Math.round((performance.now() - t0) / 100) / 10,
      art: { name: art.name, origin: "upload", previews: artImgs.map((c) => fit(c, 720).toDataURL("image/jpeg", 0.8)) },
      brand: { name: brand.name, origin: "upload" },
    };
  }

  return { check, readManual, load, findLogo, opencvBox };
})();
