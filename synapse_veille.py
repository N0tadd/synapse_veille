"""
Veille SYNAPSE — Notifications Discord
By N0tad
"""

import re, requests, threading, json, os, sys, time, gc, schedule
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta

# ─── CONFIG ───────────────────────────────────────────────────────────────────

KEYWORDS        = ["cloison", "plafond", "menuiserie", "doublage", "isolation"] # à personnaliser
BASE_URL        = "https://eu.eu-supply.com"
PAGE_URL        = f"{BASE_URL}/ctm/supplier/publictenders?B=SYNAPSE"
POST_URL        = f"{BASE_URL}/ctm/Supplier/publictenders/PublicTenders"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1497169206695694436/6roh1yrAtNtjEqw67vY8NPOlBKMDo9RwsDnzxx_VjcAf496W3kU-K_PEOMFNC3lsiRVO" # à personnaliser

DIR         = os.path.dirname(os.path.abspath(__file__))
FICHIER_VUS = os.path.join(DIR, "synapse_vus.json")
FICHIER_LOG = os.path.join(DIR, "synapse_veille.log")

# HEADER HTTP (Le User Agent utilisé ici est propre à moi)

HEADERS = {
    "User-Agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept-Language":    "fr-FR,fr;q=0.9",
    "X-Requested-With":   "XMLHttpRequest",
    "Accept":             "*/*",
    "Content-Type":       "application/x-www-form-urlencoded; charset=UTF-8",
    "Sec-Ch-Ua":          '"Not-A.Brand";v="24", "Chromium";v="146"',
    "Sec-Ch-Ua-Mobile":   "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site":     "same-origin",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Dest":     "empty",
    "Origin":             BASE_URL,
    "Referer":            PAGE_URL,
}

POST_DATA = {
    "SearchFilter.SortField":             "None",
    "SearchFilter.SortDirection":         "None",
    "SearchFilter.Reference":             "",
    "SearchFilter.TenderId":              "0",
    "SearchFilter.OperatorId":            "3",
    "Branding":                           "SYNAPSE",
    "SavedCategoryId":                    "",
    "SavedUnitAndName":                   "",
    "SearchFilter.PublishType":           "1",
    "SearchFilter.BrandingCode":          "SYNAPSE",
    "CpvContainer.CpvCodes":              "",
    "CpvContainer.CpvMain":               "",
    "CpvContainer.ContractType":          "",
    "CpvContainer.CpvIds":                "",
    "CpvContainer.IsMandatory":           "True",
    "SearchFilter.ShowExpiredRft":        "false",
    "SearchFilter.PagingInfo.PageNumber": "1",
    "SearchFilter.PagingInfo.PageSize":   "100",
}

# ─── LOGS ─────────────────────────────────────────────────────────────────────

class Logger:
    def __init__(self, f):
        self.terminal = sys.stdout
        self.log = open(f, "a", encoding="utf-8")

    def write(self, m):
        self.terminal.write(m)
        self.log.write(m)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

sys.stdout = Logger(FICHIER_LOG)

# ─── STOCKAGE ─────────────────────────────────────────────────────────────────

def charger_vus() -> set:
    if not os.path.exists(FICHIER_VUS):
        return set()
    try:
        with open(FICHIER_VUS, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, ValueError):
        print("[WARN] eusupp_vus.json corrompu, réinitialisation")
        return set()

def sauvegarder_vus(vus: set):
    with open(FICHIER_VUS, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, indent=2)

# ─── DISCORD ──────────────────────────────────────────────────────────────────

