import Link from "next/link";
export default function NotFound() { return <div className="empty-state"><h1>기록을 찾을 수 없습니다</h1><p>주소가 바뀌었거나 아직 공개되지 않은 기록입니다.</p><Link className="button" href="/">변화 피드로 돌아가기</Link></div>; }
