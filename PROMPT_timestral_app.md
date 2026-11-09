# Progetto: app locale di forecasting agnostica con Timestral

## Obiettivo

Realizza un'applicazione web che gira interamente in locale. L'utente carica un qualsiasi dataset tabellare con una serie temporale, sceglie quale colonna è il tempo e quale il valore da prevedere, e ottiene:

- una valutazione onesta di quanto è bravo il modello (backtest contro baseline semplici);
- le previsioni future con intervalli di incertezza;
- una dashboard interattiva.

Il modello è **Timestral** di Mistral AI, una famiglia di time-series foundation model zero-shot in quattro taglie: 5M, 28M, 123M e 209M parametri.

Nessun database: l'app è stateless. I file caricati vengono elaborati in memoria e i risultati restano nello stato del frontend. L'utente può salvarli scaricando un JSON e ricaricarlo in un secondo momento.

## Stack

- **Backend**: Python ≥ 3.10, FastAPI, Uvicorn, pandas, numpy, openpyxl, torch ≥ 2.4. Timestral si installa con `pip install git+https://github.com/mistralai/timestral.git`. Gestisci le dipendenze con `uv` (lockfile committato).
- **Frontend**: Next.js (App Router), TypeScript strict, Tailwind CSS, Recharts per i grafici. Interfaccia in italiano.
- **Monorepo**:
  ```
  /backend    → API FastAPI + logica di forecasting
  /frontend   → app Next.js
  /samples    → dataset di esempio
  README.md
  Makefile    → make setup, make dev (avvia entrambi), make test
  ```
- Il backend gira su `localhost:8000`, il frontend su `localhost:3000`. Abilita CORS solo per l'origine del frontend.

## Come lavorare

1. Prima di scrivere codice, leggi il sorgente del pacchetto `timestral` installato (`forecaster.py` in particolare) e verifica l'API reale. Non inventare parametri. Quello che so oggi è riportato nella sezione "API Timestral", ma la fonte di verità è il codice.
2. Presentami un piano breve (struttura dei file, endpoint, schema JSON) e procedi.
3. Implementa in quest'ordine, facendo un commit per ogni fase:
   1. preprocessing con i suoi test;
   2. backtest e metriche con i loro test;
   3. API;
   4. frontend;
   5. rifinitura.
4. Prima di dichiarare finita una fase, fai girare i test e il criterio di accettazione relativo.

## API Timestral (da verificare sul sorgente)

```python
from timestral import TimestralForecaster
f = TimestralForecaster.from_pretrained("mistralai/Timestral-28M")  # device="cuda" opzionale
fc = f.forecast(context, prediction_length=h)
# context: np.ndarray o tensor (B, V, T), (B, T) o (T,); NaN = valore mancante
# fc.quantiles: torch.Tensor (B, V, H, 21), ordinati sull'asse dei quantili
# fc.quantile_levels: tuple di 21 livelli (0.01, 0.05, 0.1, ..., 0.9, 0.95, 0.99)
# fc.median -> (B, V, H); fc.quantile(level) richiede un livello ESATTO della tupla
```

Dettagli utili:

- Per i quantili usa sempre l'indice del livello più vicino in `quantile_levels`, non il confronto esatto tra float.
- Opzioni di `forecast`:
  - `symmetric_averaging=True` di default;
  - `clip_nonnegative=True` di default: se il contesto è tutto non negativo, le previsioni vengono tagliate a 0;
  - `observation_mask`, `past_covariates`, `known_covariates`.
- I tensori vanno convertiti con `.cpu().numpy()`.
- Il contesto massimo è 32.768 passi: oltre, il modello tiene solo i più recenti.
- I pesi si scaricano da Hugging Face al primo uso:

  | Taglia | Peso |
  |---|---|
  | 5M | ~21 MB |
  | 28M | ~111 MB |
  | 123M | ~490 MB |
  | 209M | ~837 MB |

  Poi restano nella cache di HF e si possono caricare offline con `local_files_only=True`.
- Il device va scelto in automatico: `cuda` se disponibile, altrimenti `cpu`. Non usare MPS senza averlo verificato.

## Flusso utente

