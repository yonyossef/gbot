"""
E2E tests for Shop Assistant WhatsApp webhook.

Covers: single item, quantity, multi-item mode, items DB, new-item flow, ! reserved.
"""

import os

import pytest
import httpx

from tests.conftest import post_whatsapp

# Base URL for live server tests (GET with timeout to debug page loading)
TEST_PAGE_URL = os.environ.get("TEST_PAGE_URL", "http://localhost:8001/test")
PAGE_LOAD_TIMEOUT = float(os.environ.get("PAGE_LOAD_TIMEOUT", "5.0"))


class TestHealthEndpoints:
    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "running"

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_test_page(self, client):
        r = client.get("/test")
        assert r.status_code == 200
        assert b"Shop Assistant" in r.content

    def test_test_page_no_cache_headers(self, client):
        """No-cache headers prevent browser from using stuck cached response (causes 'no requests' hang)."""
        r = client.get("/test")
        cache_control = r.headers.get("cache-control", "").lower()
        assert "no-store" in cache_control or "no-cache" in cache_control

    def test_test_page_no_blocking_resources(self, client):
        """Ensure /test page has no render-blocking external resources that can cause loading to hang."""
        r = client.get("/test")
        assert r.status_code == 200
        html = r.content.decode("utf-8", errors="replace")
        assert "fonts.googleapis.com" not in html
        assert "fonts.gstatic.com" not in html

    def test_test_page_complete_response(self, client):
        """Ensure /test returns complete HTML with proper headers."""
        r = client.get("/test")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "").lower()
        html = r.content.decode("utf-8", errors="replace")
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html
        assert len(html) > 500
        assert '<script src="http' not in html and "<script src='http" not in html

    def test_test_page_has_fetch_timeout(self, client):
        """Ensure chat has fetch timeout to prevent indefinite hang when sending."""
        r = client.get("/test")
        html = r.content.decode("utf-8", errors="replace")
        assert "AbortController" in html
        assert "controller.abort()" in html


@pytest.mark.live_server
class TestPageLoadLive:
    """Real HTTP GET with timeout - run against live server to debug page loading hang.
    Run: pytest -m live_server -v  (requires server on port 8001)
    Skips if server unreachable (e.g. in CI without server).
    """

    def test_test_page_loads_within_timeout(self):
        """GET /test must complete within timeout. Fails if server hangs. Skips if unreachable."""
        base = TEST_PAGE_URL.rsplit("/test", 1)[0] or "http://localhost:8001"
        try:
            with httpx.Client(timeout=PAGE_LOAD_TIMEOUT) as client:
                r = client.get(TEST_PAGE_URL)
        except httpx.ConnectError as e:
            pytest.skip(f"Server unreachable at {TEST_PAGE_URL}: {e}")
        assert r.status_code == 200
        assert b"Shop Assistant" in r.content
        assert "text/html" in r.headers.get("content-type", "").lower()

    def test_test_minimal_loads_within_timeout(self):
        """GET /test-minimal - bare HTML. If /test hangs but this works, issue is chat.html content."""
        base = TEST_PAGE_URL.rsplit("/test", 1)[0] or "http://localhost:8001"
        url = f"{base}/test-minimal"
        try:
            with httpx.Client(timeout=PAGE_LOAD_TIMEOUT) as client:
                r = client.get(url)
        except httpx.ConnectError as e:
            pytest.skip(f"Server unreachable at {url}: {e}")
        assert r.status_code == 200
        assert b"OK" in r.content


class TestParser:
    def test_parse_item_and_quantity(self):
        from main import parse_item_and_quantity
        assert parse_item_and_quantity("Low Milk") == ("Milk", 1)
        assert parse_item_and_quantity("Low Milk 3") == ("Milk", 3)
        assert parse_item_and_quantity("Milk 2") == ("Milk", 2)
        assert parse_item_and_quantity("Beans") == ("Beans", 1)
        assert parse_item_and_quantity("") == ("Unknown Item", 1)

    def test_has_explicit_low(self):
        from main import _has_explicit_low
        assert _has_explicit_low("Low Almond 2") is True
        assert _has_explicit_low("Almond 2") is False


