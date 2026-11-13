// Pannello Studio: note salvate e artefatti (generazione a partire dalla fase F3).

import { icon, menu } from '../ui.js';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const ARTIFACTS = [
  { title: 'Riassunto', meta: 'sintesi delle fonti', icon: 'list' },
  { title: 'FAQ', meta: 'domande e risposte', icon: 'help' },
  { title: 'Guida di studio', meta: 'concetti e verifiche', icon: 'file-badge' },
  { title: 'Timeline', meta: 'date e avvenimenti', icon: 'clock' },
  { title: 'Briefing', meta: 'documento di sintesi', icon: 'file-text' },
  { title: 'Mappa mentale', meta: 'nodi e relazioni', icon: 'workflow' },
];

function noteRow(note, actions) {
  const row = el('div', 'note');
  const main = el('div', 'note__main');
  main.appendChild(el('div', 'note__title', note.title || 'Nota'));
  main.appendChild(el('div', 'note__excerpt', (note.markdown || '').slice(0, 120)));
  main.addEventListener('click', () => actions.openNote(note));
  row.appendChild(main);

  const more = el('button', 'icon note__menu');
  more.type = 'button';
  more.title = 'Altre azioni';
  more.appendChild(icon('more'));
  more.addEventListener('click', (event) => {
    event.stopPropagation();
    menu(more, [
      { label: 'Apri', icon: 'search', onClick: () => actions.openNote(note) },
      { label: 'Elimina', icon: 'trash', onClick: () => actions.removeNote(note.id) },
    ]);
  });
  row.appendChild(more);
  return row;
}

export function renderStudio(container, state, actions) {
  container.replaceChildren();

  const notesSection = el('section', 'studio-section');
  const notesHead = el('div', 'studio-section__head');
  notesHead.appendChild(el('h3', 'studio-section__title', 'Note'));
  notesSection.appendChild(notesHead);

  if (!state.notes.length) {
    notesSection.appendChild(
      el('p', 'empty', 'Nessuna nota. Salva una risposta dalla chat o creane una con il pulsante in alto.'),
    );
  } else {
    for (const note of state.notes) notesSection.appendChild(noteRow(note, actions));
  }
  container.appendChild(notesSection);

  const artifacts = el('section', 'studio-section');
  const head = el('div', 'studio-section__head');
  head.appendChild(el('h3', 'studio-section__title', 'Artefatti'));
  artifacts.appendChild(head);

  for (const artifact of ARTIFACTS) {
    const card = el('div', 'artifact artifact--soon');
    card.appendChild(icon(artifact.icon));
    const body = el('div', 'artifact__body');
    body.appendChild(el('div', 'artifact__title', artifact.title));
    body.appendChild(el('div', 'artifact__meta', `${artifact.meta} · non ancora generato`));
    card.appendChild(body);
    card.title = 'La generazione arriva con la fase F3';
    artifacts.appendChild(card);
  }
  container.appendChild(artifacts);
}
