"""Self-contained visual HTML executive report generator for stockout intelligence.

Generates ``data/stockout_report.html`` from the cleaned catalog and
``stockout_opportunities.json`` structure with zero external runtime
dependencies so clients can open it directly in any browser or capture
portfolio-ready visuals.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _fmt_brl(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    formatted = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "0.0%"
    return f"{value:.1f}%"


def generate_html_report(
    cleaned_df: pd.DataFrame,
    report_data: dict[str, Any],
    output_path: Path | str = Path("data/stockout_report.html"),
) -> Path:
    """Render an interactive, standalone HTML dashboard of competitor stockouts."""
    summary = report_data["summary"]
    by_category = report_data["by_category"]
    opportunities = report_data["opportunities_by_active_ingredient"]
    generated_at = str(report_data.get("generated_at", ""))[:19].replace("T", " ") + " UTC"

    # Build category breakdown cards/bars
    category_bars_html: list[str] = []
    for cat in by_category:
        cat_name = html.escape(str(cat["category"]))
        total = int(cat["total_skus"])
        oos = int(cat["out_of_stock_skus"])
        in_stock = total - oos
        rate = float(cat["stockout_rate_pct"])
        avg_to = _fmt_brl(cat.get("avg_reference_price_to"))
        category_bars_html.append(
            f"""
            <div class="cat-row">
                <div class="cat-header">
                    <span class="cat-name">{cat_name}</span>
                    <span class="cat-metrics">
                        <strong>{oos}</strong>/{total} OOS ({rate:.1f}%) &middot; Avg OOS Price: <strong>{avg_to}</strong>
                    </span>
                </div>
                <div class="bar-track" role="img" aria-label="{cat_name}: {rate:.1f}% out of stock">
                    <div class="bar-fill-oos" style="width: {min(100.0, rate):.1f}%"></div>
                </div>
                <div class="cat-sub">
                    <span>In stock: {in_stock}</span>
                    <span>Out of stock: {oos}</span>
                </div>
            </div>
            """
        )

    # Build grouped opportunity cards (top 6 highest priority)
    top_cards_html: list[str] = []
    for opp in opportunities[:6]:
        priority = str(opp["opportunity_priority"])
        badge_cls = "badge-high" if priority == "HIGH" else "badge-med"
        ingredient = html.escape(str(opp["active_ingredient"]))
        category = html.escape(str(opp["category"]))
        oos_count = int(opp["out_of_stock_skus"])
        alts = int(opp["competitor_in_stock_alternatives"])
        alt_note = (
            '<span class="zero-alt">0 competitor substitutes in stock</span>'
            if alts == 0
            else f'<span class="has-alt">{alts} substitute SKU(s) left</span>'
        )
        avg_from = _fmt_brl(opp.get("avg_reference_price_from"))
        avg_to = _fmt_brl(opp.get("avg_reference_price_to"))
        avg_disc = _fmt_pct(opp.get("avg_discount_pct_before_stockout"))
        top_cards_html.append(
            f"""
            <div class="opp-card">
                <div class="opp-top">
                    <span class="badge {badge_cls}">{priority} PRIORITY</span>
                    <span class="opp-cat">{category}</span>
                </div>
                <h3 class="opp-title">{ingredient}</h3>
                <div class="opp-meta">{oos_count} OOS SKU(s) &middot; {alt_note}</div>
                <div class="opp-pricing">
                    <div>
                        <span class="lbl">Avg List ("De")</span>
                        <span class="val muted">{avg_from}</span>
                    </div>
                    <div>
                        <span class="lbl">Avg Cash ("Por")</span>
                        <span class="val strong">{avg_to}</span>
                    </div>
                    <div>
                        <span class="lbl">Prior Discount</span>
                        <span class="val accent">{avg_disc}</span>
                    </div>
                </div>
            </div>
            """
        )

    # Build filterable table rows for all out-of-stock SKUs
    table_rows_html: list[str] = []
    for opp in opportunities:
        priority = str(opp["opportunity_priority"])
        badge_cls = "badge-high" if priority == "HIGH" else "badge-med"
        category = str(opp["category"])
        ingredient = str(opp["active_ingredient"])
        alts = int(opp["competitor_in_stock_alternatives"])
        for prod in opp["products"]:
            sku = html.escape(str(prod["sku"]))
            name = html.escape(str(prod["product_name"]))
            brand = html.escape(str(prod["brand"]))
            dosage = html.escape(str(prod["dosage_raw"])) if prod.get("dosage_raw") else "—"
            units = (
                f"{prod['package_units']} un."
                if prod.get("package_units") is not None
                else "—"
            )
            p_from = _fmt_brl(prod.get("reference_price_from"))
            p_to = _fmt_brl(prod.get("reference_price_to"))
            disc = _fmt_pct(prod.get("discount_pct"))
            avail = html.escape(str(prod["availability_raw"]))
            search_blob = html.escape(
                f"{sku} {name} {brand} {ingredient} {category} {priority}".lower()
            )
            table_rows_html.append(
                f"""
                <tr data-category="{html.escape(category)}" data-priority="{priority}" data-search="{search_blob}">
                    <td><span class="badge {badge_cls}">{priority}</span></td>
                    <td><code class="sku">{sku}</code></td>
                    <td>
                        <div class="prod-name">{name}</div>
                        <div class="prod-sub">{html.escape(ingredient)} &middot; {brand}</div>
                    </td>
                    <td><span class="pill">{html.escape(category)}</span></td>
                    <td>{dosage} / {units}</td>
                    <td class="num muted">{p_from}</td>
                    <td class="num strong">{p_to}</td>
                    <td class="num accent">{disc}</td>
                    <td class="num">{alts}</td>
                    <td><span class="status-oos">{avail}</span></td>
                </tr>
                """
            )

    category_options = "\n".join(
        f'<option value="{html.escape(str(cat["category"]))}">{html.escape(str(cat["category"]))}</option>'
        for cat in by_category
    )

    avg_catalog_discount = (
        float(cleaned_df["discount_pct"].mean()) if not cleaned_df.empty else 0.0
    )

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Competitor Stockout &amp; Pricing Intelligence Report</title>
<style>
  :root {{
    --bg: #f8fafc;
    --surface: #ffffff;
    --border: #e2e8f0;
    --text: #0f172a;
    --muted: #64748b;
    --primary: #0f766e;
    --primary-soft: #ccfbf1;
    --danger: #dc2626;
    --danger-soft: #fee2e2;
    --warn: #d97706;
    --warn-soft: #fef3c7;
    --ok: #15803d;
    --ok-soft: #dcfce7;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  .container {{
    max-width: 1340px;
    margin: 0 auto;
    padding: 32px 24px 56px;
  }}
  header {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-end;
    gap: 16px;
    margin-bottom: 28px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }}
  .eyebrow {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--primary);
    margin-bottom: 6px;
  }}
  h1 {{
    margin: 0;
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.02em;
  }}
  .subtitle {{
    margin: 6px 0 0;
    color: var(--muted);
    font-size: 14px;
  }}
  .timestamp {{
    font-size: 12px;
    color: var(--muted);
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 8px 12px;
    border-radius: 8px;
  }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }}
  .kpi-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }}
  .kpi-label {{
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }}
  .kpi-value {{
    font-size: 30px;
    font-weight: 800;
    margin-top: 6px;
    letter-spacing: -0.02em;
  }}
  .kpi-value.danger {{ color: var(--danger); }}
  .kpi-value.primary {{ color: var(--primary); }}
  .kpi-foot {{
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
  }}
  .section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 24px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }}
  .section h2 {{
    margin: 0 0 4px;
    font-size: 18px;
    font-weight: 700;
  }}
  .section-desc {{
    margin: 0 0 18px;
    font-size: 13px;
    color: var(--muted);
  }}
  .cat-row {{ margin-bottom: 16px; }}
  .cat-row:last-child {{ margin-bottom: 0; }}
  .cat-header {{
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 14px;
    margin-bottom: 6px;
  }}
  .cat-name {{ font-weight: 700; }}
  .cat-metrics {{ color: var(--muted); font-size: 13px; }}
  .cat-metrics strong {{ color: var(--text); }}
  .bar-track {{
    height: 12px;
    background: var(--ok-soft);
    border-radius: 999px;
    overflow: hidden;
  }}
  .bar-fill-oos {{
    height: 100%;
    background: linear-gradient(90deg, #ef4444, #dc2626);
    border-radius: 999px;
  }}
  .cat-sub {{
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: var(--muted);
    margin-top: 4px;
  }}
  .opp-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
    gap: 16px;
  }}
  .opp-card {{
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    background: #fcfdff;
  }}
  .opp-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }}
  .opp-cat {{
    font-size: 11px;
    color: var(--muted);
    font-weight: 600;
  }}
  .opp-title {{
    margin: 0 0 4px;
    font-size: 15px;
    font-weight: 700;
  }}
  .opp-meta {{
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 14px;
  }}
  .zero-alt {{ color: var(--danger); font-weight: 600; }}
  .has-alt {{ color: var(--warn); font-weight: 600; }}
  .opp-pricing {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    padding-top: 12px;
    border-top: 1px dashed var(--border);
  }}
  .opp-pricing .lbl {{
    display: block;
    font-size: 11px;
    color: var(--muted);
  }}
  .opp-pricing .val {{
    font-size: 14px;
    font-weight: 700;
  }}
  .badge {{
    display: inline-block;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.04em;
    padding: 3px 8px;
    border-radius: 999px;
  }}
  .badge-high {{ background: var(--danger-soft); color: var(--danger); }}
  .badge-med {{ background: var(--warn-soft); color: var(--warn); }}
  .toolbar {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 16px;
  }}
  .toolbar input, .toolbar select {{
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 13px;
    background: var(--surface);
    color: var(--text);
  }}
  .toolbar input {{ flex: 1; min-width: 220px; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
  }}
  th {{
    text-align: left;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    padding: 10px 8px;
    border-bottom: 2px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 10px 8px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tr:hover td {{ background: #f8fafc; }}
  .sku {{
    font-size: 11px;
    background: #f1f5f9;
    padding: 2px 6px;
    border-radius: 4px;
    white-space: nowrap;
  }}
  .prod-name {{ font-weight: 600; }}
  .prod-sub {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
  .pill {{
    display: inline-block;
    font-size: 11px;
    background: #f1f5f9;
    color: #334155;
    padding: 2px 8px;
    border-radius: 6px;
    white-space: nowrap;
  }}
  .status-oos {{
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    background: var(--danger-soft);
    color: var(--danger);
    padding: 3px 8px;
    border-radius: 6px;
    white-space: nowrap;
  }}
  .num {{ text-align: right; white-space: nowrap; }}
  .muted {{ color: var(--muted); }}
  .strong {{ font-weight: 700; color: var(--text); }}
  .accent {{ font-weight: 700; color: var(--primary); }}
  footer {{
    text-align: center;
    font-size: 12px;
    color: var(--muted);
    margin-top: 20px;
  }}
</style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <div class="eyebrow">Pharmacy Competitive Intelligence</div>
        <h1>Competitor Price &amp; Stockout Monitor</h1>
        <p class="subtitle">
          Automated out-of-stock alerts, active-ingredient coverage gaps, and pre-stockout reference pricing.
        </p>
      </div>
      <div class="timestamp">Generated: {html.escape(generated_at)}</div>
    </header>

    <section class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Tracked Catalog SKUs</div>
        <div class="kpi-value">{summary['total_catalog_skus']}</div>
        <div class="kpi-foot">{summary['in_stock_skus']} in stock &middot; deduplicated by SKU &amp; URL</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Competitor Stockouts</div>
        <div class="kpi-value danger">{summary['out_of_stock_skus']}</div>
        <div class="kpi-foot">{summary['stockout_rate_pct']}% overall stockout rate</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">High-Priority Molecules</div>
        <div class="kpi-value primary">{summary['high_priority_opportunities']}</div>
        <div class="kpi-foot">{summary['unique_active_ingredients_affected']} active ingredients affected</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Avg Cash Price (OOS)</div>
        <div class="kpi-value">{_fmt_brl(summary.get('avg_reference_price_to_oos'))}</div>
        <div class="kpi-foot">Catalog avg real discount: {avg_catalog_discount:.1f}%</div>
      </div>
    </section>

    <section class="section">
      <h2>Stockout Rate by Category</h2>
      <p class="section-desc">Red segments show the percentage of tracked SKUs currently unavailable at the competitor.</p>
      {"".join(category_bars_html)}
    </section>

    <section class="section">
      <h2>Top Commercial Capture Opportunities</h2>
      <p class="section-desc">Prioritized by active ingredients where the competitor has zero in-stock substitutes, multiple stockouts, or high ticket value.</p>
      <div class="opp-grid">
        {"".join(top_cards_html)}
      </div>
    </section>

    <section class="section">
      <h2>All Out-of-Stock Competitor SKUs</h2>
      <p class="section-desc">Filter by category, priority, brand, SKU, or active ingredient to plan targeted ad campaigns and generic repricing.</p>
      <div class="toolbar">
        <input id="searchInput" type="search" placeholder="Search SKU, product, active ingredient, or brand..." />
        <select id="categoryFilter">
          <option value="ALL">All Categories</option>
          {category_options}
        </select>
        <select id="priorityFilter">
          <option value="ALL">All Priorities</option>
          <option value="HIGH">HIGH Priority Only</option>
          <option value="MEDIUM">MEDIUM Priority Only</option>
        </select>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Priority</th>
              <th>SKU</th>
              <th>Product &amp; Active Ingredient</th>
              <th>Category</th>
              <th>Dosage / Pack</th>
              <th class="num">List ("De")</th>
              <th class="num">Cash ("Por")</th>
              <th class="num">Discount</th>
              <th class="num">Comp. Alts</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="oosTableBody">
            {"".join(table_rows_html)}
          </tbody>
        </table>
      </div>
    </section>

    <footer>
      Generated automatically by <strong>pharma-competitor-stock-price-tracker</strong> &middot;
      Data backed by SQLite (<code>data/pharma_catalog.db</code>) &amp; Excel-ready CSV (<code>data/cleaned_pharma_catalog.csv</code>)
    </footer>
  </div>

<script>
  const searchInput = document.getElementById("searchInput");
  const categoryFilter = document.getElementById("categoryFilter");
  const priorityFilter = document.getElementById("priorityFilter");
  const rows = Array.from(document.querySelectorAll("#oosTableBody tr"));

  function applyFilters() {{
    const q = searchInput.value.trim().toLowerCase();
    const cat = categoryFilter.value;
    const prio = priorityFilter.value;
    rows.forEach((row) => {{
      const matchSearch = !q || row.dataset.search.includes(q);
      const matchCat = cat === "ALL" || row.dataset.category === cat;
      const matchPrio = prio === "ALL" || row.dataset.priority === prio;
      row.style.display = (matchSearch && matchCat && matchPrio) ? "" : "none";
    }});
  }}

  searchInput.addEventListener("input", applyFilters);
  categoryFilter.addEventListener("change", applyFilters);
  priorityFilter.addEventListener("change", applyFilters);
</script>
</body>
</html>
"""

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(document, encoding="utf-8")
    logger.info("Generated visual HTML stockout report -> %s", out_file)
    return out_file
