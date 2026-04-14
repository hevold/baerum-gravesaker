#!/usr/bin/env python3
"""
Daglig skraper for gravesaker i Bærum kommune – filtrerer på Eiksmarka.
Kilde: https://baerum.gravearbeider.no/soknad/list
Geocoding: Kartverkets adresse-API (ws.geonorge.no)
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

BASE_URL = "https://baerum.gravearbeider.no/soknad/list"
KARTVERKET_API = "https://ws.geonorge.no/adresser/v1/sok"
KOMMUNENUMMER = "3024"   # Bærum

# Omtrentlig bounding box for Eiksmarka (litt sjenerøs for å fange alle gater)
EIKSMARKA = {
    "min_lat": 59.910,
    "max_lat": 59.960,
    "min_lon": 10.480,
    "max_lon": 10.580,
}

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "gravesaker.json")

HEADERS = {
    "User-Agent": "BaerumGravesaker-monitor/1.0 (journalistisk overvåking av offentlige gravearbeider)",
    "Accept-Language": "nb-NO,nb;q=0.9",
}

# Fallback: kjente Eiksmarka-gatenavn dersom geocoding feiler
EIKSMARKA_STREETS = {
    "eiksmarka", "myrvollveien", "granåsveien", "granasveien",
    "eiksveien", "eiksbakken", "røykenveien", "roykenveien",
    "eiksmarka stasjon", "franzefossveien", "eikslia", "hosleveien",
    "nedre eiksmarka", "øvre eiksmarka", "øvre granåsvei",
}


# --- Geocoding ---------------------------------------------------------------

def geocode_street(veinavn: str) -> tuple[float, float] | None:
    """Slå opp koordinater for et gatenavn i Bærum via Kartverkets API."""
    # Bruk bare første gatenavn hvis det er en kommaseparert liste
    gate = veinavn.split(",")[0].strip()
    if not gate:
        return None

    params = {
        "sok": gate,
        "kommunenummer": KOMMUNENUMMER,
        "treffPerSide": 1,
        "side": 0,
    }

    try:
        resp = requests.get(KARTVERKET_API, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        adresser = data.get("adresser", [])
        if adresser:
            punkt = adresser[0].get("representasjonspunkt", {})
            lat = punkt.get("lat")
            lon = punkt.get("lon")
            if lat and lon:
                return float(lat), float(lon)
    except Exception as e:
        print(f"  ⚠️  Geocoding feilet for '{gate}': {e}", file=sys.stderr)

    return None


def is_in_eiksmarka(lat: float, lon: float) -> bool:
    """Sjekk om koordinatene er innenfor Eiksmarkas bounding box."""
    b = EIKSMARKA
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]


def street_matches_eiksmarka(veinavn: str) -> bool:
    """Fallback: sjekk om gatenavnet ligner kjente Eiksmarka-gater."""
    lower = veinavn.lower()
    return any(s in lower for s in EIKSMARKA_STREETS)


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

    for tr in soup.select("table tbody tr"):
        cells = tr.select("td")
        if len(cells) < 6:
            continue

        # Prøv å hente lenke til detalj-side
        link_el = cells[0].find("a")
        detail_url = ""
        if link_el and link_el.get("href"):
            detail_url = "https://baerum.gravearbeider.no" + link_el["href"]

        rows.append({
            "id": cells[0].get_text(strip=True),
            "sakstittel": cells[1].get_text(strip=True),
            "arbeidstype": cells[2].get_text(strip=True) if len(cells) > 2 else "",
            "veinavn": cells[3].get_text(strip=True) if len(cells) > 3 else "",
            "entreprenor": cells[4].get_text(strip=True) if len(cells) > 4 else "",
            "start": cells[5].get_text(strip=True) if len(cells) > 5 else "",
            "slutt": cells[6].get_text(strip=True) if len(cells) > 6 else "",
            "kilde_url": detail_url,
        })

    return rows


def get_total_pages(soup_page1: BeautifulSoup) -> int:
    """Les totalt antall sider fra pagineringslenker."""
    links = soup_page1.select(".pagination a, ul.pagination li a")
    max_page = 1
    for a in links:
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

    all_rows = fetch_page(1)  # side 1 er allerede hentet

    for page in range(2, total_pages + 1):
        print(f"   → Side {page}/{total_pages}...", end=" ")
        rows = fetch_page(page)
        all_rows.extend(rows)
        print(f"{len(rows)} rader")
        time.sleep(random.uniform(0.8, 1.5))  # høflig forsinkelse

    return all_rows


# --- Statusberegning ---------------------------------------------------------

def parse_date_no(s: str) -> date | None:
    """Parser norsk datoformat DD.MM.YYYY."""
    s = s.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def compute_status(start_str: str, slutt_str: str) -> str:
    """Beregn status basert på datoer."""
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
    print(f"\n🕳️  Bærum gravesaker – Eiksmarka-monitor")
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
    print(f"\n✅ Hentet totalt {len(all_rows)} søknader fra baerum.gravearbeider.no")

    # Filtrer og geocode nye saker
    new_count = 0
    geocode_cache: dict[str, tuple[float, float] | None] = {}

    for row in all_rows:
        if row["id"] in existing:
            # Oppdater status for eksisterende saker
            existing[row["id"]]["status"] = compute_status(row["start"], row["slutt"])
            continue

        veinavn = row.get("veinavn", "")

        # Sjekk fallback-matching først (raskere)
        if street_matches_eiksmarka(veinavn):
            lat, lon = geocode_cache.get(veinavn) or (None, None)
            if lat is None:
                coords = geocode_street(veinavn)
                geocode_cache[veinavn] = coords
                if coords:
                    lat, lon = coords

            if lat:
                row["lat"] = lat
                row["lon"] = lon
            row["status"] = compute_status(row["start"], row["slutt"])
            row["scraped_date"] = today_iso
            existing[row["id"]] = row
            new_count += 1
            print(f"  📍 Ny sak (fallback): {row['id']} – {veinavn}")
            continue

        # Geocode og sjekk bounding box
        coords = geocode_cache.get(veinavn)
        if veinavn not in geocode_cache:
            coords = geocode_street(veinavn)
            geocode_cache[veinavn] = coords
            time.sleep(0.3)

        if coords:
            lat, lon = coords
            if is_in_eiksmarka(lat, lon):
                row["lat"] = lat
                row["lon"] = lon
                row["status"] = compute_status(row["start"], row["slutt"])
                row["scraped_date"] = today_iso
                existing[row["id"]] = row
                new_count += 1
                print(f"  📍 Ny sak (geocode): {row['id']} – {veinavn} ({lat:.4f}, {lon:.4f})")

    # Lagre oppdatert data
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    all_cases = sorted(existing.values(), key=lambda x: x.get("id", ""), reverse=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, ensure_ascii=False, indent=2)

    print(f"\n📊 Resultat:")
    print(f"   Nye Eiksmarka-saker: {new_count}")
    print(f"   Totalt i databasen:  {len(existing)}")
    print(f"   Lagret til:          {DATA_FILE}")

    # GitHub Actions output
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"new_cases={new_count}\n")
            f.write(f"total_cases={len(existing)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
