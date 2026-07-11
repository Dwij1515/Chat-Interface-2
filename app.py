import requests
import re
import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session
from groq import Groq
from dotenv import load_dotenv
import logging

# LangChain imports
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from tool.composia_sdk import ComposiaSDK

# Initialize Composia SDK
composia = ComposiaSDK(
    weather_api_key=os.getenv("OPENWEATHER_API_KEY"),
    gmail_credentials_path=os.getenv("GOOGLE_CLIENT_SECRET_FILE"),
    google_credentials_path=os.getenv("GOOGLE_CLIENT_SECRET_FILE")
)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# Initialize Groq client
try:
    groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
    logger.info("Groq client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")
    groq_client = None

# Initialize LangChain Groq client
try:
    langchain_llm = ChatGroq(
        api_key=os.getenv('GROQ_API_KEY'),
        model_name="llama-3.1-8b-instant",
        temperature=0.7
    )
    logger.info("LangChain Groq client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize LangChain Groq client: {e}")
    langchain_llm = None

# Available models (you can expand this list)
AVAILABLE_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile"
]

# Simple in-memory storage (in production, use a proper database)
chat_sessions = {}
user_profiles = {}

def initialize_session():
    """Initialize session with default values"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())

    if 'current_chat_id' not in session:
        session['current_chat_id'] = None

    if 'user_profile' not in session:
        session['user_profile'] = {
            'name': None,
            'preferences': {},
            'created_at': datetime.now().isoformat()
        }

def create_new_chat(title=None):
    """Create a new chat session"""
    # Ensure session is initialized
    if 'user_id' not in session:
        initialize_session()

    chat_id = str(uuid.uuid4())
    user_id = session.get('user_id')

    if not user_id:
        raise ValueError("User ID not found in session")

    if title is None:
        title = f"Chat {datetime.now().strftime('%m/%d %H:%M')}"

    chat_data = {
        'id': chat_id,
        'title': title,
        'messages': [],
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'user_id': user_id
    }

    if user_id not in chat_sessions:
        chat_sessions[user_id] = {}

    chat_sessions[user_id][chat_id] = chat_data
    session['current_chat_id'] = chat_id
    session.modified = True

    return chat_data

def get_current_chat():
    """Get the current active chat session"""
    user_id = session.get('user_id')
    chat_id = session.get('current_chat_id')

    if not user_id or not chat_id:
        return None

    return chat_sessions.get(user_id, {}).get(chat_id)

def update_chat_title(chat_id, title):
    """Update chat title"""
    user_id = session.get('user_id')
    if user_id and chat_id in chat_sessions.get(user_id, {}):
        chat_sessions[user_id][chat_id]['title'] = title
        chat_sessions[user_id][chat_id]['updated_at'] = datetime.now().isoformat()
        return True
    return False

# LangChain Weather Tool using ComposiaSDK
@tool
def get_weather_for_city(city_name: str) -> str:
    """Get current weather information for a specific city.

    Args:
        city_name: The name of the city to get weather for

    Returns:
        A string containing the current weather information
    """
    res = composia.get_weather(city_name)
    if "error" in res:
        return f"Error: {res['error']}"
    return f"The current weather in {res['location']} is {res['temperature']}°C with {res['description']}. The humidity is {res['humidity']}% and wind speed is {res['wind_speed']} m/s."

# LangChain Email Tools using ComposiaSDK
@tool
def get_latest_emails(confirm_fetch: bool = True) -> str:
    """Retrieve a list of the latest emails from Gmail, including the top important emails.

    Args:
        confirm_fetch: Set to True to confirm fetching emails.

    Returns:
        A formatted string listing the latest emails (sender, subject, date, id).
    """
    res = composia.get_latest_emails()
    if isinstance(res, dict) and "error" in res:
        return f"Error: {res['error']}"
    if not res:
        return "No emails found in the inbox."
    
    lines = ["Latest Emails:"]
    for i, email in enumerate(res, 1):
        lines.append(f"{i}. [ID: {email['id']}] From: {email['from']} | Subject: {email['subject']} | Date: {email['date']}")
    return "\n".join(lines)

@tool
def get_emails_between_dates(start_date: str, end_date: str) -> str:
    """Retrieve emails received between two specific dates.

    Args:
        start_date: The start date in YYYY/MM/DD format.
        end_date: The end date in YYYY/MM/DD format.

    Returns:
        A formatted string listing the emails in that range.
    """
    res = composia.get_emails_between_dates(start_date, end_date)
    if isinstance(res, dict) and "error" in res:
        return f"Error: {res['error']}"
    if not res:
        return f"No emails found between {start_date} and {end_date}."
    
    lines = [f"Emails between {start_date} and {end_date}:"]
    for i, email in enumerate(res, 1):
        lines.append(f"{i}. [ID: {email['id']}] From: {email['from']} | Subject: {email['subject']} | Date: {email['date']}")
    return "\n".join(lines)

@tool
def search_emails_by_subject(subject_query: str) -> str:
    """Search emails in the inbox that contain a specific keyword in their subject header.

    Args:
        subject_query: The subject keyword/phrase to search for.

    Returns:
        A formatted string listing matching emails.
    """
    res = composia.search_emails_by_subject(subject_query)
    if isinstance(res, dict) and "error" in res:
        return f"Error: {res['error']}"
    if not res:
        return f"No emails found with subject containing '{subject_query}'."
    
    lines = [f"Search results for subject '{subject_query}':"]
    for i, email in enumerate(res, 1):
        lines.append(f"{i}. [ID: {email['id']}] From: {email['from']} | Subject: {email['subject']} | Date: {email['date']}")
    return "\n".join(lines)

@tool
def save_email_attachments(email_id: str) -> str:
    """Download and save all file attachments for a specific email by its ID.

    Args:
        email_id: The unique ID of the email message.

    Returns:
        A success message listing saved file paths, or an error description.
    """
    res = composia.save_attachments(email_id)
    if isinstance(res, dict) and "error" in res:
        return f"Error saving attachments: {res['error']}"
    if not res:
        return "No attachments found for this email."
    
    files = [f["filepath"] for f in res]
    return f"Successfully saved attachments to: {', '.join(files)}"

# Initialize LangChain tools and agent
def initialize_langchain_agent(model_name: str = "llama-3.1-8b-instant"):
    """Initialize LangChain agent with weather and email tools from ComposiaSDK"""
    try:
        # Update the LLM model if different from default
        if langchain_llm.model_name != model_name:
            updated_llm = ChatGroq(
                api_key=os.getenv('GROQ_API_KEY'),
                model_name=model_name,
                temperature=0.7
            )
        else:
            updated_llm = langchain_llm

        # Define the tools available to the agent
        tools = [
            get_weather_for_city,
            get_latest_emails,
            get_emails_between_dates,
            search_emails_by_subject,
            save_email_attachments
        ]

        # Create the prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a helpful AI assistant. Answer user queries. If you need to use a tool to answer the query, call the tool directly. Do not explain that you are calling a tool."""),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])

        # Create the agent
        agent = create_tool_calling_agent(updated_llm, tools, prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

        return agent_executor
    except Exception as e:
        logger.error(f"Failed to initialize LangChain agent: {e}")
        return None

@app.route('/')
def index():
    """Render the main chat interface"""
    initialize_session()

    # Create a new chat if none exists
    if not session.get('current_chat_id'):
        create_new_chat("New Chat")

    return render_template('index.html', models=AVAILABLE_MODELS)
# Native Groq Tool Calling Configuration
GROQ_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_for_city",
            "description": "Get current weather information for a specific city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_name": {
                        "type": "string",
                        "description": "The name of the city to get weather for."
                    }
                },
                "required": ["city_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_emails",
            "description": "Retrieve a list of the latest emails from Gmail, including the top important emails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirm_fetch": {
                        "type": "boolean",
                        "description": "Set to True to confirm fetching emails."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_emails_between_dates",
            "description": "Retrieve emails received between two specific dates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "The start date in YYYY/MM/DD format."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "The end date in YYYY/MM/DD format."
                    }
                },
                "required": ["start_date", "end_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_emails_by_subject",
            "description": "Search emails in the inbox that contain a specific keyword in their subject header.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject_query": {
                        "type": "string",
                        "description": "The subject keyword/phrase to search for."
                    }
                },
                "required": ["subject_query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_email_attachments",
            "description": "Download and save all file attachments for a specific email by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": "The unique ID of the email message."
                    }
                },
                "required": ["email_id"]
            }
        }
    }
]

