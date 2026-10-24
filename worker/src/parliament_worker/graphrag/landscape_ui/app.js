const state = { overview: null, domain: "all", query: "", page: 1, total: 0, scope: null, offset: 0 };
const $ = (id) => document.getElementById(id);
const format = (number) => new Intl.NumberFormat("ko-KR").format(Number(number || 0));
const dateTime = (value) => value ? new Date(value).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "확인 시각 없음";
const nodeNames = { person: "인물", organization: "기관", bill: "법안", policy: "정책", activity: "활동" };
const edgeNames = { holds_office: "직위 관계", lead_sponsor: "대표발의", co_sponsor: "공동발의", incorporated_into_alternative: "대안 반영", concerns: "정책 관련", scheduled_participant: "예정 참여", implementing_agency: "담당 기관", publisher: "발표 기관" };
const decisionNames = { pending: "검수 대기", approved: "승인", rejected: "기각", unknown: "미확인" };
const licenseNames = { unknown: "이용 조건 미확인", allowed: "이용 허용", restricted: "이용 제한" };
const bodyNames = { available: "원문 확보", partial: "일부 확보", unavailable: "원문 미확보", failed: "수집 실패", unknown: "미확인" };
const blockNames = { human_role_review: "인물·역할 검수", identity_review: "신원 검수", source_use_review: "출처 이용 검수", relation_grounding_review: "관계 근거 검수" };

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = String(content);
  return node;
}

function clear(node) { node.replaceChildren(); return node; }

function appendText(parent, tag, className, content) {
  const child = element(tag, className, content);
  parent.append(child);
  return child;
}

async function get(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(response.status === 503 ? "저장소를 읽을 수 없습니다." : "데이터를 불러오지 못했습니다.");
  return response.json();
}

function showError(message) {
  const panel = $("error");
  panel.textContent = message;
  panel.hidden = !message;
}

function metric(label, value, note, style) {
  const card = element("div", `metric ${style || ""}`);
  appendText(card, "span", "metric-label", label);
  appendText(card, "strong", "metric-value", typeof value === "string" ? value : format(value));
  appendText(card, "span", "metric-note", note);
  return card;
}

function renderMetrics(data) {
  const total = data.totals;
  const target = clear($("metrics"));
  target.append(
    metric("활성 원천 기록", total.sources, "현재 GraphRAG 입력", "metric-ink"),
    metric("원문 그래프", `${format(total.indexedSourceUnits)} / ${format(total.sourceUnits)}`, `미생성 ${format(total.missingSourceGraphs)}구간`, "metric-blue"),
    metric("고유 관계 후보", total.relations, "자동 추출 · 검수 상태 별도", "metric-teal"),
    metric("커뮤니티 보고서", total.reports, "계층 전체 · 비공개", "metric-purple")
  );
}

function collectionMetricText(item) {
  return item.expected === null
    ? `${format(item.completed)}${item.unit} · 전체 대상 집계 중`
    : `${format(item.completed)} / ${format(item.expected)}${item.unit}`;
}

function rawDomainNotes(data, domain) {
  return (data.collection?.pipelines || [])
    .filter((item) => item.domainIds?.includes(domain))
    .map((item) => item.availability === "available"
      ? `${item.label}: ${item.metrics[0].label} ${collectionMetricText(item.metrics[0])}`
      : `${item.label}: 집계 미확인`);
}

