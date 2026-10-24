export const ISSUE_READING_MESSAGES = {
  "not-found": { title: "공개된 해설을 찾지 못했어요", description: "현재 공개된 범위에서 확인되지 않아요. 이전 화면이나 공개 이슈 목록으로 돌아갈 수 있어요." },
  conflict: { title: "해설의 공개 버전을 다시 확인해 주세요", description: "해설과 근거의 공개 버전이 일치하는지 확인이 필요해요. 다시 불러와 주세요." },
  invalid: { title: "해설 주소를 확인해 주세요", description: "올바른 이슈 주소로 다시 열어 주세요." },
  error: { title: "해설을 불러오지 못했어요", description: "연결 실패는 공개 해설이 없다는 뜻이 아니에요. 잠시 후 다시 시도해 주세요." },
} as const;
