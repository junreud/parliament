package dev.parliament.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentParameterPlanCatalogTest {

    @Test
    void officialFailureSetIsCompletelyClassifiedAndParameterized() {
        ParliamentParameterPlanCatalog catalog = ParliamentParameterPlanCatalog.loadDefault(new ObjectMapper());

        assertThat(catalog.all()).hasSize(82);
        assertThat(catalog.all()).filteredOn(plan -> plan.status() == ParameterPlanStatus.PARAMETERIZED)
                .hasSize(72)
                .allSatisfy(plan -> assertThat(plan.bindings()).isNotEmpty());
        assertThat(catalog.all()).filteredOn(plan -> plan.status() == ParameterPlanStatus.EMPTY_ALLOWED)
                .hasSize(7);
        assertThat(catalog.all()).filteredOn(plan -> plan.status() == ParameterPlanStatus.RETRYABLE)
                .hasSize(3);
        assertThat(catalog.all()).noneMatch(plan -> plan.status() == ParameterPlanStatus.UNRESOLVED);

        assertThat(catalog.require("allbill").bindings())
                .singleElement()
                .satisfies(binding -> {
                    assertThat(binding.parameter()).isEqualTo("BILL_NO");
                    assertThat(binding.strategy()).isEqualTo(ParameterValueStrategy.SOURCE_FIELD);
                    assertThat(binding.sourceKey()).isEqualTo("billrcp");
                    assertThat(binding.sourceField()).isEqualTo("BILL_NO");
                });
        assertThat(catalog.require("vconfdetail").bindings())
                .singleElement()
                .satisfies(binding -> {
                    assertThat(binding.parameter()).isEqualTo("CONF_ID");
                    assertThat(binding.sourceKey()).isEqualTo("vconfbilllist");
                    assertThat(binding.sourceField()).isEqualTo("CONF_ID");
                });
        assertThat(catalog.require("nzbyfwhwaoanttzje").bindings())
                .extracting(ParliamentParameterBinding::parameter)
                .containsExactly("DAE_NUM", "CONF_DATE");
        assertThat(catalog.require("namemberevent").bindings())
                .singleElement()
                .satisfies(binding -> {
                    assertThat(binding.parameter()).isEqualTo("NAAS_CD");
                    assertThat(binding.sourceKey()).isEqualTo("nwvrqwxyaytdsfvhu");
                    assertThat(binding.sourceField()).isEqualTo("MONA_CD");
                });
    }
}
