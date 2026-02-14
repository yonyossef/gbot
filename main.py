"""
Shop Assistant WhatsApp Bot - FastAPI backend.

Webhook endpoint for Twilio to receive incoming WhatsApp messages.
Logs inventory needs (e.g., "Low Milk", "Beans") to a Google Sheet.
Uses items.json DB: new items via "Low" or confirmation; multi-mode accepts existing only.
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from twilio.request_validator import RequestValidator

from services.i18n import get_supported_langs, get_user_lang, set_user_lang, t
from services.items_db import (
    add_item,
    delete_item,
    get_all_items,
    get_item_canonical_name,
    get_item_supplier_id,
    get_items_by_supplier,
    get_item_type,
    get_valid_prep_supplier_id,
    is_known_item,
    rename_item,
    set_prep_items_supplier,
    set_required_quantity,
    update_item_supplier,
    update_item_type,
)
from services.sheets import append_inventory_row, append_inventory_rows
from services.suppliers_db import add_supplier, get_all, get_by_id, get_numbered_list

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

# Multi-item mode: key = sender_phone, value = list of (item, quantity) tuples
_multi_mode_sessions: Dict[str, List[Tuple[str, int]]] = {}

# Pending new-item confirmation: key = sender_phone, value = (item_name, quantity)
_pending_new_item: Dict[str, Tuple[str, int]] = {}

# Pending supplier selection: key = sender_phone, value = (item_name, quantity)
_pending_supplier_selection: Dict[str, Tuple[str, int]] = {}

# Pending add supplier: key = sender_phone, value = step number (1=company, 2=contact, 3=number)
_pending_add_supplier: Dict[str, dict] = {}

# Pending type selection: key = sender_phone, value = (item_name, quantity, supplier_id)
_pending_type_selection: Dict[str, Tuple[str, int, Optional[str]]] = {}

# Pending language selection: key = sender_phone (user sent "Lang", awaiting 1/2)
_pending_lang_selection: Dict[str, bool] = {}

# Pending supplier details: key = sender_phone (user sent "Sup", awaiting number to show details)
_pending_supplier_details: Dict[str, bool] = {}

# Pending preferences: key = sender_phone, value = "menu" | "lang" | "prep_supplier"
_pending_preferences: Dict[str, str] = {}

# Pending edit: key = sender_phone, value = {"step": str, "item_name": str, ...}
_pending_edit: Dict[str, dict] = {}

# Pending Lows fill (פם <supplier_regex>): key = sender_phone, value = {"items": [...], "index": int, "collected": [(name,qty)]}
_pending_lows_fill: Dict[str, dict] = {}

# Pending Need fill (Need <supplier_regex>): key = sender_phone, value = {"items": [...], "index": int, "collected": [(name,req_qty)]}
_pending_need_fill: Dict[str, dict] = {}

app = FastAPI(
    title="Shop Assistant Bot",
    description="WhatsApp bot for logging inventory needs to Google Sheets",
    version="0.1.0",
)

# Preload chat - served with no-cache headers to prevent browser using stuck cached response
_CHAT_HTML: str = (STATIC_DIR / "chat.html").read_text(encoding="utf-8")


def _normalize_command(body: str, lang: str) -> str:
    """
    Convert Hebrew commands to English equivalents.
    ListExt (מלאימורחב/ממ) is normalized for all languages.
    """
    if not body:
        return body
    text = body.strip()
    # ListExt: מלאימורחב or ממ (any language - Hebrew commands)
    if re.match(r"^(מלאימורחב|ממ)(\s|$)", text):
        if re.match(r"^(מלאימורחב|ממ)\s+.+", text):
            text = re.sub(r"^(מלאימורחב|ממ)\s+", "ListExt ", text, count=1)
        else:
            text = "ListExt"
        return text
    if lang != "he":
        return body
    # Low: פריט or פ (with optional space + rest)
    if re.match(r"^(פריט|פ)(\s|$)", text):
        text = re.sub(r"^(פריט|פ)(\s+)", "Low ", text, count=1)
        text = re.sub(r"^(פריט|פ)$", "Low ", text, count=1)
    # Sup: ספק or ס (standalone)
    elif re.match(r"^(ספק|ס)\s*$", text):
        text = "Sup"
    # Supa: ספקחדש or סח (standalone)
    elif re.match(r"^(ספקחדש|סח)\s*$", text):
        text = "Supa"
    # List: מלאי or מ (standalone or with filter)
    elif re.match(r"^(מלאי|מ)(\s|$)", text):
        if re.match(r"^(מלאי|מ)\s+.+", text):
            text = re.sub(r"^(מלאי|מ)\s+", "List ", text, count=1)
        else:
            text = "List"
    # Help: עזרה or ע (standalone or with command)
    elif re.match(r"^(עזרה|ע)(\s|$)", text):
        m = re.match(r"^(עזרה|ע)\s+(.+)$", text)
        if m:
            raw = m.group(2).strip()
            cmd_map = {"מלאי": "List", "מ": "List", "מלאימורחב": "ListExt", "ממ": "ListExt",
                       "ספק": "Sup", "ס": "Sup", "ספקחדש": "Supa", "סח": "Supa",
                       "פריט": "Low", "פ": "Low", "צריך": "Need", "צ": "Need", "ערוך": "Edit", "ער": "Edit",
                       "עזרה": "Help", "ע": "Help", "פם": "Lows", "ם": "Lows", "שפה": "Pref", "הגדרות": "Pref", "ה": "Pref",
                       "חזור": "Back", "ח": "Back", "בטל": "Back", "צא": "Back"}
            text = "Help " + cmd_map.get(raw, raw)
        else:
            text = "Help"
    # Need: צריך or צ (only when followed by space + content; standalone is reserved)
    elif re.match(r"^(צריך|צ)\s+.+", text):
        text = re.sub(r"^(צריך|צ)(\s+)", "Need ", text, count=1)
    # Edit: ערוך or ער (only when followed by space + content)
    elif re.match(r"^(ערוך|ער)\s+.+", text):
        text = re.sub(r"^(ערוך|ער)(\s+)", "Edit ", text, count=1)
    # Lows: פם or ם (standalone or with item)
    elif re.match(r"^(פם|ם)(\s|$)", text):
        text = re.sub(r"^(פם|ם)(\s+)", "Lows ", text, count=1)
        text = re.sub(r"^(פם|ם)\s*$", "Lows", text, count=1)
    # Lang: שפה (standalone) -> Pref (language moved to preferences)
    elif re.match(r"^שפה\s*$", text):
        text = "Pref"
    # Pref: הגדרות or ה (standalone)
    elif re.match(r"^(הגדרות|ה)\s*$", text):
        text = "Pref"
    # Back: חזור, ח, בטל, צא (standalone)
    elif re.match(r"^(חזור|ח|בטל|צא)\s*$", text):
        text = "Back"
    return text


def _has_explicit_low(text: str) -> bool:
    """True if message starts with 'Low ' or 'L ' (case-insensitive)."""
    t = text.strip() if text else ""
    return bool(t and re.match(r"^(?:low|l)\s+", t, re.IGNORECASE))


def _format_wa_link(phone: str) -> str:
    """Format phone for WhatsApp wa.me link. Returns empty string if invalid."""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) >= 9:
        digits = "972" + digits[1:]  # Israel: 050... -> 97250...
    elif not digits.startswith(("972", "1", "44", "49")):
        return ""  # Unknown format
    return f"https://wa.me/{digits}"


def parse_item_and_quantity(body: str) -> Tuple[str, int]:
    """
    Extract item name and quantity from a message.

    Rules:
    - "Low Milk 3" or "Milk 3" -> ("Milk", 3)
    - "Beans" or "Low Beans" -> ("Beans", 1)
    - Item followed by number at end = quantity; default is 1.
    """
    if not body or not body.strip():
        return ("Unknown Item", 1)

    text = body.strip()

    # Strip "low " or "l " prefix (case-insensitive)
    match = re.match(r"^(?:low|l)\s+(.+)$", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # Check for "item N" at end (quantity)
    qty_match = re.search(r"\s+(\d+)\s*$", text)
    if qty_match:
        quantity = int(qty_match.group(1))
        item = text[: qty_match.start()].strip()
    else:
        quantity = 1
        item = text

    item = item.title() if item else "Unknown Item"
    return (item, quantity)


def _parse_item_raw(text: str) -> Optional[Tuple[str, int]]:
    """Parse item and optional quantity (for multi-item mode). Returns None if empty/invalid."""
    if not text or not text.strip():
        return None
    item, qty = parse_item_and_quantity(text)
    if item == "Unknown Item":
        return None
    return (item, qty)


def _t(phone: str, key: str, **kwargs) -> str:
    """Get translated string for user's language."""
    return t(key, get_user_lang(phone), **kwargs)


