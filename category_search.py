import pandas as pd
import os
import time
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright

# ================= ⚙️ CONFIGURATION =================
PINCODE_FILE = "/Users/apple/Desktop/webscrape/operationalpincodesudupi.csv"
OUTPUT_FILE = "/Users/apple/Desktop/webscrape/results/category_discovery_leads.csv"
OUTPUT_COLUMNS = ["Name", "Category", "Address", "Location", "Pincode", "Contact_Number"]

# FULL LIST OF CATEGORIES
SEARCH_CATEGORIES = [
    "Rice Mill", "Hardware Store", "Transport Contractor", "Catering Service",
    "Agro Product Trader", "Tractor Dealer", "Fertilizer Shop",
    "Cloth Store", "Shoe Store", "Garment Manufacturer",
    "Automobile Showroom", "Car Service Center", "Tire Shop",
    "Fencing Contractor", "Computer Hardware Store", "Electrical Supply Store",
    "Metal Fabrication", "Plumbing Contractor", "Cement Dealer",
    "Bakery", "Dairy Farm", "Poultry Farm", "Grocery Wholesaler",
    "Furniture Store", "Mattress Store", "Medical Shop", "Hospital"
]

# SETTINGS
MAX_RESULTS_PER_SEARCH = 60   # Good balance between speed and volume
RESTART_BROWSER_EVERY = 20    # Restart browser every 20 searches
# ====================================================

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

def extract_details(page):
    """Extracts Name, Category, Address, Location, Contact_Number from Business Detail view."""
    data = {"Name": "N/A", "Phone": "Not Found", "Category": "N/A", "Address": "N/A"}
    try:
        try:
            name_el = page.locator("div[role='main'] h1").first
            if name_el.count() > 0:
                text = name_el.inner_text()
                if "Results" not in text:
                    data["Name"] = text
        except: pass

        try:
            phone_btn = page.locator("button[aria-label^='Phone:']")
            if phone_btn.count() > 0:
                raw = phone_btn.first.get_attribute("aria-label")
                data["Phone"] = (raw or "").replace("Phone:", "").strip()
            else:
                main_text = page.locator("div[role='main']").inner_text()
                match = re.search(r'((\+91|0)?\s?\d{5}\s?\d{5})', main_text)
                if match:
                    data["Phone"] = match.group(0).strip()
        except: pass

        try:
            cat_btn = page.locator("button[jsaction*='category']")
            if cat_btn.count() > 0:
                data["Category"] = cat_btn.first.inner_text()
        except: pass

        try:
            addr_btn = page.locator("button[data-item-id='address']")
            if addr_btn.count() > 0:
                raw = addr_btn.first.get_attribute("aria-label") or ""
                data["Address"] = raw.replace("Address:", "").strip()
        except: pass
    except Exception:
        pass
    return data

