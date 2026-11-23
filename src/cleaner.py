"""Data cleaning, regex attribute extraction, and deduplication using Pandas.

Reads raw JSON records produced by ``src/scraper.py``, standardizes Brazilian
and international currency values, extracts installment terms, computes real
discount percentages, parses dosage (mg) and package presentation units via
regular expressions, maps availability strings to a boolean ``is_in_stock``
flag, deduplicates by SKU/URL, and exports ``data/cleaned_pharma_catalog.csv``
with ``utf-8-sig`` encoding for direct spreadsheet compatibility.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Matches numeric price tokens such as "1.099,00", "11,49", "12.90", "89"
_PRICE_PATTERN = re.compile(r"(?:R\$|\$)?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{1,2}|\d+(?:\.\d{1,2})?)")

# Matches installment phrases such as "ou 3x de R$ 29,97 sem juros"
_INSTALLMENT_PATTERN = re.compile(
    r"(\d{1,2})\s*x\s*(?:de\s*)?(?:R\$|\$)?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{1,2}|\d+(?:\.\d{1,2})?)",
    flags=re.IGNORECASE,
)

# Dosage concentration patterns: mg/ml, mg, mcg, UI, or small-dose g (<= 10g)
_CONCENTRATION_MG_ML_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*mg\s*/\s*ml\b", flags=re.IGNORECASE
)
_DOSAGE_MG_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*mg\b", flags=re.IGNORECASE)
_DOSAGE_MCG_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*mcg\b", flags=re.IGNORECASE)
_DOSAGE_UI_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*ui\b", flags=re.IGNORECASE)
_MASS_G_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*g\b", flags=re.IGNORECASE)
_VOLUME_ML_PATTERN = re.compile(
    r"(?<!/)\b(\d+(?:[.,]\d+)?)\s*ml\b", flags=re.IGNORECASE
)

# Package unit count patterns (pills, capsules, sachets, units, etc.)
_PACKAGE_UNITS_PATTERN = re.compile(
    r"(?:c/\s*|com\s+|-\s*)?(\d+)\s*"
    r"(comprimidos?(?:\s+revestidos?|\s+efervescentes?)?|"
    r"c[aá]psulas?(?:\s+gelatinosas?|\s+duras?|\s+moles?)?|"
    r"unidades?|"
    r"sach[eê]s?|"
    r"flaconetes?|"
    r"dr[aá]geas?|"
    r"ampolas?|"
    r"pastilhas?|"
    r"tabletes?)\b",
    flags=re.IGNORECASE,
)

_OUT_OF_STOCK_KEYWORDS = (
    "indisponivel",
    "avise-me",
    "esgotado",
    "fora de estoque",
    "sem estoque",
    "out of stock",
    "unavailable",
)

_IN_STOCK_KEYWORDS = (
    "em estoque",
    "disponivel",
    "in stock",
    "pronta entrega",
)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(ascii_only.lower().split())


def _to_float_br(number_token: str) -> float:
    """Convert a Brazilian ('1.099,90' / '14,50') or dot-decimal ('14.50') token."""
    cleaned = number_token.strip()
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def parse_price(raw_price: Any) -> float | None:
    """Clean currency symbols and formatting from a raw price string."""
    if raw_price is None or (isinstance(raw_price, float) and pd.isna(raw_price)):
        return None
    if isinstance(raw_price, (int, float)):
        return round(float(raw_price), 2)

    text = str(raw_price).strip()
    if not text:
        return None

    # Ignore installment fragments if accidentally concatenated in the same string
    cash_portion = re.split(r"\bou\s+\d+\s*x\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    match = _PRICE_PATTERN.search(cash_portion)
    if not match:
        return None
    return round(_to_float_br(match.group(1)), 2)


def parse_installment(raw_installment: Any) -> tuple[int | None, float | None]:
    """Extract (installment_count, installment_value) from strings like 'ou 3x de R$ 29,97'."""
    if raw_installment is None or (
        isinstance(raw_installment, float) and pd.isna(raw_installment)
    ):
        return None, None
    match = _INSTALLMENT_PATTERN.search(str(raw_installment))
    if not match:
        return None, None
    return int(match.group(1)), round(_to_float_br(match.group(2)), 2)


def compute_discount_pct(price_from: float | None, price_to: float | None) -> float:
    """Calculate real percentage discount: ((price_from - price_to) / price_from) * 100."""
    if price_from is None or price_to is None:
        return 0.0
    if pd.isna(price_from) or pd.isna(price_to) or price_from <= 0:
        return 0.0
    if price_to >= price_from:
        return 0.0
    return round(((price_from - price_to) / price_from) * 100.0, 2)


def extract_dosage_and_presentation(title: str) -> dict[str, Any]:
    """Extract structured dosage (normalized to mg), net volume/weight, and package units."""
    text = title or ""
    dosage_mg: float | None = None
    dosage_raw: str | None = None
    volume_ml: float | None = None
    weight_g: float | None = None
    package_units: int | None = None
    package_form: str | None = None

    # 1. Extract package unit count & pharmaceutical form first (helps disambiguate '1g' vs '300g')
    unit_match = _PACKAGE_UNITS_PATTERN.search(text)
    if unit_match:
        package_units = int(unit_match.group(1))
        package_form = _normalize_text(unit_match.group(2)).split()[0]

    # 2. Extract volume in ml (excluding '/ml' from 'mg/ml')
    vol_match = _VOLUME_ML_PATTERN.search(text)
    if vol_match:
        volume_ml = _to_float_br(vol_match.group(1))

    # 3. Extract dosage concentration in priority order
    if m := _CONCENTRATION_MG_ML_PATTERN.search(text):
        dosage_mg = round(_to_float_br(m.group(1)), 4)
        dosage_raw = f"{m.group(1)}mg/ml"
    elif m := _DOSAGE_MG_PATTERN.search(text):
        dosage_mg = round(_to_float_br(m.group(1)), 4)
        dosage_raw = f"{m.group(1)}mg"
    elif m := _DOSAGE_MCG_PATTERN.search(text):
        dosage_mg = round(_to_float_br(m.group(1)) / 1000.0, 6)
        dosage_raw = f"{m.group(1)}mcg"
    elif m := _DOSAGE_UI_PATTERN.search(text):
        dosage_raw = f"{m.group(1)}UI"

    # 4. Handle grams ('g'): small values (<= 10g) represent active dosage (e.g., Dipirona 1g);
    #    larger values (> 10g) represent net container weight (e.g., Protetor Solar 40g, Creatina 300g).
    g_match = _MASS_G_PATTERN.search(text)
    if g_match:
        g_val = _to_float_br(g_match.group(1))
        if g_val <= 10.0 and dosage_mg is None:
            dosage_mg = round(g_val * 1000.0, 4)
            dosage_raw = f"{g_match.group(1)}g"
        else:
            weight_g = g_val

    if package_form is None:
        if volume_ml is not None:
            package_form = "ml"
        elif weight_g is not None:
            package_form = "g"

    return {
        "dosage_raw": dosage_raw,
        "dosage_mg": dosage_mg,
        "package_units": package_units,
        "package_form": package_form,
        "volume_ml": volume_ml,
        "weight_g": weight_g,
    }


def parse_availability(availability_raw: Any) -> bool:
    """Map raw Portuguese/English availability labels to a boolean ``is_in_stock`` flag."""
    normalized = _normalize_text(str(availability_raw) if availability_raw is not None else "")
    if not normalized:
        return False
    if any(token in normalized for token in _OUT_OF_STOCK_KEYWORDS):
        return False
    if any(token in normalized for token in _IN_STOCK_KEYWORDS):
        return True
    return False


def load_raw_products(raw_path: Path | str) -> list[dict[str, Any]]:
    """Load raw records from the JSON file saved by ``src/scraper.py``."""
    payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "products" in payload:
        return list(payload["products"])
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unsupported raw JSON structure in {raw_path}")


def clean_catalog(
    raw_records: list[dict[str, Any]],
    output_csv_path: Path | str | None = Path("data/cleaned_pharma_catalog.csv"),
) -> pd.DataFrame:
    """Transform raw pharmacy listings into a structured, deduplicated DataFrame."""
    if not raw_records:
        raise ValueError("No raw product records provided to cleaner.")

    df = pd.DataFrame(raw_records)
    initial_count = len(df)

    # Normalize key text columns
    df["sku"] = df["sku"].astype(str).str.strip().str.upper()
    df["product_name"] = df["product_name"].astype(str).str.strip()
    df["product_url"] = df["product_url"].astype(str).str.strip()
    df["active_ingredient"] = (
        df.get("active_ingredient", pd.Series(dtype="object"))
        .fillna("Não informado")
        .astype(str)
        .str.strip()
    )
    df["brand"] = (
        df.get("brand", pd.Series(dtype="object"))
        .fillna("Não informado")
        .astype(str)
        .str.strip()
    )
    df["category"] = (
        df.get("category", pd.Series(dtype="object"))
        .fillna("Geral")
        .astype(str)
        .str.strip()
    )
    df["availability_raw"] = (
        df.get("availability_raw", pd.Series(dtype="object"))
        .fillna("Indisponível")
        .astype(str)
        .str.strip()
    )

    # Deduplicate by SKU and product URL
    df = df.drop_duplicates(subset=["sku"], keep="first")
    df = df.drop_duplicates(subset=["product_url"], keep="first").reset_index(drop=True)
    duplicates_removed = initial_count - len(df)
    logger.info(
        "Deduplication complete: %d raw -> %d unique SKUs (%d duplicates removed)",
        initial_count,
        len(df),
        duplicates_removed,
    )

    # Price cleaning & real discount computation
    df["price_from"] = df["price_from_raw"].apply(parse_price)
    df["price_to"] = df["price_to_raw"].apply(parse_price)
    df["discount_pct"] = [
        compute_discount_pct(p_from, p_to)
        for p_from, p_to in zip(df["price_from"], df["price_to"])
    ]

    # Parse installment options (parcelado vs à vista)
    installments = df.get("installment_raw", pd.Series([None] * len(df))).apply(
        parse_installment
    )
    df["installment_count"] = pd.Series(
        [pair[0] for pair in installments], dtype="Int64"
    )
    df["installment_value"] = pd.Series(
        [pair[1] for pair in installments], dtype="float64"
    )

    # Regex extraction of dosage & presentation
    extracted = df["product_name"].apply(extract_dosage_and_presentation)
    extracted_df = pd.DataFrame(extracted.tolist())
    df["dosage_raw"] = extracted_df["dosage_raw"]
    df["dosage_mg"] = pd.to_numeric(extracted_df["dosage_mg"], errors="coerce")
    df["package_units"] = pd.Series(extracted_df["package_units"], dtype="Int64")
    df["package_form"] = extracted_df["package_form"]
    df["volume_ml"] = pd.to_numeric(extracted_df["volume_ml"], errors="coerce")
    df["weight_g"] = pd.to_numeric(extracted_df["weight_g"], errors="coerce")

    # Unit price (R$ per pill/capsule/unit) when countable presentation is available
    df["price_per_unit"] = df.apply(
        lambda row: (
            round(row["price_to"] / row["package_units"], 4)
            if pd.notna(row["price_to"])
            and pd.notna(row["package_units"])
            and row["package_units"] > 0
            else None
        ),
        axis=1,
    )

    # Availability boolean flag
    df["is_in_stock"] = df["availability_raw"].apply(parse_availability).astype(bool)

    ordered_columns = [
        "sku",
        "product_name",
        "active_ingredient",
        "brand",
        "category",
        "dosage_raw",
        "dosage_mg",
        "package_units",
        "package_form",
        "volume_ml",
        "weight_g",
        "price_from",
        "price_to",
        "discount_pct",
        "price_per_unit",
        "installment_count",
        "installment_value",
        "is_in_stock",
        "availability_raw",
        "product_url",
        "scraped_at",
    ]
    cleaned_df = df[ordered_columns].copy()

    if output_csv_path is not None:
        out_path = Path(output_csv_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        logger.info("Exported cleaned catalog (%d rows) to %s", len(cleaned_df), out_path)

    return cleaned_df


def clean_from_file(
    raw_path: Path | str = Path("data/raw_products.json"),
    output_csv_path: Path | str = Path("data/cleaned_pharma_catalog.csv"),
) -> pd.DataFrame:
    """Convenience wrapper to read raw JSON and write cleaned CSV."""
    raw_records = load_raw_products(raw_path)
    return clean_catalog(raw_records, output_csv_path=output_csv_path)
