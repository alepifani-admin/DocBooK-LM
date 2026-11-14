// Avvio e orchestrazione dell'interfaccia.

import { api } from './api.js';
import * as chatView from './views/chat.js';
import * as sourcesView from './views/sources.js';
import * as studioView from './views/studio.js';
import { createViewer } from './views/viewer.js';
import {
  closeMenus,
  confirmAction,
  icon,
  menu,
  numberFormat,
  promptAction,
  toast,
} from './ui.js';

const $ = (selector) => document.querySelector(selector);

const log = $('#chat-log');
const list = $('#sources-list');
const studio = $('#studio-body');
const question = $('#question');
const dialog = $('#add-dialog');

// Errori non gestiti dell'interfaccia: finiscono nel log del servizio, altrimenti
// restano solo in un avviso che sparisce dopo tre secondi.
function reportError(message, detail = '') {
  try {
    void fetch('/api/client-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: String(message || 'errore'),
        detail: String(detail || ''),
        agent: navigator.userAgent,
      }),
    }).catch(() => {});
  } catch {
    /* niente rete: non vale la pena rompere altro */
  }
}

window.addEventListener('error', (event) => {
  reportError(event.message, `${event.filename}:${event.lineno}\n${event.error?.stack || ''}`);
});
window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  reportError(reason?.message || reason, reason?.stack || '');
});

const state = {
  notebookId: localStorage.getItem('docbook.notebook') || '',
  notebook: null,
  notebooks: [],
  sources: [],
  selected: new Set(),
  notes: [],
  messages: [],
  models: [],
  model: '',
  routerError: '',
  streaming: false,
  controller: null,
};

// ---------------------------------------------------------------- utilità

function sourceById(id) {
  return state.sources.find((source) => source.id === id);
}

function selectedSources() {
  return [...state.selected].map(sourceById).filter((source) => source && source.status === 'ready');
}

function refreshContextInfo() {
  const tokens = sourcesView.totalTokens(state);
  const count = selectedSources().length;
  const info = $('#context-info');
  if (!state.sources.length) info.textContent = 'nessuna fonte';
  else if (!count) info.textContent = 'nessuna fonte selezionata';
  else info.textContent = `${count} ${count === 1 ? 'fonte' : 'fonti'} · ${numberFormat.format(tokens)} token`;
  $('#btn-send').disabled = !count || state.streaming;
}

function renderSources() {
  sourcesView.renderSources(list, state, actions);
  const ready = state.sources.filter((source) => source.status === 'ready');
  $('#source-count').textContent =
    state.sources.length === 0 ? '0 fonti' : `${state.sources.length} ${state.sources.length === 1 ? 'fonte' : 'fonti'}`;
  $('#select-all').checked = ready.length > 0 && ready.every((source) => state.selected.has(source.id));
  $('#select-all').disabled = ready.length === 0;
  $('#btn-clear-sources').disabled = state.sources.length === 0;
  refreshContextInfo();
  scheduleIndexPoll();
}

// L'indicizzazione semantica procede in background dopo l'upload: finché manca
// qualche vettore si ricontrolla ogni 3 s (con un tetto), così l'avanzamento
// sulla scheda della fonte resta leggibile.
let indexPoll = null;
let indexPolls = 0;
const INDEX_POLL_MAX = 100;

function indexPending() {
  return state.sources.some(
    (source) =>
      source.id.startsWith('pending-') ||
      (source.status === 'ready' && source.n_chunks > 0 && source.embedded < source.n_chunks),
  );
}

function scheduleIndexPoll() {
  if (indexPoll || !indexPending() || indexPolls >= INDEX_POLL_MAX) return;
  indexPoll = window.setTimeout(async () => {
    indexPoll = null;
    indexPolls += 1;
    const uploading = state.sources.some((source) => source.id.startsWith('pending-'));
    if (!uploading) {
      try {
        const payload = await api.sources(state.notebookId);
        state.sources = payload.sources;
        renderSources();
      } catch {
        /* rete locale: si riprova al giro successivo */
      }
    }
    scheduleIndexPoll();
  }, 3000);
}

function renderChat() {
  chatView.renderChat(log, state, actions);
}

function renderStudio() {
  studioView.renderStudio(studio, state, actions);
}

