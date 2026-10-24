import { describe, expect, it } from "vitest";
import {
  DEFAULT_SETTINGS,
  parseSettings,
  toggleSaved,
  normalizeOrigin,
} from "../src/state";
describe("기기 설정", () => {
  it("손상된 저장소에서 기본 설정으로 복구한다", () =>
    expect(parseSettings("{oops")).toEqual(DEFAULT_SETTINGS));
  it("예시와 실제 저장 ID를 분리한다", () => {
    const preview = toggleSaved(DEFAULT_SETTINGS, "sample-1");
    expect(preview.saved.preview).toEqual(["sample-1"]);
    expect(preview.saved.live).toEqual([]);
    expect(
      toggleSaved({ ...preview, mode: "live" }, "real-1").saved.preview,
    ).toEqual(["sample-1"]);
  });
  it("같은 기록을 다시 누르면 해제한다", () =>
    expect(
      toggleSaved(toggleSaved(DEFAULT_SETTINGS, "a"), "a").saved.preview,
    ).toEqual([]));
  it("잘못된 타입과 과도한 저장 ID를 복구한다", () => {
    const state = parseSettings(
      JSON.stringify({
        fontSize: "huge",
        topics: ["family", "bad"],
        saved: {
          preview: Array.from({ length: 70 }, (_, i) => `p${i}`),
          live: [5],
        },
      }),
    );
    expect(state.fontSize).toBe("normal");
    expect(state.topics).toEqual(["family"]);
    expect(state.saved.preview).toHaveLength(50);
    expect(state.saved.live).toEqual([]);
  });
  it("임의 저장 한도를 넘겨도 기존 기록을 지운 척하지 않는다", () => {
    const state = {
      ...DEFAULT_SETTINGS,
      saved: {
        preview: Array.from({ length: 50 }, (_, i) => `p${i}`),
        live: [],
      },
    };
    expect(toggleSaved(state, "extra")).toEqual(state);
  });
});
describe("서버 주소", () => {
  it("HTTPS origin을 정규화한다", () =>
    expect(normalizeOrigin(" https://records.example.org/ ")).toBe(
      "https://records.example.org",
    ));
  it.each([
    "http://example.org",
    "https://user:secret@example.org",
    "https://example.org/path",
    "https://example.org/?token=x",
    "https://example.org/#x",
    "javascript:alert(1)",
  ])("잘못된 주소 %s를 거부한다", (value) =>
    expect(normalizeOrigin(value)).toBeNull(),
  );
});
