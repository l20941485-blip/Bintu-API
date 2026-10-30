/**
 * Fetch readable text from a public URL using Bintu's REST API.
 *
 * Run: node examples/rest_javascript.js https://example.com
 */

const baseUrl = (process.env.BINTU_BASE_URL || "https://bintu-api.onrender.com").replace(/\/$/, "");
const apiKey = process.env.BINTU_API_KEY;
const targetUrl = process.argv[2] || "https://example.com";

if (!apiKey) {
  console.error("Set BINTU_API_KEY before running this example.");
  process.exit(1);
}

const endpoint = `${baseUrl}/api/v1/scrape/text?url=${encodeURIComponent(targetUrl)}`;

const response = await fetch(endpoint, {
  headers: {
    "X-API-Key": apiKey,
    Accept: "application/json",
  },
});

if (!response.ok) {
  console.error(`Request failed: ${response.status} ${response.statusText}`);
  console.error(await response.text());
  process.exit(1);
}

const result = await response.json();

console.log(`url: ${result.url}`);
console.log(`approx_tokens: ${result.approx_tokens}`);
console.log(`truncated: ${result.truncated}`);
console.log(`cache_hit: ${result.cache_hit}`);
console.log(`cache_layer: ${result.cache_layer}`);
console.log("\n--- text preview ---");
console.log(result.text.slice(0, 500));
