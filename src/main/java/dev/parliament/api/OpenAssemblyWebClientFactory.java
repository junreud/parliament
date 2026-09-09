package dev.parliament.api;

import dev.parliament.config.ParliamentIngestionProperties;
import io.netty.handler.ssl.SslContextBuilder;
import io.netty.handler.ssl.SslContext;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;
import java.io.File;
import java.io.FileInputStream;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.List;

public class OpenAssemblyWebClientFactory {

    public WebClient create(WebClient.Builder builder, ParliamentIngestionProperties properties) {
        String certificatePath = properties.getCaCertificatePath();
        if (certificatePath == null || certificatePath.isBlank()) {
            return builder.build();
        }
        File certificate = new File(certificatePath);
        if (!certificate.isFile()) {
            throw new IllegalArgumentException("Open Assembly CA certificate file does not exist");
        }
        try {
            SslContext sslContext = SslContextBuilder.forClient()
                    .trustManager(combinedTrustManager(certificate)).build();
            HttpClient httpClient = HttpClient.create()
                    .httpResponseDecoder(decoder -> decoder.maxHeaderSize(32 * 1024))
                    .secure(ssl -> ssl.sslContext(sslContext));
            return builder.clientConnector(new ReactorClientHttpConnector(httpClient)).build();
        } catch (Exception error) {
            throw new IllegalArgumentException("Open Assembly CA certificate is invalid", error);
        }
    }

    private X509TrustManager combinedTrustManager(File certificateFile) throws Exception {
        TrustManagerFactory systemFactory = TrustManagerFactory.getInstance(
                TrustManagerFactory.getDefaultAlgorithm());
        systemFactory.init((KeyStore) null);

        KeyStore additionalStore = KeyStore.getInstance(KeyStore.getDefaultType());
        additionalStore.load(null, null);
        CertificateFactory certificates = CertificateFactory.getInstance("X.509");
        try (FileInputStream input = new FileInputStream(certificateFile)) {
            int index = 0;
            for (var certificate : certificates.generateCertificates(input)) {
                additionalStore.setCertificateEntry("local-ca-" + index++, certificate);
            }
        }
        TrustManagerFactory additionalFactory = TrustManagerFactory.getInstance(
                TrustManagerFactory.getDefaultAlgorithm());
        additionalFactory.init(additionalStore);

        List<X509TrustManager> delegates = new ArrayList<>();
        collectX509Managers(systemFactory, delegates);
        collectX509Managers(additionalFactory, delegates);
        return new CompositeX509TrustManager(delegates);
    }

    private void collectX509Managers(
            TrustManagerFactory factory,
            List<X509TrustManager> destination
    ) {
        for (var manager : factory.getTrustManagers()) {
            if (manager instanceof X509TrustManager x509) {
                destination.add(x509);
            }
        }
    }

    private static final class CompositeX509TrustManager implements X509TrustManager {
        private final List<X509TrustManager> delegates;

        private CompositeX509TrustManager(List<X509TrustManager> delegates) {
            this.delegates = List.copyOf(delegates);
        }

        @Override
        public void checkClientTrusted(X509Certificate[] chain, String authType)
                throws java.security.cert.CertificateException {
            check(manager -> manager.checkClientTrusted(chain, authType));
        }

        @Override
        public void checkServerTrusted(X509Certificate[] chain, String authType)
                throws java.security.cert.CertificateException {
            check(manager -> manager.checkServerTrusted(chain, authType));
        }

        @Override
        public X509Certificate[] getAcceptedIssuers() {
            return delegates.stream().flatMap(manager -> List.of(manager.getAcceptedIssuers()).stream())
                    .toArray(X509Certificate[]::new);
        }

        private void check(TrustCheck check) throws java.security.cert.CertificateException {
            java.security.cert.CertificateException failure = null;
            for (X509TrustManager delegate : delegates) {
                try {
                    check.verify(delegate);
                    return;
                } catch (java.security.cert.CertificateException error) {
                    failure = error;
                }
            }
            throw failure == null
                    ? new java.security.cert.CertificateException("no X509 trust manager available")
                    : failure;
        }

        @FunctionalInterface
        private interface TrustCheck {
            void verify(X509TrustManager manager) throws java.security.cert.CertificateException;
        }
    }
}
