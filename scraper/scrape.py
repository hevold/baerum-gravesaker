#!/usr/bin/env python3
"""
Daglig skraper for gravesaker i Bærum kommune – hele kommunen.
Kilde:    https://baerum.gravearbeider.no/soknad/list
Geocoding: Nominatim / OpenStreetMap (nominatim.openstreetmap.org)
"""

import json
import os
import sys
import time
import random
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup

# --- Konfigurasjon -----------------------------------------------------------

BASE_URL   = "https://baerum.gravearbeider.no/soknad/list"
NOMINATIM  = "https://nominatim.openstreetmap.org/search"

DATA_FILE  = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "gravesaker.json")

HEADERS = {
    "User-Agent": "BaerumGravesaker-monitor/1.0 (journalistisk overvaking; kontakt: hevold@gmail.com)",
    "Accept-Language": "nb-NO,nb;q=0.9",
}

# Nominatim krever egen User-Agent
NOM_HEADERS = {
    "User-Agent": "BaerumGravesaker/1.0 (hevold@gmail.com)",
}

# Grov bounding box for hele Bærum – utelukker åpenbart feil treff fra andre kommuner
BAERUM_BOUNDS = {
    "min_lat": 59.80,
    "max_lat": 60.05,
    "min_lon": 10.30,
    "max_lon": 10.75,
}


# --- Geocoding via Nominatim -------------------------------------------------

def geocode_street(veinavn: str) -> tuple[float, float] | None:
    """
    Slå opp koordinater for et gatenavn i Bærum via Nominatim (OSM).
    Returnerer (lat, lon) eller None hvis ikke funnet.
    """
    gate = veinavn.split(",")[0].strip()
    if not gate or len(gate) < 3:
        return None

    # Prøv strukturert søk mot Bærum, Norge
    params = {
        "street":      gate,
        "city":        "Bærum",
        "country":     "Norway",
        "format":      "json",
        "limit":       1,
        "addressdetails": 0,
    }

    try:
        resp = requests.get(NOMINATIM, params=params, headers=NOM_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            # Behold bare treff innenfor Bærums grove bounding box
            b = BAERUM_BOUNDS
            if b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]:
                return lat, lon

        # Fallback: fri-tekst-søk med kommunenavn
        params2 = {
            "q":       f"{gate}, Bærum, Norge",
            "format":  "json",
            "limit":   1,
        }
        resp2 = requests.get(NOMINATIM, params=params2, headers=NOM_HEADERS, timeout=10)
        data2 = resp2.json()
        if data2:
            lat = float(data2[0]["lat"])
            lon = float(data2[0]["lon"])
            b = BAERUM_BOUNDS
            if b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]:
                return lat, lon

    except Exception as e:
        print(f"  ⚠️  Geocoding feilet for '{gate}': {e}", file=sys.stderr)

    return None


# --- Scraping ----------------------------------------------------------------

def fetch_page(page: int) -> list[dict]:
    """Hent én side fra søknadslisten og returner rader som dict-liste."""
    url = f"{BASE_URL}?page={page}&sort=id&order=desc"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ❌ Feil ved henting av side {page}: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []

    for tr in soup.select("table tr"):
        cells = tr.select("td")
        if len(cells) < 6:          # Hopp over header-rader (th) og tomme rader
            continue

        link_el = cells[0].find("a")
        detail_url = ""
        if link_el and link_el.get("href"):
            href = link_el["href"]
            if not href.startswith("http"):
                href = "https://baerum.gravearbeider.no" + href
            detail_url = href

        rows.append({
            "id":          cells[0].get_text(strip=True),
            "sakstittel":  cells[1].get_text(strip=True),
            "arbeidstype": cells[2].get_text(strip=True) if len(cells) > 2 else "",
            "veinavn":     cells[3].get_text(strip=True) if len(cells) > 3 else "",
            "entreprenor": cells[4].get_text(strip=True) if len(cells) > 4 else "",
            "start":       cells[5].get_text(strip=True) if len(cells) > 5 else "",
            "slutt":       cells[6].get_text(strip=True) if len(cells) > 6 else "",
            "kilde_url":   detail_url,
        })

    return rows


