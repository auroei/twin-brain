#!/usr/bin/env python3
"""
Simple script to verify API key format and test basic connection.
"""

import os
import sys
from pathlib import Path

# Script is in apps/your-twin-brain/scripts/, add src to path
APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR / "src"))

from dotenv import load_dotenv
import google.generativeai as genai

# Import paths from twin_brain package
from twin_brain.paths import ENV_FILE

# Load environment variables from app's .env
load_dotenv(dotenv_path=ENV_FILE)

api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("❌ GEMINI_API_KEY not found in .env file")
    sys.exit(1)

print(f"✅ API key found (length: {len(api_key)} characters)")

# Check format (Gemini API keys typically start with "AIza")
if api_key.startswith("AIza"):
    print("✅ API key format looks correct (starts with 'AIza')")
else:
    print("⚠️  Warning: API key doesn't start with 'AIza' - might be incorrect format")

print("\n🔍 Listing available models...")
try:
    genai.configure(api_key=api_key)
    
    # List available models
    models = genai.list_models()
    print("Available models:")
    for m in models:
        if 'generateContent' in m.supported_generation_methods:
            print(f"  - {m.name}")
    
    # Try different model names (prioritize newer available models)
    model_names_to_try = [
        'gemini-2.0-flash',  # Newer version
        'gemini-flash-latest',  # Latest flash
        'gemini-2.5-flash',  # Even newer
        'gemini-1.5-flash',  # Original
        'gemini-pro-latest',  # Latest pro
        'models/gemini-2.0-flash',
        'models/gemini-flash-latest'
    ]
    
    print("\n🔍 Testing API key with different models...")
    success = False
    
    for model_name in model_names_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Say hello")
            
            if response and response.text:
                print(f"✅ API key works with model '{model_name}'!")
                print(f"   Response: {response.text.strip()}")
                success = True
                break
        except Exception as e:
            # Try next model
            continue
    
    if success:
        sys.exit(0)
    else:
        print("❌ Could not find a working model")
        sys.exit(1)
        
except Exception as e:
    error_msg = str(e)
    print(f"❌ API key test failed: {error_msg}")
    
    if "API_KEY_INVALID" in error_msg:
        print("\n💡 Troubleshooting tips:")
        print("1. Verify the API key is correct (no extra spaces, copied completely)")
        print("2. Check that the Generative Language API is enabled in Google Cloud Console")
        print("3. Ensure the API key has the correct permissions")
        print("4. Try generating a new API key from: https://aistudio.google.com/app/apikey")
        print("5. Wait a few minutes if you just created the key (propagation delay)")
    
    sys.exit(1)