def _escape_xml(s: str) -> str:
    """Escape XML special chars for Message body."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def twiml_response(message: str) -> Response:
    """Return a TwiML response for Twilio."""
    body = _escape_xml(message)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{body}</Message>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


def twiml_response_multi(messages: List[str]) -> Response:
    """Return TwiML with multiple Message elements (Twilio sends each separately)."""
    parts = [f"    <Message>{_escape_xml(m)}</Message>" for m in messages]
    twiml = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Response>\n" + "\n".join(parts) + "\n</Response>"
    return Response(content=twiml, media_type="application/xml")


@app.get("/")
async def root() -> dict:
    """Health check / root endpoint."""
    return {"name": "Shop Assistant Bot", "status": "running"}


@app.get("/health")
async def health() -> dict:
    """Health check for Railway and monitoring."""
    return {"status": "healthy"}


@app.get("/test-minimal")
async def test_minimal() -> HTMLResponse:
    """Minimal HTML for debugging - if this loads but /test hangs, the issue is chat.html content."""
    return HTMLResponse(
        content="<!DOCTYPE html><html><body>OK</body></html>",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/test")
async def test_chat() -> HTMLResponse:
    """WhatsApp-style chat UI. No-cache headers prevent browser from using stuck cached response."""
    return HTMLResponse(
        content=_CHAT_HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/intro")
async def intro(lang: Optional[str] = None) -> dict:
    """Return intro message for chat UI. lang: en|he, defaults to app default."""
    from services.i18n import DEFAULT_LANG
    code = lang if lang in ("en", "he") else DEFAULT_LANG
    return {"intro": t("intro", code)}


@app.get("/guide")
async def user_guide() -> FileResponse:
    """User guide for the Shop Assistant bot."""
    guide_path = Path(__file__).parent / "USER_GUIDE.md"
    return FileResponse(guide_path, media_type="text/markdown")


def _validate_twilio_request(request: Request, form_dict: dict) -> bool:
    """Validate that the request is from Twilio using X-Twilio-Signature."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not auth_token:
        return True  # Skip validation if token not configured (e.g. local dev)
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    validator = RequestValidator(auth_token)
    return validator.validate(url, form_dict, signature)


