import base64
import gzip
import json
from dotenv import load_dotenv
import chainlit as cl
from chainlit.element import ElementBased
import requests
import os
from uuid import uuid4
import logging
from io import BytesIO

load_dotenv(override=True)

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

api_key = os.getenv("AZURE_OPENAI_WHISPER_API_KEY")

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
) if api_key is None or api_key == "" else None

whisper_client = AzureOpenAI(
    api_key=api_key,  
    api_version=os.getenv("AZURE_OPENAI_WHISPER_VERSION"),
    azure_endpoint = os.getenv("AZURE_OPENAI_WHISPER_ENDPOINT"),
    azure_ad_token_provider=token_provider
)

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# DISABLED: Disable the App Insights VERY verbose logger
# logging.getLogger('azure.monitor').setLevel(logging.WARN)
# from azure.monitor.opentelemetry import configure_azure_monitor
# APPLICATIONINSIGHTS_CONNECTIONSTRING = os.getenv("APPLICATIONINSIGHTS_CONNECTIONSTRING")
# if APPLICATIONINSIGHTS_CONNECTIONSTRING:
#     # Configure the Azure Monitor exporter
#     configure_azure_monitor(connection_string=APPLICATIONINSIGHTS_CONNECTIONSTRING)

class APIClient:
    def __init__(self):
        self.base_url = os.getenv("API_BASE_URL")

    def post_message(self, conversation_id, message):
        payload = message if isinstance(message, dict) else {"message": message}
        headers = {'Content-Encoding': 'gzip', 'Content-Type': 'application/json'}
        compressed_payload = gzip.compress(json.dumps(payload).encode('utf-8'))
        response = requests.post(f"{self.base_url}/conversation/{conversation_id}", data=compressed_payload, headers=headers)
        return response.json()
    
    def post_message_stream(self, conversation_id, message):
        payload = message if isinstance(message, dict) else {"message": message}
        headers = {'Content-Encoding': 'gzip', 'Content-Type': 'application/json'}
        compressed_payload = gzip.compress(json.dumps(payload).encode('utf-8'))
        response = requests.post(f"{self.base_url}/conversation/{conversation_id}/stream", data=compressed_payload, headers=headers, stream=True)
        response.raise_for_status()
        result = None
        for line in response.iter_lines():
            if line:
                logger.debug(f"Received line: {line}")
                mark, content = json.loads(line)
                yield [mark, content]
                if mark == "result":
                    result = content
                    break
        
        return result
    
    def get_messages(self, conversation_id):
        response = requests.get(f"{self.base_url}/conversation/{conversation_id}")
        return response.json()
    
client = APIClient()
INTRO_MESSAGE = "Hi!"

@cl.on_chat_start
async def setup_agents():
    conversation_id = get_conversation_id()  
    if conversation_id is None or conversation_id == "":
        conversation_id = str(uuid4())
        logging.info(f"Starting new conversation with id: {conversation_id}")
        cl.user_session.set('conversation_id', conversation_id)
        cl.user_session.set('last_seen_message_index', 0)
        
        messages = await send_message(conversation_id, INTRO_MESSAGE)        
        await display_messages(messages)
    else:
        logging.info(f"Resuming conversation with id: {conversation_id}")
        messages = client.get_messages(conversation_id) or []
        await display_messages(messages)

def get_conversation_id():
    conversation_id = cl.user_session.get('conversation_id')
    logging.info(f"conversation_id: {conversation_id}")  
    return conversation_id


@cl.on_message
async def run_conversation(message: cl.Message):
    conversation_id = get_conversation_id()    
    
    # Processing images exclusively
    images_files = [file for file in message.elements if "image" in file.mime]

    # Read the first image
    images = []
    for image in images_files:
        with open(image.path, "rb") as f:
            # Read the image file as bytes        
            encoded_image = base64.b64encode(f.read()).decode('utf-8')
            images.append({"mimeType": images_files[0].mime, "data": encoded_image})
        
    
    new_messages = await send_message(conversation_id, {
        "message": message.content,
        "media": images if len(images) > 0 else None
    })    
    
    await display_messages(new_messages)

async def send_message(conversation_id, message, speak=False):
    logging.info(f"conversation_id: {conversation_id}, message: {message}")
    # new_messages = client.post_message(conversation_id, message)
    
    # return new_messages
    # tts sentence end mark
    collected_messages = []
    tts_sentence_end = [ ".", "!", "?", ";", "。", "！", "？", "；", "\n" ]
    
    msg = None
    tool = None
    name = None
    for mark, content in client.post_message_stream(conversation_id, message):
        logger.debug(f"Received mark: {mark}, content: {content}")
        if mark == "start":
            name = content
        if mark == "delta":            
            msg = cl.Message(content="", author=name) if msg is None else msg
            text = content["content"]
            tool_calls = content["tool_calls"]
            if text is not None:
                collected_messages.append(text)
                await msg.stream_token(text)
                if text in tts_sentence_end:
                    speech = " ".join(collected_messages).strip()
                    # Sub-optimal solution, Chainlit has issues playing multiple audio files
                    # await speak_message(msg, speech)
                    collected_messages = []
            if tool_calls:
                tool = cl.Step(name = tool_calls[0]["function"]["name"]) if tool is None else tool
                await tool.stream_token(tool_calls[0]["function"]["arguments"], is_input=True)
                                
        if mark == "function_result" and tool is not None:
            await tool.stream_token(json.dumps(content), is_input=False)
            await tool.send()
            tool = None        
        if mark == "end":
            await msg.update()
            await msg.send()
        if mark == "response":
            response, usage = content
            if speak:
                await speak_message(msg, response["content"])
            break
    
    return []

