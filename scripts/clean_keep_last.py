#!/usr/bin/env python3
"""
Clean items DB and spreadsheet - keep only the last item.
Run from project root with .env loaded.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from services.items_db import _load_raw, _save_raw
from services.sheets import _get_credentials
import gspread


def main():
    # 1. Items DB - keep only last item
    items = _load_raw()
    if not items:
        print("Items DB is empty.")
    else:
        last_item = items[-1]
        _save_raw([last_item])
        print(f"Items DB: kept only '{last_item.get('name')}'")

    # 2. Spreadsheet - keep header + last data row
    sheet_key = os.environ.get("SHEET_KEY")
    sheet_name = os.environ.get("SHEET_NAME", "Low")
    if not sheet_key:
        print("SHEET_KEY not set, skipping spreadsheet.")
        return

    creds = _get_credentials()
    client = gspread.authorize(creds)
    ws = client.open_by_key(sheet_key).worksheet(sheet_name)
    all_rows = ws.get_all_values()

    if len(all_rows) <= 1:
        print("Spreadsheet has only header or is empty.")
        return

    header = all_rows[0]
    last_row = all_rows[-1]
    # Clear sheet and write header + last row only
    ws.clear()
    ws.append_row(header, value_input_option="USER_ENTERED")
    ws.append_row(last_row, value_input_option="USER_ENTERED")
    print(f"Spreadsheet: kept header + last row ({last_row[1] if len(last_row) > 1 else '?'})")


if __name__ == "__main__":
    main()
