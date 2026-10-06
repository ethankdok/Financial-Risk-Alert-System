// Renders the Official Evidence conference items from the real script.js with a
// minimal fake DOM, so Python tests can assert on the produced markup without a
// browser. Usage: node tests/frontend_render_harness.js < {"title","items"} JSON.
'use strict';

const fs = require('fs');
const path = require('path');

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = '';
    this.ownText = '';
    this.isFragment = tagName === '#fragment';
  }

  appendChild(child) {
    if (child.isFragment) this.children.push(...child.children);
    else this.children.push(child);
    return child;
  }

  removeChild(child) {
    this.children = this.children.filter((item) => item !== child);
  }

  get firstChild() {
    return this.children[0] || null;
  }

  set textContent(value) {
    this.ownText = String(value);
    this.children = [];
  }

  get textContent() {
    return [this.ownText, ...this.children.map((child) => child.textContent)].filter(Boolean).join(' ');
  }

  get classList() {
    return { add: (name) => { this.className = `${this.className} ${name}`.trim(); } };
  }
}

const escapeHtml = (value) => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const toHtml = (node) => {
  const attributes = [];
  if (node.className) attributes.push(` class="${escapeHtml(node.className)}"`);
  if (node.href) attributes.push(` href="${escapeHtml(node.href)}"`);
  const inner = escapeHtml(node.ownText) + node.children.map(toHtml).join('');
  return `<${node.tagName}${attributes.join('')}>${inner}</${node.tagName}>`;
};

const collectLinks = (node, links = []) => {
  if (node.href) links.push(node.href);
  node.children.forEach((child) => collectLinks(child, links));
  return links;
};

// Text a user sees without opening a 技術與規則細節 / 技術細節 container.
const primaryText = (node) => {
  if (/\bfinancial-technical-details\b/.test(node.className)) return '';
  return [node.ownText, ...node.children.map(primaryText)].filter(Boolean).join(' ');
};
const technicalText = (node) => {
  if (/\bfinancial-technical-details\b/.test(node.className)) return node.textContent;
  return node.children.map(technicalText).filter(Boolean).join(' ');
};

const slice = (source, start, end) => {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  if (from < 0 || to < 0) throw new Error(`script.js segment not found: ${start}`);
  return source.slice(from, to);
};

const source = fs.readFileSync(path.join(__dirname, '..', 'script.js'), 'utf8');
const code = [
  slice(source, '  const text = (value', '  const setState = '),
  slice(source, '  const severityTag = ', '  const showEmpty = '),
  `const nodes = Object.fromEntries(
    ['official', 'summary', 'metrics', 'rules', 'dimensions', 'llm', 'llmState']
      .map((name) => [name, document.createElement('div')]));`,
  slice(source, '  const renderSummary = ', '  const DIGEST_STATUS_LABELS = '),
  slice(source, '  const DIGEST_STATUS_LABELS = ', '  const renderFinancialEvidence = '),
  `return { renderOfficialItems, renderOfficialEvidence, selectFinancialSnapshot, nodes,
    renderSummary, renderRules, renderDimensions, renderLlm };`,
].join('\n');

const document = {
  createElement: (tag) => new FakeNode(tag),
  createDocumentFragment: () => new FakeNode('#fragment'),
};
// eslint-disable-next-line no-new-func
const api = new Function('document', code)(document);

// Modes: "items" (default) renders one group; "evidence" renders the whole
// Official Evidence section from a card; "snapshot" returns the chosen snapshot;
// "financial" renders the summary, rules, eight dimensions and AI narrative.
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const render = (node) => ({
  html: toHtml(node), text: node.textContent, links: collectLinks(node),
  primary_text: primaryText(node), technical_text: technicalText(node),
});
if (input.mode === 'financial') {
  const snapshot = api.selectFinancialSnapshot(input.card);
  const analysis = snapshot.ai_analysis || {};
  api.renderSummary(input.card, snapshot, analysis);
  api.renderRules(snapshot.rule_cards || [], analysis.rule_monitoring || []);
  api.renderDimensions(analysis.dimension_assessments || []);
  api.renderLlm(analysis);
  const sections = ['summary', 'rules', 'dimensions', 'llm'];
  process.stdout.write(JSON.stringify({
    ...Object.fromEntries(sections.map((name) => [name, render(api.nodes[name])])),
    llm_state: api.nodes.llmState.textContent,
  }));
} else if (input.mode === 'snapshot') {
  process.stdout.write(JSON.stringify({ snapshot: api.selectFinancialSnapshot(input.card) }));
} else if (input.mode === 'evidence') {
  api.renderOfficialEvidence(input.card, api.selectFinancialSnapshot(input.card));
  process.stdout.write(JSON.stringify(render(api.nodes.official)));
} else {
  const group = api.renderOfficialItems(input.title || '法說會 Investor Conference Evidence', input.items || [], '目前未取得法說會資料。');
  process.stdout.write(JSON.stringify(render(group)));
}
