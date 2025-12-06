# Buyvia Voice Recognition Service

A simple Python Flask server that provides voice-to-text transcription using Google Speech Recognition, optimized for Ghanaian English accents.

## Features

- 🎤 **Google Speech Recognition** - Accurate transcription via Google's API
- 🇬🇭 **Ghana Accent Support** - Automatic pronunciation corrections
- ⚡ **Fast Processing** - Typically < 3 seconds response time
- 🔌 **Simple API** - Easy REST endpoints

## Quick Start

### Prerequisites

1. **Python 3.8+** - [Download Python](https://python.org)
2. **FFmpeg** - Required for audio conversion
   ```bash
   # Windows (using winget)
   winget install ffmpeg
   
   # Or download from https://ffmpeg.org/download.html
   ```

### Running the Service

**Windows:**
```bash
# Double-click start.bat
# Or run in terminal:
cd voice-service
start.bat
```

**Manual:**
```bash
cd voice-service
python -m venv venv
venv\Scripts\activate  
# source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
python server.py
```

The service will start at `http://localhost:5000`

## API Endpoints

### Health Check
```
GET /health
```
Returns: `{"status": "healthy", "service": "Buyvia Voice"}`

### Transcribe Audio
```
POST /transcribe
Content-Type: multipart/form-data

file: <audio file (m4a, wav, mp3, etc.)>
```
Returns:
```json
{
  "success": true,
  "raw_text": "go to cart",
  "normalized_text": "go to cart",
  "command": {
    "type": "navigate",
    "screen": "cart",
    "confidence": 0.95
  }
}
```

### Parse Text (Testing)
```
POST /parse
Content-Type: application/json

{"text": "go to cart"}
```

## Supported Commands

| Say This | Action |
|----------|--------|
| "Go to cart" | Navigate to cart |
| "Go home" | Navigate to home |
| "My orders" | Navigate to orders |
| "Profile" | Navigate to profile |
| "Checkout" | Go to checkout |
| "Search for phones" | Search products |
| "Help" | Show help |

## Ghana Accent Corrections

The service automatically corrects common pronunciation variations:

| Heard | Corrected |
|-------|-----------|
| "cut" | "cart" |
| "cat" | "cart" |
| "card" | "cart" |
| "hom" | "home" |
| "orda" | "order" |

## Connecting from React Native

The app automatically connects to:
- **Android Emulator**: `http://10.0.2.2:5000`
- **iOS Simulator**: `http://localhost:5000`
- **Physical Device**: Set `EXPO_PUBLIC_VOICE_API_URL` in `.env`

For physical devices on the same network:
```env
EXPO_PUBLIC_VOICE_API_URL=http://YOUR_COMPUTER_IP:5000
```

## Troubleshooting

### "Audio conversion failed"
- Install FFmpeg: `winget install ffmpeg`
- Restart terminal after installation

### "Google API error"
- Check internet connection
- Google Speech API has rate limits for free usage

### "Connection refused" from app
- Ensure the service is running
- For physical devices, use your computer's local IP
- Check firewall settings

## Architecture

```
React Native App
      │
      ▼
┌─────────────────┐
│  Voice Service  │ (localhost:5000)
│  (Flask/Python) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Google Speech   │
│ Recognition API │
└─────────────────┘
```
