import re
import requests
import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session
from groq import Groq
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# Initialize Groq client
try:
    groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
    logger.info("Groq client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")
    groq_client = None

# Available models (you can expand this list)
AVAILABLE_MODELS = [
    "llama3-8b-8192",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma-7b-it"
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

def should_trigger_weather_tool(user_input: str):
    """Detects if user is asking for weather in a city"""
    pattern = r'\bweather\b.*?\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b|\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b.*?\bweather\b'
    match = re.search(pattern, user_input, re.IGNORECASE)
    if match:
        city = match.group(1) or match.group(2)
        return True, city
    return False, None

def get_weather_for_city(city_name: str):
    """Calls OpenWeatherMap API to get weather for a city"""
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        return "Weather API key is missing. Please set OPENWEATHER_API_KEY."

    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={api_key}&units=metric"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"]
        return f"The current weather in {city_name} is {temp}°C with {desc}."
    elif response.status_code == 404:
        return f"Could not find weather data for '{city_name}'."
    else:
        return f"Error fetching weather data: {response.status_code}"

@app.route('/')
def index():
    """Render the main chat interface"""
    initialize_session()

    # Create a new chat if none exists
    if not session.get('current_chat_id'):
        create_new_chat("New Chat")

    return render_template('index.html', models=AVAILABLE_MODELS)
@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages and get AI responses"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        selected_model = data.get('model', 'llama3-8b-8192')

        if not user_message:
            return jsonify({'error': 'Message cannot be empty'}), 400

        initialize_session()

        # Check for weather request before calling LLM
        triggered, city = should_trigger_weather_tool(user_message)
        if triggered and city:
            current_chat = get_current_chat()
            if not current_chat:
                current_chat = create_new_chat()

            user_msg = {
                'role': 'user',
                'content': user_message,
                'timestamp': datetime.now().isoformat()
            }

            weather_response = get_weather_for_city(city)
            ai_msg = {
                'role': 'assistant',
                'content': weather_response,
                'timestamp': datetime.now().isoformat(),
                'model': "weather-api"
            }

            current_chat['messages'].append(user_msg)
            current_chat['messages'].append(ai_msg)
            current_chat['updated_at'] = datetime.now().isoformat()
            session.modified = True

            return jsonify({
                'response': weather_response,
                'model_used': "weather-api",
                'chat_id': current_chat['id']
            })

        # Fallback: use Groq if not a weather request
        if not groq_client:
            return jsonify({'error': 'Groq API client not initialized. Please check your API key.'}), 500

        current_chat = get_current_chat()
        if not current_chat:
            current_chat = create_new_chat()

        user_msg = {
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        }
        current_chat['messages'].append(user_msg)

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
            'model': selected_model
        }
        current_chat['messages'].append(ai_msg)
        current_chat['updated_at'] = datetime.now().isoformat()

        if len(current_chat['messages']) == 2 and current_chat['title'].startswith('New Chat'):
            first_msg = current_chat['messages'][0]['content']
            new_title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg
            current_chat['title'] = new_title

        session.modified = True

        return jsonify({
            'response': ai_response,
            'model_used': selected_model,
            'chat_id': current_chat['id']
        })

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        logger.error(f"Error type: {type(e).__name__}")

        if hasattr(e, 'status_code'):
            if e.status_code == 401:
                return jsonify({'error': 'Invalid API key. Please check your Groq API key in the .env file.'}), 500
            elif e.status_code == 429:
                return jsonify({'error': 'Rate limit exceeded. Please try again in a moment.'}), 500
            else:
                return jsonify({'error': f'API Error (Status {e.status_code}): {str(e)}'}), 500
        else:
            return jsonify({'error': f'An error occurred: {str(e)}'}), 500

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
