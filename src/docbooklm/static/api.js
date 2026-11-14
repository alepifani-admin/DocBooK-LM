// Client dell'API di DocBooK LM.

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get('content-type') || '';
  const body = type.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = (body && (body.error || body.detail)) || `errore ${response.status}`;
    throw new Error(message);
  }
  return body;
}

const json = (payload) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

export const api = {
  state: (notebook) => request(`/api/state?notebook=${encodeURIComponent(notebook)}`),

  notebooks: () => request('/api/notebooks'),
  createNotebook: (name) => request('/api/notebooks', json({ name })),
  renameNotebook: (id, name) =>
    request(`/api/notebooks/${id}`, { ...json({ name }), method: 'PATCH' }),

  sources: (notebook) => request(`/api/sources?notebook=${encodeURIComponent(notebook)}`),
  clearSources: (notebook) =>
    request(`/api/sources?notebook=${encodeURIComponent(notebook)}`, { method: 'DELETE' }),
  deleteSource: (id) => request(`/api/sources/${id}`, { method: 'DELETE' }),
  source: (id) => request(`/api/sources/${id}`),

  upload: (notebook, file) => {
    const form = new FormData();
    form.append('notebook', notebook);
    form.append('file', file);
    return request('/api/sources', { method: 'POST', body: form });
  },
  addUrl: (notebook, url) => request('/api/sources/url', json({ notebook, url })),
  addText: (notebook, title, text) => {
    const form = new FormData();
    form.append('notebook', notebook);
    form.append('title', title);
    form.append('text', text);
    return request('/api/sources/text', { method: 'POST', body: form });
  },

  notes: (notebook) => request(`/api/notes?notebook=${encodeURIComponent(notebook)}`),
  createNote: (notebook, title, markdown) =>
    request('/api/notes', json({ notebook, title, markdown })),
  updateNote: (id, title, markdown) =>
    request(`/api/notes/${id}`, { ...json({ title, markdown }), method: 'PATCH' }),
  deleteNote: (id) => request(`/api/notes/${id}`, { method: 'DELETE' }),

  exportAnswer: (notebook, message) =>
    request('/api/exports/answer', json({ notebook, message })),
  exportNote: (note) => request('/api/exports/note', json({ note })),
  exportUrl: (name) => `/api/exports/${encodeURIComponent(name)}`,

  models: () => request('/api/models'),
  selectModel: (model) => request('/api/models/select', json({ model })),

  pageUrl: (sourceId, page, dpi = 150) =>
    `/api/sources/${sourceId}/page/${page}.png?dpi=${dpi}`,
  locate: (sourceId, quote, page) =>
    request(
      `/api/sources/${sourceId}/locate?quote=${encodeURIComponent(quote)}&page=${page}`,
    ),

  // Streaming della chat: eventi `meta`, `delta`, `done`, `error`.
  async chat(payload, handlers, signal) {
    const response = await fetch('/api/chat', {
      ...json(payload),
      signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || body.detail || `errore ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let event = '';

    const dispatch = (name, data) => {
      if (!data) return;
      let parsed;
      try {
        parsed = JSON.parse(data);
      } catch {
        return;
      }
      if (handlers[name]) handlers[name](parsed);
    };

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('event:')) {
          event = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dispatch(event, line.slice(5).trim());
        }
      }
    }
  },
};
