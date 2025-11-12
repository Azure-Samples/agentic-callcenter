"""
ElevenLabs TTS utility functions for the voice module.
"""
import os
import logging
from elevenlabs import ElevenLabs
from typing import Optional
import tempfile
import uuid
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)


class ElevenLabsTTS:
    """Helper class for ElevenLabs Text-to-Speech operations."""

    def __init__(self, api_key: Optional[str] = None, storage_account_name: Optional[str] = None,
                 storage_container: Optional[str] = None):
        """
        Initialize ElevenLabs TTS client.

        Args:
            api_key: ElevenLabs API key. If not provided, will use ELEVENLABS_API_KEY env var.
            storage_account_name: Azure Storage account name for blob uploads
            storage_container: Azure Storage container name for TTS audio
        """
        self.api_key = api_key or os.getenv('ELEVENLABS_API_KEY')
        if not self.api_key:
            raise ValueError("ElevenLabs API key not provided. Set ELEVENLABS_API_KEY environment variable.")

        self.client = ElevenLabs(api_key=self.api_key)
        self.voice_id = os.getenv('ELEVENLABS_VOICE_ID', 'Rachel')
        self.model = os.getenv('ELEVENLABS_MODEL', 'eleven_turbo_v2_5')

        # Azure Blob Storage configuration
        self.storage_account_name = storage_account_name or os.getenv('AZURE_STORAGE_ACCOUNT_NAME')
        self.storage_container = storage_container or os.getenv('AZURE_STORAGE_TTS_CONTAINER', 'tts-audio')
        self.blob_service_client = None

        if self.storage_account_name:
            try:
                account_url = f"https://{self.storage_account_name}.blob.core.windows.net"
                self.blob_service_client = BlobServiceClient(
                    account_url=account_url,
                    credential=DefaultAzureCredential()
                )
                logger.info(f"Initialized Azure Blob Storage client for account: {self.storage_account_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize Azure Blob Storage client: {e}")
                self.blob_service_client = None

    def synthesize_to_file(self, text: str, output_path: Optional[str] = None) -> str:
        """
        Synthesize text to speech and save to a file.

        Args:
            text: Text to synthesize
            output_path: Path to save the audio file. If None, creates a temp file.

        Returns:
            Path to the generated audio file
        """
        if output_path is None:
            # Create a temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            output_path = temp_file.name
            temp_file.close()

        try:
            logger.info(f"Synthesizing text with ElevenLabs (voice: {self.voice_id}): {text[:100]}...")

            # Generate speech using ElevenLabs
            audio_generator = self.client.text_to_speech.convert(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model,
                output_format="mp3_44100_128"
            )

            # Save the audio to a file
            with open(output_path, "wb") as audio_file:
                for chunk in audio_generator:
                    audio_file.write(chunk)

            logger.info(f"Speech synthesized successfully to: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"ElevenLabs TTS error: {e}")
            raise

    def synthesize_to_bytes(self, text: str) -> bytes:
        """
        Synthesize text to speech and return as bytes.

        Args:
            text: Text to synthesize

        Returns:
            Audio data as bytes
        """
        try:
            logger.info(f"Synthesizing text with ElevenLabs (voice: {self.voice_id}): {text[:100]}...")

            # Generate speech using ElevenLabs
            audio_generator = self.client.text_to_speech.convert(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model,
                output_format="mp3_44100_128"
            )

            # Collect all chunks
            audio_bytes = b''
            for chunk in audio_generator:
                audio_bytes += chunk

            logger.info(f"Speech synthesized successfully ({len(audio_bytes)} bytes)")
            return audio_bytes

        except Exception as e:
            logger.error(f"ElevenLabs TTS error: {e}")
            raise


    def synthesize_to_blob_url(self, text: str) -> str:
        """
        Synthesize text to speech, upload to Azure Blob Storage, and return the public URL.

        Args:
            text: Text to synthesize

        Returns:
            Public URL of the uploaded audio file

        Raises:
            ValueError: If blob storage is not configured
        """
        if not self.blob_service_client:
            raise ValueError("Azure Blob Storage not configured. Set AZURE_STORAGE_ACCOUNT_NAME.")

        try:
            # Generate a unique filename
            blob_name = f"{uuid.uuid4()}.mp3"

            logger.info(f"Synthesizing text with ElevenLabs (voice: {self.voice_id}): {text[:100]}...")

            # Generate speech using ElevenLabs
            audio_generator = self.client.text_to_speech.convert(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model,
                output_format="mp3_44100_128"
            )

            # Collect all chunks into bytes
            audio_bytes = b''
            for chunk in audio_generator:
                audio_bytes += chunk

            logger.info(f"Speech synthesized successfully ({len(audio_bytes)} bytes)")

            # Upload to blob storage
            blob_client = self.blob_service_client.get_blob_client(
                container=self.storage_container,
                blob=blob_name
            )

            blob_client.upload_blob(audio_bytes, overwrite=True, content_settings={
                'content_type': 'audio/mpeg'
            })

            # Generate public URL
            blob_url = f"https://{self.storage_account_name}.blob.core.windows.net/{self.storage_container}/{blob_name}"
            logger.info(f"Audio uploaded to blob storage: {blob_url}")

            return blob_url

        except Exception as e:
            logger.error(f"Error uploading audio to blob storage: {e}")
            raise


# Singleton instance for reuse
_tts_instance: Optional[ElevenLabsTTS] = None


def get_tts_client() -> ElevenLabsTTS:
    """Get or create a singleton ElevenLabs TTS client."""
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = ElevenLabsTTS()
    return _tts_instance