1. **Caricamento.** Drag & drop o selezione di un file: CSV, TSV, XLSX o JSON (array di oggetti). Limite di 50 MB. Il backend prova in automatico separatore ed encoding.
2. **Anteprima e mappatura.** L'app mostra le prime 20 righe e il tipo rilevato per ogni colonna, poi chiede:
   - **Colonna del tempo** (obbligatoria), precompilata con la colonna più probabile.
   - **Valore da prevedere** (obbligatorio), precompilato con la prima colonna numerica che non sia il tempo.
   - **Colonna di raggruppamento** (opzionale): se il file contiene più serie (per esempio una per prodotto o per squadra), l'utente sceglie la colonna e poi il gruppo da analizzare.
   - **Aggregazione dei duplicati**: se più righe cadono sullo stesso istante, somma (default) oppure media.
3. **Impostazioni**, con default sensati:
   - taglie del modello da confrontare (default: 5M e 28M; avvisa del peso delle taglie grandi);
   - orizzonte di previsione;
   - numero di finestre di backtest.
4. **Elaborazione.** Il job parte in background e il frontend mostra le fasi in corso: caricamento modello, backtest, previsione. Il primo download dei pesi può richiedere minuti, quindi va mostrato chiaramente.
5. **Dashboard** (vedi sotto). Da qui l'utente può cambiare taglia o serie senza ricaricare il file, oppure ripartire con un altro dataset.

## Preprocessing (backend)

**Rilevamento della colonna del tempo.** In ordine di priorità:
1. colonne parsabili come date o datetime (ISO, `dd/mm/yyyy`, `yyyy-mm`, timestamp);
2. anni interi plausibili (1800–2100);
3. stagioni sportive nel formato `2016-2017` o `2016/17`, ordinate per anno di inizio;
4. una colonna intera monotona crescente, trattata come indice.

**Frequenza.** Si ricava dalla colonna del tempo:
- con `pd.infer_freq` sulle date regolari;
- altrimenti con il passo mediano tra osservazioni consecutive, mappato su orario, giornaliero, settimanale, mensile, trimestrale, annuale o stagionale;
- per anni, stagioni e indici il passo è 1.

**Serie regolare.** Va ordinata per tempo e riportata su una griglia regolare alla frequenza rilevata. I buchi diventano NaN (Timestral li gestisce come mancanti): non interpolare.

**Etichette future.** Le prossime `h` etichette si generano con la stessa frequenza e lo stesso formato dell'input. Per esempio, dopo `2025-2026` vengono `2026-2027`, `2027-2028`.

**Stagionalità.** Il periodo stagionale si deduce dalla frequenza: 24 per orario, 7 per giornaliero, 52 per settimanale, 12 per mensile, 4 per trimestrale, nessuno per annuale e stagionale. Serve alla baseline seasonal naive e alla MASE.

**Validazione.** Restituisce errori chiari in italiano, senza stack trace, se:
- i valori non sono numerici;
- la serie ha meno di 8 osservazioni valide;
- il tempo non è ordinabile;
- ci sono troppi mancanti (oltre il 50%).

## Backtest e metriche (backend)

**Rolling origin.** Ogni finestra prevede `h_bt` passi usando solo i dati precedenti:
- `h_bt` = orizzonte scelto, ma 1 per serie con meno di 30 punti;
- finestre = min(scelta utente, quante ne entrano lasciando almeno `max(4, 2·h_bt)` punti di contesto), default 10, massimo 50;
- le origini sono le ultime N, con passo `h_bt` (finestre che non si sovrappongono).

**Efficienza.** Per serie corte fai una chiamata per origine. Per serie lunghe puoi raggruppare le origini in batch, allineando i contesti a destra con NaN a sinistra, ma solo dopo aver verificato con un test che i risultati coincidono con le chiamate singole entro 1e-4. Altrimenti resta sulle chiamate singole.

**Baseline**, calcolate sulle stesse finestre:
- **naive**: ultimo valore osservato;
- **media ultime k**: k = 3 per serie corte, altrimenti pari al periodo stagionale o 7;
- **seasonal naive**: solo se c'è un periodo stagionale e almeno due cicli di storia.

