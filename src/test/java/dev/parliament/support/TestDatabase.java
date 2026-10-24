package dev.parliament.support;

import org.testcontainers.mysql.MySQLContainer;

/** Disposable MySQL fixture; explicit loopback test schemas can replace Docker locally. */
public final class TestDatabase implements AutoCloseable {
    private final MySQLContainer container;
    private final String jdbcUrl;
    private final String r2dbcUrl;
    private final String username;
    private final String password;

    private TestDatabase(String suite) {
        String prefix = "PARLIAMENT_TEST_" + suite.toUpperCase(java.util.Locale.ROOT) + "_";
        String external = System.getenv(prefix + "JDBC_URL");
        if (external == null || external.isBlank()) external = System.getenv("PARLIAMENT_TEST_JDBC_URL");
        if (external != null && !external.isBlank()) {
            if (!external.matches("jdbc:mysql://127\\.0\\.0\\.1:[0-9]+/parliament_[a-z0-9_]+_test"))
                throw new IllegalArgumentException("external fixture must be an explicit disposable loopback test schema");
            container = null;
            jdbcUrl = external;
            String reactive = System.getenv(prefix + "R2DBC_URL");
            r2dbcUrl = reactive == null || reactive.isBlank() ? required("PARLIAMENT_TEST_R2DBC_URL") : reactive;
            username = required("PARLIAMENT_TEST_DB_USER");
            password = required("PARLIAMENT_TEST_DB_PASSWORD");
        } else {
            container = new MySQLContainer("mysql:8.4").withDatabaseName("parliament_" + suite + "_test");
            container.start();
            jdbcUrl = container.getJdbcUrl();
            username = container.getUsername();
            password = container.getPassword();
            r2dbcUrl = "r2dbc:mysql://" + username + ":" + password + "@" + container.getHost()
                    + ":" + container.getMappedPort(3306) + "/" + container.getDatabaseName();
        }
    }

    public static TestDatabase start(String suite) { return new TestDatabase(suite); }
    public String jdbcUrl() { return jdbcUrl; }
    public String r2dbcUrl() { return r2dbcUrl; }
    public String username() { return username; }
    public String password() { return password; }
    public void close() { if (container != null) container.stop(); }

    private static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) throw new IllegalArgumentException("missing test environment: " + name);
        return value;
    }
}
