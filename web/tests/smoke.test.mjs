import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";

// Contract fixtures run only in this isolated test server, never in the product.
const activity = {
  id: "contract-event", type: "vote", title: "계약 검증용 표결 기록", summary: "테스트용 공개 기록입니다.", stage: "voted",
  personIds: ["contract-person"], topics: ["housing"], billId: "contract-bill", occurredAt: null,
  publishedAt: "2026-10-01T04:00:00Z", collectedAt: "2026-10-01T05:00:00Z", sourceUrl: "https://www.assembly.go.kr/",
  evidence: [{ id: "contract-evidence", sourceUrl: "https://www.assembly.go.kr/", excerpt: "계약 검증용 근거", locator: "테스트 원문", sourceVersion: "source-v1" }],
  votes: [{ personId: "contract-person", name: "검증용 인물", result: "unknown", sessionId: "session-1" }],
  coverage: "테스트용 자료 범위", corrected: true, version: "version-1"
};
const knowledgeDocument = {
  id: "contract-document", version: "raw-v1", sourceKey: "official", recordKey: "record-1",
  sourceUrl: "https://ampos.nanet.go.kr/record", title: "검증용 공식 문서", format: "html", bodyStatus: "available", licenseStatus: "allowed",
  publishedAt: activity.publishedAt, collectedAt: activity.collectedAt, extractionVersion: "extract-v1",
  segments: [{ id: "segment-1", text: "검증용 인물이 제안했다.", locator: "본문 1", mentions: [{ id: "mention-1", surface: "검증용 인물", start: 0, end: 6, personId: "contract-person", decision: "approved" }] }]
};
const knowledgeEvidence = {
  id: "contract-evidence", documentId: knowledgeDocument.id, documentVersion: "raw-v1", extractionVersion: "extract-v1", segmentId: "segment-1",
  start: 0, end: 6, excerpt: "검증용 인물", before: "", after: "이 제안했다.", mentions: knowledgeDocument.segments[0].mentions,
  sourceUrl: knowledgeDocument.sourceUrl, title: knowledgeDocument.title, locator: "본문 1"
};
const knowledgeContext = {
  eventId: activity.id, eventVersion: activity.version, changeKind: "new_record", activity,
  participants: [{ personId: "contract-person", name: "검증용 인물", role: "lead_sponsor", evidenceIds: [knowledgeEvidence.id], organizationAtTime: "사건 당시 기관", positionAtTime: "의원" }],
  relations: [], evidence: [knowledgeEvidence], documents: [knowledgeDocument]
};
const knowledgeGraph = {
  rootKey: "person:contract-person", visibility: "published", truncated: true,
  nodes: [
    { key: "person:contract-person", id: "contract-person", kind: "person", label: "검증용 인물", href: "/people/contract-person", version: null },
    { key: "organization:contract-org", id: "contract-org", kind: "organization", label: "확인된 기관", href: "/explore?rootKind=organization&rootId=contract-org", version: null },
    { key: "document:contract-document", id: "contract-document", kind: "document", label: "검증용 공식 문서", href: "/documents/contract-document?version=raw-v1&extractionVersion=extract-v1", version: "raw-v1" }
  ],
  edges: [
    { id: "edge-office", sourceKey: "person:contract-person", targetKey: "organization:contract-org", type: "holds_office", label: "의원", evidenceIds: [knowledgeEvidence.id], batchId: "batch-contract", reviewedAt: activity.collectedAt, validFrom: null, validUntil: null, observedAt: activity.collectedAt },
    { id: "edge-source", sourceKey: "person:contract-person", targetKey: "document:contract-document", type: "supported_by", label: "원문 근거", evidenceIds: [knowledgeEvidence.id], batchId: "batch-contract", reviewedAt: activity.collectedAt, validFrom: null, validUntil: null, observedAt: activity.collectedAt }
  ]
};
async function listen(server) {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return server.address().port;
}

