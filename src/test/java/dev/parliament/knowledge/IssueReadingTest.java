package dev.parliament.knowledge;

import static org.mockito.Mockito.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import dev.parliament.tracking.Activity;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.HttpStatus;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

/** All identities and content in the normal-response tests are synthetic. */
class IssueReadingTest {
    ObjectMapper mapper = new ObjectMapper().registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule())
            .disable(com.fasterxml.jackson.databind.SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    KnowledgeReads knowledge;
    ObjectNode source;
    ObjectNode publication;

    @BeforeEach void setup() throws Exception {
        knowledge = mock(KnowledgeReads.class);
        source = (ObjectNode) mapper.readTree("""
            {"id":"test-editorial","title":"시험 해설","summary":"시험 배경",
             "reviewStatus":"reviewed","reviewedAt":"2026-10-18T09:00:00+09:00",
             "checkedAt":"2026-10-18","currentStage":"검토한 단계","nextTrigger":"다음 공식 발표",
             "coverage":"합성 이슈의 법안 기록 1건과 역할 1건만 포함한다.",
             "background":["배경 문장"],"facts":["사실 문장"],"claims":[],"unknowns":["미확인 문장"],
             "timeline":[],"updates":[]}
            """);
        publication = (ObjectNode) mapper.readTree("""
            {"issueId":"test-issue","editorialId":"test-editorial","editorialVersion":"REPLACE",
             "version":"published-test-v1","state":"published","publishedAt":"2026-10-18T01:00:00Z",
             "reviewedAt":"2026-10-18T09:00:00+09:00",
             "summaryEvidenceIds":["test-evidence"],"stageEvidenceIds":["test-evidence"],
             "blocks":[{"id":"b1","section":"background","index":0,"evidenceIds":["test-evidence"],"personIds":["test-person"]},
                       {"id":"f1","section":"facts","index":0,"evidenceIds":["test-evidence"],"personIds":[]},
                       {"id":"u1","section":"unknowns","index":0,"evidenceIds":[],"personIds":[]}],
             "contexts":[{"eventId":"test-event","eventVersion":"test-event-v1"}],
             "people":[{"id":"test-person","evidenceIds":["test-evidence"]}],
             "evidence":[{"id":"test-evidence","documentId":"test-doc","documentVersion":"test-doc-v1",
                           "extractionVersion":"test-extract-v1","segmentId":"test-segment","start":0,"end":2}]}
            """);
        publication.put("editorialVersion", sourceHash());
        sealPublication();
        var evidence = evidence("test-doc-v1");
        var participant = new KnowledgeReads.Participant("test-person", "합성 인물", "lead_sponsor",
                List.of("test-evidence"), null, null);
        var activity = new Activity("test-event", "bill", "합성 법안 기록", "합성 기록 요약", "proposed",
                List.of("test-person"), List.of("test-issue"), "test-bill", null,
                Instant.parse("2026-10-17T00:00:00Z"), Instant.parse("2026-10-18T00:00:00Z"),
                "https://www.law.go.kr/test", List.of(new Activity.Evidence("test-evidence",
                "https://www.law.go.kr/test", "근거", "page 1", "test-doc-v1")), List.of(),
                "합성 검사 전용", false, "test-event-v1");
        var relation = new KnowledgeBatch.Relation("test-role", "test-person", "test-bill", "lead_sponsor",
                List.of("test-evidence"), "approved", "합성 자료의 승인 역할");
        var document = mapper.convertValue(mapper.readTree("""
            {"id":"test-doc","version":"test-doc-v1","extractionVersion":"test-extract-v1",
             "sourceKey":"synthetic","recordKey":"test-doc","sourceUrl":"https://www.law.go.kr/test",
             "title":"합성 원문","format":"html","bodyStatus":"available","licenseStatus":"allowed",
             "publishedAt":"2026-10-17T00:00:00Z","collectedAt":"2026-10-18T00:00:00Z","datePrecision":"date",
             "segments":[{"id":"test-segment","text":"근거","locator":"page 1","mentions":[]}]}
            """), new com.fasterxml.jackson.core.type.TypeReference<java.util.Map<String,Object>>() {});
        var context = new KnowledgeReads.PublicContext("test-event", "test-event-v1", "new_record", activity,
                List.of(participant), List.of(relation), List.of(evidence), List.of(document), "published", null, null);
        when(knowledge.context("test-event", "test-event-v1")).thenReturn(Mono.just(context));
        when(knowledge.evidence("test-evidence")).thenReturn(Mono.just(evidence));
        when(knowledge.profile("test-person")).thenReturn(Mono.just(new KnowledgeReads.Profile(
                "test-person", "합성 인물", "person", List.of(), List.of(), List.of(), List.of())));
    }

    @Test void returnsVersionedReadingWithExactPublishedReferences() throws Exception {
        var response = client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Cache-Control", "no-store")
                .expectBody().jsonPath("$.issueId").isEqualTo("test-issue")
                .jsonPath("$.version").isEqualTo(publication.path("version").asText())
                .jsonPath("$.editorialVersion").isEqualTo(sourceHash())
                .jsonPath("$.blocks[0].id").isEqualTo("b1")
                .jsonPath("$.people[0].id").isEqualTo("test-person")
                .jsonPath("$.evidence[0].documentVersion").isEqualTo("test-doc-v1")
                .jsonPath("$.contexts[0].activity.publishedAt").isEqualTo("2026-10-17T00:00:00Z")
                .jsonPath("$.contexts[0].documents[0].id").isEqualTo("test-doc")
                .jsonPath("$.publicationState").isEqualTo("published").returnResult();
        var artifact = Path.of("build/test-evidence/issue-reading-v1-success.json");
        Files.createDirectories(artifact.getParent());
        Files.write(artifact, response.getResponseBody());
    }

    @ParameterizedTest @ValueSource(strings = {"draft", "pending", "rejected", "withdrawn"})
    void hidesNonPublishedContent(String state) throws Exception {
        publication.put("state", state);
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isNotFound();
        verifyNoInteractions(knowledge);
    }

    @Test void copiedReviewedTimestampDoesNotApprovePendingEditorial() throws Exception {
        source.put("reviewStatus", "human-review-pending");
        publication.put("editorialVersion", sourceHash());
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isNotFound();
        verifyNoInteractions(knowledge);
    }

    @Test void changedEditorialRequiresNewPublication() throws Exception {
        source.put("summary", "새로 바뀐 미검토 문장");
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void changedSourcePinCannotReuseAnOldPublicationVersion() throws Exception {
        source.put("summary", "새 원고로 변경");
        publication.put("editorialVersion", sourceHash());
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void changedEvidenceVersionIsNotSubstituted() throws Exception {
        when(knowledge.evidence("test-evidence")).thenReturn(Mono.just(evidence("new-version")));
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void revokedEvidenceReturns404WithoutOldContent() throws Exception {
        when(knowledge.evidence("test-evidence")).thenReturn(Mono.error(new ResponseStatusException(HttpStatus.NOT_FOUND)));
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isNotFound()
                .expectBody().jsonPath("$.summary").doesNotExist();
    }

    @Test void evidenceMustStillBelongToThePublishedContext() throws Exception {
        when(knowledge.context("test-event", "test-event-v1")).thenReturn(Mono.just(
                new KnowledgeReads.PublicContext("test-event", "test-event-v1", "new_record", null,
                        List.of(), List.of(), List.of(), List.of(), "published", null, null)));
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void canonicalIdentityMismatchIsNotMerged() throws Exception {
        when(knowledge.profile("test-person")).thenReturn(Mono.just(new KnowledgeReads.Profile(
                "other-person", "같은 이름", "person", List.of(), List.of(), List.of(), List.of())));
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void everyFactMustHaveAnExactBinding() throws Exception {
        publication.withArray("blocks").remove(1);
        sealPublication();
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void publicContextParticipantRequiresItsApprovedRoleRelation() throws Exception {
        var context = knowledge.context("test-event", "test-event-v1").block();
        when(knowledge.context("test-event", "test-event-v1")).thenReturn(Mono.just(
                new KnowledgeReads.PublicContext(context.eventId(), context.eventVersion(), context.changeKind(),
                        context.activity(), context.participants(), List.of(), context.evidence(), context.documents(),
                        context.dateKind(), null, null)));
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(409);
    }

    @Test void arbitraryUpdateFieldsAreNotProjected() throws Exception {
        source.withArray("updates").add(mapper.createObjectNode().put("date", "2026-10-18")
                .put("note", "검사용 갱신").put("privateCandidateId", "must-not-expose"));
        publication.put("editorialVersion", sourceHash());
        sealPublication();
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isOk()
                .expectBody().jsonPath("$.updates[0].privateCandidateId").doesNotExist();
    }

    @Test void remoteEditorialSourceIsRejectedWithoutFetching() throws Exception {
        var catalogBytes = mapper.writeValueAsBytes(mapper.createObjectNode().set("publications", mapper.createArrayNode().add(publication)));
        var catalog = new IssueReadingCatalog(mapper, new ByteArrayResource(catalogBytes),
                new org.springframework.core.io.UrlResource("https://example.invalid/private.json"));
        var client = clientFor(catalog);
        client.get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(503);
        verifyNoInteractions(knowledge);
    }

    @Test void invalidIssueIdentifierDoesNotReachPrivateReads() throws Exception {
        client().get().uri("/api/v1/issues/bad.id/reading").exchange().expectStatus().isBadRequest()
                .expectHeader().valueEquals("Cache-Control", "no-store")
                .expectBody().jsonPath("$.error").isEqualTo("invalid_issue_id");
        verifyNoInteractions(knowledge);
    }

    @Test void missingEditorialFileIsUnavailable() throws Exception {
        var bytes = mapper.writeValueAsBytes(mapper.createObjectNode().set("publications", mapper.createArrayNode().add(publication)));
        var catalog = new IssueReadingCatalog(mapper, new ByteArrayResource(bytes), new ClassPathResource("missing-source.json"));
        var client = clientFor(catalog);
        client.get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(503);
        verifyNoInteractions(knowledge);
    }

    @Test void rechecksWithdrawnPublicationWithoutKeepingAnOldSuccess() throws Exception {
        var path = Files.createTempFile("issue-reading-synthetic-", ".json");
        try {
            var catalogTree = mapper.createObjectNode().set("publications", mapper.createArrayNode().add(publication));
            Files.write(path, mapper.writeValueAsBytes(catalogTree));
            var sourceBytes = mapper.writeValueAsBytes(mapper.createObjectNode().set("issues", mapper.createArrayNode().add(source)));
            var catalog = new IssueReadingCatalog(mapper, new org.springframework.core.io.FileSystemResource(path), new ByteArrayResource(sourceBytes));
            var client = clientFor(catalog);
            client.get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isOk();
            clearInvocations(knowledge);
            publication.put("state", "withdrawn");
            Files.write(path, mapper.writeValueAsBytes(catalogTree));
            client.get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isNotFound();
            verifyNoInteractions(knowledge);
        } finally { Files.deleteIfExists(path); }
    }

    @Test void upstreamFailureIsUnavailableAndNeverEmptySuccess() throws Exception {
        when(knowledge.evidence("test-evidence")).thenReturn(Mono.error(new IllegalStateException("private database detail")));
        client().get().uri("/api/v1/issues/test-issue/reading").exchange().expectStatus().isEqualTo(503)
                .expectBody().jsonPath("$.error").isEqualTo("reading_unavailable")
                .jsonPath("$.summary").doesNotExist();
    }

    @Test void productionCatalogDoesNotPublishTheRepresentativeCandidate() {
        var catalog = new IssueReadingCatalog(mapper, new ClassPathResource("knowledge/issue-readings.json"),
                new ClassPathResource("nonexistent-editorial-source.json"));
        var client = clientFor(catalog);
        client.get().uri("/api/v1/issues/child-support-advance/reading").exchange().expectStatus().isNotFound();
        verifyNoInteractions(knowledge);
    }

    WebTestClient client() throws Exception {
        var catalogBytes = mapper.writeValueAsBytes(mapper.createObjectNode().set("publications", mapper.createArrayNode().add(publication)));
        var sourceBytes = mapper.writeValueAsBytes(mapper.createObjectNode().set("issues", mapper.createArrayNode().add(source)));
        var catalog = new IssueReadingCatalog(mapper, new ByteArrayResource(catalogBytes), new ByteArrayResource(sourceBytes));
        return clientFor(catalog);
    }

    WebTestClient clientFor(IssueReadingCatalog catalog) {
        return WebTestClient.bindToController(new IssueReadingController(new IssueReadingReads(catalog, knowledge)))
                .httpMessageCodecs(codecs -> {
                    codecs.defaultCodecs().jackson2JsonEncoder(new org.springframework.http.codec.json.Jackson2JsonEncoder(mapper));
                    codecs.defaultCodecs().jackson2JsonDecoder(new org.springframework.http.codec.json.Jackson2JsonDecoder(mapper));
                }).build();
    }

    void sealPublication() throws Exception {
        var typed = mapper.treeToValue(publication, IssueReadingCatalog.Publication.class);
        var node = (ObjectNode) mapper.valueToTree(typed);
        node.remove(List.of("version", "state"));
        publication.put("version", "reading_" + HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(mapper.writeValueAsBytes(node))));
    }

    String sourceHash() throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(mapper.writeValueAsBytes(source)));
    }

    KnowledgeReads.PublicEvidence evidence(String version) {
        return new KnowledgeReads.PublicEvidence("test-evidence", "test-doc", version, "test-extract-v1",
                "test-segment", 0, 2, "근거", "", "", List.of(),
                "https://www.law.go.kr/test", "합성 원문", "page 1");
    }
}
