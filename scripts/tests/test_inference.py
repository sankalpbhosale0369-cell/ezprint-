
import logging

class MockPrinterManager:
    def __init__(self):
        self._initialize_printer_capabilities()
        
    def _initialize_printer_capabilities(self):
        printer_patterns = [
            ("HP LaserJet P1", False, False, "single"),
            ("HP 1020", False, False, "single"),
            ("HP 1018", False, False, "single"),
            ("HP 1005", False, False, "single"),
            ("HP 1100", False, False, "single"),
            ("HP 1200", False, False, "single"),
            ("HP 1300", False, False, "single"),
            ("HP LaserJet M402d", False, True, "duplex"),
            ("HP LaserJet P2055", False, True, "duplex"),
            ("HP 2055", False, True, "duplex"),
            ("HP LaserJet Pro MFP M426", False, True, "duplex"),
            ("HP 1320", False, True, "duplex"),
            ("HP 2015", False, True, "duplex"),
            ("HP 2035", False, True, "duplex"),
            ("HP 3015", False, True, "duplex"),
            ("HP 4015", False, True, "duplex"),
            ("HP 4250", False, True, "duplex"),
            ("HP 4350", False, True, "duplex"),
            ("HP 5200", False, True, "duplex"),
            ("HP LaserJet", False, False, "single"),
            ("HP Color LaserJet", True, True, "color"),
            ("HP CP", True, True, "color"),
            ("HP M", True, True, "color"),
            ("HP DeskJet", True, False, "color"),
            ("HP OfficeJet", True, True, "color"),
            ("HP Envy", True, False, "color"),
            ("HP Photosmart", True, False, "color"),
            ("Canon PIXMA", True, False, "color"),
            ("Canon imageCLASS", False, True, "duplex"),
            ("Canon LBP", False, True, "duplex"),
            ("Canon i-SENSYS", False, True, "duplex"),
            ("Epson Stylus", True, False, "color"),
            ("Epson WorkForce", True, True, "color"),
            ("Epson Expression", True, False, "color"),
            ("Epson EcoTank", True, False, "color"),
            ("Brother HL", False, True, "duplex"),
            ("Brother MFC", True, True, "color"),
            ("Brother DCP", True, False, "color"),
            ("Samsung ML", False, True, "duplex"),
            ("Samsung CLP", True, True, "color"),
            ("Samsung Xpress", False, True, "duplex"),
            ("Xerox Phaser", True, True, "color"),
            ("Xerox WorkCentre", True, True, "color"),
            ("Lexmark E", False, True, "duplex"),
            ("Lexmark C", True, True, "color"),
            ("Lexmark X", True, True, "color"),
            ("Color", True, False, "color"),
            ("Laser", False, True, "duplex"),
        ]
        self._printer_patterns = printer_patterns

    def _infer_printer_capabilities(self, printer_name):
        if not printer_name:
            return None
        printer_name_upper = printer_name.upper()
        for pattern, is_color, is_duplex, printer_type in self._printer_patterns:
            if pattern.upper() in printer_name_upper:
                return {
                    "is_color": is_color,
                    "is_duplex": is_duplex,
                    "type": printer_type
                }
        return {
            "is_color": False,
            "is_duplex": False,
            "type": "single"
        }

pm = MockPrinterManager()
test_name = "Canon G2000 series Printer"
caps = pm._infer_printer_capabilities(test_name)
print(f"Capabilities for '{test_name}': {caps}")
