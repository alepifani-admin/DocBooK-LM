# Regole del progetto DocBooK LM

## Contesto

NotebookLM locale su macOS Intel (iMac Pro, Vega 64 16 GB), motore = router
`llama.cpp` Vulkan/MoltenVK su `http://127.0.0.1:8080`.

- L'infrastruttura del motore **non si modifica da qui**: preset, build e
  aggiornamenti appartengono al progetto `~/Documents/LLAMA.CPP`.
- DocBooK LM non avvia modelli propri: usa il router per la chat. **Eccezione
  approvata**: per il retrieval denso avvia due sidecar `llama-server` dedicati
  (`bge-m3` su 8091, `bge-reranker-v2-m3` su 8092) con i GGUF di
  `models-embed/`. Non toccano `models-presets.ini` e non alzano `--models-max`;
  se non partono, la ricerca resta lessicale.
- Audio Overview: **fuori dal progetto**.

## Regole di lavoro

1. Committa e carica su GitHub a ogni cambiamento sostanziale.
2. Aggiorna il README e il launcher quando cambiano porte, parametri o comandi.
3. `make check` deve essere verde prima di ogni commit (ruff, mypy, pytest).
4. Ogni estrazione o citazione nuova nasce con il suo test: le regressioni qui
   sono silenziose (una citazione sbagliata sembra una risposta giusta).
5. Non introdurre dipendenze di rete a runtime nell'interfaccia: nessun CDN.
6. Le regole di stile dell'interfaccia sono vincolanti (scala 8, palette neutra,
   due pesi, Lucide, niente maiuscole).
