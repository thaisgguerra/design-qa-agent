/* Page languages: Portuguese (default) and English.
   Static text uses data-i18n* attributes in index.html. Results from engine.js come as message
   descriptors {k, p} and are turned into text at render time, so switching language re-renders a
   result without running the analysis again. Plain strings (e.g. from the Python server) pass through. */
"use strict";

const I18N = (() => {
  const pct = (v) => `${Math.round(v * 100)}%`;
  const list = (items, lang) => items.length < 2 ? items.join("") :
    items.slice(0, -1).join(", ") + (lang === "en" ? " and " : " e ") + items[items.length - 1];

  const D = {
    pt: {
      lang_toggle: "EN", lang_toggle_label: "Switch to English",
      title: "Flori Brand Check",
      hero_title: "Essa arte condiz com a marca?",
      hero_sub: "Envie a arte e o manual de marca do cliente. A gente confere logo, cores e tipografia e devolve uma nota com o que ajustar.",
      art_title: "A arte", art_sub: "O que foi produzido: post, banner, apresentação…",
      brand_title: "O manual de marca", brand_sub: "A identidade visual do cliente, de preferência em PDF.",
      seg_link: "Link", seg_file: "Arquivo",
      art_url_ph: "Cole o link do Figma, Google Drive ou da imagem",
      brand_url_ph: "Cole o link do Google Drive ou do PDF",
      drop_art: "<strong>Arraste a arte aqui</strong> ou clique para escolher", drop_art_hint: "PNG, JPG, WEBP ou PDF, até 30 MB",
      drop_brand: "<strong>Arraste o manual aqui</strong> ou clique para escolher", drop_brand_hint: "PDF ou imagem, até 30 MB",
      drop_change: "clique para trocar",
      notes_label: 'Contexto <span class="muted">(opcional)</span>',
      notes_ph: "Ex.: post de Instagram para a campanha de lançamento, fundo escuro de propósito",
      submit: "Comparar com o manual",
      tip: "<strong>Dica:</strong> links do Google Drive precisam estar em <em>Compartilhar → Qualquer pessoa com o link</em>. No Figma, copie o link do frame (botão direito → <em>Copy link to selection</em>).",
      banner_how: "<strong>Como funciona:</strong> a comparação mede as cores, o logo (presença, cor e respiro) e as fontes, quando a arte é PDF.",
      banner_browser: "Tudo roda no seu navegador: os arquivos não saem do seu computador. Aqui só dá para enviar arquivos, não links.",
      loading_slow: "Leva uns 30 a 60 segundos.", loading_fast: "Leva só alguns segundos.", preparing: "Preparando…",
      loading_msgs: ["Lendo o manual de marca…", "Separando a paleta oficial…", "Medindo as cores da arte…",
        "Conferindo o respiro do logo…", "Checando as fontes…", "Olhando a composição…", "Escrevendo o feedback…"],
      donut_sub: "na marca",
      sec_cats: "Nota por critério", palette_title: "Paleta", palette_sub: "Cores oficiais lidas no manual e cores medidas na arte.",
      strengths_title: "O que está mandando bem", sec_findings: "O que ajustar",
      review_summary: 'Pontos para revisar <span class="muted">(sem certeza, vale conferir)</span>',
      copy: "Copiar relatório", copied: "Copiado!", copy_fail: "Não deu para copiar", again: "Nova comparação",
      footer: "Brand Check · Ferramenta desenvolvida para a Flori Tech",
      // link chips and form errors
      chip_figma_token: "precisa de token do Figma no servidor", chip_folder: "Pasta do Drive",
      chip_folder_warn: "use o link do arquivo, não da pasta", chip_direct: "Link direto", chip_not_link: "Isso não parece um link",
      err_no_art: "Falta a arte: cole um link ou escolha um arquivo no passo 1.",
      err_no_brand: "Falta o manual de marca: cole um link ou escolha um arquivo no passo 2.",
      err_generic: "Não foi possível analisar.", err_server: "Não consegui falar com o servidor. Ele está rodando?",
      err_status: (p) => `O servidor respondeu com erro ${p.status}.`,
      // verdicts
      band: [["Na mosca!", "Essa arte está com a cara da marca."], ["Quase lá", "Bem alinhada, com alguns ajustes."],
        ["Precisa de ajustes", "Tem desvios que o cliente vai notar."], ["Fora da marca", "A arte se afastou bastante do manual."]],
      meta_brand: (p) => `Marca: ${p.v}`, meta_art: (p) => `Arte: ${p.v}`,
      meta_palette: (p) => `Paleta medida: ${p.v}% nas cores oficiais`,
      preview_alt: (p) => `Imagem ${p.n} da arte`, image_n: (p) => `Imagem ${p.n}`,
      na: "Não se aplica.", pal_official: "Paleta oficial", pal_no_codes: "O manual não traz códigos de cor.",
      pal_measured: "Cores medidas na arte", pal_in: (p) => `${p.v}% na paleta`, pal_off: "fora da paleta",
      pal_delta: (p) => `Diferença ΔE ${p.v}`,
      strengths_none: "Nada bateu com o manual nos critérios medidos.",
      findings_none: "Nenhum desvio encontrado. Pode mandar para o cliente! 🎉",
      f_manual: "O manual diz", f_art: "Na arte", f_fix: "Como ajustar",
      sev: { critico: "Crítico", importante: "Importante", ajuste: "Ajuste" },
      cat: { logo: "Logo", cores: "Cores", tipografia: "Tipografia", composicao: "Composição e respiro", elementos: "Elementos gráficos", linguagem: "Tom de voz" },
      rep_title: (p) => `# Brand Check: ${p.score}% na marca (${p.band})`,
      rep_meta: (p) => `Marca: ${p.brand} · Arte: ${p.art}`, rep_cats: "## Nota por critério", rep_na: "não se aplica",
      rep_fix: "## O que ajustar", rep_none: "- Nada a ajustar.", rep_strengths: "## Pontos fortes",
      rep_line: (p) => `- [${p.sev}] ${p.title}\n  - Manual: ${p.g}\n  - Arte: ${p.o}\n  - Ajuste: ${p.s}`,
      // engine: progress and errors
      prog_manual: "Lendo o manual de marca…", prog_colors: "Medindo as cores da arte…", prog_logo: "Procurando o logo na arte…",
      e_too_big: (p) => `O arquivo “${p.name}” passa de 30 MB. Exporte uma versão mais leve.`,
      e_pdf: (p) => `Não consegui abrir o PDF “${p.name}”.`,
      e_not_image: (p) => `“${p.name}” não é uma imagem nem um PDF. Use PNG, JPG, WEBP ou PDF.`,
      e_no_pages: "A arte não tem nenhuma página.",
      e_lib: "Não consegui carregar uma biblioteca da internet. Confira a conexão.",
      manual_color: "Cor do manual",
      // engine: results
      c_colors: (p) => `${p.a}% da área da arte usa cores da paleta` + (p.estimated ? " (paleta estimada)." : " oficial."),
      off_title: (p) => `${p.n} cor(es) fora da paleta (${pct(p.total)} da arte)`,
      off_guideline: (p) => "Paleta oficial: " + p.palette.map((c) => `${c.name} ${c.hex}`).join(", ") + ".",
      off_observed: (p) => p.colors.map((c) => `${c.hex} (${pct(c.share)}, mais perto de ${c.nearest})`).join("; ") + ".",
      off_fix: "Troque essas cores pela cor oficial mais próxima. Se forem sombras de foto ou render, pode ignorar.",
      s_palette_ok: "As cores da arte estão dentro da paleta da marca.",
      s_color: (p) => `Usa a cor oficial ${p.name} (${pct(p.share)} da arte).`,
      nf_title: "Não encontrei o logo na arte", nf_guideline: "O logo do manual foi procurado em todas as imagens da arte.",
      nf_observed: "Nenhuma área parecida com o logo.",
      nf_fix: "Se a peça deveria ter logo, confira se ele está lá e sem distorção. Logos muito pequenos, inclinados ou em versão diferente podem não ser reconhecidos.",
      s_logo: (p) => "Logo da marca presente na arte" + (p.n > 1 ? ` (${p.n} imagens).` : "."),
      s_logo_clear: (p) => `Logo com a área de proteção de ${p.frac} respeitada.`,
      s_logo_color: (p) => `Logo na cor oficial ${p.name} ${p.hex}.`,
      cl_title: "Logo sem a área de proteção",
      cl_guideline: (p) => `O manual pede um respiro de ${p.frac} da largura do logo em volta dele.`,
      cl_observed: (p) => `O logo está a ${p.gap}px da borda; o mínimo seria ${p.need}px.`,
      cl_fix: "Afaste o logo da borda ou diminua o tamanho dele.",
      lc_title: "Logo numa cor fora da paleta", lc_guideline: "O logo deve usar uma das cores oficiais da marca.",
      lc_observed: (p) => `O logo aparece em ${p.color}; a cor oficial mais próxima é ${p.name} ${p.hex}.`,
      lc_fix: (p) => `Aplique o logo em ${p.hex} ou em outra versão prevista no manual. Se a arte for foto ou render, a luz pode explicar a diferença.`,
      c_logo: (p) => "Logo encontrado" + (p.n > 1 ? ` em ${p.n} imagens` : "") +
        (p.clear || p.color ? ", " + [p.clear && "respeita a área de proteção", p.color && `na cor ${p.color}`].filter(Boolean).join(", ") : "") + ".",
      c_fonts: (p) => `Fontes da arte: ${p.fonts.join(", ")}.`,
      ft_title: (p) => `Fonte fora da marca: ${p.f}`, ft_guideline: (p) => `O manual usa ${p.brand.join(", ")}.`,
      ft_observed: (p) => `A arte usa ${p.f}.`, ft_fix: (p) => `Troque ${p.f} por ${p.to}.`,
      s_font: (p) => `Usa a fonte da marca ${p.f}.`,
      c_typo_na: "Só dá para conferir fontes quando a arte e o manual são PDFs com fontes identificáveis.",
      c_needs_ai: "Precisa de análise com IA.",
      c_logo_nf: "Não encontrei o logo na arte.", c_logo_nx: "Não consegui extrair o logo do manual.",
      summary: (p, lang) => {
        if (p.score == null) return "Não consegui medir nada nessa arte.";
        let s = `Medi ${list(p.measured.map((k) => D[lang].cat[k].toLowerCase()), lang)}. `;
        s += p.n ? `${p.n} ponto(s) para ajustar` + (p.crit ? `, ${p.crit} crítico(s).` : ".") : "Nada fora do manual nesses critérios.";
        if (p.estimated) s += " O manual não traz códigos de cor escritos; a paleta foi estimada pelas cores das páginas.";
        return s;
      },
    },
    en: {
      lang_toggle: "PT", lang_toggle_label: "Mudar para português",
      title: "Flori Brand Check",
      hero_title: "Is this art on brand?",
      hero_sub: "Upload the art and the client's brand guidelines. We check logo, colors and typography and give you a score with what to fix.",
      art_title: "The art", art_sub: "What was made: post, banner, presentation…",
      brand_title: "The brand guidelines", brand_sub: "The client's visual identity, ideally as a PDF.",
      seg_link: "Link", seg_file: "File",
      art_url_ph: "Paste a Figma, Google Drive or image link",
      brand_url_ph: "Paste a Google Drive or PDF link",
      drop_art: "<strong>Drop the art here</strong> or click to choose", drop_art_hint: "PNG, JPG, WEBP or PDF, up to 30 MB",
      drop_brand: "<strong>Drop the guidelines here</strong> or click to choose", drop_brand_hint: "PDF or image, up to 30 MB",
      drop_change: "click to replace",
      notes_label: 'Context <span class="muted">(optional)</span>',
      notes_ph: "E.g. Instagram post for the launch campaign, dark background on purpose",
      submit: "Compare with the guidelines",
      tip: "<strong>Tip:</strong> Google Drive links must be set to <em>Share → Anyone with the link</em>. In Figma, copy the frame link (right click → <em>Copy link to selection</em>).",
      banner_how: "<strong>How it works:</strong> the comparison measures colors, the logo (presence, color and clear space) and fonts, when the art is a PDF.",
      banner_browser: "Everything runs in your browser: your files never leave your computer. Here you can upload files, not links.",
      loading_slow: "It takes about 30 to 60 seconds.", loading_fast: "It only takes a few seconds.", preparing: "Getting ready…",
      loading_msgs: ["Reading the brand guidelines…", "Pulling out the official palette…", "Measuring the art's colors…",
        "Checking the logo's clear space…", "Checking the fonts…", "Looking at the layout…", "Writing the feedback…"],
      donut_sub: "on brand",
      sec_cats: "Score by criterion", palette_title: "Palette", palette_sub: "Official colors read from the guidelines and colors measured in the art.",
      strengths_title: "What's working", sec_findings: "What to fix",
      review_summary: 'Points to review <span class="muted">(not certain, worth a look)</span>',
      copy: "Copy report", copied: "Copied!", copy_fail: "Couldn't copy", again: "New comparison",
      footer: "Brand Check · A tool built for Flori Tech",
      chip_figma_token: "needs a Figma token on the server", chip_folder: "Drive folder",
      chip_folder_warn: "use the file link, not the folder", chip_direct: "Direct link", chip_not_link: "This doesn't look like a link",
      err_no_art: "The art is missing: paste a link or choose a file in step 1.",
      err_no_brand: "The brand guidelines are missing: paste a link or choose a file in step 2.",
      err_generic: "The analysis didn't work.", err_server: "Couldn't reach the server. Is it running?",
      err_status: (p) => `The server returned error ${p.status}.`,
      band: [["Spot on!", "This art looks just like the brand."], ["Almost there", "Well aligned, with a few tweaks."],
        ["Needs work", "There are deviations the client will notice."], ["Off brand", "The art drifted far from the guidelines."]],
      meta_brand: (p) => `Brand: ${p.v}`, meta_art: (p) => `Art: ${p.v}`,
      meta_palette: (p) => `Measured palette: ${p.v}% in official colors`,
      preview_alt: (p) => `Art image ${p.n}`, image_n: (p) => `Image ${p.n}`,
      na: "Not applicable.", pal_official: "Official palette", pal_no_codes: "The guidelines have no color codes.",
      pal_measured: "Colors measured in the art", pal_in: (p) => `${p.v}% in palette`, pal_off: "off palette",
      pal_delta: (p) => `ΔE difference ${p.v}`,
      strengths_none: "Nothing matched the guidelines on the measured criteria.",
      findings_none: "No deviations found. Good to send to the client! 🎉",
      f_manual: "The guidelines say", f_art: "In the art", f_fix: "How to fix",
      sev: { critico: "Critical", importante: "Important", ajuste: "Tweak" },
      cat: { logo: "Logo", cores: "Colors", tipografia: "Typography", composicao: "Layout and spacing", elementos: "Graphic elements", linguagem: "Tone of voice" },
      rep_title: (p) => `# Brand Check: ${p.score}% on brand (${p.band})`,
      rep_meta: (p) => `Brand: ${p.brand} · Art: ${p.art}`, rep_cats: "## Score by criterion", rep_na: "not applicable",
      rep_fix: "## What to fix", rep_none: "- Nothing to fix.", rep_strengths: "## What's working",
      rep_line: (p) => `- [${p.sev}] ${p.title}\n  - Guidelines: ${p.g}\n  - Art: ${p.o}\n  - Fix: ${p.s}`,
      prog_manual: "Reading the brand guidelines…", prog_colors: "Measuring the art's colors…", prog_logo: "Looking for the logo in the art…",
      e_too_big: (p) => `The file “${p.name}” is over 30 MB. Export a lighter version.`,
      e_pdf: (p) => `Couldn't open the PDF “${p.name}”.`,
      e_not_image: (p) => `“${p.name}” is not an image or a PDF. Use PNG, JPG, WEBP or PDF.`,
      e_no_pages: "The art has no pages.",
      e_lib: "Couldn't load a library from the internet. Check your connection.",
      manual_color: "Guidelines color",
      c_colors: (p) => `${p.a}% of the art's area uses ` + (p.estimated ? "palette colors (estimated palette)." : "official palette colors."),
      off_title: (p) => `${p.n} off-palette color(s) (${pct(p.total)} of the art)`,
      off_guideline: (p) => "Official palette: " + p.palette.map((c) => `${c.name} ${c.hex}`).join(", ") + ".",
      off_observed: (p) => p.colors.map((c) => `${c.hex} (${pct(c.share)}, closest to ${c.nearest})`).join("; ") + ".",
      off_fix: "Replace these colors with the closest official color. If they are photo or render shading, you can ignore them.",
      s_palette_ok: "The art's colors are within the brand palette.",
      s_color: (p) => `Uses the official color ${p.name} (${pct(p.share)} of the art).`,
      nf_title: "Couldn't find the logo in the art", nf_guideline: "The logo from the guidelines was searched in every image of the art.",
      nf_observed: "No area looks like the logo.",
      nf_fix: "If the piece should have a logo, check that it's there and not distorted. Very small, tilted or alternate versions of the logo may not be recognized.",
      s_logo: (p) => "Brand logo present in the art" + (p.n > 1 ? ` (${p.n} images).` : "."),
      s_logo_clear: (p) => `Logo clear space of ${p.frac} respected.`,
      s_logo_color: (p) => `Logo in the official color ${p.name} ${p.hex}.`,
      cl_title: "Logo without its clear space",
      cl_guideline: (p) => `The guidelines ask for clear space of ${p.frac} of the logo's width around it.`,
      cl_observed: (p) => `The logo is ${p.gap}px from the edge; the minimum would be ${p.need}px.`,
      cl_fix: "Move the logo away from the edge or make it smaller.",
      lc_title: "Logo in an off-palette color", lc_guideline: "The logo must use one of the brand's official colors.",
      lc_observed: (p) => `The logo appears in ${p.color}; the closest official color is ${p.name} ${p.hex}.`,
      lc_fix: (p) => `Apply the logo in ${p.hex} or in another version from the guidelines. If the art is a photo or render, lighting may explain the difference.`,
      c_logo: (p) => "Logo found" + (p.n > 1 ? ` in ${p.n} images` : "") +
        (p.clear || p.color ? ", " + [p.clear && "clear space respected", p.color && `in ${p.color}`].filter(Boolean).join(", ") : "") + ".",
      c_fonts: (p) => `Fonts in the art: ${p.fonts.join(", ")}.`,
      ft_title: (p) => `Off-brand font: ${p.f}`, ft_guideline: (p) => `The guidelines use ${p.brand.join(", ")}.`,
      ft_observed: (p) => `The art uses ${p.f}.`, ft_fix: (p) => `Replace ${p.f} with ${p.to}.`,
      s_font: (p) => `Uses the brand font ${p.f}.`,
      c_typo_na: "Fonts can only be checked when both the art and the guidelines are PDFs with identifiable fonts.",
      c_needs_ai: "Needs AI analysis.",
      c_logo_nf: "Couldn't find the logo in the art.", c_logo_nx: "Couldn't extract the logo from the guidelines.",
      summary: (p, lang) => {
        if (p.score == null) return "Couldn't measure anything in this art.";
        let s = `Measured ${list(p.measured.map((k) => D[lang].cat[k].toLowerCase()), lang)}. `;
        s += p.n ? `${p.n} point(s) to fix` + (p.crit ? `, ${p.crit} critical.` : ".") : "Nothing off-guidelines on these criteria.";
        if (p.estimated) s += " The guidelines have no written color codes; the palette was estimated from the pages' colors.";
        return s;
      },
    },
  };

  let lang = "pt";
  try { if (localStorage.getItem("brandcheck.lang") === "en") lang = "en"; } catch { /* storage blocked */ }

  function t(key, params = {}) {
    const v = D[lang][key] ?? D.pt[key] ?? key;
    return typeof v === "function" ? v(params, lang) : v;
  }
  // a message descriptor {k, p} from engine.js, or a plain string
  const msg = (m) => (m && typeof m === "object" && "k" in m ? t(m.k, m.p) : m ?? "");

  function apply() {
    document.documentElement.lang = lang === "en" ? "en" : "pt-BR";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  }

  function setLang(l) {
    lang = l;
    try { localStorage.setItem("brandcheck.lang", l); } catch { /* storage blocked */ }
    apply();
  }

  return { t, msg, apply, setLang, get lang() { return lang; } };
})();
