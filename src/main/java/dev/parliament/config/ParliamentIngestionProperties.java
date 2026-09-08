package dev.parliament.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "parliament.ingestion")
public class ParliamentIngestionProperties {
    private boolean enabled;
    private boolean writeEnabled;
    private String apiKey;
    private String adminKey;
    private int maxPageSize = 100;
    private int maxPagesPerRun = 1000;
    private String baseUrl = "https://open.assembly.go.kr/portal/openapi";

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public boolean isWriteEnabled() { return writeEnabled; }
    public void setWriteEnabled(boolean writeEnabled) { this.writeEnabled = writeEnabled; }
    public String getApiKey() { return apiKey; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public String getAdminKey() { return adminKey; }
    public void setAdminKey(String adminKey) { this.adminKey = adminKey; }
    public int getMaxPageSize() { return maxPageSize; }
    public void setMaxPageSize(int maxPageSize) { this.maxPageSize = maxPageSize; }
    public int getMaxPagesPerRun() { return maxPagesPerRun; }
    public void setMaxPagesPerRun(int maxPagesPerRun) { this.maxPagesPerRun = maxPagesPerRun; }
    public String getBaseUrl() { return baseUrl; }
    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
}
