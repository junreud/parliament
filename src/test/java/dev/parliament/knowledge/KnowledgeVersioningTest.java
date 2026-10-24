package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.util.List;
import org.junit.jupiter.api.Test;
import static dev.parliament.knowledge.KnowledgeBatch.*;

class KnowledgeVersioningTest {
    private final KnowledgeVersioning versions=new KnowledgeVersioning(new ObjectMapper().registerModule(new JavaTimeModule()));
    @Test void pollingObservationDoesNotCreateAnActivityVersion() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");
        var d=b.documents().get(0);
        var polled=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                d.publishedAt(),d.collectedAt().plusSeconds(60),"raw/new-location.pdf",d.extractionVersion(),d.segments(),"new_observation",d.datePrecision());
        assertThat(version(KnowledgeFixtures.documents(b,List.of(polled)))).isEqualTo(version(b));
    }
    @Test void reviewedRolesAndRawTransitionsCreateNewVersions() {
        var pending=KnowledgeFixtures.batch("pending","pending","allowed");
        var approved=KnowledgeFixtures.batch("approved","approved","allowed");
        assertThat(version(approved)).isNotEqualTo(version(pending));
        var d=approved.documents().get(0);
        var returned=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),d.segments(),"return_observation",d.datePrecision(),"return_transition");
        assertThat(version(KnowledgeFixtures.documents(approved,List.of(returned)))).isNotEqualTo(version(approved));
    }
    @Test void changeKindsAndIssueMembershipArePartOfTheEventContextVersion() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");
        var c=b.contexts().get(0);
        var changed=new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),b.relations(),b.activities(),
                List.of(new Context(c.eventId(),c.eventVersion(),c.relationIds(),c.evidenceIds(),c.documentIds(),"explanation_only")));
        assertThat(version(changed)).isNotEqualTo(version(b));
        assertThat(version(new KnowledgeBatch(b.id(),"another-issue",b.entities(),b.documents(),b.evidence(),b.relations(),b.activities(),b.contexts())))
                .isNotEqualTo(version(b));
    }
    @Test void scheduleIsPreservedAndChangesVersionWithoutInventingOccurrence() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");var c=b.contexts().get(0);
        var schedule=KnowledgeFixtures.TIME.plusSeconds(7*86400);
        var planned=new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),b.relations(),b.activities(),
                List.of(new Context(c.eventId(),c.eventVersion(),c.relationIds(),c.evidenceIds(),c.documentIds(),c.changeKind(),schedule,"date")));
        var prepared=versions.prepare(planned);
        assertThat(prepared.contexts().get(0).scheduledAt()).isEqualTo(schedule);
        assertThat(prepared.activities().get(0).occurredAt()).isEqualTo(b.activities().get(0).occurredAt());
        assertThat(version(planned)).isNotEqualTo(version(b));
        new KnowledgePolicy().validate(prepared);
        var unknown=new Context(c.eventId(),c.eventVersion(),c.relationIds(),c.evidenceIds(),c.documentIds(),c.changeKind(),null,"unknown");
        assertThat(unknown.scheduledAt()).isNull();
        var invalid=new Context(c.eventId(),c.eventVersion(),c.relationIds(),c.evidenceIds(),c.documentIds(),c.changeKind(),schedule,"hour");
        assertThatThrownBy(()->new KnowledgePolicy().validate(new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),b.relations(),b.activities(),List.of(invalid))))
                .hasMessageContaining("scheduled precision");
    }
    private String version(KnowledgeBatch b) {return versions.prepare(b).activities().get(0).version();}
}
