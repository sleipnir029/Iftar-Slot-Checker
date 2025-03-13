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
    
    # Determine target date:
    now = datetime.now()
    # If current time is 19:45 or later, use next day; otherwise, use today.
    cutoff_time = datetime.strptime("19:45", "%H:%M").time()
    if now.time() >= cutoff_time:
        target_date = now + timedelta(days=1)
        logging.info("Current time is after 19:45; using next day's registration.")
    else:
        target_date = now
        logging.info("Current time is before 19:45; using today's registration.")

    # Format target date as DD.MM.YYYY
    target_str = target_date.strftime("%d.%m.%Y")
    logging.info("Looking for date cell with data-date='%s'", target_str)
    
    
    # # Calendar uses date format "DD.MM.YYYY"
    # today_str = datetime.now().strftime("%d.%m.%Y")
    # logging.info("Looking for date cell with data-date='%s'", today_str)
    
    try:
        resp = requests.get(base_url)
        resp.raise_for_status()  # This will raise an exception if there's an error.
    except Exception as e:
        logging.error("Error fetching main page: %s", e)
        return
    
    soup = BeautifulSoup(resp.text, "html.parser")
    # Find the calendar cell for today's date
    day_cell = soup.select_one(f'td.day[data-date="{target_str}"]')
    # logging.info("Day cell found: %s", day_cell)
    if not day_cell:
        logging.info("No cell found for today's date.")
        return
    
    # Check the event status in the day cell.
    status_el = day_cell.select_one(".event-status")
    status_text = status_el.get_text(strip=True).lower() if status_el else ""
    logging.info("Status text in day cell: '%s'", status_text)
    
    # If the day is marked as unavailable, immediately send a notification and return.
    if any(keyword in status_text for keyword in ["ausgebucht", "verkauf beendet", "fully booked"]):
        logging.info("❌ Tickets not available (fully booked/sale ended).")
        # send_telegram_message(f"❌ No available tickets found for {target_str}.")
        # return
    else:
        logging.info("✅ Tickets available for today!")
    
    # Find the link to the detail page
    link_tag = day_cell.select_one("ul.events a.event")
    # logging.info("Event link: %s", link_tag)
    if not link_tag:
        logging.info("No event link found in ul.events. Checking fallback day label link...")
        # If you really want to fallback to the day label link:
        link_tag = day_cell.select_one("a.day-label.event")
    
    if not link_tag or not link_tag.get("href"):
        logging.info("No valid detail link found in the day cell.")
        return
    
    detail_url = link_tag["href"]
    logging.info("Detail url: %s", detail_url)
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
    
    # Find all ticket product rows on the detail page.
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
        if availability_div:
            availability_text = availability_div.get_text(strip=True).lower()
            if "ausgebucht" in availability_text:
                is_sold_out = True
        logging.info("Ticket '%s': sold out? %s ❌", product_title, is_sold_out)
        if "brüderticket" in product_title and not is_sold_out:
            messages.append(f"🧔 Brother ticket available for {target_str}!\nRegister here: {detail_url}")
        elif "schwesternticket" in product_title and not is_sold_out:
            messages.append(f"🧕 Sister ticket available for {target_str}!\nRegister here: {detail_url}")
    
    if messages:
        for msg in messages:
            send_telegram_message(msg)
            logging.info("Notification sent: %s", msg)
    else:
        logging.info("No available tickets found for today.")
        # send_telegram_message(f"❌ No available tickets found for {target_str}.")
    
    logging.info("Done checking today's slots.")

def main():
    while True:
        check_today_slots()
        # Adjust sleep interval as needed.
        time.sleep(30)

if __name__ == "__main__":
    main()