function renderHeader() {
  $('#notebook-title').value = state.notebook ? state.notebook.name : 'Il mio quaderno';
  const select = $('#model-select');
  select.replaceChildren();
  if (!state.models.length) {
    const option = document.createElement('option');
    option.textContent = state.routerError ? 'motore non raggiungibile' : 'nessun modello';
    select.appendChild(option);
    select.disabled = true;
  } else {
    select.disabled = false;
    for (const model of state.models) {
      const option = document.createElement('option');
      option.value = model.id;
      option.textContent = model.id;
      option.selected = model.id === state.model;
      select.appendChild(option);
    }
  }
  select.title = state.routerError || `Router: ${state.models.length} preset`;
}

function renderAll() {
  renderHeader();
  renderSources();
  renderChat();
  renderStudio();
}

// ---------------------------------------------------------------- azioni

const viewer = createViewer($('#viewer'), {
  sourceById,
});

const actions = {
  sourceById,
  toggleSource(id) {
    if (state.selected.has(id)) state.selected.delete(id);
    else state.selected.add(id);
    renderSources();
  },
  openSource(id) {
    viewer.openSource(sourceById(id));
  },
  async removeSource(id) {
    const source = sourceById(id);
    if (!source) return;
    if (String(id).startsWith('pending-')) return;  // segnaposto di un upload in corso
    const confirmed = await confirmAction({
      title: 'Eliminare la fonte?',
      message: `«${source.title}» viene rimossa dal quaderno, con il file caricato e i suoi passaggi.`,
    });
    if (!confirmed) return;
    try {
      await api.deleteSource(id);
    } catch (error) {
      // gia' sparita sul server: l'elenco va comunque allineato
      if (!String(error.message).includes('inesistente')) {
        toast(error.message);
        return;
      }
    }
    state.sources = state.sources.filter((item) => item.id !== id);
    state.selected.delete(id);
    renderSources();
  },
  async clearSources() {
    const count = state.sources.length;
    if (!count) return;
    if (typeof api.clearSources !== 'function') {
      toast('Ricarica la pagina (⌘R): l’interfaccia è stata aggiornata');
      return;
    }
    const message =
      count === 1
        ? 'L’unica fonte del quaderno viene rimossa, con il file caricato e i suoi passaggi.'
        : `Le ${count} fonti del quaderno vengono rimosse, con i file caricati e i loro passaggi.`;
    const confirmed = await confirmAction({
      title: count === 1 ? 'Eliminare la fonte?' : 'Eliminare tutte le fonti?',
      message,
      confirmLabel: count === 1 ? 'Elimina' : 'Elimina tutte',
    });
    if (!confirmed) return;
    try {
      await api.clearSources(state.notebookId);
      state.sources = [];
      state.selected = new Set();
      renderSources();
      toast(count === 1 ? 'Fonte eliminata' : `${count} fonti eliminate`);
    } catch (error) {
      toast(error.message);
    }
  },
  ask(text) {
    void send(text);
  },
  openCitation(citation) {
    viewer.openCitation(citation);
  },
  async copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Risposta copiata');
    } catch {
      toast('Copia non riuscita');
    }
  },
  async saveNote(message) {
    const title = (message.text || 'Nota').split('\n')[0].slice(0, 60) || 'Nota';
    try {
      const note = await api.createNote(state.notebookId, title, message.text || '');
      state.notes.unshift(note);
      renderStudio();
      toast('Nota salvata nello Studio');
    } catch (error) {
      toast(error.message);
    }
  },
  regenerate(message) {
    const index = state.messages.indexOf(message);
    const previous = index > 0 ? state.messages[index - 1] : null;
    if (!previous || previous.role !== 'user') return;
    state.messages.splice(index);
    renderChat();
    void send(previous.text, { echo: false });
  },
  openNote(note) {
    viewer.openNote(note, {
      onSave: async (title, markdown) => {
        try {
          const saved = await api.updateNote(note.id, title, markdown);
          Object.assign(note, saved);
          renderStudio();
          toast('Nota aggiornata');
        } catch (error) {
          toast(error.message);
        }
      },
    });
  },
  async removeNote(id) {
    const note = state.notes.find((item) => item.id === id);
    const confirmed = await confirmAction({
      title: 'Eliminare la nota?',
      message: note ? `«${note.title}» viene eliminata dallo Studio.` : 'La nota viene eliminata dallo Studio.',
    });
    if (!confirmed) return;
    try {
      await api.deleteNote(id);
      state.notes = state.notes.filter((note) => note.id !== id);
      renderStudio();
    } catch (error) {
      toast(error.message);
    }
  },
};

