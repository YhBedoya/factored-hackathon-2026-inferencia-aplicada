import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
	// TanStack Router's codegen plugin must run before the React plugin so it
	// can rewrite route files before they are compiled.
	plugins: [
		tanstackRouter({ target: "react", autoCodeSplitting: true }),
		react(),
		tailwindcss(),
	],
	resolve: {
		alias: {
			"@": path.resolve(import.meta.dirname, "./src"),
		},
	},
	server: {
		// Bind to 0.0.0.0 so the dev server is reachable from other containers
		// (T14 puts this behind an Nginx proxy on the docker network).
		host: true,
		port: 5173,
		// HMR websocket must reconnect through Nginx on port 80, not the
		// container-internal Vite port.
		hmr: {
			clientPort: 80,
		},
		allowedHosts: ["localhost", "nginx"],
	},
});
