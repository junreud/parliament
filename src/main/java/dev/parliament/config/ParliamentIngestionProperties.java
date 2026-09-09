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
    private int currentAssemblyNumber = 22;
    private boolean automaticEnabled;
    private String incrementalCron = "0 0 4 * * *";
    private String incrementalZone = "Asia/Seoul";
    private int incrementalPageSize = 100;
    private int incrementalMaxPages = 1000;
    private boolean socialVerificationEnabled = true;
    private int socialVerificationMaxAgeDays = 7;
    private int socialVerificationBatchSize = 200;
    private String baseUrl = "https://open.assembly.go.kr/portal/openapi";
    private String caCertificatePath;

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
    public int getCurrentAssemblyNumber() { return currentAssemblyNumber; }
    public void setCurrentAssemblyNumber(int currentAssemblyNumber) {
        if (currentAssemblyNumber < 1 || currentAssemblyNumber > 99) {
            throw new IllegalArgumentException("currentAssemblyNumber must be between 1 and 99");
        }
        this.currentAssemblyNumber = currentAssemblyNumber;
    }
    public String getBaseUrl() { return baseUrl; }
    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
    public String getCaCertificatePath() { return caCertificatePath; }
    public void setCaCertificatePath(String caCertificatePath) { this.caCertificatePath = caCertificatePath; }
    public boolean isAutomaticEnabled() { return automaticEnabled; }
    public void setAutomaticEnabled(boolean automaticEnabled) { this.automaticEnabled = automaticEnabled; }
    public String getIncrementalCron() { return incrementalCron; }
    public void setIncrementalCron(String incrementalCron) {
        if (incrementalCron == null || incrementalCron.isBlank()) {
            throw new IllegalArgumentException("incrementalCron is required");
        }
        this.incrementalCron = incrementalCron;
    }
    public String getIncrementalZone() { return incrementalZone; }
    public void setIncrementalZone(String incrementalZone) {
        if (incrementalZone == null || incrementalZone.isBlank()) {
            throw new IllegalArgumentException("incrementalZone is required");
        }
        this.incrementalZone = incrementalZone;
    }
    public int getIncrementalPageSize() { return incrementalPageSize; }
    public void setIncrementalPageSize(int incrementalPageSize) {
        if (incrementalPageSize < 1) throw new IllegalArgumentException("incrementalPageSize must be positive");
        this.incrementalPageSize = incrementalPageSize;
    }
    public int getIncrementalMaxPages() { return incrementalMaxPages; }
    public void setIncrementalMaxPages(int incrementalMaxPages) {
        if (incrementalMaxPages < 1) throw new IllegalArgumentException("incrementalMaxPages must be positive");
        this.incrementalMaxPages = incrementalMaxPages;
    }
    public boolean isSocialVerificationEnabled() { return socialVerificationEnabled; }
    public void setSocialVerificationEnabled(boolean socialVerificationEnabled) {
        this.socialVerificationEnabled = socialVerificationEnabled;
    }
    public int getSocialVerificationMaxAgeDays() { return socialVerificationMaxAgeDays; }
    public void setSocialVerificationMaxAgeDays(int socialVerificationMaxAgeDays) {
        if (socialVerificationMaxAgeDays < 1) {
            throw new IllegalArgumentException("socialVerificationMaxAgeDays must be positive");
        }
        this.socialVerificationMaxAgeDays = socialVerificationMaxAgeDays;
    }
    public int getSocialVerificationBatchSize() { return socialVerificationBatchSize; }
    public void setSocialVerificationBatchSize(int socialVerificationBatchSize) {
        if (socialVerificationBatchSize < 1 || socialVerificationBatchSize > 10_000) {
            throw new IllegalArgumentException("socialVerificationBatchSize must be between 1 and 10000");
        }
        this.socialVerificationBatchSize = socialVerificationBatchSize;
    }
}
