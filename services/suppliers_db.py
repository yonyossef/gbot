"""
Suppliers database - JSON file storing supplier info.

Fields: company_name, contact_name, contact_number.
"""

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SUPPLIERS_FILE = Path(os.environ.get("SUPPLIERS_DB_PATH", DATA_DIR / "suppliers.json"))


def _ensure_dir() -> None:
    SUPPLIERS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> List[dict]:
    _ensure_dir()
    if not SUPPLIERS_FILE.exists():
        return []
    try:
        with open(SUPPLIERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("suppliers", [])
    except (json.JSONDecodeError, IOError):
        return []


def _save(suppliers: List[dict]) -> None:
    _ensure_dir()
    with open(SUPPLIERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"suppliers": suppliers}, f, indent=2)


def get_all() -> List[dict]:
    """Return all suppliers: [{id, company_name, contact_name, contact_number}, ...]."""
    return _load()


def get_by_id(supplier_id: str) -> Optional[dict]:
    """Get supplier by id."""
    for s in _load():
        if s.get("id") == supplier_id:
            return s
    return None


def add_supplier(company_name: str, contact_name: str, contact_number: str) -> str:
    """Add a supplier. Returns the new supplier id."""
    suppliers = _load()
    sid = str(uuid.uuid4())[:8]
    suppliers.append({
        "id": sid,
        "company_name": company_name.strip(),
        "contact_name": contact_name.strip(),
        "contact_number": contact_number.strip(),
    })
    _save(suppliers)
    return sid


def get_numbered_list() -> List[tuple]:
    """Return [(1, supplier), (2, supplier), ...] for display."""
    return [(i + 1, s) for i, s in enumerate(_load())]
