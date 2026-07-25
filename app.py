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

from flask_sqlalchemy import SQLAlchemy
import json

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# SQLAlchemy SQLite setup for zero-config resume-ready persistence
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///chat_history.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
sqlite_db = SQLAlchemy(app)

class SQLiteUser(sqlite_db.Model):
    __tablename__ = 'users'
    user_id = sqlite_db.Column(sqlite_db.String(64), primary_key=True)
    created_at = sqlite_db.Column(sqlite_db.String(64))

class SQLiteChatSession(sqlite_db.Model):
    __tablename__ = 'chat_sessions'
    id = sqlite_db.Column(sqlite_db.String(64), primary_key=True)
    title = sqlite_db.Column(sqlite_db.String(255))
    user_id = sqlite_db.Column(sqlite_db.String(64), sqlite_db.ForeignKey('users.user_id'))
    created_at = sqlite_db.Column(sqlite_db.String(64))
    updated_at = sqlite_db.Column(sqlite_db.String(64))
    messages = sqlite_db.relationship('SQLiteChatMessage', backref='session', cascade='all, delete-orphan', lazy=True)

class SQLiteChatMessage(sqlite_db.Model):
    __tablename__ = 'chat_messages'
    id = sqlite_db.Column(sqlite_db.String(64), primary_key=True)
    chat_id = sqlite_db.Column(sqlite_db.String(64), sqlite_db.ForeignKey('chat_sessions.id'))
    role = sqlite_db.Column(sqlite_db.String(64)) # 'user' or 'assistant'
    content = sqlite_db.Column(sqlite_db.Text)
    model = sqlite_db.Column(sqlite_db.String(128), nullable=True)
    timestamp = sqlite_db.Column(sqlite_db.String(64))

class SQLiteUserProfile(sqlite_db.Model):
    __tablename__ = 'user_profiles'
    user_id = sqlite_db.Column(sqlite_db.String(64), sqlite_db.ForeignKey('users.user_id'), primary_key=True)
    name = sqlite_db.Column(sqlite_db.String(255), nullable=True)
    preferences = sqlite_db.Column(sqlite_db.Text, default='{}') # JSON string
    created_at = sqlite_db.Column(sqlite_db.String(64))

# Create database tables
with app.app_context():
    try:
        sqlite_db.create_all()
        logger.info("SQLite database tables created or verified successfully")
    except Exception as db_err:
        logger.error(f"Failed to initialize SQLite tables: {db_err}")

# Initialize Groq client
groq_key = os.getenv('GROQ_API_KEY')
try:
    if groq_key:
        groq_client = Groq(api_key=groq_key)
        logger.info("Groq client initialized successfully")
    else:
        groq_client = None
        logger.warning("GROQ_API_KEY not set in environment")
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")
    groq_client = None

# Initialize LangChain Groq client
try:
    if groq_key:
        langchain_llm = ChatGroq(
            api_key=groq_key,
            model_name="llama-3.1-8b-instant",
            temperature=0.7
        )
        logger.info("LangChain Groq client initialized successfully")
    else:
        langchain_llm = None
        logger.warning("GROQ_API_KEY not set for LangChain Groq")
except Exception as e:
    logger.error(f"Failed to initialize LangChain Groq client: {e}")
    langchain_llm = None

# Available models (you can expand this list)
AVAILABLE_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
    "gemma2-9b-it"
]

# MongoDB configuration and connection with automatic fallback
MONGO_URI = os.getenv("MONGO_URI")
db = None
chats_col = None
profiles_col = None

is_cloud = bool(os.getenv("RENDER") or os.getenv("PORT"))
if MONGO_URI and not (is_cloud and ("localhost" in MONGO_URI or "127.0.0.1" in MONGO_URI)):
    try:
        from pymongo import MongoClient
        # Configure MongoClient with a short 2-second timeout to check connection immediately
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        # Force a connection validation check by pinging the server
        client.admin.command('ping')
        
        db = client.get_database()  # This resolves the database name from the connection string URI if present
        # In case the URI does not specify a DB name, default to 'chat_interface'
        if db.name == 'admin' or not db.name:
            db = client['chat_interface']
        chats_col = db['chats']
        profiles_col = db['profiles']
        logger.info(f"Connected to MongoDB successfully: DB Name = '{db.name}'")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB, falling back to SQLite: {e}")
        db = None
        chats_col = None
        profiles_col = None
else:
    logger.info("Using SQLite database persistence for chat history")


