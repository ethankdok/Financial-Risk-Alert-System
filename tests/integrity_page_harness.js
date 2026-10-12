// Runs the real financial-integrity.js against a minimal fake DOM and a stubbed fetch, then prints what it built.
// Usage: node tests/integrity_page_harness.js < {"companies": {...}, "preview": {...}, "preview_status": 200,
//                                                "ticker": "2454"}
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const created = [];

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.ownText = '';
    this.className = '';
    this.hidden = false;
    this.disabled = false;
    this.tabIndex = 0;
    this.value = '';
    created.push(this);
  }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children = this.children.filter((c) => c !== child); return child; }
  get firstChild() { return this.children[0] || null; }
  get childNodes() { return this.children; }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get textContent() { return [this.ownText, ...this.children.map((c) => c.textContent)].filter(Boolean).join(' '); }
  set innerHTML(_value) { throw new Error('innerHTML must not be used'); }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'href') this.href = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, event) { (this.listeners[type] || []).forEach((fn) => fn(event || {target: this})); }
}

class TextNode {
  constructor(text) { this.tagName = '#text'; this.ownText = String(text); this.children = []; }
  get textContent() { return this.ownText; }
}

function main(input) {
  const html = fs.readFileSync(path.join(__dirname, '..', 'financial-integrity.html'), 'utf8');
  const byId = {};
  for (const match of html.matchAll(/<(\w+)[^>]*\sid="([^"]+)"[^>]*>/g)) {
    const node = new FakeNode(match[1]);
    node.attributes.id = match[2];
    const view = /data-view="([^"]+)"/.exec(match[0]);
    if (view) node.attributes['data-view'] = view[1];
    byId[match[2]] = node;
  }
  const tabButtons = Object.values(byId).filter((n) => n.tagName === 'button' && n.attributes['data-view']);
  const select = byId.tickerSelect;
  let selectValue = '';
  Object.defineProperty(select, 'value', {get: () => selectValue, set: (v) => {
    const allowed = select.children.map((o) => o.getAttribute('value'));
    selectValue = allowed.includes(String(v)) ? String(v) : '';
  }});
  const documentListeners = {};
  const requests = [];
  const document = {
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (text) => new TextNode(text),
    getElementById: (id) => byId[id] || null,
    querySelectorAll: (selector) => (selector === '.tabs button' ? tabButtons : []),
    addEventListener: (type, fn) => { (documentListeners[type] = documentListeners[type] || []).push(fn); },
  };
  function respond(status, payload) {
    return Promise.resolve({ok: status >= 200 && status < 300, status, json: () => Promise.resolve(payload)});
  }
  function fetch(url, options) {
    requests.push({url, method: (options && options.method) || 'GET', body: options && options.body ? JSON.parse(options.body) : null});
    if (url === '/api/integrity/companies') return respond(200, {success: true, data: input.companies});
    if (url === '/api/integrity/assessments/preview') {
      const status = input.preview_status || 200;
      return respond(status, status === 200 ? {success: true, data: input.preview}
        : {success: false, error: 'FinTrust API returned an error.', detail: input.error_detail || {}, status_code: status});
    }
    return respond(404, {success: false});
  }
  const context = {
    document, fetch, URL, URLSearchParams, Number, String, JSON, Object, Array, Promise, isFinite, console,
    window: {location: {search: input.ticker ? `?ticker=${input.ticker}` : ''}},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'financial-integrity.js'), 'utf8'), context);
  (documentListeners.DOMContentLoaded || []).forEach((fn) => fn());
  setTimeout(() => {
    const text = (id) => (byId[id] ? byId[id].textContent : null);
    const links = created.filter((n) => n.tagName === 'a').map((n) => n.href);
    const tags = [...new Set(created.map((n) => n.tagName))].sort();
    const badges = created.filter((n) => n.tagName === 'span' && /badge/.test(n.className))
      .map((n) => ({className: n.className, text: n.textContent}));
    process.stdout.write(JSON.stringify({
      requests, links, tags, badges,
      summary: text('summaryBody'), overview: text('overviewBody'), models: text('modelsBody'),
      cross: text('crossBody'), b2b: text('b2bBody'), method: text('methodBody'),
      summaryClass: byId.summaryBody.className, runDisabled: byId.runBtn.disabled,
    }));
  }, 50);
}

let raw = '';
process.stdin.on('data', (chunk) => { raw += chunk; });
process.stdin.on('end', () => main(JSON.parse(raw || '{}')));
