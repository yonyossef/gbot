#!/bin/bash
# Validate Railway project gregarious-charisma
# Run: ./validate-railway.sh
# Ensure you're logged in first: railway login
# Output saved to railway.info.txt

set -e
cd "$(dirname "$0")"
OUTPUT_FILE="railway.info.txt"

{
echo "=== Railway project validation ==="
echo ""

echo "1. Checking login..."
railway whoami || { echo "❌ Not logged in. Run: railway login"; exit 1; }
echo "✅ Logged in"
echo ""

echo "2. Linking to project gregarious-charisma..."
railway link --project gregarious-charisma
echo "✅ Linked"
echo ""

echo "3. Project status..."
railway status
echo ""

echo "4. Environment variables (names only)..."
railway variables 2>/dev/null | head -20 || echo "(run 'railway variables' for full list)"
echo ""

echo "5. Recent deployment logs..."
railway logs --limit 10 2>/dev/null || echo "(no logs yet)"
echo ""

echo "=== Validation complete ==="
echo ""
echo "Saved at: $(date -Iseconds 2>/dev/null || date)"

} 2>&1 | tee "$OUTPUT_FILE"
echo ""
echo "Output saved to $OUTPUT_FILE"
