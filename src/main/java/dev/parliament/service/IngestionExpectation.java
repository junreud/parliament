package dev.parliament.service;

public enum IngestionExpectation {
    STANDARD,
    PARAMETERIZED_STATIC,
    DEPENDENCY_DRIVEN,
    EMPTY_ALLOWED,
    RETRYABLE
}
