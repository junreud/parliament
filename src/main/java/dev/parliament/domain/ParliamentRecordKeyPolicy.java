package dev.parliament.domain;

import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.util.TextUtil;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Row identities are source-specific; a bill ID alone cannot identify a vote. */
public final class ParliamentRecordKeyPolicy {
    private static final List<String> SIMPLE_IDS = List.of(
            "BILL_ID", "CONF_ID", "NAAS_CD", "MONA_CD", "PTT_ID", "BOARD_ID", "ID", "SEQ");
    private static final List<String> COMPOSITE_IDS = List.of(
            "BILL_ID", "BILL_NO", "CONF_ID", "NAAS_CD", "MONA_CD", "MEMBER_ID", "MEMBER_NO",
            "AGE", "VOTE_DATE", "VOTE_NO", "MEETING_ORD", "SESS", "SESS_NO", "RSESSION");

    public String key(ParliamentSourceDefinition source, Map<String, Object> row, String canonicalJson) {
        boolean multiRow = source.name().contains("표결") || source.name().contains("제안자")
                || source.name().contains("안건") || source.name().contains("회의록")
                || source.name().contains("회의별")
                || source.key().equals("billinfoppsr") || source.key().equals("billjudgeconf")
                || source.key().equals("billlwjudgeconf") || source.key().equals("vconfbilllist");
        if (multiRow) {
            Map<String, String> parts = new LinkedHashMap<>();
            for (String field : COMPOSITE_IDS) {
                if (row.get(field) != null && !row.get(field).toString().isBlank()) {
                    parts.put(field, row.get(field).toString().trim());
                }
            }
            // Without a member identifier and a vote session, preserve each payload rather
            // than silently collapse unknown row contracts into a bill-level identity.
            if (source.name().contains("표결") && (!hasMember(parts) || !hasSession(parts))) {
                return "unresolved:" + TextUtil.textSha1(source.variantKey() + ":" + canonicalJson);
            }
            if (parts.size() > 1) {
                StringBuilder identity = new StringBuilder(source.variantKey());
                parts.forEach((field, value) -> identity.append('|').append(field.length()).append(':')
                        .append(field).append('=').append(value.length()).append(':').append(value));
                return "composite-v2:" + TextUtil.textSha1(identity.toString());
            }
            return "unresolved:" + TextUtil.textSha1(source.variantKey() + ":" + canonicalJson);
        }
        for (String field : SIMPLE_IDS) {
            if (row.get(field) != null && !row.get(field).toString().isBlank()) {
                return row.get(field).toString().trim();
            }
        }
        return TextUtil.textSha1(source.apiCode() + ":" + source.variantKey() + ":" + canonicalJson);
    }

    private boolean hasMember(Map<String, String> values) {
        return List.of("NAAS_CD", "MONA_CD", "MEMBER_ID", "MEMBER_NO").stream().anyMatch(values::containsKey);
    }

    private boolean hasSession(Map<String, String> values) {
        return List.of("CONF_ID", "VOTE_DATE", "VOTE_NO", "MEETING_ORD", "SESS", "SESS_NO", "RSESSION")
                .stream().anyMatch(values::containsKey);
    }
}
