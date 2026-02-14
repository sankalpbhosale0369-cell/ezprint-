"""
Simple test to verify the duplicate printer filter logic
"""
import re

# Simulate printer data as returned by Windows API
test_printers = [
    {'name': 'HP LaserJet P1007', 'port_name': 'USB005', 'driver_name': 'HP LaserJet P1007', 'is_virtual': False},
    {'name': 'HP LaserJet P1007 (Copy 1)', 'port_name': 'USB006', 'driver_name': 'HP LaserJet P1007', 'is_virtual': False},
    {'name': 'Microsoft Print to PDF', 'port_name': 'PORTPROMPT:', 'driver_name': 'Microsoft Print To PDF', 'is_virtual': True},
    {'name': 'Canon Printer', 'port_name': 'USB001', 'driver_name': 'Canon', 'is_virtual': False},
    {'name': 'Canon Printer (Copy 2)', 'port_name': 'USB002', 'driver_name': 'Canon', 'is_virtual': False},
]

print("=" * 80)
print("BEFORE FILTERING:")
print("=" * 80)
for p in test_printers:
    print(f"  - {p['name']} ({p['port_name']})")

print(f"\nTotal: {len(test_printers)} printers")

# Apply the same filtering logic as in printer_manager.py
virtual_names = ["MICROSOFT PRINT TO PDF", "XPS DOCUMENT WRITER", "ONENOTE", "FAX"]
copy_pattern = re.compile(r'\(Copy\s+\d+\)$', re.IGNORECASE)

filtered_printers = []
for p in test_printers:
    name_upper = (p.get('name') or '').upper()
    
    # Skip strictly identified virtual devices
    if any(v_name in name_upper for v_name in virtual_names):
        print(f"\n[FILTERED] Virtual printer: {p.get('name')}")
        continue
    
    # Skip duplicate Windows printer queues like "(Copy 1)", "(Copy 2)", etc.
    if copy_pattern.search(p.get('name', '')):
        print(f"[FILTERED] Duplicate queue: {p.get('name')}")
        continue
    
    filtered_printers.append(p)

print("\n" + "=" * 80)
print("AFTER FILTERING:")
print("=" * 80)
for p in filtered_printers:
    print(f"  - {p['name']} ({p['port_name']})")

print(f"\nTotal: {len(filtered_printers)} printers")

print("\n" + "=" * 80)
print("VERIFICATION:")
print("=" * 80)

# Check results
has_copy = any(copy_pattern.search(p.get('name', '')) for p in filtered_printers)
has_virtual = any(any(v in p.get('name', '').upper() for v in virtual_names) for p in filtered_printers)

if not has_copy:
    print("[PASS] No (Copy X) printers in filtered list")
else:
    print("[FAIL] Found (Copy X) printers in filtered list")

if not has_virtual:
    print("[PASS] No virtual printers in filtered list")
else:
    print("[FAIL] Found virtual printers in filtered list")

# Check HP LaserJet
hp_count = sum(1 for p in filtered_printers if 'HP LaserJet P1007' in p.get('name', ''))
if hp_count == 1:
    print("[PASS] Exactly 1 HP LaserJet P1007 in filtered list")
else:
    print(f"[FAIL] {hp_count} HP LaserJet P1007 entries in filtered list")

# Check Canon
canon_count = sum(1 for p in filtered_printers if 'Canon Printer' in p.get('name', ''))
if canon_count == 1:
    print("[PASS] Exactly 1 Canon Printer in filtered list")
else:
    print(f"[FAIL] {canon_count} Canon Printer entries in filtered list")

print("\n" + "=" * 80)
print("TEST COMPLETE - ALL CHECKS PASSED" if not has_copy and not has_virtual and hp_count == 1 and canon_count == 1 else "TEST COMPLETE - SOME CHECKS FAILED")
print("=" * 80)
