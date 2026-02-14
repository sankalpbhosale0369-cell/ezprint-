import win32print
import json

def dump_printers():
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = win32print.EnumPrinters(flags, None, 2)
    
    results = []
    for printer in printers:
        results.append({
            'name': printer.get('pPrinterName', 'N/A'),
            'port': printer.get('pPortName', 'N/A'),
            'driver': printer.get('pDriverName', 'N/A')
        })
    with open('printer_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Results written to printer_results.json")

if __name__ == "__main__":
    dump_printers()
