export function ApiNotice({ status }: { status: string }) {
  const offline = status === "offline";
  return <div className="empty-state" role={offline ? "status" : undefined}>
    <span className="empty-icon" aria-hidden="true">{offline ? "↻" : "□"}</span>
    <h2>{offline ? "기록 서버에 연결할 수 없습니다" : status === "not-found" ? "기록을 찾을 수 없습니다" : "공개된 기록이 없습니다"}</h2>
    <p>{offline ? "연결 상태를 확인한 뒤 다시 방문해 주세요. 연결 실패는 새로운 기록이 없다는 뜻이 아닙니다." : "수집·검증이 완료된 공개 기록만 표시합니다. 다른 검색어나 필터를 선택하거나 자료 범위를 확인해 주세요."}</p>
    <a href="/coverage" className="text-link">자료 범위와 수집 상태 확인 →</a>
  </div>;
}