# MongoDB helper functions with SQLite fallbacks
def save_chat(chat_data):
    """Save or update chat session data"""
    if not chat_data:
        return
    user_id = chat_data.get('user_id')
    chat_id = chat_data.get('id')
    if chats_col is not None:
        try:
            chats_col.replace_one({'id': chat_id}, chat_data, upsert=True)
        except Exception as e:
            logger.error(f"Error saving chat to MongoDB: {e}")
    else:
        # Fallback to SQLite
        try:
            # Ensure User exists first
            userObj = SQLiteUser.query.filter_by(user_id=user_id).first()
            if not userObj:
                userObj = SQLiteUser(user_id=user_id, created_at=datetime.now().isoformat())
                sqlite_db.session.add(userObj)
                sqlite_db.session.commit()
                
            sessionObj = SQLiteChatSession.query.filter_by(id=chat_id).first()
            if not sessionObj:
                sessionObj = SQLiteChatSession(
                    id=chat_id,
                    title=chat_data.get('title'),
                    user_id=user_id,
                    created_at=chat_data.get('created_at', datetime.now().isoformat()),
                    updated_at=chat_data.get('updated_at', datetime.now().isoformat())
                )
                sqlite_db.session.add(sessionObj)
            else:
                sessionObj.title = chat_data.get('title')
                sessionObj.updated_at = chat_data.get('updated_at', datetime.now().isoformat())
            
            # Now delete old messages and overwrite them
            SQLiteChatMessage.query.filter_by(chat_id=chat_id).delete()
            
            # Insert messages
            for idx, msg in enumerate(chat_data.get('messages', [])):
                msgObj = SQLiteChatMessage(
                    id=f"{chat_id}_{idx}",
                    chat_id=chat_id,
                    role=msg.get('role'),
                    content=msg.get('content'),
                    model=msg.get('model'),
                    timestamp=msg.get('timestamp', datetime.now().isoformat())
                )
                sqlite_db.session.add(msgObj)
            sqlite_db.session.commit()
        except Exception as e:
            sqlite_db.session.rollback()
            logger.error(f"Error saving chat to SQLite: {e}")

def get_chat_by_id(user_id, chat_id):
    """Retrieve a specific chat session"""
    if chats_col is not None:
        try:
            chat_data = chats_col.find_one({'id': chat_id, 'user_id': user_id})
            if chat_data:
                chat_data.pop('_id', None)
                return chat_data
        except Exception as e:
            logger.error(f"Error retrieving chat from MongoDB: {e}")
            return None
    else:
        # SQLite retrieval
        try:
            sessionObj = SQLiteChatSession.query.filter_by(id=chat_id, user_id=user_id).first()
            if sessionObj:
                messages = []
                for msg in sessionObj.messages:
                    messages.append({
                        'role': msg.role,
                        'content': msg.content,
                        'model': msg.model,
                        'timestamp': msg.timestamp
                    })
                return {
                    'id': sessionObj.id,
                    'title': sessionObj.title,
                    'user_id': sessionObj.user_id,
                    'created_at': sessionObj.created_at,
                    'updated_at': sessionObj.updated_at,
                    'messages': messages
                }
        except Exception as e:
            logger.error(f"Error retrieving chat from SQLite: {e}")
        return None

def get_user_chats(user_id):
    """Retrieve all chats for a user"""
    if chats_col is not None:
        try:
            cursor = chats_col.find({'user_id': user_id})
            chats = {}
            for doc in cursor:
                doc.pop('_id', None)
                chats[doc['id']] = doc
            return chats
        except Exception as e:
            logger.error(f"Error retrieving user chats from MongoDB: {e}")
            return {}
    else:
        # SQLite retrieval
        try:
            sessions = SQLiteChatSession.query.filter_by(user_id=user_id).all()
            chats = {}
            for s in sessions:
                messages = []
                for msg in s.messages:
                    messages.append({
                        'role': msg.role,
                        'content': msg.content,
                        'model': msg.model,
                        'timestamp': msg.timestamp
                    })
                chats[s.id] = {
                    'id': s.id,
                    'title': s.title,
                    'user_id': s.user_id,
                    'created_at': s.created_at,
                    'updated_at': s.updated_at,
                    'messages': messages
                }
            return chats
        except Exception as e:
            logger.error(f"Error retrieving user chats from SQLite: {e}")
            return {}

def delete_user_chat(user_id, chat_id):
    """Delete a specific chat session"""
    if chats_col is not None:
        try:
            chats_col.delete_one({'id': chat_id, 'user_id': user_id})
            return True
        except Exception as e:
            logger.error(f"Error deleting chat from MongoDB: {e}")
            return False
    else:
        # SQLite delete
        try:
            sessionObj = SQLiteChatSession.query.filter_by(id=chat_id, user_id=user_id).first()
            if sessionObj:
                sqlite_db.session.delete(sessionObj)
                sqlite_db.session.commit()
                return True
        except Exception as e:
            sqlite_db.session.rollback()
            logger.error(f"Error deleting chat from SQLite: {e}")
            return False