class TestSingleItemMode:
    """Single item: Low X, X, X 2 (default = Low)."""

    def test_low_new_item_adds(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")  # asks type
        msg = post_whatsapp(client, "1")  # Raw
        assert "✅" in msg and "Milk" in msg
        mock_sheets.assert_called_once()

    def test_low_item_with_quantity(self, client, mock_sheets):
        post_whatsapp(client, "Low Almond 2")  # asks type
        msg = post_whatsapp(client, "1")  # Raw
        assert "✅" in msg and "Almond" in msg and "2" in msg
        mock_sheets.assert_called_once()
        call_kw = mock_sheets.call_args.kwargs
        assert call_kw["item_name"] == "Almond"
        assert call_kw["quantity"] == 2

    def test_default_low_existing_item(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")  # add with Raw
        msg = post_whatsapp(client, "Milk 3")  # no Low, existing
        assert "✅" in msg and "Milk" in msg
        mock_sheets.assert_called()

    def test_default_low_new_item_asks_confirmation(self, client):
        msg = post_whatsapp(client, "Almond 2")
        assert "❓" in msg or "not in the list" in msg
        assert "yes" in msg.lower() or "no" in msg.lower()


class TestNewItemConfirmation:
    """New item without Low: confirm with yes/y/ye or no/n/!."""

    def test_yes_adds_item(self, client, mock_sheets):
        post_whatsapp(client, "Almond 2")  # asks
        post_whatsapp(client, "yes")  # -> type selection
        msg = post_whatsapp(client, "1")  # Raw
        assert "✅" in msg and "Almond" in msg
        mock_sheets.assert_called()

    def test_y_adds_item(self, client, mock_sheets):
        post_whatsapp(client, "Almond 2")
        post_whatsapp(client, "y")
        msg = post_whatsapp(client, "1")
        assert "✅" in msg

    def test_ye_adds_item(self, client, mock_sheets):
        post_whatsapp(client, "Almond 2")
        post_whatsapp(client, "ye")
        msg = post_whatsapp(client, "1")
        assert "✅" in msg

    def test_no_cancels(self, client):
        post_whatsapp(client, "Almond 2")
        msg = post_whatsapp(client, "no")
        assert "Cancelled" in msg

    def test_n_cancels(self, client):
        post_whatsapp(client, "Almond 2")
        msg = post_whatsapp(client, "n")
        assert "Cancelled" in msg

    def test_exclamation_cancels(self, client):
        post_whatsapp(client, "Almond 2")
        msg = post_whatsapp(client, "!")
        assert "Cancelled" in msg

    def test_exclamation_cancels_type_selection(self, client):
        post_whatsapp(client, "Low Almond 2")
        msg = post_whatsapp(client, "!")
        assert "Cancelled" in msg

    def test_ken_adds_item(self, client, mock_sheets):
        post_whatsapp(client, "Almond 2")
        post_whatsapp(client, "כן")  # Hebrew yes
        msg = post_whatsapp(client, "1")
        assert "✅" in msg and "Almond" in msg
        mock_sheets.assert_called()

    def test_k_adds_item(self, client, mock_sheets):
        post_whatsapp(client, "Almond 2")
        post_whatsapp(client, "כ")  # Hebrew yes (short)
        msg = post_whatsapp(client, "1")
        assert "✅" in msg
        mock_sheets.assert_called()

    def test_lo_cancels(self, client):
        post_whatsapp(client, "Almond 2")
        msg = post_whatsapp(client, "לא")  # Hebrew no
        assert "Cancelled" in msg

    def test_l_cancels(self, client):
        post_whatsapp(client, "Almond 2")
        msg = post_whatsapp(client, "ל")  # Hebrew no (short)
        assert "Cancelled" in msg


class TestReservedExclamation:
    """! is reserved: not an item, ends multi mode, cancels."""

    def test_exclamation_single_mode_no_pending(self, client):
        msg = post_whatsapp(client, "!")
        assert "reserved" in msg.lower() or "!" in msg

    def test_exclamation_cancels_pending(self, client):
        post_whatsapp(client, "Almond 2")
        msg = post_whatsapp(client, "!")
        assert "Cancelled" in msg


class TestMultiItemMode:
    """Lows -> items (existing only) -> ! to finish."""

    def test_lows_starts_mode(self, client):
        msg = post_whatsapp(client, "Lows")
        assert "Multi-item" in msg and "!" in msg

    def test_multi_mode_new_item_rejected(self, client):
        post_whatsapp(client, "Lows")
        msg = post_whatsapp(client, "Almond 2")
        assert "❌" in msg or "not in the list" in msg
        assert "Low" in msg

    def test_multi_mode_existing_item_added(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")  # add to DB
        post_whatsapp(client, "Lows")
        msg = post_whatsapp(client, "Milk 2")
        assert "📝" in msg and "Milk" in msg

    def test_multi_mode_exclamation_finishes(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Low Beans")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Lows")
        post_whatsapp(client, "Milk 2")
        post_whatsapp(client, "Beans")
        msg = post_whatsapp(client, "!")
        assert "✅" in msg
        assert "Milk" in msg and "Beans" in msg
        assert mock_sheets.call_count >= 2

    def test_lows_with_first_item(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "Lows Milk 3")
        assert "Multi-item" in msg and "Milk" in msg
        msg2 = post_whatsapp(client, "!")
        assert "✅" in msg2


class TestLowsFill:
    """Lows <supplier_regex> – easy fill: show items by supplier, ask quantity for each (empty=0)."""

    def test_lows_fill_shows_items_and_asks_quantity(self, client_suppliers, mock_sheets):
        """Lows <supplier> starts easy fill, shows first item, asks quantity."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Edward Bakery")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Croissant")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Low Bread")
        post_whatsapp(client_suppliers, "1")
        msg = post_whatsapp(client_suppliers, "Lows Edward")
        assert "Croissant" in msg or "Bread" in msg
        assert "Quantity" in msg or "כמות" in msg
        assert "1/" in msg

    def test_lows_fill_empty_quantity_is_zero(self, client_suppliers, mock_sheets):
        """Empty reply = quantity 0, skips item."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")  # Raw
        post_whatsapp(client_suppliers, "1")  # Acme
        post_whatsapp(client_suppliers, "Lows Acme")
        msg = post_whatsapp(client_suppliers, " ")  # empty/space = 0
        # Only 1 item, we finish; empty qty = 0 so nothing added
        assert "No items" in msg or "Added" in msg or "נוסף" in msg or "נוספו" in msg

    def test_lows_fill_adds_items_with_quantity(self, client_suppliers, mock_sheets):
        """Quantity > 0 adds item to list."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")  # Raw
        post_whatsapp(client_suppliers, "1")  # Acme
        post_whatsapp(client_suppliers, "Lows Acme")
        msg = post_whatsapp(client_suppliers, "3")  # quantity 3 for Milk
        assert "✅" in msg and "Milk" in msg
        assert mock_sheets.called

    def test_lows_fill_no_match(self, client):
        """Lows <unknown_supplier> returns no match."""
        msg = post_whatsapp(client, "Lows NonexistentSupplierXYZ")
        assert "match" in msg.lower() or "תואם" in msg or "No items" in msg

    def test_lows_fill_back_cancels(self, client_suppliers, mock_sheets):
        """Back cancels Lows fill mode."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")  # Raw
        post_whatsapp(client_suppliers, "1")  # Acme
        post_whatsapp(client_suppliers, "Lows Acme")
        msg = post_whatsapp(client_suppliers, "Back")
        assert "Cancelled" in msg or "בוטל" in msg


class TestNeedFill:
    """Need <supplier_regex> – easy fill: show items by supplier, ask required quantity for each (empty=0)."""

    def test_need_fill_shows_items_and_asks_quantity(self, client_suppliers, mock_sheets):
        """Need <supplier> starts easy fill, shows first item, asks required quantity."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Edward Bakery")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Croissant")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Low Bread")
        post_whatsapp(client_suppliers, "1")
        msg = post_whatsapp(client_suppliers, "Need Edward")
        assert "Croissant" in msg or "Bread" in msg
        assert "Required" in msg or "כמות" in msg or "נדרשת" in msg
        assert "1/" in msg

    def test_need_fill_sets_required_quantity(self, client_suppliers, mock_sheets):
        """Required quantity > 0 updates item."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Need Acme")
        msg = post_whatsapp(client_suppliers, "10")
        assert "✅" in msg and "Milk" in msg
        assert "Updated" in msg or "עודכנו" in msg

    def test_need_fill_empty_quantity_is_zero(self, client_suppliers, mock_sheets):
        """Empty reply = required 0."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Need Acme")
        msg = post_whatsapp(client_suppliers, " ")
        assert "Updated" in msg or "עודכנו" in msg or "No items" in msg

    def test_need_fill_back_cancels(self, client_suppliers, mock_sheets):
        """Back cancels Need fill mode."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Need Acme")
        msg = post_whatsapp(client_suppliers, "Back")
        assert "Cancelled" in msg or "בוטל" in msg


