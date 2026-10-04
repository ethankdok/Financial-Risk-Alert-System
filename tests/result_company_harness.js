// Runs the real result-page company selection from script.js (getAnalysisText,
// urlTickerParam, pickSupportedCompany, loadFinancialEvidence) with stubbed
// location / localStorage / fetch. Input (stdin JSON):
//   {"search": "?ticker=2408", "storage": {"analysisResult": "..."}, "companies": [...]}
// Output: the picked company, every fetched URL, and any empty-state message.
'use strict';

const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8');
const slice = (start, end) => {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  if (from < 0 || to < 0) throw new Error(`script.js segment not found: ${start}`);
  return source.slice(from, to);
};

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const fetched = [];
const empties = [];
const rendered = [];
const storage = input.storage || {};

const env = {
  location: { search: input.search || '' },
  localStorage: { getItem: (key) => (key in storage ? storage[key] : null) },
  document: { querySelector: () => null },
  fetch: async (url) => {
    fetched.push(url);
    if (url === '/api/financial/companies') {
      return { ok: true, json: async () => ({ success: true, data: { companies: input.companies || [] } }) };
    }
    const ticker = decodeURIComponent(url.split('/')[4] || '');
    return { ok: true, json: async () => ({ success: true, data: { ticker } }) };
  },
  text: (value, fallback = '尚未提供') => (value === null || value === undefined || value === '' ? fallback : String(value)),
  showEmpty: (message, detail) => empties.push({ message, detail }),
  setState: () => {},
  renderFinancialEvidence: (card) => rendered.push(card.ticker),
  console: { error: () => {} },
};

const code = [
  slice('  const getAnalysisText = () => {', '  const renderSummary = '),
  slice('  const loadFinancialEvidence = async () => {', "  document.querySelectorAll('[data-follow-company]')"),
  'return { pickSupportedCompany, loadFinancialEvidence };',
].join('\n');
// eslint-disable-next-line no-new-func
const api = new Function(...Object.keys(env), code)(...Object.values(env));

(async () => {
  const picked = await api.pickSupportedCompany();
  fetched.length = 0;
  await api.loadFinancialEvidence();
  process.stdout.write(JSON.stringify({ picked, fetched, empties, rendered }));
})();
