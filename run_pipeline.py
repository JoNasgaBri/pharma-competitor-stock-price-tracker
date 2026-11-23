"""End-to-end orchestration CLI for the Pharmacy Price & Out-of-Stock Tracker.

Runs the 4-stage pipeline:
1. Modular HTTP scraping with pagination and rate-limiting -> ``data/raw_products.json``
2. Pandas & Regex cleaning, dosage/unit extraction, deduplication -> ``data/cleaned_pharma_catalog.csv``
3. Competitive stockout intelligence -> ``data/stockout_opportunities.json``
4. Idempotent relational persistence in SQLite -> ``data/pharma_catalog.db``
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.analytics import generate_stockout_report
from src.cleaner import clean_from_file
from src.database import save_catalog_to_db
from src.report import generate_html_report
from src.sandbox_server import SandboxPharmacyServer
from src.scraper import DEFAULT_CATEGORY_PATHS, scrape_catalog


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pharmacy Competitor Stock & Price Tracker Pipeline"
    )
    parser.add_argument(
        "--source",
        choices=["sandbox", "live", "cached"],
        default="sandbox",
        help=(
            "Data source mode: 'sandbox' starts a local paginated HTML pharmacy server "
            "(default), 'live' scrapes --base-url, 'cached' skips scraping and uses "
            "existing data/raw_products.json."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Target base URL when --source=live (e.g. https://farmacia-exemplo.com.br).",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=None,
        help="Category paths or URLs to scrape (defaults to Genéricos, Vitaminas, Dermocosméticos).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Output directory for JSON, CSV, and SQLite artifacts (default: data).",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=1.0,
        help="Minimum delay in seconds between paginated HTTP requests (default: 1.0).",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=2.0,
        help="Maximum delay in seconds between paginated HTTP requests (default: 2.0).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def run_pipeline(
    source: str = "sandbox",
    base_url: str | None = None,
    categories: list[str] | None = None,
    data_dir: Path = Path("data"),
    min_delay: float = 1.0,
    max_delay: float = 2.0,
) -> dict[str, object]:
    """Execute all 4 stages of the pharmacy catalog & stockout pipeline."""
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_path = data_dir / "raw_products.json"
    cleaned_csv_path = data_dir / "cleaned_pharma_catalog.csv"
    opportunities_path = data_dir / "stockout_opportunities.json"
    html_report_path = data_dir / "stockout_report.html"
    db_path = data_dir / "pharma_catalog.db"

    # Stage 1: Modular HTTP Scraping with Pagination & Rate-Limiting
    if source == "sandbox":
        with SandboxPharmacyServer() as server:
            raw_records = scrape_catalog(
                base_url=server.base_url,
                category_paths=categories or DEFAULT_CATEGORY_PATHS,
                output_path=raw_path,
                min_delay=min_delay,
                max_delay=max_delay,
            )
    elif source == "live":
        if not base_url:
            raise ValueError("--base-url is required when --source=live.")
        raw_records = scrape_catalog(
            base_url=base_url,
            category_paths=categories or DEFAULT_CATEGORY_PATHS,
            output_path=raw_path,
            min_delay=min_delay,
            max_delay=max_delay,
        )
    elif source == "cached":
        if not raw_path.exists():
            raise FileNotFoundError(
                f"Cached raw file not found at {raw_path}. Run with --source=sandbox first."
            )
        raw_records = None
    else:
        raise ValueError(f"Unsupported source mode: {source}")

    # Stage 2: Cleaning, Regex Extraction, Deduplication & CSV Export (utf-8-sig)
    cleaned_df = clean_from_file(raw_path=raw_path, output_csv_path=cleaned_csv_path)

    # Stage 3: Competitive Intelligence & Visual Stockout Report
    report = generate_stockout_report(cleaned_df=cleaned_df, output_path=opportunities_path)
    generate_html_report(
        cleaned_df=cleaned_df,
        report_data=report,
        output_path=html_report_path,
    )

    # Stage 4: Idempotent Relational Persistence in SQLite
    db_stats = save_catalog_to_db(cleaned_df=cleaned_df, db_path=db_path)

    summary = report["summary"]
    print("\n" + "=" * 72)
    print("PHARMA COMPETITOR STOCK & PRICE TRACKER - PIPELINE SUMMARY")
    print("=" * 72)
    if raw_records is not None:
        print(f"Raw records extracted : {len(raw_records)}")
    print(f"Unique SKUs cleaned   : {summary['total_catalog_skus']}")
    print(f"In-stock SKUs         : {summary['in_stock_skus']}")
    print(
        f"Out-of-stock SKUs     : {summary['out_of_stock_skus']} "
        f"({summary['stockout_rate_pct']}% stockout rate)"
    )
    print(
        f"High-priority alerts  : {summary['high_priority_opportunities']} "
        f"active ingredients"
    )
    print(
        f"SQLite persistence    : inserted={db_stats['inserted']}, "
        f"ignored={db_stats['ignored']}, total_rows={db_stats['total_rows']}"
    )
    print("-" * 72)
    print("Top Stockout Opportunities (Priority / Active Ingredient / Avg Cash Price):")
    for opp in report["opportunities_by_active_ingredient"][:5]:
        avg_price = (
            f"R$ {opp['avg_reference_price_to']:.2f}"
            if opp["avg_reference_price_to"] is not None
            else "N/A"
        )
        print(
            f"  [{opp['opportunity_priority']:6s}] {opp['active_ingredient']} "
            f"({opp['category']}) | {opp['out_of_stock_skus']} OOS | "
            f"Competitor alt: {opp['competitor_in_stock_alternatives']} | Ref: {avg_price}"
        )
    print("-" * 72)
    print("Artifacts written:")
    print(f"  - {raw_path}")
    print(f"  - {cleaned_csv_path}")
    print(f"  - {opportunities_path}")
    print(f"  - {html_report_path}")
    print(f"  - {db_path}")
    print("=" * 72 + "\n")

    return {
        "cleaned_rows": len(cleaned_df),
        "report": report,
        "db_stats": db_stats,
    }


def main() -> None:
    args = parse_args()
    configure_logging(verbose=args.verbose)
    run_pipeline(
        source=args.source,
        base_url=args.base_url,
        categories=args.categories,
        data_dir=args.data_dir,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
    )


if __name__ == "__main__":
    main()