def execute_tool(name, arguments):
    import json
    try:
        logger.info(f"Executing tool {name} with args {arguments}")
        if name == "get_weather_for_city":
            city_name = arguments.get("city_name")
            res = composia.get_weather(city_name)
            if "error" in res:
                return json.dumps({"error": res["error"]})
            return json.dumps({
                "location": res["location"],
                "temperature": f"{res['temperature']}°C",
                "description": res["description"],
                "humidity": f"{res['humidity']}%",
                "wind_speed": f"{res['wind_speed']} m/s"
            })
        elif name == "get_latest_emails":
            res = composia.get_latest_emails()
            return json.dumps(res)
        elif name == "get_emails_between_dates":
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")
            res = composia.get_emails_between_dates(start_date, end_date)
            return json.dumps(res)
        elif name == "search_emails_by_subject":
            subject_query = arguments.get("subject_query")
            res = composia.search_emails_by_subject(subject_query)
            return json.dumps(res)
        elif name == "save_email_attachments":
            email_id = arguments.get("email_id")
            res = composia.save_attachments(email_id)
            return json.dumps(res)
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        return json.dumps({"error": str(e)})
    return json.dumps({"error": f"Unknown tool name: {name}"})

def run_groq_tool_calling(user_message, selected_model, current_chat):
    import json
    try:
        if not groq_client:
            return None
            
        user_profile = session.get('user_profile', {})
        user_name = user_profile.get('name', '')
        
        system_message = (
            "You are a helpful AI assistant. You have access to real-time weather and email tools from ComposiaSDK. "
            "Use the appropriate tools to answer the user's questions about weather, emails, and attachments. "
            "When users ask questions like 'Should I wear a jacket in Paris?' or 'Is it raining in London?', "
            "first call the weather tool to get the current temperature/condition, and then answer their question "
            "incorporating the real-time weather data."
        )
        if user_name:
            system_message += f" The user's name is {user_name}."
            
        messages = [{"role": "system", "content": system_message}]
        
        recent_messages = current_chat['messages'][-10:]
        # Exclude the user message we just appended in route (will append manually)
        for msg in recent_messages[:-1]:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        messages.append({"role": "user", "content": user_message})
        
        logger.info("Calling Groq API for tool selection...")
        response = groq_client.chat.completions.create(
            model=selected_model,
            messages=messages,
            tools=GROQ_TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=1024
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        if tool_calls:
            messages.append(response_message)
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                tool_output = execute_tool(function_name, function_args)
                
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": tool_output
                })
                
            logger.info("Calling Groq API with tool output...")
            second_response = groq_client.chat.completions.create(
                model=selected_model,
                messages=messages
            )
            return second_response.choices[0].message.content
        else:
            return response_message.content
    except Exception as e:
        logger.error(f"Failed native Groq tool calling: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages and get AI responses using LangChain"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        selected_model = data.get('model', 'llama-3.1-8b-instant')

        if not user_message:
            return jsonify({'error': 'Message cannot be empty'}), 400

        initialize_session()

        # Get or create current chat
        current_chat = get_current_chat()
        if not current_chat:
            current_chat = create_new_chat()

        # Add user message to chat history
        user_msg = {
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        }
        current_chat['messages'].append(user_msg)

        # Intercept specific weather and email commands for high reliability
        msg_lower = user_message.lower()
        intercepted = False
        ai_response = ""
        model_used = selected_model

        # 1. Weather command
        weather_match = re.search(r'weather(?: in)? ([a-zA-Z\s]+)', msg_lower)
        if weather_match:
            city = weather_match.group(1).strip()
            res = composia.get_weather(city)
            if "error" in res:
                ai_response = f"Error fetching weather: {res['error']}"
            else:
                ai_response = f"The current weather in **{res['location']}** is **{res['temperature']}°C** with **{res['description']}**.  \n- Humidity: {res['humidity']}%  \n- Wind Speed: {res['wind_speed']} m/s"
            model_used = f"{selected_model} + Composia Weather SDK"
            intercepted = True

        # 2. Save attachments command
        elif "save attachment" in msg_lower or "download attachment" in msg_lower:
            id_match = re.search(r'(msg_\d+)', msg_lower)
            if not id_match:
                id_match = re.search(r'attachment(?:s)?\s+(?:for|of)?\s*(?:email|message)?\s*([a-zA-Z0-9_\-]+)', msg_lower)
            if id_match:
                email_id = id_match.group(1).strip()
                res = composia.save_attachments(email_id)
                if isinstance(res, dict) and "error" in res:
                    ai_response = f"Error downloading attachments: {res['error']}"
                elif not res:
                    ai_response = f"No attachments found for email ID `{email_id}`."
                else:
                    files = [f["filepath"] for f in res]
                    ai_response = f"Successfully downloaded and saved attachments to the project folder:  \n" + "\n".join([f"- `{f}`" for f in files])
            else:
                ai_response = "Please specify the email ID, e.g., *save attachments for msg_001*."
            model_used = f"{selected_model} + Composia Gmail SDK"
            intercepted = True

        # 3. Email command
        elif "mail" in msg_lower or "email" in msg_lower:
            if "between" in msg_lower:
                dates = re.findall(r'(\d{4}/\d{2}/\d{2})', user_message)
                if len(dates) >= 2:
                    start_date, end_date = dates[0], dates[1]
                    res = composia.get_emails_between_dates(start_date, end_date)
                    title = f"Emails between {start_date} and {end_date}"
                else:
                    res = {"error": "Please specify start and end dates in YYYY/MM/DD format, e.g., *emails between 2026/06/01 and 2026/07/09*."}
            elif "subject" in msg_lower:
                subj_match = re.search(r'subject(?: containing| with| about)?\s+[\'\"“]?([a-zA-Z0-9_\-\s]+)[\'\"”]?', msg_lower)
                if subj_match:
                    subject = subj_match.group(1).strip()
                    res = composia.search_emails_by_subject(subject)
                    title = f"Emails with subject containing '{subject}'"
                else:
                    res = {"error": "Please specify a subject keyword, e.g., *emails with subject Guidelines*."}
            else:
                res = composia.get_latest_emails()
                title = "Latest Emails"

            if isinstance(res, dict) and "error" in res:
                ai_response = res["error"]
            elif not res:
                ai_response = "No emails found matching that query in your inbox."
            else:
                lines = [f"### {title}:", ""]
                for idx, email in enumerate(res, 1):
                    lines.append(f"{idx}. **From:** {email['from']}  \n   **Subject:** {email['subject']} (Date: *{email['date']}*, ID: `{email['id']}`)")
                lines.append("\n*To save attachments, type: save attachment [ID]*")
                ai_response = "\n".join(lines)
            model_used = f"{selected_model} + Composia Gmail SDK"
            intercepted = True

        if intercepted:
            ai_msg = {
                'role': 'assistant',
                'content': ai_response,
                'timestamp': datetime.now().isoformat(),
                'model': model_used
            }
            current_chat['messages'].append(ai_msg)
            current_chat['updated_at'] = datetime.now().isoformat()

            # Auto-generate chat title if this is the first exchange
            if len(current_chat['messages']) == 2 and current_chat['title'].startswith('New Chat'):
                first_msg = current_chat['messages'][0]['content']
                new_title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg
                current_chat['title'] = new_title

            session.modified = True
            return jsonify({
                'response': ai_response,
                'model_used': model_used,
                'chat_id': current_chat['id']
            })

        # Execute chat using native Groq SDK tool calling
        ai_response = run_groq_tool_calling(user_message, selected_model, current_chat)
        model_used = selected_model

        if not ai_response:
            # Fallback to direct Groq API if tool calling fails
            return fallback_to_groq_api(user_message, selected_model, current_chat)

        # Detect model names or tool additions
        if "weather" in user_message.lower():
            model_used = f"{selected_model} + Composia Weather SDK"
        elif any(kw in user_message.lower() for kw in ["email", "mail", "attachment"]):
            model_used = f"{selected_model} + Composia Gmail SDK"

        # Add AI response to chat history
        ai_msg = {
            'role': 'assistant',
            'content': ai_response,
            'timestamp': datetime.now().isoformat(),
            'model': model_used
        }
        current_chat['messages'].append(ai_msg)
        current_chat['updated_at'] = datetime.now().isoformat()

        # Auto-generate chat title if this is the first exchange
        if len(current_chat['messages']) == 2 and current_chat['title'].startswith('New Chat'):
            first_msg = current_chat['messages'][0]['content']
            new_title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg
            current_chat['title'] = new_title

        session.modified = True

        logger.info("Successfully generated AI response using native Groq tool calling")
        return jsonify({
            'response': ai_response,
            'model_used': model_used,
            'chat_id': current_chat['id']
        })

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

        # Try fallback to direct Groq API
        try:
            current_chat = get_current_chat()
            if current_chat:
                return fallback_to_groq_api(user_message, selected_model, current_chat)
        except:
            pass

        if hasattr(e, 'status_code'):
            if e.status_code == 401:
                return jsonify({'error': 'Invalid API key. Please check your Groq API key in the .env file.'}), 500
            elif e.status_code == 429:
                return jsonify({'error': 'Rate limit exceeded. Please try again in a moment.'}), 500
            else:
                return jsonify({'error': f'API Error (Status {e.status_code}): {str(e)}'}), 500
        else:
            return jsonify({'error': f'An error occurred: {str(e)}'}), 500

def fallback_to_groq_api(user_message: str, selected_model: str, current_chat: dict):
    """Fallback function to use direct Groq API when LangChain fails"""
    try:
        if not groq_client:
            return jsonify({'error': 'Both LangChain and Groq API clients are unavailable.'}), 500

        logger.info("Using fallback Groq API")

        # Prepare messages for Groq API
        user_profile = session.get('user_profile', {})
        user_name = user_profile.get('name', '')

        system_message = "You are a helpful AI assistant. Provide clear, concise, and helpful responses."
        if user_name:
            system_message += f" The user's name is {user_name}. Remember this information throughout the conversation."

        messages = [{"role": "system", "content": system_message}]
        recent_messages = current_chat['messages'][-20:]
        for msg in recent_messages:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })

        # Call Groq API
        chat_completion = groq_client.chat.completions.create(
            messages=messages,
            model=selected_model,
            max_tokens=1024,
            temperature=0.7,
            top_p=1,
            stream=False
        )

        ai_response = chat_completion.choices[0].message.content

        ai_msg = {
            'role': 'assistant',
            'content': ai_response,
            'timestamp': datetime.now().isoformat(),
            'model': f"{selected_model} (fallback)"
        }
        current_chat['messages'].append(ai_msg)
        current_chat['updated_at'] = datetime.now().isoformat()

        session.modified = True

        return jsonify({
            'response': ai_response,
            'model_used': f"{selected_model} (fallback)",
            'chat_id': current_chat['id']
        })

    except Exception as fallback_error:
        logger.error(f"Fallback Groq API also failed: {fallback_error}")
        return jsonify({'error': 'Both LangChain and fallback API failed. Please try again.'}), 500

