"""
Verification script to confirm duplicate printer filtering works
"""
import sys
import os

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopkeeper_app.printer_manager import PrinterManager

print("=" * 80)
print("VERIFICATION: Duplicate Printer Filter")
print("=" * 80)

# Initialize printer manager
pm = PrinterManager()

print("\nFetching available printers...")
printers = pm.get_available_printers()

print(f"\nTotal printers returned: {len(printers)}")
print("\n" + "=" * 80)
print("PRINTER LIST:")
print("=" * 80)

for idx, p in enumerate(printers, 1):
    name = p.get('name', 'Unknown')
    port = p.get('port_name', 'Unknown')
    connection = p.get('connection_type', 'Unknown')
    is_virtual = p.get('is_virtual', False)
    status = p.get('status', 'Unknown')
    
    print(f"\n{idx}. {name}")
    print(f"   Port: {port}")
    print(f"   Connection: {connection}")
    print(f"   Virtual: {is_virtual}")
    print(f"   Status: {status}")

print("\n" + "=" * 80)
print("VERIFICATION CHECKS:")
print("=" * 80)

# Check for "(Copy X)" pattern
import re
copy_pattern = re.compile(r'\(Copy\s+\d+\)$', re.IGNORECASE)

has_copy = False
for p in printers:
    if copy_pattern.search(p.get('name', '')):
        has_copy = True
        print(f"❌ FAIL: Found duplicate printer: {p.get('name')}")

if not has_copy:
    print("✅ PASS: No '(Copy X)' printers found in list")

# Check for HP LaserJet P1007
hp_printers = [p for p in printers if 'HP LaserJet P1007' in p.get('name', '')]
if len(hp_printers) == 1:
    print(f"✅ PASS: Exactly 1 HP LaserJet P1007 found: {hp_printers[0].get('name')}")
elif len(hp_printers) == 0:
    print("⚠️  WARNING: No HP LaserJet P1007 found (may not be connected)")
else:
    print(f"❌ FAIL: Multiple HP LaserJet P1007 entries found: {len(hp_printers)}")
    for p in hp_printers:
        print(f"   - {p.get('name')}")

print("\n" + "=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)

# Cleanup
pm.cleanup()
