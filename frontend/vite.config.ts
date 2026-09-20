import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";

// Ship notices for the packages actually included in the browser bundle.
function bundledLicenses(): Plugin {
  return {
    name: "bundled-licenses",
    generateBundle(_options, bundle) {
      const notices = new Map<string, string>();
      for (const chunk of Object.values(bundle)) {
        if (chunk.type !== "chunk") continue;
        for (const id of Object.keys(chunk.modules)) {
          if (id.startsWith("\0") || !id.includes("node_modules/")) continue;
          let dir = dirname(id.split("?")[0]);
          while (dir !== dirname(dir)) {
            const pkgPath = join(dir, "package.json");
            if (existsSync(pkgPath)) {
              try {
                const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
                if (pkg.name) {
                  const key = `${pkg.name}@${pkg.version}`;
                  if (notices.has(key)) break;
                  const files = readdirSync(dir).filter(name => /^licen[cs]e(?:\.|$)/i.test(name));
                  if (files.length) {
                    notices.set(key, files.map(name => readFileSync(join(dir, name), "utf8")).join("\n"));
                  } else {
                    notices.set(key, `${pkg.name} (${pkg.license || "MIT"})`);
                  }
                  break;
                }
              } catch {
                // Ignore parse errors
              }
            }
            dir = dirname(dir);
          }
        }
      }
      return this.emitFile({ type: "asset", fileName: "third-party-licenses.txt",
        source: [...notices].sort(([a], [b]) => a.localeCompare(b)).map(([name, license]) => `${name}\n${license}`).join("\n\n") });
    },
  };
}

export default defineConfig({
  plugins: [react(), bundledLicenses()],
  base: "/studio/",
  build: {
    outDir: "../src/semaloom/app/static",
    emptyOutDir: true,
  },
});