test("production SSR and fixed proxy meet the backend contracts", { timeout: 30000 }, async () => {
  const observed = [];
  let knowledgeStatus = 200;
  const backend = createServer(async (request, response) => {
    const url = new URL(request.url, "http://localhost");
    let body = "";
    for await (const chunk of request) body += chunk;
    observed.push({ path: url.pathname, search: url.search, method: request.method, headers: request.headers, body });
    response.setHeader("Content-Type", "application/json");
    if (knowledgeStatus !== 200 && (/\/(profile|context|lineage|timeline)$/.test(url.pathname) || /\/api\/v1\/(documents|evidence)\//.test(url.pathname) || url.pathname.startsWith("/api/v1/knowledge/"))) {
      response.statusCode = knowledgeStatus;
      return response.end('{"message":"knowledge unavailable"}');
    }
    if (url.pathname === "/api/v1/knowledge/graph") return response.end(JSON.stringify(knowledgeGraph));
    if (url.pathname === "/api/v1/knowledge/people") return response.end(JSON.stringify({ items: [{ id: "contract-person", name: "검증용 인물", kind: "person", position: "의원", organizationId: "contract-org", organizationName: "확인된 기관", observedAt: activity.collectedAt }], nextCursor: url.searchParams.has("cursor") ? null : "next-person" }));
    if (url.pathname === "/api/v1/activities") return response.end(JSON.stringify({ items: [activity], nextCursor: "cursor-fixture" }));
    if (url.pathname === "/api/v1/activities/contract-event/history") return response.end(JSON.stringify({ items: [{ version: "version-1", reviewedAt: activity.collectedAt, corrected: true, correctionReason: "테스트 정정 사유" }] }));
    if (url.pathname === "/api/v1/activities/contract-event/context") return response.end(JSON.stringify(knowledgeContext));
    if (url.pathname === "/api/v1/activities/contract-event") return response.end(JSON.stringify(activity));
    if (url.pathname === "/api/v1/people") return response.end(JSON.stringify({ items: [{ id: "contract-person", name: "검증용 인물", kind: "legislator", organization: "검증용 기관", role: "검증용 직위" }] }));
    if (url.pathname === "/api/v1/people/contract-person") return response.end(JSON.stringify({ id: "contract-person", name: "검증용 인물", kind: "legislator", organization: "검증용 기관", role: "검증용 직위", activities: [activity] }));
    if (url.pathname === "/api/v1/people/contract-person/profile") return response.end(JSON.stringify({ id: "contract-person", name: "검증용 인물", kind: "person", facts: [{ label: "확인된 경력", value: "근거가 있는 소개 사실", evidenceIds: [knowledgeEvidence.id] }], tenures: [{ organizationId: "contract-org", organizationName: "확인된 기관", position: "의원", party: null, validFrom: null, validUntil: null, observedAt: activity.collectedAt, evidenceIds: [knowledgeEvidence.id] }], relatedIssues: [{ id: "contract-issue", title: "검증용 이슈" }], activities: [knowledgeContext] }));
    if (url.pathname === "/api/v1/bills") return response.end(JSON.stringify({ items: [{ id: "contract-bill", title: "검증용 법안", stage: "proposed" }] }));
    if (url.pathname === "/api/v1/bills/contract-bill") return response.end(JSON.stringify({ id: "contract-bill", title: "검증용 법안", stage: "proposed", activities: [activity], votes: activity.votes, sourceUrl: activity.sourceUrl }));
    if (url.pathname === "/api/v1/bills/contract-alternative") return response.end(JSON.stringify({ id: "contract-alternative", title: "검증용 위원회 대안", stage: "passed", activities: [], votes: [], sourceUrl: activity.sourceUrl }));
    if (url.pathname === "/api/v1/bills/contract-bill/lineage") return response.end(JSON.stringify({ id: "contract-bill", items: [{ id: "relation-1", subjectId: "contract-bill", objectId: "contract-alternative", type: "incorporated_into_alternative", evidenceIds: [knowledgeEvidence.id], decision: "approved", reason: "대안 원문으로 확인" }] }));
    if (url.pathname === "/api/v1/issues") return response.end(JSON.stringify({ items: [{ id: "contract-issue", title: "검증용 이슈", topic: "housing", description: "검증용 설명" }] }));
    if (url.pathname === "/api/v1/issues/contract-issue") return response.end(JSON.stringify({ id: "contract-issue", title: "검증용 이슈", topic: "housing", description: "검증용 설명", activities: [activity] }));
    if (url.pathname === "/api/v1/issues/contract-issue/timeline") return response.end(JSON.stringify({ id: "contract-issue", items: [knowledgeContext], nextCursor: "next-timeline" }));
    if (url.pathname === "/api/v1/documents/contract-document") return response.end(JSON.stringify(knowledgeDocument));
    if (url.pathname === "/api/v1/evidence/contract-evidence") return response.end(JSON.stringify(knowledgeEvidence));
    if (url.pathname === "/api/v1/coverage") return response.end(JSON.stringify({ items: [{ source: "검증용 소스", status: "success_changed", lastObservedAt: activity.collectedAt, range: "테스트 범위", note: "검증 완료" }] }));
    if (url.pathname === "/api/v1/search") return response.end(JSON.stringify({ items: [activity], nextCursor: null }));
    if (url.pathname === "/api/v1/auth/verify") {
      response.setHeader("Set-Cookie", "parliament_session=contract; Path=/; HttpOnly; SameSite=Lax");
      return response.end('{"authenticated":true}');
    }
    response.statusCode = 404; response.end('{"message":"not found"}');
  });
  const backendPort = await listen(backend);
  const reservation = createServer();
  const webPort = await listen(reservation);
  await new Promise(resolve => reservation.close(resolve));
  const origin = `http://127.0.0.1:${webPort}`;
  const child = spawn(process.execPath, [".next/standalone/server.js"], { env: { ...process.env, HOSTNAME: "127.0.0.1", PORT: String(webPort), BACKEND_URL: `http://127.0.0.1:${backendPort}`, PUBLIC_BASE_URL: origin, NEXT_TELEMETRY_DISABLED: "1" }, stdio: "pipe" });
  let logs = "";
  child.stdout.on("data", chunk => { logs += chunk; }); child.stderr.on("data", chunk => { logs += chunk; });
  try {
    let ready = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      try { ready = (await fetch(`${origin}/about`)).ok; } catch { /* Wait only for the local test server. */ }
      if (ready) break;
      await delay(100);
    }
    assert.ok(ready, `Local production server did not start: ${logs}`);
    const home = await fetch(origin);
    const homeHtml = await home.text();
    assert.equal(home.status, 200);
    assert.match(homeHtml, /계약 검증용 표결 기록/);
    assert.match(homeHtml, /cursor-fixture/);
    const detailHtml = await (await fetch(`${origin}/activities/contract-event?version=version-1`)).text();
    assert.match(detailHtml, /<title>계약 검증용 표결 기록/);
    assert.match(detailHtml, /개인별 기록 미확인/);
    assert.match(detailHtml, /source-v1/);
    assert.match(detailHtml, /정정된 기록/);
    assert.match(detailHtml, /테스트 정정 사유/);
    assert.match(detailHtml, /검증용 인물/);
    assert.match(detailHtml, /대표발의/);
    assert.match(detailHtml, /사건 당시 기관/);
    assert.ok(observed.some(entry => entry.path === "/api/v1/activities/contract-event" && entry.search === "?version=version-1"));
    for (const path of ["/people", "/people/contract-person", "/bills", "/bills/contract-bill", "/issues", "/issues/contract-issue", "/coverage", "/search?q=test"]) {
      const response = await fetch(origin + path);
      const html = await response.text();
      assert.equal(response.status, 200, path);
      assert.doesNotMatch(html, /기록 서버에 연결할 수 없습니다/, path);
    }
    const personHtml = await (await fetch(`${origin}/people/contract-person`)).text();
    assert.match(personHtml, /근거가 있는 소개 사실/);
    assert.match(personHtml, /활동 역할/);
    assert.match(personHtml, /explore\?rootKind=person/);
    const peopleHtml = await (await fetch(`${origin}/people?query=test&organizationId=contract-org`)).text();
    assert.match(peopleHtml, /자료 확인일/);
    assert.match(peopleHtml, /cursor=next-person/);
    assert.match(peopleHtml, /organizationId=contract-org/);
    assert.ok(observed.some(entry => entry.path === "/api/v1/knowledge/people" && entry.search.includes("query=test") && entry.search.includes("organizationId=contract-org")));
    const graphHtml = await (await fetch(`${origin}/explore?rootKind=person&rootId=contract-person&depth=2`)).text();
    assert.match(graphHtml, /검증용 인물의 검수된 관계 지도/);
    assert.match(graphHtml, /일부 연결만 표시/);
    assert.match(graphHtml, /evidence\/contract-evidence/);
    assert.match(graphHtml, /extractionVersion=extract-v1/);
    assert.match(graphHtml, /연결과 근거/);
    assert.ok(observed.some(entry => entry.path === "/api/v1/knowledge/graph" && entry.search.includes("depth=2")));
    const billHtml = await (await fetch(`${origin}/bills/contract-bill`)).text();
    assert.match(billHtml, /href="\/bills\/contract-alternative">검증용 위원회 대안/);
    assert.match(billHtml, /의결/);
    const issueHtml = await (await fetch(`${origin}/issues/contract-issue`)).text();
    assert.match(issueHtml, /공개일 기준/);
    assert.match(issueHtml, /next-timeline/);
    const documentHtml = await (await fetch(`${origin}/documents/contract-document?version=raw-v1&extractionVersion=extract-v1`)).text();
    assert.match(documentHtml, /추출 버전/);
    assert.match(documentHtml, /href="\/people\/contract-person"/);
    const evidenceHtml = await (await fetch(`${origin}/evidence/contract-evidence`)).text();
    assert.match(evidenceHtml, /뒤 문맥/);
    assert.match(evidenceHtml, /documents\/contract-document\?version=raw-v1/);
    assert.match(evidenceHtml, /extractionVersion=extract-v1/);
    assert.ok(observed.some(entry => entry.path === "/api/v1/activities/contract-event/context" && entry.search === "?version=version-1"));
    assert.ok(observed.some(entry => entry.path === "/api/v1/documents/contract-document" && entry.search.includes("extractionVersion=extract-v1")));
    knowledgeStatus = 404;
    for (const path of ["/people/contract-person", "/activities/contract-event", "/bills/contract-bill", "/issues/contract-issue"]) {
      const response = await fetch(origin + path);
      assert.equal(response.status, 200);
      assert.doesNotMatch(await response.text(), /연결된 인물·문서·근거를 불러오지 못했습니다/);
    }
    assert.equal((await fetch(`${origin}/documents/contract-document`)).status, 404);
    const legacyDirectoryHtml = await (await fetch(`${origin}/people`)).text();
    assert.match(legacyDirectoryHtml, /기존 공개 명부/);
    assert.match(legacyDirectoryHtml, /검증용 인물/);
    knowledgeStatus = 503;
    const partialHtml = await (await fetch(`${origin}/activities/contract-event`)).text();
    assert.match(partialHtml, /연결된 인물·문서·근거를 불러오지 못했습니다/);
    assert.match(partialHtml, /계약 검증용 표결 기록/);
    const unavailableGraphHtml = await (await fetch(`${origin}/explore?rootKind=person&rootId=contract-person`)).text();
    assert.match(unavailableGraphHtml, /기록 서버에 연결할 수 없습니다/);
    assert.doesNotMatch(unavailableGraphHtml, /검수된 관계 지도/);
    knowledgeStatus = 200;
    assert.equal(observed.find(entry => entry.path === "/api/v1/people").search, "");
    assert.equal(observed.find(entry => entry.path === "/api/v1/bills").search, "");
    assert.equal((await fetch(`${origin}/activities/missing`)).status, 404);
    assert.equal((await fetch(`${origin}/api/admin/ingestion`)).status, 404);
    const beforeCandidatePreview = observed.length;
    assert.equal((await fetch(`${origin}/api/admin/tracking/knowledge/batches/batch-contract/graph`)).status, 404);
    assert.equal(observed.length, beforeCandidatePreview);
    const login = await fetch(`${origin}/api/v1/auth/verify`, { method: "POST", headers: { Origin: origin, "Content-Type": "application/json", "X-Admin-Key": "not-forwarded" }, body: '{"token":"fixture-token"}' });
    assert.equal(login.status, 200);
    assert.match(login.headers.get("set-cookie"), /HttpOnly/);
    assert.equal(observed.at(-1).headers["x-admin-key"], undefined);
    assert.equal((await fetch(`${origin}/api/v1/auth/verify`, { method: "POST", headers: { Origin: "https://evil.example" }, body: "{}" })).status, 403);
    const observedBeforeOversize = observed.length;
    const oversized = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(16384));
        controller.enqueue(new Uint8Array(16384));
        controller.enqueue(new Uint8Array(4096));
        controller.close();
      }
    });
    const rejected = await fetch(`${origin}/api/v1/auth/verify`, {
      method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
      body: oversized, duplex: "half"
    });
    assert.equal(rejected.status, 413);
    assert.equal(observed.length, observedBeforeOversize);
  } finally {
    child.kill("SIGTERM");
    await new Promise(resolve => backend.close(resolve));
  }
});