def _do_append_and_confirm(
    item_name: str,
    quantity: int,
    sender_phone: str,
    supplier_id: Optional[str] = None,
    item_type: str = "Raw",
) -> str:
    """Append to sheet, add to items DB, return success message."""
    supplier_name = None
    if supplier_id:
        s = get_by_id(supplier_id)
        supplier_name = s.get("company_name", "") if s else None
    try:
        append_inventory_row(
            item_name=item_name,
            sender_phone=sender_phone,
            quantity=quantity,
            status="Low Stock",
            supplier_name=supplier_name,
            item_type=item_type,
        )
        add_item(item_name, supplier_id, item_type, quantity, updated_by=sender_phone)
        if quantity > 1:
            return _t(sender_phone, "added_to_list_qty", item_name=item_name, quantity=quantity)
        return _t(sender_phone, "added_to_list", item_name=item_name)
    except (ValueError, Exception) as e:
        print(f"[ERROR] Sheets append failed: {e}")
        return _t(sender_phone, "could_not_add", item_name=item_name)


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    """
    Twilio webhook for incoming WhatsApp messages.

    Supports:
    - Single item: "Low Milk", "Milk 2" (default = Low), "!" reserved
    - Pending new-item: reply yes/no to add new item
    - Multi-item mode: "Lows" then items (existing only), "!" to finish
    """
    form = await request.form()
    form_dict = {k: v for k, v in form.items() if isinstance(v, str)}

    if not _validate_twilio_request(request, form_dict):
        return Response(status_code=403, content="Invalid signature")

    body_text = (form_dict.get("Body", "") or "").strip()
    sender_phone = form_dict.get("From", "Unknown")

    # Normalize Hebrew commands to English when in Hebrew mode
    body_text = _normalize_command(body_text, get_user_lang(sender_phone))

    # --- Reserved: "!" is never an item ---
    if body_text == "!":
        if sender_phone in _pending_new_item:
            _pending_new_item.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_supplier_selection:
            _pending_supplier_selection.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_type_selection:
            _pending_type_selection.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_preferences:
            _pending_preferences.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_edit:
            _pending_edit.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_add_supplier:
            _pending_add_supplier.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_supplier_details:
            _pending_supplier_details.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_lows_fill:
            _pending_lows_fill.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone in _pending_need_fill:
            _pending_need_fill.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        if sender_phone not in _multi_mode_sessions:
            return twiml_response(_t(sender_phone, "exclamation_reserved"))

    # --- Back: go back one step in any pending state ---
    if re.match(r"^(?:back|b|exit|quit|cancel)\s*$", body_text, re.IGNORECASE):
        if sender_phone in _pending_add_supplier:
            state = _pending_add_supplier[sender_phone]
            step = state.get("step", 1)
            if step == 3:
                state["step"] = 2
                return twiml_response(_t(sender_phone, "contact_name_prompt"))
            if step == 2:
                state["step"] = 1
                return twiml_response(_t(sender_phone, "company_name_prompt"))
            _pending_add_supplier.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_supplier_details:
            _pending_supplier_details.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_preferences:
            _pending_preferences.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_type_selection:
            _pending_type_selection.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_supplier_selection:
            item_name, quantity = _pending_supplier_selection.pop(sender_phone)
            _pending_type_selection[sender_phone] = (item_name, quantity, None)
            return twiml_response(_t(sender_phone, "type_select"))
        if sender_phone in _pending_new_item:
            _pending_new_item.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_lows_fill:
            _pending_lows_fill.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_need_fill:
            _pending_need_fill.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        if sender_phone in _pending_edit:
            state = _pending_edit[sender_phone]
            if state.get("step") == "type_raw_supplier":
                state["step"] = "type"
                state.pop("type_raw_suppliers", None)
                return twiml_response(_t(sender_phone, "type_select"))
            if state.get("step") in ("supplier", "type", "rename", "delete_confirm"):
                state["step"] = "menu"
                item_name = state.get("item_name", "")
                sid = get_item_supplier_id(item_name)
                itype = get_item_type(item_name)
                s = get_by_id(sid) if sid else None
                sup_name = s.get("company_name", "") if s else _t(sender_phone, "list_no_supplier")
                type_label = _t(sender_phone, "type_prep") if itype == "Prep" else _t(sender_phone, "type_raw")
                lines = [
                    _t(sender_phone, "edit_menu_header", item_name=item_name, supplier=sup_name, type_label=type_label),
                    "",
                    "  1. " + _t(sender_phone, "edit_change_supplier"),
                    "  2. " + _t(sender_phone, "edit_change_type"),
                    "  3. " + _t(sender_phone, "edit_rename"),
                    "  4. " + _t(sender_phone, "edit_delete"),
                    "",
                    _t(sender_phone, "reply_with_number"),
                ]
                return twiml_response("\n".join(lines))
            _pending_edit.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "back_cancelled"))
        return twiml_response(_t(sender_phone, "back_no_step"))

    # --- Pending Lows fill: quantity for current item (empty = 0) ---
    # Check early so numeric replies (0, 3, etc.) are not consumed by other handlers
    if sender_phone in _pending_lows_fill:
        state = _pending_lows_fill[sender_phone]
        items_list = state["items"]
        idx = state["index"]
        try:
            qty = int(body_text.strip()) if body_text.strip() else 0
        except ValueError:
            qty = 0
        if qty < 0:
            qty = 0
        if qty > 0:
            it = items_list[idx]
            state["collected"].append((it["name"], qty))
        idx += 1
        if idx >= len(items_list):
            _pending_lows_fill.pop(sender_phone, None)
            collected = state["collected"]
            if not collected:
                return twiml_response(_t(sender_phone, "multi_mode_ended_empty"))
            rows_for_sheets: List[Tuple[str, int, Optional[str], str]] = []
            for item_name, qty in collected:
                sid = get_item_supplier_id(item_name)
                itype = get_item_type(item_name)
                s = get_by_id(sid) if sid else None
                sup_name = s.get("company_name", "") if s else None
                rows_for_sheets.append((item_name, qty, sup_name, itype))
            try:
                append_inventory_rows(rows_for_sheets, sender_phone)
            except (ValueError, Exception) as e:
                print(f"[ERROR] Sheets batch append failed: {e}")
            added: List[str] = []
            for item_name, qty in collected:
                sid = get_item_supplier_id(item_name)
                itype = get_item_type(item_name)
                add_item(item_name, sid, itype, qty, updated_by=sender_phone)
                added.append(f"{item_name}×{qty}" if qty > 1 else item_name)
            items_str = "  • " + "\n  • ".join(added)
            return twiml_response(_t(sender_phone, "added_items", count=len(added), items=items_str))
        state["index"] = idx
        next_it = items_list[idx]
        return twiml_response(_t(sender_phone, "lows_fill_quantity_prompt", item_name=next_it["name"], num=idx + 1, total=len(items_list)))

    # --- Pending Need fill: required quantity for current item (empty = 0) ---
    if sender_phone in _pending_need_fill:
        state = _pending_need_fill[sender_phone]
        items_list = state["items"]
        idx = state["index"]
        try:
            req_qty = int(body_text.strip()) if body_text.strip() else 0
        except ValueError:
            req_qty = 0
        if req_qty < 0:
            req_qty = 0
        it = items_list[idx]
        state["collected"].append((it["name"], req_qty))
        idx += 1
        if idx >= len(items_list):
            _pending_need_fill.pop(sender_phone, None)
            collected = state["collected"]
            if not collected:
                return twiml_response(_t(sender_phone, "need_fill_ended_empty"))
            updated: List[str] = []
            for item_name, req_qty in collected:
                if set_required_quantity(item_name, req_qty):
                    updated.append(f"{item_name}→{req_qty}" if req_qty else item_name)
            if not updated:
                return twiml_response(_t(sender_phone, "need_fill_ended_empty"))
            items_str = "  • " + "\n  • ".join(updated)
            return twiml_response(_t(sender_phone, "need_fill_updated", count=len(updated), items=items_str))
        state["index"] = idx
        next_it = items_list[idx]
        return twiml_response(_t(sender_phone, "need_fill_quantity_prompt", item_name=next_it["name"], num=idx + 1, total=len(items_list)))

    # --- Pending edit (Edit Milk -> menu -> supplier/type/rename/delete) ---
    if sender_phone in _pending_edit:
        state = _pending_edit[sender_phone]
        step = state.get("step", "menu")
        item_name = state.get("item_name", "")

        if step == "menu":
            try:
                num = int(body_text.strip())
                if num == 1:
                    suppliers = get_numbered_list()
                    if not suppliers:
                        _pending_edit.pop(sender_phone, None)
                        return twiml_response(_t(sender_phone, "edit_no_suppliers"))
                    state["step"] = "supplier"
                    lines = [_t(sender_phone, "select_supplier"), ""]
                    for i, s in suppliers:
                        lines.append(f"  {i}. {s.get('company_name', '?')}")
                    lines.extend(["", _t(sender_phone, "reply_with_number")])
                    return twiml_response("\n".join(lines))
                if num == 2:
                    state["step"] = "type"
                    return twiml_response(_t(sender_phone, "type_select"))
                if num == 3:
                    state["step"] = "rename"
                    return twiml_response(_t(sender_phone, "edit_rename_prompt", item_name=item_name))
                if num == 4:
                    state["step"] = "delete_confirm"
                    return twiml_response(_t(sender_phone, "edit_delete_confirm", item_name=item_name))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "reply_number_range", max=4))

        if step == "supplier":
            suppliers = get_numbered_list()
            try:
                num = int(body_text.strip())
                if 1 <= num <= len(suppliers):
                    _, sup = suppliers[num - 1]
                    sid = sup.get("id", "")
                    if update_item_supplier(item_name, sid):
                        _pending_edit.pop(sender_phone, None)
                        return twiml_response(_t(sender_phone, "edit_supplier_updated", item_name=item_name, company=sup.get("company_name", "?")))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "reply_number_range", max=len(suppliers)))

        if step == "type":
            try:
                num = int(body_text.strip())
                if num == 1:
                    # Prep → Raw: must choose a supplier other than the prep supplier
                    current_type = get_item_type(item_name)
                    current_sid = get_item_supplier_id(item_name)
                    if current_type == "Prep" and current_sid:
                        all_suppliers = get_numbered_list()
                        filtered = [s for _, s in all_suppliers if s.get("id") != current_sid]
                        other_suppliers = [(i, s) for i, s in enumerate(filtered, 1)]
                        if not other_suppliers:
                            _pending_edit.pop(sender_phone, None)
                            return twiml_response(_t(sender_phone, "edit_prep_to_raw_no_other_supplier"))
                        state["step"] = "type_raw_supplier"
                        state["type_raw_suppliers"] = other_suppliers
                        lines = [_t(sender_phone, "edit_prep_to_raw_select_supplier"), ""]
                        for i, s in other_suppliers:
                            lines.append(f"  {i}. {s.get('company_name', '?')}")
                        lines.extend(["", _t(sender_phone, "reply_with_number")])
                        return twiml_response("\n".join(lines))
                    if update_item_type(item_name, "Raw"):
                        _pending_edit.pop(sender_phone, None)
                        return twiml_response(_t(sender_phone, "edit_type_updated", item_name=item_name, type_label=_t(sender_phone, "type_raw")))
                if num == 2:
                    # Raw → Prep: set supplier to default prep supplier (must exist)
                    prep_sid = get_valid_prep_supplier_id(get_by_id)
                    if prep_sid:
                        update_item_supplier(item_name, prep_sid)
                    if update_item_type(item_name, "Prep"):
                        _pending_edit.pop(sender_phone, None)
                        return twiml_response(_t(sender_phone, "edit_type_updated", item_name=item_name, type_label=_t(sender_phone, "type_prep")))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "reply_type_raw_prep"))

        if step == "type_raw_supplier":
            suppliers = state.get("type_raw_suppliers", [])
            try:
                num = int(body_text.strip())
                if 1 <= num <= len(suppliers):
                    _, sup = suppliers[num - 1]
                    sid = sup.get("id", "")
                    if update_item_supplier(item_name, sid) and update_item_type(item_name, "Raw"):
                        _pending_edit.pop(sender_phone, None)
                        return twiml_response(_t(sender_phone, "edit_type_updated", item_name=item_name, type_label=_t(sender_phone, "type_raw")))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "reply_number_range", max=len(suppliers)))

        if step == "rename":
            new_name = body_text.strip()
            if not new_name:
                return twiml_response(_t(sender_phone, "edit_rename_empty"))
            if is_known_item(new_name) and get_item_canonical_name(new_name) != item_name:
                return twiml_response(_t(sender_phone, "edit_rename_exists", new_name=new_name))
            if rename_item(item_name, new_name):
                _pending_edit.pop(sender_phone, None)
                return twiml_response(_t(sender_phone, "edit_renamed", old_name=item_name, new_name=new_name))
            return twiml_response(_t(sender_phone, "edit_rename_failed"))

        if step == "delete_confirm":
            body_clean = body_text.strip()
            body_lower = body_clean.lower()
            if body_lower in ("yes", "y", "ye") or body_clean in ("כן", "כ"):
                if delete_item(item_name):
                    _pending_edit.pop(sender_phone, None)
                    return twiml_response(_t(sender_phone, "edit_deleted", item_name=item_name))
            if body_lower in ("no", "n") or body_clean in ("לא", "ל"):
                _pending_edit.pop(sender_phone, None)
                return twiml_response(_t(sender_phone, "cancelled"))
            return twiml_response(_t(sender_phone, "edit_delete_reply_yes_no"))

    # --- Pending add supplier (multi-step) ---
    if sender_phone in _pending_add_supplier:
        state = _pending_add_supplier[sender_phone]
        step = state.get("step", 1)
        if step == 1:
            state["company_name"] = body_text
            state["step"] = 2
            return twiml_response(_t(sender_phone, "contact_name_prompt"))
        if step == 2:
            state["contact_name"] = body_text
            state["step"] = 3
            return twiml_response(_t(sender_phone, "contact_number_prompt"))
        if step == 3:
            sid = add_supplier(
                state["company_name"],
                state["contact_name"],
                body_text,
            )
            _pending_add_supplier.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "supplier_added", company_name=state["company_name"]))

    # --- Pending supplier details (user sent Sup, awaiting number) ---
    if sender_phone in _pending_supplier_details:
        suppliers = get_numbered_list()
        if not suppliers:
            _pending_supplier_details.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "no_suppliers_yet"))
        try:
            num = int(body_text.strip())
            if 1 <= num <= len(suppliers):
                _, sup = suppliers[num - 1]
                _pending_supplier_details.pop(sender_phone, None)
                company = sup.get("company_name", "?")
                contact = sup.get("contact_name", "")
                phone = sup.get("contact_number", "")
                wa_url = _format_wa_link(phone) if phone else ""
                chat_line = _t(sender_phone, "supplier_chat", wa_url=wa_url) if wa_url else ""
                details_msg = _t(
                    sender_phone, "supplier_details",
                    company=company, contact=contact, contact_number=phone, chat_line=chat_line
                )
                # Order in separate message for easy copy-paste to supplier
                supplier_items = get_items_by_supplier(sup.get("id", ""))
                item_lines = []
                for it in supplier_items:
                    qty = it.get("quantity", 1)
                    req = it.get("required_quantity", 0)
                    order_qty = max(0, req - qty)
                    item_lines.append(_t(sender_phone, "supplier_item_line", name=it.get("name", "?"), order_qty=order_qty))
                order_body = "\n".join(item_lines) if item_lines else _t(sender_phone, "supplier_no_items")
                order_msg = _t(sender_phone, "order_header") + "\n" + order_body
                return twiml_response_multi([details_msg, order_msg])
        except ValueError:
            pass
        return twiml_response(_t(sender_phone, "reply_number_range", max=len(suppliers)))

    # --- Pending type selection (type first for new item) ---
    if sender_phone in _pending_type_selection:
        item_name, quantity, supplier_id = _pending_type_selection[sender_phone]
        try:
            num = int(body_text.strip())
            if num == 1:
                # Raw: show supplier list (or add with None if no suppliers)
                _pending_type_selection.pop(sender_phone, None)
                suppliers = get_numbered_list()
                if suppliers:
                    _pending_supplier_selection[sender_phone] = (item_name, quantity)
                    lines = [_t(sender_phone, "select_supplier"), ""]
                    for i, s in suppliers:
                        lines.append(f"  {i}. {s.get('company_name', '?')}")
                    lines.extend(["", _t(sender_phone, "reply_with_number")])
                    return twiml_response("\n".join(lines))
                reply = _do_append_and_confirm(
                    item_name, quantity, sender_phone, None, "Raw"
                )
                return twiml_response(reply)
            if num == 2:
                # Prep: use prep supplier, no supplier selection
                _pending_type_selection.pop(sender_phone, None)
                prep_sid = get_valid_prep_supplier_id(get_by_id)
                reply = _do_append_and_confirm(
                    item_name, quantity, sender_phone, prep_sid, "Prep"
                )
                return twiml_response(reply)
        except ValueError:
            pass
        return twiml_response(_t(sender_phone, "reply_type_raw_prep"))

    # --- Pending supplier selection (after choosing Raw for new item) ---
    if sender_phone in _pending_supplier_selection:
        item_name, quantity = _pending_supplier_selection[sender_phone]
        suppliers = get_numbered_list()
        if not suppliers:
            _pending_supplier_selection.pop(sender_phone, None)
            reply = _do_append_and_confirm(
                item_name, quantity, sender_phone, None, "Raw"
            )
            return twiml_response(reply)
        try:
            num = int(body_text.strip())
            if 1 <= num <= len(suppliers):
                _, sup = suppliers[num - 1]
                _pending_supplier_selection.pop(sender_phone, None)
                reply = _do_append_and_confirm(
                    item_name, quantity, sender_phone, sup.get("id"), "Raw"
                )
                return twiml_response(reply)
        except ValueError:
            pass
        return twiml_response(_t(sender_phone, "reply_number_range", max=len(suppliers)))

    # --- Pending new-item confirmation ---
    if sender_phone in _pending_new_item:
        body_clean = body_text.strip()
        body_lower = body_clean.lower()
        if body_lower in ("yes", "y", "ye") or body_clean in ("כן", "כ"):
            item_name, quantity = _pending_new_item.pop(sender_phone)
            _pending_type_selection[sender_phone] = (item_name, quantity, None)
            return twiml_response(_t(sender_phone, "type_select"))
        if body_lower in ("no", "n") or body_clean in ("לא", "ל") or body_text == "!":
            _pending_new_item.pop(sender_phone, None)
            return twiml_response(_t(sender_phone, "cancelled"))
        return twiml_response(_t(sender_phone, "reply_yes_no_new_item"))

    # --- Multi-item mode: end with "!" ---
    if sender_phone in _multi_mode_sessions:
        if body_text == "!":
            items = _multi_mode_sessions.pop(sender_phone)
            if not items:
                return twiml_response(_t(sender_phone, "multi_mode_ended_empty"))
            rows_for_sheets: List[Tuple[str, int, Optional[str], str]] = []
            for item_name, qty in items:
                sid = get_item_supplier_id(item_name)
                itype = get_item_type(item_name)
                s = get_by_id(sid) if sid else None
                sup_name = s.get("company_name", "") if s else None
                rows_for_sheets.append((item_name, qty, sup_name, itype))
            try:
                append_inventory_rows(rows_for_sheets, sender_phone)
            except (ValueError, Exception) as e:
                print(f"[ERROR] Sheets batch append failed: {e}")
            added: List[str] = []
            for item_name, qty in items:
                sid = get_item_supplier_id(item_name)
                itype = get_item_type(item_name)
                add_item(item_name, sid, itype, qty, updated_by=sender_phone)
                added.append(f"{item_name}×{qty}" if qty > 1 else item_name)
            items_list = "  • " + "\n  • ".join(added)
            return twiml_response(_t(sender_phone, "added_items", count=len(added), items=items_list))

        # In multi mode: only existing items
        parsed = _parse_item_raw(body_text)
        if parsed:
            item_name, qty = parsed
            if not is_known_item(item_name):
                return twiml_response(
                    _t(sender_phone, "item_not_in_list_multi", item_name=item_name)
                )
            _multi_mode_sessions[sender_phone].append((item_name, qty))
            part = f"{item_name}×{qty}" if qty > 1 else item_name
            return twiml_response(_t(sender_phone, "added_part_send_more", part=part))
        return twiml_response(_t(sender_phone, "send_existing_or_finish"))

    # --- Multi-item mode: start with "Lows" / "S" / "פם" / "ם" ---
    if re.match(r"^(?:lows|s)\s*$", body_text, re.IGNORECASE):
        _multi_mode_sessions[sender_phone] = []
        return twiml_response(_t(sender_phone, "multi_mode_start"))

    match = re.match(r"^(?:lows|s)\s+(.+)$", body_text, re.IGNORECASE)
    if match:
        rest = match.group(1).strip()
        parsed = _parse_item_raw(rest)
        if parsed:
            item_name, qty = parsed
            if is_known_item(item_name):
                _multi_mode_sessions[sender_phone] = [(item_name, qty)]
                part = f"{item_name}×{qty}" if qty > 1 else item_name
                return twiml_response(_t(sender_phone, "multi_mode_added_part", part=part))
        # Not a known item: try supplier regex for easy fill (פם <supplier_regex>)
        supplier_pattern = rest
        if not supplier_pattern:
            _multi_mode_sessions[sender_phone] = []
            return twiml_response(_t(sender_phone, "multi_mode_send_existing"))
        # Cancel any blocking pending state so Lows fill can start
        _pending_supplier_selection.pop(sender_phone, None)
        _pending_type_selection.pop(sender_phone, None)
        _pending_new_item.pop(sender_phone, None)
        try:
            pat = re.compile(supplier_pattern, re.IGNORECASE)
        except re.error:
            return twiml_response(_t(sender_phone, "list_invalid_regex", pattern=supplier_pattern))
        suppliers = get_all()
        matching = [s for s in suppliers if pat.search(s.get("company_name", "") or "")]
        if not matching:
            return twiml_response(_t(sender_phone, "list_no_match", pattern=supplier_pattern))
        all_items: List[dict] = []
        for s in matching:
            for it in get_items_by_supplier(s.get("id", "")):
                all_items.append({
                    "name": it.get("name", ""),
                    "supplier_id": it.get("supplier_id"),
                    "type": it.get("type", "Raw"),
                })
        if not all_items:
            return twiml_response(_t(sender_phone, "list_no_match", pattern=supplier_pattern))
        _pending_lows_fill[sender_phone] = {"items": all_items, "index": 0, "collected": []}
        first = all_items[0]
        return twiml_response(_t(sender_phone, "lows_fill_quantity_prompt", item_name=first["name"], num=1, total=len(all_items)))

    # --- Help: show all commands or detailed help for one command ---
    help_match = re.match(r"^(?:help|h)\s+(.+)$", body_text, re.IGNORECASE)
    if help_match:
        cmd = help_match.group(1).strip().lower()
        detail_map = {
            "low": "help_low_detail", "l": "help_low_detail", "sup": "help_sup_detail", "supa": "help_supa_detail",
            "list": "help_list_detail", "listext": "help_listext_detail", "ext": "help_listext_detail",
            "need": "help_need_detail", "n": "help_need_detail",
            "needfill": "help_need_fill_detail", "need_fill": "help_need_fill_detail",
            "edit": "help_edit_detail", "e": "help_edit_detail",
            "help": "help_help_detail", "h": "help_help_detail", "lows": "help_lows_detail", "s": "help_lows_detail",
            "lowsfill": "help_lows_fill_detail", "lows_fill": "help_lows_fill_detail",
            "lang": "help_lang_detail", "pref": "help_pref_detail", "p": "help_pref_detail",
            "back": "help_back_detail", "b": "help_back_detail",
            "exit": "help_back_detail", "quit": "help_back_detail", "cancel": "help_back_detail",
        }
        key = detail_map.get(cmd)
        if key:
            return twiml_response(_t(sender_phone, key))
        return twiml_response(_t(sender_phone, "help_unknown", command=help_match.group(1).strip()))
    if re.match(r"^(?:help|h)\s*$", body_text, re.IGNORECASE):
        lines = [
            _t(sender_phone, "help_title"),
            "",
            _t(sender_phone, "help_low"),
            _t(sender_phone, "help_sup"),
            _t(sender_phone, "help_supa"),
            _t(sender_phone, "help_list"),
            _t(sender_phone, "help_listext"),
            _t(sender_phone, "help_need"),
            _t(sender_phone, "help_need_fill"),
            _t(sender_phone, "help_edit"),
            _t(sender_phone, "help_lows"),
            _t(sender_phone, "help_lows_fill"),
            _t(sender_phone, "help_pref"),
            _t(sender_phone, "help_back"),
            _t(sender_phone, "help_help"),
        ]
        return twiml_response("\n".join(lines))

    # --- Preferences: Pref / P / ה / הגדרות / שפה ---
    if re.match(r"^(?:pref|p|lang)\s*$", body_text, re.IGNORECASE):
        _pending_preferences[sender_phone] = "menu"
        lines = [_t(sender_phone, "pref_title"), "", "  1. " + _t(sender_phone, "pref_lang"), "  2. " + _t(sender_phone, "pref_prep_supplier"), "", _t(sender_phone, "reply_with_number")]
        return twiml_response("\n".join(lines))

    # --- Pending preferences: menu selection ---
    if sender_phone in _pending_preferences:
        state = _pending_preferences[sender_phone]
        if state == "menu":
            try:
                num = int(body_text.strip())
                if num == 1:
                    _pending_preferences[sender_phone] = "lang"
                    langs = get_supported_langs(get_user_lang(sender_phone))
                    lines = [_t(sender_phone, "lang_supported"), ""]
                    for i, (code, name) in enumerate(langs, 1):
                        lines.append(f"  {i}. {name}")
                    lines.extend(["", _t(sender_phone, "lang_select")])
                    return twiml_response("\n".join(lines))
                if num == 2:
                    suppliers = get_numbered_list()
                    if not suppliers:
                        _pending_preferences.pop(sender_phone, None)
                        return twiml_response(_t(sender_phone, "pref_no_suppliers"))
                    _pending_preferences[sender_phone] = "prep_supplier"
                    lines = [_t(sender_phone, "pref_prep_supplier_prompt"), ""]
                    for i, s in suppliers:
                        lines.append(f"  {i}. {s.get('company_name', '?')}")
                    lines.extend(["", _t(sender_phone, "reply_with_number")])
                    return twiml_response("\n".join(lines))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "reply_number_range", max=2))
        if state == "lang":
            try:
                num = int(body_text.strip())
                langs = get_supported_langs(get_user_lang(sender_phone))
                if 1 <= num <= len(langs):
                    code, name = langs[num - 1]
                    set_user_lang(sender_phone, code)
                    _pending_preferences.pop(sender_phone, None)
                    return twiml_response(_t(sender_phone, "lang_set", lang_name=name))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "lang_select"))
        if state == "prep_supplier":
            suppliers = get_numbered_list()
            try:
                num = int(body_text.strip())
                if 1 <= num <= len(suppliers):
                    _, sup = suppliers[num - 1]
                    sid = sup.get("id", "")
                    count = set_prep_items_supplier(sid)
                    _pending_preferences.pop(sender_phone, None)
                    return twiml_response(_t(sender_phone, "pref_prep_supplier_set", company=sup.get("company_name", "?"), count=count))
            except ValueError:
                pass
            return twiml_response(_t(sender_phone, "reply_number_range", max=len(suppliers)))


    # --- Edit: edit item (supplier, type, rename, delete) ---
    edit_match = re.match(r"^(?:edit|e)\s+(.+)$", body_text, re.IGNORECASE)
    if edit_match:
        raw_name = edit_match.group(1).strip()
        # Strip trailing quantity if present (Edit Milk 3 -> Milk)
        qty_match = re.search(r"\s+(\d+)\s*$", raw_name)
        item_name = raw_name[: qty_match.start()].strip() if qty_match else raw_name
        if not item_name:
            return twiml_response(_t(sender_phone, "invalid_item"))
        canonical = get_item_canonical_name(item_name)
        if not canonical:
            return twiml_response(_t(sender_phone, "edit_item_not_found", item_name=item_name))
        _pending_edit[sender_phone] = {"step": "menu", "item_name": canonical}
        sid = get_item_supplier_id(canonical)
        itype = get_item_type(canonical)
        s = get_by_id(sid) if sid else None
        sup_name = s.get("company_name", "") if s else _t(sender_phone, "list_no_supplier")
        type_label = _t(sender_phone, "type_prep") if itype == "Prep" else _t(sender_phone, "type_raw")
        lines = [
            _t(sender_phone, "edit_menu_header", item_name=canonical, supplier=sup_name, type_label=type_label),
            "",
            "  1. " + _t(sender_phone, "edit_change_supplier"),
            "  2. " + _t(sender_phone, "edit_change_type"),
            "  3. " + _t(sender_phone, "edit_rename"),
            "  4. " + _t(sender_phone, "edit_delete"),
            "",
            _t(sender_phone, "reply_with_number"),
        ]
        return twiml_response("\n".join(lines))

    # --- Need: set required quantity for item, or Need <supplier_regex> for easy fill ---
    need_match = re.match(r"^(?:need|n)\s+(.+)$", body_text, re.IGNORECASE)
    if need_match:
        rest = need_match.group(1).strip()
        parsed = _parse_item_raw(rest)
        if parsed:
            item_name, req_qty = parsed
            if is_known_item(item_name):
                set_required_quantity(item_name, req_qty)
                return twiml_response(_t(sender_phone, "need_updated", item_name=item_name, quantity=req_qty))
            # Not a known item: try supplier regex for Need fill (Need <supplier_regex>)
        supplier_pattern = rest
        if not supplier_pattern:
            return twiml_response(_t(sender_phone, "invalid_item"))
        _pending_supplier_selection.pop(sender_phone, None)
        _pending_type_selection.pop(sender_phone, None)
        _pending_new_item.pop(sender_phone, None)
        try:
            pat = re.compile(supplier_pattern, re.IGNORECASE)
        except re.error:
            return twiml_response(_t(sender_phone, "list_invalid_regex", pattern=supplier_pattern))
        suppliers = get_all()
        matching = [s for s in suppliers if pat.search(s.get("company_name", "") or "")]
        if not matching:
            return twiml_response(_t(sender_phone, "list_no_match", pattern=supplier_pattern))
        all_items: List[dict] = []
        for s in matching:
            for it in get_items_by_supplier(s.get("id", "")):
                all_items.append({
                    "name": it.get("name", ""),
                    "supplier_id": it.get("supplier_id"),
                    "type": it.get("type", "Raw"),
                })
        if not all_items:
            return twiml_response(_t(sender_phone, "list_no_match", pattern=supplier_pattern))
        _pending_need_fill[sender_phone] = {"items": all_items, "index": 0, "collected": []}
        first = all_items[0]
        return twiml_response(_t(sender_phone, "need_fill_quantity_prompt", item_name=first["name"], num=1, total=len(all_items)))

    # --- ListExt: extended table with last_updated, last_updated_by ---
    listext_match = re.match(r"^(?:listext|ext)\s+(.+)$", body_text, re.IGNORECASE)
    if listext_match or re.match(r"^(?:listext|ext)\s*$", body_text, re.IGNORECASE):
        supplier_filter = listext_match.group(1).strip() if listext_match else None
        if supplier_filter:
            try:
                pat = re.compile(supplier_filter, re.IGNORECASE)
            except re.error:
                return twiml_response(_t(sender_phone, "list_invalid_regex", pattern=supplier_filter))
        items = get_all_items()
        if not items:
            return twiml_response(_t(sender_phone, "no_items_yet"))
        by_supplier: Dict[str, List[tuple]] = {}
        for i in items:
            sup_id = i.get("supplier_id") or ""
            s = get_by_id(sup_id) if sup_id else None
            sup_name = s.get("company_name", "") if s else _t(sender_phone, "list_no_supplier")
            if supplier_filter and not pat.search(sup_name):
                continue
            key = (sup_name, sup_id)
            if key not in by_supplier:
                by_supplier[key] = []
            by_supplier[key].append(i)
        if not by_supplier:
            return twiml_response(_t(sender_phone, "list_no_match", pattern=supplier_filter or ""))
        sections = sorted(by_supplier.keys(), key=lambda k: (k[0] == _t(sender_phone, "list_no_supplier"), k[0].lower()))
        lines = [_t(sender_phone, "listext_header"), ""]
        for key in sections:
            sup_name, _sid = key
            group_items = by_supplier[key]
            group_items.sort(key=lambda x: (x.get("name", "").lower(),))
            lines.append(f"{sup_name}:")
            for i in group_items:
                itype = i.get("type", "Raw")
                type_label = _t(sender_phone, "type_prep") if itype == "Prep" else _t(sender_phone, "type_raw")
                qty = i.get("quantity", 1)
                req = i.get("required_quantity", 0)
                seg = f"{qty} / {req}" if req > 0 else f"{qty} / -"
                qty_display = "\u202a" + seg + "\u202c"
                last_upd = i.get("last_updated") or "-"
                last_by = i.get("last_updated_by") or "-"
                lines.append(f"  • {i.get('name', '?')}  |  {qty_display}  |  {type_label}  |  {last_upd}  |  {last_by}")
            lines.append("")
        return twiml_response("\n".join(lines).rstrip())

    # --- List: show items grouped by supplier, optional regex filter ---
    list_match = re.match(r"^list\s+(.+)$", body_text, re.IGNORECASE)
    if list_match or re.match(r"^list\s*$", body_text, re.IGNORECASE):
        supplier_filter = list_match.group(1).strip() if list_match else None
        if supplier_filter:
            try:
                pat = re.compile(supplier_filter, re.IGNORECASE)
            except re.error:
                return twiml_response(_t(sender_phone, "list_invalid_regex", pattern=supplier_filter))
        items = get_all_items()
        if not items:
            return twiml_response(_t(sender_phone, "no_items_yet"))
        by_supplier: Dict[str, List[tuple]] = {}
        for i in items:
            sup_id = i.get("supplier_id") or ""
            s = get_by_id(sup_id) if sup_id else None
            sup_name = s.get("company_name", "") if s else _t(sender_phone, "list_no_supplier")
            if supplier_filter and not pat.search(sup_name):
                continue
            key = (sup_name, sup_id)
            if key not in by_supplier:
                by_supplier[key] = []
            by_supplier[key].append(i)
        if not by_supplier:
            return twiml_response(_t(sender_phone, "list_no_match", pattern=supplier_filter or ""))
        # Sort supplier sections by name, no-supplier last
        sections = sorted(by_supplier.keys(), key=lambda k: (k[0] == _t(sender_phone, "list_no_supplier"), k[0].lower()))
        lines = [_t(sender_phone, "items_header"), ""]
        for key in sections:
            sup_name, _sid = key
            group_items = by_supplier[key]
            group_items.sort(key=lambda x: (x.get("name", "").lower(),))
            lines.append(f"{sup_name}:")
            for i in group_items:
                itype = i.get("type", "Raw")
                type_label = _t(sender_phone, "type_prep") if itype == "Prep" else _t(sender_phone, "type_raw")
                qty = i.get("quantity", 1)
                req = i.get("required_quantity", 0)
                seg = f"{qty} / {req}" if req > 0 else f"{qty} / -"
                qty_display = "\u202a" + seg + "\u202c"
                lines.append(f"  • {i.get('name', '?')}  |  {qty_display}  |  {type_label}")
            lines.append("")
        return twiml_response("\n".join(lines).rstrip())

    if re.match(r"^sup\s*$", body_text, re.IGNORECASE):
        suppliers = get_numbered_list()
        if not suppliers:
            return twiml_response(_t(sender_phone, "no_suppliers_yet"))
        _pending_supplier_details[sender_phone] = True
        lines = [_t(sender_phone, "suppliers_header"), ""]
        for i, s in suppliers:
            lines.append(f"{i}. {s.get('company_name', '?')}")
        lines.extend(["", _t(sender_phone, "suppliers_select_number")])
        return twiml_response("\n".join(lines))

    if re.match(r"^supa\s*$", body_text, re.IGNORECASE):
        _pending_add_supplier[sender_phone] = {"step": 1}
        return twiml_response(_t(sender_phone, "company_name_prompt"))

    # --- Reserved words: standalone command chars/words are not items ---
    _RESERVED = frozenset({
        "low", "l", "sup", "supa", "list", "listext", "ext", "need", "n", "edit", "e", "help", "h", "lang", "lows", "s", "pref", "p", "back", "b", "exit", "quit", "cancel",
        "yes", "y", "ye", "no",
        "פ", "ס", "סח", "מ", "ממ", "ע", "צ", "ער", "פם", "ם", "שפה", "הגדרות", "ה", "חזור", "ח", "בטל", "צא", "צריך", "ערוך", "פריט", "ספק", "מלאי", "מלאימורחב", "עזרה", "כן", "כ", "לא", "ל",
    })
    if body_text.strip().lower() in {w.lower() for w in _RESERVED if w.isascii()} or body_text.strip() in _RESERVED:
        return twiml_response(_t(sender_phone, "reserved_word"))

    # --- Single-item mode ---
    item_name, quantity = parse_item_and_quantity(body_text)
    if item_name == "Unknown Item" or not item_name:
        return twiml_response(_t(sender_phone, "invalid_item"))

    has_low = _has_explicit_low(body_text)

    if is_known_item(item_name):
        sid = get_item_supplier_id(item_name)
        itype = get_item_type(item_name)
        reply = _do_append_and_confirm(item_name, quantity, sender_phone, sid, itype)
        return twiml_response(reply)

    # New item: type first, then supplier only for Raw
    if has_low:
        _pending_type_selection[sender_phone] = (item_name, quantity, None)
        return twiml_response(_t(sender_phone, "type_select"))

    _pending_new_item[sender_phone] = (item_name, quantity)
    return twiml_response(_t(sender_phone, "add_new_item_confirm", item_name=item_name))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
