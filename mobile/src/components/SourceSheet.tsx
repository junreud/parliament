import { useEffect, useRef, useState } from "react";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import type { Evidence } from "../../../web/src/lib/contracts";
import { safeSource } from "../../../web/src/lib/format";
import { Icon } from "./Icon";

export function SourceSheet({
  evidence,
  number,
  onClose,
}: {
  evidence: Evidence;
  number: number;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState("");
  const source = safeSource(evidence.sourceUrl);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    element?.showModal();
    return () => {
      element?.close();
      document.body.style.overflow = overflow;
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, []);
  const openSource = async () => {
    if (!source) return;
    try {
      if (Capacitor.isNativePlatform())
        await Browser.open({ url: source, toolbarColor: "#ffffff" });
      else window.open(source, "_blank", "noopener,noreferrer");
    } catch {
      setError("원문을 열지 못했어요. 다시 시도해 주세요.");
    }
  };
  return (
    <dialog
      ref={dialog}
      className="source-sheet"
      aria-labelledby="source-sheet-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="source-sheet-content">
        <div className="sheet-heading">
          <h2 id="source-sheet-title">근거 {number}</h2>
          <button
            className="icon-button"
            aria-label="근거 닫기"
            onClick={onClose}
          >
            <Icon name="close" />
          </button>
        </div>
        {evidence.excerpt ? (
          <blockquote>{evidence.excerpt}</blockquote>
        ) : (
          <p>공개된 발췌가 없어요. 공식 원문에서 확인해 주세요.</p>
        )}
        <dl>
          <dt>문서 위치</dt>
          <dd>{evidence.locator || "미확인"}</dd>
          <dt>원문 버전</dt>
          <dd>{evidence.sourceVersion || "미확인"}</dd>
          {source && (
            <>
              <dt>출처</dt>
              <dd>{new URL(source).hostname}</dd>
            </>
          )}
        </dl>
        {source ? (
          <button
            className="primary-button wide"
            onClick={() => void openSource()}
          >
            공식 원문 열기 <Icon name="external" size={17} />
          </button>
        ) : (
          <p className="source-unavailable">
            안전하게 열 수 있는 공식 원문 주소를 확인하지 못했어요.
          </p>
        )}
        <p role="status" className="form-message">
          {error}
        </p>
      </div>
    </dialog>
  );
}
