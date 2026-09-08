package dev.parliament.service;

public record ParliamentSourceReport(
        String sourceKey,
        String apiCode,
        int records,
        int people,
        int pages,
        boolean complete,
        ParliamentSourceStatus status,
        String message
) {
    public static ParliamentSourceReport failed(String sourceKey, String apiCode, Throwable error) {
        String message = error instanceof dev.parliament.api.OpenAssemblyApiException
                ? error.getMessage()
                : "source request failed: " + error.getClass().getSimpleName();
        return new ParliamentSourceReport(sourceKey, apiCode, 0, 0, 0,
                false, ParliamentSourceStatus.FAILED, message);
    }
}
