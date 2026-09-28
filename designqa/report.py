"""Self-contained HTML report (the artifact a designer or PM reviews before tickets are opened)."""
from __future__ import annotations

import base64
import html
from pathlib import Path

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c1f26;--muted:#6b7280;--line:#e5e7eb;--crit:#c81e3c;--maj:#d97706;--min:#2563eb;--ok:#15803d}
@media (prefers-color-scheme:dark){:root{--bg:#111318;--card:#1b1e25;--ink:#eef0f4;--muted:#9aa1ad;--line:#2b2f38}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
main{max-width:1100px;margin:0 auto;padding:32px 16px}h1{font-size:26px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 24px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:28px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}.stat b{display:block;font-size:24px}
.stat span{color:var(--muted);font-size:13px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.card h3{margin:0 0 8px;font-size:17px}.tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tag{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.critical{background:var(--crit);color:#fff;border:0}.major{background:var(--maj);color:#fff;border:0}.minor{background:var(--min);color:#fff;border:0}
table{border-collapse:collapse;width:100%;margin:8px 0}td{border-top:1px solid var(--line);padding:6px 8px;vertical-align:top}
td:first-child{color:var(--muted);width:170px}img{max-width:100%;border-radius:8px;border:1px solid var(--line)}
.muted{color:var(--muted);font-size:13px}.rejected{opacity:.55}details{margin-top:28px}
"""


def _img(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def write_report(result: dict, out_path: Path) -> Path:
    e = html.escape
    fs = result["findings"]
    count = lambda k, v: sum(1 for f in fs if f[k] == v)
    cards = []
    for f in fs:
        ev = Path(f["evidence"]) if f.get("evidence") else None
        cards.append(f"""
<div class="card {'rejected' if f['status']=='rejected' else ''}">
  <h3>{e(f['id'])} · {e(f['title'])}</h3>
  <div class="tags"><span class="tag {e(f['severity'])}">{e(f['severity'])}</span>
  <span class="tag">{e(f['category'])}</span><span class="tag">status: {e(f['status'])}</span>
  <span class="tag">confidence {f['confidence']:.0%}</span></div>
  <table><tr><td>Element</td><td>{e(f['element'])}</td></tr>
  <tr><td>Expected (design)</td><td>{e(f['expected'])}</td></tr>
  <tr><td>Actual (build)</td><td>{e(f['actual'])}</td></tr>
  <tr><td>Rationale</td><td>{e(f['rationale'])}</td></tr>
  <tr><td>Automated checks</td><td class="muted">{e('; '.join(f['checks']))}</td></tr>
  {f"<tr><td>Ticket</td><td>{e(f['ticket'])}</td></tr>" if f.get('ticket') else ''}</table>
  {f'<img alt="Design vs implementation" src="{_img(ev)}">' if ev and ev.exists() else ''}
</div>""")
    overview = Path(result["artifacts"]["overlay"])
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Design QA Report</title><style>{CSS}</style></head>
<body><main><h1>Design QA · {e(result['screen'])}</h1>
<p class="sub">Analyzer: {e(result['analyzer'])} ({e(result['model'])}) · {e(result['created_at'])}</p>
<div class="stats">
<div class="stat"><b>{count('status','proposed')+count('status','approved')}</b><span>findings ready for tickets</span></div>
<div class="stat"><b>{count('status','needs_review')}</b><span>need human review</span></div>
<div class="stat"><b>{count('status','rejected')}</b><span>rejected by guardrails</span></div>
<div class="stat"><b>{count('severity','critical')}</b><span>critical</span></div>
<div class="stat"><b>{result['diff_ratio']:.2%}</b><span>pixels changed</span></div>
<div class="stat"><b>${result['usage']['cost_usd']:.3f}</b><span>{result['usage']['calls']} model calls · {result['usage']['seconds']:.1f}s</span></div>
</div>
{''.join(cards) or '<p>No deviations found.</p>'}
<details><summary>Full screen diff overlay</summary><img alt="Diff overlay" src="{_img(overview)}"></details>
</main></body></html>"""
    out_path.write_text(body, encoding="utf-8")
    return out_path
