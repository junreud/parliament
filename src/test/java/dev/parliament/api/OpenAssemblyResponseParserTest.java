package dev.parliament.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OpenAssemblyResponseParserTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final OpenAssemblyResponseParser parser = new OpenAssemblyResponseParser();

    @Test
    void parsesHeadAndRowsFromHttp200Response() throws Exception {
        var body = objectMapper.readTree("""
                {"ALLSCHEDULE":[
                  {"head":[{"list_total_count":2},{"RESULT":{"CODE":"INFO-000","MESSAGE":"정상 처리되었습니다."}}]},
                  {"row":[{"CONF_ID":"c1"},{"CONF_ID":"c2"}]}
                ]}
                """);

        OpenAssemblyPage page = parser.parse("ALLSCHEDULE", body);

        assertThat(page.totalCount()).isEqualTo(2);
        assertThat(page.rows()).hasSize(2);
        assertThat(page.rows().get(0).get("CONF_ID")).isEqualTo("c1");
    }

    @Test
    void rejectsApplicationErrorReturnedWithHttp200() throws Exception {
        var body = objectMapper.readTree("""
                {"RESULT":{"CODE":"ERROR-290","MESSAGE":"인증키가 유효하지 않습니다."}}
                """);

        assertThatThrownBy(() -> parser.parse("ALLSCHEDULE", body))
                .isInstanceOf(OpenAssemblyApiException.class)
                .hasMessageContaining("ERROR-290")
                .hasMessageNotContaining("sample-key");
    }

    @Test
    void treatsTheOfficialNoDataCodeAsAnEmptySuccessfulPage() throws Exception {
        var body = objectMapper.readTree("""
                {"RESULT":{"CODE":"INFO-200","MESSAGE":"해당하는 데이터가 없습니다."}}
                """);

        OpenAssemblyPage page = parser.parse("EMPTY_SOURCE", body);

        assertThat(page.totalCount()).isZero();
        assertThat(page.rows()).isEmpty();
    }
}
