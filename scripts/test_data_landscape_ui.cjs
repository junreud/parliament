/* Synthetic DOM checks. No browser, real dashboard, or external request is used. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('../web/node_modules/jsdom/lib/api.js');
const assets = path.resolve(__dirname, '../worker/src/parliament_worker/graphrag/landscape_ui');

function view() {
  const dom = new JSDOM(fs.readFileSync(path.join(assets, 'index.html'), 'utf8'), { runScripts: 'outside-only' });
  const source = fs.readFileSync(path.join(assets, 'app.js'), 'utf8');
  dom.window.eval(source.slice(0, source.indexOf('$("search-button").addEventListener')));
  return dom;
}

function law() {
  return { id: 'laws', label: '법령 본문·별표', domainIds: ['laws'], availability: 'available', activity: 'running', observedAt: '2026-10-22T00:00:00Z', failureCount: 0, sourceDefectRows: 0, collectionVerified: false, metrics: [{ label: '본문 보관', completed: 3, expected: 10, unit: '건' }], note: '최종 대조 대기' };
}

test('missing collection storage is unknown, not zero or completed', () => {
  const dom = view(); dom.window.renderCollections(null);
  const text = dom.window.document.getElementById('collection-list').textContent;
  assert.match(text, /집계.*확인/);
  assert.doesNotMatch(text, /0건|수집 완료/);
  dom.window.close();
});

test('raw collection count and bounded progress do not inflate graph counts', () => {
  const dom = view(); dom.window.renderCollections({ pipelines: [law()] });
  const list = dom.window.document.getElementById('collection-list');
  assert.match(list.textContent, /3 \/ 10건/);
  assert.match(list.textContent, /실제 실행 확인/);
  assert.match(list.textContent, /최종 대조 대기/);
  const progress = list.querySelector('progress');
  assert.equal(progress.max, 10); assert.equal(progress.value, 3);
  assert.doesNotMatch(list.textContent, /전체 수집 완료|공개 승인/);
  dom.window.close();
});

test('snapshot strings are text and cannot become active markup', () => {
  const dom = view(); const card = law(); card.note = '<img src=x onerror=alert(1)>';
  dom.window.renderCollections({ pipelines: [card] });
  assert.equal(dom.window.document.querySelector('#collection-list img'), null);
  assert.match(dom.window.document.getElementById('collection-list').textContent, /<img/);
  dom.window.close();
});

test('unknown collector snapshots show no fabricated progress fraction', () => {
  const dom = view(); dom.window.renderCollections({ pipelines: [{ ...law(), availability: 'unavailable', metrics: [] }] });
  const list = dom.window.document.getElementById('collection-list');
  assert.match(list.textContent, /집계 미확인/); assert.equal(list.querySelector('progress'), null);
  dom.window.close();
});
