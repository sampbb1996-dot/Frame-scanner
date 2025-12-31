import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

FRAME_OBJECTS = [
    {"terms": ["outdoor table", "garden table"], "min_price": 150},
    {"terms": ["garden bench", "outdoor bench"], "min_price": 120},
    {"terms": ["outdoor setting", "table and chairs"], "min_price": 250},
    {"terms": ["wrought iron"], "min_price": 180},
]

FRAME_TOLERANCE = 0.25
SEARCH_TERMS = ["outdoor", "garden", "bench", "table", "wrought"]
LOCATION = "sydney"

BASE_URL = "https://www.gumtree.com.au/s-ads/{}"


def parse_price(text):
    if not text:
        return None
    t = text.lower()
    if "free" in t:
        return 0
    nums = re.findall(r"\d+", t.replace(",", ""))
    return int(nums[0]) if nums else None


def extract_listings(term):
    r = requests.get(
        BASE_URL.format(term),
        headers=HEADERS,
        params={"location": LOCATION, "sort": "date"},
        timeout=15,
    )
    soup = BeautifulSoup(r.text, "lxml")
    listings = []

    for a in soup.select("a[href*='/s-ad/']"):
        title = a.get_text(strip=True).lower()
        link = a.get("href")
        container = a.find_parent("div")
        price_el = container.select_one(".user-ad-price__price") if container else None
        price = parse_price(price_el.get_text(strip=True)) if price_el else None

        listings.append({
            "title": title,
            "price": price,
            "link": "https://www.gumtree.com.au" + link,
        })

    return listings


def frame_collapse(listing):
    if listing["price"] is None:
        return False
    for obj in FRAME_OBJECTS:
        if any(t in listing["title"] for t in obj["terms"]):
            if listing["price"] < obj["min_price"] * FRAME_TOLERANCE:
                return True
    return False


def main():
    seen = set()
    for term in SEARCH_TERMS:
        for l in extract_listings(term):
            if l["link"] in seen:
                continue
            seen.add(l["link"])
            if frame_collapse(l):
                print("FRAME COLLAPSE")
                print(f"${l['price']} | {l['title']}")
                print(l["link"])
                print("----")


if __name__ == "__main__":
    main()
