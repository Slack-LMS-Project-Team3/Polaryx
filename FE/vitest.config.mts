import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { fileURLToPath } from "node:url";

const styleMockPath = fileURLToPath(new URL("./test/styleMock.ts", import.meta.url));

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  resolve: {
    alias: {
      "@/styles/globals.css": styleMockPath,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
  },
});
