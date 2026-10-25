# Security Notes

## RENDER_JS_ENABLED

**Default**: `False` (off by default)

**When enabled** (`RENDER_JS_ENABLED=true`):
- JavaScript rendering boots Playwright/Chromium on every fetch
- Incurs 2-4s startup latency and ongoing RAM costs
- **Only enable on paid infrastructure plans** that cover these costs
- Do NOT enable on free-tier infrastructure

**Security**: JavaScript rendering introduces a TOCTOU (Time-of-Check-to-Time-of-Use) 
DNS rebinding risk. The service resolves the target hostname at fetch time and pins 
the connection to that IP. If an attacker controls DNS and it resolves to a different 
IP between the initial check and actual use, SSRF could occur. The default-off 
state mitigates this risk.

**Operation**: To enable, set `RENDER_JS_ENABLED=true` in the environment 
variables. A startup warning will be logged when the service begins.

**Related Controls**:
- S7: Multicast address blocking (224.0.0.0/4, ff00::/8)
- S8: Port allow-list (80/443 + ALLOWED_PORTS)
- S9: JS-render DNS rebinding TOCTOU (default-off mitigation)