import pandas as pd
import os
import time
import random
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

INPUT_CSV = "/Users/apple/Desktop/webscrape/new_in.csv"
ZONE_FILE = "/Users/apple/Desktop/webscrape/operationalpincodesudupi.csv"
OUTPUT_FILE = "/Users/apple/Desktop/webscrape/results/final_logistics_leads.csv"

NEW_BUSINESS_KEYWORDS = [
    "Rice Mill", "Oil Mill", "Agri Fertilizer Dealer", "Plant Nursery",
    "Food Processing Unit", "Dairy Farm", "Wholesale Grocery Store",
    "Catering Service", "Poultry Farm", "Fish Processing Unit",
    "Bakery and Confectionery Manufacturer", "Cold Storage Facility",
    "Steel Fabrication Works", "PVC Pipe Manufacturer", "Cement Dealer",
    "Plastic Molding Factory", "Packaging Material Manufacturer",
    "Paper Product Manufacturer", "Scrap Metal Dealer", "Industrial Machine Supplier",
    "Water Pump Manufacturer", "Tarpaulin Manufacturer", "Cable Manufacturing Unit",
    "Hardware Wholesaler", "Timber Mart", "Stone Cutting and Polishing",
    "Sanitary Ware Supplier", "Tiles and Ceramics Dealer", "Glass and Plywood Dealer",
    "Electrical Equipment Manufacturer", "Fencing Contractor",
    "Garment Manufacturing Factory", "Wholesale Cloth Dealer", "Shoe Manufacturer",
    "Furniture Manufacturer", "Mattress Manufacturer", "Home Appliance Wholesaler",
    "Auto Parts Distributor", "Tire Wholesaler", "Battery Dealer",
    "Warehousing Service", "Earth Mover Service", "Transport Contractor",
    "Pharma Distributor", "Medical Equipment Supplier", "Herbal Product Manufacturer"
]

RESTART_BROWSER_EVERY = 30
SAVE_EVERY = 5
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

def apply_stealth(page):
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)

def safe_goto(page, url, retries=3):
    for attempt in range(retries):
        try:
            page.goto(url, timeout=60000, wait_until="load")
            time.sleep(random.uniform(1.5, 2.5))
            return True
        except Exception as e:
            print(f"      ⚠️ Nav attempt {attempt+1}/{retries} failed: {e}")
            time.sleep(4 + attempt * 2)
    return False

def safe_type_and_search(page, query, retries=3):
    selectors = [
        "#searchboxinput",
        "input[aria-label='Search Google Maps']",
        "input[id='searchboxinput']",
        "input[type='text']",
    ]
    for attempt in range(retries):
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=10000, state="attached")
                page.wait_for_selector(selector, timeout=5000, state="visible")
                time.sleep(0.4)
                page.click(selector, click_count=3)
                time.sleep(0.2)
                page.keyboard.press("Backspace")
                time.sleep(0.2)
                page.type(selector, query, delay=random.randint(60, 120))
                time.sleep(0.5)
                page.keyboard.press("Enter")
                return True
            except Exception:
                continue
        print(f"      ⚠️ Search box not found (attempt {attempt+1}/{retries}), reloading...")
        if not safe_goto(page, "https://www.google.com/maps"):
            return False
    return False

def extract_details(page):
    data = {"Name": "N/A", "Phone": "Not Found", "Category": "N/A", "Address": "N/A"}
    try:
        page.wait_for_selector("h1", timeout=5000)
        if page.locator("h1").count() > 0:
            data["Name"] = page.locator("h1").first.inner_text()
        phone_btn = page.locator("button[aria-label^='Phone:']")
        if phone_btn.count() > 0:
            data["Phone"] = phone_btn.first.get_attribute("aria-label").replace("Phone:", "").strip()
        else:
            try:
                all_text = page.locator("div[role='main']").inner_text(timeout=3000)
                phone_match = re.search(r'(\+91[\s-]?\d{5}[\s-]?\d{5}|0\d{2,4}[\s-]?\d{6,8}|\d{10})', all_text)
                if phone_match:
                    data["Phone"] = phone_match.group(0).strip()
            except Exception:
                pass
        cat_btn = page.locator("button[jsaction*='category']")
        if cat_btn.count() > 0:
            data["Category"] = cat_btn.first.inner_text()
        addr_btn = page.locator("button[data-item-id='address']")
        if addr_btn.count() > 0:
            raw = addr_btn.first.get_attribute("aria-label") or ""
            data["Address"] = raw.replace("Address:", "").strip()
    except Exception:
        pass
    return data

