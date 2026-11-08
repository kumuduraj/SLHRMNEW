import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { VitePWA } from "vite-plugin-pwa"
import frappeui from "frappe-ui/vite"

import path from "path"
import fs from "fs"

// Build output is committed: slhrm/public/frontend is served at /assets/slhrm/frontend/,
// and index.html is copied to slhrm/www/slhrm.html (rendered by Frappe at /slhrm).
const PWA_ASSET_BASE = "/assets/slhrm/frontend/"
const PWA_OUT_DIR = path.resolve(__dirname, "../slhrm/public/frontend")
const PWA_HTML_ENTRY = path.resolve(__dirname, "../slhrm/www/slhrm.html")

export default defineConfig(({ command }) => ({
	base: command === "build" ? PWA_ASSET_BASE : "/",
	server: {
		port: 8080,
		proxy: getProxyOptions(),
		allowedHosts: true,
	},
	plugins: [
		vue(),
		frappeui(),
		copyHtmlEntry(),
		VitePWA({
			registerType: "autoUpdate",
			strategies: "injectManifest",
			injectRegister: null,
			// SW is served from /api/method/slhrm.api.pwa_sw, so precache URLs must be absolute
			scope: "/slhrm/",
			injectManifest: {
				modifyURLPrefix: { "": PWA_ASSET_BASE },
			},
			devOptions: {
				enabled: true,
			},
			manifest: {
				display: "standalone",
				name: "SLHRM",
				short_name: "SLHRM",
				start_url: "/slhrm",
				scope: "/slhrm/",
				description: "Biometric fingerprint attendance for ERPNext",
				theme_color: "#3b82f6",
				background_color: "#ffffff",
				icons: [
					{ src: "/assets/slhrm/icons/pwa/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
					{ src: "/assets/slhrm/icons/pwa/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
					{ src: "/assets/slhrm/icons/pwa/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
					{ src: "/assets/slhrm/icons/pwa/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
					{ src: "/assets/slhrm/icons/desktop_icons/solid/slhrm.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
				],
			},
		}),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	build: {
		outDir: PWA_OUT_DIR,
		emptyOutDir: true,
		target: "es2015",
		commonjsOptions: {
			include: [/tailwind.config.js/, /node_modules/],
		},
		sourcemap: false,
		rollupOptions: {
			output: {
				manualChunks: {
					"frappe-ui": ["frappe-ui"],
				},
			},
		},
	},
	optimizeDeps: {
		include: [
			"frappe-ui > feather-icons",
			"showdown",
			"tailwind.config.js",
			"engine.io-client",
			"@ionic/core",
		],
	},
}))

function copyHtmlEntry() {
	return {
		name: "slhrm-copy-html-entry",
		apply: "build",
		closeBundle() {
			fs.mkdirSync(path.dirname(PWA_HTML_ENTRY), { recursive: true })
			fs.copyFileSync(path.join(PWA_OUT_DIR, "index.html"), PWA_HTML_ENTRY)
			console.log(`Copied index.html -> ${PWA_HTML_ENTRY}`)
		},
	}
}

function getProxyOptions() {
	const config = getCommonSiteConfig()
	const webserver_port = config ? config.webserver_port : 8000
	if (!config) {
		console.log("No common_site_config.json found, using default port 8000")
	}
	return {
		"^/(app|login|api|assets|files|private)": {
			target: `http://127.0.0.1:${webserver_port}`,
			ws: true,
			router: function (req) {
				const site_name = req.headers.host.split(":")[0]
				console.log(`Proxying ${req.url} to ${site_name}:${webserver_port}`)
				return `http://${site_name}:${webserver_port}`
			},
		},
	}
}

function getCommonSiteConfig() {
	let currentDir = path.resolve(".")
	// traverse up till we find frappe-bench with sites directory
	while (currentDir !== "/") {
		if (
			fs.existsSync(path.join(currentDir, "sites")) &&
			fs.existsSync(path.join(currentDir, "apps"))
		) {
			let configPath = path.join(currentDir, "sites", "common_site_config.json")
			if (fs.existsSync(configPath)) {
				return JSON.parse(fs.readFileSync(configPath))
			}
			return null
		}
		currentDir = path.resolve(currentDir, "..")
	}
	return null
}