async def speak(msg: cl.Message, speech_message: str):
    output_name, output_audio = await text_to_speech(speech_message, "audio/wav")
    
    output_audio_el = cl.Audio(
        name="",  # Keep name empty to avoid displaying the label
        auto_play=True,
        mime="audio/wav",
        path=output_audio
    )
    
    msg.elements = [output_audio_el]
    await msg.update()

async def display_messages(new_messages):
    
    logging.info(f"new_messages: {new_messages}")
    
    for index, message in enumerate(new_messages):
        if message['content']:
            # When content is list get the first element
            if isinstance(message['content'], list):
                content = message['content'][0]["text"] # TODO fix to get firt text element
            else:
                content = message['content']
            if content.rstrip() == "TERMINATE":
                break
            
            content = content.replace("TERMINATE", "").strip()
            
            if message["role"] == "system":
                continue

            if message["role"] == "user" and not "name" in message:
                message["name"] = "Customer"

            if message['name'] == "Customer" or message['role'] == "user":
                continue

            await cl.Message(
                    author=message["name"],
                    content=content,                
                ).send() 

def speech_to_text(audio_file):
    response = whisper_client.audio.transcriptions.create(
        model="whisper", file=audio_file
    )

    logger.debug(f"Transcription response: {response}")

    return response.text

# @cl.step(type="tool")
async def text_to_speech(text: str, mime_type: str):
    import os
    from elevenlabs import ElevenLabs

    # Initialize ElevenLabs client
    client = ElevenLabs(api_key=os.getenv('ELEVENLABS_API_KEY'))

    voice_id = os.getenv('ELEVENLABS_VOICE_ID')
    if not voice_id:
        logger.error("ELEVENLABS_VOICE_ID environment variable is not set. Please provide a valid ElevenLabs voice ID from your account.")
        raise ValueError("ELEVENLABS_VOICE_ID environment variable is required for ElevenLabs TTS.")
    model = os.getenv('ELEVENLABS_MODEL', 'eleven_turbo_v2_5')

    filename = "./.files/ai.mp3"

    try:
        # Generate speech using ElevenLabs
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model,
            output_format="mp3_44100_128"
        )

        # Save the audio to a file
        with open(filename, "wb") as audio_file:
            for chunk in audio_generator:
                audio_file.write(chunk)

        logger.info(f"Speech synthesized for text: {text[:50]}...")

    except Exception as e:
        logger.error(f"ElevenLabs TTS error: {e}")
        logger.error("Did you set the ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID?")
        raise

    return "audio", filename

@cl.on_audio_start
async def on_audio_start():
    logger.debug("Audio started")
    # NOTE: This is required to enable the audio stream
    return True

from pydub import AudioSegment
@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    audio_buffer: AudioSegment = cl.user_session.get("audio_buffer")
    
    if audio_buffer is None:
        logger.debug(f"Audio buffer created, format {chunk.mimeType}")
        audio_buffer = AudioSegment.empty()

    # For now, write the chunks to a buffer and transcribe the whole audio at the end
    audio_buffer += AudioSegment(
        data=chunk.data,
        sample_width=2,  # 16-bit
        frame_rate=24000,
        channels=2)
    cl.user_session.set("audio_buffer", audio_buffer)


@cl.on_audio_end
async def on_audio_end():
    # Get the audio buffer from the session
    audio_buffer: AudioSegment = cl.user_session.get("audio_buffer")
    audio_file = BytesIO()
    audio_buffer = audio_buffer.set_frame_rate(44100)
    audio_buffer.export(audio_file, format="wav")
    
    whisper_input = ("input_audio.wav", audio_file, "wav")
    transcription = speech_to_text(whisper_input)
    
    # input_audio_el = cl.Audio(
    #     mime="wav", content=audio_file.getvalue(), 
    #     name="" # Keep name empty to avoid displaying the label
    # )    
    await cl.Message(
        author="You", 
        type="user_message",
        content=transcription,
        # elements=[input_audio_el]
    ).send()

    conversation_id = get_conversation_id()    
    
    new_messages = await send_message(conversation_id, transcription, speak=True)    
    
    # await display_messages(new_messages)
    
    # speech_message = new_messages[-1]["content"]
    
    # await speak_message(audio_mime_type, speech_message)

async def speak_message(audio_mime_type, speech_message):
    # Clear markdown formatting, especially the asterisks
    speech_message = speech_message.replace("*", "")
    output_name, output_audio = await text_to_speech(speech_message, audio_mime_type)
    
    output_audio_el = cl.Audio(
        name="",  # Keep name empty to avoid displaying the label
        auto_play=True,
        mime="audio/wav",
        path=output_audio
    )
    answer_message = await cl.Message(content="").send()

    answer_message.elements = [output_audio_el]
    await answer_message.update()
    