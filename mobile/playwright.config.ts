import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  outputDir: process.env.PARLIAMENT_TEST_OUTPUT || "./test-results",
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { open: "never" }],
    [
      "json",
      {
        outputFile: `${process.env.PARLIAMENT_TEST_OUTPUT || "./test-results"}/results.json`,
      },
    ],
  ],
  use: {
    baseURL: "http://127.0.0.1:14200",
    viewport: { width: 412, height: 915 },
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
    trace: "on",
    video: "on",
    screenshot: "on",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:14200",
    reuseExistingServer: !process.env.CI,
  },
  timeout: 30000,
});