// ---------------------------------------------------------------- chat

async function send(text, { echo = true } = {}) {
  const content = (text ?? question.value).trim();
  if (!content || state.streaming) return;

  const selected = selectedSources().map((source) => source.id);
  if (!selected.length) {
    toast('Seleziona almeno una fonte');
    return;
  }

  if (echo) {
    state.messages.push({ role: 'user', text: content });
    renderChat();
  }
  question.value = '';
  autosize();

  state.streaming = true;
  state.controller = new AbortController();
  $('#btn-stop').hidden = false;
  refreshContextInfo();

  const turn = chatView.beginAnswer(log);

  const stopStreaming = () => {
    state.streaming = false;
    state.controller = null;
    $('#btn-stop').hidden = true;
    refreshContextInfo();
  };

  try {
    await api.chat(
      {
        notebook: state.notebookId,
        question: content,
        sources: selected,
        model: state.model,
      },
      {
        delta: (payload) => chatView.appendDelta(turn.answer, payload.text),
        reasoning: (payload) => chatView.showReasoning(turn, payload.chars),
        done: (payload) => {
          const message = {
            role: 'assistant',
            text: payload.text,
            citations: payload.citations || [],
            model: payload.model,
          };
          state.messages.push(message);
          chatView.finishAnswer(turn, message, actions);
          if (!message.citations.length) {
            toast('Nessuna citazione verificata: controlla le fonti');
          }
        },
        error: (payload) => {
          turn.turn.remove();
          chatView.errorTurn(log, payload.message || 'generazione non riuscita');
        },
      },
      state.controller.signal,
    );
  } catch (error) {
    if (error.name === 'AbortError') {
      turn.turn.remove();
      toast('Generazione interrotta');
    } else {
      turn.turn.remove();
      chatView.errorTurn(log, error.message);
    }
  } finally {
    if (state.controller) stopStreaming();
  }
}

function autosize() {
  question.style.height = 'auto';
  question.style.height = `${Math.min(question.scrollHeight, 160)}px`;
}

// ---------------------------------------------------------------- sorgenti

async function uploadFiles(files) {
  const accepted = [...files];
  if (!accepted.length) return;
  indexPolls = 0;  // nuova indicizzazione: il tetto del polling riparte

  const pending = accepted.map((file) => ({
    id: `pending-${file.name}-${Math.random().toString(36).slice(2)}`,
    title: file.name,
    kind: 'pending',
    status: 'processing',
    pages: 0,
    n_tokens: 0,
    origin: file.name,
  }));
  state.sources.push(...pending);
  renderSources();

  for (let index = 0; index < accepted.length; index += 1) {
    const file = accepted[index];
    try {
      const source = await api.upload(state.notebookId, file);
      state.sources = state.sources.filter((item) => item.id !== pending[index].id);
      if (source.duplicate) {
        const existing = sourceById(source.id);
        if (!existing) state.sources.push(source);
        toast(`«${source.title}» era già presente`);
      } else {
        state.sources.push(source);
        state.selected.add(source.id);
      }
    } catch (error) {
      state.sources = state.sources.filter((item) => item.id !== pending[index].id);
      toast(`${file.name}: ${error.message}`);
    }
    renderSources();
  }
  renderChat();
}

async function addUrl(url) {
  try {
    const source = await api.addUrl(state.notebookId, url);
    state.sources.push(source);
    state.selected.add(source.id);
    renderSources();
    renderChat();
    dialog.close();
    toast('Fonte aggiunta');
  } catch (error) {
    toast(error.message);
  }
}

async function addText(title, text) {
  try {
    const source = await api.addText(state.notebookId, title, text);
    state.sources.push(source);
    state.selected.add(source.id);
    renderSources();
    renderChat();
    dialog.close();
    toast('Testo aggiunto');
  } catch (error) {
    toast(error.message);
  }
}

