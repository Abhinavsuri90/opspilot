import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = fileURLToPath(new URL(".", import.meta.url));

// Pure modules and route handlers run in Node. Component tests (*.test.tsx) run
// in jsdom with Testing Library. Next.js needs `jsx: preserve` in tsconfig, so
// the JSX runtime is chosen here instead.
export default defineConfig({
  resolve: { alias: { "@": root } },
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    projects: [
      { extends: true, test: { name: "node", environment: "node", include: ["**/*.test.ts"] } },
      { extends: true, test: { name: "jsdom", environment: "jsdom", include: ["**/*.test.tsx"], setupFiles: ["./vitest.setup.ts"] } },
    ],
  },
});
