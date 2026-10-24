import { test } from "node:test";
import assert from "node:assert/strict";
import { runBoundedQa } from "../scripts/qa-core.mjs";
test("성공 시 수정 에이전트를 호출하지 않는다", async () => {
  let fixes = 0;
  const result = await runBoundedQa({
    verify: async () => ({ ok: true }),
    fix: async () => {
      fixes++;
      return true;
    },
    contract: async () => "same",
  });
  assert.equal(result.status, "passed");
  assert.equal(fixes, 0);
});
test("최대 3회 수정 후 실패하면 종료한다", async () => {
  let fixes = 0;
  let checks = 0;
  const result = await runBoundedQa({
    verify: async () => {
      checks++;
      return { ok: false };
    },
    fix: async () => {
      fixes++;
      return true;
    },
    contract: async () => "same",
  });
  assert.equal(result.status, "failed");
  assert.equal(fixes, 3);
  assert.equal(checks, 4);
});
test("테스트 계약 변경을 감지하면 통과시키지 않는다", async () => {
  let hash = "original";
  const result = await runBoundedQa({
    verify: async () => ({ ok: false }),
    fix: async () => {
      hash = "tampered";
      return true;
    },
    contract: async () => hash,
  });
  assert.equal(result.status, "contract-changed");
  assert.equal(result.repairs, 1);
});
test("수정 실행이 실패하면 추가 수정 루프를 돌리지 않는다", async () => {
  let fixes = 0;
  const result = await runBoundedQa({
    verify: async () => ({ ok: false }),
    fix: async () => {
      fixes++;
      return false;
    },
    contract: async () => "same",
  });
  assert.equal(result.status, "repair-unavailable");
  assert.equal(fixes, 1);
});
