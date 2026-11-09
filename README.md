# Previsioni locali con Timestral

Applicazione web che gira interamente in locale per prevedere serie temporali con **Timestral** di Mistral AI, una famiglia di foundation model zero-shot (5M, 28M, 123M e 209M parametri).

Carichi un file tabellare, scegli la colonna del tempo e il valore da prevedere, e ottieni:

- un **backtest onesto** (rolling origin) contro baseline semplici: naive, media delle ultime k e naive stagionale;
- le **previsioni future** con intervallo P10–P90 e i 21 quantili completi;
- una **dashboard** interattiva, esportabile in JSON (ricaricabile senza ricalcolare) e in CSV.

Non c'è nessun database: i file e i risultati vivono in memoria nel backend per un'ora, e nello stato della pagina.

```
backend/       API FastAPI e logica di forecasting (Python, uv)
frontend/      dashboard Next.js (TypeScript, Tailwind, Recharts)
samples/       dataset di esempio e script che genera quelli sintetici
turbo.json     task del monorepo (Turborepo)
package.json   workspace npm alla radice
Makefile       scorciatoie make per gli stessi script npm
```

Il monorepo è gestito con **Turborepo** su npm workspaces. Il backend resta un progetto Python gestito da uv: il suo `backend/package.json` serve solo a esporre a Turborepo i task `dev`, `test`, `test:fast` e `lint`, che chiamano `uv run …`. Così `turbo run` orchestra entrambe le parti e mette in cache i risultati di test, lint, typecheck e build: se i file non cambiano, il task non viene rieseguito. I test del backend considerano anche `samples/` tra i propri input.

Tutti i comandi si lanciano dalla radice con `npm run <script>`. Il `Makefile` è solo una scorciatoia per chi usa `make`: ogni target chiama lo script npm omonimo (`make dev` → `npm run dev`).

| Script | Cosa fa |
|---|---|
| `npm run setup` | `npm install` e `uv sync` nel backend |
| `npm run dev` | backend e frontend insieme (`turbo run dev`) |
| `npm run test` | pytest, ruff, tsc, eslint e `next build`, con cache |
| `npm run test:fast` | solo i test veloci del backend |
| `npm run lint` | ruff, eslint e tsc |
| `npm run build` | build di produzione del frontend |
| `npm run samples` | rigenera i dataset sintetici |

## Requisiti

- Python ≥ 3.10 e [uv](https://docs.astral.sh/uv/) (`pip install uv`, oppure l'installer ufficiale)
- Node.js ≥ 20 e npm
- `uv` raggiungibile nel PATH, perché i task di Turborepo lo invocano direttamente. Se l'hai installato con `pip install --user uv`, su Windows aggiungi `%APPDATA%\Python\Python3XX\Scripts` al PATH.
- `make`, facoltativo: basta npm; su Windows `make` si installa con `winget install GnuWin32.Make`
- Un browser recente: Next.js 16 richiede almeno Chrome/Edge 111, Firefox 111 o Safari 16.4
- GPU NVIDIA facoltativa: senza GPU si usa la CPU

## Installazione

```bash
npm run setup        # oppure: make setup
```

che esegue `npm install` (workspace npm con frontend e Turborepo, lockfile alla radice) e poi `uv sync` in `backend/`, che crea `backend/.venv` dal lockfile di uv.

Timestral si installa dal repository di Mistral ed è fissato nel lockfile di uv. Per aggiornarlo:

```bash
cd backend
uv add "timestral @ git+https://github.com/mistralai/timestral.git"
```

## Avvio

```bash
npm run dev          # oppure: make dev
```

Avvia insieme il backend su <http://localhost:8000> e il frontend su <http://localhost:3000>. Per avviarne uno solo:

```bash
npx turbo run dev --filter=backend
npx turbo run dev --filter=frontend
```

Apri <http://localhost:3000>, trascina `samples/gol_stagionali.csv`, scegli `Stagione_Anno` come tempo e `Gol` come valore, poi avvia la previsione.

### Configurazione

| Variabile | Dove | Default | Effetto |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | frontend (`frontend/.env.local`) | `http://localhost:8000` | Indirizzo del backend |
| `FRONTEND_ORIGIN` | backend | `http://localhost:3000` | Origini ammesse dal CORS (separate da virgola) |
| `TIMESTRAL_DEVICE` | backend | automatico | Forza `cpu` o `cuda`; di default `cuda` se disponibile, altrimenti `cpu` |
| `TIMESTRAL_OFFLINE` | backend | non impostata | Con `1` carica i pesi solo dalla cache locale |

## Primo download dei pesi

I pesi si scaricano da Hugging Face la prima volta che una taglia viene usata, e restano nella cache di HF (`~/.cache/huggingface/hub`):

| Taglia | Peso |
|---|---|
| Timestral-5M | ~21 MB |
| Timestral-28M | ~111 MB |
| Timestral-123M | ~490 MB |
| Timestral-209M | ~837 MB |

Durante il download la UI lo segnala nella fase "Caricamento del modello", e nelle impostazioni ogni taglia indica se è già in cache. Le taglie grandi sono anche le più lente in inferenza, soprattutto su CPU.

Per scaricare i pesi in anticipo, per esempio prima di andare offline:

```bash
cd backend
uv run python -c "from timestral import TimestralForecaster as T; [T.from_pretrained(f'mistralai/Timestral-{s}') for s in ('5M','28M')]"
```

## Uso offline

Una volta in cache, le taglie si caricano senza rete: il backend usa automaticamente `local_files_only=True` per i pesi già presenti. Per evitare del tutto chiamate di rete:

```bash
TIMESTRAL_OFFLINE=1 npm run dev     # oppure HF_HUB_OFFLINE=1
```

Se una taglia non è in cache, il job si ferma con un messaggio che lo spiega.

## Come funziona

**Preprocessing.** La colonna del tempo viene riconosciuta in quest'ordine: date e datetime (ISO, `dd/mm/yyyy`, `yyyy-mm`, timestamp Unix), anni (1800–2100), stagioni sportive (`2016-2017`, `2016/17`), interi crescenti usati come indice. La frequenza si ricava con `pd.infer_freq` o dal passo mediano. La serie viene portata su una griglia regolare in cui i buchi restano `NaN`, senza interpolazione: Timestral li tratta come valori mancanti. Le righe sullo stesso istante si sommano o si mediano. Il periodo stagionale vale 24 per i dati orari, 7 per i giornalieri, 52 per i settimanali, 12 per i mensili e 4 per i trimestrali.

**Backtest.** Le finestre non si sovrappongono e terminano sull'ultima osservazione. Ogni finestra prevede `h_bt` passi (l'orizzonte scelto, oppure 1 sotto i 30 punti) e lascia almeno `max(4, 2·h_bt)` punti di contesto; le finestre sono al massimo 50. Nelle serie da almeno 30 punti le origini vengono raggruppate in batch, allineate a destra con `NaN`: un test verifica che i risultati coincidano con le chiamate singole entro 1e-4.

