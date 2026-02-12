#!/usr/bin/env python3
"""Generate individual HTML pages for each lab packet.

Reads go_now_lab_packets.json and generates:
- data/results/lab_packets/{id}.html for each packet
- Updates go_now_lab_packets.html as an index page

Usage:
    python generate_lab_packet_pages.py
"""

import json
from html import escape
from pathlib import Path

RESULTS_DIR = Path("data/results")
JSON_PATH = RESULTS_DIR / "go_now_lab_packets.json"
PACKETS_DIR = RESULTS_DIR / "lab_packets"

CSS = """\
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, sans-serif; background: #f5f5f5; color: #111827; line-height: 1.5; }
  .container { max-width: 900px; margin: 0 auto; padding: 24px 16px 40px; }
  h1 { margin: 0 0 6px; font-size: 24px; }
  .subtitle { color: #4b5563; margin: 0 0 16px; font-size: 14px; }
  .nav { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
  a { color: #9b9b94; text-decoration: none; }
  a:hover { color: #6b6b64; text-decoration: underline; }
  .nav a { display: inline-block; padding: 6px 12px; border: 1px solid #d1d5db; border-radius: 7px; background: #fff; color: #1f2937; font-size: 13px; text-decoration: none; }
  .nav a:hover { border-color: #9b9b94; color: #6b6b64; text-decoration: none; }
  .meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .tag-go { background: #dcfce7; color: #166534; }
  .tag-score { background: #dbeafe; color: #1e40af; }
  .tag-cost { background: #ecfeff; color: #155e75; }
  section { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; margin-bottom: 12px; }
  section h2 { margin: 0 0 8px; font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; color: #374151; }
  section p { margin: 0 0 6px; font-size: 14px; }
  section ul, section ol { margin: 0 0 6px; padding-left: 18px; }
  section li { margin: 0 0 4px; font-size: 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { border: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }
  th { background: #f9fafb; font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px; color: #4b5563; }
  td a { color: #9b9b94; text-decoration: none; }
  td a:hover { color: #6b6b64; text-decoration: underline; }
  .muted { color: #6b7280; font-size: 12px; margin-top: 8px; }
  .problem-box { background: #f9fafb; border-left: 3px solid #2563eb; padding: 12px; border-radius: 0 6px 6px 0; }
  .problem-box p { margin: 0 0 4px; font-size: 14px; }
  .problem-box .label { font-weight: 600; color: #374151; }
  @media (max-width: 800px) {
    table, thead, tbody, th, td, tr { display: block; }
    thead { display: none; }
    tr { margin-bottom: 10px; border: 1px solid #e5e7eb; }
    td { border: none; border-bottom: 1px solid #f3f4f6; }
    td:last-child { border-bottom: none; }
  }
"""


def esc(val):
    if val is None:
        return ""
    return escape(str(val))


def fmt_money(n):
    try:
        return f"${int(n):,}"
    except (ValueError, TypeError):
        return "n/a"


