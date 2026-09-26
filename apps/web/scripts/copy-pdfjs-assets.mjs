// Keep PDF.js and its worker/fonts at exactly the same installed version.
// These assets ship with the site; invoice bytes never go to a third-party viewer.
import { cp, mkdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const source = path.dirname(require.resolve("pdfjs-dist/package.json"));
const { version } = JSON.parse(await readFile(path.join(source, "package.json"), "utf8"));
const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const destination = path.join(appRoot, "public", "pdfjs", version);
await mkdir(destination, { recursive: true });
await cp(path.join(source, "legacy", "build", "pdf.worker.min.mjs"), path.join(destination, "pdf.worker.min.mjs"));
for (const asset of ["cmaps", "standard_fonts", "wasm", "iccs", "LICENSE"]) {
  await cp(path.join(source, asset), path.join(destination, asset), { recursive: true });
}
console.log(`Prepared local PDF.js ${version} worker and rendering assets.`);
