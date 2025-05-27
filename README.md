# AI Chat Interface with Groq API

A modern, responsive web-based chat interface that integrates with the Groq API to provide fast AI-powered conversations. Built with Flask and featuring a clean, user-friendly design.

## Features

### Core Chat Functionality
- **Real-time Chat Interface**: Interactive chat with typing indicators and smooth message flow
- **Groq API Integration**: Powered by Groq's high-performance AI models
- **Multiple AI Models**: Support for various Groq models (Llama, Mixtral, Gemma)
- **Responsive Design**: Works seamlessly on desktop and mobile devices
- **Error Handling**: Comprehensive error handling with user-friendly messages

### Advanced Session Management
- **Persistent Chat Sessions**: Multiple chat conversations saved and accessible
- **Session Switching**: Seamlessly switch between different chat conversations
- **Auto-generated Titles**: Chat sessions automatically named based on first message
- **Manual Renaming**: Rename chat sessions with custom titles
- **Session Search**: Search through chat history and content
- **Session Deletion**: Remove unwanted chat sessions

### User Profile & Memory
- **User Profile System**: Remember user information across all sessions
- **Cross-Session Memory**: AI remembers user details (name, preferences) across different chats
- **Context Continuity**: Full conversation history maintained when resuming sessions
- **Persistent Storage**: All data persists between browser sessions

### Enhanced UI/UX
- **Collapsible Sidebar**: Toggle sidebar visibility with hamburger menu
- **Chat Preview**: See conversation previews and timestamps in sidebar
- **Context Menus**: Right-click options for chat management
- **Mobile Optimized**: Responsive design with mobile-specific interactions
- **Modern Design**: Clean, professional interface with smooth animations

## Prerequisites

