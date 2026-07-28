#!/usr/bin/env python3
"""Quality gate for marketmore.org — checks links, viewport, SEO, assets, structure."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SITE_DIR = Path(__file__).parent
HTML_PAGES = ["index.html", "our-solutions.html", "more-services.html", "contact.html"]
REPORT_PATH = SITE_DIR / "quality-report.json"

CSS_MAX_KB = 50
IMG_MAX_KB = 200

def read(name):
    return (SITE_DIR / name).read_text(encoding="utf-8")

def exists(relpath):
    return (SITE_DIR / relpath).is_file()

def check_internal_links():
    """Check that all internal .html hrefs point to existing files."""
    issues = []
    for page in HTML_PAGES:
        html = read(page)
        hrefs = re.findall(r'href="([^"#?]+)"', html)
        for href in hrefs:
            if href.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            if href.startswith("#"):
                continue
            target = href.split("?")[0].split("#")[0]
            if not exists(target):
                issues.append(f"{page}: broken link → {href}")
    return issues

def check_viewport():
    """Every HTML page must have a viewport meta tag."""
    issues = []
    for page in HTML_PAGES:
        html = read(page)
        if not re.search(r'<meta\s+name="viewport"', html):
            issues.append(f"{page}: missing viewport meta tag")
    return issues

def check_asset_sizes():
    """Warn if CSS > 50KB or any image > 200KB."""
    issues = []
    # CSS
    css_path = SITE_DIR / "style.css"
    if css_path.is_file():
        size_kb = css_path.stat().st_size / 1024
        if size_kb > CSS_MAX_KB:
            issues.append(f"style.css: {size_kb:.1f}KB exceeds {CSS_MAX_KB}KB budget")
    # Images
    img_dir = SITE_DIR / "images"
    if img_dir.is_dir():
        for f in img_dir.iterdir():
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"):
                size_kb = f.stat().st_size / 1024
                if size_kb > IMG_MAX_KB:
                    issues.append(f"images/{f.name}: {size_kb:.1f}KB exceeds {IMG_MAX_KB}KB budget")
    return issues

def check_seo():
    """Every page needs <title>, <meta description>, <link canonical>, <h1>."""
    issues = []
    for page in HTML_PAGES:
        html = read(page)
        if not re.search(r"<title>[^<]+</title>", html):
            issues.append(f"{page}: missing <title>")
        if not re.search(r'<meta\s+name="description"\s+content="[^"]+"', html):
            issues.append(f"{page}: missing meta description")
        if not re.search(r'<link\s+rel="canonical"', html):
            issues.append(f"{page}: missing canonical link")
        if not re.search(r"<h1[>\s]", html):
            issues.append(f"{page}: missing <h1>")
    return issues

def check_structure():
    """Verify lang attr, <main> landmark, no broken img src."""
    issues = []
    for page in HTML_PAGES:
        html = read(page)
        if not re.search(r'<html\s+lang="en"', html):
            issues.append(f"{page}: missing lang=\"en\" on <html>")
        if not re.search(r"<main[>\s]", html):
            issues.append(f"{page}: missing <main> landmark")
        # Check img srcs
        img_srcs = re.findall(r'<img[^>]+src="([^"]+)"', html)
        for src in img_srcs:
            if src.startswith(("http://", "https://", "data:")):
                continue
            if not exists(src):
                issues.append(f"{page}: broken img src → {src}")
    return issues

def run_lighthouse():
    """Run Lighthouse CLI if available, capture scores. Return scores dict or None."""
    for cmd in [["npx", "lighthouse", "--version"], ["lighthouse", "--version"]]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            # Found it — now run on the live site
            lh_cmd = ["npx", "lighthouse"] if cmd[0] == "npx" else ["lighthouse"]
            result = subprocess.run(
                lh_cmd + [
                    "https://marketmore.org",
                    "--output=json",
                    "--output-path=stdout",
                    "--chrome-flags=--headless --no-sandbox",
                    "--only-categories=accessibility,performance,seo",
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                cats = data.get("categories", {})
                return {
                    "accessibility": round(cats.get("accessibility", {}).get("score", 0) * 100),
                    "performance": round(cats.get("performance", {}).get("score", 0) * 100),
                    "seo": round(cats.get("seo", {}).get("score", 0) * 100),
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            continue
    return None

def main():
    report = {"pages": HTML_PAGES, "checks": {}, "summary": {}}

    # Run checks
    checks = {
        "internal_links": check_internal_links(),
        "viewport": check_viewport(),
        "asset_sizes": check_asset_sizes(),
        "seo": check_seo(),
        "structure": check_structure(),
    }

    for name, issues in checks.items():
        report["checks"][name] = {"pass": len(issues) == 0, "issues": issues}

    # Lighthouse
    scores = run_lighthouse()
    if scores:
        report["checks"]["lighthouse"] = {
            "pass": scores["accessibility"] >= 95 and scores["seo"] >= 95 and scores["performance"] >= 85,
            "scores": scores,
        }
    else:
        report["checks"]["lighthouse"] = {"pass": None, "note": "Lighthouse CLI not available — skipped"}

    # Summary
    critical_pass = all(c["pass"] for name, c in report["checks"].items() if c["pass"] is not None)
    total_issues = sum(len(c.get("issues", [])) for c in report["checks"].values())
    report["summary"] = {
        "all_critical_checks_pass": critical_pass,
        "total_issues": total_issues,
    }

    # Save JSON
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")

    # Print human-readable summary
    print("=" * 60)
    print("  MARKETMORE.ORG — Quality Gate Report")
    print("=" * 60)
    for name, check in report["checks"].items():
        status = "PASS" if check["pass"] is True else ("SKIP" if check["pass"] is None else "FAIL")
        icon = "✅" if status == "PASS" else ("⏭️" if status == "SKIP" else "❌")
        print(f"\n{icon} {name}: {status}")
        for issue in check.get("issues", []):
            print(f"   • {issue}")
        if "scores" in check:
            for k, v in check["scores"].items():
                print(f"   • {k}: {v}")
        if "note" in check:
            print(f"   ({check['note']})")

    print(f"\n{'=' * 60}")
    if critical_pass:
        print("✅ All critical checks PASSED.")
    else:
        print("❌ Some checks FAILED. Fix issues above.")
    print(f"Report saved to: {REPORT_PATH}")
    print("=" * 60)

    return 0 if critical_pass else 1

if __name__ == "__main__":
    sys.exit(main())
