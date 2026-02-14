# EzPrint MVP - Hybrid Printing System

## Project Structure
```
ezprint_MVP/
├── shopkeeper_app/          # Desktop application for shopkeepers
│   ├── main.py             # Main application entry point
│   ├── auth.py             # Authentication system
│   ├── dashboard.py        # Dashboard UI
│   ├── printer_manager.py  # Printer connection and management
│   └── websocket_client.py # WebSocket client for real-time communication
├── web_interface/          # Customer web interface
│   ├── app.py              # Flask web application
│   ├── templates/          # HTML templates
│   ├── static/             # CSS, JS, and assets
│   └── upload_handler.py   # File upload and processing
├── shared/                 # Shared components
│   ├── database.py         # Database models and connection
│   ├── qr_generator.py     # QR code generation
│   ├── file_processor.py   # Document processing utilities
│   └── config.py           # Configuration settings
├── logs/                   # Application logs
└── uploads/                # Temporary file storage
```

## Quick Start

### Windows Users
1. Double-click `start.bat` to automatically install dependencies and start the shopkeeper app

### Manual Installation

1. **Install Python Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start with Menu Options:**
   ```bash
   python start.py
   ```
   
   Choose from the menu:
   - Option 1: Start Web Interface only
   - Option 2: Start Shopkeeper App only  
   - Option 3: Start Both (recommended)
   - Option 4: Exit

3. **Start Shopkeeper App Directly:**
   ```bash
   python start_shopkeeper.py
   ```
   
   This directly launches the shopkeeper desktop application.

### Individual Components

1. **Run the Desktop Application:**
   ```bash
   cd shopkeeper_app
   python main.py
   ```

2. **Run the Web Interface:**
   ```bash
   cd web_interface
   python app.py
   ```

## Features

### Shopkeeper Side
- Desktop application with login/signup
- Automatic Shop ID and QR code generation
- Printer connection and management
- Real-time job monitoring dashboard
- Print job management

### Customer Side
- QR code scanning to access shop upload page
- File upload (PDF, DOCX, Images)
- Print customization options:
  - Page Range
  - Copies
  - Page Size (A4, A3, Letter, Legal)
  - Orientation (Portrait, Landscape)
  - Print Side (Single, Double)
  - Color Mode (Black & White, Color)
- Document preview
- Real-time printing confirmation

### System Features
- Secure WebSocket communication
- Real-time job updates
- Comprehensive logging
- Error handling
- Print job history

## Usage

1. **Shopkeeper Setup:**
   - Launch the desktop application
   - Sign up for a new account
   - Connect your printer
   - Share the generated QR code with customers

2. **Customer Usage:**
   - Scan the shop's QR code
   - Upload document
   - Customize print settings
   - Preview document
   - Confirm and print

## Configuration

Edit `shared/config.py` to modify:
- Database settings
- WebSocket ports
- File upload limits
- Print settings
