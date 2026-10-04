// Runs the real inline script of financial-evidence.html against a minimal fake DOM
// and a stubbed fetch. Input (stdin JSON):
//   {"responses": [payload | {"defer": name, "payload": payload}, ...],
//    "companies": payload | "fail", "companiesDefer": bool, "search": "?ticker=...",
//    "actions": [...]}
// Each browser fetch consumes the next response; a deferred one stays pending until
// a {"resolve": name} action (aborted requests reject like a real AbortSignal).
// Actions: "loadMore" | {"tab": type} | {"input": [id, value]} (then waits out the
// debounce) | {"typeNoWait": [id, value]} | {"resolve": name} | {"wait": ms}.
// Output: fetched URLs, aborted URLs, each element's innerHTML / hidden state.
'use strict';

const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'financial-evidence.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const code = scripts[scripts.length - 1][1];

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const responses = [...(input.responses || [])];
const fetches = [];
const aborted = [];
const companyFetches = [];
const pending = {};
// The company list request is answered separately so browser payloads keep their order.
const companiesPayload = input.companies || {success: true, data: {companies: [
  {ticker: '2330', name: '台積電'}, {ticker: '2454', name: '聯發科'}]}};

const makeElement = (id, value = '') => ({
  id, value, hidden: false, disabled: false, innerHTML: '', listeners: {},
  addEventListener(type, handler) { this.listeners[type] = handler; },
  classList: { add() {}, remove() {} },
});
const elements = {};
['ticker', 'source', 'topic', 'startDate', 'endDate', 'sort', 'summary', 'records', 'loadMore', 'textPanel',
  'officialDocumentPanel', 'sourceOptions'].forEach((id) => { elements[id] = makeElement(id); });
elements.ticker.value = '';  // the real select starts on its empty placeholder option
elements.sort.value = 'newest';
const tabs = ['all', 'investor_conference', 'material_event'].map((type) => ({ ...makeElement(`tab-${type}`), dataset: { type } }));

const document = {
  getElementById: (id) => elements[id],
  querySelectorAll: (selector) => (selector === '.tabs button' ? tabs : []),
};

const deferred = (name, value, signal, url) => new Promise((resolve, reject) => {
  pending[name] = () => resolve(value);
  if (signal) {
    signal.addEventListener('abort', () => {
      aborted.push(url);
      const error = new Error('aborted');
      error.name = 'AbortError';
      reject(error);
    });
  }
});

const fetchStub = async (url, options = {}) => {
  if (url.startsWith('/api/financial/companies')) {
    companyFetches.push(url);
    if (companiesPayload === 'fail') throw new Error('network down');
    const response = { ok: true, json: async () => companiesPayload };
    return input.companiesDefer ? deferred('companies', response, null, url) : response;
  }
  fetches.push(url);
  const spec = responses.length ? responses.shift() : { success: false, error: 'no stub response' };
  const payload = spec && spec.defer ? spec.payload : spec;
  const response = { ok: payload.success !== false, json: async () => payload };
  return spec && spec.defer ? deferred(spec.defer, response, options.signal, url) : response;
};
const windowStub = {};

const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
const fire = (id, value) => {
  elements[id].value = value;
  elements[id].listeners[id === 'ticker' || id === 'sort' ? 'change' : 'input']();
};

(async () => {
  const locationStub = { search: input.search || '' };
  // eslint-disable-next-line no-new-func
  new Function('document', 'fetch', 'window', 'location', code)(document, fetchStub, windowStub, locationStub);
  await settle();
  for (const action of input.actions || []) {
    if (action === 'loadMore') elements.loadMore.listeners.click();
    else if (action.tab) tabs.find((tab) => tab.dataset.type === action.tab).listeners.click();
    else if (action.input) {
      fire(...action.input);
      await new Promise((resolve) => setTimeout(resolve, 300));
    } else if (action.typeNoWait) fire(...action.typeNoWait);
    else if (action.resolve) {
      if (!pending[action.resolve]) throw new Error(`nothing pending for ${action.resolve}`);
      pending[action.resolve]();
    } else if (action.wait) await new Promise((resolve) => setTimeout(resolve, action.wait));
    await settle();
  }
  await settle();
  const out = { fetches, aborted, companyFetches, hidden: {}, html: {}, disabled: {},
    values: { ticker: elements.ticker.value } };
  Object.entries(elements).forEach(([id, element]) => {
    out.html[id] = element.innerHTML;
    out.hidden[id] = element.hidden;
    out.disabled[id] = element.disabled;
  });
  process.stdout.write(JSON.stringify(out));
})();