**Metriche.**
- MAE, RMSE e sMAPE, quest'ultima ignorando i denominatori nulli.
- MASE, scalata sull'errore naive in-sample di ogni finestra (stagionale quando la baseline stagionale è attiva).
- Solo per Timestral: copertura e ampiezza dell'intervallo 10–90% e WQL sui 21 quantili.

**Riproducibilità.** Su `gol_stagionali.csv` (valore `Gol`, orizzonte 3, 6 finestre) i risultati coincidono con quelli di riferimento:

| Modello | MAE modello | MAE naive | MAE media 3 | Copertura 80% |
|---|---|---|---|---|
| Timestral-209M | 4,957 | 3,000 | 4,722 | 0,833 |
| Timestral-5M | 4,251 | 3,000 | 4,722 | — |

### API

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `GET` | `/api/health` | Stato, device, modelli caricati |
| `GET` | `/api/models` | Taglie, peso e presenza nella cache locale |
| `POST` | `/api/inspect` | Multipart `file` (oppure `file_id`), con `group_col` facoltativo → colonne, tipi, anteprima, suggerimenti, valori dei gruppi |
| `POST` | `/api/forecast` | `{file_id, time_col, value_col, group_col?, group_value?, aggregation, models[], horizon, backtest_windows}` → `{job_id}` |
| `GET` | `/api/jobs/{job_id}` | `{status, stage, progress, message?, result?}` |

La documentazione interattiva è su <http://localhost:8000/docs>.

## Test

```bash
npm run test        # pytest (con gli smoke test slow), ruff, tsc, eslint, next build
npm run test:fast   # solo i test veloci del backend, senza modelli
```

Turborepo mette in cache ogni task: un secondo `npm run test` senza modifiche termina in pochi millisecondi (`FULL TURBO`). Per forzare la riesecuzione usa `npx turbo run test --force`.

Gli smoke test `slow` scaricano la 5M (~21 MB) se non è già in cache.

## Dataset di esempio

- `gol_stagionali.csv`: serie stagionale corta e reale (10 stagioni).
- `vendite_mensili.csv`: 8 anni mensili sintetici con trend, stagionalità annuale e rumore.
- `sensore_orario.csv`: 60 giorni orari di due sensori (`sensore_a`, `sensore_b`) in formato lungo, con buchi.
- `troppo_corto.csv`: 5 righe, per vedere il messaggio d'errore.

`npm run samples` rigenera i dataset sintetici con seed fisso.

## Limiti noti

- **Una serie alla volta, senza covariate.** Il codice è già predisposto per le `past_covariates` e `known_covariates` di Timestral: `ForecastContext` e `SeriesInput.context` le tagliano per ogni origine, ma la UI e l'API non le espongono ancora.
- **Stato volatile.** File e job restano in memoria per un'ora e si perdono al riavvio del backend. Per conservare un'analisi, scarica il JSON.
- **Contesto massimo di 32.768 passi**: oltre, Timestral usa solo i più recenti.
- **Frequenze sotto l'ora** (per esempio 15 minuti) sono gestite come "regolari" senza periodo stagionale. Le frequenze irregolari vengono approssimate con il passo mediano.
- **La baseline stagionale** compare solo se ogni finestra ha almeno due cicli completi di storia.
- **Dashboard ricaricata da JSON**: per calcolare altre taglie o gruppi serve che il file originale sia ancora in memoria nel backend; altrimenti va ricaricato.
- **Prestazioni su CPU**: con le taglie 123M e 209M, serie lunghe e molte finestre il calcolo può richiedere minuti.
