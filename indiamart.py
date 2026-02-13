import asyncio
import os
import random
import re
import pandas as pd
from datetime import datetime
from urllib.parse import quote_plus
from playwright.async_api import async_playwright

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

# --- CONFIGURATION ---
OUTPUT_FILE = "udupi_hyperlocal_leads.csv"
# Your expanded lists
LOCATIONS = ["Manipal", "Santhekatte Udupi", "Kalyanpura", "Adi Udupi", "Shivalli Industrial Area", "Malpe", "Kunjibettu", "Brahmavara", "Ambagilu", "udupi", "manipal industrial area"]
KEYWORDS = ["furniture"]

# List of User-Agents to rotate (mimics different browsers)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

async def run_scraper():
    # Output: Name, Contact, Location, Pin only
    CSV_COLS = ["Name", "Contact", "Location", "Pin"]
    if os.path.exists(OUTPUT_FILE):
        existing_df = pd.read_csv(OUTPUT_FILE)
        if list(existing_df.columns) != CSV_COLS:
            processed_entries = set()
        else:
            existing_df = existing_df.drop_duplicates(subset=["Name", "Location"], keep="first")
            existing_df.to_csv(OUTPUT_FILE, index=False)
            processed_entries = set(existing_df['Name'].astype(str) + existing_df['Location'].astype(str))
        print(f"Resuming: skipping {len(processed_entries)} already scraped (no duplicates).", flush=True)
    else:
        processed_entries = set()
        pd.DataFrame(columns=CSV_COLS).to_csv(OUTPUT_FILE, index=False)

    async with async_playwright() as p:
        # Launch headed so you can see, but add anti-bot args
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        
        # 2. ANTI-BLOCK: Use randomized User-Agent
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = await context.new_page()
        
        if stealth_async:
            await stealth_async(page)

        def extract_pin(text):
            if not text or text == "N/A":
                return "N/A"
            m = re.search(r"\b[1-9][0-9]{5}\b", str(text))
            return m.group(0) if m else "N/A"

        def normalize_phone(raw):
            if not raw or str(raw).strip() in ("", "N/A", "Not Found"):
                return "Not Found"
            s = str(raw).strip()
            digits = re.sub(r"\D", "", s)
            if len(digits) >= 10:
                return digits[-10:] if len(digits) > 10 else digits
            if len(digits) >= 6:
                return digits
            return s if re.search(r"\d", s) else "Not Found"

        async def get_phone_from_contact_click(page, card):
            contact_btn = await card.query_selector(".m-cp-b")
            if not contact_btn:
                return "Not Found"
            await contact_btn.click()
            await asyncio.sleep(random.uniform(1.5, 3))
            raw = "Not Found"
            for selector in [".m-ph", "[class*='ph']", "[class*='phone']", "a[href^='tel:']", "[class*='contact']"]:
                try:
                    el = await page.wait_for_selector(selector, state="visible", timeout=3000)
                    if el:
                        raw = await el.inner_text()
                        if not raw:
                            href = await el.get_attribute("href")
                            if href and href.startswith("tel:"):
                                raw = href.replace("tel:", "").strip()
                        if raw and re.search(r"\d", str(raw)):
                            break
                except Exception:
                    continue
            try:
                close_btn = await page.query_selector(".close, [aria-label='Close'], .modal-close, .popup-close, button:has-text('Close')")
                if close_btn:
                    await close_btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass
            return normalize_phone(raw)

        for loc in LOCATIONS:
            for kw in KEYWORDS:
                search_term = f"{kw} in {loc}"
                page_num = 1
                while True:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {search_term} (page {page_num})", flush=True)
                    try:
                        if page_num == 1:
                            await page.goto(f"https://dir.indiamart.com/search.mp?ss={quote_plus(search_term)}", timeout=60000)
                        else:
                            next_btn = None
                            for sel in ["a[rel='next']", "a:has-text('Next')", "a.pn", ".pagination a", "a:has-text('>')"]:
                                try:
                                    next_btn = await page.query_selector(sel)
                                    if next_btn:
                                        break
                                except Exception:
                                    continue
                            if not next_btn:
                                print(f"   No more pages for {loc}. Moving to next location.", flush=True)
                                break
                            await next_btn.click()
                            await asyncio.sleep(random.uniform(2, 5))

                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await asyncio.sleep(2)

                        cards = await page.query_selector_all(".m-slr-c")
                        if not cards:
                            if page_num == 1:
                                print("   No result cards found.", flush=True)
                            break

                        print(f"   Found {len(cards)} cards. Extracting...", flush=True)
                        for idx in range(len(cards)):
                            try:
                                card = (await page.query_selector_all(".m-slr-c"))[idx]
                                name_elem = await card.query_selector(".m-sn")
                                name = await name_elem.inner_text() if name_elem else "N/A"
                                if (name + loc) in processed_entries:
                                    continue

                                addr_elem = await card.query_selector(".m-sa")
                                address = await addr_elem.inner_text() if addr_elem else "N/A"
                                pin = extract_pin(address)

                                contact = await get_phone_from_contact_click(page, card)

                                row = {"Name": name, "Contact": contact, "Location": loc, "Pin": pin}
                                pd.DataFrame([row]).to_csv(OUTPUT_FILE, mode='a', header=False, index=False)
                                processed_entries.add(name + loc)
                                print(f"   SAVED: {name} | {contact}", flush=True)
                            except Exception as e:
                                print(f"   Skip card: {e}", flush=True)
                                continue

                        page_num += 1
                        await asyncio.sleep(random.uniform(1, 3))

                    except Exception as e:
                        print(f"Error: {e}", flush=True)
                        await asyncio.sleep(60)
                        break

        await browser.close()
        print(f"\n🏁 Finished! Data is in {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(run_scraper())