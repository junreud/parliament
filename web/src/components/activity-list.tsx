import type { Activity } from "@/lib/contracts";
import { ActivityCard } from "./activity-card";
import { ApiNotice } from "./api-notice";
export function ActivityList({ activities }: { activities?: Activity[] }) {
  return activities?.length ? <div className="activity-list">{activities.map(activity => <ActivityCard key={activity.id} activity={activity} />)}</div> : <ApiNotice status="empty" />;
}
