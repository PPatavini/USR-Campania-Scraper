#!/usr/bin/env python3
"""
Genera un feed RSS dalla pagina "Notizie/Avvisi" dell'USR Campania (sito MIM)
e, opzionalmente, pubblica le novita' su un canale Telegram.

Pensato per girare dentro una GitHub Action che pubblica su GitHub Pages.
Per sapere cosa ha gia' mandato, lo script tiene un file di stato versionato
nel repo (state/seen.json): ci finiscono solo gli avvisi davvero consegnati a
Telegram, cosi' un invio fallito viene ritentato al giro successivo invece di
essere perso. Se il file non c'e' (primo avvio) lo stato viene ricostruito dal
feed gia' pubblicato.
"""

import os
import re
import sys
import json
import time
import datetime as dt
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# ----------------------------- Configurazione -----------------------------
LIST_URL    = os.environ.get("LIST_URL", "https://www.mim.gov.it/web/miur-usr-campania/notizie")
URL_PATTERN = os.environ.get("URL_PATTERN", "/web/miur-usr-campania/-/")
BASE_URL    = os.environ.get("BASE_URL", "https://www.mim.gov.it")

FEED_OUT   = os.environ.get("FEED_OUT", "docs/feed.xml")
MAX_ITEMS  = int(os.environ.get("MAX_ITEMS", "30"))

FEED_TITLE = os.environ.get("FEED_TITLE", "USR Campania - Notizie e Avvisi")
FEED_LINK  = os.environ.get("FEED_LINK", LIST_URL)
FEED_DESC  = os.environ.get("FEED_DESC", "Feed non ufficiale degli avvisi USR Campania")

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Elenco degli avvisi gia' consegnati, dal piu' vecchio al piu' recente.
STATE_FILE = os.environ.get("STATE_FILE", "state/seen.json")
STATE_MAX  = int(os.environ.get("STATE_MAX", "500"))

# Telegram accetta circa 20 messaggi al minuto verso lo stesso canale: oltre
# quella soglia risponde 429. Meglio andare piano che perdere avvisi.
TG_INTERVAL = float(os.environ.get("TELEGRAM_INTERVAL", "4"))
TG_RETRIES  = int(os.environ.get("TELEGRAM_RETRIES", "4"))

# Recupero manuale: rimanda gli ultimi N avvisi gia' registrati come inviati.
RESEND_LAST = int(os.environ.get("RESEND_LAST") or "0")

FETCH_RETRIES = int(os.environ.get("FETCH_RETRIES", "3"))

_owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
_repo  = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]
PUBLISHED_FEED_URL = os.environ.get("PUBLISHED_FEED_URL") or (
    f"https://{_owner.lower()}.github.io/{_repo}/feed.xml" if _owner and _repo else ""
)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Referer": BASE_URL,
}

MESI = {"gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
        "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12}
DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MESI) + r")\s+(\d{4})", re.IGNORECASE)


# --------------------------- Fetch + parsing -------------------------------
def fetch_html(url: str) -> str:
    motivo = ""
    for tentativo in range(1, FETCH_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            motivo = f"errore di rete ({e})"
        else:
            if resp.status_code == 200 and len(resp.text) >= 1000:
                return resp.text
            motivo = (f"HTTP {resp.status_code}" if resp.status_code != 200
                      else "risposta troppo corta (probabile pagina di blocco)")
        if tentativo < FETCH_RETRIES:
            attesa = 5 * tentativo
            print(f"[WARN] Lettura fallita: {motivo}. Riprovo tra {attesa}s.")
            time.sleep(attesa)
    raise SystemExit(f"[ERRORE] Non riesco a leggere {url}: {motivo}. "
                     f"Se il blocco persiste vedi 'Se il sito blocca' nel README.")


def parse_date_near(anchor) -> dt.datetime:
    node = anchor
    for _ in range(4):
        if node is None:
            break
        m = DATE_RE.search(node.get_text(" ", strip=True))
        if m:
            return dt.datetime(int(m.group(3)), MESI[m.group(2).lower()], int(m.group(1)),
                               12, 0, tzinfo=dt.timezone.utc)
        node = node.parent
    return dt.datetime.now(dt.timezone.utc)


def extract_items(html: str):
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if URL_PATTERN not in href:
            continue
        url = urljoin(BASE_URL, href.split("?")[0])
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5 or url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "date": parse_date_near(a)})
        if len(items) >= MAX_ITEMS:
            break
    return items


# ----------------------------------- RSS -----------------------------------
def build_feed(items):
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=FEED_LINK, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("it")
    fg.lastBuildDate(dt.datetime.now(dt.timezone.utc))
    for it in items:
        fe = fg.add_entry()
        fe.id(it["url"]); fe.title(it["title"]); fe.link(href=it["url"])
        fe.guid(it["url"], permalink=True); fe.pubDate(it["date"])
    os.makedirs(os.path.dirname(FEED_OUT) or ".", exist_ok=True)
    fg.rss_file(FEED_OUT, pretty=True)
    print(f"[OK] Scritto {FEED_OUT} con {len(items)} voci.")