class TestListCommand:
    """List command shows all items with name, qty/required, type, supplier."""

    def test_list_empty(self, client):
        msg = post_whatsapp(client, "List")
        assert "No items" in msg

    def test_list_shows_items(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Low Beans")
        post_whatsapp(client, "2")  # Prep
        msg = post_whatsapp(client, "List")
        assert "Items" in msg
        assert "Milk" in msg
        assert "Beans" in msg
        assert "Raw" in msg
        assert "Prep" in msg

    def test_list_shows_qty_and_required(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Need Milk 10")
        msg = post_whatsapp(client, "List")
        assert "Milk" in msg
        assert "1/10" in msg or "10" in msg

    def test_list_filter_by_supplier(self, client_suppliers, mock_sheets):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Edward Bakery")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Croissant")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Other Shop")
        post_whatsapp(client_suppliers, "Jane")
        post_whatsapp(client_suppliers, "+0987654321")
        post_whatsapp(client_suppliers, "Low Bread")
        post_whatsapp(client_suppliers, "1")
        msg = post_whatsapp(client_suppliers, "List Edward")
        assert "Edward" in msg
        assert "Croissant" in msg
        assert "Bread" not in msg

    def test_list_invalid_regex(self, client):
        msg = post_whatsapp(client, "List [invalid")
        assert "Invalid" in msg or "invalid" in msg.lower()


class TestListExtCommand:
    """ListExt shows extended table with last report date and user."""

    def test_listext_empty(self, client):
        msg = post_whatsapp(client, "ListExt")
        assert "No items" in msg

    def test_listext_shows_items_with_last_updated(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "ListExt")
        assert "Milk" in msg
        assert "Items" in msg or "פריטים" in msg
        # Should have date format YYYY-MM-DD and user (..XXXX)
        assert "|" in msg
        # last_updated and last_updated_by columns
        assert "-" in msg or ".." in msg or "202" in msg

    def test_listext_hebrew_command(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "ממ")  # Hebrew ListExt
        assert "Milk" in msg

    def test_help_shows_listext(self, client):
        msg = post_whatsapp(client, "Help")
        assert "ListExt" in msg or "ממ" in msg or "מלאימורחב" in msg


class TestNeedCommand:
    """Need command sets required quantity for existing items."""

    def test_need_sets_required(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "Need Milk 10")
        assert "Required" in msg or "10" in msg
        assert "Milk" in msg

    def test_n_sets_required(self, client, mock_sheets):
        post_whatsapp(client, "Low Beans")
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "N Beans 5")
        assert "Required" in msg or "5" in msg

    def test_need_unknown_item(self, client):
        msg = post_whatsapp(client, "Need UnknownItem 10")
        assert "not in the list" in msg or "Unknown" in msg

    def test_hebrew_need_sets_required(self, client, mock_sheets):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        post_whatsapp(client, "פריט חלב")  # Low Milk
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "צריך חלב 10")  # Need Milk 10
        assert "10" in msg and ("חלב" in msg or "Milk" in msg)


