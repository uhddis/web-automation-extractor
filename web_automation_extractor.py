"""
Web Automation Data Extractor
--------------------------------
A resilient browser-automation tool built with Playwright that logs into a
site, waits for the page to genuinely finish rendering (not just fire a
"load" event), locates a specific UI element by exact text match while
correctly ignoring nested wrapper elements, and extracts structured data
into a clean CSV report.

This demonstrates patterns that matter for real-world scraping/automation
work, where pages render client-side and naive selectors are unreliable:

  - Multi-selector fallback for login fields (sites change their markup)
  - "Wait for real render" polling instead of trusting load events alone
  - Exact-match element detection that de-duplicates nested wrapper tags
    (e.g. a <div> whose only child is a <span> with the same text)
  - Retry-safe clicking (falls back to a raw JS click if a normal click
    is intercepted)
  - Structured extraction into CSV, plus a full-page screenshot for
    an audit trail

Runs against https://www.saucedemo.com — a public Sauce Labs demo site
built specifically for test-automation practice, with publicly documented
demo credentials. Safe to run and share.

Usage:
    python web_automation_extractor.py

Author: Siddharth
"""

import asyncio
import csv
import os

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.saucedemo.com"

# Publicly documented demo credentials for saucedemo.com — not a secret.
USERNAME = "standard_user"
PASSWORD = "secret_sauce"

HEADLESS = True
NAVIGATION_TIMEOUT = 30000
RENDER_WAIT_TIMEOUT = 15000
RENDER_POLL_INTERVAL_MS = 500
MIN_RENDERED_TEXT_LENGTH = 40

OUTPUT_CSV = os.path.join("output", "extracted_products.csv")
SCREENSHOT_PATH = os.path.join("output", "inventory_page.png")


# ============================================================
# HELPERS
# ============================================================

