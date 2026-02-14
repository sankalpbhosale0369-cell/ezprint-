"""
Simple diagnostic to check for HP LaserJet P1007 duplication
"""
import win32print
import re

flags = (
    win32print.PRINTER_ENUM_LOCAL |
    win32print.PRINTER_ENUM_CONNECTIONS |
    win32print.PRINTER_ENUM_NETWORK
)

printers = win32print.EnumPrinters(flags, None, 2)

print(f"Total: {len(printers)} printers\n")

# Find HP LaserJet entries
hp_printers = []
for p in printers:
    name = p.get('pPrinterName', '')
    if 'HP LaserJet P1007' in name or 'P1007' in name:
        hp_printers.append({
            'name': name,
            'port': p.get('pPortName', ''),
            'driver': p.get('pDriverName', ''),
            'attributes': p.get('Attributes', 0)
        })

print(f"HP LaserJet P1007 entries: {len(hp_printers)}\n")

for idx, hp in enumerate(hp_printers, 1):
    print(f"Entry {idx}:")
    print(f"  Name: {hp['name']}")
    print(f"  Port: {hp['port']}")
    print(f"  Driver: {hp['driver']}")
    print(f"  Attributes: 0x{hp['attributes']:08X}")
    print()

# Check if ports are the same
if len(hp_printers) == 2:
    print("COMPARISON:")
    print(f"  Same Port? {hp_printers[0]['port'] == hp_printers[1]['port']}")
    print(f"  Same Driver? {hp_printers[0]['driver'] == hp_printers[1]['driver']}")
    print(f"  Same Attributes? {hp_printers[0]['attributes'] == hp_printers[1]['attributes']}")
