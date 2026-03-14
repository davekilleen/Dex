import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { spawn, ChildProcess } from "child_process";
import * as net from "net";
import * as qrcode from "qrcode-terminal";
import * as os from "os";

let tauMirrorProcess: ChildProcess | null = null;
let actualPort: number | null = null;

async function findAvailablePort(startPort: number): Promise<number> {
	for (let port = startPort; port < startPort + 10; port++) {
		const available = await isPortAvailable(port);
		if (available) return port;
	}
	throw new Error(`No available ports found in range ${startPort}-${startPort + 9}`);
}

function isPortAvailable(port: number): Promise<boolean> {
	return new Promise((resolve) => {
		const server = net.createServer();
		server.once("error", () => resolve(false));
		server.once("listening", () => {
			server.close();
			resolve(true);
		});
		server.listen(port, "0.0.0.0");
	});
}

function getLocalIP(): string {
	const interfaces = os.networkInterfaces();
	for (const name of Object.keys(interfaces)) {
		const iface = interfaces[name];
		if (!iface) continue;
		for (const alias of iface) {
			if (alias.family === "IPv4" && !alias.internal) {
				return alias.address;
			}
		}
	}
	return "127.0.0.1";
}

async function startTauMirror(pi: ExtensionAPI): Promise<void> {
	try {
		// Find available port
		const port = await findAvailablePort(3001);
		actualPort = port;

		// Spawn tau-mirror process
		tauMirrorProcess = spawn("npx", ["tau-mirror", "--port", port.toString()], {
			stdio: ["ignore", "pipe", "pipe"],
			detached: false,
		});

		// Track process events (Pendo analytics would go here if configured)
		if (port !== 3001) {
			// Port conflict was resolved
			console.log(`[tau-mirror] Port 3001 occupied, using ${port}`);
		}

		tauMirrorProcess.on("exit", (code) => {
			console.log(`[tau-mirror] Process exited with code ${code}`);
			tauMirrorProcess = null;
			actualPort = null;
		});

		// Give it a moment to start
		await new Promise((resolve) => setTimeout(resolve, 2000));

		// Update status bar
		pi.updateStatusBarItem("tau-mirror-status", {
			text: `Web UI: http://localhost:${port}`,
			tooltip: `Tau-mirror running on port ${port}`,
			priority: 100,
		});

		console.log(`[tau-mirror] Started successfully on port ${port}`);
	} catch (error) {
		console.error("[tau-mirror] Failed to start:", error);
	}
}

function stopTauMirror(pi: ExtensionAPI): void {
	if (tauMirrorProcess) {
		tauMirrorProcess.kill();
		tauMirrorProcess = null;
		actualPort = null;
		pi.updateStatusBarItem("tau-mirror-status", { text: "" });
		console.log("[tau-mirror] Stopped");
	}
}

export default function (pi: ExtensionAPI) {
	async function initialize(ctx: ExtensionContext) {
		// Auto-start on session start
		await startTauMirror(pi);

		// Register /qr command
		pi.registerCommand("qr", {
			description: "Generate QR code for mobile access",
			execute: async () => {
				if (!actualPort) {
					return "Tau-mirror is not running";
				}

				const localIP = getLocalIP();
				const url = `http://${localIP}:${actualPort}`;

				// Generate QR code in terminal
				console.log("\nScan this QR code to access Pi from mobile:\n");
				qrcode.generate(url, { small: true });
				console.log(`\nURL: ${url}\n`);

				return `QR code generated. Scan with your phone to access Pi at ${url}`;
			},
		});

		// Clean shutdown on session end
		ctx.onSessionEnd(() => {
			stopTauMirror(pi);
		});
	}

	return {
		name: "tau-mirror-integration",
		version: "1.0.0",
		description: "Web UI for Pi via tau-mirror - access your session from any browser",
		initialize,
	};
}