function renderCollections(data) {
  const target = clear($("collection-list"));
  if (!data?.pipelines?.length) {
    appendText(target, "p", "muted", "별도 원문 수집 집계를 확인할 수 없습니다. 아래 GraphRAG 입력 수치와 합산하지 않았습니다.");
    return;
  }
  const activities = { running: "실제 실행 확인", stopped: "실행 중인 수집기 없음", unknown: "실행 상태 미확인" };
  data.pipelines.forEach((item) => {
    const card = element("article", "collection-card");
    const heading = element("div", "collection-heading");
    const title = appendText(heading, "h3", "", item.label);
    title.id = `collection-${item.id}`;
    card.setAttribute("aria-labelledby", title.id);
    appendText(heading, "span", `status ${item.activity === "running" ? "status-progress" : "status-missing"}`,
      item.availability === "available" ? activities[item.activity] || activities.unknown : "집계 미확인");
    card.append(heading);
    if (item.availability !== "available") {
      appendText(card, "p", "collection-note", "수집 원장을 읽거나 검증할 수 없습니다. 누락을 0건으로 처리하지 않았습니다.");
      target.append(card);
      return;
    }
    const metrics = element("dl", "collection-metrics");
    item.metrics.forEach((metric) => {
      const row = element("div");
      appendText(row, "dt", "", metric.label);
      appendText(row, "dd", "", collectionMetricText(metric));
      metrics.append(row);
    });
    card.append(metrics);
    const first = item.metrics[0];
    if (first?.expected > 0) {
      const progress = element("progress", "collection-progress");
      progress.max = first.expected;
      progress.value = first.completed;
      progress.setAttribute("aria-label", `${item.label} ${first.label}`);
      card.append(progress);
    }
    appendText(card, "p", "collection-note", item.note);
    if (item.failureCount) appendText(card, "p", "collection-warning", `본문·첨부 수집 오류 표식 ${format(item.failureCount)}건`);
    if (item.sourceDefectRows) appendText(card, "p", "collection-warning", `중복·식별자 검토 표식 ${format(item.sourceDefectRows)}건 · 자동 연결 보류`);
    appendText(card, "p", "collection-stamp", `최근 집계 ${dateTime(item.observedAt)} · ${item.collectionVerified ? "해당 원문 수집 조건 확인" : "수집·최종 대조 진행"}`);
    target.append(card);
  });
}

function renderPipeline(data) {
  const t = data.totals;
  const batches = data.mysql?.batches || [];
  const published = batches.filter((batch) => batch.state === "published").length;
  const drafts = batches.filter((batch) => batch.state !== "published").length;
  const items = [
    ["01", "수집", t.sources, "활성 원천"],
    ["02", "원문 분할", t.sourceUnits, "고정된 원문 단위"],
    ["03", "관계 추출", t.relations, "고유 관계 후보"],
    ["04", "요약 생성", t.reports, "커뮤니티 보고서"],
    ["05", "별도 서비스 DB", published, `법령 묶음 게시 판정 · 초안 ${format(drafts)}건`]
  ];
  const target = clear($("pipeline-steps"));
  items.forEach(([number, name, value, description]) => {
    const step = element("div", "pipeline-step");
    appendText(step, "span", "step-number", number);
    appendText(step, "strong", "step-name", name);
    appendText(step, "span", "step-value", format(value));
    appendText(step, "span", "step-desc", description);
    target.append(step);
  });
}

function domainStatus(item) {
  if (!item.sources) return ["그래프 입력 없음", "status-missing"];
  if (item.graphs < item.units) return ["그래프 생성 중", "status-progress"];
  return ["입력분 그래프 생성", "status-ready"];
}

