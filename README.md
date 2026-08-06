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
state/seen.json  (verrà creato in automatico: gli avvisi già mandati)
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

Il workflow parte solo su richiesta (`workflow_dispatch`): la schedulazione è affidata a
[cron-job.org](https://cron-job.org), che ogni 15 minuti chiama l'API di GitHub
`POST /repos/<utente>/<repo>/actions/workflows/feed.yml/dispatches` con `{"ref":"main"}`.
In alternativa puoi rimettere un blocco `schedule:` con un `cron` dentro `feed.yml`.

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

Chi è già stato mandato sul canale è scritto in `state/seen.json`, che l'Action ricommitta
sul repo a ogni novità. Ci finiscono **solo gli avvisi effettivamente consegnati**: se
Telegram rifiuta un messaggio (per esempio per il limite di ~20 messaggi al minuto per
canale), quell'avviso non viene segnato come inviato e viene ritentato al giro dopo.
Gli invii sono distanziati di 4 secondi l'uno dall'altro e in caso di `429` lo script
aspetta il tempo richiesto da Telegram e riprova.

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

## Se il canale Telegram smette di aggiornarsi

Prima cosa da guardare: la scheda `Actions` del repo.

- **I run risultano `cancelled` uno dopo l'altro, senza log.** È capitato a fine luglio
  2026: un run era rimasto piantato in stato `waiting` sull'ambiente `github-pages` e,
  con `concurrency.cancel-in-progress: false`, teneva occupata la coda. Ogni run
  successivo restava in attesa e veniva annullato da quello dopo, all'infinito — quindi
  né feed né Telegram si aggiornavano, e GitHub non manda notifiche per i run annullati.
  Ora il workflow usa `cancel-in-progress: true`, così un run bloccato viene annullato
  dal successivo e la catena riparte da sola. Se dovesse ricapitare, basta annullare a
  mano il run più vecchio rimasto appeso.
- **I run sono `failed`.** Guarda *quale* job è fallito. Se è `build`, guarda il log del
  passo "Genera feed": di solito è il sito MIM che risponde `403` (vedi la sezione qui
  sopra) o che ha cambiato struttura. Se è `deploy`, è un problema dell'infrastruttura
  GitHub Pages e non tocca Telegram (vedi sotto).
- **Il job `deploy` fallisce ma il run resta verde.** È voluto. Il deploy su Pages è
  marcato `continue-on-error`, perché quando parte gli avvisi sono già stati mandati su
  Telegram: far fallire il run servirebbe solo a mandarti una mail per un feed che verrà
  ripubblicato 15 minuti dopo. Se `deploy` fallisce per giorni di fila, allora vale la
  pena guardarci: il feed RSS è fermo anche se il canale è aggiornato.
- **I run sono verdi ma sul canale non arriva niente.** Nel log cerca la riga
  `[OK] Telegram: inviati N/M avvisi`: se `N < M` qualche invio è stato rifiutato e verrà
  ritentato da solo al giro successivo.

### Perché i timeout sono così stretti

Il job `build` ha `timeout-minutes: 8`, `deploy` ne ha 5, e `actions/deploy-pages` si
arrende dopo 3 minuti. Non è pignoleria: nel caso peggiore un run dura 13 minuti, cioè
meno dei 15 che passano fra un dispatch e l'altro. Se un run sfora, è ancora in corso
quando arriva il successivo, che lo annulla — e da lì parte una catena in cui nessun run
arriva più in fondo. È successo il 6 agosto 2026, quando le deployment di Pages restavano
appese in `deployment_in_progress` per 10 minuti a botta. Se cambi la frequenza del cron
esterno, ricontrolla che la somma dei timeout ci stia dentro.

### Rimandare avvisi persi

Se qualche avviso non è mai arrivato sul canale, lancia il workflow a mano
(`Actions` → `Run workflow`) impostando **`resend_last`** al numero di avvisi più recenti
da rimandare: vengono tolti da `state/seen.json` e ripubblicati al giro successivo.

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
| `STATE_FILE` | `state/seen.json` | dove tiene traccia degli avvisi già inviati |
| `TELEGRAM_INTERVAL` | `4` | secondi di pausa fra un messaggio e l'altro |
| `RESEND_LAST` | `0` | rimanda gli ultimi N avvisi già inviati (recupero manuale) |
