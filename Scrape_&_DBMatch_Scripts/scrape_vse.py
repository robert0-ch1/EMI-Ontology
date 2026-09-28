"""
Scrape Vintage Synth Explorer's SynthFinder listing.

Visits every page of https://www.vintagesynth.com/synthfinder and extracts
the manufacturer and name for each synth. Saves to data/vse_synths.csv.

Polite scraping: sequential requests with a 2-second delay, identifying
User-Agent, and honours HTTP 429 rate-limit headers if returned.
One-time scrape for non-commercial research use.
"""

import requests
from bs4 import BeautifulSoup
import csv
import os
import time
import re

# --- Configuration ---
BASE_URL = "https://www.vintagesynth.com/synthfinder"
OUTPUT_PATH = "data/vse_synths.csv"
DELAY_SECONDS = 2

HEADERS = {
    "User-Agent": (
        "SynthOntology/1.0 "
        "(one-time scrape)"
    )
}


def fetch_page(page_num):
    """Fetch one page of the synth finder. Returns the HTML text."""
    params = {"page": str(page_num)} if page_num > 0 else {}
    response = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)

    # If the server asks us to slow down, listen
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 30))
        print(f"  Rate-limited; waiting {retry_after}s...")
        time.sleep(retry_after)
        return fetch_page(page_num)  # retry

    response.raise_for_status()
    return response.text


def parse_synths(html):
    """
    Extract (manufacturer, name) tuples from one page's HTML.

    On VSE listings, manufacturers appear as <h3> headings, followed by
    a series of <div class="views-row"> entries containing one synth each.
    We walk the content in order, tracking the current manufacturer.
    """
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".view-content")
    if not content:
        return []

    results = []
    current_manufacturer = None

    for element in content.children:
        # Skip text nodes and whitespace
        if not hasattr(element, "name") or element.name is None:
            continue

        if element.name == "h3":
            current_manufacturer = element.get_text(strip=True)

        elif element.name == "div" and "views-row" in element.get("class", []):
            link = element.select_one("a")
            if link and current_manufacturer:
                name = link.get_text(strip=True)
                # Fix HTML entities that survived as literal text
                name = name.replace("&eacute;", "é")
                name = name.replace("&amp;", "&")
                results.append((current_manufacturer, name))

    return results


def find_total_pages():
    """Look at page 0's pagination to find the highest page number."""
    html = fetch_page(0)
    soup = BeautifulSoup(html, "html.parser")

    # The "Last page" link tells us the maximum page number
    last_link = soup.select_one(".pager__item--last a")
    if last_link:
        match = re.search(r"page=(\d+)", last_link.get("href", ""))
        if match:
            return int(match.group(1)) + 1  # pages are 0-indexed

    # Fallback: scan all visible page numbers
    page_nums = [0]
    for link in soup.select(".pager__item a"):
        match = re.search(r"page=(\d+)", link.get("href", ""))
        if match:
            page_nums.append(int(match.group(1)))
    return max(page_nums) + 1


def main():
    # Make sure the data folder exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    print("Discovering pagination...")
    total_pages = find_total_pages()
    print(f"  Found {total_pages} pages")
    print()

    all_synths = []

    for page_num in range(total_pages):
        print(f"Scraping page {page_num + 1}/{total_pages}...", end=" ", flush=True)
        try:
            html = fetch_page(page_num)
            synths = parse_synths(html)
            all_synths.extend(synths)
            print(f"got {len(synths)} synths")
        except requests.RequestException as e:
            print(f"FAILED: {e}")
            continue

        if page_num < total_pages - 1:
            time.sleep(DELAY_SECONDS)

    print()
    print(f"Total synths scraped: {len(all_synths)}")

    # Save to CSV
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["manufacturer", "name"])
        writer.writerows(all_synths)

    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()