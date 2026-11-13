// Pannello delle fonti: elenco, selezione, menu contestuale, trascinamento.

import { icon, menu, numberFormat } from '../ui.js';

const ICONS = {
  pdf: 'file-text',
  docx: 'file-badge',
  image: 'image',
  text: 'file',
  web: 'globe',
  archive: 'layers',
  pending: 'file',
};

const LABELS = {
  pdf: 'PDF',
  docx: 'Word',
  image: 'immagine',
  text: 'testo',
  web: 'sito',
  archive: 'archivio',
  pending: 'file',
};

function meta(source) {
  const parts = [LABELS[source.kind] || 'file'];
  if (source.pages) parts.push(source.pages === 1 ? '1 pagina' : `${source.pages} pagine`);
  if (source.n_tokens) parts.push(`${numberFormat.format(source.n_tokens)} token`);
  return parts.join(' · ');
}

function embeddingNote(source) {
  // L'upload non aspetta la GPU: finché i vettori non sono tutti pronti il
  // passaggio e' cercabile solo per parole esatte.
  if (source.status !== 'ready' || !source.n_chunks) return '';
  if (source.embedded >= source.n_chunks) return '';
  return `ricerca semantica ${source.embedded}/${source.n_chunks}`;
}

function card(source, state, actions) {
  const wrap = document.createElement('article');
  wrap.className = 'source' + (state.selected.has(source.id) ? ' source--active' : '');
  if (source.status === 'processing') wrap.classList.add('source--processing');

  const check = document.createElement('label');
  check.className = 'check source__check';
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = state.selected.has(source.id);
  input.disabled = source.status !== 'ready';
  input.addEventListener('change', () => actions.toggleSource(source.id));
  check.appendChild(input);
  wrap.appendChild(check);

  const kindIcon = document.createElement('span');
  kindIcon.className = 'source__icon';
  kindIcon.appendChild(icon(ICONS[source.kind] || ICONS.pending));
  wrap.appendChild(kindIcon);

  const main = document.createElement('div');
  main.className = 'source__main';
  main.addEventListener('click', () => actions.openSource(source.id));

  const title = document.createElement('div');
  title.className = 'source__title';
  title.textContent = source.title || source.origin || 'Fonte';
  main.appendChild(title);

  if (source.status === 'processing') {
    const skeleton = document.createElement('div');
    skeleton.className = 'source__meta';
    const bar = document.createElement('div');
    bar.className = 'skeleton';
    bar.style.width = '120px';
    skeleton.appendChild(bar);
    main.appendChild(skeleton);
  } else if (source.status === 'error') {
    const error = document.createElement('div');
    error.className = 'source__meta source__meta--error';
    error.textContent = source.error || 'estrazione non riuscita';
    main.appendChild(error);
  } else {
    const info = document.createElement('div');
    info.className = 'source__meta';
    info.textContent = meta(source);
    const note = embeddingNote(source);
    if (note) {
      const progress = document.createElement('span');
      progress.className = 'source__indexing';
      progress.textContent = ` · ${note}`;
      info.appendChild(progress);
    }
    main.appendChild(info);
  }
  wrap.appendChild(main);

  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'icon source__menu';
  more.title = 'Altre azioni';
  more.appendChild(icon('more'));
  more.addEventListener('click', (event) => {
    event.stopPropagation();
    menu(more, [
      { label: 'Apri', icon: 'search', onClick: () => actions.openSource(source.id) },
      { label: 'Elimina', icon: 'trash', onClick: () => actions.removeSource(source.id) },
    ]);
  });
  // durante il caricamento la scheda e' un segnaposto: non c'e' nulla da aprire
  // ne' da eliminare sul server
  if (!String(source.id).startsWith('pending-')) wrap.appendChild(more);

  return wrap;
}

export function renderSources(container, state, actions) {
  container.replaceChildren();

  if (!state.sources.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'Nessuna fonte. Aggiungi un PDF, un documento Word, un link o incolla del testo: le risposte useranno solo ciò che carichi.';
    container.appendChild(empty);
    return;
  }

  for (const source of state.sources) {
    container.appendChild(card(source, state, actions));
  }
}

export function totalTokens(state) {
  let total = 0;
  for (const source of state.sources) {
    if (state.selected.has(source.id)) total += source.n_tokens || 0;
  }
  return total;
}
