@echo off
echo EzPrint MVP - Hybrid Printing System
echo ====================================
echo.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting EzPrint Shopkeeper App...
python start_shopkeeper.py
pause
