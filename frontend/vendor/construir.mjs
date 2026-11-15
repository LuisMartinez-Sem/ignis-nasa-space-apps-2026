// Construye vendor/three.bundle.js (ESM minificado) y copia las fuentes self-hosted.
// Por qué: en un hackathon el WiFi falla. Sin CDN, la demo funciona offline y la CSP
// puede ser estricta ('self').
import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const raiz = join(dirname(fileURLToPath(import.meta.url)), "..");

await build({
  entryPoints: [join(raiz, "vendor/entrada-three.js")],
  outfile: join(raiz, "vendor/three.bundle.js"),
  bundle: true,
  minify: true,
  format: "esm",
  target: "es2022",
  legalComments: "none",
  logLevel: "info",
});

const destino = join(raiz, "assets/fonts");
await mkdir(destino, { recursive: true });
const fuentes = [
  ["@fontsource/jetbrains-mono", "jetbrains-mono", [400, 500, 700]],
  ["@fontsource/inter", "inter", [400, 500, 600]],
];
for (const [paquete, nombre, pesos] of fuentes) {
  for (const peso of pesos) {
    const archivo = `${nombre}-latin-${peso}-normal.woff2`;
    await copyFile(join(raiz, "node_modules", paquete, "files", archivo), join(destino, archivo));
  }
}
console.log("Fuentes copiadas a assets/fonts");
