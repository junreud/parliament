import { TOPICS } from "../../web/src/lib/format";
export type Mode = "preview" | "live";
export interface Settings {
  mode: Mode;
  origin: string;
  topics: string[];
  saved: Record<Mode, string[]>;
  fontSize: "normal" | "large";
  reducedMotion: boolean;
  haptics: boolean;
}
export const STORAGE_KEY = "parliament.mobile.v1";
export const DEFAULT_SETTINGS: Settings = {
  mode: "preview",
  origin: "",
  topics: [],
  saved: { preview: [], live: [] },
  fontSize: "normal",
  reducedMotion: false,
  haptics: true,
};
export function normalizeOrigin(value: string): string | null {
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      url.pathname === "/" &&
      !url.search &&
      !url.hash
      ? url.origin
      : null;
  } catch {
    return null;
  }
}
export function parseSettings(raw: string | null): Settings {
  try {
    const data = JSON.parse(raw || "null");
    if (!data || typeof data !== "object" || Array.isArray(data))
      return structuredClone(DEFAULT_SETTINGS);
    const ids = (values: unknown): string[] =>
      Array.isArray(values)
        ? [
            ...new Set(
              values.filter(
                (v): v is string =>
                  typeof v === "string" && /^[a-zA-Z0-9_.:-]{1,128}$/.test(v),
              ),
            ),
          ].slice(0, 50)
        : [];
    const origin =
      typeof data.origin === "string" ? normalizeOrigin(data.origin) || "" : "";
    return {
      mode: data.mode === "live" && origin ? "live" : "preview",
      origin,
      topics: ids(data.topics).filter((id) => Object.hasOwn(TOPICS, id)),
      saved: { preview: ids(data.saved?.preview), live: ids(data.saved?.live) },
      fontSize: data.fontSize === "large" ? "large" : "normal",
      reducedMotion: data.reducedMotion === true,
      haptics: data.haptics !== false,
    };
  } catch {
    return structuredClone(DEFAULT_SETTINGS);
  }
}
export function toggleSaved(settings: Settings, id: string): Settings {
  const items = settings.saved[settings.mode];
  if (!items.includes(id) && items.length >= 50) return settings;
  return {
    ...settings,
    saved: {
      ...settings.saved,
      [settings.mode]: items.includes(id)
        ? items.filter((item) => item !== id)
        : [...items, id],
    },
  };
}
