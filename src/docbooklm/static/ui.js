// Piccoli aiuti condivisi: icone, menu contestuali, avvisi.

const NS = 'http://www.w3.org/2000/svg';

export const numberFormat = new Intl.NumberFormat('it-IT');

export function icon(name) {
  const svg = document.createElementNS(NS, 'svg');
  const use = document.createElementNS(NS, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.appendChild(use);
  svg.setAttribute('aria-hidden', 'true');
  return svg;
}

export function button(className, name, label) {
  const node = document.createElement('button');
  node.type = 'button';
  node.className = className;
  if (label) {
    node.appendChild(icon(name));
    node.appendChild(document.createTextNode(label));
  } else {
    node.appendChild(icon(name));
    node.title = label || name;
  }
  return node;
}

let openMenu = null;

export function closeMenus() {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
  }
}

export function menu(anchor, items) {
  closeMenus();
  const box = document.createElement('div');
  box.className = 'menu';
  for (const item of items) {
    const entry = document.createElement('button');
    entry.type = 'button';
    entry.appendChild(icon(item.icon));
    entry.appendChild(document.createTextNode(item.label));
    entry.addEventListener('click', (event) => {
      event.stopPropagation();
      closeMenus();
      item.onClick();
    });
    box.appendChild(entry);
  }
  anchor.parentElement.appendChild(box);
  openMenu = box;
  return box;
}

document.addEventListener('click', closeMenus);

export function toast(message) {
  const host = document.getElementById('toasts');
  if (!host) return;
  const node = document.createElement('div');
  node.className = 'toast';
  node.appendChild(icon('alert'));
  node.appendChild(document.createTextNode(message));
  host.appendChild(node);
  setTimeout(() => node.remove(), 4500);
}

/**
 * Conferma dentro l'interfaccia, al posto di `window.confirm`.
 *
 * I dialoghi nativi possono essere soppressi dal browser ("impedisci ulteriori
 * finestre"): `confirm()` allora restituisce `false` senza mostrare niente, e
 * l'azione sembra non funzionare. Questo dialogo non ha quel problema.
 */
export function confirmAction({ title, message = '', confirmLabel = 'Elimina' } = {}) {
  const dialog = document.getElementById('confirm-dialog');
  const ok = document.getElementById('confirm-ok');
  const cancel = document.getElementById('confirm-cancel');
  if (!dialog || !ok || !cancel) return Promise.resolve(false);

  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-text').textContent = message;
  ok.textContent = confirmLabel;

  return new Promise((resolve) => {
    const finish = (value) => {
      ok.removeEventListener('click', accept);
      cancel.removeEventListener('click', refuse);
      dialog.removeEventListener('cancel', escape);
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const accept = () => finish(true);
    const refuse = () => finish(false);
    const escape = (event) => {
      event.preventDefault();
      finish(false);
    };
    ok.addEventListener('click', accept);
    cancel.addEventListener('click', refuse);
    dialog.addEventListener('cancel', escape);
    dialog.showModal();
    cancel.focus();
  });
}

/**
 * Chiede una riga di testo dentro l'interfaccia, al posto di `window.prompt`
 * (sopprimibile dal browser come `confirm`, e allora restituisce `null` senza
 * mostrare nulla). Restituisce `null` se si annulla.
 */
export function promptAction({ title, label = '', value = '', confirmLabel = 'Salva' } = {}) {
  const dialog = document.getElementById('prompt-dialog');
  const input = document.getElementById('prompt-input');
  const ok = document.getElementById('prompt-ok');
  const cancel = document.getElementById('prompt-cancel');
  if (!dialog || !input || !ok || !cancel) return Promise.resolve(null);

  document.getElementById('prompt-title').textContent = title;
  document.getElementById('prompt-label').textContent = label;
  ok.textContent = confirmLabel;
  input.value = value;

  return new Promise((resolve) => {
    const finish = (result) => {
      ok.removeEventListener('click', accept);
      cancel.removeEventListener('click', refuse);
      input.removeEventListener('keydown', onKey);
      dialog.removeEventListener('cancel', escape);
      if (dialog.open) dialog.close();
      resolve(result);
    };
    const accept = () => finish(input.value.trim() || null);
    const refuse = () => finish(null);
    const onKey = (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        accept();
      }
    };
    const escape = (event) => {
      event.preventDefault();
      finish(null);
    };
    ok.addEventListener('click', accept);
    cancel.addEventListener('click', refuse);
    input.addEventListener('keydown', onKey);
    dialog.addEventListener('cancel', escape);
    dialog.showModal();
    input.focus();
    input.select();
  });
}