def run_deep_discovery():
    print("🤖 STARTING ROBUST DISCOVERY...", flush=True)

    # --- 1. SETUP ---
    if not os.path.exists(PINCODE_FILE):
        print(f"❌ Pincode file missing: {PINCODE_FILE}")
        return

    # Load Pincodes
    try:
        zone_df = pd.read_csv(PINCODE_FILE)
        cols = [str(c).strip().lower() for c in zone_df.columns]
        zone_df.columns = cols
        pincode_col = next((c for c in cols if 'pincode' in c), cols[0])
        pincodes = zone_df[pincode_col].dropna().astype(str).str.replace(".0", "", regex=False).unique().tolist()
        print(f"✅ Loaded {len(pincodes)} Pincodes.")
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    # Load Existing to prevent duplicates
    existing_ids = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            df = pd.read_csv(OUTPUT_FILE)
            for _, row in df.iterrows():
                name = str(row.get("Name", "")).strip()
                ph = str(row.get("Contact_Number", row.get("Phone", ""))).strip()
                if name and ph:
                    existing_ids.add((name, ph))
            print(f"📋 Loaded {len(existing_ids)} existing leads to avoid duplicates.")
        except Exception:
            pass

    write_header = not os.path.exists(OUTPUT_FILE)
    print(f"📁 Writing to: {OUTPUT_FILE} (each lead written as soon as extracted)\n")

    # --- 2. BROWSER LOOP ---
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for pin_idx, pincode in enumerate(pincodes):
            print(f"\n📍 Scanning Zone [{pin_idx+1}/{len(pincodes)}]: {pincode}")
            
            for cat_idx, category in enumerate(SEARCH_CATEGORIES):
                
                # Restart browser to keep it fast
                if cat_idx > 0 and cat_idx % RESTART_BROWSER_EVERY == 0:
                    page.close()
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                search_term = f"{category} in {pincode}"
                print(f"   🔎 Searching: {search_term}")

                try:
                    # LOAD
                    page.goto("https://www.google.com/maps/search/" + quote(search_term), timeout=60000)
                    
                    # WAIT
                    try:
                        page.wait_for_selector("a[href*='/place/'], div[role='heading']:has-text('No results')", timeout=10000)
                    except:
                        print("      🔸 No results.")
                        continue

                    # SCROLL (Wait a bit longer to ensure loading)
                    print("      📜 Scrolling...", end="", flush=True)
                    prev_count = 0
                    same_count = 0
                    while True:
                        try:
                            page.hover("div[role='feed']")
                            page.mouse.wheel(0, 5000)
                            time.sleep(2) # Wait 2 seconds for load
                            
                            curr_count = page.locator("a[href*='/place/']").count()
                            if curr_count == prev_count:
                                same_count += 1
                                if same_count >= 2: break 
                            else:
                                print(f".{curr_count}", end="", flush=True)
                                same_count = 0
                            
                            prev_count = curr_count
                            if curr_count >= MAX_RESULTS_PER_SEARCH: break
                        except: break
                    
                    print(f"\n      👀 Found {prev_count} listings. Extracting...")

                    # EXTRACT
                    leads_buffer = []
                    for i in range(prev_count):
                        try:
                            # CLICK
                            item = page.locator("a[href*='/place/']").nth(i)
                            item.click()
                            
                            # WAIT FOR DETAILS (Critical Step)
                            # We wait for the H1 title to change from "Results" to the business name
                            try:
                                page.wait_for_selector("div[role='main'] h1", timeout=3000)
                                time.sleep(0.5) # Slight buffer
                            except: pass

                            # GET DATA
                            details = extract_details(page)
                            
                            # SAVE CHECK (accept if we have a phone; allow Name "N/A" when name selector fails)
                            if details["Phone"] != "Not Found" and details["Name"] != "Results":
                                uid = (details["Name"].strip(), details["Phone"].strip())
                                if uid not in existing_ids:
                                    existing_ids.add(uid)
                                    leads_buffer.append(details)
                                    # Build row with requested columns: Name, Category, Address, Location, Pincode, Contact_Number
                                    row = {
                                        "Name": details["Name"],
                                        "Category": details["Category"],
                                        "Address": details["Address"],
                                        "Location": details["Address"],
                                        "Pincode": pincode,
                                        "Contact_Number": details["Phone"],
                                    }
                                    pd.DataFrame([row])[OUTPUT_COLUMNS].to_csv(
                                        OUTPUT_FILE, mode="a", header=write_header, index=False
                                    )
                                    if write_header:
                                        write_header = False
                                    print(f"         📞 NEW: {details['Name']} | {details['Phone']}")
                                    print(f"         💾 Written to CSV — refresh file to see")
                        except Exception:
                            pass

                    if not leads_buffer:
                        print("      🔸 No new valid leads with phones found.")

                except Exception as e:
                    print(f"      ⚠️ Search Error: {e}")

        browser.close()
        print("\n🏁 DISCOVERY COMPLETE.")

if __name__ == "__main__":
    run_deep_discovery()