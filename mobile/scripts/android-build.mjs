import { spawnSync } from "node:child_process";
import { access, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
const env = { ...process.env };
if (!env.ANDROID_HOME) {
  const sdk = path.resolve(root, "../.local/android-sdk");
  try {
    await access(sdk);
    env.ANDROID_HOME = sdk;
  } catch {
    /* Android Studio may supply ANDROID_SDK_ROOT. */
  }
}
if (!env.JAVA_HOME) {
  const local = path.resolve(root, "../.local/java");
  try {
    const jdk = (await readdir(local)).find((name) =>
      name.startsWith("jdk-21"),
    );
    if (jdk) env.JAVA_HOME = path.join(local, jdk, "Contents/Home");
  } catch {
    /* Use the caller's configured Java installation. */
  }
}
for (const [cmd, args, cwd] of [
  ["npm", ["run", "android:sync"], root],
  [
    process.platform === "win32" ? "gradlew.bat" : "./gradlew",
    ["assembleDebug"],
    path.join(root, "android"),
  ],
]) {
  const result = spawnSync(cmd, args, {
    cwd,
    env,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) process.stderr.write(`${result.error.message}\n`);
  if (result.status !== 0) process.exit(result.status || 1);
}
