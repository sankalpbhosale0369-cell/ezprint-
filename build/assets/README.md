# Build Assets

This directory contains assets used during the build and installer creation process.

## Files

### license.txt
End User License Agreement displayed during installation. This is already created and ready to use.

### installer_icon.ico
Installer icon - **use the existing icon from `assets/icons/ezprint.ico`**.
The NSIS script is configured to use this icon automatically.

### installer_banner.bmp (TO BE CREATED)
Welcome page banner for the NSIS installer.

**Requirements:**
- Dimensions: 164 x 314 pixels
- Format: BMP (Windows Bitmap)
- Color depth: 24-bit recommended
- Content: Company branding, product name, visual appeal

**How to create:**
1. Use any image editor (Photoshop, GIMP, Paint.NET, etc.)
2. Create a 164x314 pixel canvas
3. Add your branding elements:
   - Company logo
   - Product name: "EzPrint Agent"
   - Tagline or descriptive text
   - Professional background/gradient
4. Save as BMP format
5. Place in this directory as `installer_banner.bmp`

**Temporary Solution:**
If you don't have a custom banner ready, you can:
1. Use NSIS's default header instead - edit `build/config/installer.nsi`:
   - Comment out the line: `!define MUI_WELCOMEFINISHPAGE_BITMAP "..\..\assets\installer_banner.bmp"`
2. Or use the NSIS default banner from: `${NSISDIR}\Contrib\Graphics\Wizard\nsis3-branding.bmp`
3. Copy and customize the default NSIS banner

**Online Tools:**
- Canva (canva.com) - Free design tool
- Figma (figma.com) - Professional design tool
- GIMP (gimp.org) - Free open-source image editor

## Notes

The installer will still work without a custom banner if you use NSIS defaults. The banner is purely cosmetic and doesn't affect functionality.
