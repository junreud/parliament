export type IconName =
  | "home"
  | "search"
  | "bookmark"
  | "settings"
  | "arrow"
  | "back"
  | "check"
  | "close"
  | "external"
  | "family"
  | "housing"
  | "labor"
  | "economy-tax"
  | "shield"
  | "spark"
  | "refresh"
  | "sun";
const paths: Record<IconName, React.ReactNode> = {
  home: (
    <>
      <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z" />
      <path d="M9 21v-8h6v8" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  bookmark: <path d="M6 4h12v17l-6-4-6 4Z" />,
  settings: (
    <>
      <path d="M4 7h16M4 17h16" />
      <circle cx="9" cy="7" r="3" fill="currentColor" />
      <circle cx="15" cy="17" r="3" fill="currentColor" />
    </>
  ),
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  back: <path d="m15 5-7 7 7 7" />,
  check: <path d="m5 12 4 4L19 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  external: (
    <>
      <path d="M14 3h7v7m0-7L10 14M10 4H4v16h16v-6" />
    </>
  ),
  family: (
    <>
      <circle cx="8" cy="7" r="3" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M2 21v-3a6 6 0 0 1 12 0v3m2-6a5 5 0 0 1 6 5v1" />
    </>
  ),
  housing: (
    <>
      <path d="m3 11 9-8 9 8M5 10v11h14V10M9 21v-7h6v7" />
    </>
  ),
  labor: (
    <>
      <rect x="3" y="7" width="18" height="14" rx="3" />
      <path d="M8 7V3h8v4M3 13h18M10 13v3h4v-3" />
    </>
  ),
  "economy-tax": (
    <>
      <path d="M4 21h16M6 17V9m6 8V3m6 14v-5" />
      <path d="m3 6 6-3" />
    </>
  ),
  shield: (
    <>
      <path d="m12 3 9 4v5c0 5-9 9-9 9s-9-4-9-9V7Z" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  spark: (
    <>
      <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" />
    </>
  ),
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1" />
    </>
  ),
};
export function Icon({
  name,
  size = 22,
  filled = false,
}: {
  name: IconName;
  size?: number;
  filled?: boolean;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
