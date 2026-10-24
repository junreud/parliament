process.env.HOSTNAME = process.env.WEB_HOST || "127.0.0.1";
await import("../.next/standalone/server.js");
