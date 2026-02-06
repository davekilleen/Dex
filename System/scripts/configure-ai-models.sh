#!/bin/bash
# Configure AI models for pi
# Usage: ./configure-ai-models.sh [openrouter_key] [ollama_model]

set -e

MODELS_JSON="$HOME/.pi/agent/models.json"
OPENROUTER_KEY="$1"
OLLAMA_MODEL="${2:-qwen2.5:14b}"

# Ensure directory exists
mkdir -p "$HOME/.pi/agent"

echo "=== Configuring AI Models for Pi ==="
echo ""

# Start building JSON
cat > "$MODELS_JSON" << 'HEADER'
{
  "providers": {
HEADER

FIRST_PROVIDER=true

# Add OpenRouter if key provided
if [[ -n "$OPENROUTER_KEY" ]]; then
    echo "Adding OpenRouter (budget cloud models)..."
    
    if [[ "$FIRST_PROVIDER" == "false" ]]; then
        echo "," >> "$MODELS_JSON"
    fi
    FIRST_PROVIDER=false
    
    cat >> "$MODELS_JSON" << EOF
    "openrouter": {
      "baseUrl": "https://openrouter.ai/api/v1",
      "api": "openai-completions",
      "apiKey": "$OPENROUTER_KEY",
      "models": [
        {
          "id": "moonshotai/kimi-k2.5",
          "name": "Kimi K2.5 (Budget)",
          "input": ["text"],
          "contextWindow": 262144,
          "maxTokens": 32768,
          "cost": { "input": 0.6, "output": 3, "cacheRead": 0, "cacheWrite": 0 }
        },
        {
          "id": "deepseek/deepseek-chat",
          "name": "DeepSeek V3 (Budget)",
          "input": ["text"],
          "contextWindow": 64000,
          "maxTokens": 8192,
          "cost": { "input": 0.14, "output": 0.28, "cacheRead": 0, "cacheWrite": 0 }
        },
        {
          "id": "google/gemini-2.0-flash-exp:free",
          "name": "Gemini Flash (Free)",
          "input": ["text", "image"],
          "contextWindow": 1048576,
          "maxTokens": 8192,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }
      ]
    }
EOF
fi

# Check if Ollama is available and add it
if command -v ollama &> /dev/null; then
    # Check if the model is installed
    if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
        echo "Adding Ollama (offline model: $OLLAMA_MODEL)..."
        
        if [[ "$FIRST_PROVIDER" == "false" ]]; then
            echo "," >> "$MODELS_JSON"
        fi
        FIRST_PROVIDER=false
        
        # Determine context window based on model
        case "$OLLAMA_MODEL" in
            *"72b"*|*"70b"*)
                CONTEXT=65536
                ;;
            *"32b"*|*"33b"*)
                CONTEXT=32768
                ;;
            *)
                CONTEXT=32768
                ;;
        esac
        
        cat >> "$MODELS_JSON" << EOF
    "ollama": {
      "baseUrl": "http://localhost:11434/v1",
      "api": "openai-completions",
      "apiKey": "ollama",
      "models": [
        {
          "id": "$OLLAMA_MODEL",
          "name": "$(echo $OLLAMA_MODEL | sed 's/:/ /' | awk '{print toupper(substr($1,1,1)) substr($1,2) " " $2}') (Offline)",
          "input": ["text"],
          "contextWindow": $CONTEXT,
          "maxTokens": 8192,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 }
        }
      ]
    }
EOF
    else
        echo "⚠️  Ollama model '$OLLAMA_MODEL' not found. Install with: ollama pull $OLLAMA_MODEL"
    fi
else
    echo "ℹ️  Ollama not installed. Skipping offline model config."
fi

# Close JSON
cat >> "$MODELS_JSON" << 'FOOTER'
  }
}
FOOTER

echo ""
echo "✅ Configuration written to: $MODELS_JSON"
echo ""
echo "=== Configured Models ==="

# Parse and show what was configured
if [[ -n "$OPENROUTER_KEY" ]]; then
    echo "☁️  Budget Cloud (OpenRouter):"
    echo "   - Kimi K2.5"
    echo "   - DeepSeek V3"
    echo "   - Gemini Flash (free tier)"
fi

if command -v ollama &> /dev/null && ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    echo "💻 Offline (Ollama):"
    echo "   - $OLLAMA_MODEL"
fi

echo ""
echo "To use: Open pi, type /model, and select a model"
