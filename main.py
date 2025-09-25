from fastapi import FastAPI, Request, HTTPException
from linebot import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage
from google.adk.agents import Agent
from dotenv import load_dotenv
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams, StdioServerParameters
import os
import uvicorn
import shutil
from google.genai import types
from google.adk.runners import InMemoryRunner

load_dotenv()

# --- Configuration ---
try:
    LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
    DESTINATION_USER_ID = os.environ["DESTINATION_USER_ID"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
except KeyError as e:
    print(f"ERROR: Environment variable {e} not set. Please create a .env file.")
    exit()

# --- Initialize FastAPI and LINE Handler ---
app = FastAPI()
handler = WebhookHandler(LINE_CHANNEL_SECRET)

npx_command = shutil.which("npx")
if not npx_command:
    raise RuntimeError("npx command not found. Please ensure Node.js is installed and in your PATH.")

line_mcp_tool = McpToolset(

    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=npx_command, 
            args=[
                "-y",
                "@line/line-bot-mcp-server",
            ],
            env={
                "CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
                "DESTINATION_USER_ID": DESTINATION_USER_ID
            },
        ),
        # Increase timeout to accommodate first-time npx package download/startup and slow network
        timeout=180.0,
    )
)

# Create the agent
agent = Agent(
    name='line_agent',
    model='gemini-2.0-flash',
    tools=[line_mcp_tool],
    instruction="""
    You are a helpful assistant chatbot for the LINE messaging app.
    Your task is to respond to the user's message.
    To do this, you MUST use the `reply_message` tool.
    The `replyToken` needed for this tool will be provided in the user's input.
    You must call the `reply_message` tool with the provided `replyToken` and your text response.
    """
)

# Runner to execute the agent
runner = InMemoryRunner(agent=agent, app_name='LineBotApp')

# Prewarm MCP toolset on startup to avoid first-call timeouts
@app.on_event("startup")
async def startup_event():
    try:
        await line_mcp_tool.get_tools()
        print("MCP toolset pre-initialized.")
    except Exception as e:
        print(f"Warning: MCP pre-initialization failed: {e}")

# --- Webhook Endpoint ---
@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

# --- LINE Message Handler ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = getattr(event.source, "user_id", None) or "anonymous"
    session_id = user_id

    # Ensure a session exists for this user
    if not runner.session_service.get_session_sync(app_name=runner.app_name, user_id=user_id, session_id=session_id):
        runner.session_service.create_session_sync(app_name=runner.app_name, user_id=user_id, session_id=session_id)

    # Let the agent process the user's message and user ID
    agent_input = f"The user said: '{user_message}'. The replyToken is '{reply_token}'."
    new_message = types.Content(parts=[types.Part(text=agent_input)])

    print(f"Invoking agent with input: {agent_input}")

    # Run the agent synchronously and consume events
    for event in runner.run(user_id=user_id, session_id=session_id, new_message=new_message):
        # Optionally log non-user events
        if getattr(event, "author", None) and event.author != "user":
            print(f"Event from {event.author}: {event.content}")

    print("Agent run completed")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)