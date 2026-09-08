package dev.parliament.api;

import java.util.List;
import java.util.Map;

public record OpenAssemblyPage(int totalCount, List<Map<String, Object>> rows) {
}

