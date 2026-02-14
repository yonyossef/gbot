"""
Google Sheets connector for the Shop Assistant bot.

Authentication: Uses a Google Service Account JSON passed as a single string
environment variable (GOOGLE_CREDENTIALS_JSON). This is ideal for Railway and
other platforms where file-based credentials are impractical.

To obtain the JSON:
1. Go to Google Cloud Console (https://console.cloud.google.com)
2. Create or select a project
3. Enable the Google Sheets API
4. IAM & Admin → Service Accounts → Create Service Account
5. Create a key (JSON) and download it
6. Share your target Google Sheet with the service account email (editor access)
7. Minify the JSON to one line and set as GOOGLE_CREDENTIALS_JSON env var
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials


def _get_credentials() -> Credentials:
    """
    Load credentials from GOOGLE_CREDENTIALS_JSON (Railway) or GOOGLE_SERVICE_ACCOUNT_FILE (local).
    Reuses the same pattern as a1/a4 projects.
    """
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # Railway: JSON string in env
    json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if json_str:
        try:
            credentials_dict = json.loads(json_str)
            return Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in GOOGLE_CREDENTIALS_JSON: {e}") from e

    # Local: file path (e.g. ../a4/service_account.json or ../a1/service_account.json)
    file_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if file_path and os.path.exists(file_path):
        return Credentials.from_service_account_file(file_path, scopes=scopes)

    raise ValueError(
        "Set GOOGLE_CREDENTIALS_JSON (Railway) or GOOGLE_SERVICE_ACCOUNT_FILE (local path). "
        "See a1/a4 for service_account.json locations."
    )


EXPECTED_HEADERS = ["Timestamp", "Item Name", "Quantity", "Status", "Sender Phone", "Supplier", "Type"]


def _looks_like_header(cell: str) -> bool:
    """Check if a cell value looks like a header (not data)."""
    if not isinstance(cell, str):
        return False
    s = cell.strip().lower()
    return s in ("timestamp", "item name", "quantity", "status", "sender phone", "supplier", "type")


def _ensure_headers(worksheet) -> None:
    """
    Ensure the worksheet has a Quantity column and correct header row.
    Handles: empty sheet, sheet with header only, sheet with 4-col data (no header).
    """
    try:
        row1 = worksheet.row_values(1)
    except Exception:
        row1 = []

    if not row1:
        # Empty sheet: add full header row
        worksheet.append_row(EXPECTED_HEADERS, value_input_option="USER_ENTERED")
        return

    # Check if we have all 7 headers (incl. Supplier, Type)
    has_type = (
        len(row1) >= 7
        and isinstance(row1[6], str)
        and row1[6].strip().lower() == "type"
    )
    if has_type:
        return
    # Check if we have all 6 headers (incl. Supplier)
    has_supplier = (
        len(row1) >= 6
        and isinstance(row1[5], str)
        and row1[5].strip().lower() == "supplier"
    )
    if has_supplier:
        worksheet.insert_cols([["Type"]], col=7, value_input_option="USER_ENTERED")
        return
    # Check if we have Quantity (col C) - older format
    has_quantity = (
        len(row1) >= 3
        and isinstance(row1[2], str)
        and row1[2].strip().lower() == "quantity"
    )
    if has_quantity and len(row1) >= 5:
        # Add Supplier column
        worksheet.insert_cols([["Supplier"]], col=6, value_input_option="USER_ENTERED")
        return

    # Row 1 has 4 columns - either old header or data
    if len(row1) == 4:
        if not _looks_like_header(row1[0]) and not _looks_like_header(row1[2]):
            # Row 1 is data: insert Quantity column first (shifts data), then add header row
            worksheet.insert_cols([[""]], col=3, value_input_option="USER_ENTERED")
            worksheet.insert_rows(
                [EXPECTED_HEADERS],
                row=1,
                value_input_option="USER_ENTERED",
            )
        else:
            # Row 1 is old header (Timestamp, Item Name, Status, Sender Phone)
            worksheet.insert_cols([["Quantity"]], col=3, value_input_option="USER_ENTERED")
        return

    # Unexpected format: ensure row 1 has all 7 headers
    if len(row1) < 7:
        worksheet.update(
            [EXPECTED_HEADERS],
            "A1:G1",
            value_input_option="USER_ENTERED",
        )


def append_inventory_row(
    item_name: str,
    sender_phone: str,
    quantity: int = 1,
    status: str = "Low Stock",
    supplier_name: Optional[str] = None,
    item_type: str = "Raw",
    sheet_key: Optional[str] = None,
    sheet_name: Optional[str] = None,
) -> None:
    """
    Append a row to the inventory sheet.

    Row format: [Timestamp, Item Name, Quantity, Status, Sender Phone, Supplier, Type]

    Args:
        item_name: The item to log (e.g., "Milk", "Beans").
        sender_phone: The WhatsApp sender's phone number.
        quantity: Quantity (default 1).
        status: Status for the row (default: "Low Stock").
        supplier_name: Supplier company name (optional).
        item_type: Raw or Prep (default: "Raw").
        sheet_key: Google Sheet ID. Uses SHEET_KEY env var if not provided.
        sheet_name: Worksheet name (e.g. "Low"). Uses SHEET_NAME env var if not provided.
    """
    key = sheet_key or os.environ.get("SHEET_KEY")
    if not key:
        raise ValueError(
            "SHEET_KEY environment variable is not set. "
            "Provide the Google Sheet ID from the sheet URL."
        )

    ws_name = sheet_name or os.environ.get("SHEET_NAME", "Low")

    creds = _get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(key)
    worksheet = spreadsheet.worksheet(ws_name)

    _ensure_headers(worksheet)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    supplier = supplier_name or ""
    row = [timestamp, item_name, quantity, status, sender_phone, supplier, item_type]
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def append_inventory_rows(
    rows: List[Tuple[str, int, Optional[str], str]],
    sender_phone: str,
    status: str = "Low Stock",
    sheet_key: Optional[str] = None,
    sheet_name: Optional[str] = None,
) -> None:
    """
    Append multiple rows to the inventory sheet in one API call.
    Each row is (item_name, quantity, supplier_name, item_type).
    """
    if not rows:
        return
    key = sheet_key or os.environ.get("SHEET_KEY")
    if not key:
        raise ValueError(
            "SHEET_KEY environment variable is not set. "
            "Provide the Google Sheet ID from the sheet URL."
        )
    ws_name = sheet_name or os.environ.get("SHEET_NAME", "Low")
    creds = _get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(key)
    worksheet = spreadsheet.worksheet(ws_name)
    _ensure_headers(worksheet)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    data = [
        [timestamp, item_name, quantity, status, sender_phone, supplier or "", item_type]
        for item_name, quantity, supplier, item_type in rows
    ]
    worksheet.append_rows(data, value_input_option="USER_ENTERED")
