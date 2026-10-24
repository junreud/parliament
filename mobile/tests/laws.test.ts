import { describe, expect, it } from "vitest";
import { isLawPage, readLaws, lawSource } from "../src/laws";

const law = {
  id: "law_013103_286729",
  lawId: "013103",
  mst: "286729",
  title: "아동수당법",
  agency: "보건복지부",
  promulgationNumber: "21777",
  promulgatedDate: "2026-06-09",
  effectiveDate: "2026-09-10",
  collectedAt: "2026-10-09T08:00:00Z",
  sourceUrl: "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=286729",
  sourceVersion: "a".repeat(64),
  extractionVersion: "law_public_metadata_v1",
  evidence: [
    {
      label: "시행일",
      text: "20260910",
      locator: "json:법령.기본정보.시행일자",
    },
  ],
};
const page = { items: [law], coverage: "선택한 법령 1건", nextCursor: null };
describe("실제 법령 공개 계약", () => {
  it("기본정보와 공포일·시행일을 별도로 검증한다", () =>
    expect(isLawPage(page)).toBe(true));
  it.each(["2026-02-30", "2026-13-01", "20260910"])(
    "잘못된 달력 날짜 %s를 거부한다",
    (date) => {
      expect(
        isLawPage({ ...page, items: [{ ...law, effectiveDate: date }] }),
      ).toBe(false);
    },
  );
  it("날짜 미확인을 임의로 보완하지 않는다", () =>
    expect(
      isLawPage({ ...page, items: [{ ...law, effectiveDate: null }] }),
    ).toBe(true));
  it("법령 버전과 출처 주소가 다르면 거부한다", () => {
    expect(
      isLawPage({
        ...page,
        items: [
          { ...law, sourceUrl: law.sourceUrl.replace("286729", "289533") },
        ],
      }),
    ).toBe(false);
    expect(
      lawSource({ ...law, sourceUrl: "https://evil.example/" }),
    ).toBeNull();
  });
  it("출처 링크의 인증 값과 추가 쿼리를 거부한다", () => {
    expect(
      isLawPage({
        ...page,
        items: [{ ...law, sourceUrl: law.sourceUrl + "&OC=private" }],
      }),
    ).toBe(false);
  });
  it("HTTPS 공개 조회만 허용하고 응답을 검증한다", async () => {
    const urls: string[] = [];
    const request = async (url: string) => {
      urls.push(url);
      return { status: 200, data: page };
    };
    expect((await readLaws("http://localhost:8080", request)).status).toBe(
      "error",
    );
    expect(urls).toHaveLength(0);
    expect(await readLaws("https://records.example.org", request)).toEqual({
      status: "ok",
      data: page,
    });
    expect(urls).toEqual(["https://records.example.org/api/v1/laws"]);
  });
  it("장애·빈 응답·404를 수집본으로 대체하지 않는다", async () => {
    expect(
      (
        await readLaws("https://records.example.org", async () => ({
          status: 503,
          data: page,
        }))
      ).status,
    ).toBe("error");
    expect(
      (
        await readLaws("https://records.example.org", async () => ({
          status: 404,
          data: {},
        }))
      ).status,
    ).toBe("not-found");
    expect(
      await readLaws("https://records.example.org", async () => ({
        status: 200,
        data: { ...page, items: [] },
      })),
    ).toEqual({ status: "ok", data: { ...page, items: [] } });
    expect(
      (
        await readLaws("https://records.example.org", async () => {
          throw new Error("offline");
        })
      ).status,
    ).toBe("error");
  });
  it("중복 문서와 손상된 응답을 거부한다", () => {
    expect(isLawPage({ ...page, items: [law, law] })).toBe(false);
    expect(isLawPage({ ...page, items: [{ title: "가짜" }] })).toBe(false);
  });
});
