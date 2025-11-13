from contextlib import asynccontextmanager
import os
import uuid
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from azure.identity import DefaultAzureCredential

from dotenv import load_dotenv
load_dotenv(override=True)

import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Create a session for the functions to use once, instead of creating a new session for each request
import aiohttp
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    global api_client_session
    api_client_session = aiohttp.ClientSession()
    
    # Regular FastAPI execution
    yield
    
    # Cleanup logic
    await api_client_session.close()
    
app = FastAPI(lifespan=lifespan)

# FastAPI global configuration
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logging.error(f"Unprocessable request: {request} {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

base_url = os.getenv("API_BASE_URL")
async def ask_agents(input_message, conversation_id):
    logger.info(f"Asking agents: {input_message}")
    async with api_client_session.post(f"{base_url}/conversation/{conversation_id}", json={"message": input_message}) as response:
        logger.debug(f"Ask response: {response.status}")
        response.raise_for_status()
        new_messages = await response.json()
        return new_messages

from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.core.messaging import CloudEvent
from azure.communication.callautomation import (
    PhoneNumberIdentifier,
    RecognizeInputType,
    TextSource,
    SsmlSource,
    FileSource
    )

from azure.communication.callautomation.aio import (
    CallAutomationClient
    )
call_automation_client = CallAutomationClient(endpoint=os.getenv("ACS_ENDPOINT"), credential=DefaultAzureCredential())
COGNITIVE_SERVICE_ENDPOINT = os.getenv("COGNITIVE_SERVICE_ENDPOINT")

# Initialize ElevenLabs TTS client
from elevenlabs_utils import get_tts_client
tts_client = get_tts_client()

@app.post("/api/call")
async def incoming_call_handler(req: Request):
    try:
        for event_dict in await req.json():
            event = EventGridEvent.from_dict(event_dict)
            logger.info("Incoming event data: %s", event.data)
            
            # Handle the initial validation event from EventGrid
            # This is performed once when the subscription is created
            if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
                logger.info("Validating WebHook subscription")
                validation_url = event.data['validationUrl']
                validation_code = event.data['validationCode']
                async with aiohttp.ClientSession() as client:
                    await client.get(validation_url)
                
                return JSONResponse(content={"validationResponse": validation_code}, status_code=200)
            
            # Handle the incoming call event
            elif event.event_type =="Microsoft.Communication.IncomingCall":
                logger.info("Incoming call received: data=%s", event.data)  
                if event.data['from']['kind'] =="phoneNumber":
                    caller_id =  event.data['from']["phoneNumber"]["value"]
                else :
                    caller_id =  event.data['from']['rawId'] 
                logger.info("incoming call handler caller id: %s", caller_id)
                
                call_id = uuid.uuid4()
                
                query_parameters = urlencode({ "callerId": caller_id })
                # Quick way to get the callback url from current request full URL, without knowing the host
                original_uri = str(req.url)
                # Must use https for callback url since it is required by ACS
                # See https://learn.microsoft.com/en-us/azure/communication-services/resources/troubleshooting/voice-video-calling/troubleshooting-codes?pivots=calling#troubleshooting-tips
                callback_uri = original_uri.replace("/api/call", f"/api/call/{call_id}?{query_parameters}").replace("http://", "https://")     
                logger.info("callback url: %s",  callback_uri)
                
                incoming_call_context = event.data['incomingCallContext']
                answer_call_result = await call_automation_client.answer_call(
                    incoming_call_context=incoming_call_context,
                    cognitive_services_endpoint=COGNITIVE_SERVICE_ENDPOINT,
                    callback_url=callback_uri)
                
                logger.info("Answered call for connection id: %s", answer_call_result.call_connection_id)
                return JSONResponse(status_code=200, content="")
            else:
                logger.warning("Event type not supported: %s", event.event_type)
            
        return JSONResponse(status_code=200, content="")
    except Exception as ex:
        logger.error(f"Error in incoming_call_handler: {ex}")
        return JSONResponse(status_code=500, content=str(ex))

async def reply_and_wait(replyText, callerId, call_connection_id, context=""):
    try:
        logger.debug("Replying and waiting: %s", replyText)
        connection_client = call_automation_client.get_call_connection(call_connection_id)

        # Generate audio with ElevenLabs and upload to blob storage
        play_source = None
        if replyText != "":
            audio_url = tts_client.synthesize_to_blob_url(replyText)
            play_source = FileSource(url=audio_url)

        await connection_client.start_recognizing_media(
            input_type=RecognizeInputType.SPEECH,
            target_participant=PhoneNumberIdentifier(callerId),
            end_silence_timeout=1, # The final pause of the speaker used to detect the final result that gets generated as speech.
            play_prompt=play_source,
            operation_context=context)
    except Exception as ex:
        logger.error("Error in recognize: %s", ex)

async def play_message(call_connection_id, text_to_play, context):
    logger.debug("Playing message: %s", text_to_play)

    # Generate audio with ElevenLabs and upload to blob storage
    audio_url = tts_client.synthesize_to_blob_url(text_to_play)
    play_source = FileSource(url=audio_url)

    await call_automation_client.get_call_connection(call_connection_id).play_media_to_all(
        play_source,
        operation_context=context)

async def terminate_call(call_connection_id):     
    await call_automation_client.get_call_connection(call_connection_id).hang_up(is_for_everyone=True)  
            
HELLO_PROMPT = "Hello, how may I help you today?"
CHAT_CONTEXT = "ChatContext"
TIMEOUT_SILENCE_PROMPT = "I am sorry, I did not hear anything. If you need assistance, please let me know how I can help you,"
AGENTS_ERROR = "I am sorry, I am unable to assist you at this time. Please try again later."
GOODBYE_PROMPT = "Thank you for calling! I hope I was able to assist you. Have a great day!"
GOODBYE_CONTEXT = "Goodbye"

max_retry_dict = {}
@app.post("/api/call/{contextId}")
async def handle_callback(req: Request):
    try:        
        events = await req.json()
        contextId = req.path_params.get("contextId")
        
        logger.info("Request Json: %s", events)
        for event_dict in events:       
            event = CloudEvent.from_dict(event_dict)
            
            call_connection_id = event.data['callConnectionId']
            logger.info("%s event received for call connection id: %s", event.type, call_connection_id)
            caller_id = req.query_params.get("callerId").strip()
            if "+" not in caller_id:
                caller_id="+".strip()+caller_id.strip()

            logger.info("Call connected: data=%s", event.data)
            if event.type == "Microsoft.Communication.CallConnected":
                max_retry_dict[call_connection_id] = 3
                await reply_and_wait(HELLO_PROMPT, caller_id, call_connection_id, context=CHAT_CONTEXT)
                 
            elif event.type == "Microsoft.Communication.RecognizeCompleted":
                 if event.data['recognitionType'] == "speech": 
                     speech_text = event.data['speechResult']['speech']; 
                     logger.info("Recognition completed, speech_text: %s", speech_text); 
                     if speech_text is not None and len(speech_text) > 0:                      
                          
                        answers = await ask_agents(speech_text, conversation_id=caller_id)
                        # TODO review if and why user resposes are returned in the answers
                        final_answer = "\n".join([answer['content'] for answer in answers if answer['role'] == "assistant"])
                        logger.info("Agent response: %s", final_answer)
                        
                        if final_answer.strip() == "":
                            await reply_and_wait(AGENTS_ERROR, caller_id, call_connection_id, context=CHAT_CONTEXT)
                        else:
                            await reply_and_wait(final_answer, caller_id, call_connection_id, context=CHAT_CONTEXT)
                            # await play_message(call_connection_id, joint_answer, CHAT_CONTEXT)
                            # await reply_and_wait("", caller_id, call_connection_id, context=CHAT_CONTEXT)
                                                 
            elif event.type == "Microsoft.Communication.RecognizeFailed":
                resultInformation = event.data['resultInformation']
                reasonCode = resultInformation['subCode']
                context = event.data['operationContext']
                                
                if reasonCode == 8510 and 0 < max_retry_dict[call_connection_id]:
                    await reply_and_wait(TIMEOUT_SILENCE_PROMPT, caller_id, CHAT_CONTEXT) 
                    max_retry_dict[call_connection_id] -= 1
                else:
                    max_retry_dict.pop(call_connection_id)
                    await play_message(call_connection_id, GOODBYE_PROMPT, GOODBYE_CONTEXT)
                 
            elif event.type == "Microsoft.Communication.PlayCompleted":
                context = event.data['operationContext']    
                if context.lower() == GOODBYE_CONTEXT.lower():
                    await terminate_call(call_connection_id)
                        
        return JSONResponse(status_code=200, content="") 
    except Exception as ex:
        logger.error(f"Error in handle_callback: {ex}")
        return JSONResponse(status_code=500, content=str(ex))