def envoyer_discord(lien: str, infos: dict):
    champs = [("🏢 Acheteur", "acheteur"), ("⏳ Date limite", "date_limite"),
              ("📋 Procédure", "procedure"), ("🔍 Mot-clé", "mot_cle")]
    fields = [{"name": n, "value": infos[k], "inline": True} for n, k in champs if infos.get(k)]
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"embeds": [{
            "title":       f"📢 {infos.get('titre', 'Nouvel AO')[:200]}",
            "description": f"[Consulter l'avis]({lien})",
            "color":       0x2ECC71,
            "url":         lien,
            "fields":      fields,
            "footer":      {"text": "eu-supply SYNAPSE — Veille SONISO"},
        }]}, timeout=10)
        r.raise_for_status()
        print(f"  [DISCORD] Envoyé : {lien}")
    except Exception as e:
        print(f"  [ERREUR] Discord : {e}")

# ─── REQUÊTE ──────────────────────────────────────────────────────────────────

def fetch(kw: str, dates: tuple, results: dict):
    try:
        with requests.Session() as s:
            s.headers.update(HEADERS)
            s.get(PAGE_URL, timeout=15)
            r = s.post(POST_URL, timeout=15, data={
                **POST_DATA,
                "SearchFilter.ShortDescription": kw,
                "TextFilter":                    kw,
                "SearchFilter.FromDate":         dates[0],
                "SearchFilter.ToDate":           dates[1],
            })
            print(f"  [{kw}] {r.status_code} — {len(r.content)} octets")
            results[kw] = r.text
    except Exception as e:
        print(f"  [ERREUR] fetch({kw}) : {e}")
        results[kw] = ""

# ─── SCRAPE ───────────────────────────────────────────────────────────────────

def scraper():
    try:
        print(f"\n[CHECK] {time.strftime('%Y-%m-%d %H:%M:%S')} — Scraping eu-supply SYNAPSE...")

        today  = datetime.today()
        dates  = ((today - timedelta(days=3650)).strftime("%d/%m/%Y"), today.strftime("%d/%m/%Y"))

        # Requêtes en parallèle
        results = {}
        threads = [threading.Thread(target=fetch, args=(kw, dates, results)) for kw in KEYWORDS]
        for t in threads: t.start()
        for t in threads: t.join()

        # Extraction via Playwright
        tous = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            for kw in KEYWORDS:
                html = results.get(kw, "")
                if not html:
                    continue
                page = context.new_page()
                page.set_content(html, wait_until="domcontentloaded")

                def tip(sel, root):
                    el = root.query_selector(sel)
                    return (el.get_attribute("data-original-title") or el.inner_text()).strip() if el else ""

                for tr in page.query_selector_all("tbody tr"):
                    lien_el = tr.query_selector("td:nth-child(3) a[href]")
                    if not lien_el:
                        continue
                    href = BASE_URL + lien_el.get_attribute("href")
                    tous[href] = {
                        "titre":       lien_el.inner_text().strip(),
                        "date_limite": tip("td:nth-child(5) div", tr),
                        "procedure":   tip("td:nth-child(6) div", tr),
                        "acheteur":    tip("td:nth-child(7) div", tr),
                        "mot_cle":     kw,
                    }
                page.close()
            context.close()
            browser.close()

        del results
        gc.collect()

        print(f"  {len(tous)} avis scrappés au total")

        vus      = charger_vus()
        nouveaux = {l: i for l, i in tous.items() if l not in vus}

        if not nouveaux:
            print("  Aucun nouvel avis.")
            return

        print(f"  {len(nouveaux)} nouvel(aux) avis trouvé(s) !")
        for lien, infos in sorted(nouveaux.items()):
            envoyer_discord(lien, infos)
            vus.add(lien)
            time.sleep(1)

        sauvegarder_vus(vus)

    except Exception as e:
        print(f"[ERREUR CRITIQUE] scraper() : {e}")
        import traceback; traceback.print_exc()

# ─── LANCEMENT ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"{'='*60}\nVeille eu-supply SYNAPSE — toutes les 30 min\n"
          f"   Keywords : {KEYWORDS}\n"
          f"   Logs : {FICHIER_LOG}\n   JSON : {FICHIER_VUS}\n{'='*60}\n")
    scraper()
    schedule.every(30).minutes.do(scraper)
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"[ERREUR] Boucle principale : {e}")
        time.sleep(30)
