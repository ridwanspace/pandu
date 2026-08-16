import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the slim Docker runtime stage.
  output: "standalone",
  // Workaround: the Turbopack file trace copies only @swc/helpers/cjs, but
  // the server bundle requires the esm build at runtime.
  outputFileTracingIncludes: {
    "/**": ["./node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers/**"],
  },
};

export default nextConfig;
