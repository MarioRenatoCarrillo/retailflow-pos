# RetailFlow POS

Console-based Point of Sale (POS) system built in Python.

## Features
- Cashier login with lockout (max 3 attempts)
- Inventory loading from CSV
- Sales workflow: add/remove items, cash payment, receipt generation
- Returns workflow: full receipt cancel or item-level return
- Receipt persistence using SQLite

## Run locally
```bash
python3 src/pos_app.py