// ---------------------------------------------------------------- quaderni

async function switchNotebook(id) {
  state.notebookId = id;
  localStorage.setItem('docbook.notebook', id);
  await load();
}

async function newNotebook() {
  const name = await promptAction({
    title: 'Nuovo quaderno',
    label: 'Nome',
    value: 'Nuovo quaderno',
    confirmLabel: 'Crea',
  });
  if (!name) return;
  try {
    const notebook = await api.createNotebook(name);
    state.notebooks.push(notebook);
    await switchNotebook(notebook.id);
  } catch (error) {
    toast(error.message);
  }
}

function notebookMenu() {
  const anchor = $('#btn-notebooks');
  const items = state.notebooks
    .filter((notebook) => notebook.id !== state.notebookId)
    .map((notebook) => ({
      label: notebook.name,
      icon: 'notebook',
      onClick: () => void switchNotebook(notebook.id),
    }));
  items.push({ label: 'Nuovo quaderno', icon: 'plus', onClick: () => void newNotebook() });
  menu(anchor, items);
}

// ---------------------------------------------------------------- eventi

$('#composer').addEventListener('submit', (event) => {
  event.preventDefault();
  void send();
});

question.addEventListener('input', autosize);
question.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    void send();
  }
});

$('#btn-stop').addEventListener('click', () => {
  if (state.controller) state.controller.abort();
});

$('#select-all').addEventListener('change', (event) => {
  state.selected = new Set(
    event.target.checked
      ? state.sources.filter((source) => source.status === 'ready').map((source) => source.id)
      : [],
  );
  renderSources();
});

$('#btn-add-source').addEventListener('click', () => {
  if (!dialog.open) dialog.showModal();
});

$('#btn-dialog-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', (event) => {
  if (event.target.hasAttribute('data-close')) dialog.close();
});
for (const tab of dialog.querySelectorAll('.tab')) {
  tab.addEventListener('click', () => {
    for (const other of dialog.querySelectorAll('.tab')) {
      other.setAttribute('aria-selected', String(other === tab));
    }
    for (const panel of dialog.querySelectorAll('[data-panel]')) {
      panel.hidden = panel.dataset.panel !== tab.dataset.tab;
    }
  });
}

$('#btn-choose-file').addEventListener('click', () => $('#file-input').click());
$('#file-input').addEventListener('change', async (event) => {
  const files = event.target.files;
  if (!files || !files.length) return;
  dialog.close();
  await uploadFiles(files);
  event.target.value = '';
});

const filedrop = $('#filedrop');
filedrop.addEventListener('dragover', (event) => {
  event.preventDefault();
  filedrop.classList.add('dragover');
});
filedrop.addEventListener('dragleave', () => filedrop.classList.remove('dragover'));
filedrop.addEventListener('drop', async (event) => {
  event.preventDefault();
  filedrop.classList.remove('dragover');
  if (!event.dataTransfer?.files?.length) return;
  dialog.close();
  await uploadFiles(event.dataTransfer.files);
});

const clearButton = $('#btn-clear-sources');
if (clearButton) {
  // la pagina puo' essere una copia precedente all'aggiunta del pulsante
  clearButton.addEventListener('click', () => void actions.clearSources());
}

$('#btn-add-url').addEventListener('click', () => {
  const url = $('#url-input').value.trim();
  if (url) void addUrl(url);
});
$('#btn-add-text').addEventListener('click', () => {
  const text = $('#text-body').value.trim();
  if (text) void addText($('#text-title').value.trim() || 'Testo incollato', text);
});

const panelSources = $('#panel-sources');
for (const type of ['dragenter', 'dragover']) {
  panelSources.addEventListener(type, (event) => {
    event.preventDefault();
    panelSources.classList.add('dragover');
  });
}
panelSources.addEventListener('dragleave', (event) => {
  if (!panelSources.contains(event.relatedTarget)) panelSources.classList.remove('dragover');
});
panelSources.addEventListener('drop', async (event) => {
  event.preventDefault();
  panelSources.classList.remove('dragover');
  if (event.dataTransfer?.files?.length) await uploadFiles(event.dataTransfer.files);
});

