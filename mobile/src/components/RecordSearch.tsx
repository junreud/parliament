import type { FormEvent } from "react";

export function RecordSearch({
  id,
  value,
  onChange,
  onSubmit,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form className="record-search" role="search" onSubmit={submit}>
      <label htmlFor={id}>공개 기록 검색</label>
      <div className="record-search-control">
        <input
          id={id}
          type="search"
          placeholder="사건·정책 키워드"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          maxLength={120}
        />
        <button type="submit">검색</button>
      </div>
      <p>발표·법안·표결의 제목과 요약에서 찾습니다.</p>
    </form>
  );
}
