# DocBooK LM

NotebookLM **locale**: carichi fonti, fai domande, ottieni risposte ancorate alle
pagine dei tuoi documenti. Gira interamente sulla macchina (iMac Pro, Radeon Pro
Vega 64 16 GB) sul router `llama.cpp` compilato **Vulkan/MoltenVK**.

Nessuna chiamata esterna: i documenti non escono dal disco.

## Come si avvia

Doppio clic su **`DocBooK LM START.command`**. Apre `http://127.0.0.1:8078/`.

Il launcher verifica che il router `llama.cpp` risponda su `http://127.0.0.1:8080`,
crea `.venv` e `.env` se mancano, avvia l'API e apre il browser. `CTRL+C` ferma
tutto; in alternativa c'e' **`DocBooK LM STOP.command`**.

> Il motore non viene avviato da qui: e' il router di `~/Documents/LLAMA.CPP`
> (preset con contesti misurati sulla Vega 64). Se e' spento, apri
> `LLAMA.CPP START.command`.

## Cosa c'e' dentro

| Pezzo | Scelta |
|---|---|
| Interfaccia | HTML + moduli ES nativi, nessun bundler, nessuna build |
| API | FastAPI su `127.0.0.1:8078`, SSE per lo streaming |
| Dati | SQLite (`data/docbook.db`): quaderni, fonti, passaggi, note, messaggi |
| Ricerca | ibrida: BM25 (FTS5) + denso `bge-m3` + rerank `bge-reranker-v2-m3`, fusi con RRF |
| PDF | pdfium per testo e rendering, Vision OCR per le scansioni |
| Modello | router `llama.cpp` su `:8080`, preset scelto dal selettore |
| Embedding | due sidecar `llama-server` dedicati su `:8091` (bge-m3) e `:8092` (reranker) |

## Interfaccia

Tre pannelli come NotebookLM.

- **Fonti**: trascini PDF, Word, immagini, markdown, csv e archivi zip, oppure
  incolli un link o del testo. Ogni fonte conserva le sue pagine e i suoi
  passaggi. Un archivio zip diventa **una fonte sola**: le pagine dei documenti
  vanno in sequenza e il nome di ciascuno diventa la sezione dei suoi passaggi.
  I file che arrivano senza estensione vengono riconosciuti dal contenuto.
- **Chat**: la risposta arriva in streaming con citazioni `[1]` `[2]`; cliccando
  una citazione si apre la pagina del PDF con la frase evidenziata.
- **Studio**: note salvate sul server. Gli artefatti (riassunto, FAQ, guida di
  studio, timeline, briefing, mappa mentale) compaiono nell'interfaccia e vengono
  generati a partire dalla fase F3.

**Cache.** Il servizio espone gli asset sotto un prefisso nuovo a ogni avvio
(`/s/<token>/app.js`): una copia vecchia rimasta nel browser non ha lo stesso
indirizzo e viene comunque riscaricata, anche se era stata salvata con una
scadenza futura. `Cache-Control: no-store` accompagna sia la pagina sia i file,
e `/static/...` resta come ripiego per una pagina già in cache.

Stile vincolante per ogni modifica futura (`src/docbooklm/static/style.css`):

- spaziature solo sulla **scala 8** (`--s1`…`--s8`: 8, 16, 24, 32, 40, 48, 64, 80 px);
- **una sola palette neutra** (`--c0`…`--c8`), nessun colore di accento, nessun
  gradiente, nessun glow, nessuna ombra;
- **due pesi** di carattere al massimo (400 e 500), scala tipografica 12/14/16/20/28,
  **niente maiuscole** forzate;
