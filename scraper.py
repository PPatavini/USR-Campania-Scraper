#!/usr/bin/env python3
"""
Genera un feed RSS dalla pagina "Notizie/Avvisi" dell'USR Campania (sito MIM)
e, opzionalmente, pubblica le novità su un canale Telegram.

Pensato per girare dentro una GitHub Action schedulata.
Configurabile via variabili d'ambiente (vedi sotto / README).
"""

import os
import re
import sys
import json
import datetime as dt
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# --------------------------------------------------------------------------
# Configurazione (tutto sovrascrivibile da env var)
# --------------------------------------------------------------------------
LIST_URL   = os.environ.get("LIST_URL", "https://www.mim.gov.it/web/miur-usr-campania/notizie")
# Le notizie/avvisi su Liferay hanno URL del tipo  .../web/miur-usr-campania/-/<slug>
URL_PATTERN = os.environ.get("URL_PATTERN", "/web/miur-usr-campania/-/")
BASE_URL    = os.environ.get("BASE_URL", "https://www.mim.gov.it")

FEED_OUT   = os.environ.get("FEED_OUT", "docs/feed.xml")
STATE_OUT  = os.environ.get("STATE_OUT", "state.json")
MAX_ITEMS  = int(os.environ.get("MAX_ITEMS", "30"))

FEED_TITLE = os.environ.get("FEED_TITLE", "USR Campania - Notizie e Avvisi")
FEED_LINK  = os.environ.get("FEED_LINK", LIST_URL)
FEED_DESC  = os.environ.get("FEED_DESC", "Feed non ufficiale degli avvisi USR Campania")

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Referer": BASE_URL,
}

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MESI) + r")\s+(\d{4})", re.IGNORECASE)


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def fetch_html(url: str) -> str:
    """Scarica l'HTML. Se il sito blocca le richieste, vedi nota Playwright nel README."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise SystemExit(
            f"[ERRORE] Il sito ha risposto {resp.status_code}. "
            f"Probabile blocco anti-bot: vedi la sezione 'Se il sito blocca' nel README."
        )
    if len(resp.text) < 1000:
        raise SystemExit("[ERRORE] Risposta troppo corta: probabile pagina di blocco/challenge.")
    return resp.text


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def parse_date_near(anchor) -> dt.datetime:
    """Cerca una data italiana ('12 giugno 2026') vicino al link. Best-effort."""
    node = anchor
    for _ in range(4):  # risali di qualche livello cercando il testo della data
        if node is None:
            break
        m = DATE_RE.search(node.get_text(" ", strip=True))
        if m:
            day, month, year = int(m.group(1)), MESI[m.group(2).lower()], int(m.group(3))
            return dt.datetime(year, month, day, 12, 0, tzinfo=dt.timezone.utc)
        node = node.parent
    return dt.datetime.now(dt.timezone.utc)


def extract_items(html: str):
    """Estrae (titolo, url, data) dalle notizie, dedup per URL, mantiene l'ordine di pagina."""
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if URL_PATTERN not in href:
            continue
        url = urljoin(BASE_URL, href.split("?")[0])
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5:   # scarta link vuoti / icone
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "date": parse_date_near(a)})
        if len(items) >= MAX_ITEMS:
            break
    return items


# --------------------------------------------------------------------------
# RSS
# --------------------------------------------------------------------------
def build_feed(items):
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=FEED_LINK, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("it")
    fg.lastBuildDate(dt.datetime.now(dt.timezone.utc))
    for it in items:
        fe = fg.add_entry()
        fe.id(it["url"])
        fe.title(it["title"])
        fe.link(href=it["url"])
        fe.guid(it["url"], permalink=True)
        fe.pubDate(it["date"])
    os.makedirs(os.path.dirname(FEED_OUT) or ".", exist_ok=True)
    fg.rss_file(FEED_OUT, pretty=True)
    print(f"[OK] Scritto {FEED_OUT} con {len(items)} voci.")


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
def load_state():
    try:
        with open(STATE_OUT, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(seen_urls):
    with open(STATE_OUT, "w", encoding="utf-8") as f:
        json.dump({"seen": list(seen_urls)}, f, ensure_ascii=False, indent=2)


def post_telegram(item):
    text = f"📣 {item['title']}\n{item['url']}"
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": False},
        timeout=30,
    )
    if not r.ok:
        print(f"[WARN] Telegram ha risposto {r.status_code}: {r.text[:200]}")
    return r.ok


def handle_telegram(items):
    if not (TG_TOKEN and TG_CHAT):
        return  # Telegram disattivato
    state = load_state()
    current = [it["url"] for it in items]
    if state is None:
        # Primo avvio: registra le notizie esistenti SENZA spammarle.
        save_state(set(current))
        print("[OK] Primo avvio: stato inizializzato, nessun messaggio inviato.")
        return
    seen = set(state.get("seen", []))
    nuovi = [it for it in items if it["url"] not in seen]
    # invia dal più vecchio al più recente per mantenere l'ordine nel canale
    for it in reversed(nuovi):
        if post_telegram(it):
            seen.add(it["url"])
    save_state(seen | set(current))
    print(f"[OK] Telegram: inviati {len(nuovi)} nuovi avvisi.")


# --------------------------------------------------------------------------
def main():
    html = fetch_html(LIST_URL)
    items = extract_items(html)
    if not items:
        print("[ATTENZIONE] Nessuna notizia trovata. Controlla URL_PATTERN / struttura pagina.")
        sys.exit(1)
    build_feed(items)
    handle_telegram(items)


if __name__ == "__main__":
    main()