def create_fresh_page(browser, context):
    try:
        page = context.new_page()
        apply_stealth(page)
        return page
    except Exception:
        return None

def run_marketing_agent():
    print("🤖 STARTING LOGISTICS MARKETING AGENT (v2 - Fixed)...")

    if os.path.exists(OUTPUT_FILE):
        print(f"🔄 Resuming from: {OUTPUT_FILE}")
        df = pd.read_csv(OUTPUT_FILE)
    else:
        print(f"📂 Loading Input CSV: {INPUT_CSV}")
        try:
            df = pd.read_csv(INPUT_CSV)
        except Exception as e:
            print(f"❌ Critical Error loading CSV: {e}")
            return

    for col in ["Google_Phone", "Google_Category", "Google_Address", "Source", "Google_Location_Used"]:
        if col not in df.columns:
            df[col] = ""

    print(f"📂 Loading Operating Zones from: {ZONE_FILE}")
    try:
        zone_df = pd.read_csv(ZONE_FILE)
        zone_df.columns = [str(c).strip() for c in zone_df.columns]
        pincode_col = next((c for c in zone_df.columns if c.lower() == 'pincode'), None)
        if not pincode_col:
            print(f"❌ No Pincode column found. Columns: {zone_df.columns.tolist()}")
            return
        pincodes = zone_df[pincode_col].dropna().astype(str).str.replace(".0", "", regex=False).unique().tolist()
        operating_zones = [(p, "") for p in pincodes]
        print(f"📍 Loaded {len(operating_zones)} operational pincodes.")
    except Exception as e:
        print(f"❌ Critical Error loading zones: {e}")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-infobars"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/"
        )
        page = create_fresh_page(browser, context)

        print("\n🚀 PHASE 1: Enriching Existing Database...")
        rows_to_process = df[df["Google_Phone"].astype(str).isin(["nan", "", "Not Found"])].index.tolist()
        print(f"   → {len(rows_to_process)} rows need enrichment.")

        for count, i in enumerate(rows_to_process):
            if count > 0 and count % RESTART_BROWSER_EVERY == 0:
                print(f"\n♻️ Restarting browser at #{count}...")
                try:
                    page.close()
                except Exception:
                    pass
                time.sleep(random.uniform(5, 10))
                page = create_fresh_page(browser, context)
                if page is None:
                    print("❌ Could not create new page. Stopping.")
                    break

            row = df.loc[i]
            name = str(row.get("EnterpriseName", "")).strip()
            pincode = str(row.get("Pincode", "")).replace(".0", "")
            district = str(row.get("District", "")).strip()
            query = f"{name} {pincode} {district}"
            print(f"   [{i}/{len(df)}] 🔎 {query}")

            try:
                time.sleep(random.uniform(1.5, 3.0))
                if not safe_goto(page, "https://www.google.com/maps"):
                    df.at[i, "Google_Phone"] = "Not Found"
                    continue
                if not safe_type_and_search(page, query):
                    df.at[i, "Google_Phone"] = "Not Found"
                    continue
                try:
                    page.wait_for_selector("h1, a[href*='/place/']", timeout=8000)
                except PlaywrightTimeout:
                    df.at[i, "Google_Phone"] = "Not Found"
                    continue
                if page.locator("a[href*='/place/']").count() > 0 and page.locator("h1").count() == 0:
                    try:
                        page.locator("a[href*='/place/']").first.click()
                        page.wait_for_selector("h1", timeout=6000)
                    except Exception:
                        pass
                details = extract_details(page)
                df.at[i, "Google_Phone"] = details["Phone"]
                df.at[i, "Google_Category"] = details["Category"]
                df.at[i, "Google_Address"] = details["Address"]
                df.at[i, "Source"] = "Govt_List_Enriched"
                if details["Phone"] != "Not Found":
                    print(f"      ✅ {details['Phone']} | {details['Category']}")
                else:
                    print(f"      🔸 Found but no phone.")
            except Exception as e:
                print(f"      ⚠️ Error on row {i}: {e}")
                df.at[i, "Google_Phone"] = "Not Found"
                try:
                    page.close()
                except Exception:
                    pass
                time.sleep(5)
                page = create_fresh_page(browser, context)
                if page is None:
                    print("❌ Could not recover. Stopping.")
                    break

            if count % SAVE_EVERY == 0:
                df.to_csv(OUTPUT_FILE, index=False)
                print(f"      💾 Saved. ({count}/{len(rows_to_process)})")
                time.sleep(random.uniform(2, 5))

        df.to_csv(OUTPUT_FILE, index=False)
        print("\n✅ PHASE 1 COMPLETE.")

        print("\n🚀 PHASE 2: Discovering NEW Businesses...")
        existing_unique_ids = set()
        for _, row in df.iterrows():
            ph = str(row.get("Google_Phone", "")).strip()
            nm = str(row.get("EnterpriseName", "")).strip().lower()
            if ph not in ["nan", "", "Not Found"]:
                existing_unique_ids.add((nm, ph))
        print(f"   → Dedup set: {len(existing_unique_ids)} existing entries.")

        new_leads = []
        search_count = 0
        total_searches = len(operating_zones) * len(NEW_BUSINESS_KEYWORDS)

        for zone_idx, (pincode, district) in enumerate(operating_zones):
            pincode = str(pincode).replace(".0", "")
            for keyword in NEW_BUSINESS_KEYWORDS:
                search_count += 1
                search_term = f"{keyword} {pincode}"
                print(f"   [{search_count}/{total_searches}] 🔎 {search_term}")

                if search_count > 0 and search_count % RESTART_BROWSER_EVERY == 0:
                    print("♻️ Restarting browser...")
                    try:
                        page.close()
                    except Exception:
                        pass
                    time.sleep(random.uniform(8, 15))
                    page = create_fresh_page(browser, context)
                    if page is None:
                        break

                try:
                    time.sleep(random.uniform(2, 4))
                    if not safe_goto(page, "https://www.google.com/maps"):
                        continue
                    if not safe_type_and_search(page, search_term):
                        continue
                    try:
                        page.wait_for_selector("a[href*='/place/']", timeout=6000)
                    except PlaywrightTimeout:
                        print("      ❌ No businesses found.")
                        continue

                    results = page.locator("a[href*='/place/']").all()
                    found_count = 0
                    for res in results[:7]:
                        try:
                            res.click()
                            time.sleep(random.uniform(1.5, 3.0))
                            details = extract_details(page)
                            if details["Phone"] != "Not Found":
                                new_id = (details["Name"].strip().lower(), details["Phone"].strip())
                                if new_id not in existing_unique_ids:
                                    new_leads.append({
                                        "EnterpriseName": details["Name"],
                                      "Pincode": pincode,
                                        "District": district,
                                        "Google_Phone": details["Phone"],
                                        "Google_Category": details["Category"],
                                        "Google_Address": details["Address"],
                                        "Source": "Discovery_Mode",
                                        "Google_Location_Used": search_term
                                    })
                                    existing_unique_ids.add(new_id)
                                    found_count += 1
                                    print(f"      ✨ NEW LEAD: {details['Name']} ({details['Phone']})")
                                else:
                                    print(f"      🔸 Duplicate: {details['Name']}")
                            page.go_back()
                            time.sleep(random.uniform(1, 2))
                        except Exception as res_err:
                            try:
                                page.go_back()
                                time.sleep(1)
                            except Exception:
                                pass
                            continue
                    print(f"      → {found_count} new leads.")
                except Exception as e:
                    print(f"      ⚠️ Error: {e}")
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = create_fresh_page(browser, context)
                    time.sleep(5)

            if new_leads:
                new_df = pd.DataFrame(new_leads)
                new_df.to_csv(OUTPUT_FILE, mode='a', header=not os.path.exists(OUTPUT_FILE), index=False)
                print(f"      💾 Saved {len(new_leads)} leads from zone {pincode}.")
                new_leads = []

        if new_leads:
            pd.DataFrame(new_leads).to_csv(OUTPUT_FILE, mode='a', header=False, index=False)

        try:
            browser.close()
        except Exception:
            pass
        print("\n🏁 ALL DONE!")

if __name__ == "__main__":
    run_marketing_agent()
