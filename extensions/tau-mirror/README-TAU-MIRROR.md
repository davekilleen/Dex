# Tau-Mirror Web UI

Access your Pi session from any device - desktop browser, tablet, or phone.

## Quick Start

1. Start Pi: `pi`
2. Look for: "Web UI: http://localhost:3001" in status bar
3. Open that URL in any browser
4. Chat from web or terminal - both stay in sync

## Mobile Access

Want to use Pi from your phone?

1. Make sure phone is on same WiFi as your computer
2. In Pi terminal, run: `/qr`
3. Scan QR code with phone camera
4. Browser opens automatically → chat from mobile!

## Features

- **Real-time sync:** Type in web UI, see in terminal (and vice versa)
- **Mobile-friendly:** Touch-optimized interface for phones/tablets
- **Voice input:** Click mic icon to speak instead of type
- **Session history:** Browse past conversations
- **Dark mode:** Auto-detects system preference
- **Installable:** Add to home screen (works like native app)

## Troubleshooting

**Web UI won't load:**
- Check status message for actual port (might be 3002, 3003 if 3001 was taken)
- Verify Pi is still running in terminal

**Mobile can't connect:**
- Ensure phone on same WiFi network as computer
- Check firewall settings allow port 3001
- Try re-generating QR code (`/qr`)

**Session disconnected:**
- Refresh browser page (Cmd+R / F5)
- Session history preserved, you can continue chatting

**Port conflict:**
- If another app uses 3001, Pi auto-picks next available port
- Check status bar for actual URL

## Privacy & Security

- Web UI runs **locally only** (not on the internet)
- No authentication required (localhost trust model)
- Your conversations never leave your computer
- Only devices on your WiFi can access (via QR code)

## Technical Details

- **Package:** tau-mirror (https://www.npmjs.com/package/tau-mirror)
- **Default port:** 3001 (auto-increments if occupied)
- **Auto-start:** Launches when Pi starts
- **Clean shutdown:** Terminates when Pi exits

## Advanced

**Change port manually:**
Currently auto-assigned. Manual configuration coming in future update.

**Use on public WiFi:**
Not recommended (no authentication). Use terminal only on untrusted networks.

**Check if running:**
Look for "Web UI: http://localhost:PORT" in Pi status bar.

---

*Powered by tau-mirror - PWA web UI for Pi terminal mirroring*