def save_user_profile(user_id, profile_data):
    """Save or update user profile data"""
    if not profile_data:
        return
    if profiles_col is not None:
        try:
            profiles_col.replace_one({'user_id': user_id}, {
                'user_id': user_id,
                'profile': profile_data
            }, upsert=True)
        except Exception as e:
            logger.error(f"Error saving user profile to MongoDB: {e}")
    else:
        # SQLite save
        try:
            # Ensure User exists first
            userObj = SQLiteUser.query.filter_by(user_id=user_id).first()
            if not userObj:
                userObj = SQLiteUser(user_id=user_id, created_at=datetime.now().isoformat())
                sqlite_db.session.add(userObj)
                sqlite_db.session.commit()

            profileObj = SQLiteUserProfile.query.filter_by(user_id=user_id).first()
            if not profileObj:
                profileObj = SQLiteUserProfile(
                    user_id=user_id,
                    name=profile_data.get('name'),
                    preferences=json.dumps(profile_data.get('preferences', {})),
                    created_at=profile_data.get('created_at', datetime.now().isoformat())
                )
                sqlite_db.session.add(profileObj)
            else:
                profileObj.name = profile_data.get('name')
                profileObj.preferences = json.dumps(profile_data.get('preferences', {}))
            sqlite_db.session.commit()
        except Exception as e:
            sqlite_db.session.rollback()
            logger.error(f"Error saving user profile to SQLite: {e}")

def get_user_profile(user_id):
    """Retrieve user profile data"""
    if profiles_col is not None:
        try:
            doc = profiles_col.find_one({'user_id': user_id})
            if doc:
                return doc.get('profile')
        except Exception as e:
            logger.error(f"Error retrieving user profile from MongoDB: {e}")
    else:
        # SQLite retrieval
        try:
            profileObj = SQLiteUserProfile.query.filter_by(user_id=user_id).first()
            if profileObj:
                return {
                    'name': profileObj.name,
                    'preferences': json.loads(profileObj.preferences or '{}'),
                    'created_at': profileObj.created_at
                }
        except Exception as e:
            logger.error(f"Error retrieving user profile from SQLite: {e}")
    return None



