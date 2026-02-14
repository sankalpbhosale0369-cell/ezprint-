"""
Diagnostic: Check Windows printer status for disconnected printer
"""
import win32print

print("=" * 80)
print("WINDOWS PRINTER STATUS DIAGNOSTIC")
print("=" * 80)

# Get all printers
flags = (
    win32print.PRINTER_ENUM_LOCAL |
    win32print.PRINTER_ENUM_CONNECTIONS |
    win32print.PRINTER_ENUM_NETWORK
)

printers = win32print.EnumPrinters(flags, None, 2)

print(f"\nTotal printers: {len(printers)}\n")

# Focus on HP LaserJet P1007
for p in printers:
    name = p.get('pPrinterName', '')
    if 'HP LaserJet P1007' not in name or '(Copy' in name:
        continue
    
    print("=" * 80)
    print(f"PRINTER: {name}")
    print("=" * 80)
    
    port = p.get('pPortName', '')
    attributes = p.get('Attributes', 0)
    status_from_enum = p.get('Status', 0)
    
    print(f"\nFrom EnumPrinters (Level 2):")
    print(f"  Port: {port}")
    print(f"  Attributes: {attributes} (0x{attributes:08X})")
    print(f"  Status: {status_from_enum} (0x{status_from_enum:08X})")
    
    # Try to open printer and get detailed status
    print(f"\nAttempting OpenPrinter...")
    try:
        h = win32print.OpenPrinter(name)
        print(f"  OpenPrinter: SUCCESS")
        
        try:
            # Get Level 2 info
            print(f"\n  GetPrinter(Level 2):")
            info2 = win32print.GetPrinter(h, 2)
            status2 = info2.get('Status', 0)
            print(f"    Status: {status2} (0x{status2:08X})")
            
            # Get Level 6 info (extended status)
            print(f"\n  GetPrinter(Level 6):")
            try:
                info6 = win32print.GetPrinter(h, 6)
                if isinstance(info6, dict):
                    status6 = info6.get('dwStatus', 0)
                    print(f"    dwStatus: {status6} (0x{status6:08X})")
                else:
                    print(f"    Level 6 not supported or returned: {type(info6)}")
            except Exception as e:
                print(f"    Level 6 failed: {e}")
            
        finally:
            win32print.ClosePrinter(h)
            
    except Exception as e:
        print(f"  OpenPrinter: FAILED - {e}")
    
    # Decode status flags
    print(f"\n" + "=" * 80)
    print("STATUS FLAG ANALYSIS:")
    print("=" * 80)
    
    # Use the status from GetPrinter if available, else from EnumPrinters
    status_to_check = status_from_enum
    
    status_flags = {
        0x00000001: "PAUSED",
        0x00000002: "ERROR",
        0x00000004: "PENDING_DELETION",
        0x00000008: "PAPER_JAM",
        0x00000010: "PAPER_OUT",
        0x00000020: "MANUAL_FEED",
        0x00000040: "PAPER_PROBLEM",
        0x00000080: "OFFLINE",
        0x00000100: "IO_ACTIVE",
        0x00000200: "BUSY",
        0x00000400: "PRINTING",
        0x00000800: "OUTPUT_BIN_FULL",
        0x00001000: "NOT_AVAILABLE",
        0x00002000: "WAITING",
        0x00004000: "PROCESSING",
        0x00008000: "INITIALIZING",
        0x00010000: "WARMING_UP",
        0x00020000: "TONER_LOW",
        0x00040000: "NO_TONER",
        0x00080000: "PAGE_PUNT",
        0x00100000: "USER_INTERVENTION",
        0x00200000: "OUT_OF_MEMORY",
        0x00400000: "DOOR_OPEN",
        0x00800000: "SERVER_UNKNOWN",
        0x01000000: "POWER_SAVE",
    }
    
    if status_to_check == 0:
        print("  Status = 0 (READY / NO FLAGS SET)")
    else:
        print(f"  Status = {status_to_check} (0x{status_to_check:08X})")
        print("  Active flags:")
        for flag_val, flag_name in status_flags.items():
            if status_to_check & flag_val:
                print(f"    - {flag_name} (0x{flag_val:08X})")
    
    # Check attributes
    print(f"\n" + "=" * 80)
    print("ATTRIBUTE FLAG ANALYSIS:")
    print("=" * 80)
    
    attr_flags = {
        0x00000001: "QUEUED",
        0x00000002: "DIRECT",
        0x00000004: "DEFAULT",
        0x00000008: "SHARED",
        0x00000010: "NETWORK",
        0x00000020: "HIDDEN",
        0x00000040: "LOCAL",
        0x00000080: "ENABLE_DEVQ",
        0x00000100: "KEEPPRINTEDJOBS",
        0x00000200: "DO_COMPLETE_FIRST",
        0x00000400: "WORK_OFFLINE",
        0x00000800: "ENABLE_BIDI",
        0x00001000: "RAW_ONLY",
        0x00002000: "PUBLISHED",
    }
    
    print(f"  Attributes = {attributes} (0x{attributes:08X})")
    print("  Active flags:")
    for flag_val, flag_name in attr_flags.items():
        if attributes & flag_val:
            print(f"    - {flag_name} (0x{flag_val:08X})")
    
    # Final determination
    print(f"\n" + "=" * 80)
    print("FINAL DETERMINATION:")
    print("=" * 80)
    
    # Check if WORK_OFFLINE attribute is set
    work_offline = bool(attributes & 0x00000400)
    print(f"  WORK_OFFLINE attribute: {work_offline}")
    
    # Check if OFFLINE status is set
    offline_status = bool(status_to_check & 0x00000080)
    print(f"  OFFLINE status flag: {offline_status}")
    
    # Our current logic
    if status_to_check == 0:
        our_determination = "Online (status == 0)"
    elif status_to_check & 0x00000080:
        our_determination = "Offline (OFFLINE flag set)"
    else:
        our_determination = "Online (no offline flag)"
    
    print(f"\n  Our current logic says: {our_determination}")
    
    print("\n" + "=" * 80)

print("\nDIAGNOSTIC COMPLETE")
print("=" * 80)
print("\nINSTRUCTIONS:")
print("1. Run this script WITH printer connected and powered ON")
print("2. Note the status values")
print("3. DISCONNECT the printer (unplug USB or power off)")
print("4. Run this script again")
print("5. Compare the status values")
print("=" * 80)