def get_total_pages(soup: BeautifulSoup) -> int:
    """Les totalt antall sider fra .paginate-buttons-lenker."""
    max_page = 1
    for a in soup.select(".paginate-buttons a"):
        try:
            n = int(a.get_text(strip=True))
            if n > max_page:
                max_page = n
        except ValueError:
            pass
    return max_page


def scrape_all() -> list[dict]:
    """Hent alle sider fra søknadslisten."""
    print("🔍 Henter side 1 for å finne totalt antall sider...")
    resp = requests.get(f"{BASE_URL}?page=1&sort=id&order=desc", headers=HEADERS, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    total_pages = get_total_pages(soup)
    print(f"   → Totalt {total_pages} sider")

    all_rows = fetch_page(1)

    for page in range(2, total_pages + 1):
        print(f"   → Side {page}/{total_pages}...", end=" ", flush=True)
        rows = fetch_page(page)
        all_rows.extend(rows)
        print(f"{len(rows)} rader")
        time.sleep(random.uniform(0.8, 1.5))

    return all_rows


# --- Statusberegning ---------------------------------------------------------

def parse_date_no(s: str) -> date | None:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def compute_status(start_str: str, slutt_str: str) -> str:
    today = date.today()
    start = parse_date_no(start_str)
    slutt = parse_date_no(slutt_str)
    if not start:
        return "ukjent"
    if start > today:
        return "planlagt"
    if slutt and slutt < today:
        return "avsluttet"
    return "pågår"


# --- Hovedprogram ------------------------------------------------------------

def main():
    today_iso = datetime.now().isoformat()
    print(f"\n🕳️  Bærum gravesaker – kommunemonitor")
    print(f"   Kjøredato: {today_iso[:10]}\n")

    # Last inn eksisterende data
    existing: dict[str, dict] = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                for item in json.load(f):
                    existing[item["id"]] = item
            print(f"📂 Lastet {len(existing)} eksisterende saker\n")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠️  Kunne ikke lese eksisterende data: {e}\n")

    # Skrap alle sider
    all_rows = scrape_all()
    print(f"\n✅ Hentet totalt {len(all_rows)} søknader fra baerum.gravearbeider.no\n")

    # Geocode og lagre nye saker (alle i Bærum)
    new_count  = 0
    skip_count = 0
    geocode_cache: dict[str, tuple[float, float] | None] = {}

    for row in all_rows:
        # Oppdater status for eksisterende saker
        if row["id"] in existing:
            existing[row["id"]]["status"] = compute_status(row["start"], row["slutt"])
            continue

        veinavn = row.get("veinavn", "")

        # Geocode (med cache for samme gatenavn)
        if veinavn not in geocode_cache:
            coords = geocode_street(veinavn)
            geocode_cache[veinavn] = coords
            time.sleep(1.1)   # Nominatim: maks 1 req/sek
        else:
            coords = geocode_cache[veinavn]

        if coords:
            lat, lon = coords
            row["lat"]          = lat
            row["lon"]          = lon
            row["status"]       = compute_status(row["start"], row["slutt"])
            row["scraped_date"] = today_iso
            existing[row["id"]] = row
            new_count += 1
            print(f"  📍 {row['id']:8} | {veinavn[:35]:35} | {row['status']:10} | {lat:.4f},{lon:.4f}")
        else:
            skip_count += 1
            # Lagre likevel, uten koordinater (vises i tabell men ikke på kart)
            row["status"]       = compute_status(row["start"], row["slutt"])
            row["scraped_date"] = today_iso
            existing[row["id"]] = row
            new_count += 1

    # Lagre
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    all_cases = sorted(existing.values(), key=lambda x: x.get("id", ""), reverse=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Resultat:")
    print(f"   Nye saker:           {new_count}")
    print(f"   Uten koordinater:    {skip_count}")
    print(f"   Totalt i databasen:  {len(existing)}")
    print(f"   Lagret til:          {DATA_FILE}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"new_cases={new_count}\n")
            f.write(f"total_cases={len(existing)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
