# Performs one live health check, REST scrape, and MCP discovery request.`nparam(
  [string]$BaseUrl = "https://bintu-api.onrender.com",
  [string]$ApiKey = $env:BINTU_API_KEY
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
  Write-Error "Set BINTU_API_KEY before running this smoke test."
}

Write-Host "Checking health at $BaseUrl/healthz..."
$health = Invoke-RestMethod -Uri "$BaseUrl/healthz" -Method Get
if ($health.status -ne "ok") {
  Write-Error "Health check failed: $($health | ConvertTo-Json -Compress)"
}
Write-Host "Health check passed."

Write-Host "Checking REST scrape..."
$url = "https://example.com"
$scrape = Invoke-RestMethod `
  -Method Get `
  -Uri "$BaseUrl/api/v1/scrape/text?url=$([uri]::EscapeDataString($url))" `
  -Headers @{ "X-API-Key" = $ApiKey }

if (-not $scrape.text) {
  Write-Error "REST scrape returned no text."
}

Write-Host ("REST scrape passed: {0} approximate tokens." -f $scrape.approx_tokens)

Write-Host "Checking MCP tools/list..."
$headers = @{
  "X-API-Key" = $ApiKey
  "Accept" = "application/json, text/event-stream"
}

$body = @{
  jsonrpc = "2.0"
  id = 1
  method = "tools/list"
  params = @{}
} | ConvertTo-Json -Depth 10

$mcp = Invoke-RestMethod `
  -Method Post `
  -Uri "$BaseUrl/mcp" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body

if (-not ($mcp.result.tools | Where-Object { $_.name -eq "bintu_scrape_text" })) {
  Write-Error "MCP tools/list did not expose bintu_scrape_text."
}

Write-Host "MCP discovery passed."
Write-Host "Smoke test passed."
