// Renders research API payloads with the real historical-research.js render functions (no DOM needed).
// stdin: {"overview": data, "bridge": data, "timeline": data, "signals": data, "discrepancy": data, "text": data,
//         "detail": feature}; stdout: {"<view>": "<html>"}.
'use strict';

const fs = require('fs');
const path = require('path');

const research = require(path.join(__dirname, '..', '..', 'historical-research.js'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const renderers = {
  overview: research.renderOverview, bridge: research.renderBridge, timeline: research.renderTimeline,
  signals: research.renderSignals, discrepancy: research.renderDiscrepancies, text: research.renderTextReadiness,
  detail: research.renderFeatureDetail,
};
const output = {};
for (const [view, payload] of Object.entries(input)) output[view] = renderers[view](payload);
process.stdout.write(JSON.stringify(output));
