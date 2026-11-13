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
