🤖 Web Automation Data Extractor

A resilient browser-automation tool built with Playwright that logs into a site, waits for the page to genuinely finish rendering, locates specific UI elements by exact text match, and extracts structured data into a clean CSV report — plus a full-page screenshot for an audit trail.

Runs against saucedemo.com, a public Sauce Labs demo site built specifically for test-automation practice, using its publicly documented demo credentials. Safe to run and share.

Why this is harder than it looks

Naive automation scripts break constantly because they assume: a page is "ready" as soon as load fires, a CSS selector will always exist, and text matching won't produce duplicate matches. Real pages violate all three assumptions. This project handles each one directly:

Render polling, not just load events — waits for a meaningful amount of visible text on the page, since modern client-side-rendered pages often fire load/networkidle well before their real content appears
Multi-selector fallback — login fields are located by trying several reasonable selector candidates in order, since markup varies between sites
De-duplicated exact-text matching — a naive element.innerText === target check often matches both a wrapper <div> and the <span> inside it. This tool walks the DOM and keeps only the innermost match, avoiding false duplicate detections
Retry-safe clicking — falls back to a raw JavaScript click if Playwright's normal click is intercepted by an overlay or animation

Features

Logs in with resilient, multi-selector field detection
Waits for real page render before interacting with content
Extracts structured product data (name, description, price) to CSV
Exact-match element detection utility, demonstrated on a live click
Full-page screenshot capture

Tech Stack

Python 3, asyncio
Playwright (async API) — browser automation
CSV — structured export

Installation

git clone https://github.com/uhddis/web-automation-extractor.git
cd web-automation-extractor
pip install -r requirements.txt
playwright install chromium

Usage

python web_automation_extractor.py

This will:

Log into the demo site
Extract all product data from the inventory page
Save it to output/extracted_products.csv
Save a full-page screenshot to output/inventory_page.png
Demonstrate the exact-match detection helper by finding and clicking a specific product's "Add to cart" button

Adapting This for Your Own Use Case

Swap BASE_URL and the login selectors for your target site
Replace extract_products() with your own extraction logic for whatever structured data you need
The find_exact_text_container() helper is reusable for any scenario where you need to reliably locate one specific element among visually similar ones

Future Improvements

Add configurable retry/backoff for navigation failures
Support headless vs. headed mode via command-line flag
Add structured logging instead of print statements
Parallelize extraction across multiple pages/tabs

License
This project is licensed under the MIT License — see the LICENSE file for details.