# ------------------------------ Stato invii --------------------------------
def published_guids():
    """Guid del feed gia' pubblicato, ordinati dal piu' vecchio al piu' recente."""
    if not PUBLISHED_FEED_URL:
        return None
    try:
        r = requests.get(PUBLISHED_FEED_URL, timeout=30)
        if r.status_code != 200:
            print(f"[WARN] Il feed pubblicato ha risposto {r.status_code}.")
            return None
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[WARN] Non riesco a leggere il feed pubblicato: {e}")
        return None
    guids = [(it.findtext("guid") or it.findtext("link") or "").strip()
             for it in root.iter("item")]
    guids = [g for g in guids if g]
    guids.reverse()  # nel feed il piu' recente sta in cima, qui serve in fondo
    return guids or None


def load_state():
    """Avvisi gia' inviati. None = nessuno stato disponibile (primo avvio)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                dati = json.load(f)
            guids = dati.get("sent") if isinstance(dati, dict) else dati
            if isinstance(guids, list):
                print(f"[OK] Stato letto da {STATE_FILE}: {len(guids)} avvisi gia' inviati.")
                return [str(g) for g in guids]
            print(f"[WARN] {STATE_FILE} ha un formato inatteso: uso il feed pubblicato.")
        except Exception as e:
            print(f"[WARN] {STATE_FILE} illeggibile ({e}): uso il feed pubblicato.")

    guids = published_guids()
    if guids is not None:
        print(f"[OK] Stato ricostruito dal feed pubblicato: {len(guids)} avvisi.")
    return guids


def save_state(guids):
    unici, visti = [], set()
    for g in guids:
        if g not in visti:
            visti.add(g)
            unici.append(g)
    unici = unici[-STATE_MAX:]
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sent": unici}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"[OK] Stato salvato in {STATE_FILE}: {len(unici)} avvisi.")


# --------------------------------- Telegram --------------------------------
def post_telegram(item) -> bool:
    testo = f"📣 {item['title']}\n{item['url']}"
    for tentativo in range(1, TG_RETRIES + 1):
        attesa = 5 * tentativo
        try:
            r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                              json={"chat_id": TG_CHAT, "text": testo}, timeout=30)
        except requests.RequestException as e:
            print(f"[WARN] Telegram irraggiungibile ({e}).")
        else:
            if r.ok:
                return True
            if r.status_code == 429:
                try:
                    attesa = int(r.json()["parameters"]["retry_after"]) + 1
                except Exception:
                    attesa = 30
                print(f"[WARN] Troppi messaggi: Telegram chiede di aspettare {attesa}s.")
            elif r.status_code < 500:
                # 400/403: errore definitivo (chat sbagliata, bot non admin...).
                print(f"[WARN] Telegram ha risposto {r.status_code}: {r.text[:200]}")
                return False
            else:
                print(f"[WARN] Telegram ha risposto {r.status_code}.")
        if tentativo < TG_RETRIES:
            print(f"[WARN] Riprovo tra {attesa}s.")
            time.sleep(attesa)
    print(f"[WARN] Invio non riuscito: {item['url']} (verra' ritentato al prossimo giro).")
    return False


def handle_telegram(items, inviati):
    """Manda le voci non ancora inviate. Torna solo quelle davvero consegnate."""
    if not (TG_TOKEN and TG_CHAT):
        print("[OK] Telegram non configurato: registro le voci senza inviarle.")
        return [it["url"] for it in reversed(items)]

    gia_visti = set(inviati)
    # reversed(): la pagina elenca dal piu' recente, sul canale vanno in ordine.
    nuovi = [it for it in reversed(items) if it["url"] not in gia_visti]
    if not nuovi:
        print("[OK] Telegram: nessuna novita'.")
        return []

    print(f"[OK] Telegram: {len(nuovi)} avvisi da inviare.")
    consegnati = []
    for i, it in enumerate(nuovi):
        if i:
            time.sleep(TG_INTERVAL)
        if post_telegram(it):
            consegnati.append(it["url"])
    print(f"[OK] Telegram: inviati {len(consegnati)}/{len(nuovi)} avvisi.")
    return consegnati


def main():
    items = extract_items(fetch_html(LIST_URL))
    if not items:
        print("[ATTENZIONE] Nessuna notizia trovata. Controlla URL_PATTERN / struttura pagina.")
        sys.exit(1)
    print(f"[OK] Trovate {len(items)} voci sulla pagina.")

    inviati = load_state()
    if inviati is None:
        # Primo avvio: registra quello che c'e' senza riempire il canale.
        print("[OK] Nessuno stato precedente: registro gli avvisi attuali senza inviarli.")
        inviati = [it["url"] for it in reversed(items)]
    else:
        if RESEND_LAST > 0:
            da_rimandare = inviati[-RESEND_LAST:]
            inviati = inviati[:-RESEND_LAST]
            print(f"[OK] RESEND_LAST={RESEND_LAST}: rimando gli ultimi "
                  f"{len(da_rimandare)} avvisi gia' inviati.")
        inviati = inviati + handle_telegram(items, inviati)

    save_state(inviati)
    build_feed(items)


if __name__ == "__main__":
    main()