- icone a tratto tutte dalla stessa libreria: [Lucide](https://lucide.dev) (MIT),
  16 px, `stroke-width: 1.25`, sprite inline in `static/icons.svg`;
- numeri senza decorazioni;
- stato di caricamento con skeleton, non con spinner colorati.

## Citazioni verificate

Il modello riceve passaggi numerati e deve citarli. Prima di mostrare la risposta,
`chat.verify` controlla ogni marcatore: se la frase che lo contiene non condivide
almeno una parola di contenuto con il passaggio citato, la citazione viene
**rimossa** dal testo. Una citazione che resta e' una citazione che ha un appiglio
nel documento.

## Retrieval ibrido

Tre stadi, in ordine di costo crescente:

1. **lessicale** — BM25 su FTS5 con prefisso e accenti rimossi: trova nomi propri,
   sigle, numeri e i termini esatti del documento;
2. **denso** — `bge-m3` (1024 dimensioni, vettori normalizzati) sui primi ~60
   candidati: trova il senso anche quando la domanda usa parole diverse
   ("quanta memoria video" contro "sedici gigabyte di VRAM");
3. **fusione e rerank** — Reciprocal Rank Fusion (`k = 60`) delle due liste, poi
   il cross-encoder `bge-reranker-v2-m3` riordina i 14 candidati migliori;
   il rerank si salta quando i passaggi entrano comunque tutti nel contesto.

Quanti passaggi finiscono nel prompt lo decide il **contesto**, non un numero
fisso: fino a 32.000 caratteri (~8.000 token, una trentina di secondi di prefill)
per fonte, con un tetto di 16 passaggi. Con pagine brevi — bolle, fatture,
schede — entrano tutte; con i capitoli di un libro otto o nove.

I due modelli girano in **sidecar** `llama-server` separati dal router di chat:

| Servizio | Porta | Modello | Flag |
|---|---|---|---|
| embedding | `127.0.0.1:8091` | `models-embed/bge-m3-Q8_0.gguf` | `--embeddings --pooling cls -ngl 99` |
| rerank | `127.0.0.1:8092` | `models-embed/bge-reranker-v2-m3-Q8_0.gguf` | `--reranking --pooling rank -ngl 99` |

Sono avviati dall'API all'avvio e fermati alla chiusura; non toccano
`models-presets.ini` e non alzano `--models-max` del router. Insieme occupano
~1,3 GB di VRAM, sotto il modello di chat.

Misure sulla Vega 64: query ~60 ms di embedding, rerank di 12 estratti da 700
caratteri ~1,1 s, indicizzazione ~2.500 token/s (un libro di 300 pagine in pochi
minuti, in background).

Se i sidecar non ci sono o i modelli mancano, l'API parte lo stesso: resta BM25
con il riempimento dall'inizio di ogni fonte. E' una degradazione, non un errore.

L'indicizzazione avviene **dopo** l'upload: la fonte e' interrogabile subito per
parole esatte, e sulla scheda compare `ricerca semantica 12/39` finché i vettori
non sono completi.

## Fasi

| Fase | Stato | Contenuto |
|---|---|---|
| F0 | fatto | fondamenta: store SQLite, estrazione, API, launcher, test |
| F1 | fatto | interfaccia NotebookLM a tre pannelli, chat con citazioni, viewer PDF |
| F2 | fatto | retrieval denso (`bge-m3`) + rerank, indice in background |
| F3 | da fare | artefatti Studio (riassunto, FAQ, guida, timeline, briefing) |
| F4 | da fare | mappa mentale (JSON → SVG, nodi cliccabili verso le fonti) |
| F5 | da fare | rifiniture: export conversazione, tabelle PDF con celle unite |

L'**Audio Overview e' escluso dal progetto** per scelta esplicita.

## Comandi

```bash
make setup     # venv 3.12 + dipendenze + .env
make api       # API su :8078
make check     # ruff + mypy + pytest
make test
make stop
```

## API

| Endpoint | Descrizione |
|---|---|
| `GET /` | interfaccia |
| `GET /api/state?notebook=` | quaderni, fonti, note, messaggi, modelli in una chiamata |
| `GET/POST/PATCH/DELETE /api/notebooks` | quaderni |
| `GET /api/sources?notebook=` | elenco fonti, con `embedded`/`n_chunks` dell'indice semantico |
| `POST /api/sources` | upload (`multipart`: `notebook`, `file`) |
| `POST /api/sources/url` | fonte da un link (`{"notebook", "url"}`) |
| `POST /api/sources/text` | testo incollato (`multipart`) |
| `DELETE /api/sources/{id}` | rimuove fonte, passaggi e cache delle pagine |
| `GET /api/sources/{id}/page/{n}.png` | pagina del PDF in PNG |
| `GET /api/sources/{id}/locate?quote=` | rettangoli della frase nella pagina |
| `GET/POST/DELETE /api/notes` | note dello Studio |
| `POST /api/chat` | SSE: `meta`, `reasoning`, `delta`, `done`, `error` |
| `GET /api/models` · `POST /api/models/select` | preset del router e modello corrente |
| `GET /health` | stato del servizio e del router |

## Limiti noti

- il modello e' quello che il router tiene caricato: con `--models-max 1` non si
  possono avere due modelli insieme, quindi il cambio modello puo' costare il
  caricamento del preset (10–30 s la prima volta);
- il ragionamento dei preset Qwen3 e' disattivato (`DOCBOOKLM_THINKING=false`,
  cioe' `enable_thinking: false` nel template della chat): con il thinking
  attivo i token finiscono nel blocco di ragionamento e il contenuto della
  risposta resta vuoto;
- **gpt-oss** (Harmony) non guarda `enable_thinking`: con `DOCBOOKLM_THINKING=false`
  il servizio manda `reasoning_effort: low`, altrimenti il modello spende tutti
  i `max_tokens` nel ragionamento e la risposta resta vuota. I suoi pensieri
  non finiscono nel testo: arrivano come evento `reasoning` e l'interfaccia
  mostra «sto ragionando…» finche' non comincia la risposta;
- domande molto generiche senza parole chiave usano l'inizio di ogni fonte: la
  copertura puo' essere parziale;
- i vettori restano nel database: se cambi modello di embedding (`DOCBOOKLM_EMBED_MODEL`)
  i vecchi vettori non sono confrontabili e vanno ricalcolati (cancella
  `chunk_vec` o reimporta le fonti);
- l'OCR usa Vision: fuori da macOS le scansioni vengono rifiutate con messaggio
  esplicito;
- i siti che caricano i contenuti via JavaScript restano in gran parte vuoti;
- i link verso `localhost` e le reti private sono bloccati (`DOCBOOKLM_ALLOW_PRIVATE_URLS=true`
  per abilitarli).
