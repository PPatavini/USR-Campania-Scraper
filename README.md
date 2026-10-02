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

Il portale MIM sta dietro ad Akamai, che può decidere di rifiutare le richieste che
arrivano dai datacenter. È successo il **2 ottobre 2026 alle 11:00 UTC**: da un momento
all'altro ogni richiesta dai runner GitHub ha iniziato a ricevere `403 Access Denied`.

**Non è un blocco aggirabile dal codice.** Verificato con un workflow di prova fatto
girare su un runner GitHub, provando quattro strategie:

| Strategia | Esito |
|---|---|
| `requests` con gli header attuali | 403 |
| `requests` con header di browser completi + cookie di sessione | 403 |
| `curl_cffi` con impronta TLS di Chrome | 403 |
| Playwright, Chromium headless vero | 403 |

Lo stesso 403 arriva su `robots.txt`, sulla homepage, sui vecchi domini `miur.gov.it` e
`istruzione.it`. Akamai blocca **l'indirizzo IP**, non il travestimento del client: la
richiesta non raggiunge nemmeno il sito. Anche i relay di lettura di terze parti
(`r.jina.ai`, allorigins, codetabs) falliscono, segno che il blocco riguarda il traffico
dai datacenter in generale, non solo GitHub.

> Nelle versioni precedenti questo README consigliava di passare a Playwright. **Non
> funziona**, ed è stato verificato sul campo: un browser headless vero prende 403 esatta-
> mente come `requests`. Il consiglio è rimasto qui per mesi senza che nessuno lo provasse.

### Cosa fa lo scraper quando è bloccato

Riconosce il 403 come blocco anti-bot e **non fa fallire il run**: far fallire servirebbe
solo a mandare una mail di errore ogni 15 minuti per qualcosa che non si può riparare da
qui. Al suo posto:

- stampa un `::warning::`, visibile nella scheda `Actions` e nel riepilogo del run;
- annota in `state/seen.json` la chiave `bloccato_dal`, così si vede a colpo d'occhio se
  dura da un'ora o da una settimana;
- salta la pubblicazione su Pages (senza `docs/feed.xml` quei passi andrebbero in rosso);
- **non perde niente**: gli avvisi non consegnati restano fuori dallo stato e partono tutti
  al primo giro che riesce a leggere la pagina. Il marcatore `bloccato_dal` sparisce da solo.

Un errore diverso (un `500`, la pagina che cambia struttura) continua invece a far fallire
il run rumorosamente, perché quello sì che richiede un intervento.

### Come tornare a leggere il sito

Il blocco è sull'IP, quindi l'unica strada è farsi vedere da un indirizzo diverso:

1. **Aspettare.** Le regole Akamai cambiano. Lo scraper continua a riprovare ogni 15
   minuti e riparte da solo, recuperando gli arretrati. Costo zero, nessuna garanzia.
2. **Un runner self-hosted** su una macchina di casa (anche un Raspberry Pi acceso).
   L'IP residenziale non è bloccato. È la soluzione solida, ma vuole una macchina accesa.
3. **Un proxy con IP residenziali italiani.** Funziona, costa, e aggiunge una dipendenza.

Vale anche la pena **abbassare la frequenza**: 96 richieste al giorno sulla stessa pagina
sono un profilo che un WAF nota. Una ogni 30-60 minuti dà gli stessi avvisi con un quarto
del rumore.

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
- **Il run è `failed`.** Guarda *quale passo* è fallito. Se è "Genera feed", di solito è
  il sito MIM che risponde `403` (vedi la sezione qui sopra) o che ha cambiato struttura.
  Se il run non ha eseguito nessun passo, è GitHub che non ha trovato runner liberi
  (vedi sotto).
- **Un passo di Pages è rosso ma il run resta verde.** È voluto. I tre passi finali
  (`Configura Pages`, `Carica la cartella docs`, `Pubblica su GitHub Pages`) sono marcati
  `continue-on-error`, perché quando arrivano gli avvisi sono già stati mandati su
  Telegram e lo stato è già stato committato: far fallire il run servirebbe solo a
  mandarti una mail per un feed che verrà ripubblicato 15 minuti dopo. Se sono rossi per
  giorni di fila, allora vale la pena guardarci: il feed RSS è fermo anche se il canale
  è aggiornato.
- **I run sono verdi ma sul canale non arriva niente.** Nel log cerca la riga
  `[OK] Telegram: inviati N/M avvisi`: se `N < M` qualche invio è stato rifiutato e verrà
  ritentato da solo al giro successivo.

### Se GitHub non trova runner liberi

Capita che i job restino in coda senza che GitHub assegni loro una macchina
(`The job was not acquired by Runner of type hosted even after multiple attempts`).
È successo il pomeriggio del 6 agosto 2026, per ore: alcuni run partivano dopo 5 minuti,
altri restavano fermi 15 minuti e venivano annullati dal dispatch successivo senza aver
eseguito niente.

**Attenzione: `timeout-minutes` non serve a niente in questo caso.** Conta solo il tempo
di esecuzione, non quello passato in coda in attesa di un runner: un job può restare
`queued` ben oltre il proprio timeout. Il tempo di coda lo decide GitHub, che dopo circa
15 minuti si arrende da solo. Non c'è modo di accorciarlo dal workflow.

La buona notizia è che non si perde niente: gli avvisi non mandati restano fuori da
`state/seen.json` e partono al primo giro che riesce a girare. Un'ora di runner
irraggiungibili si traduce in avvisi in ritardo, non in avvisi persi.

Quello che si può fare è **chiedere meno macchine**. Per questo scraping e pubblicazione
stanno in un unico job invece che in due: un job solo significa un solo runner da
ottenere per giro, cioè metà delle occasioni di incappare nel problema. È il motivo per
cui il job separato `deploy`, introdotto il 5 agosto, è stato riaccorpato il giorno dopo.

Il `timeout-minutes` del job e il `timeout: 180000` passato a `actions/deploy-pages`
servono invece per l'altro caso: quando il runner c'è ma il passo si impianta lo stesso,
come le deployment di Pages che il 6 agosto restavano appese in `deployment_in_progress`
per 10 minuti a botta.

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
