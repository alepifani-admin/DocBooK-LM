// Pannello della chat: benvenuto, turni, streaming, citazioni.

import { decorateCitations, renderMarkdown } from '../md.js';
import { icon } from '../ui.js';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function scrollToEnd(log) {
  log.scrollTop = log.scrollHeight;
}

function suggestions(state, actions) {
  const ready = state.sources.filter((source) => source.status === 'ready');
  const items = [];
  if (ready.length) {
    items.push(`Riassumi le fonti selezionate in dieci righe.`);
    items.push(`Quali sono i punti principali di «${ready[0].title}»?`);
    if (ready[1]) items.push(`Confronta «${ready[0].title}» e «${ready[1].title}».`);
    items.push('Elenca le date e i numeri citati nelle fonti.');
  } else {
    items.push('Aggiungi una fonte per iniziare.');
  }
  const wrap = el('div', 'suggestions');
  for (const text of items.slice(0, 4)) {
    const node = el('button', 'suggestion', text);
    node.type = 'button';
    if (!ready.length) node.disabled = true;
    node.addEventListener('click', () => actions.ask(text));
    wrap.appendChild(node);
  }
  return wrap;
}

function welcome(state, actions) {
  const wrap = el('div', 'welcome');
  wrap.appendChild(el('h1', null, state.notebook ? state.notebook.name : 'Il mio quaderno'));
  wrap.appendChild(
    el('p', null, 'Fai una domanda: la risposta arriva solo dalle fonti che selezioni, con la citazione della pagina.'),
  );
  wrap.appendChild(suggestions(state, actions));
  return wrap;
}

function citationChips(citations, actions) {
  const wrap = el('div', 'answer__sources');
  const seen = new Set();
  for (const citation of citations) {
    const key = `${citation.source_id}:${citation.page}:${citation.quote}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const chip = el('button', 'source-chip');
    chip.type = 'button';
    chip.title = citation.quote || '';
    chip.appendChild(icon('quote'));
    const label = citation.page
      ? `${citation.source_title} · p. ${citation.page}`
      : citation.source_title;
    chip.appendChild(el('span', null, label));
    chip.addEventListener('click', () => actions.openCitation(citation));
    wrap.appendChild(chip);
  }
  return wrap;
}

function actionsBar(message, actions) {
  const bar = el('div', 'answer__actions');

  const copy = el('button', 'icon');
  copy.type = 'button';
  copy.title = 'Copia la risposta';
  copy.appendChild(icon('copy'));
  copy.addEventListener('click', () => actions.copy(message.text));
  bar.appendChild(copy);

  const save = el('button', 'icon');
  save.type = 'button';
  save.title = 'Salva in una nota';
  save.appendChild(icon('bookmark'));
  save.addEventListener('click', () => actions.saveNote(message));
  bar.appendChild(save);

  const pdf = el('button', 'icon');
  pdf.type = 'button';
  pdf.title = 'Esporta in PDF';
  pdf.appendChild(icon('download'));
  pdf.addEventListener('click', () => actions.exportAnswer(message));
  bar.appendChild(pdf);

  const again = el('button', 'icon');
  again.type = 'button';
  again.title = 'Rigenera';
  again.appendChild(icon('refresh'));
  again.addEventListener('click', () => actions.regenerate(message));
  bar.appendChild(again);

  return bar;
}

export function renderChat(log, state, actions) {
  log.replaceChildren();
  if (!state.messages.length) {
    log.appendChild(welcome(state, actions));
    return;
  }
  for (const message of state.messages) {
    if (message.role === 'user') {
      log.appendChild(userTurn(message.text));
      continue;
    }
    log.appendChild(answerTurn(message, actions));
  }
  scrollToEnd(log);
}

export function userTurn(text) {
  const turn = el('div', 'turn turn--user');
  turn.appendChild(el('div', 'bubble', text));
  return turn;
}

function answerTurn(message, actions) {
  const turn = el('div', 'turn');
  const answer = el('div', 'answer');
  const rendered = renderMarkdown(message.text || '');
  while (rendered.firstChild) answer.appendChild(rendered.firstChild);
  decorateCitations(answer, message.citations || []);
  turn.appendChild(answer);

  const citations = message.citations || [];
  if (citations.length) turn.appendChild(citationChips(citations, actions));
  else if (message.role === 'assistant')
    turn.appendChild(
      (() => {
        const warning = el('div', 'warning');
        warning.appendChild(icon('alert'));
        warning.appendChild(el('span', null, 'Nessuna citazione verificata in questa risposta.'));
        return warning;
      })(),
    );

  turn.appendChild(actionsBar(message, actions));
  return turn;
}

// Turno in corso: testo semplice durante lo streaming, markdown alla fine.
export function beginAnswer(log) {
  const turn = el('div', 'turn');
  const answer = el('div', 'answer');
  answer.textContent = '';
  turn.appendChild(answer);
  log.appendChild(turn);
  scrollToEnd(log);
  return { turn, answer };
}

export function appendDelta(answer, text) {
  clearReasoning(answer);
  answer.textContent += text;
  const log = answer.closest('.chat');
  if (log) scrollToEnd(log);
}

// gpt-oss e simili pensano per minuti prima della prima parola: senza questa
// riga la chat sembra bloccata e si finisce per interrompere una risposta viva
export function showReasoning(turn, chars) {
  let hint = turn.turn.querySelector('.answer__hint');
  if (!hint) {
    hint = el('div', 'muted answer__hint');
    turn.turn.appendChild(hint);
  }
  const count = Number(chars) || 0;
  hint.textContent = count
    ? `sto ragionando… ${count.toLocaleString('it-IT')} caratteri`
    : 'sto ragionando…';
}

function clearReasoning(answer) {
  const hint = answer.closest('.turn')?.querySelector('.answer__hint');
  if (hint) hint.remove();
}

export function finishAnswer(answerElement, message, actions) {
  const { turn, answer } = answerElement;
  clearReasoning(answer);
  answer.replaceChildren();
  const rendered = renderMarkdown(message.text || '');
  while (rendered.firstChild) answer.appendChild(rendered.firstChild);
  decorateCitations(answer, message.citations || []);

  const citations = message.citations || [];
  if (citations.length) turn.appendChild(citationChips(citations, actions));
  else {
    const warning = el('div', 'warning');
    warning.appendChild(icon('alert'));
    warning.appendChild(el('span', null, 'Nessuna citazione verificata in questa risposta.'));
    turn.appendChild(warning);
  }
  turn.appendChild(actionsBar(message, actions));
  const log = answer.closest('.chat');
  if (log) scrollToEnd(log);
}

export function errorTurn(log, message) {
  const turn = el('div', 'turn');
  const warning = el('div', 'warning');
  warning.appendChild(icon('alert'));
  warning.appendChild(el('span', null, message));
  turn.appendChild(warning);
  log.appendChild(turn);
  scrollToEnd(log);
}