**Metriche**, per modello e per baseline, aggregate su tutte le finestre e i passi:
- MAE, RMSE, sMAPE (quest'ultima ignorando i denominatori nulli);
- MASE, scalata sull'errore naive in-sample della storia disponibile;
- solo per Timestral: copertura dell'intervallo 10–90%, ampiezza media dell'intervallo e WQL sui 21 quantili.

**Previsione futura.** Usa tutta la storia e restituisce P10, P50 e P90 per ogni passo, insieme ai 21 quantili completi.

**Sintesi.** Per ogni taglia, una frase che dice se batte o meno la baseline migliore sulla MAE e di quanto.

## API

Lo stato in memoria vive in un dizionario di job con TTL di un'ora e in una cache dei modelli già caricati: nessun database.

| Metodo | Endpoint | Descrizione |
|---|---|---|
| `GET` | `/api/health` | Stato del server e device |
| `GET` | `/api/models` | Taglie disponibili e quali sono già in cache locale |
| `POST` | `/api/inspect` | Multipart con il file → `file_id`, colonne con tipo rilevato, anteprima di 20 righe, colonna del tempo e valore suggeriti, valori distinti della colonna di gruppo se richiesta |
| `POST` | `/api/forecast` | JSON `{file_id, time_col, value_col, group_col?, group_value?, aggregation, models[], horizon, backtest_windows}` → `{job_id}` |
| `GET` | `/api/jobs/{job_id}` | `{status: queued\|running\|done\|error, stage, progress 0–1, message?, result?}` |

I file caricati restano in memoria per `file_id` con lo stesso TTL. I job girano in un thread pool e l'inferenza è serializzata con un lock per modello.

### Schema di `result`

```json
{
  "meta": {"time_col": "...", "value_col": "...", "group": null, "frequency": "season", "season_length": null,
           "n_obs": 10, "n_missing": 0, "horizon": 3, "backtest_horizon": 1, "backtest_windows": 6},
  "history": [{"t": "2016-2017", "y": 9.0}],
  "baselines": ["naive", "mean_k"],
  "models": {
    "Timestral-28M": {
      "backtest": [{"origin": "2019-2020", "t": "2020-2021", "step": 1, "y": 19.0,
                    "p10": 0, "p50": 0, "p90": 0, "naive": 0, "mean_k": 0}],
      "metrics": {"model": {"mae": 0, "rmse": 0, "smape": 0, "mase": 0, "coverage_80": 0, "width_80": 0, "wql": 0},
                  "naive": {"mae": 0, "rmse": 0, "smape": 0, "mase": 0},
                  "mean_k": {"...": 0}},
      "forecast": [{"t": "2026-2027", "p10": 0, "p50": 0, "p90": 0, "quantiles": [0]}],
      "summary": "..."
    }
  }
}
```

## Dashboard (frontend)

Lo stile prende spunto da una dashboard già esistente: card con bordo leggero, numeri grandi con font serif, testo sans, tema chiaro e scuro, layout responsive da 400 px in su.

- **Intestazione.** Nome del file, serie analizzata e una frase di sintesi ("Con Timestral-28M il modello batte / non batte la baseline migliore: errore medio X contro Y").
- **Controlli.** Selettore della taglia e, se c'è un gruppo, selettore del gruppo (rilancia il job). Pulsante "Nuovo dataset".
- **Riquadri:**
  - MAE di Timestral, verde se batte la baseline migliore, rosso se no;
  - MAE di ogni baseline;
  - copertura 10–90% con l'ampiezza media sotto;
  - previsione del primo passo futuro con il suo intervallo.
- **Grafico principale:**
  - serie storica come linea;
  - previsioni di backtest come punti con barra P10–P90;
  - previsione futura come linea tratteggiata con banda P10–P90 in un'area ombreggiata "previsioni";
  - tooltip con tutti i valori.

  Per serie lunghe aggiungi un brush per zoomare e mostra di default la coda: le ultime 5 × orizzonte osservazioni più le previsioni.
- **Confronto tra taglie.** Barre orizzontali della MAE per ogni taglia elaborata, con linee verticali tratteggiate per ogni baseline. La taglia selezionata è evidenziata.
- **Tabella del backtest.** Ordinabile, con il valore reale in rosso quando esce dall'intervallo.
- **Tabella delle previsioni future**, con P10, P50 e P90.
- **Note chiuse in fondo.** Definizioni delle metriche, frequenza rilevata, finestre usate e avvisi (per esempio "serie corta: interpretare con cautela" sotto i 30 punti).
- **Esportazione:**
  - scarica il risultato in JSON;
  - scarica le previsioni in CSV;
  - ricarica un JSON salvato per rivedere la dashboard senza ricalcolare.

Formattazione dei numeri con locale `it-IT`. Gli stati di caricamento sono skeleton, non spinner, e gli errori del backend vanno mostrati in modo leggibile.

## Test

**Backend (pytest):**
- rilevamento della colonna del tempo e della frequenza su date, mesi, anni, stagioni sportive e indici;
- generazione delle etichette future, inclusa `2025-2026 → 2026-2027`;
- regolarizzazione con buchi;
- metriche su casi calcolati a mano;
- finestre di backtest al limite (serie da 8 punti).

**Smoke test end-to-end** con il marker `slow`, usando Timestral-5M su `samples/gol_stagionali.csv` e su una serie sintetica.

**Frontend:** `tsc --noEmit`, lint e `next build` senza errori.

## Dataset di esempio da creare in `/samples`

**1. `gol_stagionali.csv`**, una serie stagionale corta, reale:

```
Stagione_Anno,Squadra,Presenze,Gol,Pres_Camp,Gol_Camp
2016-2017,Racing Club,28,9,23,9
2017-2018,Racing Club,28,18,21,13
2018-2019,Inter,35,9,27,6
2019-2020,Inter,49,21,35,14
2020-2021,Inter,48,19,38,17
2021-2022,Inter,49,25,35,21
2022-2023,Inter,57,28,38,21
2023-2024,Inter,44,27,33,24
2024-2025,Inter,48,22,31,12
2025-2026,Inter,47,23,30,17
```

**2. `vendite_mensili.csv`**: 8 anni mensili sintetici con trend, stagionalità annuale e rumore, generati con seed fisso.

**3. `sensore_orario.csv`**: 60 giorni orari sintetici con ciclo giornaliero, qualche buco e due colonne gruppo (`sensore_a`, `sensore_b`) in formato lungo.

## Criteri di accettazione

1. `make setup && make dev` avvia tutto. Su `localhost:3000` si carica `gol_stagionali.csv`, si scelgono `Stagione_Anno` e `Gol`, e la dashboard compare.
2. **Riproducibilità.** Su `gol_stagionali.csv` con colonna `Gol`, orizzonte 3, backtest a 1 passo, 6 finestre e media delle ultime 3 come baseline, i risultati devono coincidere entro ±0,01 con quelli già ottenuti:

   | Modello | MAE modello | MAE naive | MAE media 3 | Copertura 80% |
   |---|---|---|---|---|
   | Timestral-209M | 4,957 | 3,000 | 4,722 | 0,833 |
   | Timestral-5M | 4,251 | 3,000 | 4,722 | — |

   Per la 5M la copertura non va verificata. Se non tornano, indaga la causa (contesto, quantili, opzioni di `forecast`) prima di andare avanti.
3. Con `vendite_mensili.csv` la frequenza rilevata è mensile, la stagionalità è 12, compare la baseline seasonal naive e le etichette future sono mesi corretti.
4. Con `sensore_orario.csv` si può scegliere il gruppo; i buchi restano mancanti e non vengono interpolati.
5. Un file con 5 righe o con una colonna di testo come valore produce un messaggio d'errore chiaro nella UI.
6. Il JSON scaricato e poi ricaricato riproduce la stessa dashboard senza chiamare il backend.
7. Il README spiega installazione, avvio, primo download dei pesi, uso offline e limiti noti.

## Fuori scope per ora

Autenticazione, database, deploy, covariate e forecasting multivariato. Lascia però il codice strutturato in modo che le covariate di Timestral (`past_covariates` e `known_covariates`) si possano aggiungere in seguito senza riscrivere il backtest.