def section(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


async def visible(locator):
    try:
        return await locator.is_visible()
    except Exception:
        return False


async def page_text(page):
    try:
        return await page.locator("body").inner_text()
    except Exception:
        return ""


async def click_resilient(locator):
    """Tries a normal click; falls back to a raw JS click if intercepted."""
    try:
        await locator.click()
    except Exception:
        await locator.evaluate("(el) => el.click()")


async def wait_for_real_render(page, min_text_length=MIN_RENDERED_TEXT_LENGTH, timeout_ms=RENDER_WAIT_TIMEOUT):
    """
    Waits for the page to have a meaningful amount of visible text, rather
    than trusting a 'load' or 'networkidle' event alone — many modern pages
    render their real content client-side well after those fire.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass

    start = asyncio.get_event_loop().time()
    while True:
        body = await page_text(page)
        if len(body.strip()) >= min_text_length:
            return True

        elapsed_ms = (asyncio.get_event_loop().time() - start) * 1000
        if elapsed_ms >= timeout_ms:
            print("WARNING: page did not reach the expected render threshold in time.")
            return False

        await page.wait_for_timeout(RENDER_POLL_INTERVAL_MS)


# ============================================================
# LOGIN
# ============================================================

async def login(page, username, password):
    section("1. LOGIN")

    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT)
    await wait_for_real_render(page)

    # Multi-selector fallback: real-world sites rarely have one stable
    # selector for login fields, so try several reasonable candidates.
    username_selectors = ['input[name="user-name"]', 'input[id*="user" i]', 'input[placeholder*="username" i]']
    password_selectors = ['input[type="password"]', 'input[name="password"]']
    login_button_selectors = ['input[type="submit"]', 'button[type="submit"]', '#login-button']

    username_field = await _first_visible(page, username_selectors)
    password_field = await _first_visible(page, password_selectors)
    login_button = await _first_visible(page, login_button_selectors)

    if not (username_field and password_field and login_button):
        raise RuntimeError("Could not locate login form fields.")

    await username_field.fill(username)
    await password_field.fill(password)
    await click_resilient(login_button)

    await wait_for_real_render(page)

    if "inventory" not in page.url:
        raise RuntimeError(f"Login does not appear to have succeeded (URL: {page.url}).")

    print(f"✓ Logged in. Current URL: {page.url}")


async def _first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        if await visible(locator):
            return locator
    return None


# ============================================================
# EXACT-MATCH ELEMENT DETECTION
# ============================================================

async def find_exact_text_container(page, target_text, must_contain_selector=None):
    """
    Finds the smallest visible container whose text matches target_text
    exactly, correctly ignoring nested wrapper elements that report the
    same innerText as their only child (a common source of false
    duplicate matches in naive text-matching approaches).

    If must_contain_selector is given, only returns a container that also
    has at least one visible matching descendant (e.g. a button).
    """
    result = await page.evaluate(
        """
        (args) => {
            const target = args.target;
            const requiredSelector = args.requiredSelector;

            const normalize = (t) => (t || "").replace(/\\s+/g, " ").trim();
            const lower = (t) => normalize(t).toLowerCase();

            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden"
                    && rect.width > 0 && rect.height > 0;
            };

            const wanted = lower(target);
            const all = Array.from(document.querySelectorAll("*")).filter(isVisible);

            const exactMatches = all.filter(el => lower(el.innerText) === wanted);

            // Keep only the innermost match per block — exclude any match
            // that contains another match inside it (a wrapper, not a
            // second distinct element).
            const leafMatches = exactMatches.filter(
                el => !exactMatches.some(other => other !== el && el.contains(other))
            );

            for (const match of leafMatches) {
                let current = match;
                for (let level = 0; level < 8 && current; level++) {
                    if (!isVisible(current)) {
                        current = current.parentElement;
                        continue;
                    }

                    let ok = true;
                    if (requiredSelector) {
                        const found = Array.from(current.querySelectorAll(requiredSelector)).some(isVisible);
                        ok = found;
                    }

                    if (ok) {
                        const marker = "wae-target-" + Math.random().toString(36).slice(2);
                        current.setAttribute("data-wae-target", marker);
                        return { found: true, marker, text: current.innerText };
                    }

                    current = current.parentElement;
                }
            }

            return { found: false };
        }
        """,
        {"target": target_text, "requiredSelector": must_contain_selector},
    )

    if not result.get("found"):
        return None

    marker = result["marker"]
    return page.locator(f'[data-wae-target="{marker}"]').first


# ============================================================
# EXTRACT PRODUCT DATA
# ============================================================

async def extract_products(page):
    """
    Extracts structured product data (name, description, price) from the
    inventory page.
    """
    section("2. EXTRACT PRODUCT DATA")

    await wait_for_real_render(page)

    products = await page.evaluate(
        """
        () => {
            const items = Array.from(document.querySelectorAll(".inventory_item"));
            return items.map(item => ({
                name: item.querySelector(".inventory_item_name")?.innerText.trim() || "",
                description: item.querySelector(".inventory_item_desc")?.innerText.trim() || "",
                price: item.querySelector(".inventory_item_price")?.innerText.trim() || "",
            }));
        }
        """
    )

    print(f"✓ Extracted {len(products)} product records.")
    return products


def export_to_csv(products, output_path=OUTPUT_CSV):
    section("3. EXPORT CSV")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "description", "price"])
        writer.writeheader()
        writer.writerows(products)

    print(f"✓ Saved: {os.path.abspath(output_path)}")


async def take_screenshot(page, path=SCREENSHOT_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    await page.screenshot(path=path, full_page=True)
    print(f"✓ Screenshot saved: {os.path.abspath(path)}")


# ============================================================
# DEMO: EXACT-MATCH ELEMENT DETECTION IN ACTION
# ============================================================

async def demo_exact_match_click(page, target_product_name):
    """
    Demonstrates the exact-match detection helper: finds the specific
    product card matching target_product_name (ignoring any other product
    whose name merely contains it as a substring) and clicks its "Add to
    cart" button.
    """
    section(f"4. EXACT-MATCH DEMO: '{target_product_name}'")

    container = await find_exact_text_container(page, target_product_name, must_contain_selector="button")
    if container is None:
        print(f"✗ No exact match found for '{target_product_name}'.")
        return False

    add_button = container.locator("button").first
    await click_resilient(add_button)
    print(f"✓ Found exact product card and clicked its button.")
    return True


# ============================================================
# MAIN
# ============================================================

async def main():
    section("WEB AUTOMATION DATA EXTRACTOR")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await context.new_page()

        try:
            await login(page, USERNAME, PASSWORD)

            products = await extract_products(page)
            export_to_csv(products)
            await take_screenshot(page)

            if products:
                await demo_exact_match_click(page, products[0]["name"])

            print("\n✓ Run complete.")

        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