class TestEditCommand:
    """Edit command: change supplier, type, rename, delete."""

    def test_edit_item_not_found(self, client):
        msg = post_whatsapp(client, "Edit UnknownItem")
        assert "not in the list" in msg or "Unknown" in msg

    def test_edit_shows_menu(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")  # Raw
        msg = post_whatsapp(client, "Edit Milk")
        assert "Milk" in msg
        assert "1." in msg and "4." in msg
        assert "supplier" in msg.lower() or "ספק" in msg
        assert "Delete" in msg or "מחק" in msg

    def test_edit_change_type(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")  # Raw
        post_whatsapp(client, "Edit Milk")
        msg = post_whatsapp(client, "2")  # Change type
        assert "1" in msg and "2" in msg  # Raw/Prep options
        msg = post_whatsapp(client, "2")  # Prep
        assert "Prep" in msg or "מוכן" in msg
        assert "Milk" in msg

    def test_edit_rename(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "3")  # Rename
        msg = post_whatsapp(client, "Yogurt")
        assert "Yogurt" in msg and ("Renamed" in msg or "שונה" in msg)
        msg = post_whatsapp(client, "List")
        assert "Yogurt" in msg and "Milk" not in msg

    def test_edit_delete(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "4")  # Delete
        msg = post_whatsapp(client, "yes")
        assert "deleted" in msg.lower() or "נמחק" in msg
        assert "Milk" in msg
        msg = post_whatsapp(client, "List")
        assert "Milk" not in msg or "No items" in msg or "אין" in msg

    def test_edit_e_shortcut(self, client, mock_sheets):
        post_whatsapp(client, "Low Beans")
        post_whatsapp(client, "1")
        msg = post_whatsapp(client, "E Beans")
        assert "Beans" in msg and "1." in msg

    def test_edit_exclamation_cancels(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        msg = post_whatsapp(client, "!")
        assert "Cancelled" in msg or "בוטל" in msg

    def test_edit_back_cancels(self, client, mock_sheets):
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        msg = post_whatsapp(client, "Back")
        assert "Cancelled" in msg or "בוטל" in msg

    def test_edit_delete_hebrew_ken_confirms(self, client, mock_sheets):
        """Hebrew 'כ' (yes) in delete confirm should delete the item."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "4")  # Delete
        msg = post_whatsapp(client, "כ")  # Hebrew yes
        assert "deleted" in msg.lower() or "נמחק" in msg
        assert "Milk" in msg
        msg = post_whatsapp(client, "List")
        assert "Milk" not in msg or "No items" in msg or "אין" in msg

    def test_edit_delete_hebrew_lo_cancels(self, client, mock_sheets):
        """Hebrew 'ל' (no) in delete confirm should cancel."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "4")  # Delete
        msg = post_whatsapp(client, "ל")  # Hebrew no
        assert "Cancelled" in msg or "בוטל" in msg
        msg = post_whatsapp(client, "List")
        assert "Milk" in msg

    def test_edit_delete_invalid_asks_yes_no(self, client, mock_sheets):
        """Invalid input in delete confirm should ask yes/no, not 'add new item'."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "4")  # Delete
        msg = post_whatsapp(client, "maybe")
        assert "yes" in msg.lower() or "כן" in msg or "לא" in msg
        assert "add" not in msg.lower() and "פריט" not in msg

    def test_edit_delete_full_hebrew_flow(self, client, mock_sheets):
        """Full Hebrew flow: Pref→Hebrew, ער חלב, 4, כ → item deleted."""
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        post_whatsapp(client, "פריט חלב")  # Low Milk
        post_whatsapp(client, "1")
        post_whatsapp(client, "ער חלב")  # Edit Milk
        post_whatsapp(client, "4")  # Delete
        msg = post_whatsapp(client, "כ")  # Hebrew yes
        assert "נמחק" in msg or "deleted" in msg.lower()
        assert "חלב" in msg or "Milk" in msg

    def test_edit_prep_to_raw_selects_other_supplier(self, client_suppliers, mock_sheets):
        """When changing Prep→Raw, must select a supplier other than prep supplier."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Prep Supplier")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501111111")
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Raw Supplier")
        post_whatsapp(client_suppliers, "Jane")
        post_whatsapp(client_suppliers, "0502222222")
        post_whatsapp(client_suppliers, "Low Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Prep (no supplier selection)
        post_whatsapp(client_suppliers, "Edit Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Change type
        msg = post_whatsapp(client_suppliers, "1")  # Raw -> shows supplier list
        assert "supplier" in msg.lower() or "ספק" in msg
        assert "Raw Supplier" in msg
        assert "Prep Supplier" not in msg
        msg = post_whatsapp(client_suppliers, "1")  # Raw Supplier (only other in list)
        assert "Raw" in msg or "גלם" in msg
        assert "Egg Salad" in msg

    def test_edit_raw_to_prep_sets_prep_supplier(self, client_suppliers, mock_sheets):
        """When changing Raw→Prep, supplier is set to default prep supplier."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Prep Co")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501111111")
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Raw Co")
        post_whatsapp(client_suppliers, "Jane")
        post_whatsapp(client_suppliers, "0502222222")
        post_whatsapp(client_suppliers, "Pref")
        post_whatsapp(client_suppliers, "2")  # Default prep supplier
        post_whatsapp(client_suppliers, "1")  # Prep Co
        post_whatsapp(client_suppliers, "Low Egg Salad")
        post_whatsapp(client_suppliers, "1")  # Raw
        post_whatsapp(client_suppliers, "2")  # Raw Co (second supplier)
        post_whatsapp(client_suppliers, "Edit Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Change type
        msg = post_whatsapp(client_suppliers, "2")  # Prep
        assert "Prep" in msg or "מוכן" in msg
        assert "Egg Salad" in msg
        msg = post_whatsapp(client_suppliers, "List")
        assert "Prep Co" in msg
        assert "Egg Salad" in msg

    def test_edit_change_supplier(self, client_suppliers, mock_sheets):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501234567")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")  # Raw
        post_whatsapp(client_suppliers, "1")  # Acme
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Beta")
        post_whatsapp(client_suppliers, "Jane")
        post_whatsapp(client_suppliers, "0509876543")
        post_whatsapp(client_suppliers, "Edit Milk")
        msg = post_whatsapp(client_suppliers, "1")  # Change supplier
        assert "1." in msg and "2." in msg
        msg = post_whatsapp(client_suppliers, "2")  # Beta
        assert "Beta" in msg and ("supplier" in msg.lower() or "ספק" in msg)
        msg = post_whatsapp(client_suppliers, "List")
        assert "Beta" in msg and "Milk" in msg

    def test_edit_raw_to_raw_no_supplier_prompt(self, client, mock_sheets):
        """Raw→Raw: change type to Raw when already Raw - no supplier selection."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")  # Raw
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "2")  # Change type
        msg = post_whatsapp(client, "1")  # Raw (already Raw)
        assert "Raw" in msg or "גלם" in msg
        assert "set" in msg.lower() or "הוגדר" in msg

    def test_edit_prep_to_raw_no_other_supplier(self, client_suppliers, mock_sheets):
        """Prep→Raw when only one supplier: show no-other-supplier message."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Prep Only")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501111111")
        post_whatsapp(client_suppliers, "Low Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Prep
        post_whatsapp(client_suppliers, "Edit Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Change type
        msg = post_whatsapp(client_suppliers, "1")  # Raw
        assert "other" in msg.lower() or "אחר" in msg or "Supa" in msg or "סח" in msg

    def test_edit_rename_to_existing_fails(self, client, mock_sheets):
        """Rename to existing item name should fail."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Low Cheese")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "3")  # Rename
        msg = post_whatsapp(client, "Cheese")
        assert "exists" in msg.lower() or "קיים" in msg or "Cheese" in msg
        post_whatsapp(client, "!")  # Cancel edit flow
        msg = post_whatsapp(client, "List")
        assert "Milk" in msg and "Cheese" in msg

    def test_edit_rename_empty_rejected(self, client, mock_sheets):
        """Empty rename should be rejected."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        post_whatsapp(client, "3")  # Rename
        msg = post_whatsapp(client, "   ")
        assert "empty" in msg.lower() or "ריק" in msg or "name" in msg.lower()

    def test_edit_menu_invalid_input(self, client, mock_sheets):
        """Invalid input at edit menu should ask for number 1-4."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        msg = post_whatsapp(client, "x")
        assert "1" in msg and ("4" in msg or "number" in msg.lower())
        msg = post_whatsapp(client, "5")
        assert "1" in msg or "4" in msg or "number" in msg.lower()

    def test_edit_back_from_supplier_selection(self, client_suppliers, mock_sheets):
        """Back from supplier selection returns to edit menu."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501234567")
        post_whatsapp(client_suppliers, "Low Milk")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "Edit Milk")
        post_whatsapp(client_suppliers, "1")  # Change supplier
        msg = post_whatsapp(client_suppliers, "Back")
        assert "Milk" in msg and ("1." in msg or "2." in msg)

    def test_edit_back_from_type_raw_supplier(self, client_suppliers, mock_sheets):
        """Back from Prep→Raw supplier selection returns to type menu."""
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Prep Co")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501111111")
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Raw Co")
        post_whatsapp(client_suppliers, "Jane")
        post_whatsapp(client_suppliers, "0502222222")
        post_whatsapp(client_suppliers, "Low Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Prep
        post_whatsapp(client_suppliers, "Edit Egg Salad")
        post_whatsapp(client_suppliers, "2")  # Change type
        post_whatsapp(client_suppliers, "1")  # Raw -> supplier list
        msg = post_whatsapp(client_suppliers, "Back")
        assert "Type" in msg or "סוג" in msg
        post_whatsapp(client_suppliers, "2")  # Prep - keep as Prep, exit edit
        msg = post_whatsapp(client_suppliers, "List")
        assert "Egg Salad" in msg

    def test_edit_no_suppliers_change_supplier(self, client, mock_sheets):
        """Edit menu 1 (change supplier) with no suppliers shows message."""
        post_whatsapp(client, "Low Milk")
        post_whatsapp(client, "1")
        post_whatsapp(client, "Edit Milk")
        msg = post_whatsapp(client, "1")  # Change supplier
        assert "No suppliers" in msg or "Supa" in msg or "סח" in msg

    def test_edit_hebrew_command(self, client_suppliers, mock_sheets):
        """Hebrew ערוך/ער opens edit menu (requires Hebrew mode)."""
        post_whatsapp(client_suppliers, "Pref")
        post_whatsapp(client_suppliers, "1")
        post_whatsapp(client_suppliers, "2")  # Hebrew
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "TestCo")
        post_whatsapp(client_suppliers, "John")
        post_whatsapp(client_suppliers, "0501111111")
        post_whatsapp(client_suppliers, "פריט חלב")
        post_whatsapp(client_suppliers, "1")  # Raw
        post_whatsapp(client_suppliers, "1")  # TestCo
        msg = post_whatsapp(client_suppliers, "ערוך חלב")
        assert "חלב" in msg or "Milk" in msg
        assert "1." in msg


class TestLangCommand:
    """Lang command: show languages, select, use for replies."""

    def test_lang_shows_supported(self, client):
        post_whatsapp(client, "Pref")
        msg = post_whatsapp(client, "1")  # Language option
        assert "Supported languages" in msg or "שפות" in msg
        assert "1." in msg and "2." in msg

    def test_lang_select_english(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")  # Language
        msg = post_whatsapp(client, "1")  # English
        assert "Language set" in msg or "English" in msg

    def test_lang_select_hebrew(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")  # Language
        msg = post_whatsapp(client, "2")  # Hebrew
        assert "עברית" in msg or "Language" in msg

    def test_lang_affects_replies(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "List")
        assert "פריטים" in msg or "אין" in msg  # Hebrew "Items" or "No"

    def test_exclamation_cancels_lang_selection(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")  # Language
        msg = post_whatsapp(client, "!")
        assert "בוטל" in msg or "Cancelled" in msg


class TestHelpCommand:
    """Help shows all commands."""

    def test_english_commands_case_insensitive(self, client):
        """Full English commands work regardless of uppercase/lowercase."""
        from services.i18n import set_user_lang

        # Use unique phone per command to avoid pending-state interference; set English
        commands = [
            ("HELP", "Commands"),
            ("help", "Commands"),
            ("LIST", "Items"),
            ("list", "Items"),
            ("PREF", "Preferences"),
            ("pref", "Preferences"),
            ("LOWS", "multi"),
            ("lows", "multi"),
            ("SUP", "Suppliers"),
            ("sup", "Suppliers"),
            ("Ext", "Items"),
            ("EXT", "Items"),
        ]
        for i, (cmd, expect) in enumerate(commands):
            phone = f"whatsapp:+1555{i:07d}"
            set_user_lang(phone, "en")
            msg = post_whatsapp(client, cmd, from_phone=phone)
            assert expect.lower() in msg.lower(), f"{cmd} failed: expected {expect!r} in {msg[:80]!r}"

    def test_help_shows_commands(self, client):
        msg = post_whatsapp(client, "Help")
        assert "Commands" in msg or "פקודות" in msg
        assert "Low" in msg or "פריט" in msg
        assert "List" in msg or "מלאי" in msg
        assert "Edit" in msg or "ערוך" in msg

    def test_help_command_detail(self, client):
        msg = post_whatsapp(client, "Help Low")
        assert "Usage" in msg
        assert "Low Milk" in msg or "Milk" in msg

    def test_help_hebrew_command_detail(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "עזרה מלאי")
        assert "שימוש" in msg or "Usage" in msg
        assert "מ" in msg or "מלאי" in msg

    def test_help_unknown_command(self, client):
        msg = post_whatsapp(client, "Help FooBar")
        assert "Unknown" in msg or "לא ידוע" in msg or "FooBar" in msg


class TestHebrewCommands:
    """Hebrew commands work when in Hebrew mode."""

    def test_hebrew_list_command(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "מ")  # List
        assert "פריטים" in msg or "אין" in msg

    def test_hebrew_help_command(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "ע")  # Help
        assert "פקודות" in msg

    def test_hebrew_low_adds_item(self, client, mock_sheets):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        post_whatsapp(client, "פריט חלב")  # Low Milk
        msg = post_whatsapp(client, "1")  # Raw
        assert "✅" in msg and "חלב" in msg
        mock_sheets.assert_called_once()

    def test_hebrew_pam_lows_mode(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "פם")  # Lows
        assert "ריבוי" in msg or "multi" in msg.lower()

    def test_hebrew_mem_sofit_lows_mode(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "ם")  # Lows shortcut
        assert "ריבוי" in msg or "multi" in msg.lower()

    def test_s_shortcut_lows_mode(self, client):
        msg = post_whatsapp(client, "S")  # Lows shortcut
        assert "multi" in msg.lower() or "ריבוי" in msg

    def test_hebrew_shafa_lang(self, client):
        post_whatsapp(client, "Pref")
        post_whatsapp(client, "1")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "שפה")  # Pref (opens settings)
        assert "שפות" in msg or "הגדרות" in msg or "language" in msg.lower() or "Preferences" in msg


class TestInvalidItem:
    def test_empty_body_invalid(self, client):
        msg = post_whatsapp(client, "")
        assert "Invalid" in msg or "Unknown" in msg


class TestBackCommand:
    """Back / B / חזור / ח – go back one step."""

    def test_back_cancels_new_item(self, client):
        post_whatsapp(client, "Low UnknownX")
        msg = post_whatsapp(client, "Back")
        assert "Cancelled" in msg or "בוטל" in msg

    def test_back_in_add_supplier_step2(self, client_suppliers):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme")
        msg = post_whatsapp(client_suppliers, "Back")
        assert "Company" in msg or "חברה" in msg

    def test_back_no_step(self, client):
        msg = post_whatsapp(client, "Back")
        assert "Nothing" in msg or "אין" in msg

    def test_cancel_same_as_back(self, client):
        post_whatsapp(client, "Low UnknownY")
        msg = post_whatsapp(client, "Cancel")
        assert "Cancelled" in msg or "בוטל" in msg


class TestReservedWords:
    """Standalone command chars/words are reserved, not treated as items."""

    def test_hebrew_tsadi_reserved(self, client):
        post_whatsapp(client, "Lang")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "צ")  # standalone צ
        assert "reserved" in msg.lower() or "שמור" in msg
        assert "add" not in msg.lower() or "פריט" not in msg

    def test_hebrew_lamed_reserved(self, client):
        post_whatsapp(client, "Lang")
        post_whatsapp(client, "2")  # Hebrew
        msg = post_whatsapp(client, "ל")  # standalone ל (not in pending)
        assert "reserved" in msg.lower() or "שמור" in msg

    def test_need_alone_reserved(self, client):
        msg = post_whatsapp(client, "Need")
        assert "reserved" in msg.lower()


class TestSupplierManagement:
    """Sup, Supa."""

    def test_suppliers_empty(self, client_suppliers):
        msg = post_whatsapp(client_suppliers, "Sup")
        assert "No suppliers" in msg or "Add" in msg

    def test_add_supplier_flow(self, client_suppliers):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme Corp")
        post_whatsapp(client_suppliers, "John Doe")
        msg = post_whatsapp(client_suppliers, "+1234567890")
        assert "✅" in msg and "Acme" in msg

    def test_suppliers_list(self, client_suppliers):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme Corp")
        post_whatsapp(client_suppliers, "John Doe")
        post_whatsapp(client_suppliers, "+1234567890")
        msg = post_whatsapp(client_suppliers, "Sup")
        assert "Acme" in msg
        assert "number" in msg.lower() or "מספר" in msg

    def test_suppliers_select_shows_details_and_chat_link(self, client_suppliers):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme Corp")
        post_whatsapp(client_suppliers, "John Doe")
        post_whatsapp(client_suppliers, "+972501234567")
        post_whatsapp(client_suppliers, "Sup")
        msg = post_whatsapp(client_suppliers, "1")
        assert "Acme" in msg
        assert "John" in msg
        assert "wa.me" in msg


class TestSupplierSelection:
    """New item with supplier selection."""

    def test_new_item_asks_type_first_when_suppliers_exist(self, client_suppliers):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme Corp")
        post_whatsapp(client_suppliers, "John Doe")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Almond 2")
        msg = post_whatsapp(client_suppliers, "yes")
        assert "Type" in msg or "סוג" in msg
        assert "1" in msg and "2" in msg

    def test_supplier_selection_adds_item(self, client_suppliers, mock_sheets):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme Corp")
        post_whatsapp(client_suppliers, "John Doe")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Almond 2")
        post_whatsapp(client_suppliers, "1")  # supplier
        msg = post_whatsapp(client_suppliers, "1")  # Raw
        assert "✅" in msg and "Almond" in msg
        mock_sheets.assert_called_once()
        assert mock_sheets.call_args.kwargs.get("item_type") == "Raw"

    def test_type_prep_adds_as_prep(self, client_suppliers, mock_sheets):
        post_whatsapp(client_suppliers, "Supa")
        post_whatsapp(client_suppliers, "Acme Corp")
        post_whatsapp(client_suppliers, "John Doe")
        post_whatsapp(client_suppliers, "+1234567890")
        post_whatsapp(client_suppliers, "Low Salad 1")
        msg = post_whatsapp(client_suppliers, "2")  # Prep (no supplier selection)
        assert "✅" in msg and "Salad" in msg
        assert mock_sheets.call_args.kwargs.get("item_type") == "Prep"
