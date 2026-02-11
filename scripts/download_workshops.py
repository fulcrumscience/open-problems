#!/usr/bin/env python3
"""Download additional workshop PDFs from DOE BER and NIH.

Scrapes the DOE BER workshop reports listing page for PDF links,
downloads them to data/workshops/, and creates YAML sidecar files.
Skips files that already exist.

Usage:
    python scripts/download_workshops.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKSHOPS_DIR = ROOT / "data" / "workshops"

DOE_BASE = "https://science.osti.gov"

# Additional DOE BER workshop reports to download (beyond already-collected 8).
# Manually curated from the BER listing page — focused on biology/bioenergy topics.
DOE_REPORTS = [
    {
        "source_id": "doe-les-workshop-2023",
        "title": "Atmospheric System Research LES Workshop Report",
        "organization": "DOE ASR",
        "date_published": "2023-09",
        "url": "https://science.osti.gov/ber/Community-Resources/BER-Workshop-Reports",
        "pdf_path": "/-/media/ber/pdf/community-resources/2023/Atmospheric_System_Research_LES_Workshop_Report_Sept23.pdf",
    },
    {
        "source_id": "doe-mountain-hydroclimate-2023",
        "title": "Understanding and Predictability of Integrated Mountain Hydroclimate",
        "organization": "DOE BER",
        "date_published": "2023-04",
        "url": "https://science.osti.gov/ber/Community-Resources/BER-Workshop-Reports",
        "pdf_path": "/-/media/ber/pdf/community-resources/2023/IMHC-Final-High-Res.pdf",
    },
    {
        "source_id": "doe-marine-aerosols-clouds-2024",
        "title": "Observing Marine Aerosols and Clouds from Ships 2024 Workshop Report",
        "organization": "DOE BER",
        "date_published": "2024-06",
        "url": "https://science.osti.gov/ber/Community-Resources/BER-Workshop-Reports",
        "pdf_path": "/-/media/ber/pdf/workshop-reports/2024/BER-ShipObservationsReport_final.pdf",
    },
    {
        "source_id": "doe-land-atmosphere-southeast-2024",
        "title": "Optimizing DOE Opportunities to Research Land-Atmosphere Interactions in the U.S. Southeast",
        "organization": "DOE BER",
        "date_published": "2024-10",
        "url": "https://science.osti.gov/ber/Community-Resources/BER-Workshop-Reports",
        "pdf_path": "/-/media/ber/pdf/workshop-reports/2024/DOE_SELARO_report_Final_Fast_Download.pdf",
    },
    {
        "source_id": "doe-climate-data-products-2024",
        "title": "Understanding Decision-Relevant Regional Climate Data Products Workshop",
        "organization": "DOE BER",
        "date_published": "2024-10",
        "url": "https://science.osti.gov/ber/Community-Resources/BER-Workshop-Reports",
        "pdf_path": "/-/media/ber/pdf/workshop-reports/2024/EESM_DRCDP_Workshop_Report-24-12-07-FNL.pdf",
    },
]

# NIH workshop reports — manually curated from NIH IC pages
NIH_REPORTS = [
    {
        "source_id": "nih-niaid-amr-2022",
        "title": "NIAID Workshop on Antimicrobial Resistance in One Health",
        "organization": "NIH/NIAID",
        "date_published": "2022",
        "url": "https://www.niaid.nih.gov/research/antimicrobial-resistance",
        "pdf_url": None,  # placeholder — requires manual download
    },
]


def download_report(report: dict, dry_run: bool = False) -> bool:
    """Download a single workshop report PDF and create YAML sidecar."""
    source_id = report["source_id"]
    pdf_dest = WORKSHOPS_DIR / f"{source_id}.pdf"
    yaml_dest = WORKSHOPS_DIR / f"{source_id}.yaml"

    if pdf_dest.exists():
        print(f"  SKIP {source_id} (already exists)")
        return False

    pdf_path = report.get("pdf_path")
    pdf_url = report.get("pdf_url")

    if not pdf_path and not pdf_url:
        print(f"  SKIP {source_id} (no PDF URL)")
        return False

    url = pdf_url or f"{DOE_BASE}{pdf_path}"

    if dry_run:
        print(f"  DRY RUN: would download {source_id} from {url}")
        return False

    print(f"  Downloading {source_id}...")
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            pdf_dest.write_bytes(resp.content)
            print(f"    Saved {pdf_dest.name} ({len(resp.content) / 1024 / 1024:.1f} MB)")
    except httpx.HTTPError as e:
        print(f"    FAILED: {e}")
        return False

    # Write YAML sidecar
    sidecar = {
        "source_id": source_id,
        "title": report["title"],
        "organization": report["organization"],
        "date_published": report["date_published"],
        "url": report["url"],
    }
    with open(yaml_dest, "w") as f:
        yaml.dump(sidecar, f, default_flow_style=False)

    return True


def main():
    parser = argparse.ArgumentParser(description="Download additional workshop PDFs")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    args = parser.parse_args()

    WORKSHOPS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Workshop directory: {WORKSHOPS_DIR}")
    existing = list(WORKSHOPS_DIR.glob("*.pdf"))
    print(f"Existing PDFs: {len(existing)}")

    downloaded = 0

    print("\n--- DOE BER Reports ---")
    for report in DOE_REPORTS:
        if download_report(report, args.dry_run):
            downloaded += 1

    print(f"\nDownloaded {downloaded} new workshop reports")
    total = len(list(WORKSHOPS_DIR.glob("*.pdf")))
    print(f"Total PDFs in workshops/: {total}")


if __name__ == "__main__":
    main()
