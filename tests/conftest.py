"""
Pytest fixtures for Shop Assistant e2e tests.

Mocks Google Sheets; uses temp items DB per test.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set temp DBs before importing main
TEST_ITEMS_FILE = Path(tempfile.gettempdir()) / "gbot_test_items.json"
TEST_SUPPLIERS_FILE = Path(tempfile.gettempdir()) / "gbot_test_suppliers.json"


@pytest.fixture(autouse=True)
def temp_items_db():
    """Use a temp items.json for each test; clear before/after."""
    os.environ["ITEMS_DB_PATH"] = str(TEST_ITEMS_FILE)
    if TEST_ITEMS_FILE.exists():
        TEST_ITEMS_FILE.unlink()
    yield
    if TEST_ITEMS_FILE.exists():
        TEST_ITEMS_FILE.unlink()
    os.environ.pop("ITEMS_DB_PATH", None)


@pytest.fixture(autouse=True)
def temp_suppliers_db():
    """Use a temp suppliers.json for each test."""
    os.environ["SUPPLIERS_DB_PATH"] = str(TEST_SUPPLIERS_FILE)
    if TEST_SUPPLIERS_FILE.exists():
        TEST_SUPPLIERS_FILE.unlink()
    yield
    if TEST_SUPPLIERS_FILE.exists():
        TEST_SUPPLIERS_FILE.unlink()
    os.environ.pop("SUPPLIERS_DB_PATH", None)


@pytest.fixture
def mock_sheets():
    """Mock append_inventory_row and append_inventory_rows so we don't need Google credentials."""
    mock_combined = MagicMock()
    with patch("main.append_inventory_row", mock_combined), patch("main.append_inventory_rows", mock_combined):
        yield mock_combined


@pytest.fixture
def mock_suppliers_empty():
    """Mock suppliers to return empty list (skip supplier selection in most tests)."""
    with patch("main.get_numbered_list", return_value=[]), patch(
        "main.get_by_id", return_value=None
    ):
        yield


@pytest.fixture
def client(mock_sheets, mock_suppliers_empty):
    """FastAPI test client with mocked sheets and empty suppliers."""
    from services.i18n import reset_user_langs, set_user_lang
    from main import (
        app,
        _multi_mode_sessions,
        _pending_new_item,
        _pending_supplier_selection,
        _pending_type_selection,
        _pending_lang_selection,
        _pending_preferences,
        _pending_edit,
        _pending_add_supplier,
        _pending_supplier_details,
        _pending_lows_fill,
        _pending_need_fill,
    )
    _multi_mode_sessions.clear()
    _pending_new_item.clear()
    _pending_supplier_selection.clear()
    _pending_type_selection.clear()
    _pending_lang_selection.clear()
    _pending_preferences.clear()
    _pending_edit.clear()
    _pending_add_supplier.clear()
    _pending_supplier_details.clear()
    _pending_lows_fill.clear()
    _pending_need_fill.clear()
    reset_user_langs()
    set_user_lang("whatsapp:+15551234567", "en")  # Tests assert on English
    return TestClient(app)


@pytest.fixture
def client_suppliers(mock_sheets):
    """Client with real (temp) suppliers DB - for supplier management tests."""
    from services.i18n import reset_user_langs, set_user_lang
    from main import (
        app,
        _multi_mode_sessions,
        _pending_new_item,
        _pending_supplier_selection,
        _pending_type_selection,
        _pending_lang_selection,
        _pending_preferences,
        _pending_edit,
        _pending_add_supplier,
        _pending_supplier_details,
        _pending_lows_fill,
        _pending_need_fill,
    )
    _multi_mode_sessions.clear()
    _pending_new_item.clear()
    _pending_supplier_selection.clear()
    _pending_type_selection.clear()
    _pending_lang_selection.clear()
    _pending_preferences.clear()
    _pending_edit.clear()
    _pending_add_supplier.clear()
    _pending_supplier_details.clear()
    _pending_lows_fill.clear()
    _pending_need_fill.clear()
    reset_user_langs()
    set_user_lang("whatsapp:+15551234567", "en")  # Tests assert on English
    return TestClient(app)


def post_whatsapp(client: TestClient, body: str, from_phone: str = "whatsapp:+15551234567") -> str:
    """POST to /whatsapp, return the message text from TwiML."""
    resp = client.post(
        "/whatsapp",
        data={"Body": body, "From": from_phone, "To": "whatsapp:+15559876543"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert "application/xml" in resp.headers.get("content-type", "")
    # Parse <Message>...</Message> - returns first message (or all concatenated for multi)
    import re
    msgs = re.findall(r"<Message>([^<]*)</Message>", resp.text, re.DOTALL)
    assert msgs, f"Expected TwiML Message in: {resp.text[:200]}"
    return msgs[0].strip() if len(msgs) == 1 else "\n\n".join(m.strip() for m in msgs)