@app.route('/chats/new', methods=['POST'])
def new_chat():
    """Create a new chat session"""
    try:
        initialize_session()
        data = request.get_json() or {}
        title = data.get('title', None)

        logger.info(f"Creating new chat with title: {title}")
        logger.info(f"Session user_id: {session.get('user_id')}")

        chat_data = create_new_chat(title)
        logger.info(f"Successfully created chat with ID: {chat_data['id']}")

        return jsonify({
            'message': 'New chat created successfully',
            'chat': chat_data
        })
    except Exception as e:
        logger.error(f"Error creating new chat: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': f'Failed to create new chat: {str(e)}'}), 500

@app.route('/chats', methods=['GET'])
def get_chats():
    """Get all chat sessions for the current user"""
    try:
        initialize_session()
        user_id = session.get('user_id')
        user_chats = chat_sessions.get(user_id, {})

        # Create a default chat if none exists
        if not user_chats and not session.get('current_chat_id'):
            logger.info("No chats found, creating default chat")
            create_new_chat("New Chat")
            user_chats = chat_sessions.get(user_id, {})

        # Convert to list and sort by updated_at
        chats_list = []
        for chat_id, chat_data in user_chats.items():
            # Add preview text (first user message)
            preview = ""
            for msg in chat_data['messages']:
                if msg['role'] == 'user':
                    preview = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
                    break

            chat_summary = {
                'id': chat_data['id'],
                'title': chat_data['title'],
                'preview': preview,
                'created_at': chat_data['created_at'],
                'updated_at': chat_data['updated_at'],
                'message_count': len(chat_data['messages'])
            }
            chats_list.append(chat_summary)

        # Sort by updated_at (most recent first)
        chats_list.sort(key=lambda x: x['updated_at'], reverse=True)

        logger.info(f"Returning {len(chats_list)} chats for user {user_id}")
        return jsonify({
            'chats': chats_list,
            'current_chat_id': session.get('current_chat_id')
        })
    except Exception as e:
        logger.error(f"Error getting chats: {e}")
        return jsonify({'error': 'Failed to get chats'}), 500

@app.route('/chats/<chat_id>', methods=['GET'])
def get_chat(chat_id):
    """Get a specific chat session"""
    try:
        initialize_session()
        user_id = session.get('user_id')
        chat_data = chat_sessions.get(user_id, {}).get(chat_id)

        if not chat_data:
            return jsonify({'error': 'Chat not found'}), 404

        return jsonify({'chat': chat_data})
    except Exception as e:
        logger.error(f"Error getting chat {chat_id}: {e}")
        return jsonify({'error': 'Failed to get chat'}), 500

@app.route('/chats/<chat_id>/switch', methods=['POST'])
def switch_chat(chat_id):
    """Switch to a different chat session"""
    try:
        initialize_session()
        user_id = session.get('user_id')

        if chat_id not in chat_sessions.get(user_id, {}):
            return jsonify({'error': 'Chat not found'}), 404

        session['current_chat_id'] = chat_id
        session.modified = True

        chat_data = chat_sessions[user_id][chat_id]
        return jsonify({
            'message': 'Chat switched successfully',
            'chat': chat_data
        })
    except Exception as e:
        logger.error(f"Error switching to chat {chat_id}: {e}")
        return jsonify({'error': 'Failed to switch chat'}), 500

@app.route('/chats/<chat_id>/rename', methods=['POST'])
def rename_chat(chat_id):
    """Rename a chat session"""
    try:
        initialize_session()
        data = request.get_json()
        new_title = data.get('title', '').strip()

        if not new_title:
            return jsonify({'error': 'Title cannot be empty'}), 400

        if update_chat_title(chat_id, new_title):
            return jsonify({'message': 'Chat renamed successfully'})
        else:
            return jsonify({'error': 'Chat not found'}), 404
    except Exception as e:
        logger.error(f"Error renaming chat {chat_id}: {e}")
        return jsonify({'error': 'Failed to rename chat'}), 500

@app.route('/chats/<chat_id>/delete', methods=['DELETE'])
def delete_chat(chat_id):
    """Delete a chat session"""
    try:
        initialize_session()
        user_id = session.get('user_id')

        if user_id not in chat_sessions or chat_id not in chat_sessions[user_id]:
            return jsonify({'error': 'Chat not found'}), 404

        del chat_sessions[user_id][chat_id]

        # If this was the current chat, switch to another one or create new
        if session.get('current_chat_id') == chat_id:
            remaining_chats = list(chat_sessions.get(user_id, {}).keys())
            if remaining_chats:
                session['current_chat_id'] = remaining_chats[0]
            else:
                # Create a new chat if no chats remain
                create_new_chat("New Chat")

        session.modified = True
        return jsonify({'message': 'Chat deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting chat {chat_id}: {e}")
        return jsonify({'error': 'Failed to delete chat'}), 500

@app.route('/profile', methods=['GET'])
def get_profile():
    """Get user profile"""
    try:
        initialize_session()
        return jsonify({'profile': session.get('user_profile', {})})
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        return jsonify({'error': 'Failed to get profile'}), 500

@app.route('/profile', methods=['POST'])
def update_profile():
    """Update user profile"""
    try:
        initialize_session()
        data = request.get_json()

        if 'name' in data:
            session['user_profile']['name'] = data['name'].strip()

        if 'preferences' in data:
            session['user_profile']['preferences'].update(data['preferences'])

        session.modified = True
        return jsonify({
            'message': 'Profile updated successfully',
            'profile': session['user_profile']
        })
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        return jsonify({'error': 'Failed to update profile'}), 500

@app.route('/chats/search', methods=['GET'])
def search_chats():
    """Search through chat sessions"""
    try:
        initialize_session()
        query = request.args.get('q', '').strip().lower()

        if not query:
            return jsonify({'chats': []})

        user_id = session.get('user_id')
        user_chats = chat_sessions.get(user_id, {})

        matching_chats = []
        for chat_id, chat_data in user_chats.items():
            # Search in title and messages
            if query in chat_data['title'].lower():
                matching_chats.append(chat_data)
                continue

            # Search in message content
            for msg in chat_data['messages']:
                if query in msg['content'].lower():
                    matching_chats.append(chat_data)
                    break

        return jsonify({'chats': matching_chats})
    except Exception as e:
        logger.error(f"Error searching chats: {e}")
        return jsonify({'error': 'Failed to search chats'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'groq_client_initialized': groq_client is not None
    })

if __name__ == '__main__':
    # Check if required environment variables are set
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        logger.warning("GROQ_API_KEY not found in environment variables. Please set it in .env file.")
    else:
        logger.info(f"GROQ_API_KEY found (length: {len(api_key)})")

    logger.info("Starting Flask application...")
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    logger.info(f"Debug mode: {debug_mode}")
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
