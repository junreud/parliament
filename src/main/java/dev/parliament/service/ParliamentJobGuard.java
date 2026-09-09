package dev.parliament.service;

import java.util.concurrent.atomic.AtomicBoolean;

public class ParliamentJobGuard {
    private final AtomicBoolean running = new AtomicBoolean();

    public boolean tryAcquire() {
        return running.compareAndSet(false, true);
    }

    public void release() {
        running.set(false);
    }
}