$('#btn-add-note').addEventListener('click', async () => {
  const title = await promptAction({
    title: 'Nuova nota',
    label: 'Titolo',
    value: 'Nota',
    confirmLabel: 'Crea',
  });
  if (title === null) return;
  try {
    const note = await api.createNote(state.notebookId, title || 'Nota', '');
    state.notes.unshift(note);
    renderStudio();
    actions.openNote(note);
  } catch (error) {
    toast(error.message);
  }
});

$('#notebook-title').addEventListener('change', async (event) => {
  const name = event.target.value.trim() || 'Il mio quaderno';
  try {
    await api.renameNotebook(state.notebookId, name);
    state.notebook.name = name;
    const entry = state.notebooks.find((notebook) => notebook.id === state.notebookId);
    if (entry) entry.name = name;
    renderChat();
  } catch (error) {
    toast(error.message);
  }
});

$('#model-select').addEventListener('change', async (event) => {
  const model = event.target.value;
  try {
    await api.selectModel(model);
    state.model = model;
    toast(`Modello: ${model}`);
  } catch (error) {
    toast(error.message);
  }
});

// ------------------------------------------------------ pannello a schermo stretto

function showPanel(name) {
  const workspace = $('#workspace');
  if (name === 'chat') delete workspace.dataset.mobilePanel;
  else workspace.dataset.mobilePanel = name;
  localStorage.setItem('docbook.panel', name);
  for (const button of document.querySelectorAll('#panel-switch [data-panel]')) {
    button.setAttribute('aria-pressed', String(button.dataset.panel === name));
  }
}

for (const button of document.querySelectorAll('#panel-switch [data-panel]')) {
  button.addEventListener('click', () => showPanel(button.dataset.panel));
}

$('#btn-notebooks').addEventListener('click', (event) => {
  event.stopPropagation();
  notebookMenu();
});

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('docbook.theme', theme);
  const button = $('#btn-theme');
  button.replaceChildren(icon(theme === 'dark' ? 'sun' : 'moon'));
  button.title = theme === 'dark' ? 'Tema chiaro' : 'Tema scuro';
}

$('#btn-theme').addEventListener('click', () => {
  applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
});

// divisori trascinabili
for (const resizer of document.querySelectorAll('[data-resizer]')) {
  resizer.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    const which = resizer.dataset.resizer;
    const startX = event.clientX;
    const style = document.documentElement.style;
    const current = parseInt(
      getComputedStyle(document.documentElement).getPropertyValue(
        which === 'sources' ? '--w-sources' : '--w-studio',
      ),
      10,
    );
    const move = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      const width = Math.max(240, Math.min(520, which === 'sources' ? current + delta : current - delta));
      style.setProperty(which === 'sources' ? '--w-sources' : '--w-studio', `${width}px`);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
}

// ---------------------------------------------------------------- avvio

async function load() {
  try {
    const payload = await api.state(state.notebookId || '');
    state.notebookId = payload.notebook.id;
    localStorage.setItem('docbook.notebook', state.notebookId);
    state.notebook = payload.notebook;
    state.notebooks = payload.notebooks;
    state.sources = payload.sources;
    state.notes = payload.notes;
    state.messages = (payload.messages || []).map((message) => ({
      role: message.role,
      text: message.text,
      citations: message.citations || [],
      model: message.model,
    }));
    state.models = payload.models;
    state.model = payload.model;
    state.routerError = payload.router_error;
    state.selected = new Set(
      state.sources.filter((source) => source.status === 'ready').map((source) => source.id),
    );
    renderAll();
    if (payload.router_error) toast('Motore non raggiungibile: avvia LLAMA.CPP START.command');
  } catch (error) {
    toast(error.message);
  }
}

async function injectSprite() {
  try {
    const response = await fetch(new URL('./icons.svg', import.meta.url));
    const markup = await response.text();
    const holder = document.createElement('div');
    holder.style.display = 'none';
    holder.innerHTML = markup;
    document.body.prepend(holder);
  } catch {
    /* senza sprite le icone restano vuote, il resto funziona */
  }
}

async function boot() {
  await injectSprite();
  applyTheme(localStorage.getItem('docbook.theme') || 'light');
  showPanel(localStorage.getItem('docbook.panel') || 'chat');
  await load();
}

void boot();
