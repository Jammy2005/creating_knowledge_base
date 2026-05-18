"""Render the 9 short docs flagged by corpus_health.py for visual review.

Shows the FULL text of each (they're <200 words) so we can judge whether
they're substantive content or just titles/notices to drop.
"""

import json, webbrowser, os

CORPUS = "output/corpus.jsonl"

SHORT_IDS = [
    "kw_cma_0007", "kw_cma_0009", "kw_cma_0030", "kw_cma_0029",
    "kw_cma_0031", "kw_cma_0028", "kw_cma_0032", "kw_cma_0011",
    "kw_cbk_0109",
]

with open(CORPUS) as f:
    by_id = {json.loads(l)["id"]: json.loads(l) for l in f if l.strip()}

cards = ""
for did in SHORT_IDS:
    d = by_id.get(did)
    if not d:
        cards += f'<div class="card missing">MISSING: {did}</div>'
        continue
    cards += f"""
    <div class="card">
      <div class="meta">
        <span class="id">{d['id']}</span>
        <span class="source">{d.get('source','')}</span>
        <span class="words">{d.get('word_count','?')} words</span>
      </div>
      <div class="name">{d.get('name','')}</div>
      <div class="url"><a href="{d.get('url','')}" target="_blank">{d.get('url','')}</a></div>
      <div class="arabic">{d.get('text','')}</div>
    </div>"""

html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>Short Docs Review (9)</title>
  <style>
    body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: #f5f5f0; padding: 2rem; direction: rtl; }}
    h1 {{ font-size: 1.3rem; color: #333; margin-bottom: 1.5rem; direction: ltr; }}
    .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1.2rem; }}
    .card.missing {{ background: #fee; color: #900; direction: ltr; }}
    .meta {{ display: flex; gap: 1rem; margin-bottom: 0.5rem; flex-wrap: wrap; direction: ltr; }}
    .id {{ font-family: monospace; font-size: 13px; background: #e8f0fe; color: #1a56db; padding: 2px 8px; border-radius: 4px; }}
    .source {{ font-size: 13px; color: #555; }}
    .words {{ font-size: 13px; color: #888; margin-right: auto; }}
    .name {{ font-size: 1.05rem; color: #222; margin-bottom: 0.4rem; }}
    .url {{ font-size: 12px; margin-bottom: 0.8rem; direction: ltr; word-break: break-all; }}
    .url a {{ color: #1a56db; text-decoration: none; }}
    .arabic {{ font-size: 1.1rem; line-height: 2; color: #111; text-align: right; direction: rtl; unicode-bidi: embed; border-top: 1px solid #eee; padding-top: 0.8rem; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>Short Docs Review — {len(SHORT_IDS)} flagged docs (full text shown)</h1>
  {cards}
</body>
</html>"""

out = "short_docs_review.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
webbrowser.open("file://" + os.path.abspath(out))
print(f"Opened {out}")
