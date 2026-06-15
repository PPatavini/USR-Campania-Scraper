# Feed RSS (+ Telegram) per gli avvisi USR Campania

Genera automaticamente un **feed RSS** dalla pagina Notizie/Avvisi dell'USR Campania
(`https://www.mim.gov.it/web/miur-usr-campania/notizie`) e, se vuoi, **pubblica le novità
su un canale Telegram**. Tutto gratis, schedulato con GitHub Actions, senza server tuoi.

Il sito non offre un RSS ufficiale: questo progetto lo ricava facendo lo scraping della
pagina. È un feed **non ufficiale**.

---

## Cosa ti serve
- Un account GitHub (gratuito).
- (Opzionale, solo per Telegram) un bot e un canale Telegram.

## Installazione in 4 passi

### 1. Crea il repository
Crea un nuovo repo su GitHub e carica questi file mantenendo la struttura:

```
scraper.py
requirements.txt
.github/workflows/feed.yml
docs/            (verrà creata in automatico al primo run)
```

### 2. Abilita GitHub Pages
`Settings` → `Pages` → **Source: Deploy from a branch** → Branch: `main`, cartella `/docs` → Save.

Dopo il primo run, il tuo feed sarà raggiungibile a:

```
https://<tuo-utente>.github.io/<nome-repo>/feed.xml
```

Questo è l'URL da incollare in qualsiasi lettore RSS (Feedly, NetNewsWire, Thunderbird, ecc.).

### 3. Lancia la prima volta
Vai su `Actions` → seleziona il workflow **Aggiorna feed USR Campania** → `Run workflow`.
Da lì in poi gira da solo ogni 2 ore (puoi cambiare il `cron` in `feed.yml`).

### 4. (Opzionale) Telegram
1. Su Telegram apri **@BotFather** → `/newbot` → ottieni il **token**.
2. Crea un **canale**, poi aggiungi il tuo bot come **amministratore** del canale.
3. Trova il **chat id** del canale: per un canale pubblico è `@nomecanale`; per uno privato
   usa l'id numerico (formato `-100xxxxxxxxxx`).
4. Nel repo: `Settings` → `Secrets and variables` → `Actions` → `New repository secret`,
   crea:
   - `TELEGRAM_BOT_TOKEN` = il token del bot
   - `TELEGRAM_CHAT_ID` = `@nomecanale` (o l'id numerico)

Al **primo run con Telegram attivo** il programma registra le notizie già presenti **senza
inviarle** (così non riempie il canale di vecchi avvisi); da lì pubblica solo le novità.

> Non vuoi gestire il pezzo Telegram qui dentro? Puoi anche lasciare solo l'RSS e collegare
> l'URL del feed a un bot RSS→Telegram esterno (es. @TheFeedReaderBot).

---

## Se il sito blocca le richieste (anti-bot)

Il portale MIM a volte blocca le richieste automatiche. Se nei log dell'Action vedi un
errore tipo `403` o "risposta troppo corta", sostituisci la funzione `fetch_html` in
`scraper.py` con una versione che usa un browser headless (Playwright), che supera la
maggior parte dei blocchi:

```python
def fetch_html(url: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="it-IT")
        page.goto(url, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()
    return html
```

E aggiungi al workflow, prima del run dello scraper:

```yaml
      - name: Installa Playwright
        run: |
          pip install playwright
          python -m playwright install --with-deps chromium
```

## Se non trova nessuna notizia
Il parser cerca i link che contengono `/web/miur-usr-campania/-/` (lo schema degli articoli
Liferay). Se la struttura della pagina cambiasse, regola `URL_PATTERN` in cima a `scraper.py`
(o passalo come variabile d'ambiente).

## Configurazione rapida (variabili d'ambiente, tutte opzionali)
| Variabile | Default | A cosa serve |
|---|---|---|
| `LIST_URL` | pagina Notizie USR Campania | pagina da leggere (puoi puntarla agli Avvisi) |
| `URL_PATTERN` | `/web/miur-usr-campania/-/` | come riconosce i link delle notizie |
| `MAX_ITEMS` | `30` | quante voci tenere nel feed |
| `FEED_TITLE` / `FEED_DESC` | — | titolo e descrizione del feed |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | attivano la pubblicazione su Telegram |
