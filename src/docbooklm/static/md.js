// Markdown minimale -> DOM, senza innerHTML: il testo del modello non diventa mai HTML.
// Le citazioni [n] vengono trasformate in pulsanti cliccabili dopo il rendering.

const CITE = /\[(\d{1,3})\]/g;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function inline(text, parent) {
  // Tokenizza **grassetto**, *corsivo*, `codice`, [testo](url).
  const pattern = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
    const token = match[0];
    if (token.startsWith('**')) {
      const strong = el('strong');
      strong.textContent = token.slice(2, -2);
      parent.appendChild(strong);
    } else if (token.startsWith('`')) {
      parent.appendChild(el('code', null, token.slice(1, -1)));
    } else if (token.startsWith('[')) {
      const label = token.slice(1, token.indexOf(']'));
      const href = token.slice(token.indexOf('](') + 2, -1);
      const link = el('a', null, label);
      link.href = href;
      link.target = '_blank';
      link.rel = 'noreferrer';
      parent.appendChild(link);
    } else {
      const em = el('em');
      em.textContent = token.slice(1, -1);
      parent.appendChild(em);
    }
    last = match.index + token.length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  return parent;
}

function paragraph(lines) {
  const node = el('p');
  inline(lines.join(' '), node);
  return node;
}

function tableBlock(rows) {
  const table = el('table');
  rows.forEach((row, index) => {
    const tr = el('tr');
    row.forEach((cell) => {
      const td = el(index === 0 ? 'th' : 'td');
      inline(cell, td);
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  return table;
}

export function renderMarkdown(text) {
  const root = el('div', 'answer');
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.trim().startsWith('```')) {
      const code = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1;
      const pre = el('pre');
      pre.appendChild(el('code', null, code.join('\n')));
      root.appendChild(pre);
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 4);
      const node = el(`h${level}`);
      inline(heading[2], node);
      root.appendChild(node);
      index += 1;
      continue;
    }

    if (/^\s*([-*])\s+/.test(line)) {
      const list = el('ul');
      while (index < lines.length && /^\s*([-*])\s+/.test(lines[index])) {
        const item = el('li');
        inline(lines[index].replace(/^\s*([-*])\s+/, ''), item);
        list.appendChild(item);
        index += 1;
      }
      root.appendChild(list);
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const list = el('ol');
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        const item = el('li');
        inline(lines[index].replace(/^\s*\d+[.)]\s+/, ''), item);
        list.appendChild(item);
        index += 1;
      }
      root.appendChild(list);
      continue;
    }

    if (line.trim().startsWith('>')) {
      const quote = el('blockquote');
      const parts = [];
      while (index < lines.length && lines[index].trim().startsWith('>')) {
        parts.push(lines[index].trim().replace(/^>\s?/, ''));
        index += 1;
      }
      inline(parts.join(' '), quote);
      root.appendChild(quote);
      continue;
    }

    if (line.includes('|') && lines[index + 1] && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[index + 1])) {
      const rows = [];
      const split = (row) =>
        row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
      rows.push(split(line));
      index += 2;
      while (index < lines.length && lines[index].includes('|')) {
        rows.push(split(lines[index]));
        index += 1;
      }
      root.appendChild(tableBlock(rows));
      continue;
    }

    const buffer = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+[.)]\s|>)/.test(lines[index])
    ) {
      buffer.push(lines[index]);
      index += 1;
    }
    root.appendChild(paragraph(buffer));
  }

  return root;
}

// Sostituisce [n] con pulsanti; restituisce il numero di citazioni agganciate.
export function decorateCitations(root, citations) {
  const valid = new Set((citations || []).map((item) => String(item.n)));
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const targets = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement && node.parentElement.classList.contains('cite')) continue;
    if (/\[\d{1,3}\]/.test(node.nodeValue)) targets.push(node);
  }

  let total = 0;
  for (const node of targets) {
    const text = node.nodeValue;
    const fragment = document.createDocumentFragment();
    let last = 0;
    let match;
    CITE.lastIndex = 0;
    while ((match = CITE.exec(text)) !== null) {
      if (match.index > last) fragment.appendChild(document.createTextNode(text.slice(last, match.index)));
      const number = match[1];
      const button = el('button', 'cite', number);
      button.type = 'button';
      button.dataset.cite = number;
      if (!valid.has(number)) button.disabled = true;
      else total += 1;
      fragment.appendChild(button);
      last = match.index + match[0].length;
    }
    if (last < text.length) fragment.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(fragment, node);
  }
  return total;
}
