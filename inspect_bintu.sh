#!/bin/bash
echo "🔍 BINTU-API INSPECTION REPORT"
echo "================================"
echo "Date: $(date)"
echo ""

# 1. Check Directory Structure
echo "📂 1. DIRECTORY STRUCTURE (bintu_api & tests)"
echo "----------------------------------------------"
find bintu_api tests -type f -name "*.py" | sort
echo ""

# 2. Check Dependencies
echo "📦 2. KEY DEPENDENCIES"
echo "----------------------------------------------"
if [ -f requirements.txt ]; then
    echo "Found in requirements.txt:"
    grep -E "beautifulsoup|trafilatura|playwright|supabase|redis|fastapi" requirements.txt || echo "Not found in requirements.txt"
fi
echo ""

# 3. Inspect Scraper Logic
echo "🕸️ 3. SCRAPER LOGIC (fetcher.py)"
echo "----------------------------------------------"
if [ -f bintu_api/scraper/fetcher.py ]; then
    echo "Lines of code: $(wc -l < bintu_api/scraper/fetcher.py)"
    echo "Key functions defined:"
    grep "^def " bintu_api/scraper/fetcher.py
    echo ""
    echo "Redirect handling:"
    grep -n "REDIRECT_STATUSES\|redirect_count\|Location" bintu_api/scraper/fetcher.py | head -5
else
    echo "File not found."
fi
echo ""

# 4. Inspect Cache Logic
echo "💾 4. CACHE LOGIC (cache.py)"
echo "----------------------------------------------"
if [ -f bintu_api/scraper/cache.py ]; then
    echo "Lines of code: $(wc -l < bintu_api/scraper/cache.py)"
    echo "Class definitions:"
    grep "^class " bintu_api/scraper/cache.py
    echo ""
    echo "Cache Key Logic:"
    grep -n "key\|hash" bintu_api/scraper/cache.py | head -5
else
    echo "File not found."
fi
echo ""

# 5. Inspect Extraction Logic
echo "📝 5. EXTRACTION LOGIC (html_extract.py)"
echo "----------------------------------------------"
if [ -f bintu_api/extraction/html_extract.py ]; then
    echo "Lines of code: $(wc -l < bintu_api/extraction/html_extract.py)"
    echo "Main extraction function:"
    grep "^def extract" bintu_api/extraction/html_extract.py
else
    echo "File not found."
fi
echo ""

# 6. Check for existing Stages directory
echo "🚀 6. EXISTING STAGES"
echo "----------------------------------------------"
if [ -d bintu_api/stages ]; then
    echo "Stages directory already exists. Contents:"
    ls -la bintu_api/stages/
else
    echo "Stages directory does not exist yet."
fi
echo ""

echo "✅ Inspection Complete. Copy this output for analysis."
