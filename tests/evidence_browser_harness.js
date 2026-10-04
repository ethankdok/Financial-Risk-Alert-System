// Runs the real inline script of financial-evidence.html against a minimal fake DOM
// and a stubbed fetch. Input (stdin JSON): {"responses": [payload, ...],
// "actions": ["loadMore" | {"tab": type} | {"input": [id, value]}]}. Each fetch
// consumes the next payload. Output: fetched URLs plus each element's innerHTML.
'use strict';

const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'financial-evidence.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const code = scripts[scripts.length - 1][1];

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const responses = [...(input.responses || [])];
const fetches = [];

const makeElement = (id, value = '') => ({
  id, value, hidden: false, innerHTML: '', listeners: {},
  addEventListener(type, handler) { this.listeners[type] = handler; },
  classList: { add() {}, remove() {} },
});
const elements = {};
['ticker', 'source', 'topic', 'startDate', 'endDate', 'sort', 'summary', 'records', 'loadMore', 'textPanel',
  'officialDocumentPanel', 'sourceOptions'].forEach((id) => { elements[id] = makeElement(id); });
elements.ticker.value = '2454';
elements.sort.value = 'newest';
const tabs = ['all', 'investor_conference', 'material_event'].map((type) => ({ ...makeElement(`tab-${type}`), dataset: { type } }));

const document = {
  getElementById: (id) => elements[id],
  querySelectorAll: (selector) => (selector === '.tabs button' ? tabs : []),
};
const fetchStub = async (url) => {
  fetches.push(url);
  const payload = responses.length ? responses.shift() : { success: false, error: 'no stub response' };
  return { ok: payload.success !== false, json: async () => payload };
};
const windowStub = {};

const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

(async () => {
  // eslint-disable-next-line no-new-func
  new Function('document', 'fetch', 'window', code)(document, fetchStub, windowStub);
  await settle();
  for (const action of input.actions || []) {
    if (action === 'loadMore') elements.loadMore.listeners.click();
    else if (action.tab) tabs.find((tab) => tab.dataset.type === action.tab).listeners.click();
    else if (action.input) {
      const [id, value] = action.input;
      elements[id].value = value;
      elements[id].listeners[id === 'ticker' || id === 'sort' ? 'change' : 'input']();
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    await settle();
  }
  const out = { fetches, hidden: {}, html: {} };
  Object.entries(elements).forEach(([id, element]) => {
    out.html[id] = element.innerHTML;
    out.hidden[id] = element.hidden;
  });
  process.stdout.write(JSON.stringify(out));
})();
