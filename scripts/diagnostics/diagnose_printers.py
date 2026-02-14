"""
Diagnostic script to analyze printer duplication issue
"""
import win32print

# Enumerate all printers
flags = (
    win32print.PRINTER_ENUM_LOCAL |
    win32print.PRINTER_ENUM_CONNECTIONS |
    win32print.PRINTER_ENUM_NETWORK
)

printers = win32print.EnumPrinters(flags, None, 2)

print(f"Total printers returned by Windows API: {len(printers)}\n")
print("=" * 80)

for idx, p in enumerate(printers, 1):
    name = p.get('pPrinterName', '')
    port = p.get('pPortName', '')
    driver = p.get('pDriverName', '')
    attributes = p.get('Attributes', 0)
    
    print(f"\nPrinter #{idx}:")
    print(f"  Name: {name}")
    print(f"  Port: {port}")
    print(f"  Driver: {driver}")
    print(f"  Attributes: {attributes} (0x{attributes:08X})")
    
    # Try to get more details
    try:
        h = win32print.OpenPrinter(name)
        try:
            info6 = win32print.GetPrinter(h, 6)
            status = info6.get('dwStatus', 0) if isinstance(info6, dict) else 0
            print(f"  Status: {status} (0x{status:08X})")
        finally:
            win32print.ClosePrinter(h)
    except Exception as e:
        print(f"  Status: Could not open printer - {e}")
    
    print("-" * 80)

# Check for duplicates
print("\n" + "=" * 80)
print("DUPLICATE ANALYSIS:")
print("=" * 80)

names = [p.get('pPrinterName', '') for p in printers]
name_counts = {}
for name in names:
    name_counts[name] = name_counts.get(name, 0) + 1

duplicates = {name: count for name, count in name_counts.items() if count > 1}
if duplicates:
    print("\nDUPLICATES FOUND:")
    for name, count in duplicates.items():
        print(f"  '{name}' appears {count} times")
else:
    print("\nNo exact name duplicates found.")

# Check for "(Copy X)" pattern
print("\n" + "=" * 80)
print("COPY PATTERN ANALYSIS:")
print("=" * 80)

import re
copy_pattern = re.compile(r'^(.+?)\s*\(Copy\s+\d+\)$', re.IGNORECASE)

copy_printers = []
original_printers = []

for p in printers:
    name = p.get('pPrinterName', '')
    match = copy_pattern.match(name)
    if match:
        original_name = match.group(1).strip()
        copy_printers.append({
            'copy_name': name,
            'original_name': original_name,
            'port': p.get('pPortName', ''),
            'driver': p.get('pDriverName', '')
        })
    else:
        original_printers.append({
            'name': name,
            'port': p.get('pPortName', ''),
            'driver': p.get('pDriverName', '')
        })

if copy_printers:
    print(f"\nFound {len(copy_printers)} printer(s) with '(Copy X)' pattern:")
    for cp in copy_printers:
        print(f"\n  Copy: {cp['copy_name']}")
        print(f"    Original name: {cp['original_name']}")
        print(f"    Port: {cp['port']}")
        print(f"    Driver: {cp['driver']}")
        
        # Find matching original
        matching = [op for op in original_printers if op['name'] == cp['original_name']]
        if matching:
            print(f"    MATCH FOUND:")
            for m in matching:
                print(f"      Original: {m['name']}")
                print(f"      Port: {m['port']}")
                print(f"      Driver: {m['driver']}")
                print(f"      Same Port? {m['port'] == cp['port']}")
                print(f"      Same Driver? {m['driver'] == cp['driver']}")
        else:
            print(f"    NO MATCHING ORIGINAL FOUND")
else:
    print("\nNo printers with '(Copy X)' pattern found.")
