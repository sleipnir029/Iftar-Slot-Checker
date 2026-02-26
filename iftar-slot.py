import json
import os
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin
from dotenv import load_dotenv
import logging

# Set up logging to both file and console.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("iftar_scraper.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

load_dotenv()
# Telegram details
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
STATE_FILE = os.getenv("STATE_FILE", "state.json")

# Global dictionaries for cooldown and state tracking.
# last_notifications: stores last notification timestamp for a key (ticket_type, target_date)
last_notifications = {}
# last_states: stores the last known availability state for a key (ticket_type, target_date)
last_states = {}

# Cooldown period in seconds (10 minutes here)
COOLDOWN_SECONDS = 600

# Consecutive fetch failures; when >= ADMIN_ALERT_THRESHOLD, send alert to ADMIN_CHAT_ID if set.
consecutive_fetch_failures = 0
ADMIN_ALERT_THRESHOLD = 3

# First run after load_state(): only sync state from live page, do not send notifications.
_first_run_after_load = True

# HTTP session with consistent User-Agent to avoid blocking; optional Accept-Language for German.
HTTP_HEADERS = {
    "User-Agent": "IftarSlotChecker/1.0 (+https://github.com/community/iftar-iza)",
    "Accept-Language": "de,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
REQUEST_RETRIES = 3
REQUEST_BACKOFF = (1, 2, 4)  # seconds between retries


def _get_with_retries(url: str):
    """Fetch URL with retries and backoff on 5xx or connection errors. Returns response or None."""
    session = requests.Session()
    session.headers.update(HTTP_HEADERS)
    last_exc = None
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code >= 500 and attempt < REQUEST_RETRIES - 1:
                time.sleep(REQUEST_BACKOFF[attempt])
                continue
            resp.raise_for_status()
            return resp
        except (requests.RequestException, OSError) as e:
            last_exc = e
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(REQUEST_BACKOFF[attempt])
    logging.error("Error fetching %s after %d attempts: %s", url, REQUEST_RETRIES, last_exc)
    return None


def _state_key(key: tuple) -> str:
    """Convert (ticket_type, date_str) to a JSON-serializable string key."""
    return f"{key[0]}|{key[1]}"


def _parse_state_key(s: str) -> tuple:
    """Convert string key back to (ticket_type, date_str)."""
    parts = s.split("|", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (s, "")


def load_state() -> None:
    """Load last_states and last_notifications from STATE_FILE if it exists."""
    global last_notifications, last_states
    if not STATE_FILE:
        return
    try:
        if os.path.isfile(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            last_states.clear()
            for k, v in data.get("last_states", {}).items():
                last_states[_parse_state_key(k)] = bool(v)
            last_notifications.clear()
            for k, v in data.get("last_notifications", {}).items():
                try:
                    last_notifications[_parse_state_key(k)] = datetime.fromisoformat(v)
                except (ValueError, TypeError):
                    pass
            logging.info("Loaded state from %s (%d states, %d notifications).",
                        STATE_FILE, len(last_states), len(last_notifications))
    except (OSError, json.JSONDecodeError) as e:
        logging.warning("Could not load state file %s: %s", STATE_FILE, e)


def save_state() -> None:
    """Persist last_states and last_notifications to STATE_FILE."""
    if not STATE_FILE:
        return
    try:
        data = {
            "last_states": {_state_key(k): v for k, v in last_states.items()},
            "last_notifications": {
                _state_key(k): v.isoformat() for k, v in last_notifications.items()
            },
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logging.warning("Could not save state to %s: %s", STATE_FILE, e)

def send_telegram_message(message, chat_id: str | None = None):
    """Send a Telegram message to CHAT_ID, or to chat_id if provided."""
    target = chat_id or CHAT_ID
    if not target:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": target,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, data=data)
        result = response.json()
        logging.info("Telegram response: %s", result)
    except Exception as e:
        logging.error("Error sending Telegram message: %s", e)


def send_admin_alert(message: str) -> None:
    """Send an alert to ADMIN_CHAT_ID if set. Used for critical failures."""
    if ADMIN_CHAT_ID:
        send_telegram_message(message, chat_id=ADMIN_CHAT_ID)

def check_today_slots():
    global consecutive_fetch_failures, _first_run_after_load
    logging.info("Checking today's slots...")
    base_url = "https://dailyiftar.imsuaachen.de/"
    now = datetime.now()
    
    # Determine target date: if current time is 19:45 or later, use next day; otherwise, use today.
    cutoff_time = datetime.strptime("19:45", "%H:%M").time()
    if now.time() >= cutoff_time:
        target_date = now + timedelta(days=1)
        logging.info("Current time is after 19:45; using next day's registration.")
    else:
        target_date = now
        logging.info("Current time is before 19:45; using today's registration.")
    
    target_str = target_date.strftime("%d.%m.%Y")
    logging.info("Looking for date cell with data-date='%s'", target_str)
    
    resp = _get_with_retries(base_url)
    if resp is None:
        consecutive_fetch_failures += 1
        if consecutive_fetch_failures >= ADMIN_ALERT_THRESHOLD:
            send_admin_alert(
                f"⚠️ Iftar checker: failed to fetch calendar page {consecutive_fetch_failures} times in a row. "
                f"Check logs and site availability."
            )
            consecutive_fetch_failures = 0
        return
    
    soup = BeautifulSoup(resp.text, "html.parser")
    day_cell = soup.select_one(f'td.day[data-date="{target_str}"]')
    if not day_cell:
        logging.info("No cell found for date %s.", target_str)
        return
    
    status_el = day_cell.select_one(".event-status")
    status_text = status_el.get_text(strip=True).lower() if status_el else ""
    logging.info("Status text in day cell: '%s'", status_text)
    
    # (Optional) You might decide here to immediately notify if cell status shows unavailability.
    if any(keyword in status_text for keyword in ["ausgebucht", "verkauf beendet", "fully booked", "sale over", "reserviert", "reserved"]):
        logging.info("❌ Tickets not available (fully booked/sale ended/reserved) for %s.", target_str)
        # send_telegram_message(f"❌ No available tickets found for {target_str}.")
        # We don't return here so that if the detail page state changes (e.g. toggles back to available),
        # a state change will be detected.
    
    # Find the actual event link within <ul class="events">
    link_tag = day_cell.select_one("ul.events a.event")
    if not link_tag:
        logging.info("No event link found in ul.events. Trying fallback day label link...")
        link_tag = day_cell.select_one("a.day-label.event")
    
    if not link_tag or not link_tag.get("href"):
        logging.info("No valid detail link found in the day cell.")
        return
    
    detail_url = link_tag["href"]
    logging.info("Detail url (raw): %s", detail_url)
    if detail_url.startswith("/"):
        detail_url = urljoin(base_url, detail_url)
    logging.info("Detail page link: %s", detail_url)
    
    detail_resp = _get_with_retries(detail_url)
    if detail_resp is None:
        consecutive_fetch_failures += 1
        if consecutive_fetch_failures >= ADMIN_ALERT_THRESHOLD:
            send_admin_alert(
                f"⚠️ Iftar checker: failed to fetch detail page {consecutive_fetch_failures} times in a row. "
                f"Check logs and site availability."
            )
            consecutive_fetch_failures = 0
        return
    
    detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
    messages = []
    
    # Iterate over ticket products on the detail page.
    articles = detail_soup.find_all("article", class_="product-row")
    if not articles:
        logging.info("No ticket articles are found on detail page.")
    
    for article in articles:
        header = article.find("h4")
        if not header:
            continue
        product_title = header.get_text(strip=True).lower()
        availability_div = article.find("div", class_="availability-box")
        # Site uses: AUSVERKAUFT/sold out (or .gone), Reserviert/reserved (not bookable), or available with "Auswählen"/Select.
        # Treat both sold-out and reserved as not available (no "ticket available" notification).
        article_text = article.get_text(strip=True).lower()
        is_sold_out = False
        emoji = "✅"
        if availability_div:
            availability_text = availability_div.get_text(strip=True).lower()
            classes = availability_div.get("class") or []
            has_gone_class = "gone" in classes
            has_reserved_class = "reserved" in classes
            if has_gone_class:
                is_sold_out = True
                emoji = "❌"
            elif has_reserved_class:
                is_sold_out = True
                emoji = "⏳"  # reserved, not bookable
            elif "ausgebucht" in availability_text or "sold out" in availability_text or "ausverkauft" in availability_text:
                is_sold_out = True
                emoji = "❌"
            elif "reserviert" in availability_text or "reserved" in availability_text:
                is_sold_out = True
                emoji = "⏳"
        if not is_sold_out and (
            "ausgebucht" in article_text or "sold out" in article_text or "ausverkauft" in article_text
            or "reserviert" in article_text or "reserved" in article_text
        ):
            is_sold_out = True
            emoji = "⏳" if ("reserviert" in article_text or "reserved" in article_text) else "❌"
        logging.info("Ticket '%s': sold out? %s %s", product_title, is_sold_out, emoji)
        
        key = None
        ticket_emoji = ""
        if "brüderticket" in product_title or "brotherticket" in product_title:
            key = ("bruder", target_str)
            ticket_emoji = "🧔"
        elif "schwesternticket" in product_title or "sisterticket" in product_title:
            key = ("schwester", target_str)
            ticket_emoji = "🧕"
        else:
            continue
        
        # If the ticket is not sold out:
        if not is_sold_out:
            # Check previous state for this ticket.
            previous_state = last_states.get(key, False)
            # If previous state was unavailable or not set, state change detected.
            if not previous_state:
                last_notifications[key] = datetime.now()
                last_states[key] = True
                if not _first_run_after_load:
                    messages.append((key, f"{ticket_emoji} {key[0].capitalize()} ticket is available for {target_str}!\n✅ Register here: {detail_url}"))
            else:
                # Ticket was already available.
                elapsed = (datetime.now() - last_notifications[key]).total_seconds()
                if elapsed >= COOLDOWN_SECONDS:
                    last_notifications[key] = datetime.now()
                    if not _first_run_after_load:
                        messages.append((key, f"{ticket_emoji} {key[0].capitalize()} ticket is still available for {target_str}!\n✅ Register here: {detail_url}"))
                else:
                    logging.info("Cooldown active for %s ticket on %s (elapsed %.0f seconds).", key[0], target_str, elapsed)
        else:
            # If ticket is sold out, update state.
            last_states[key] = False

    if _first_run_after_load:
        _first_run_after_load = False
        logging.info("First run after startup: state synced from live page (no notifications sent).")

    if messages:
        for key, msg in messages:
            send_telegram_message(msg)
            logging.info("Notification sent: %s", msg)
    else:
        logging.info("No available tickets are found for %s.", target_str)
        # send_telegram_message(f"❌ No available tickets found for {target_str}.")
    
    logging.info("Done checking slots for %s.", target_str)
    consecutive_fetch_failures = 0
    save_state()


def main():
    global _first_run_after_load
    load_state()
    _first_run_after_load = True
    while True:
        check_today_slots()
        time.sleep(30)  # Check every 30 seconds; adjust as needed.

if __name__ == "__main__":
    main()
