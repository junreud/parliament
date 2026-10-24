import type { CapacitorConfig } from "@capacitor/cli";
const config: CapacitorConfig = {
  appId: "dev.parliament.flow",
  appName: "의정의 흐름",
  webDir: "dist",
  backgroundColor: "#ffffff",
  android: { backgroundColor: "#ffffff", allowMixedContent: false },
  server: { androidScheme: "https" },
};
export default config;
