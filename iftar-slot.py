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

# Global dictionaries for cooldown and state tracking.
# last_notifications: stores last notification timestamp for a key (ticket_type, target_date)
last_notifications = {}
# last_states: stores the last known availability state for a key (ticket_type, target_date)
last_states = {}

# Cooldown period in seconds (10 minutes here)
COOLDOWN_SECONDS = 600

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
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

def check_today_slots():
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
    
    try:
        resp = requests.get(base_url)
        resp.raise_for_status()
    except Exception as e:
        logging.error("Error fetching main page: %s", e)
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
    if any(keyword in status_text for keyword in ["ausgebucht", "verkauf beendet", "fully booked"]):
        logging.info("❌ Tickets not available (fully booked/sale ended) for %s.", target_str)
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
    
    try:
        detail_resp = requests.get(detail_url)
        detail_resp.raise_for_status()
    except Exception as e:
        logging.error("Error fetching detail page: %s", e)
        return
    
    detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
    messages = []
    
    # Iterate over ticket products on the detail page.
    articles = detail_soup.find_all("article", class_="product-row")
    if not articles:
        logging.info("No ticket articles found on detail page.")
    
    for article in articles:
        header = article.find("h4")
        if not header:
            continue
        product_title = header.get_text(strip=True).lower()
        availability_div = article.find("div", class_="availability-box")
        is_sold_out = False
        emoji = "✅"
        if availability_div:
            availability_text = availability_div.get_text(strip=True).lower()
            if "ausgebucht" in availability_text:
                is_sold_out = True
                emoji = "❌"
        logging.info("Ticket '%s': sold out? %s %s", product_title, is_sold_out, emoji)
        
        key = None
        ticket_emoji = ""
        if "brüderticket" in product_title:
            key = ("bruder", target_str)
            ticket_emoji = "🧔"
        elif "schwesternticket" in product_title:
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
                messages.append((key, f"{ticket_emoji} {key[0].capitalize()} ticket available for {target_str}!\n✅ Register here: {detail_url}"))
                last_notifications[key] = datetime.now()
                last_states[key] = True
            else:
                # Ticket was already available.
                elapsed = (datetime.now() - last_notifications[key]).total_seconds()
                if elapsed >= COOLDOWN_SECONDS:
                    messages.append((key, f"{ticket_emoji} {key[0].capitalize()} ticket still available for {target_str}!\n✅ Register here: {detail_url}"))
                    last_notifications[key] = datetime.now()
                else:
                    logging.info("Cooldown active for %s ticket on %s (elapsed %.0f seconds).", key[0], target_str, elapsed)
        else:
            # If ticket is sold out, update state.
            last_states[key] = False

    if messages:
        for key, msg in messages:
            send_telegram_message(msg)
            logging.info("Notification sent: %s", msg)
    else:
        logging.info("No available tickets found for %s.", target_str)
        # send_telegram_message(f"❌ No available tickets found for {target_str}.")
    
    logging.info("Done checking slots for %s.", target_str)

def main():
    while True:
        check_today_slots()
        time.sleep(30)  # Check every 30 seconds; adjust as needed.

if __name__ == "__main__":
    main()