def render_packet_page(exp: dict, all_packets: list[dict]) -> str:
    d = exp.get("design") or {}
    cost = exp.get("estimated_direct_cost_usd") or {}

    # Prev/next navigation
    ids = [e["id"] for e in all_packets]
    idx = ids.index(exp["id"]) if exp["id"] in ids else -1
    prev_link = f'<a href="{ids[idx - 1]}.html">&larr; Previous</a>' if idx > 0 else ""
    next_link = f'<a href="{ids[idx + 1]}.html">Next &rarr;</a>' if idx < len(ids) - 1 else ""

    materials_rows = ""
    for m in exp.get("materials") or []:
        link_cell = f'<a href="{esc(m.get("link", ""))}" target="_blank" rel="noopener">source</a>' if m.get("link") else ""
        materials_rows += f"""<tr>
          <td>{esc(m.get('item'))}</td>
          <td>{esc(m.get('supplier'))}</td>
          <td>{esc(m.get('catalog_or_id'))}</td>
          <td>{link_cell}</td>
          <td>{esc(m.get('purpose'))}</td>
        </tr>"""

    refs_items = ""
    for ref in exp.get("protocol_references") or []:
        url = ref.get("url", "")
        title = esc(ref.get("title", ""))
        use = esc(ref.get("use", ""))
        if url:
            refs_items += f'<li><a href="{esc(url)}" target="_blank" rel="noopener">{title}</a> &mdash; {use}</li>'
        else:
            refs_items += f"<li>{title} &mdash; {use}</li>"

    handoff_items = "".join(
        f"<li>{esc(h)}</li>" for h in (exp.get("handoff_package_for_lab") or [])
    )

    readout_items = "".join(
        f"<li>{esc(r)}</li>" for r in (exp.get("readouts") or [])
    )

    wp_items = "".join(
        f"<li>{esc(w)}</li>" for w in (d.get("work_packages") or [])
    )

    control_items = "".join(
        f"<li>{esc(c)}</li>" for c in (d.get("controls") or [])
    )

    criteria_items = "".join(
        f"<li>{esc(s)}</li>" for s in (d.get("success_criteria") or [])
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(exp.get('title', exp['id']))} — Lab Packet</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <div class="nav">
    <a href="../go_now_lab_packets.html">All lab packets</a>
    <a href="../viewer.html">Assessment viewer</a>
    {prev_link}
    {next_link}
  </div>

  <p class="muted">{esc(exp['id'])}</p>
  <h1>{esc(exp.get('title', ''))}</h1>
  <div class="meta">
    <span class="tag tag-go">READY TO TEST</span>
    <span class="tag tag-score">Score {float(exp.get('best_score', 0)):.3f}</span>
    <span class="tag tag-cost">{fmt_money(cost.get('low'))} &ndash; {fmt_money(cost.get('high'))}</span>
  </div>

  <section>
    <h2>Problem mapping</h2>
    <div class="problem-box">
      <p><span class="label">Problem:</span> {esc(exp.get('maps_to_problem_statement'))}</p>
      <p><span class="label">Sub-question:</span> {esc(exp.get('maps_to_sub_question'))}</p>
    </div>
  </section>

  <section>
    <h2>Objective</h2>
    <p>{esc(exp.get('objective'))}</p>
  </section>

  <section>
    <h2>Readouts</h2>
    <ul>{readout_items}</ul>
  </section>

  <section>
    <h2>Experimental design</h2>
    <p><strong>Overview:</strong> {esc(d.get('overview'))}</p>
    <ul>{wp_items}</ul>
    <p><strong>Controls:</strong></p>
    <ul>{control_items}</ul>
    <p><strong>Sample size plan:</strong> {esc(d.get('sample_size_plan'))}</p>
    <p><strong>Success criteria:</strong></p>
    <ul>{criteria_items}</ul>
    <p><strong>Estimated timeline:</strong> {esc(d.get('estimated_timeline_weeks'))} weeks</p>
  </section>

  <section>
    <h2>Materials</h2>
    <table>
      <thead><tr><th>Item</th><th>Supplier</th><th>Catalog / ID</th><th>Link</th><th>Purpose</th></tr></thead>
      <tbody>{materials_rows}</tbody>
    </table>
    <p class="muted">Direct cost estimate: {fmt_money(cost.get('low'))} &ndash; {fmt_money(cost.get('high'))} ({esc(cost.get('scope', 'scope not specified'))})</p>
  </section>

  <section>
    <h2>References</h2>
    <ul>{refs_items}</ul>
  </section>

  <section>
    <h2>Lab handoff checklist</h2>
    <ul>{handoff_items}</ul>
  </section>

  <div class="nav" style="margin-top: 20px;">
    {prev_link}
    <a href="../go_now_lab_packets.html">All lab packets</a>
    {next_link}
  </div>
