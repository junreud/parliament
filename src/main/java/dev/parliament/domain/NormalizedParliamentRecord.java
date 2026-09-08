package dev.parliament.domain;

import java.util.List;

public record NormalizedParliamentRecord(
        String recordKey,
        String payloadHash,
        String rawJson,
        List<PersonCandidate> people
) {
}

