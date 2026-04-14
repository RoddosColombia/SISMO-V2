"""
CLI runner for the audit engine.

Usage:
    cd backend
    python -m services.audit.run_audit [--no-cache] [--output report.html]

Fetches all journals from Alegra, runs 9 validation rules, generates HTML triage dashboard.
"""
import asyncio
import argparse
import sys
from pathlib import Path


async def main(use_cache: bool = True, output: str = "audit_report.html"):
    from services.audit.fetch import fetch_all_journals
    from services.audit.classify import audit_all_journals
    from services.audit.report import generate_report_html

    print("=== SISMO Audit Engine ===")
    print()

    # Step 1: Fetch
    print("Step 1: Fetching journals from Alegra...")
    journals = await fetch_all_journals(use_cache=use_cache)
    print(f"  Fetched {len(journals)} journals")
    if not journals:
        print("  ERROR: No journals found. Check Alegra credentials.")
        sys.exit(1)

    # Step 2: Classify
    print("Step 2: Running 9 validation rules...")
    classifications = audit_all_journals(journals)

    # Step 3: Report
    total = len(classifications)
    with_issues = sum(1 for c in classifications if c.has_issues)
    high = sum(1 for c in classifications if c.max_severity and c.max_severity.value == "HIGH")
    medium = sum(1 for c in classifications if c.max_severity and c.max_severity.value == "MEDIUM")
    low = sum(1 for c in classifications if c.max_severity and c.max_severity.value == "LOW")

    print(f"  Total journals: {total}")
    print(f"  With issues: {with_issues} ({round(with_issues/total*100, 1)}%)")
    print(f"  HIGH severity: {high}")
    print(f"  MEDIUM severity: {medium}")
    print(f"  LOW severity: {low}")
    print(f"  Clean: {total - with_issues}")

    # Generate HTML
    output_path = Path(output)
    print(f"\nStep 3: Generating HTML report -> {output_path}")
    generate_report_html(classifications, str(output_path))
    print(f"  Report saved to {output_path.absolute()}")

    # Summary by type
    type_counts: dict[str, int] = {}
    for c in classifications:
        type_counts[c.inferred_type] = type_counts.get(c.inferred_type, 0) + 1
    print(f"\nType distribution:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

    # Top findings
    all_findings = []
    for c in classifications:
        all_findings.extend(c.findings)
    rule_counts: dict[str, int] = {}
    for f in all_findings:
        rule_counts[f.rule] = rule_counts.get(f.rule, 0) + 1
    if rule_counts:
        print(f"\nFindings by rule:")
        for rule, count in sorted(rule_counts.items(), key=lambda x: -x[1]):
            print(f"  {rule}: {count}")

    print(f"\n=== DONE. Open {output_path} in your browser. ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SISMO Audit Engine")
    parser.add_argument("--no-cache", action="store_true", help="Force re-fetch from Alegra (ignore cache)")
    parser.add_argument("--output", default="audit_report.html", help="Output HTML file path")
    args = parser.parse_args()
    asyncio.run(main(use_cache=not args.no_cache, output=args.output))