def initialize_session():
    """Initialize session with default values"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())

    if 'current_chat_id' not in session:
        session['current_chat_id'] = None

    if 'user_profile' not in session or not session['user_profile'].get('name'):
        db_profile = get_user_profile(session['user_id'])
        if db_profile:
            session['user_profile'] = db_profile
        else:
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

    save_chat(chat_data)
    session['current_chat_id'] = chat_id
    session.modified = True

    return chat_data

def get_current_chat():
    """Get the current active chat session"""
    user_id = session.get('user_id')
    chat_id = session.get('current_chat_id')

    if not user_id or not chat_id:
        return None

    return get_chat_by_id(user_id, chat_id)

def update_chat_title(chat_id, title):
    """Update chat title"""
    user_id = session.get('user_id')
    if not user_id:
        return False
    chat_data = get_chat_by_id(user_id, chat_id)
    if chat_data:
        chat_data['title'] = title
        chat_data['updated_at'] = datetime.now().isoformat()
        save_chat(chat_data)
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
        save_chat(current_chat)

        # Intercept specific weather and email commands for high reliability
        msg_lower = user_message.lower()
        intercepted = False
        ai_response = ""
        model_used = selected_model

        # 1. Weather command
        weather_match = re.search(r'(?:weather|temperature|forecast)(?:\s+(?:in|of|for|at))?\s+([a-zA-Z\s]+)', msg_lower)
        if weather_match:
            city = weather_match.group(1).strip()
            res = composia.get_weather(city)
            if isinstance(res, dict) and "error" in res:
                ai_response = f"Error fetching weather: {res['error']}"
            else:
                ai_response = f"The current weather in **{res['location']}** is **{res['temperature']}°C** with **{res['description']}**.  \n- Humidity: {res['humidity']}%  \n- Wind Speed: {res['wind_speed']} m/s"
            model_used = f"{selected_model} + Composia Weather SDK"
            intercepted = True

        # 2. Save attachments command
        elif any(kw in msg_lower for kw in ["save attachment", "download attachment", "save file", "download file", "get attachment"]):
            id_match = re.search(r'(msg_\d+)', msg_lower)
            if not id_match:
                id_match = re.search(r'(?:attachment|file|email|msg)\s*(?:for|of|id)?\s*([a-zA-Z0-9_\-]+)', msg_lower)
            if id_match:
                email_id = id_match.group(1).strip()
                if not email_id.startswith("msg_") and email_id.isdigit():
                    email_id = f"msg_{email_id.zfill(3)}"
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
                dates = re.findall(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})', user_message)
                if len(dates) >= 2:
                    start_date, end_date = dates[0].replace('-', '/'), dates[1].replace('-', '/')
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
                for idx, email_item in enumerate(res, 1):
                    lines.append(f"{idx}. **From:** {email_item['from']}  \n   **Subject:** {email_item['subject']} (Date: *{email_item['date']}*, ID: `{email_item['id']}`)")
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
            save_chat(current_chat)
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
        save_chat(current_chat)

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
        save_chat(current_chat)

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
        user_chats = get_user_chats(user_id)

        # Create a default chat if none exists
        if not user_chats and not session.get('current_chat_id'):
            logger.info("No chats found, creating default chat")
            create_new_chat("New Chat")
            user_chats = get_user_chats(user_id)

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
        chat_data = get_chat_by_id(user_id, chat_id)

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
        chat_data = get_chat_by_id(user_id, chat_id)

        if not chat_data:
            return jsonify({'error': 'Chat not found'}), 404

        session['current_chat_id'] = chat_id
        session.modified = True

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

        chat_data = get_chat_by_id(user_id, chat_id)
        if not chat_data:
            return jsonify({'error': 'Chat not found'}), 404

        delete_user_chat(user_id, chat_id)

        # If this was the current chat, switch to another one or create new
        if session.get('current_chat_id') == chat_id:
            remaining_chats = list(get_user_chats(user_id).keys())
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

@app.route('/chats/<chat_id>/export', methods=['GET'])
def export_chat(chat_id):
    """Export a chat session as Markdown or JSON"""
    try:
        from flask import Response
        initialize_session()
        user_id = session.get('user_id')
        chat_data = get_chat_by_id(user_id, chat_id)
        
        if not chat_data:
            return jsonify({'error': 'Chat not found'}), 404
            
        export_format = request.args.get('format', 'markdown').lower()
        
        if export_format == 'json':
            content = json.dumps(chat_data, indent=2)
            filename = f"chat_export_{chat_id}.json"
            mimetype = "application/json"
        else:
            # Generate markdown format
            lines = [
                f"# Chat Session: {chat_data['title']}",
                f"- **Exported On:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "---",
                ""
            ]
            for msg in chat_data['messages']:
                role_name = "User" if msg['role'] == 'user' else "AI Assistant"
                timestamp = msg.get('timestamp', '')
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        timestamp_str = timestamp
                else:
                    timestamp_str = "N/A"
                
                model_info = f" ({msg['model']})" if msg['role'] == 'assistant' and msg.get('model') else ""
                lines.append(f"### {role_name}{model_info}")
                lines.append(f"*Sent on: {timestamp_str}*")
                lines.append("")
                lines.append(msg['content'])
                lines.append("")
                lines.append("---")
                lines.append("")
                
            content = "\n".join(lines)
            filename = f"chat_export_{chat_id}.md"
            mimetype = "text/markdown"
            
        return Response(
            content,
            mimetype=mimetype,
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exporting chat {chat_id}: {e}")
        return jsonify({'error': 'Failed to export chat'}), 500

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
        save_user_profile(session.get('user_id'), session['user_profile'])

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
        user_chats = get_user_chats(user_id)

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

@app.route('/gmail/status', methods=['GET'])
def get_gmail_status():
    """Endpoint to check current Gmail integration status"""
    status = composia.test_gmail_connection()
    return jsonify(status)

@app.route('/gmail/config', methods=['POST'])
def update_gmail_config():
    """Endpoint to update Gmail credentials in .env and test connection"""
    try:
        data = request.get_json() or {}
        user = data.get('gmail_user', '').strip()
        app_password = data.get('gmail_app_password', '').strip()
        
        if not user or not app_password:
            return jsonify({'success': False, 'error': 'Both Gmail address and App Password are required.'}), 400
            
        env_file = os.path.join(os.path.dirname(__file__), '.env')
        
        # Read existing .env lines
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                lines = f.readlines()
        else:
            lines = []
            
        new_lines = []
        user_set = False
        pass_set = False
        
        for line in lines:
            if line.startswith('GMAIL_USER='):
                new_lines.append(f'GMAIL_USER={user}\n')
                user_set = True
            elif line.startswith('GMAIL_APP_PASSWORD='):
                new_lines.append(f'GMAIL_APP_PASSWORD={app_password}\n')
                pass_set = True
            else:
                new_lines.append(line)
                
        if not user_set:
            new_lines.append(f'GMAIL_USER={user}\n')
        if not pass_set:
            new_lines.append(f'GMAIL_APP_PASSWORD={app_password}\n')
            
        with open(env_file, 'w') as f:
            f.writelines(new_lines)
            
        # Force reload dotenv
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
        
        # Test connection
        test_res = composia.test_gmail_connection()
        return jsonify(test_res)
    except Exception as e:
        logger.error(f"Error updating Gmail config: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
    app.run(debug=debug_mode, host='0.0.0.0', port=5000, use_reloader=False)
