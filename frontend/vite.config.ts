import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE wird im GitHub-Actions-Build auf /<repo-name>/ gesetzt (GitHub Pages)
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE ?? "./",
});
