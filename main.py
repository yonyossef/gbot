"""
Shop Assistant WhatsApp Bot - FastAPI backend.

Webhook endpoint for Twilio to receive incoming WhatsApp messages.
Logs inventory needs (e.g., "Low Milk", "Beans") to a Google Sheet.
"""

import os
import re
from typing import Optional

from fastapi import FastAPI, Request, Response
from twilio.request_validator import RequestValidator

from services.sheets import append_inventory_row

app = FastAPI(
    title="Shop Assistant Bot",
    description="WhatsApp bot for logging inventory needs to Google Sheets",
    version="0.1.0",
)


def parse_item_from_message(body: str) -> str:
    """
    Extract the item name from an incoming message.

    Rules:
    - "Low Milk" or "low milk" -> "Milk" (strip "low " prefix, capitalize)
    - "Beans" -> "Beans" (use as-is)
    - For MVP: treat any incoming text as a Low Stock alert.
    """
    if not body or not body.strip():
        return "Unknown Item"

    text = body.strip()

    # Strip "low " prefix (case-insensitive)
    match = re.match(r"^low\s+(.+)$", text, re.IGNORECASE)
    if match:
        item = match.group(1).strip()
    else:
        item = text

    # Capitalize first letter of each word for consistency
    return item.title() if item else "Unknown Item"


def twiml_response(message: str) -> Response:
    """Return a TwiML response for Twilio."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{message}</Message>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.get("/")
async def root() -> dict:
    """Health check / root endpoint."""
    return {"name": "Shop Assistant Bot", "status": "running"}


@app.get("/health")
async def health() -> dict:
    """Health check for Railway and monitoring."""
    return {"status": "healthy"}


def _validate_twilio_request(request: Request, form_dict: dict) -> bool:
    """Validate that the request is from Twilio using X-Twilio-Signature."""
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not auth_token:
        return True  # Skip validation if token not configured (e.g. local dev)
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    validator = RequestValidator(auth_token)
    return validator.validate(url, form_dict, signature)


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    """
    Twilio webhook for incoming WhatsApp messages.

    Twilio sends form-encoded data. We parse the Body, extract the item name,
    append to Google Sheet, and return a TwiML confirmation.
    """
    form = await request.form()
    form_dict = {k: v for k, v in form.items() if isinstance(v, str)}

    if not _validate_twilio_request(request, form_dict):
        return Response(status_code=403, content="Invalid signature")

    body_text = form_dict.get("Body", "") or ""
    sender_phone = form_dict.get("From", "Unknown")

    item_name = parse_item_from_message(body_text)

    try:
        append_inventory_row(
            item_name=item_name,
            sender_phone=sender_phone,
            status="Low Stock",
        )
        reply = f"✅ Added {item_name} to the shopping list."
    except (ValueError, Exception) as e:
        # Log error but still respond to Twilio (avoid retries)
        reply = f"⚠️ Could not add to list: {item_name}. Please try again later."
        print(f"[ERROR] Sheets append failed: {e}")

    return twiml_response(reply)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
