import csv

in_path = "0-3507&&15-16k.csv"
out_path = "0-3507_contacts_10digit.csv"

with open(in_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

contacts = []
for row in rows:
    raw = row.get("Google_Phone", "").strip()
    digits = "".join(c for c in raw if c.isdigit())
    last10 = digits[-10:] if len(digits) >= 10 else digits
    if last10:
        contacts.append({"Contact": f"+91{last10}"})

with open(out_path, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["Contact"])
    w.writeheader()
    w.writerows(contacts)

print(f"Wrote {len(contacts)} contacts to {out_path}")
