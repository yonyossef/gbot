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
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


def _get_credentials() -> Credentials:
    """Load credentials from GOOGLE_CREDENTIALS_JSON environment variable."""
    json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not json_str:
        raise ValueError(
            "GOOGLE_CREDENTIALS_JSON environment variable is not set. "
            "Provide the full Service Account JSON as a string."
        )
    try:
        credentials_dict = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in GOOGLE_CREDENTIALS_JSON: {e}") from e

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    return Credentials.from_service_account_info(credentials_dict, scopes=scopes)


def append_inventory_row(
    item_name: str,
    sender_phone: str,
    status: str = "Low Stock",
    sheet_key: Optional[str] = None,
) -> None:
    """
    Append a row to the inventory sheet.

    Row format: [Timestamp, Item Name, Status, Sender Phone]

    Args:
        item_name: The item to log (e.g., "Milk", "Beans").
        sender_phone: The WhatsApp sender's phone number.
        status: Status for the row (default: "Low Stock").
        sheet_key: Google Sheet ID. Uses SHEET_KEY env var if not provided.
    """
    key = sheet_key or os.environ.get("SHEET_KEY")
    if not key:
        raise ValueError(
            "SHEET_KEY environment variable is not set. "
            "Provide the Google Sheet ID from the sheet URL."
        )

    creds = _get_credentials()
    client = gspread.authorize(creds)
    sheet = client.open_by_key(key).sheet1

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    row = [timestamp, item_name, status, sender_phone]
    sheet.append_row(row, value_input_option="USER_ENTERED")
