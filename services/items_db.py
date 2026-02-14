"""
Items database - JSON file storing known item names, supplier, and type.

Type: "Raw" (raw product) or "Prep" (prepared item).
Tracks last_updated and last_updated_by when quantity is updated via Low/Lows.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ITEMS_FILE = Path(os.environ.get("ITEMS_DB_PATH", DATA_DIR / "items.json"))
PREP_CONFIG_FILE = DATA_DIR / "prep_config.json"

VALID_TYPES = ("Raw", "Prep")


def _ensure_data_dir() -> None:
    ITEMS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _normalize_item(item: dict) -> dict:
    """Ensure item has name, supplier_id, type, quantity, required_quantity, last_updated, last_updated_by."""
    name = item.get("name") or ""
    if isinstance(item.get("name"), str):
        name = item["name"].strip()
    qty = item.get("quantity")
    if not isinstance(qty, int) or qty < 0:
        qty = 1
    req = item.get("required_quantity")
    if not isinstance(req, int) or req < 0:
        req = 0
    result = {
        "name": name,
        "supplier_id": item.get("supplier_id"),
        "type": item.get("type") if item.get("type") in VALID_TYPES else "Raw",
        "quantity": qty,
        "required_quantity": req,
    }
    if item.get("last_updated"):
        result["last_updated"] = item["last_updated"]
    if item.get("last_updated_by"):
        result["last_updated_by"] = item["last_updated_by"]
    return result


def _load_raw() -> List[dict]:
    """Load items as list of {name, supplier_id, type}."""
    _ensure_data_dir()
    if not ITEMS_FILE.exists():
        return []
    try:
        with open(ITEMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("items", [])
        result = []
        for item in raw:
            if isinstance(item, dict):
                result.append(_normalize_item(item))
            else:
                result.append({"name": str(item).strip(), "supplier_id": None, "type": "Raw", "quantity": 1, "required_quantity": 0})
        return result
    except (json.JSONDecodeError, IOError):
        return []


def _save_raw(items: List[dict]) -> None:
    """Save items."""
    _ensure_data_dir()
    with open(ITEMS_FILE, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, indent=2)


def _name_key(name: str) -> str:
    return name.strip().lower() if name else ""


def is_known_item(item_name: str) -> bool:
    """Check if item exists in the database (case-insensitive)."""
    key = _name_key(item_name)
    if not key:
        return False
    for item in _load_raw():
        n = item.get("name", "")
        if _name_key(n) == key:
            return True
    return False


def _format_phone_display(phone: Optional[str]) -> str:
    """Return last 4 digits for display, or empty string."""
    if not phone:
        return ""
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) >= 4:
        return ".." + digits[-4:]
    return digits if digits else ""


def add_item(
    item_name: str,
    supplier_id: Optional[str] = None,
    item_type: str = "Raw",
    quantity: int = 1,
    updated_by: Optional[str] = None,
) -> None:
    """Add or update item in the database. Quantity is added to existing total.
    updated_by: phone/sender for last_updated_by when quantity changes via Low/Lows."""
    if not item_name or not item_name.strip():
        return
    if item_type not in VALID_TYPES:
        item_type = "Raw"
    if not isinstance(quantity, int) or quantity < 1:
        quantity = 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    items = _load_raw()
    key = _name_key(item_name)
    for item in items:
        if _name_key(item.get("name", "")) == key:
            item["supplier_id"] = supplier_id
            item["type"] = item_type
            item["quantity"] = item.get("quantity", 1) + quantity
            if updated_by:
                item["last_updated"] = now
                item["last_updated_by"] = _format_phone_display(updated_by)
            _save_raw(items)
            return
    new_item = {
        "name": item_name.strip().title(),
        "supplier_id": supplier_id,
        "type": item_type,
        "quantity": quantity,
        "required_quantity": 0,
    }
    if updated_by:
        new_item["last_updated"] = now
        new_item["last_updated_by"] = _format_phone_display(updated_by)
    items.append(new_item)
    items.sort(key=lambda x: (x.get("name", "").lower(),))
    _save_raw(items)


def get_item_supplier_id(item_name: str) -> Optional[str]:
    """Get supplier_id for an item, or None."""
    key = _name_key(item_name)
    for item in _load_raw():
        if _name_key(item.get("name", "")) == key:
            return item.get("supplier_id")
    return None


def get_item_type(item_name: str) -> str:
    """Get type for an item, default Raw."""
    key = _name_key(item_name)
    for item in _load_raw():
        if _name_key(item.get("name", "")) == key:
            return item.get("type") or "Raw"
    return "Raw"


def get_all_items() -> List[dict]:
    """Return all items: [{name, supplier_id, type, quantity, required_quantity}, ...]."""
    return _load_raw()


def get_items_by_supplier(supplier_id: str) -> List[dict]:
    """Return items that have this supplier_id."""
    if not supplier_id:
        return []
    return [i for i in _load_raw() if i.get("supplier_id") == supplier_id]


def get_prep_supplier_id() -> Optional[str]:
    """Return the default prep supplier id (set in Preferences, or from existing Prep items)."""
    _ensure_data_dir()
    if PREP_CONFIG_FILE.exists():
        try:
            with open(PREP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            sid = data.get("prep_supplier_id")
            if sid:
                return sid
        except (json.JSONDecodeError, IOError):
            pass
    # Fallback: use supplier from first Prep item
    for item in _load_raw():
        if item.get("type") == "Prep" and item.get("supplier_id"):
            return item["supplier_id"]
    return None


def get_valid_prep_supplier_id(validate_fn) -> Optional[str]:
    """Return prep supplier id only if it exists. If config has stale id, try fallback by name."""
    sid = get_prep_supplier_id()
    if sid and validate_fn(sid):
        return sid
    # Config has stale/invalid id - try to find "הכנות" by name and fix config
    from services.suppliers_db import get_all
    for s in get_all():
        name = (s.get("company_name") or "").strip()
        if "הכנות" in name or "prep" in name.lower():
            set_prep_supplier_id(s.get("id"))
            return s.get("id")
    return None


def set_prep_supplier_id(supplier_id: Optional[str]) -> None:
    """Save the default prep supplier id."""
    _ensure_data_dir()
    with open(PREP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"prep_supplier_id": supplier_id}, f, indent=2)


def set_prep_items_supplier(supplier_id: Optional[str]) -> int:
    """Set supplier_id for all items of type Prep. Returns count updated."""
    set_prep_supplier_id(supplier_id)
    items = _load_raw()
    count = 0
    for item in items:
        if item.get("type") == "Prep":
            item["supplier_id"] = supplier_id
            count += 1
    if count:
        _save_raw(items)
    return count


def set_required_quantity(item_name: str, required_quantity: int) -> bool:
    """Set required_quantity for an item. Returns True if item exists."""
    if not item_name or not item_name.strip():
        return False
    if not isinstance(required_quantity, int) or required_quantity < 0:
        return False
    items = _load_raw()
    key = _name_key(item_name)
    for item in items:
        if _name_key(item.get("name", "")) == key:
            item["required_quantity"] = required_quantity
            _save_raw(items)
            return True
    return False


def get_item_canonical_name(item_name: str) -> Optional[str]:
    """Return the stored name for an item (case-insensitive match), or None."""
    key = _name_key(item_name)
    if not key:
        return None
    for item in _load_raw():
        if _name_key(item.get("name", "")) == key:
            return item.get("name", "")
    return None


def update_item_supplier(item_name: str, supplier_id: Optional[str]) -> bool:
    """Update supplier for an item. Returns True if item exists."""
    items = _load_raw()
    key = _name_key(item_name)
    for item in items:
        if _name_key(item.get("name", "")) == key:
            item["supplier_id"] = supplier_id
            _save_raw(items)
            return True
    return False


def update_item_type(item_name: str, item_type: str) -> bool:
    """Update type for an item. Returns True if item exists."""
    if item_type not in VALID_TYPES:
        return False
    items = _load_raw()
    key = _name_key(item_name)
    for item in items:
        if _name_key(item.get("name", "")) == key:
            item["type"] = item_type
            _save_raw(items)
            return True
    return False


def rename_item(old_name: str, new_name: str) -> bool:
    """Rename an item. Returns True if renamed. Fails if new_name already exists."""
    if not new_name or not new_name.strip():
        return False
    if is_known_item(new_name) and _name_key(new_name) != _name_key(old_name):
        return False
    items = _load_raw()
    key = _name_key(old_name)
    for item in items:
        if _name_key(item.get("name", "")) == key:
            item["name"] = new_name.strip()
            items.sort(key=lambda x: (x.get("name", "").lower(),))
            _save_raw(items)
            return True
    return False


def delete_item(item_name: str) -> bool:
    """Delete an item. Returns True if deleted."""
    items = _load_raw()
    key = _name_key(item_name)
    new_items = [i for i in items if _name_key(i.get("name", "")) != key]
    if len(new_items) < len(items):
        _save_raw(new_items)
        return True
    return False
