package dev.parliament.beta;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import static org.assertj.core.api.Assertions.*;

class BetaConfigurationTest {
    @Test
    void betaDefaultsOffEvenWhenTrackingEnabled() {
        new ApplicationContextRunner().withUserConfiguration(BetaConfiguration.class, BetaController.class)
                .withPropertyValues("tracking.enabled=true")
                .run(context -> assertThat(context).doesNotHaveBean(BetaRepository.class).doesNotHaveBean(BetaController.class));
    }
    @Test
    void retentionSurvivesDisabledAdmissionWithoutCreatingPublicBetaBeans() {
        new ApplicationContextRunner()
                .withBean(org.springframework.r2dbc.core.DatabaseClient.class,
                        () -> org.mockito.Mockito.mock(org.springframework.r2dbc.core.DatabaseClient.class))
                .withUserConfiguration(BetaConfiguration.class, BetaController.class, BetaRetentionConfiguration.class)
                .withPropertyValues("beta.enabled=false")
                .run(context -> assertThat(context).hasSingleBean(BetaHousekeeping.class)
                        .hasSingleBean(BetaRetention.class).doesNotHaveBean(BetaRepository.class)
                        .doesNotHaveBean(BetaController.class));
    }
}
