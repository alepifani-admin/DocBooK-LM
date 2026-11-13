// Cassetto del visualizzatore: pagina del PDF con la citazione evidenziata,
// testo della fonte, oppure una nota.

import { api } from '../api.js';
import { icon } from '../ui.js';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function createViewer(root, actions) {
  const titleEl = root.querySelector('#viewer-title');
  const navEl = root.querySelector('#viewer-nav');
  const bodyEl = root.querySelector('#viewer-body');
  let current = null;

  function show() {
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('viewer--open'));
  }

  function close() {
    root.classList.remove('viewer--open');
    setTimeout(() => {
      root.hidden = true;
      bodyEl.replaceChildren();
      navEl.replaceChildren();
      current = null;
    }, 180);
  }

  function heading() {
    if (!current) return '';
    if (current.type === 'note') return 'Nota';
    const source = actions.sourceById(current.sourceId);
    return source ? source.title : 'Fonte';
  }

  function setNav(parts) {
    navEl.replaceChildren();
    for (const part of parts) navEl.appendChild(part);
  }

  function navButton(name, title, onClick, disabled = false) {
    const node = el('button', 'icon');
    node.type = 'button';
    node.title = title;
    node.appendChild(icon(name));
    node.disabled = disabled;
    node.addEventListener('click', onClick);
    return node;
  }

  async function openPdf(sourceId, page, quote) {
    const source = actions.sourceById(sourceId);
    const total = source ? source.pages || 1 : 1;
    current = { type: 'pdf', sourceId, page: Math.max(1, page || 1), quote: quote || '' };
    show();
    titleEl.textContent = heading();

    const frame = el('div', 'pdf-page');
    const image = document.createElement('img');

    const render = () => {
      frame.replaceChildren();
      image.src = api.pageUrl(sourceId, current.page, 150);
      frame.appendChild(image);
      setNav([
        navButton('chevron-left', 'Pagina precedente', () => {
          if (current.page > 1) openPdf(sourceId, current.page - 1, '');
        }, current.page <= 1),
        el('span', null, `pagina ${current.page} di ${total}`),
        navButton('chevron-right', 'Pagina successiva', () => {
          if (current.page < total) openPdf(sourceId, current.page + 1, '');
        }, current.page >= total),
      ]);
    };

    image.addEventListener('load', async () => {
      if (!current || current.type !== 'pdf' || !current.quote) return;
      try {
        const found = await api.locate(sourceId, current.quote, current.page);
        for (const box of found.boxes || []) {
          const highlight = el('div', 'hl');
          highlight.style.left = `${box[0] * 100}%`;
          highlight.style.top = `${box[1] * 100}%`;
          highlight.style.width = `${box[2] * 100}%`;
          highlight.style.height = `${box[3] * 100}%`;
          frame.appendChild(highlight);
        }
      } catch {
        /* la pagina resta leggibile anche senza evidenziazione */
      }
    });

    render();
    bodyEl.className = 'viewer__body';
    bodyEl.replaceChildren(frame);
    if (quote) {
      const box = el('div', 'quote-box');
      box.appendChild(el('div', 'quote-box__where', `pagina ${current.page}`));
      box.appendChild(document.createTextNode(quote));
      bodyEl.prepend(box);
    }
  }

  async function openText(sourceId, quote) {
    current = { type: 'text', sourceId, quote: quote || '' };
    show();
    titleEl.textContent = heading();
    setNav([el('span', null, quote ? 'passaggio citato' : 'testo della fonte')]);
    bodyEl.className = 'viewer__body viewer__body--text';
    bodyEl.replaceChildren(el('p', 'empty', 'Caricamento…'));
    try {
      const payload = await api.source(sourceId);
      const text = (payload.passages || []).map((item) => item.text).join('\n\n');
      const wrapper = el('div', 'viewer__text');
      const index = quote ? text.indexOf(quote) : -1;
      if (index >= 0) {
        wrapper.appendChild(document.createTextNode(text.slice(0, index)));
        const mark = el('mark', null, quote);
        wrapper.appendChild(mark);
        wrapper.appendChild(document.createTextNode(text.slice(index + quote.length)));
      } else {
        wrapper.textContent = text || 'Nessun testo disponibile.';
      }
      bodyEl.replaceChildren(wrapper);
    } catch (error) {
      bodyEl.replaceChildren(el('p', 'empty', error.message));
    }
  }

  function openNote(note, options = {}) {
    current = { type: 'note', note };
    show();
    titleEl.textContent = 'Nota';
    bodyEl.className = 'viewer__body viewer__body--text';

    const titleInput = document.createElement('input');
    titleInput.type = 'text';
    titleInput.value = note.title || 'Nota';
    titleInput.className = 'note-editor__title';
    titleInput.setAttribute('aria-label', 'Titolo della nota');

    const area = document.createElement('textarea');
    area.value = note.markdown || '';
    area.className = 'note-editor__body';
    area.setAttribute('aria-label', 'Testo della nota');
    area.placeholder = 'Scrivi qui la nota, in markdown.';

    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'btn btn--small';
    save.textContent = 'Salva';
    save.addEventListener('click', async () => {
      if (options.onSave) await options.onSave(titleInput.value.trim() || 'Nota', area.value);
    });

    setNav([save]);
    const editor = el('div', 'note-editor');
    editor.appendChild(titleInput);
    editor.appendChild(area);
    bodyEl.replaceChildren(editor);
    area.focus();
  }

  root.querySelector('#btn-viewer-close').addEventListener('click', close);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !root.hidden) close();
  });

  return {
    openCitation(citation) {
      if (!citation) return;
      if (citation.page) openPdf(citation.source_id, citation.page, citation.quote || '');
      else openText(citation.source_id, citation.quote || '');
    },
    openSource(source) {
      if (!source) return;
      if (source.kind === 'pdf' && source.pages) openPdf(source.id, 1, '');
      else openText(source.id, '');
    },
    openNote,
    close,
  };
}
