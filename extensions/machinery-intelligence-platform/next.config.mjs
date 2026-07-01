import { fileURLToPath } from "node:url";
import path from "node:path";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // This extension has its own package-lock.json, separate from the
  // vault's root one — pin the Turbopack root to avoid the ambiguity warning.
  turbopack: {
    root: projectRoot,
  },
};

export default nextConfig;
