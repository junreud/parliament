package dev.parliament.api;

class OpenAssemblyTransientException extends OpenAssemblyApiException {
    OpenAssemblyTransientException(int status) {
        super("Open Assembly transient HTTP error " + status);
    }
}
