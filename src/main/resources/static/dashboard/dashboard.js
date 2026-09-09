(() => {
  'use strict';

  const STATUS = {
    SCHEDULED: ['예정', '#7294e8'], RUNNING: ['실행 중', '#3f6ed8'],
    SUCCESS_CHANGED: ['성공 · 변경', '#1d7650'], SUCCESS_UNCHANGED: ['성공 · 변경 없음', '#8aa396'],
    SUCCESS_EMPTY: ['정상 · 내용 없음', '#8b6bc5'], SKIPPED_NO_PARENT_CHANGES: ['정상 · 선행 변경 없음', '#b0bcb5'],
    PARTIAL: ['부분 완료', '#d6813e'], FAILED: ['실패', '#ba3f3f'],
    RETRY_EXHAUSTED: ['재시도 최종 실패', '#811f32'], MISSED: ['미실행', '#df7770'],
    AUTOMATION_DISABLED: ['자동화 꺼짐', '#b78b45']
  };
  const EXPECTATION = {
    STANDARD: '일반', PARAMETERIZED_STATIC: '고정 파라미터', DEPENDENCY_DRIVEN: '선행 변경 의존',
    EMPTY_ALLOWED: '빈 결과 허용', RETRYABLE: '재시도 대상'
  };
  const $ = id => document.getElementById(id);
  const state = { key: '', snapshot: null };

  $('auth-form').addEventListener('submit', event => {
    event.preventDefault();
    state.key = $('admin-key').value;
    load();
  });
  $('refresh').addEventListener('click', load);
  $('selected-date').addEventListener('change', load);
  $('days').addEventListener('change', load);
  $('status-filter').addEventListener('change', renderTable);
  $('expectation-filter').addEventListener('change', renderTable);
  $('search').addEventListener('input', renderTable);

  async function load() {
    if (!state.key) return;
    setBusy(true);
    const date = $('selected-date').value;
    const params = new URLSearchParams({ days: $('days').value });
    if (date) params.set('date', date);
    try {
      const response = await fetch(`/api/v1/parliament-ingestion-dashboard?${params}`, {
        headers: { 'X-Parliament-Ingestion-Key': state.key }, cache: 'no-store'
      });
      if (!response.ok) throw new Error(response.status === 403 ? '관리 키가 올바르지 않습니다.' : `조회 실패 (${response.status})`);
      state.snapshot = await response.json();
      $('auth-panel').hidden = true;
      $('dashboard').hidden = false;
      $('auth-error').textContent = '';
      if (!$('selected-date').value && state.snapshot.days.length) {
        $('selected-date').value = state.snapshot.days[state.snapshot.days.length - 1].date;
      }
      render();
    } catch (error) {
      $('auth-error').textContent = error.message;
      if (!$('dashboard').hidden) $('freshness').textContent = `마지막 갱신 유지 · ${error.message}`;
    } finally {
      setBusy(false);
    }
  }

  function render() {
    const data = state.snapshot;
    const generated = formatDateTime(data.generatedAt);
    $('freshness').textContent = `마지막 조회 ${generated} · ${data.timezone} · 60초마다 자동 갱신`;
    $('auto-state').className = `pill ${data.automaticEnabled ? 's-SUCCESS_CHANGED' : 's-AUTOMATION_DISABLED'}`;
    $('auto-state').textContent = data.automaticEnabled
      ? `자동 적재 켜짐 · 다음 ${formatDateTime(data.nextScheduledAt)}` : '자동 적재 꺼짐';
    const selected = $('selected-date').value || data.days[data.days.length - 1]?.date;
    $('today-title').textContent = `${shortDate(selected)} 예정 및 결과`;
    $('selected-summary').textContent = `총 ${data.overview.expected.toLocaleString('ko-KR')}개 API`;
    renderMetrics(data.overview);
    renderLegend();
    renderTrend(data.days);
    fillFilters(data.sources);
    renderTable();
  }

  function renderMetrics(o) {
    const success = o.successChanged + o.successUnchanged + o.successEmpty + o.skippedNoParentChanges;
    const attention = o.partial + o.failed + o.retryExhausted + o.missed;
    const cards = [
      ['오늘 예정', o.expected, '전체 수집 대상', 'pending'],
      ['정상 완료', success, `변경 ${o.successChanged} · 변경 없음 ${o.successUnchanged}`, 'good'],
      ['정상 내용 없음', o.successEmpty, '빈 응답이 허용된 완료', 'good'],
      ['선행 변경 없음', o.skippedNoParentChanges, '하위 API 호출 생략', 'good'],
      ['실행 중 / 대기', o.running + o.scheduled, `실행 중 ${o.running} · 예정 ${o.scheduled}`, 'pending'],
      ['확인 필요', attention, `실패 ${o.failed} · 재시도 실패 ${o.retryExhausted} · 미실행 ${o.missed}`, 'attention']
    ];
    $('metrics').replaceChildren(...cards.map(([label, value, note, tone]) => {
      const card = el('article', `metric ${tone}`);
      card.append(el('span', '', label), el('strong', '', Number(value).toLocaleString('ko-KR')), el('span', '', note));
      return card;
    }));
  }

  function renderLegend() {
    const keys = ['SUCCESS_CHANGED', 'SUCCESS_UNCHANGED', 'SUCCESS_EMPTY', 'SCHEDULED', 'FAILED', 'RETRY_EXHAUSTED', 'MISSED'];
    $('legend').replaceChildren(...keys.map(key => {
      const item = el('span', '', STATUS[key][0]);
      item.style.setProperty('--swatch', STATUS[key][1]);
      return item;
    }));
  }

  function renderTrend(days) {
    const keys = ['successChanged', 'successUnchanged', 'successEmpty', 'skippedNoParentChanges', 'running', 'scheduled', 'partial', 'failed', 'retryExhausted', 'missed', 'automationDisabled'];
    const statusFor = { successChanged: 'SUCCESS_CHANGED', successUnchanged: 'SUCCESS_UNCHANGED', successEmpty: 'SUCCESS_EMPTY', skippedNoParentChanges: 'SKIPPED_NO_PARENT_CHANGES', running: 'RUNNING', scheduled: 'SCHEDULED', partial: 'PARTIAL', failed: 'FAILED', retryExhausted: 'RETRY_EXHAUSTED', missed: 'MISSED', automationDisabled: 'AUTOMATION_DISABLED' };
    $('trend').replaceChildren(...days.slice().reverse().map(day => {
      const row = el('div', 'trend-row');
      const dateButton = el('button', '', shortDate(day.date));
      dateButton.type = 'button';
      dateButton.addEventListener('click', () => { $('selected-date').value = day.date; load(); });
      const bar = el('div', 'bar');
      keys.forEach(key => {
        const value = day.counts[key] || 0;
        if (!value) return;
        const status = statusFor[key];
        const segment = el('span', 'segment');
        segment.style.width = `${(value / Math.max(day.counts.expected, 1)) * 100}%`;
        segment.style.background = STATUS[status][1];
        segment.title = `${STATUS[status][0]} ${value}`;
        bar.append(segment);
      });
      row.append(dateButton, bar, el('span', 'number', day.counts.expected));
      return row;
    }));
  }

  function fillFilters(sources) {
    if ($('status-filter').options.length === 1) {
      Object.entries(STATUS).forEach(([value, [label]]) => $('status-filter').append(new Option(label, value)));
    }
    if ($('expectation-filter').options.length === 1) {
      [...new Set(sources.map(item => item.expectation))].sort().forEach(value =>
        $('expectation-filter').append(new Option(EXPECTATION[value] || value, value)));
    }
  }

  function renderTable() {
    if (!state.snapshot) return;
    const status = $('status-filter').value;
    const expectation = $('expectation-filter').value;
    const query = $('search').value.trim().toLocaleLowerCase('ko-KR');
    const rows = state.snapshot.sources.filter(item =>
      (!status || item.outcome === status) && (!expectation || item.expectation === expectation) &&
      (!query || `${item.sourceName} ${item.sourceKey} ${item.apiCode}`.toLocaleLowerCase('ko-KR').includes(query)));
    $('visible-count').textContent = `${rows.length.toLocaleString('ko-KR')}개 표시`;
    $('source-rows').replaceChildren(...rows.map(sourceRow));
  }

  function sourceRow(item) {
    const row = document.createElement('tr');
    const name = el('td', 'api-name', item.sourceName);
    name.append(el('span', 'api-key', `${item.sourceKey} · ${item.apiCode}${item.runId ? ` · 실행 #${item.runId}` : ''}`));
    const status = el('span', `status s-${item.outcome}`, STATUS[item.outcome]?.[0] || item.outcome);
    row.append(name, el('td', '', EXPECTATION[item.expectation] || item.expectation), wrap(status),
      numberCell(item.scanned), numberCell(item.changed), numberCell(item.unchanged), numberCell(item.pages),
      el('td', '', formatDateTime(item.startedAt)), el('td', '', duration(item.startedAt, item.finishedAt)));
    const message = el('td');
    message.append(el('span', 'message', [item.errorCode, item.message].filter(Boolean).join(' · ') || '—'));
    row.append(message);
    return row;
  }

  function setBusy(busy) { $('refresh').disabled = busy || !state.key; $('refresh').textContent = busy ? '조회 중…' : '새로고침'; }
  function el(tag, className = '', text = '') { const node = document.createElement(tag); node.className = className; node.textContent = text; return node; }
  function wrap(node) { const cell = document.createElement('td'); cell.append(node); return cell; }
  function numberCell(value) { return el('td', 'number', Number(value || 0).toLocaleString('ko-KR')); }
  function shortDate(value) { if (!value) return '—'; return new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(new Date(`${value}T00:00:00`)); }
  function formatDateTime(value) { if (!value) return '—'; return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)); }
  function duration(start, end) { if (!start || !end) return '—'; const seconds = Math.max(0, (new Date(end) - new Date(start)) / 1000); return seconds < 60 ? `${seconds.toFixed(1)}초` : `${Math.floor(seconds / 60)}분 ${Math.round(seconds % 60)}초`; }

  setInterval(() => { if (state.key && !document.hidden) load(); }, 60000);
})();
