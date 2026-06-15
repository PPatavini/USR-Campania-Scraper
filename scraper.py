#!/usr/bin/env python3
"""
Genera un feed RSS dalla pagina "Notizie/Avvisi" dell'USR Campania (sito MIM)
e, opzionalmente, pubblica le novita' su un canale Telegram.

Pensato per girare dentro una GitHub Action che pubblica su GitHub Pages.
Per capire cosa ha gia' inviato, lo script legge il feed gia' pubblicato:
le notizie che non erano nel feed precedente sono "nuove" -> vanno su Telegram.
"""

import os
import re
import sys
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
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise SystemExit(f"[ERRORE] Il sito ha risposto {resp.status_code}. "
                         f"Probabile blocco anti-bot: vedi 'Se il sito blocca' nel README.")
    if len(resp.text) < 1000:
        raise SystemExit("[ERRORE] Risposta troppo corta: probabile pagina di blocco/challenge.")
    return resp.text


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


# ------------------- Telegram (dedup via feed pubblicato) ------------------
def published_guids():
    if not PUBLISHED_FEED_URL:
        return None
    try:
        r = requests.get(PUBLISHED_FEED_URL, timeout=30)
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.content)
        return {(it.findtext("guid") or it.findtext("link") or "").strip()
                for it in root.iter("item")
                if (it.findtext("guid") or it.findtext("link"))}
    except Exception as e:
        print(f"[WARN] Non riesco a leggere il feed pubblicato: {e}")
        return None


def post_telegram(item):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": f"📣 {item['title']}\n{item['url']}"},
                      timeout=30)
    if not r.ok:
        print(f"[WARN] Telegram ha risposto {r.status_code}: {r.text[:200]}")
    return r.ok


def handle_telegram(items):
    if not (TG_TOKEN and TG_CHAT):
        return
    seen = published_guids()
    if seen is None:
        print("[OK] Feed pubblicato non ancora disponibile: nessun invio (primo avvio).")
        return
    nuovi = [it for it in items if it["url"] not in seen]
    for it in reversed(nuovi):
        post_telegram(it)
    print(f"[OK] Telegram: inviati {len(nuovi)} nuovi avvisi.")


def main():
    items = extract_items(fetch_html(LIST_URL))
    if not items:
        print("[ATTENZIONE] Nessuna notizia trovata. Controlla URL_PATTERN / struttura pagina.")
        sys.exit(1)
    handle_telegram(items)
    build_feed(items)


if __name__ == "__main__":
    main()