- Python 3.8 or higher
- Groq API key (get one from [Groq Console](https://console.groq.com/))

## Installation

1. **Clone or download the project files**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   - Copy `.env.example` to `.env`
   - Add your Groq API key and other configuration:
   ```
   GROQ_API_KEY=your_groq_api_key_here
   FLASK_SECRET_KEY=your_secret_key_here
   FLASK_DEBUG=True
   ```

## Getting Your Groq API Key

1. Visit [Groq Console](https://console.groq.com/)
2. Sign up or log in to your account
3. Navigate to the API Keys section
4. Create a new API key
5. Copy the key and add it to your `.env` file

## Usage

1. **Start the application**:
   ```bash
   python app.py
   ```

2. **Open your browser** and navigate to:
   ```
   http://localhost:5000
   ```

3. **Start chatting**:
   - Type your message in the input field
   - Press Enter or click the send button
   - Choose different AI models from the dropdown

## Using Advanced Features

### Managing Chat Sessions
- **Create New Chat**: Click the "New Chat" button in sidebar or header
- **Switch Chats**: Click on any chat in the sidebar to resume that conversation
- **Rename Chats**: Click the menu button (⋮) next to a chat title and select "Rename"
- **Delete Chats**: Click the menu button (⋮) next to a chat title and select "Delete"
- **Search Chats**: Use the search box in the sidebar to find specific conversations

### User Profile Setup
- **Set Your Name**: Click the edit button next to your name in the sidebar footer
- **Profile Benefits**: The AI will remember your name across all chat sessions
- **Persistent Memory**: Your profile information is saved and restored automatically

### Sidebar Navigation
- **Toggle Sidebar**: Click the hamburger menu (☰) in the header to show/hide sidebar
- **Mobile Usage**: On mobile, the sidebar overlays the chat and can be dismissed by tapping outside
- **Chat Previews**: See the first message of each conversation in the sidebar
- **Timestamps**: View when each chat was last updated

### Session Continuity
- **Resume Conversations**: Click any chat in the sidebar to continue where you left off
- **Full History**: All messages in a session are preserved and loaded when switching
- **Context Awareness**: The AI maintains context and memory within each session
- **Cross-Session Memory**: User profile information is available across all sessions

## Available AI Models

The application supports several Groq models:

- **llama3-8b-8192**: Fast and efficient for general conversations
- **llama3-70b-8192**: More powerful model for complex tasks
- **mixtral-8x7b-32768**: Excellent for reasoning and analysis
- **gemma-7b-it**: Google's Gemma model optimized for instruction following

## Project Structure

```
Chat Interface 2/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── README.md             # This file
├── templates/
│   └── index.html        # Main chat interface template
└── static/
    ├── css/
    │   └── style.css     # Styling for the chat interface
    └── js/
        └── script.js     # Frontend JavaScript functionality
```

## API Endpoints

### Core Chat
- `GET /` - Main chat interface
- `POST /chat` - Send message and get AI response
- `GET /health` - Health check endpoint

### Chat Session Management
- `GET /chats` - Get all chat sessions for current user
- `POST /chats/new` - Create a new chat session
- `GET /chats/<chat_id>` - Get specific chat session
- `POST /chats/<chat_id>/switch` - Switch to a different chat session
- `POST /chats/<chat_id>/rename` - Rename a chat session
- `DELETE /chats/<chat_id>/delete` - Delete a chat session
- `GET /chats/search?q=<query>` - Search through chat sessions

### User Profile
- `GET /profile` - Get user profile information
- `POST /profile` - Update user profile information

## Features in Detail

### Advanced Session Management
- **Multiple Conversations**: Maintain unlimited separate chat sessions
- **Persistent Storage**: All conversations saved in server memory (upgradeable to database)
- **Smart Titles**: Auto-generated titles based on conversation content
- **Quick Switching**: Instant switching between conversations with full context restoration
- **Search & Filter**: Find conversations by title or message content
- **Bulk Management**: Rename, delete, and organize chat sessions

### User Profile & Memory System
- **Cross-Session Identity**: AI remembers user information across all conversations
- **Persistent Profiles**: User data maintained between browser sessions
- **Context Inheritance**: User preferences and information available in all chats
- **Profile Management**: Easy editing of user information through modal interface

### Enhanced User Interface
- **Collapsible Sidebar**: Clean, organized view of all chat sessions
- **Mobile Responsive**: Optimized for both desktop and mobile devices
- **Context Menus**: Right-click functionality for chat management
- **Visual Feedback**: Loading states, animations, and status indicators
- **Keyboard Shortcuts**: Enter to send, Shift+Enter for new lines

### Real-time Chat Experience
- **Typing Indicators**: Visual feedback while AI is generating responses
- **Message Timestamps**: Track when messages were sent
- **Model Information**: See which AI model generated each response
- **Auto-scrolling**: Smooth scrolling to latest messages
- **Character Limits**: Visual character count with warnings

### Technical Features
- **Session-based Storage**: Secure session management with Flask
- **Error Recovery**: Comprehensive error handling with user-friendly messages
- **API Integration**: Robust Groq API integration with retry logic
- **Performance Optimized**: Efficient loading and rendering of chat history

## Customization

### Adding New Models
To add new Groq models, update the `AVAILABLE_MODELS` list in `app.py`:

```python
AVAILABLE_MODELS = [
    "llama3-8b-8192",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma-7b-it",
    "your-new-model-name"
]
```

### Styling
Modify `static/css/style.css` to customize the appearance:
- Colors and gradients
- Typography and spacing
- Animation effects
- Layout adjustments

### Functionality
Extend `static/js/script.js` to add new features:
- Message formatting
- Additional UI interactions
- Enhanced error handling

## Troubleshooting

### Common Issues

1. **"Groq API client not initialized"**
   - Check that your `GROQ_API_KEY` is correctly set in the `.env` file
   - Verify the API key is valid and active

2. **"Failed to get response"**
   - Check your internet connection
   - Verify the selected model is available
   - Check Groq API status

3. **Application won't start**
   - Ensure all dependencies are installed: `pip install -r requirements.txt`
   - Check that port 5000 is not in use by another application

### Debug Mode
Enable debug mode by setting `FLASK_DEBUG=True` in your `.env` file for detailed error messages.

## Security Notes

- Never commit your `.env` file with real API keys
- Use strong secret keys for Flask sessions
- Consider implementing rate limiting for production use
- Validate and sanitize all user inputs

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve the application.

## License

This project is open source and available under the MIT License.
