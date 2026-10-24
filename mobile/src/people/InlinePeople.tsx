import { Fragment } from "react";
import type { Mention } from "../../../web/src/lib/knowledge-contracts";
import { approvedMentions } from "./api";

export function InlinePeople({
  text,
  mentions,
  offset = 0,
  onPerson,
}: {
  text: string;
  mentions: Mention[];
  offset?: number;
  onPerson: (id: string) => void;
}) {
  const points = Array.from(text),
    ranges = approvedMentions(text, mentions, offset);
  let cursor = 0;
  return (
    <span className="source-text">
      {ranges.map((mention) => {
        const start = mention.start - offset,
          end = mention.end - offset;
        const before = points.slice(cursor, start).join("");
        cursor = end;
        return (
          <Fragment key={mention.id}>
            {before}
            <button
              type="button"
              className="person-mention"
              data-reader-focus={mention.id}
              aria-label={`${mention.surface} 인물 미리보기`}
              onClick={() => onPerson(mention.personId!)}
            >
              {mention.surface}
            </button>
          </Fragment>
        );
      })}
      {points.slice(cursor).join("")}
    </span>
  );
}
