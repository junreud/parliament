import { useEffect, useRef } from "react";
import type { PersonProfile } from "../../../web/src/lib/knowledge-contracts";
import type { Settings } from "../state";
import { useResource } from "./data";
import { OfficeDates } from "./PublicMeta";
import { Icon } from "../components/Icon";

export function PersonSheet({
  id,
  settings,
  onClose,
  onOpen,
}: {
  id: string;
  settings: Settings;
  onClose: () => void;
  onOpen: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const profile = useResource<PersonProfile>(
    settings,
    `/api/v1/people/${id}/profile`,
  );
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog
      className="person-sheet"
      ref={dialog}
      aria-label="인물 미리보기"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sheet-handle" />
      <div className="sheet-heading">
        <span className="eyebrow">인물 미리보기</span>
        <button
          className="icon-button"
          aria-label="인물 미리보기 닫기"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      {profile.status === "loading" ? (
        <p role="status">인물을 확인하고 있어요.</p>
      ) : profile.data ? (
        <>
          <div className="person-preview-heading">
            <span className="person-avatar">
              {profile.data.name.slice(0, 1)}
            </span>
            <div>
              <h2>{profile.data.name}</h2>
              <p>
                {profile.data.tenures[0]?.organizationName ||
                  "소속 정보 확인 중"}
              </p>
            </div>
          </div>
          {profile.data.tenures[0] && (
            <OfficeDates {...profile.data.tenures[0]} />
          )}
          <p className="secondary-text">
            {settings.mode === "preview"
              ? "가상 인물 · UX 예시"
              : "공식 자료에서 공개가 확인된 인물 문서예요."}
          </p>
          <p className="person-preview-note">
            소개와 활동 기록을 살펴보고, 읽던 글로 돌아올 수 있어요.
          </p>
          <button
            className="primary-button wide"
            onClick={() => onOpen(profile.data!.id)}
          >
            인물 전체 보기 <Icon name="arrow" size={18} />
          </button>
        </>
      ) : (
        <>
          <p role="status">
            {profile.status === "not-found"
              ? "공개된 인물 문서가 없어요"
              : "인물 자료를 불러오지 못했어요"}
          </p>
          <button className="secondary-button" onClick={profile.reload}>
            인물 다시 읽기
          </button>
        </>
      )}
    </dialog>
  );
}
