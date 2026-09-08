package dev.parliament.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentSourceCatalogTest {

    @Test
    void catalogIncludesCorePublicDataAndNeverActivatesVideoSources() {
        ParliamentSourceCatalog catalog = ParliamentSourceCatalog.loadDefault(new ObjectMapper());

        assertThat(catalog.all()).hasSizeGreaterThanOrEqualTo(270);
        assertThat(catalog.active()).extracting(ParliamentSourceDefinition::apiCode)
                .contains("ALLNAMEMBER", "ALLSCHEDULE", "ALLBILL", "OPENSRVAPI");
        assertThat(catalog.active())
                .noneMatch(source -> source.mediaType() == ParliamentMediaType.VIDEO);
        assertThat(catalog.all())
                .filteredOn(source -> source.mediaType() == ParliamentMediaType.VIDEO)
                .allMatch(source -> source.collectionMode() == ParliamentCollectionMode.EXCLUDED);
        assertThat(catalog.all()).extracting(ParliamentSourceDefinition::apiCode)
                .doesNotHaveDuplicates();
    }
}