function renderDomains(data) {
  const list = clear($("domain-list"));
  const filter = $("domain-filter");
  filter.querySelectorAll("option:not(:first-child)").forEach((node) => node.remove());
  const max = Math.max(1, ...data.domains.map((domain) => domain.sources));
  data.domains.forEach((domain) => {
    const option = element("option", "", domain.label);
    option.value = domain.id;
    filter.append(option);
    const button = element("button", "domain-row");
    button.type = "button";
    const mysqlLawCount = domain.id === "laws" ? state.overview?.mysql?.documents?.filter((doc) => doc.sourceKey === "law").length || 0 : 0;
    button.setAttribute("aria-label", mysqlLawCount && !domain.sources ? `${domain.label} 서비스 DB 문서 ${format(mysqlLawCount)}건 보기` : `${domain.label} GraphRAG 입력 ${format(domain.sources)}건 탐색`);
    const main = element("span", "domain-main");
    const titleLine = element("span", "domain-title-line");
    appendText(titleLine, "strong", "", domain.label);
    const [label, klass] = domainStatus(domain);
    appendText(titleLine, "span", `status ${klass}`, label);
    main.append(titleLine);
    appendText(main, "span", "domain-purpose", domain.purpose);
    rawDomainNotes(data, domain.id).forEach((note) => appendText(main, "span", "domain-collection", note));
    const bar = element("span", "domain-bar");
    const fill = element("span", "domain-fill");
    fill.style.width = `${Math.max(domain.sources ? 2 : 0, domain.sources / max * 100)}%`;
    bar.append(fill);
    main.append(bar);
    button.append(main);
    const count = element("span", "domain-count");
    appendText(count, "strong", "", format(domain.sources));
    appendText(count, "small", "", mysqlLawCount ? `원천 · MySQL 문서 ${format(mysqlLawCount)}` : `원천 · ${format(domain.graphs)} 그래프`);
    button.append(count);
    button.addEventListener("click", () => {
      if (mysqlLawCount && !domain.sources) {
        $("mysql-documents").scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      state.domain = domain.id;
      state.page = 1;
      filter.value = domain.id;
      loadSources();
      $("explorer").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    list.append(button);
  });
  const gaps = clear($("gap-list"));
  const priority = data.domains.filter((item) => item.id !== "other" && (!item.sources || item.id === "bills" || item.id === "central_people"));
  priority.forEach((item) => {
    const card = element("div", "gap-item");
    appendText(card, "span", "gap-dot", item.sources ? "△" : "○");
    const body = element("div");
    appendText(body, "strong", "", item.label);
    appendText(body, "p", "", item.next);
    rawDomainNotes(data, item.id).forEach((note) => appendText(body, "p", "", note));
    appendText(body, "small", "", item.plan);
    card.append(body);
    gaps.append(card);
  });
  const planTable = clear($("plan-table"));
  const table = element("table", "plan-table");
  const head = element("thead");
  const headRow = element("tr");
  ["영역", "수집 목적", "별도 원문 수집", "현재 GraphRAG 원천", "다음 확인", "계획 근거"].forEach((label) => appendText(headRow, "th", "", label));
  head.append(headRow); table.append(head);
  const body = element("tbody");
  data.domains.filter((item) => item.id !== "other").forEach((item) => {
    const row = element("tr");
    [item.label, item.purpose, rawDomainNotes(data, item.id).join(" / ") || "별도 수집기 집계 없음", `${format(item.sources)}건`, item.next, item.plan].forEach((value) => appendText(row, "td", "", value));
    body.append(row);
  });
  table.append(body); planTable.append(table);
}

function chart(targetId, entries, names, limit = 8) {
  const target = clear($(targetId));
  const rows = Object.entries(entries || {}).sort((a, b) => b[1] - a[1]).slice(0, limit);
  const max = Math.max(1, ...rows.map((row) => row[1]));
  if (!rows.length) { appendText(target, "p", "muted", "현재 항목이 없습니다."); return; }
  rows.forEach(([name, value]) => {
    const row = element("div", "chart-row");
    const label = element("div", "chart-label");
    appendText(label, "span", "", names[name] || name.replaceAll("_", " "));
    appendText(label, "strong", "", format(value));
    row.append(label);
    const bar = element("div", "chart-bar");
    const fill = element("span", "");
    fill.style.width = `${Math.max(2, value / max * 100)}%`;
    bar.append(fill);
    row.append(bar);
    target.append(row);
  });
}

function renderGraph(data) {
  chart("node-chart", data.nodeKinds, nodeNames);
  chart("edge-chart", data.edgeTypes, edgeNames);
  chart("review-chart", data.edgeDecisions, decisionNames);
  chart("level-chart", data.reportLevels, { "0": "1차", "1": "상위 1단계", "2": "상위 2단계", "3": "상위 3단계" });
  $("claim-count").textContent = `보고서 안의 주장 후보 ${format(data.totals.reportClaims)}건 · 내용 검수 전`;
}

function renderRadar(data) {
  const summary = clear($("radar-summary"));
  const list = clear($("radar-list"));
  if (!data) {
    appendText(summary, "p", "muted", "이 컴퓨터에서 뉴스 레이더 저장소를 확인할 수 없습니다.");
    return;
  }
  summary.append(
    metric("수집된 뉴스 기사", data.articleRecords, "별도 레이더 저장소", "metric-ink"),
    metric("검토 전 이슈 후보", data.candidates.length, "공식 기록 연결 전", "metric-teal")
  );
  const stamp = element("p", "radar-stamp", `최근 후보 생성 ${dateTime(data.generatedAt)} · 관측 ${format(data.observations)}회`);
  summary.append(stamp);
  data.candidates.forEach((candidate) => {
    const card = element("details", "radar-card");
    const heading = element("summary");
    const headline = element("span", "radar-headline");
    appendText(headline, "strong", "", candidate.title || "제목 없음");
    appendText(headline, "small", "", `${format(candidate.articleCount)}개 기사 · ${format(candidate.publisherCount)}개 매체`);
    heading.append(headline);
    appendText(heading, "span", "status status-progress", "공식 기록 확인 전");
    card.append(heading);
    appendText(card, "p", "radar-reason", candidate.reason || "후보 선정 근거 미제공");
    const articles = element("ul", "radar-articles");
    candidate.articles.forEach((article) => {
      const item = element("li");
      if (article.url) {
        const link = element("a", "", article.title || "기사 원문");
        link.href = article.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        item.append(link);
      } else appendText(item, "span", "", article.title || "기사 제목 없음");
      appendText(item, "small", "", `${article.publisher || "매체 미확인"} · ${dateTime(article.publishedAt)}`);
      articles.append(item);
    });
    card.append(articles);
    list.append(card);
  });
}

function renderMysql(data) {
  const target = clear($("mysql-panel"));
  if (!data) {
    appendText(target, "p", "mysql-empty", "MySQL 관측 파일이 없습니다. 현재 GraphRAG 데이터와 공개 DB의 수치를 합산하지 않았습니다.");
    return;
  }
  const heading = element("div", "mysql-heading");
  appendText(heading, "strong", "", `로컬 MySQL · ${data.database}`);
  appendText(heading, "span", "", `관측 ${dateTime(data.observedAt)}`);
  target.append(heading);
  const items = [
    ["수집 원천", "parliament_source_record"],
    ["지식 자료 묶음", "knowledge_batch"],
    ["문서 버전", "knowledge_document_version"],
    ["근거 구간", "knowledge_evidence"],
    ["검수 관계", "knowledge_relation"],
    ["공개 사건", "tracking_event"]
  ];
  const cards = element("div", "mysql-cards");
  items.forEach(([label, key]) => cards.append(metric(label, data.counts[key], "MySQL 실제 행 수", "mysql-metric")));
  target.append(cards);
  const cols = element("div", "mysql-columns");
  const batches = element("div", "mysql-list");
  appendText(batches, "h3", "", "자료 묶음별 검수 상태");
  (data.batches || []).forEach((item) => {
    const row = element("div", "mysql-row");
    appendText(row, "strong", "", item.issueId);
    appendText(row, "span", item.state === "published" ? "status status-ready" : "status status-progress", item.state === "published" ? "게시 판정" : item.state === "draft" ? "초안" : item.state);
    appendText(row, "small", "", item.id);
    batches.append(row);
  });
  const docs = element("div", "mysql-list");
  docs.id = "mysql-documents";
  appendText(docs, "h3", "", "저장된 문서");
  (data.documents || []).forEach((item) => {
    const versions = (data.extractions || []).filter((entry) => entry.documentId === item.id);
    const selected = versions.find((entry) => entry.extractionVersion === item.extractionVersion);
    const row = element("details", "mysql-doc");
    const summary = element("summary");
    appendText(summary, "strong", "", item.title || item.id);
    appendText(summary, "span", "", `${format(selected?.segmentCount || 0)}구간 · 추출 버전 ${format(versions.length)}개`);
    row.append(summary);
    appendText(row, "p", "mysql-doc-meta", `${item.id} · ${bodyNames[item.bodyStatus] || item.bodyStatus || "본문 미확인"} · ${licenseNames[item.licenseStatus] || item.licenseStatus || "이용 미확인"}`);
    if (selected) {
      appendText(row, "p", "mysql-doc-note", "현재 문서가 가리키는 추출 버전의 조문 예시입니다. 근거 구간은 GraphRAG 관계와 별도로 저장돼 있습니다.");
      selected.samples.filter((sample) => sample.text).forEach((sample) => {
        const sampleRow = element("div", "mysql-sample");
        appendText(sampleRow, "small", "", sample.locator || "위치 미확인");
        appendText(sampleRow, "p", "", sample.text);
        row.append(sampleRow);
      });
    }
    const match = /^law_\d+_(\d+)$/.exec(item.id || "");
    if (match) {
      const source = element("a", "mysql-source", "국가법령정보센터 원문 ↗");
      source.href = `https://www.law.go.kr/DRF/lawService.do?target=law&MST=${match[1]}&type=JSON`;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      row.append(source);
    }
    docs.append(row);
  });
  cols.append(batches, docs);
  target.append(cols);
}

async function loadOverview() {
  try {
    const data = await get("/api/overview");
    state.overview = data;
    $("snapshot-time").textContent = `그래프 파일 ${dateTime(data.databaseModifiedAt * 1000)} · 원천 최근 관측 ${dateTime(data.latestSourceObservation)}`;
    renderMetrics(data);
    renderCollections(data.collection);
    renderPipeline(data);
    renderDomains(data);
    renderGraph(data);
    renderRadar(data.radar);
    renderMysql(data.mysql);
    showError("");
  } catch (error) { showError(error.message); }
}

async function loadSources() {
  const params = new URLSearchParams({ domain: state.domain, q: state.query, page: String(state.page) });
  try {
    const data = await get(`/api/sources?${params}`);
    state.total = data.total;
    $("record-count").textContent = `${format(data.total)}건의 원천 기록`;
    $("page-state").textContent = `${format(state.page)} / ${format(Math.max(1, Math.ceil(data.total / data.pageSize)))}`;
    $("page-prev").disabled = state.page <= 1;
    $("page-next").disabled = state.page * data.pageSize >= data.total;
    const list = clear($("record-list"));
    if (!data.items.length) { appendText(list, "p", "records-empty", "이 조건에서 확인된 기록이 없습니다."); return; }
    data.items.forEach((item) => {
      const button = element("button", "record-row" + (state.scope === item.scope ? " selected" : ""));
      button.type = "button";
      appendText(button, "span", "record-kind", item.sourceKey || "출처 미확인");
      appendText(button, "strong", "", item.title);
      appendText(button, "small", "", `원문 ${format(item.units)}구간 · ${licenseNames[item.license] || item.license}`);
      button.addEventListener("click", () => { state.scope = item.scope; state.offset = 0; loadDetail(); });
      list.append(button);
    });
  } catch (error) { showError(error.message); }
}

function detailField(parent, label, value) {
  const row = element("div", "detail-field");
  appendText(row, "dt", "", label);
  appendText(row, "dd", "", value || "확인되지 않음");
  parent.append(row);
}

function renderDetail(data) {
  const target = clear($("detail"));
  const header = element("div", "detail-header");
  appendText(header, "span", "panel-kicker", "원천 기록 상세");
  appendText(header, "h3", "", data.document.title || data.scope);
  appendText(header, "p", "detail-id", data.scope);
  target.append(header);
  const fields = element("dl", "detail-fields");
  detailField(fields, "출처 유형", data.document.sourceKey);
  detailField(fields, "원문 상태", bodyNames[data.document.bodyStatus] || data.document.bodyStatus);
  detailField(fields, "이용 조건", licenseNames[data.document.licenseStatus] || data.document.licenseStatus);
  detailField(fields, "발표일", data.document.publishedAt);
  detailField(fields, "원문 버전", data.document.version);
  detailField(fields, "추출 버전", data.document.extractionVersion);
  target.append(fields);
  if (data.document.sourceUrl) {
    const link = element("a", "source-link", "공식 원문 열기 ↗");
    link.href = data.document.sourceUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    target.append(link);
  }
  const section = element("section", "unit-section");
  appendText(section, "h4", "", `원문 구간 ${format(data.totalUnits)}개`);
  data.units.forEach((unit, index) => {
    const card = element("details", "unit-card");
    if (index === 0) card.open = true;
    const summary = element("summary");
    appendText(summary, "strong", "", unit.locator || unit.id);
    appendText(summary, "span", unit.indexed ? "unit-ready" : "unit-missing", unit.indexed ? "그래프 생성" : "그래프 없음");
    card.append(summary);
    appendText(card, "p", "unit-text", unit.text || "원문 텍스트 없음");
    if (unit.textTruncated) appendText(card, "p", "muted", "긴 원문은 앞부분만 표시합니다. 전체 내용은 공식 원문에서 확인하세요.");
    if (unit.entities.length) {
      appendText(card, "h5", "", "추출된 노드");
      const tags = element("div", "entity-tags");
      unit.entities.forEach((node) => appendText(tags, "span", "entity-tag", `${node.name} · ${nodeNames[node.kind] || node.kind}`));
      card.append(tags);
    }
    if (unit.relations.length) {
      appendText(card, "h5", "", "관계 후보와 근거");
      unit.relations.forEach((relation) => {
        const box = element("div", "relation-box");
        appendText(box, "strong", "", `${relation.from} → ${edgeNames[relation.type] || relation.type} → ${relation.to}`);
        appendText(box, "span", "relation-state", decisionNames[relation.decision] || relation.decision);
        if (relation.evidence.length) appendText(box, "p", "relation-proof", relation.evidence[0].text);
        if (relation.blockedBy.length) appendText(box, "small", "", `공개 보류: ${relation.blockedBy.map((reason) => blockNames[reason] || reason).join(", ")}`);
        card.append(box);
      });
    }
    section.append(card);
  });
  if (data.offset > 0 || data.offset + data.units.length < data.totalUnits) {
    const pager = element("div", "pager unit-pager");
    const prev = element("button", "", "이전 구간"); prev.disabled = data.offset === 0;
    const next = element("button", "", "다음 구간"); next.disabled = data.offset + data.units.length >= data.totalUnits;
    prev.addEventListener("click", () => { state.offset -= 8; loadDetail(); });
    next.addEventListener("click", () => { state.offset += 8; loadDetail(); });
    pager.append(prev, next); section.append(pager);
  }
  target.append(section);
}

async function loadDetail() {
  if (!state.scope) return;
  try {
    const params = new URLSearchParams({ scope: state.scope, offset: String(state.offset) });
    const data = await get(`/api/source?${params}`);
    renderDetail(data);
    document.querySelectorAll(".record-row").forEach((row) => row.classList.remove("selected"));
  } catch (error) { showError(error.message); }
}

$("search-button").addEventListener("click", () => { state.query = $("source-search").value.trim(); state.page = 1; loadSources(); });
$("source-search").addEventListener("keydown", (event) => { if (event.key === "Enter") $("search-button").click(); });
$("domain-filter").addEventListener("change", (event) => { state.domain = event.target.value; state.page = 1; loadSources(); });
$("page-prev").addEventListener("click", () => { state.page -= 1; loadSources(); });
$("page-next").addEventListener("click", () => { state.page += 1; loadSources(); });
$("refresh-button").addEventListener("click", () => { loadOverview().then(loadSources); });
loadOverview().then(loadSources);
setInterval(loadOverview, 60000);
