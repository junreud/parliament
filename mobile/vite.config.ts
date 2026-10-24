import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: { port: 14200, strictPort: true },
  preview: { host: "127.0.0.1", port: 14200, strictPort: true },
});
