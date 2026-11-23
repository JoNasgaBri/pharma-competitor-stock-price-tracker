"""Competitive stockout intelligence and opportunity reporting.

Filters out-of-stock products (``is_in_stock == False``), groups them by
category and active ingredient, compares against in-stock competitor
alternatives for the same active ingredient, and exports an actionable
JSON report to ``data/stockout_opportunities.json``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 2)


def _safe_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def generate_stockout_report(
    cleaned_df: pd.DataFrame,
    output_path: Path | str = Path("data/stockout_opportunities.json"),
) -> dict[str, Any]:
    """Identify competitor stockout opportunities grouped by active ingredient and category."""
    total_skus = int(len(cleaned_df))
    oos_df = cleaned_df[cleaned_df["is_in_stock"] == False].copy()  # noqa: E712
    in_stock_df = cleaned_df[cleaned_df["is_in_stock"] == True].copy()  # noqa: E712

    oos_count = int(len(oos_df))
    in_stock_count = int(len(in_stock_df))
    stockout_rate = round((oos_count / total_skus) * 100.0, 2) if total_skus > 0 else 0.0

    # In-stock competitor alternatives per active ingredient
    in_stock_counts = (
        in_stock_df.groupby("active_ingredient")["sku"].count().to_dict()
        if not in_stock_df.empty
        else {}
    )

    # Category-level breakdown
    category_summary: list[dict[str, Any]] = []
    for category, cat_group in cleaned_df.groupby("category", sort=True):
        cat_total = int(len(cat_group))
        cat_oos = cat_group[cat_group["is_in_stock"] == False]  # noqa: E712
        cat_oos_count = int(len(cat_oos))
        category_summary.append(
            {
                "category": str(category),
                "total_skus": cat_total,
                "out_of_stock_skus": cat_oos_count,
                "stockout_rate_pct": (
                    round((cat_oos_count / cat_total) * 100.0, 2) if cat_total > 0 else 0.0
                ),
                "avg_reference_price_from": (
                    _safe_float(cat_oos["price_from"].mean()) if not cat_oos.empty else None
                ),
                "avg_reference_price_to": (
                    _safe_float(cat_oos["price_to"].mean()) if not cat_oos.empty else None
                ),
            }
        )

    # Group out-of-stock SKUs by (category, active_ingredient)
    opportunities: list[dict[str, Any]] = []
    if not oos_df.empty:
        grouped = oos_df.groupby(["category", "active_ingredient"], sort=True)
        for (category, active_ingredient), group in grouped:
            alternatives_available = int(in_stock_counts.get(active_ingredient, 0))
            avg_price_from = _safe_float(group["price_from"].mean())
            avg_price_to = _safe_float(group["price_to"].mean())
            avg_discount_pct = _safe_float(group["discount_pct"].mean())

            # Commercial priority heuristic:
            # HIGH when competitor has zero in-stock substitutes for the active ingredient
            # OR when multiple SKUs are out of stock OR high-ticket item (>= R$ 80).
            if (
                alternatives_available == 0
                or len(group) >= 2
                or (avg_price_to is not None and avg_price_to >= 80.0)
            ):
                priority = "HIGH"
            else:
                priority = "MEDIUM"

            products_list: list[dict[str, Any]] = []
            for _, row in group.sort_values(
                by="price_to", ascending=False, na_position="last"
            ).iterrows():
                products_list.append(
                    {
                        "sku": row["sku"],
                        "product_name": row["product_name"],
                        "brand": row["brand"],
                        "dosage_raw": (
                            None if pd.isna(row["dosage_raw"]) else str(row["dosage_raw"])
                        ),
                        "dosage_mg": _safe_float(row["dosage_mg"]),
                        "package_units": _safe_int(row["package_units"]),
                        "reference_price_from": _safe_float(row["price_from"]),
                        "reference_price_to": _safe_float(row["price_to"]),
                        "discount_pct": _safe_float(row["discount_pct"]),
                        "availability_raw": row["availability_raw"],
                        "product_url": row["product_url"],
                    }
                )

            opportunities.append(
                {
                    "category": str(category),
                    "active_ingredient": str(active_ingredient),
                    "opportunity_priority": priority,
                    "out_of_stock_skus": int(len(group)),
                    "competitor_in_stock_alternatives": alternatives_available,
                    "avg_reference_price_from": avg_price_from,
                    "avg_reference_price_to": avg_price_to,
                    "avg_discount_pct_before_stockout": avg_discount_pct,
                    "products": products_list,
                }
            )

        # Sort by priority (HIGH first), then out_of_stock_skus desc, then avg_reference_price_to desc
        opportunities.sort(
            key=lambda item: (
                0 if item["opportunity_priority"] == "HIGH" else 1,
                -item["out_of_stock_skus"],
                -(item["avg_reference_price_to"] or 0.0),
            )
        )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_catalog_skus": total_skus,
            "in_stock_skus": in_stock_count,
            "out_of_stock_skus": oos_count,
            "stockout_rate_pct": stockout_rate,
            "unique_active_ingredients_affected": (
                int(oos_df["active_ingredient"].nunique()) if not oos_df.empty else 0
            ),
            "avg_reference_price_from_oos": (
                _safe_float(oos_df["price_from"].mean()) if not oos_df.empty else None
            ),
            "avg_reference_price_to_oos": (
                _safe_float(oos_df["price_to"].mean()) if not oos_df.empty else None
            ),
            "high_priority_opportunities": sum(
                1 for item in opportunities if item["opportunity_priority"] == "HIGH"
            ),
        },
        "by_category": category_summary,
        "opportunities_by_active_ingredient": opportunities,
    }

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Generated stockout report with %d out-of-stock SKUs across %d active ingredients -> %s",
        oos_count,
        len(opportunities),
        out_file,
    )
    return report
