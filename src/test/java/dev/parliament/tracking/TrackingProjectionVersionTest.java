package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

class TrackingProjectionVersionTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final Instant observed = Instant.parse("2026-10-07T01:00:00Z");

    @Test
    void sameRawWithRevisedStageMappingCreatesDerivedVersionAndPreservesSourceHash()
            throws Exception {
        var first =
                project(
                        billContract(Map.of("접수", "proposed"), null, List.of("housing"), 20, null),
                        List.of());
        var replay =
                project(
                        billContract(Map.of("접수", "proposed"), null, List.of("housing"), 20, null),
                        List.of());
        var corrected =
                project(
                        billContract(Map.of("접수", "reviewing"), null, List.of("housing"), 20, null),
                        List.of());
        assertThat(replay.version()).isEqualTo(first.version());
        assertThat(corrected.id()).isEqualTo(first.id());
        assertThat(corrected.version()).isNotEqualTo(first.version());
        assertThat(corrected.evidence().get(0).sourceVersion()).isEqualTo("same-raw-hash");
    }

    @Test
    void namespaceAndFieldContractAndTopicChangesProduceNewVersionEvenIfRawIsUnchanged()
            throws Exception {
        var firstContract =
                billContract(
                        Map.of("접수", "proposed"),
                        "OPEN_ASSEMBLY_NAAS_CD",
                        List.of("housing"),
                        20,
                        null);
        var first =
                project(firstContract, List.of(new TrackingProjection.PersonRef("p_one", "표본 인물")));
        var namespace =
                project(
                        billContract(
                                Map.of("접수", "proposed"),
                                "OPEN_ASSEMBLY_MONA_CD",
                                List.of("housing"),
                                20,
                                null),
                        List.of(new TrackingProjection.PersonRef("p_one", "표본 인물")));
        var person =
                project(firstContract, List.of(new TrackingProjection.PersonRef("p_two", "표본 인물")));
        var topic =
                project(
                        billContract(
                                Map.of("접수", "proposed"),
                                "OPEN_ASSEMBLY_NAAS_CD",
                                List.of("labor"),
                                20,
                                null),
                        List.of(new TrackingProjection.PersonRef("p_one", "표본 인물")));
        var fields = new java.util.HashMap<>(firstContract.fields());
        fields.put("title", "ALTERNATE_TITLE");
        var fieldContract =
                new TrackingProjection.Contract(
                        firstContract.sourceKey(),
                        firstContract.kind(),
                        true,
                        fields,
                        firstContract.stageMap(),
                        firstContract.voteMap(),
                        firstContract.personNamespace(),
                        firstContract.topics(),
                        20,
                        null);
        var field =
                project(fieldContract, List.of(new TrackingProjection.PersonRef("p_one", "표본 인물")));
        assertThat(List.of(namespace.version(), person.version(), topic.version(), field.version()))
                .doesNotContain(first.version());
    }

    @Test
    void cursorLimitCollectionOrderingAndPublicMetadataDoNotCreateVersionNoise() throws Exception {
        var contract =
                billContract(Map.of("접수", "proposed"), null, List.of("housing", "labor"), 20, null);
        var first =
                project(
                        contract,
                        List.of(
                                new TrackingProjection.PersonRef("p_two", "둘"),
                                new TrackingProjection.PersonRef("p_one", "하나")));
        var paginated =
                project(
                        billContract(
                                Map.of("접수", "proposed"),
                                null,
                                List.of("labor", "housing"),
                                100,
                                "different-page"),
                        List.of(
                                new TrackingProjection.PersonRef("p_one", "하나"),
                                new TrackingProjection.PersonRef("p_two", "둘")));
        assertThat(paginated).isEqualTo(first);
        var publicCopy = first.visible(observed.plusSeconds(60), true);
        var reprojection =
                TrackingProjectionVersion.derive(
                        publicCopy, TrackingProjectionVersion.ROW_REVISION, contract, List.of());
        assertThat(reprojection.version()).isEqualTo(first.version());
        assertThat(reprojection.corrected()).isFalse();
        assertThat(reprojection.changedAt()).isNull();
        assertThat(
                        TrackingProjectionVersion.derive(
                                        first,
                                        TrackingProjectionVersion.ROW_REVISION + "-updated",
                                        contract,
                                        List.of())
                                .version())
                .isNotEqualTo(first.version());
    }

    @Test
    void groupedVotesChangeVersionWhenDerivedVoteMappingChangesAndRetainRawEvidence() {
        var unknown =
                TrackingPolicyTest.activity("https://open.assembly.go.kr/x", "row=1", "unknown");
        var yes = TrackingPolicyTest.activity("https://open.assembly.go.kr/x", "row=1", "yes");
        var first = TrackingVoteProjection.combine("source", "bill", "session", List.of(unknown));
        var revised = TrackingVoteProjection.combine("source", "bill", "session", List.of(yes));
        assertThat(revised.id()).isEqualTo(first.id());
        assertThat(revised.version()).isNotEqualTo(first.version());
        assertThat(revised.evidence()).isEqualTo(first.evidence());
        assertThat(TrackingVoteProjection.combine("source", "bill", "session", List.of(yes)))
                .isEqualTo(revised);
    }

    @Test
    void groupedVotesIncludeMemberProjectionProvenanceWhenPublicFieldsAreEqual() throws Exception {
        var first =
                project(
                        voteContract("OPEN_ASSEMBLY_NAAS_CD"),
                        List.of(new TrackingProjection.PersonRef("p_one", "표본 인물")));
        var revised =
                project(
                        voteContract("OPEN_ASSEMBLY_MONA_CD"),
                        List.of(new TrackingProjection.PersonRef("p_one", "표본 인물")));
        var groupFirst =
                TrackingVoteProjection.combine("source", "bill", "session", List.of(first));
        var groupRevised =
                TrackingVoteProjection.combine("source", "bill", "session", List.of(revised));
        assertThat(groupRevised.version()).isNotEqualTo(groupFirst.version());
        assertThat(groupRevised.evidence()).isEqualTo(groupFirst.evidence());
    }

    private Activity project(
            TrackingProjection.Contract contract, List<TrackingProjection.PersonRef> people)
            throws Exception {
        JsonNode raw =
                mapper.readTree(
                        "{\"BILL_ID\":\"B1\",\"BILL_NAME\":\"표본 법안\",\"ALTERNATE_TITLE\":\"표본"
                            + " 법안\",\"LINK_URL\":\"https://likms.assembly.go.kr/bill/billDetail.do?billId=B1\",\"PROPOSE_DT\":\"2026-10-01\",\"PROC_RESULT\":\"접수\",\"SESSION\":\"s1\",\"RESULT\":\"찬성\",\"MEMBER\":\"m1\"}");
        return TrackingProjection.toActivity(
                contract, "r1", "same-raw-hash", raw, observed, people);
    }

    private static TrackingProjection.Contract voteContract(String namespace) {
        return new TrackingProjection.Contract(
                "votes",
                "vote",
                true,
                Map.of(
                        "id",
                        "BILL_ID",
                        "title",
                        "BILL_NAME",
                        "url",
                        "LINK_URL",
                        "publishedAt",
                        "PROPOSE_DT",
                        "billId",
                        "BILL_ID",
                        "personId",
                        "MEMBER",
                        "sessionId",
                        "SESSION",
                        "voteResult",
                        "RESULT"),
                Map.of(),
                Map.of("찬성", "yes"),
                namespace,
                List.of("housing"),
                20);
    }

    private static TrackingProjection.Contract billContract(
            Map<String, String> stageMap,
            String namespace,
            List<String> topics,
            int limit,
            String cursor) {
        return new TrackingProjection.Contract(
                "bills",
                "bill",
                true,
                Map.of(
                        "id",
                        "BILL_ID",
                        "title",
                        "BILL_NAME",
                        "url",
                        "LINK_URL",
                        "publishedAt",
                        "PROPOSE_DT",
                        "stage",
                        "PROC_RESULT"),
                stageMap,
                Map.of(),
                namespace,
                topics,
                limit,
                cursor);
    }
}
