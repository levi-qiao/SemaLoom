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
          while (dir !== dirname(dir) && !existsSync(join(dir, "package.json"))) dir = dirname(dir);
          if (!existsSync(join(dir, "package.json"))) continue;
          const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
          const key = `${pkg.name}@${pkg.version}`;
          if (notices.has(key)) continue;
          const files = readdirSync(dir).filter(name => /^licen[cs]e(?:\.|$)/i.test(name));
          if (!files.length) throw new Error(`Missing bundled license: ${key}`);
          notices.set(key, files.map(name => readFileSync(join(dir, name), "utf8")).join("\n"));
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
