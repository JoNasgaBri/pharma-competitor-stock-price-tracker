"""Relational SQLite persistence layer with idempotent daily loads.

Persists the cleaned pharmacy catalog into ``data/pharma_catalog.db`` with
``sku`` defined as ``PRIMARY KEY`` and uses ``INSERT OR IGNORE`` to guarantee
idempotency across repeated daily executions.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pharma_catalog (
    sku TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    active_ingredient TEXT,
    brand TEXT,
    category TEXT,
    dosage_raw TEXT,
    dosage_mg REAL,
    package_units INTEGER,
    package_form TEXT,
    volume_ml REAL,
    weight_g REAL,
    price_from REAL,
    price_to REAL,
    discount_pct REAL,
    price_per_unit REAL,
    installment_count INTEGER,
    installment_value REAL,
    is_in_stock INTEGER NOT NULL CHECK (is_in_stock IN (0, 1)),
    availability_raw TEXT,
    product_url TEXT NOT NULL,
    scraped_at TEXT NOT NULL
);
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_pharma_is_in_stock ON pharma_catalog (is_in_stock);",
    "CREATE INDEX IF NOT EXISTS idx_pharma_category ON pharma_catalog (category);",
    "CREATE INDEX IF NOT EXISTS idx_pharma_active_ingredient ON pharma_catalog (active_ingredient);",
]

INSERT_OR_IGNORE_SQL = """
INSERT OR IGNORE INTO pharma_catalog (
    sku,
    product_name,
    active_ingredient,
    brand,
    category,
    dosage_raw,
    dosage_mg,
    package_units,
    package_form,
    volume_ml,
    weight_g,
    price_from,
    price_to,
    discount_pct,
    price_per_unit,
    installment_count,
    installment_value,
    is_in_stock,
    availability_raw,
    product_url,
    scraped_at
) VALUES (
    :sku,
    :product_name,
    :active_ingredient,
    :brand,
    :category,
    :dosage_raw,
    :dosage_mg,
    :package_units,
    :package_form,
    :volume_ml,
    :weight_g,
    :price_from,
    :price_to,
    :discount_pct,
    :price_per_unit,
    :installment_count,
    :installment_value,
    :is_in_stock,
    :availability_raw,
    :product_url,
    :scraped_at
);
"""


def _to_db_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return int(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def init_db(db_path: Path | str = Path("data/pharma_catalog.db")) -> None:
    """Create the SQLite database file, table schema, and analytical indexes."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        for index_sql in CREATE_INDEXES_SQL:
            conn.execute(index_sql)
        conn.commit()


def save_catalog_to_db(
    cleaned_df: pd.DataFrame,
    db_path: Path | str = Path("data/pharma_catalog.db"),
) -> dict[str, int]:
    """Idempotently load cleaned catalog rows into SQLite using INSERT OR IGNORE."""
    path = Path(db_path)
    init_db(path)

    rows: list[dict[str, Any]] = []
    for record in cleaned_df.to_dict(orient="records"):
        sanitized = {k: _to_db_value(v) for k, v in record.items()}
        sanitized["is_in_stock"] = int(bool(record["is_in_stock"]))
        rows.append(sanitized)

    with sqlite3.connect(path) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM pharma_catalog").fetchone()[0]
        conn.executemany(INSERT_OR_IGNORE_SQL, rows)
        conn.commit()
        after_count = conn.execute("SELECT COUNT(*) FROM pharma_catalog").fetchone()[0]

    inserted = int(after_count - before_count)
    ignored = int(len(rows) - inserted)
    logger.info(
        "SQLite load complete (%s): %d inserted, %d ignored (idempotent), %d total rows",
        path,
        inserted,
        ignored,
        after_count,
    )
    return {
        "inserted": inserted,
        "ignored": ignored,
        "total_rows": int(after_count),
    }


def fetch_stockout_summary(
    db_path: Path | str = Path("data/pharma_catalog.db"),
) -> list[dict[str, Any]]:
    """Query out-of-stock products grouped by category directly from SQLite."""
    query = """
        SELECT
            category,
            COUNT(*) AS total_skus,
            SUM(CASE WHEN is_in_stock = 0 THEN 1 ELSE 0 END) AS out_of_stock_skus,
            ROUND(AVG(CASE WHEN is_in_stock = 0 THEN price_to END), 2) AS avg_oos_price_to
        FROM pharma_catalog
        GROUP BY category
        ORDER BY out_of_stock_skus DESC, category ASC;
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]
