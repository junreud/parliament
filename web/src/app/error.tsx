"use client";
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) { return <div className="empty-state" role="alert"><h2>기록을 표시하지 못했습니다</h2><p>잠시 후 다시 시도해 주세요. 오류가 난 화면에서는 내용을 추정해 표시하지 않습니다.</p><button className="button" onClick={reset}>다시 시도</button></div>; }
