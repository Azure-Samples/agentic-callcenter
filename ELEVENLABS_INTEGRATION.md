# ElevenLabs Integration

This document describes the ElevenLabs text-to-speech (TTS) integration for the Agentic Call Center application.

## Overview

The application has been adapted to use **ElevenLabs** for text-to-speech synthesis instead of Azure Cognitive Services Speech. This integration provides high-quality, natural-sounding voices for both the phone call system and web UI.

## Changes Summary

### 1. Infrastructure Changes

#### Storage Account (infra/storage.bicep)
- Added a new blob container `tts-audio` with public blob access
- This container stores ElevenLabs-generated audio files for Azure CallAutomation to play
- Updated outputs to include `ttsAudioContainerName`

#### Main Deployment (infra/main.bicep)
- Added `AZURE_STORAGE_ACCOUNT_NAME` output
- Added `AZURE_STORAGE_TTS_CONTAINER` output

### 2. Application Changes

#### Voice Module (voice/)
- **voice/app.py**: Updated to use ElevenLabs TTS instead of Azure Speech
  - Replaced `SsmlSource` with `FileSource` for playing pre-generated audio
  - TTS audio is generated with ElevenLabs, uploaded to blob storage, and played via URL

- **voice/elevenlabs_utils.py**: New utility module for ElevenLabs integration
  - `ElevenLabsTTS` class for managing TTS operations
  - `synthesize_to_file()`: Generate audio and save to local file
  - `synthesize_to_bytes()`: Generate audio as bytes
  - `synthesize_to_blob_url()`: Generate audio, upload to Azure Blob Storage, return public URL

- **voice/requirements.txt**: Added dependencies
  - `elevenlabs==1.45.0`
  - `azure-storage-blob`

#### UI Module (ui/)
- **ui/chat.py**: Updated `text_to_speech()` function to use ElevenLabs
  - Replaced Azure Speech SDK with ElevenLabs client
  - Simplified audio generation using ElevenLabs streaming API

- **ui/requirements.txt**: Added dependency
  - `elevenlabs==1.45.0`

### 3. Configuration Changes

#### Environment Variables (.env.sample)
Added new required environment variables:
```
ELEVENLABS_API_KEY=<elevenlabs-api-key>
ELEVENLABS_VOICE_ID=<elevenlabs-voice-id>
ELEVENLABS_MODEL=eleven_turbo_v2_5
AZURE_STORAGE_ACCOUNT_NAME=<storage-account-name>
AZURE_STORAGE_TTS_CONTAINER=tts-audio
```

Existing Azure Speech variables are still present but no longer used by the voice/UI modules:
```
SPEECH_KEY=<speech-key>
SPEECH_REGION=<speech-region>
```

## Setup Instructions

### 1. Get ElevenLabs API Credentials

1. Sign up for an ElevenLabs account at https://elevenlabs.io
2. Navigate to your profile settings to get your API key
3. Choose a voice ID from the available voices (default: "Rachel")

### 2. Configure Environment Variables

Update your `.env` file with the following:

```bash
# ElevenLabs Configuration
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=your_chosen_voice_id  # e.g., "Rachel", "Bella", etc.
ELEVENLABS_MODEL=eleven_turbo_v2_5  # Or another model like "eleven_multilingual_v2"

# Azure Storage (automatically set by azd after deployment)
AZURE_STORAGE_ACCOUNT_NAME=your_storage_account_name
AZURE_STORAGE_TTS_CONTAINER=tts-audio
```

### 3. Deploy Infrastructure

The infrastructure changes include the new `tts-audio` blob container. Redeploy using:

```bash
azd up
```

This will:
- Create the new `tts-audio` container in your storage account
- Configure public blob access for the container
- Update environment variables

### 4. Install Dependencies

If running locally, install the updated dependencies:

```bash
# For voice module
cd voice
pip install -r requirements.txt

# For UI module
cd ../ui
pip install -r requirements.txt
```

## Architecture

### Voice Module Flow

1. **User speaks** → Azure CallAutomation recognizes speech
2. **Agent responds** → Text response generated
3. **ElevenLabs synthesizes** → Audio file generated
4. **Upload to Blob Storage** → Audio uploaded to `tts-audio` container
5. **Play audio** → Azure CallAutomation plays audio from public blob URL
6. **Listen for response** → Cycle repeats

### UI Module Flow

1. **User types or speaks** → Message sent to agents
2. **Agent responds** → Text response generated
3. **ElevenLabs synthesizes** → Audio file generated locally
4. **Play audio** → Audio played in browser via Chainlit

## Voice Options

### Available Models

- `eleven_turbo_v2_5` (default) - Fast, high-quality synthesis
- `eleven_multilingual_v2` - Supports multiple languages
- `eleven_monolingual_v1` - English-only, high quality

### Voice IDs

Common voice IDs include:
- `Rachel` - Professional female voice
- `Bella` - Warm female voice
- `Antoni` - Professional male voice
- `Josh` - Casual male voice

You can find all available voices in the ElevenLabs dashboard.

## Cost Considerations

### ElevenLabs Pricing
- Free tier: 10,000 characters/month
- Starter: $5/month for 30,000 characters
- Creator: $22/month for 100,000 characters
- Pro and higher tiers available

### Azure Blob Storage
- Minimal cost for storing temporary audio files
- Files can be cleaned up periodically to reduce costs
- Consider implementing a cleanup policy for old audio files

## Troubleshooting

### Common Issues

**Error: "ElevenLabs API key not provided"**
- Ensure `ELEVENLABS_API_KEY` is set in your `.env` file
- Restart the application after updating environment variables

**Error: "Azure Blob Storage not configured"**
- Ensure `AZURE_STORAGE_ACCOUNT_NAME` is set correctly
- Verify the managed identity has "Storage Blob Data Contributor" role
- Check that the `tts-audio` container exists

**Audio not playing in phone calls**
- Verify the blob container `tts-audio` has public blob access
- Check Azure CallAutomation logs for audio playback errors
- Ensure the blob URL is publicly accessible

**Poor audio quality**
- Try using a different ElevenLabs model (e.g., `eleven_multilingual_v2`)
- Adjust the `output_format` in `elevenlabs_utils.py` for higher bitrate

## Migration Notes

### Reverting to Azure Speech

If you need to revert to Azure Speech Services:

1. Restore the original `voice/app.py` from git history
2. Restore the original `ui/chat.py` from git history
3. Remove `elevenlabs_utils.py`
4. Update requirements.txt files to remove `elevenlabs` dependency
5. Ensure `SPEECH_KEY` and `SPEECH_REGION` are configured

### Hybrid Approach

You can implement a hybrid approach by:
1. Adding a configuration flag (e.g., `USE_ELEVENLABS=true/false`)
2. Conditionally using ElevenLabs or Azure Speech based on the flag
3. Useful for A/B testing or gradual migration

## Performance Notes

- **Latency**: ElevenLabs synthesis + blob upload adds ~500-1000ms latency compared to Azure Speech
- **Quality**: ElevenLabs generally provides more natural-sounding voices
- **Scalability**: Blob storage scales automatically; no infrastructure changes needed

## Future Enhancements

Potential improvements:
1. Implement caching for frequently used phrases
2. Add automatic cleanup of old audio files from blob storage
3. Support for SSML-like controls (emphasis, pauses, etc.)
4. Voice cloning for custom brand voices
5. Streaming audio support to reduce latency
