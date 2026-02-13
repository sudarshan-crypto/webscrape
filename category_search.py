import pandas as pd
import os
import time
import random
import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright

# ================= ⚙️ CONFIGURATION =================
PINCODE_FILE = "/Users/apple/Desktop/webscrape/operationalpincodesudupi.csv"
OUTPUT_FILE = "/Users/apple/Desktop/webscrape/results/category_discovery_leads.csv"
FINAL_OUTPUT = "/Users/apple/Desktop/webscrape/results/final_logistics_leads.csv"
PROGRESS_FILE = "/Users/apple/Desktop/webscrape/results/category_discovery_progress.txt"

# CSV columns
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
MAX_RESULTS_PER_SEARCH = 100  # Extract all available
RESTART_BROWSER_EVERY = 15    # Restart frequently to keep Chrome fast
# ====================================================

os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

def normalize_phone(phone):
    """Standardize phone numbers to last 10 digits."""
    if not phone or phone in ["Not Found", "N/A"]: return ""
    digits = re.sub(r"\D", "", str(phone))
    return digits[-10:] if len(digits) >= 10 else digits

def extract_real_pincode(address, default_pincode):
    """Extracts 6-digit pincode from address string. Fallback to default if not found."""
    if not address: return default_pincode
    match = re.search(r"\b(5\d{5})\b", address) # Looks for 5xxxxx (Karnataka pincodes)
    return match.group(1) if match else default_pincode

def extract_details(page, search_pincode):
    """Robust extraction of all fields."""
    data = {
        "Name": "N/A", 
        "Category": "N/A", 
        "Address": "N/A", 
        "Location": "N/A", 
        "Pincode": search_pincode, 
        "Contact_Number": "Not Found"
    }
    
    # 1. Wait for Data Load (Dynamic)
    try:
        # Wait for H1 (Name) or Directions button to ensure panel is ready
        page.wait_for_selector("div[role='main'] h1", timeout=3000)
    except:
        pass # Proceed anyway, maybe it loaded fast

    try:
        # --- GET FULL TEXT FOR REGEX BACKUP ---
        main_text = ""
        try:
            main_text = page.locator("div[role='main']").inner_text()
        except: pass

        # --- A. NAME ---
        try:
            name_el = page.locator("div[role='main'] h1").first
            if name_el.count() > 0:
                name = name_el.inner_text()
                if "Results" not in name:
                    data["Name"] = name.strip()
        except: pass

        # --- B. CONTACT NUMBER (Multi-Strategy) ---
        phone_found = False
        # Strategy 1: Aria Label Button
        if not phone_found:
            for selector in ["button[aria-label^='Phone:']", "button[aria-label^='Call:']"]:
                if page.locator(selector).count() > 0:
                    raw_ph = page.locator(selector).first.get_attribute("aria-label")
                    data["Contact_Number"] = re.sub(r"\D", "", raw_ph)[-10:]
                    phone_found = True
                    break
        
        # Strategy 2: Regex on Main Text
        if not phone_found and main_text:
            # Matches +91 XXXXX XXXXX or 0XXXXX XXXXX
            matches = re.findall(r'(?:\+91|0)?\s?(\d{5}\s?\d{5}|\d{4}\s?\d{6})', main_text)
            for m in matches:
                clean_num = re.sub(r"\D", "", m)
                if len(clean_num) >= 10:
                    data["Contact_Number"] = clean_num[-10:]
                    phone_found = True
                    break

        # --- C. CATEGORY ---
        try:
            cat_btn = page.locator("button[jsaction*='category']")
            if cat_btn.count() > 0:
                data["Category"] = cat_btn.first.inner_text()
        except: pass

        # --- D. ADDRESS & PINCODE ---
        try:
            addr_btn = page.locator("button[data-item-id='address']")
            if addr_btn.count() > 0:
                raw_addr = addr_btn.first.get_attribute("aria-label").replace("Address:", "").strip()
                data["Address"] = raw_addr
                data["Location"] = raw_addr.split(",")[0] # First part is usually building/street
                
                # Extract REAL Pincode from Address
                data["Pincode"] = extract_real_pincode(raw_addr, search_pincode)
        except: pass

    except Exception:
        pass
        
    return data

