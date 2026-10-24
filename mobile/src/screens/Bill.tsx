import { useState } from "react";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import type { Bill } from "../../../web/src/lib/contracts";
import type {
  BillLineage,
  KnowledgeRelation,
} from "../../../web/src/lib/knowledge-contracts";
import { STAGES, safeSource } from "../../../web/src/lib/format";
import type { Settings } from "../state";
import { useResource } from "../people/data";
import { EvidenceLinks, PublicRefresh } from "../people/PublicMeta";
import { Icon } from "../components/Icon";
import { useEntryView } from "../navigation";

function RelatedBill({
  relation,
  rootId,
  settings,
  onBill,
  onEvidence,
}: {
  relation: KnowledgeRelation;
  rootId: string;
  settings: Settings;
  onBill: (id: string) => void;
  onEvidence: (id: string) => void;
}) {
  const original = relation.subjectId === rootId;
  const id = original ? relation.objectId : relation.subjectId;
  const target = useResource<Bill>(settings, `/api/v1/bills/${id}`);
  const title = target.data?.title || `법안 ID · ${id}`;
  return (
    <article className="bill-relation">
      <p className="eyebrow">
        {original ? "이 원안이 통합된 대안" : "이 대안에 연결된 원안"}
      </p>
      <button
        className="person-activity-open"
        data-reader-focus={`bill-relation-${relation.id}`}
        aria-label={`${title} 법안 보기`}
        onClick={() => onBill(id)}
      >
        <h3>{title}</h3>
        <Icon name="arrow" size={17} />
      </button>
      {target.status === "loading" && (
        <p role="status">상대 법안의 공개 제목을 확인하고 있어요.</p>
      )}
      {target.status === "not-found" && (
        <p className="secondary-text">
          상대 법안의 공개 문서를 찾지 못했어요. 관계에 적힌 ID를 표시해요.
        </p>
      )}
      {target.status === "error" && (
        <>
          <p className="secondary-text">상대 법안 제목을 불러오지 못했어요.</p>
          <button className="text-button" onClick={target.reload}>
            법안 제목 재시도
          </button>
        </>
      )}
      <p>{relation.reason}</p>
      <EvidenceLinks
        ids={relation.evidenceIds}
        onEvidence={onEvidence}
        label="원안·대안 근거"
        focusKey={`lineage-${relation.id}`}
      />
    </article>
  );
}
export function BillScreen({
  id,
  settings,
  onBack,
  onBill,
  onEvidence,
  onActivity,
}: {
  id: string;
  settings: Settings;
  onBack: () => void;
  onBill: (id: string) => void;
  onEvidence: (id: string) => void;
  onActivity: (id: string) => void;
}) {
  const bill = useResource<Bill>(settings, `/api/v1/bills/${id}`);
  const lineage = useResource<BillLineage>(
    settings,
    `/api/v1/bills/${id}/lineage`,
  );
  const [visible, setVisible] = useEntryView(`bill:${id}:relations`, 10);
  const [sourceError, setSourceError] = useState("");
  const source = safeSource(bill.data?.sourceUrl);
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>법안</span>
        <PublicRefresh
          settings={settings}
          loading={bill.status === "loading" || lineage.status === "loading"}
          label="공개 법안 새로고침"
          onRefresh={() => {
            bill.reload();
            lineage.reload();
          }}
        />
      </div>
      {bill.status === "loading" ? (
        <p role="status" className="loading-state">
          공개 법안을 읽고 있어요.
        </p>
      ) : !bill.data ? (
        <section className="empty-state">
          <h1>
            {bill.status === "not-found"
              ? "공개된 법안 문서를 찾지 못했어요"
              : "법안을 불러오지 못했어요"}
          </h1>
          <button className="secondary-button" onClick={bill.reload}>
            법안 다시 읽기
          </button>
        </section>
      ) : (
        <>
          <header className="detail-heading">
            <span className="stage">
              {STAGES[bill.data.stage] || "단계 미확인"}
            </span>
            <h1>{bill.data.title}</h1>
          </header>
          <section className="wiki-section">
            <h2>원안·대안 관계</h2>
            <p className="secondary-text">
              대안 반영은 원안의 독립적인 통과를 뜻하지 않아요.
            </p>
            {lineage.status === "loading" ? (
              <p role="status">승인된 원안·대안 관계를 읽고 있어요.</p>
            ) : !lineage.data ? (
              <div className="person-empty">
                <p role="alert">
                  {lineage.status === "not-found"
                    ? "공개된 원안·대안 관계 경로를 찾지 못했어요"
                    : "원안·대안 관계를 불러오지 못했어요"}
                </p>
                <button className="text-button" onClick={lineage.reload}>
                  법안 관계 재시도
                </button>
              </div>
            ) : lineage.data.items.length ? (
              <>
                {lineage.data.items.slice(0, visible).map((relation) => (
                  <RelatedBill
                    key={`${relation.id}:${bill.revision}`}
                    relation={relation}
                    rootId={id}
                    settings={settings}
                    onBill={onBill}
                    onEvidence={onEvidence}
                  />
                ))}
                {lineage.data.items.length > visible && (
                  <button
                    className="secondary-button wide"
                    onClick={() => setVisible(Math.min(100, visible + 10))}
                  >
                    승인된 관계 더 보기
                  </button>
                )}
              </>
            ) : (
              <p className="person-empty">
                현재 공개 범위에서 승인된 원안·대안 관계가 없어요.
              </p>
            )}
          </section>
          {source && (
            <a
              className="secondary-button wide law-source-link"
              href={source}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(event) => {
                if (Capacitor.isNativePlatform()) {
                  event.preventDefault();
                  void Browser.open({
                    url: source,
                    toolbarColor: "#ffffff",
                  }).catch(() =>
                    setSourceError("원문을 열지 못했어요. 다시 시도해 주세요."),
                  );
                }
              }}
            >
              법안 공식 원문 열기 <Icon name="external" size={17} />
            </a>
          )}
          {sourceError && (
            <p className="form-message" role="status">
              {sourceError}
            </p>
          )}
          <section className="wiki-section">
            <h2>연결된 공개 기록</h2>
            {bill.data.activities?.length ? (
              bill.data.activities.map((activity) => (
                <button
                  key={`${activity.id}:${activity.version}`}
                  className="person-card"
                  data-reader-focus={`bill-activity-${activity.id}`}
                  onClick={() => onActivity(activity.id)}
                >
                  {activity.title}
                  <Icon name="arrow" size={17} />
                </button>
              ))
            ) : (
              <p className="secondary-text">
                현재 법안 응답에 연결된 활동이 없어요. 전체 활동이 없다는 뜻은
                아니에요.
              </p>
            )}
          </section>
        </>
      )}
    </>
  );
}
