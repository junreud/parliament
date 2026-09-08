package dev.parliament.domain;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.util.TextUtil;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;

public class ParliamentRecordNormalizer {
    private static final List<String> RECORD_ID_FIELDS = List.of(
            "BILL_ID", "CONF_ID", "NAAS_CD", "MONA_CD", "PTT_ID", "BOARD_ID", "ID", "SEQ"
    );
    private static final List<String> PERSON_NAME_FIELDS = List.of(
            "NAAS_NM", "HG_NM", "MEMBER_NAME", "MEM_NM", "SPEAKER_NM", "CHAIR_NM",
            "CANDIDATE_NM", "NOMINEE_NM", "PERSON_NM"
    );
    private static final List<String> PERSON_ID_FIELDS = List.of("NAAS_CD", "MONA_CD", "MEMBER_ID");
    private static final List<String> POSITION_FIELDS = List.of("JOB_TITLE", "POSITION", "OFFICE", "ROLE", "TITLE");
    private static final List<String> ORGANIZATION_FIELDS = List.of(
            "DEPT_NM", "ORG_NM", "PLPT_NM", "BLNG_CMIT_NM", "CMIT_NM", "COMMITTEE_NAME", "PARTY_NAME"
    );

    private final ObjectMapper objectMapper;
    private final ParliamentPersonClassifier classifier;
    private final ParliamentSocialAccountMapper socialAccountMapper;

    public ParliamentRecordNormalizer(ObjectMapper objectMapper) {
        this(objectMapper, new ParliamentPersonClassifier(), new ParliamentSocialAccountMapper());
    }

    ParliamentRecordNormalizer(
            ObjectMapper objectMapper,
            ParliamentPersonClassifier classifier,
            ParliamentSocialAccountMapper socialAccountMapper
    ) {
        this.objectMapper = objectMapper;
        this.classifier = classifier;
        this.socialAccountMapper = socialAccountMapper;
    }

    public NormalizedParliamentRecord normalize(ParliamentSourceDefinition source, Map<String, Object> row) {
        try {
            String rawJson = objectMapper.writeValueAsString(row);
            String recordKey = firstValue(row, RECORD_ID_FIELDS);
            if (recordKey == null) {
                recordKey = TextUtil.textSha1(source.apiCode() + ":" + rawJson);
            }
            List<PersonCandidate> people = extractPeople(source, row);
            return new NormalizedParliamentRecord(
                    recordKey,
                    TextUtil.textSha1(rawJson),
                    rawJson,
                    people
            );
        } catch (JsonProcessingException error) {
            throw new IllegalArgumentException("failed to serialize parliament row", error);
        }
    }

    private List<PersonCandidate> extractPeople(ParliamentSourceDefinition source, Map<String, Object> row) {
        String sourcePersonId = firstValue(row, PERSON_ID_FIELDS);
        String position = firstValue(row, POSITION_FIELDS);
        String organization = firstValue(row, ORGANIZATION_FIELDS);
        boolean integratedMemberSource = source.apiCode().equals("ALLNAMEMBER");
        if (position == null && integratedMemberSource) {
            position = "국회의원";
        }
        boolean memberSource = integratedMemberSource
                || source.name().contains("국회의원")
                || sourcePersonId != null;
        List<PersonCandidate> people = new ArrayList<>();
        List<SocialAccount> socialAccounts = socialAccountMapper.map(row);
        for (String field : PERSON_NAME_FIELDS) {
            String name = value(row.get(field));
            if (name != null) {
                people.add(classifier.classify(name, sourcePersonId, position, organization, memberSource));
            }
        }
        if (!socialAccounts.isEmpty() && people.isEmpty()) {
            String name = firstValue(row, List.of("NAME", "HG_NM"));
            if (name != null) {
                people.add(classifier.classify(name, sourcePersonId, position, organization, memberSource));
            }
        }
        List<PersonCandidate> uniquePeople = people.stream()
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        if (uniquePeople.size() == 1) {
            return List.of(uniquePeople.get(0).withSocialAccounts(socialAccounts));
        }
        return uniquePeople;
    }

    private String firstValue(Map<String, Object> row, List<String> fields) {
        for (String field : fields) {
            String value = value(row.get(field));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private String value(Object value) {
        if (value == null || value.toString().isBlank()) {
            return null;
        }
        return value.toString().trim();
    }
}