</div>
</body>
</html>
"""


def render_index_page(data: dict) -> str:
    experiments = data.get("experiments") or []
    generated = data.get("generated_at", "")

    total_low = sum(
        (e.get("estimated_direct_cost_usd") or {}).get("low", 0)
        for e in experiments
    )
    total_high = sum(
        (e.get("estimated_direct_cost_usd") or {}).get("high", 0)
        for e in experiments
    )

    cards = ""
    for exp in experiments:
        cost = exp.get("estimated_direct_cost_usd") or {}
        cards += f"""
    <a class="card" href="lab_packets/{esc(exp['id'])}.html">
      <div class="card-id">{esc(exp['id'])}</div>
      <div class="card-title">{esc(exp.get('title', ''))}</div>
      <div class="card-meta">
        <span class="tag tag-go">READY TO TEST</span>
        <span class="tag tag-score">Score {float(exp.get('best_score', 0)):.3f}</span>
        <span class="tag tag-cost">{fmt_money(cost.get('low'))} &ndash; {fmt_money(cost.get('high'))}</span>
      </div>
      <div class="card-problem">{esc((exp.get('maps_to_problem_statement') or '')[:120])}</div>
    </a>"""

    notes_html = ""
    for n in data.get("notes") or []:
        notes_html += f"<li>{esc(n)}</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Go-Now Lab Packets</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, sans-serif; background: #f5f5f5; color: #111827; line-height: 1.5; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 40px; }}
  h1 {{ margin: 0 0 6px; font-size: 28px; }}
  .subtitle {{ color: #4b5563; margin: 0 0 16px; font-size: 14px; }}
  .nav {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }}
  a {{ color: #9b9b94; text-decoration: none; }}
  a:hover {{ color: #6b6b64; text-decoration: underline; }}
  .nav a {{ display: inline-block; padding: 6px 12px; border: 1px solid #d1d5db; border-radius: 7px; background: #fff; color: #1f2937; font-size: 13px; text-decoration: none; }}
  .nav a:hover {{ border-color: #9b9b94; color: #6b6b64; text-decoration: none; }}
  .summary {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }}
  .chip {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }}
  .chip-value {{ font-size: 18px; font-weight: 700; color: #2563eb; }}
  .chip-label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.4px; }}
  .note-list {{ margin: 0 0 18px; padding-left: 18px; color: #4b5563; font-size: 13px; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }}
  .tag-go {{ background: #dcfce7; color: #166534; }}
  .tag-score {{ background: #dbeafe; color: #1e40af; }}
  .tag-cost {{ background: #ecfeff; color: #155e75; }}
  .cards {{ display: grid; gap: 12px; }}
  .card {{ display: block; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; text-decoration: none; color: inherit; transition: box-shadow 0.15s, border-color 0.15s; }}
  .card:hover {{ border-color: #9b9b94; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
  .card-id {{ font-size: 12px; color: #6b7280; margin-bottom: 4px; }}
  .card-title {{ font-size: 18px; font-weight: 600; margin-bottom: 8px; }}
  .card-meta {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
  .card-problem {{ font-size: 13px; color: #4b5563; }}
</style>
</head>
<body>
<div class="container">
  <h1>Go-Now Lab Packets</h1>
  <p class="subtitle">Pre-POC experimental designs and materials lists for currently eligible go-now problems.</p>
  <div class="nav">
    <a href="viewer.html">Back to assessment viewer</a>
    <a href="go_now_lab_packets.json" target="_blank" rel="noopener">Open raw JSON</a>
    <a href="go_now_rfq_packages.html">Go-now RFQ packets</a>
  </div>

  <div class="summary">
    <div class="chip"><div class="chip-value">{len(experiments)}</div><div class="chip-label">Go-now packets</div></div>
    <div class="chip"><div class="chip-value">{fmt_money(total_low)} &ndash; {fmt_money(total_high)}</div><div class="chip-label">Total direct consumables</div></div>
    <div class="chip"><div class="chip-value">{esc(data.get('criteria_version', 'n/a'))}</div><div class="chip-label">Criteria version</div></div>
  </div>

  <ul class="note-list">{notes_html}</ul>

  <div class="cards">
    {cards}
  </div>
</div>
</body>
</html>
"""


def main():
    with open(JSON_PATH) as f:
        data = json.load(f)

    experiments = data.get("experiments") or []
    if not experiments:
        print("No experiments found in JSON.")
        return

    # Create output directory
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate individual pages
    for exp in experiments:
        html = render_packet_page(exp, experiments)
        path = PACKETS_DIR / f"{exp['id']}.html"
        path.write_text(html)
        print(f"  {path}")

    # Generate index page
    index_html = render_index_page(data)
    index_path = RESULTS_DIR / "go_now_lab_packets.html"
    index_path.write_text(index_html)
    print(f"  {index_path}")

    print(f"\nGenerated {len(experiments)} individual pages + index")


if __name__ == "__main__":
    main()
