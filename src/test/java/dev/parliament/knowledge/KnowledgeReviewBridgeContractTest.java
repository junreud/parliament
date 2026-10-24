package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

/** Opt-in contract check for a privately generated GraphRAG review packet. */
class KnowledgeReviewBridgeContractTest {
    @Test
    void generatedReviewPacketRespectsTheJavaInputAndPublicationBoundary() throws Exception {
        String filename = System.getenv("KNOWLEDGE_REVIEW_BATCH");
        Assumptions.assumeTrue(filename != null && !filename.isBlank());

        ObjectMapper mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        KnowledgeJson json = new KnowledgeJson(mapper);
        KnowledgeBatch batch = json.read(Files.readString(Path.of(filename)), KnowledgeBatch.class);
        new KnowledgePolicy().validate(batch);
        KnowledgeBatch prepared = new KnowledgeVersioning(mapper).prepare(batch);
        KnowledgePolicy policy = new KnowledgePolicy();
        policy.validate(prepared);
        assertThatThrownBy(() -> policy.validatePublication(prepared))
                .isInstanceOf(IllegalArgumentException.class);

        assertThat(prepared.relations()).filteredOn(relation -> relation.id().startsWith("relation_gr_"))
                .isNotEmpty().allSatisfy(relation -> {
                    assertThat(relation.type()).isEqualTo("concerns");
                    assertThat(relation.decision()).isEqualTo("pending");
                    assertThat(relation.evidenceIds()).isNotEmpty();
                });
        assertThat(prepared.evidence()).filteredOn(evidence -> evidence.id().startsWith("evidence_gr_"))
                .isNotEmpty();
    }
}
