package dev.parliament.persistence;

import dev.parliament.domain.PersonCandidate;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

/** Exact source IDs are never guessed from names or silently reassigned. Used inside the page transaction. */
final class ParliamentPersonIdentifierRepository {
    private final DatabaseClient db;

    ParliamentPersonIdentifierRepository(DatabaseClient db) {
        this.db = db;
    }

    Mono<PersonCandidate> resolve(PersonCandidate candidate) {
        return Flux.fromIterable(candidate.identifiers())
                .concatMap(this::findIdentity)
                .distinct()
                .collectList()
                .flatMap(identities -> {
                    if (identities.size() > 1) {
                        return Mono.error(new IllegalStateException("conflicting person identifiers; verified rebuild required"));
                    }
                    return Mono.just(identities.isEmpty() ? candidate : candidate.withIdentityKey(identities.get(0)));
                });
    }

    Mono<Void> register(PersonCandidate person, String sourceKey, String recordKey) {
        return Flux.fromIterable(person.identifiers()).concatMap(identifier -> db.sql("""
                        INSERT IGNORE INTO parliament_person_identifier
                          (identifier_namespace, external_id, identity_key, evidence_source_key, evidence_record_key)
                        VALUES (:namespace, :externalId, :identityKey, :sourceKey, :recordKey)
                        """)
                .bind("namespace", identifier.namespace())
                .bind("externalId", identifier.externalId())
                .bind("identityKey", person.identityKey())
                .bind("sourceKey", sourceKey)
                .bind("recordKey", recordKey)
                .fetch().rowsUpdated()
                .then(findIdentity(identifier))
                .filter(person.identityKey()::equals)
                .switchIfEmpty(Mono.error(new IllegalStateException("conflicting person identifiers; registration refused")))
                .then()).then();
    }

    private Mono<String> findIdentity(PersonCandidate.ExternalIdentifier identifier) {
        return db.sql("""
                        SELECT identity_key FROM parliament_person_identifier
                        WHERE identifier_namespace = :namespace AND external_id = :externalId
                        FOR UPDATE
                        """)
                .bind("namespace", identifier.namespace())
                .bind("externalId", identifier.externalId())
                .map((row, metadata) -> row.get("identity_key", String.class))
                .one();
    }
}
