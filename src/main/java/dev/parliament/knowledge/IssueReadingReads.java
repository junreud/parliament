package dev.parliament.knowledge;

import static dev.parliament.knowledge.IssueReadingCatalog.*;

import java.time.Duration;
import java.util.*;
import java.util.function.UnaryOperator;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

/** Combines immutable editorial coordinates with freshly authorized public reads only. */
public final class IssueReadingReads {
    public record Block(String id, String kind, String text, String date, String title,
            List<String> evidenceIds, List<String> personIds) {}
    public record Person(String id, String name, List<String> evidenceIds) {}
    public record Update(String date, String note) {}
    public record Reading(String schema, String issueId, String editorialId, String editorialVersion,
            String version, String publicationState, String reviewedAt, String publishedAt,
            String checkedAt, String title, String summary, List<String> summaryEvidenceIds,
            String currentStage, List<String> stageEvidenceIds, String nextTrigger, String coverage, List<Block> blocks,
            List<Person> people, List<KnowledgeReads.PublicEvidence> evidence,
            List<KnowledgeReads.PublicContext> contexts, List<Update> updates) {}
    private final IssueReadingCatalog catalog;
    private final KnowledgeReads knowledge;
    private final UnaryOperator<Mono<Reading>> snapshot;

    public IssueReadingReads(IssueReadingCatalog catalog, KnowledgeReads knowledge) {
        this(catalog, knowledge, UnaryOperator.identity());
    }
    public IssueReadingReads(IssueReadingCatalog catalog, KnowledgeReads knowledge,
            UnaryOperator<Mono<Reading>> snapshot) {
        this.catalog = catalog;
        this.knowledge = knowledge;
        this.snapshot = snapshot;
    }

    public Mono<Reading> read(String issueId) {
        // Resource I/O runs off the event loop. The public DB reads share one repeatable snapshot.
        return Mono.fromCallable(() -> catalog.find(issueId)).subscribeOn(Schedulers.boundedElastic())
                .flatMap(prepared -> snapshot.apply(Mono.defer(() -> assemble(prepared))))
                .timeout(Duration.ofSeconds(8))
                .onErrorMap(error -> error instanceof ResponseStatusException ? error
                        : new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE));
    }

    private Mono<Reading> assemble(Prepared prepared) {
        var p = prepared.publication();
        var contexts = Flux.fromIterable(p.contexts()).concatMap(pin -> knowledge.context(pin.eventId(), pin.eventVersion())
                .switchIfEmpty(Mono.error(missing())).doOnNext(c -> check(c.eventId().equals(pin.eventId())
                        && c.eventVersion().equals(pin.eventVersion())))).collectList();
        var evidence = Flux.fromIterable(p.evidence()).concatMap(pin -> knowledge.evidence(pin.id())
                .switchIfEmpty(Mono.error(missing())).doOnNext(e -> check(matches(pin, e)))).collectList();
        var people = Flux.fromIterable(p.people()).concatMap(pin -> knowledge.profile(pin.id())
                .switchIfEmpty(Mono.error(missing())).map(profile -> {
                    check(pin.id().equals(profile.id()) && "person".equals(profile.kind()));
                    check(pin.evidenceIds() != null && !pin.evidenceIds().isEmpty());
                    return new Person(profile.id(), profile.name(), pin.evidenceIds());
                })).collectList();
        return Mono.zip(contexts, evidence, people).map(parts -> {
            var cs = parts.getT1();
            var es = parts.getT2();
            var ps = parts.getT3();
            var evidenceIds = new HashSet<String>();
            for (var e : es) {
                check(evidenceIds.add(e.id()));
                check(cs.stream().flatMap(c -> c.evidence().stream()).anyMatch(inContext -> same(e, inContext)));
            }
            var personIds = new HashSet<String>();
            for (var person : ps) {
                check(personIds.add(person.id()) && evidenceIds.containsAll(person.evidenceIds()));
                check(cs.stream().flatMap(c -> c.participants().stream()).anyMatch(actor ->
                        person.id().equals(actor.personId()) && actor.evidenceIds().containsAll(person.evidenceIds())));
                check(cs.stream().anyMatch(c -> c.activity() != null && c.relations().stream().anyMatch(role ->
                        "approved".equals(role.decision()) && person.id().equals(role.subjectId())
                                && Set.of("lead_sponsor", "co_sponsor", "speaker", "voter", "scheduled_participant").contains(role.type())
                                && (role.objectId().equals(c.eventId()) || role.objectId().equals(c.activity().billId()))
                                && role.evidenceIds().containsAll(person.evidenceIds()))));
            }
            check(evidenceIds.containsAll(p.summaryEvidenceIds()) && evidenceIds.containsAll(p.stageEvidenceIds()));
            for (var block : prepared.blocks()) {
                check(evidenceIds.containsAll(block.evidenceIds()) && personIds.containsAll(block.personIds()));
                for (String person : block.personIds()) check(ps.stream().anyMatch(candidate ->
                        candidate.id().equals(person) && !Collections.disjoint(candidate.evidenceIds(), block.evidenceIds())));
            }
            var e = prepared.editorial();
            var updates = new ArrayList<Update>();
            for (var update : e.path("updates"))
                updates.add(new Update(update.path("date").asText(), update.path("note").asText()));
            return new Reading("issue-reading-v1", p.issueId(), p.editorialId(), p.editorialVersion(), p.version(),
                    "published", p.reviewedAt(), p.publishedAt(), e.path("checkedAt").asText(), e.path("title").asText(),
                    e.path("summary").asText(), p.summaryEvidenceIds(), e.path("currentStage").asText(),
                    p.stageEvidenceIds(), e.path("nextTrigger").asText(), e.path("coverage").isTextual()
                            ? e.path("coverage").asText() : null, prepared.blocks(), ps, es, cs, List.copyOf(updates));
        });
    }

    private static boolean matches(EvidencePin pin, KnowledgeReads.PublicEvidence e) {
        return Objects.equals(pin.id(), e.id()) && Objects.equals(pin.documentId(), e.documentId())
                && Objects.equals(pin.documentVersion(), e.documentVersion())
                && Objects.equals(pin.extractionVersion(), e.extractionVersion())
                && Objects.equals(pin.segmentId(), e.segmentId()) && pin.start() == e.start() && pin.end() == e.end();
    }
    private static boolean same(KnowledgeReads.PublicEvidence left, KnowledgeReads.PublicEvidence right) {
        return matches(new EvidencePin(left.id(), left.documentId(), left.documentVersion(), left.extractionVersion(),
                left.segmentId(), left.start(), left.end()), right) && Objects.equals(left.excerpt(), right.excerpt());
    }
}