def run_deep_discovery():
    print("🤖 STARTING FINAL LOGISTICS DISCOVERY...", flush=True)

    # --- 1. SETUP & RESUME LOGIC ---
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
        print(f"✅ Loaded {len(pincodes)} Operational Pincodes.")
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    # Load Completed Progress (Resume)
    completed_searches = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            for line in f:
                if "," in line:
                    completed_searches.add(tuple(line.strip().split(",", 1)))
    print(f"🔄 Resuming... Skipping {len(completed_searches)} previously finished searches.")

    # Load Existing Numbers (Deduplication)
    existing_phones = set()
    if os.path.exists(OUTPUT_FILE):
        try:
            df_exist = pd.read_csv(OUTPUT_FILE)
            for ph in df_exist["Contact_Number"].dropna().astype(str):
                norm = normalize_phone(ph)
                if len(norm) == 10: existing_phones.add(norm)
        except: pass
    print(f"📋 Loaded {len(existing_phones)} existing contacts to avoid duplicates.\n")

    # --- 2. MAIN BROWSER LOOP ---
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for pin_idx, pincode in enumerate(pincodes):
            print(f"\n📍 Scanning Zone [{pin_idx+1}/{len(pincodes)}]: {pincode}")
            
            for cat_idx, category in enumerate(SEARCH_CATEGORIES):
                
                # CHECK RESUME
                if (str(pincode), category) in completed_searches:
                    continue

                # RESTART BROWSER (Memory Safety)
                if cat_idx > 0 and cat_idx % RESTART_BROWSER_EVERY == 0:
                    page.close()
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                search_term = f"{category} in {pincode}"
                print(f"   🔎 Searching: {search_term}")

                try:
                    # LOAD SEARCH
                    page.goto("https://www.google.com/maps/search/" + quote(search_term), timeout=60000)
                    
                    # WAIT FOR RESULTS
                    try:
                        page.wait_for_selector("a[href*='/place/'], div[role='heading']:has-text('No results')", timeout=10000)
                    except:
                        print("      🔸 No results found (Timeout).")
                        # Mark as done even if empty so we don't retry endlessly
                        with open(PROGRESS_FILE, "a") as f: f.write(f"{pincode},{category}\n")
                        continue

                    # SCROLLING (Aggressive)
                    print("      📜 Scrolling...", end="", flush=True)
                    prev_count = 0
                    same_count = 0
                    
                    while True:
                        try:
                            page.hover("div[role='feed']")
                            page.mouse.wheel(0, 5000)
                            time.sleep(1) # Short wait
                            curr_count = page.locator("a[href*='/place/']").count()
                            
                            if curr_count == prev_count:
                                same_count += 1
                                if same_count >= 3: break # Stop if no new results 3 times
                            else:
                                print(f".{curr_count}", end="", flush=True)
                                same_count = 0
                            
                            prev_count = curr_count
                            if curr_count >= MAX_RESULTS_PER_SEARCH: break
                        except: break
                    
                    print(f"\n      👀 Extracting {prev_count} listings...")

                    # EXTRACTION LOOP
                    leads_buffer = []
                    for i in range(prev_count):
                        try:
                            # CLICK ITEM
                            page.locator("a[href*='/place/']").nth(i).click()
                            
                            # EXTRACT
                            details = extract_details(page, pincode)
                            
                            # VALIDATE & SAVE
                            if details["Contact_Number"] != "Not Found" and details["Name"] != "Results":
                                ph_norm = normalize_phone(details["Contact_Number"])
                                
                                # Check if Valid 10-digit number AND Not Duplicate
                                if len(ph_norm) == 10 and ph_norm not in existing_phones:
                                    existing_phones.add(ph_norm)
                                    leads_buffer.append(details)
                                    print(f"         📞 NEW: {details['Name']} | {details['Contact_Number']}")
                        except: pass

                    # BATCH SAVE
                    if leads_buffer:
                        df = pd.DataFrame(leads_buffer)
                        header = not os.path.exists(OUTPUT_FILE)
                        df[OUTPUT_COLUMNS].to_csv(OUTPUT_FILE, mode='a', header=header, index=False)
                        print(f"      💾 Saved {len(leads_buffer)} new leads.")
                    else:
                        print(f"      → 0 new leads (no phone found or all duplicates).")

                    # MARK SEARCH AS COMPLETE
                    completed_searches.add((str(pincode), category))
                    with open(PROGRESS_FILE, "a") as f:
                        f.write(f"{pincode},{category}\n")

                except Exception as e:
                    print(f"      ⚠️ Search Error: {e}")

        browser.close()
        print("\n🏁 DISCOVERY COMPLETE.")

if __name__ == "__main__":
    run_deep_discovery()