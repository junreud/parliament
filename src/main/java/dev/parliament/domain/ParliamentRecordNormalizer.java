package dev.parliament.domain;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.util.TextUtil;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;

public class ParliamentRecordNormalizer {
    private static final String OFFICIAL_SNS_DIRECTORY_SOURCE = "negnlnyvatsjwocar";
    private static final List<String> PERSON_NAME_FIELDS = List.of(
            "NAAS_NM", "HG_NM", "MEMBER_NAME", "MEM_NM", "SPEAKER_NM", "CHAIR_NM",
            "CANDIDATE_NM", "NOMINEE_NM", "PERSON_NM"
    );
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
        this.objectMapper = objectMapper.copy().enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
        this.classifier = classifier;
        this.socialAccountMapper = socialAccountMapper;
    }

    public NormalizedParliamentRecord normalize(ParliamentSourceDefinition source, Map<String, Object> row) {
        try {
            String rawJson = objectMapper.writeValueAsString(row);
            String recordKey = new ParliamentRecordKeyPolicy().key(source, row, rawJson);
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
        String position = firstValue(row, POSITION_FIELDS);
        String organization = firstValue(row, ORGANIZATION_FIELDS);
        boolean integratedMemberSource = source.apiCode().equals("ALLNAMEMBER");
        if (position == null && integratedMemberSource) {
            position = "국회의원";
        }
        boolean memberSource = integratedMemberSource || source.name().contains("국회의원");
        boolean rosterSource = integratedMemberSource || "nwvrqwxyaytdsfvhu".equals(source.key());
        String naasName = value(row.get("NAAS_NM"));
        String monaName = value(row.get("HG_NM"));
        String naasId = value(row.get("NAAS_CD"));
        String monaId = value(row.get("MONA_CD"));
        boolean naasPrimary = memberSource && naasId != null && naasName != null;
        boolean monaPrimary = !naasPrimary && memberSource && monaId != null && monaName != null;
        String primaryField = naasPrimary ? "NAAS_NM" : monaPrimary ? "HG_NM" : null;
        String primaryId = naasPrimary ? naasId : monaPrimary ? monaId : null;
        String primaryNamespace = naasPrimary ? PersonCandidate.NAAS_NAMESPACE
                : monaPrimary ? PersonCandidate.MONA_NAMESPACE : null;
        boolean aliasVerified = rosterSource && naasPrimary && monaId != null && monaName != null
                && canonicalName(naasName).equals(canonicalName(monaName));
        List<PersonCandidate.ExternalIdentifier> aliases = aliasVerified
                ? List.of(new PersonCandidate.ExternalIdentifier(PersonCandidate.MONA_NAMESPACE, monaId))
                : List.of();
        List<PersonCandidate> people = new ArrayList<>();
        List<SocialAccount> socialAccounts = socialAccountMapper.map(
                row, OFFICIAL_SNS_DIRECTORY_SOURCE.equals(source.key()));
        for (String field : PERSON_NAME_FIELDS) {
            String name = value(row.get(field));
            if (name != null) {
                if (aliasVerified && "HG_NM".equals(field)) {
                    continue;
                }
                boolean primary = field.equals(primaryField);
                people.add(classifier.classify(name, primary ? primaryId : null,
                        primary ? primaryNamespace : null,
                        position, organization, primary, primary ? aliases : List.of()));
            }
        }
        if (!socialAccounts.isEmpty() && people.isEmpty()) {
            String name = firstValue(row, List.of("NAME", "HG_NM"));
            if (name != null) {
                people.add(classifier.classify(name, null, null, position, organization, false, List.of()));
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

    private String canonicalName(String name) {
        return Normalizer.normalize(name, Normalizer.Form.NFKC).replaceAll("\\s+", "").trim();
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
