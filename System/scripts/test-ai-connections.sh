#!/bin/bash
# Test AI model connections
# Used by the $ai-setup and $ai-status skills

echo "=== Testing AI Connections ==="
echo ""

# Test OpenRouter
echo "☁️  OpenRouter (Budget Cloud):"
MODELS_JSON="$HOME/.pi/agent/models.json"

if [[ -f "$MODELS_JSON" ]] && grep -q "openrouter" "$MODELS_JSON"; then
    # Extract API key
    OPENROUTER_KEY=$(grep -A2 '"openrouter"' "$MODELS_JSON" | grep 'apiKey' | sed 's/.*"apiKey": "\([^"]*\)".*/\1/')
    
    if [[ -n "$OPENROUTER_KEY" && "$OPENROUTER_KEY" != "null" ]]; then
        # Test the connection
        RESPONSE=$(curl -s -w "\n%{http_code}" \
            -H "Authorization: Bearer $OPENROUTER_KEY" \
            "https://openrouter.ai/api/v1/auth/key" 2>/dev/null)
        
        HTTP_CODE=$(echo "$RESPONSE" | tail -1)
        BODY=$(echo "$RESPONSE" | head -n -1)
        
        if [[ "$HTTP_CODE" == "200" ]]; then
            echo "   Status: ✅ Connected"
            
            # Try to get credit balance
            CREDITS=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"\${d.get('data',{}).get('limit_remaining', 'unknown')}\")" 2>/dev/null || echo "unknown")
            echo "   Credits: $CREDITS"
        else
            echo "   Status: ❌ Connection failed (HTTP $HTTP_CODE)"
            echo "   Check your API key at openrouter.ai/keys"
        fi
    else
        echo "   Status: ⚠️ No API key configured"
    fi
else
    echo "   Status: Not configured"
    echo "   Set up with: $ai-setup"
fi

echo ""

# Test Ollama
echo "💻 Ollama (Offline):"

if command -v ollama &> /dev/null; then
    echo "   Installed: ✅ Yes"
    
    # Check if running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "   Running: ✅ Yes"
        
        # List models
        MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print "   - " $1}')
        if [[ -n "$MODELS" ]]; then
            echo "   Models:"
            echo "$MODELS"
        else
            echo "   Models: None installed"
            echo "   Install with: ollama pull qwen2.5:14b"
        fi
    else
        echo "   Running: ❌ No"
        echo "   Start with: ollama serve"
    fi
else
    echo "   Installed: ❌ No"
    echo "   Install from: https://ollama.ai/download"
fi

echo ""

# Test OpenAI / Codex premium
echo "🌟 GPT-5.5 (Premium):"

# Check for OpenAI API key
if [[ -n "$OPENAI_API_KEY" ]]; then
    echo "   API Key: ✅ Set (env var)"
elif [[ -f "$HOME/.pi/agent/auth.json" ]]; then
    echo "   API Key: ✅ Codex/Pi auth present"
else
    echo "   API Key: ⚠️ No OPENAI_API_KEY found; may still be using Codex/Pi subscription"
fi

# Quick connectivity test
if curl -s --max-time 5 https://api.openai.com > /dev/null 2>&1; then
    echo "   Connection: ✅ Reachable"
else
    echo "   Connection: ⚠️ Cannot reach API (offline?)"
fi

echo ""
echo "=== Summary ==="

# Build summary
BUDGET_OK=false
OFFLINE_OK=false

if [[ -f "$MODELS_JSON" ]] && grep -q "openrouter" "$MODELS_JSON"; then
    BUDGET_OK=true
fi

if command -v ollama &> /dev/null && curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    if ollama list 2>/dev/null | tail -n +2 | grep -q .; then
        OFFLINE_OK=true
    fi
fi

echo "Premium (GPT-5.5): ✅ Available"
if $BUDGET_OK; then
    echo "Budget Cloud:      ✅ Configured"
else
    echo "Budget Cloud:      ❌ Not configured"
fi
if $OFFLINE_OK; then
    echo "Offline Mode:      ✅ Ready"
else
    echo "Offline Mode:      ❌ Not ready"
fi

echo ""
echo "Configure with: $ai-setup"
