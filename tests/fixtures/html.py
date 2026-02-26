"""
Simulated HTML for the IZA daily iftar site.
Used to test the checker without hitting the real site.
"""

BASE_URL = "https://dailyiftar.imsuaachen.de/"


def calendar_page(date_str: str, detail_path: str = "/127/", status: str = "wenige verfügbar") -> str:
    """
    Build a calendar page HTML fragment containing one day cell.
    date_str: e.g. "25.02.2026" (must match data-date).
    detail_path: href for the event link (e.g. "/127/" or "https://dailyiftar.imsuaachen.de/127/").
    status: text inside .event-status (e.g. "wenige verfügbar", "ausgebucht", "sale over").
    """
    return f"""
    <table><tr>
    <td class="day" data-date="{date_str}">
        <span class="event-status">{status}</span>
        <ul class="events">
            <li><a class="event" href="{detail_path}">18:17 Iftar</a></li>
        </ul>
    </td>
    </tr></table>
    """


def detail_page(
    brother_available: bool = True,
    sister_available: bool = True,
    brother_reserved: bool = False,
    sister_reserved: bool = False,
    language: str = "de",
) -> str:
    """
    Build a detail page with product rows for Bruder and Schwester tickets.
    language: "de" | "en" — product titles and sold-out text.
    *_reserved: if True, that ticket is "Reserviert"/"Reserved" (not bookable).
    """
    if language == "de":
        brother_title = "🧔Brüderticket"
        sister_title = "🧕Schwesternticket"
        sold_out_text = "ausgebucht"
        available_text = "Verfügbar"
    else:
        brother_title = "🧔Brotherticket"
        sister_title = "🧕Sisterticket (ONLY FOR WOMEN)"
        sold_out_text = "SOLD OUT"
        available_text = "Select"

    def product_row(title: str, available: bool, reserved: bool = False) -> str:
        if reserved:
            status = "Reserviert" if language == "de" else "Reserved"
            extra_class = " reserved"
        else:
            status = available_text if available else sold_out_text
            extra_class = ""
        return f"""
        <article class="product-row">
            <h4>{title}</h4>
            <div class="availability-box{extra_class}">{status}</div>
        </article>
        """

    rows = (
        product_row(brother_title, brother_available, reserved=brother_reserved)
        + product_row(sister_title, sister_available, reserved=sister_reserved)
    )
    return f"<div>{rows}</div>"
