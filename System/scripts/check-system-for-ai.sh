#!/bin/bash
# Check system capabilities for local AI models
# Used by /ai-setup skill

echo "=== System Check for Local AI ==="
echo ""

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macOS"
    
    # Get macOS version
    MACOS_VERSION=$(sw_vers -productVersion)
    echo "OS: macOS $MACOS_VERSION"
    
    # Get chip type
    CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown")
    if [[ "$CHIP" == *"Apple"* ]]; then
        CHIP_TYPE="Apple Silicon"
        # Get specific chip (M1, M2, etc.)
        CHIP_MODEL=$(system_profiler SPHardwareDataType | grep "Chip" | awk -F': ' '{print $2}')
        echo "Chip: $CHIP_MODEL (Apple Silicon) ✅ Great for local AI"
    else
        CHIP_TYPE="Intel"
        echo "Chip: Intel ⚠️ Local AI will be slower"
    fi
    
    # Get RAM
    RAM_BYTES=$(sysctl -n hw.memsize)
    RAM_GB=$((RAM_BYTES / 1024 / 1024 / 1024))
    echo "RAM: ${RAM_GB} GB"
    
    # Get available disk space
    DISK_AVAILABLE=$(df -h / | tail -1 | awk '{print $4}')
    echo "Disk Available: $DISK_AVAILABLE"
    
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="Linux"
    echo "OS: Linux"
    
    # Get RAM
    RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    RAM_GB=$((RAM_KB / 1024 / 1024))
    echo "RAM: ${RAM_GB} GB"
    
    # Check for GPU
    if command -v nvidia-smi &> /dev/null; then
        GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo "None")
        echo "GPU: $GPU"
    else
        echo "GPU: None detected (CPU only)"
    fi
    
    CHIP_TYPE="x86"
    
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    OS="Windows"
    echo "OS: Windows"
    RAM_GB=16  # Default, would need PowerShell for accurate
    CHIP_TYPE="x86"
fi

echo ""
echo "=== Ollama Status ==="

# Check if Ollama is installed
if command -v ollama &> /dev/null; then
    echo "Ollama: ✅ Installed"
    OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    echo "Version: $OLLAMA_VERSION"
    
    # Check if Ollama is running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Status: ✅ Running"
        
        # List installed models
        echo ""
        echo "Installed models:"
        ollama list 2>/dev/null || echo "  (none)"
    else
        echo "Status: ⚠️ Not running"
        echo "  Start with: ollama serve"
    fi
else
    echo "Ollama: ❌ Not installed"
    echo "  Install from: https://ollama.ai/download"
fi

echo ""
echo "=== Recommendation ==="

# Recommend model based on RAM
if [[ $RAM_GB -ge 64 ]]; then
    echo "With ${RAM_GB}GB RAM, you can run the largest models!"
    echo "Recommended: qwen2.5:72b (excellent quality)"
    echo "Alternative: llama3.1:70b"
    RECOMMENDED_MODEL="qwen2.5:72b"
elif [[ $RAM_GB -ge 32 ]]; then
    echo "With ${RAM_GB}GB RAM, you can run large models."
    echo "Recommended: qwen2.5:32b (great quality)"
    echo "Alternative: deepseek-coder:33b"
    RECOMMENDED_MODEL="qwen2.5:32b"
elif [[ $RAM_GB -ge 16 ]]; then
    echo "With ${RAM_GB}GB RAM, you can run medium models."
    echo "Recommended: qwen2.5:14b (good quality)"
    echo "Alternative: mistral-nemo:12b"
    RECOMMENDED_MODEL="qwen2.5:14b"
elif [[ $RAM_GB -ge 8 ]]; then
    echo "With ${RAM_GB}GB RAM, you can run smaller models."
    echo "Recommended: qwen2.5:7b (decent quality)"
    echo "Alternative: llama3.1:8b"
    RECOMMENDED_MODEL="qwen2.5:7b"
else
    echo "With ${RAM_GB}GB RAM, local AI will be challenging."
    echo "Consider: Budget cloud models instead"
    RECOMMENDED_MODEL="none"
fi

echo ""
echo "=== Summary ==="
echo "RECOMMENDED_MODEL=$RECOMMENDED_MODEL"
echo "RAM_GB=$RAM_GB"
echo "CHIP_TYPE=$CHIP_TYPE"
echo "OS=$OS"
