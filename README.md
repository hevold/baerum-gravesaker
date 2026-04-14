# 🕳️ Gravesaker Eiksmarka – Bærum kommune

Automatisk daglig overvåking av gravearbeider i Eiksmarka-området.

**Datakilde:** [baerum.gravearbeider.no](https://baerum.gravearbeider.no/soknad/list)  
**Geocoding:** [Kartverkets adresse-API](https://ws.geonorge.no/adresser/v1/)  
**Dashboard:** Aktivert via GitHub Pages

---

## Oppsett

### 1. Opprett GitHub-repo

Gå til [github.com/new](https://github.com/new) og opprett et nytt repo, f.eks. `baerum-gravesaker`.  
Last opp eller klone disse filene inn i repoet.

### 2. Aktiver GitHub Pages

1. Gå til **Settings → Pages**
2. Under *Source*, velg **Deploy from a branch**
3. Velg branch: `main`, mappe: `/docs`
4. Klikk **Save**

Dashbordet vil være tilgjengelig på:  
`https://<ditt-brukernavn>.github.io/baerum-gravesaker/`

### 3. Gi Actions skrivetilgang

1. Gå til **Settings → Actions → General**
2. Under *Workflow permissions*, velg **Read and write permissions**
3. Klikk **Save**

### 4. Kjør skraperen første gang

1. Gå til **Actions**-fanen
2. Velg **"Daglig gravesaker-skraper"**
3. Klikk **"Run workflow"** → **"Run workflow"**

Etter noen minutter vil `docs/data/gravesaker.json` inneholde Eiksmarka-saker og dashbordet oppdateres automatisk.

---

## Struktur

```
baerum-gravesaker/
├── .github/
│   └── workflows/
│       └── scrape.yml          ← GitHub Actions (kjører daglig kl. 07:00)
├── scraper/
│   └── scrape.py               ← Python-skraperen
├── docs/                       ← GitHub Pages-rot
│   ├── index.html              ← Dashboard med Leaflet-kart
│   └── data/
│       └── gravesaker.json     ← Akkumulert historikk
└── README.md
```

## Hvordan det fungerer

1. **Skraperen** henter alle ~277 søknader fra baerum.gravearbeider.no (~12 sider)
2. **Geocoding** slår opp koordinater for hvert gatenavn via Kartverkets gratis API
3. **Filtrering** beholder kun saker innenfor Eiksmarkas geografiske bounding box  
   (lat: 59.910–59.960, lon: 10.480–10.580)
4. **Nye saker** legges til `gravesaker.json` og pushes automatisk til repoet
5. **Dashbordet** laster JSON-filen og viser alle saker på kart med farger etter status

### Statuser

| Status | Farge | Beskrivelse |
|--------|-------|-------------|
| 🔴 Pågår | Rød | Startdato passert, sluttdato ikke nådd |
| 🔵 Planlagt | Blå | Startdato er i fremtiden |
| ⚫ Avsluttet | Grå | Sluttdato er passert |

---

## Tilpasninger

**Endre bounding box** (søkeområde):  
Rediger `EIKSMARKA`-konstanten øverst i `scraper/scrape.py`.

**Endre kjøretidspunkt:**  
Rediger `cron`-uttrykket i `.github/workflows/scrape.yml`.  
`'0 5 * * *'` = kl. 07:00 norsk sommertid (05:00 UTC).

**Legg til e-postvarsling:**  
Bruk GitHub Actions' innebygde notifikasjoner, eller legg til et steg i workflow-en som sender e-post via f.eks. SendGrid.
