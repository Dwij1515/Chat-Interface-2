// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const modelSelect = document.getElementById('modelSelect');
const currentModel = document.getElementById('currentModel');
const typingIndicator = document.getElementById('typingIndicator');
const errorModal = document.getElementById('errorModal');
const errorMessage = document.getElementById('errorMessage');

// Sidebar elements
const sidebar = document.getElementById('sidebar');
const toggleSidebar = document.getElementById('toggleSidebar');
const closeSidebar = document.getElementById('closeSidebar');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const newChatBtn = document.getElementById('newChatBtn');
const newChatHeaderBtn = document.getElementById('newChatHeaderBtn');
const chatList = document.getElementById('chatList');
const searchChats = document.getElementById('searchChats');
const userName = document.getElementById('userName');
const editProfileBtn = document.getElementById('editProfileBtn');

// Modal elements
const profileModal = document.getElementById('profileModal');
const profileName = document.getElementById('profileName');
const renameModal = document.getElementById('renameModal');
const chatTitle = document.getElementById('chatTitle');

// State
let isWaitingForResponse = false;
let conversationStarted = false;
let currentChatId = null;
let currentRenameId = null;
let userProfile = null;

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    setupEventListeners();
    loadUserProfile();
    loadChatSessions();
});

function initializeApp() {
    updateCharCount();
    updateCurrentModel();
    conversationStarted = true; // Start with conversation active
}

function setupEventListeners() {
    // Message input events
    if (messageInput) {
        messageInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
            updateCharCount();
            toggleSendButton();
        });

        messageInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    // Button events
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);
    if (newChatBtn) newChatBtn.addEventListener('click', createNewChat);
    if (newChatHeaderBtn) newChatHeaderBtn.addEventListener('click', createNewChat);
    if (editProfileBtn) editProfileBtn.addEventListener('click', openProfileModal);

    // Sidebar events
    toggleSidebar.addEventListener('click', openSidebar);
    closeSidebar.addEventListener('click', closeSidebarPanel);
    sidebarOverlay.addEventListener('click', closeSidebarPanel);

    // Search events
    searchChats.addEventListener('input', debounce(searchChatSessions, 300));

    // Model selection
    modelSelect.addEventListener('change', updateCurrentModel);

    // Modal events
    errorModal.addEventListener('click', function(e) {
        if (e.target === errorModal) {
            closeErrorModal();
        }
    });

    profileModal.addEventListener('click', function(e) {
        if (e.target === profileModal) {
            closeProfileModal();
        }
    });

    renameModal.addEventListener('click', function(e) {
        if (e.target === renameModal) {
            closeRenameModal();
        }
    });
}

// Update character count
function updateCharCount() {
    const charCount = document.querySelector('.char-count');
    const length = messageInput.value.length;
    charCount.textContent = `${length}/2000`;

    if (length > 1800) {
        charCount.style.color = '#dc3545';
    } else if (length > 1500) {
        charCount.style.color = '#ffc107';
    } else {
        charCount.style.color = '#666';
    }
}

// Toggle send button state
function toggleSendButton() {
    const hasText = messageInput.value.trim().length > 0;
    sendBtn.disabled = !hasText || isWaitingForResponse;
}

// Update current model display
function updateCurrentModel() {
    currentModel.textContent = modelSelect.value;
}

// Utility functions
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function formatTimestamp(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
}

// Chat session management
async function loadChatSessions() {
    try {
        const response = await fetch('/chats');
        const data = await response.json();

        if (response.ok) {
            renderChatList(data.chats);
            currentChatId = data.current_chat_id;
            if (currentChatId) {
                await loadChatMessages(currentChatId);
                highlightActiveChat(currentChatId);
            }
        }
    } catch (error) {
        console.error('Error loading chat sessions:', error);
    }
}

function renderChatList(chats) {
    chatList.innerHTML = '';

    if (chats.length === 0) {
        chatList.innerHTML = '<div class="no-chats">No chat sessions yet</div>';
        return;
    }

    chats.forEach(chat => {
        const chatItem = createChatItem(chat);
        chatList.appendChild(chatItem);
    });
}

function createChatItem(chat) {
    const div = document.createElement('div');
    div.className = 'chat-item';
    div.dataset.chatId = chat.id;

    div.innerHTML = `
        <div class="chat-item-header">
            <h4 class="chat-title">${chat.title}</h4>
            <button class="chat-menu-btn" onclick="showChatMenu(event, '${chat.id}')">
                <i class="fas fa-ellipsis-v"></i>
            </button>
        </div>
        <div class="chat-preview">${chat.preview || 'No messages yet'}</div>
        <div class="chat-timestamp">${formatTimestamp(chat.updated_at)}</div>
    `;

    div.addEventListener('click', (e) => {
        if (!e.target.closest('.chat-menu-btn')) {
            switchToChat(chat.id);
        }
    });

    return div;
}

async function createNewChat() {
    try {
        const response = await fetch('/chats/new', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (response.ok) {
            currentChatId = data.chat.id;
            await loadChatSessions(); // Refresh the list
            clearChatMessages();
            showWelcomeMessage();
            closeSidebarPanel(); // Close sidebar on mobile
        } else {
            showError(data.error || 'Failed to create new chat');
        }
    } catch (error) {
        console.error('Error creating new chat:', error);
        showError('Failed to create new chat. Please try again.');
    }
}

async function switchToChat(chatId) {
    try {
        const response = await fetch(`/chats/${chatId}/switch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });

        const data = await response.json();

        if (response.ok) {
            currentChatId = chatId;
            await loadChatMessages(chatId);
            highlightActiveChat(chatId);
            closeSidebarPanel(); // Close sidebar on mobile
        } else {
            showError(data.error || 'Failed to switch chat');
        }
    } catch (error) {
        console.error('Error switching chat:', error);
        showError('Failed to switch chat. Please try again.');
    }
}

async function loadChatMessages(chatId) {
    try {
        const response = await fetch(`/chats/${chatId}`);
        const data = await response.json();

        if (response.ok) {
            clearChatMessages();
            const messages = data.chat.messages || [];

            if (messages.length === 0) {
                showWelcomeMessage();
            } else {
                conversationStarted = true;
                messages.forEach(msg => {
                    addMessage(msg.content, msg.role, msg.model);
                });
            }
        }
    } catch (error) {
        console.error('Error loading chat messages:', error);
    }
}

// Send message
async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || isWaitingForResponse) return;

    // Clear welcome message if this is the first message
    if (!conversationStarted) {
        chatMessages.innerHTML = '';
        conversationStarted = true;
    }

    // Add user message to chat
    addMessage(message, 'user');

    // Clear input and reset height
    messageInput.value = '';
    messageInput.style.height = 'auto';
    updateCharCount();

    // Set waiting state
    isWaitingForResponse = true;
    toggleSendButton();
    showTypingIndicator();

    try {
        // Send request to backend
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: message,
                model: modelSelect.value
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to get response');
        }

        // Add AI response to chat
        hideTypingIndicator();
        addMessage(data.response, 'assistant', data.model_used);

        // Refresh chat list to update preview and timestamp
        await loadChatSessions();

    } catch (error) {
        console.error('Error sending message:', error);
        hideTypingIndicator();
        showError(error.message || 'Failed to send message. Please try again.');
    } finally {
        // Reset waiting state
        isWaitingForResponse = false;
        toggleSendButton();
        messageInput.focus();
    }
}

// Add message to chat
function addMessage(content, role, modelUsed = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    messageContent.textContent = content;

    const messageInfo = document.createElement('div');
    messageInfo.className = 'message-info';

    const timestamp = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});

    if (role === 'assistant' && modelUsed) {
        messageInfo.textContent = `${timestamp} • ${modelUsed}`;
    } else {
        messageInfo.textContent = timestamp;
    }

    messageDiv.appendChild(messageContent);
    messageDiv.appendChild(messageInfo);
    chatMessages.appendChild(messageDiv);

    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Show typing indicator
function showTypingIndicator() {
    typingIndicator.style.display = 'flex';
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Hide typing indicator
function hideTypingIndicator() {
    typingIndicator.style.display = 'none';
}

// Sidebar functions
function openSidebar() {
    sidebar.classList.add('active');
    sidebarOverlay.classList.add('active');
}

function closeSidebarPanel() {
    sidebar.classList.remove('active');
    sidebarOverlay.classList.remove('active');
}

function highlightActiveChat(chatId) {
    // Remove active class from all chat items
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });

    // Add active class to current chat
    const activeItem = document.querySelector(`[data-chat-id="${chatId}"]`);
    if (activeItem) {
        activeItem.classList.add('active');
    }
}

// Search functionality
async function searchChatSessions() {
    const query = searchChats.value.trim();

    if (!query) {
        await loadChatSessions();
        return;
    }

    try {
        const response = await fetch(`/chats/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();

        if (response.ok) {
            renderChatList(data.chats);
        }
    } catch (error) {
        console.error('Error searching chats:', error);
    }
}

// Chat menu functions
function showChatMenu(event, chatId) {
    event.stopPropagation();

    // Create context menu
    const menu = document.createElement('div');
    menu.className = 'context-menu';
    menu.innerHTML = `
        <div class="context-menu-item" onclick="renameChatDialog('${chatId}')">
            <i class="fas fa-edit"></i> Rename
        </div>
        <div class="context-menu-item delete" onclick="deleteChatConfirm('${chatId}')">
            <i class="fas fa-trash"></i> Delete
        </div>
    `;

    // Position menu
    menu.style.position = 'fixed';
    menu.style.top = event.clientY + 'px';
    menu.style.left = event.clientX + 'px';
    menu.style.zIndex = '10000';

    document.body.appendChild(menu);

    // Remove menu on click outside
    setTimeout(() => {
        document.addEventListener('click', function removeMenu() {
            if (menu.parentNode) {
                menu.parentNode.removeChild(menu);
            }
            document.removeEventListener('click', removeMenu);
        });
    }, 10);
}

function renameChatDialog(chatId) {
    currentRenameId = chatId;

    // Get current title
    const chatItem = document.querySelector(`[data-chat-id="${chatId}"]`);
    const currentTitle = chatItem.querySelector('.chat-title').textContent;

    chatTitle.value = currentTitle;
    renameModal.style.display = 'flex';
    chatTitle.focus();
}

async function deleteChatConfirm(chatId) {
    if (!confirm('Are you sure you want to delete this chat? This action cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch(`/chats/${chatId}/delete`, {
            method: 'DELETE'
        });

        if (response.ok) {
            await loadChatSessions();

            // If deleted chat was current, the backend will switch to another
            if (currentChatId === chatId) {
                // Reload to get the new current chat
                location.reload();
            }
        } else {
            const data = await response.json();
            showError(data.error || 'Failed to delete chat');
        }
    } catch (error) {
        console.error('Error deleting chat:', error);
        showError('Failed to delete chat. Please try again.');
    }
}

// Profile functions
async function loadUserProfile() {
    try {
        const response = await fetch('/profile');
        const data = await response.json();

        if (response.ok) {
            userProfile = data.profile;
            updateUserDisplay();
        }
    } catch (error) {
        console.error('Error loading user profile:', error);
    }
}

function updateUserDisplay() {
    if (userProfile && userProfile.name) {
        userName.textContent = userProfile.name;
    } else {
        userName.textContent = 'Guest User';
    }
}

function openProfileModal() {
    profileName.value = userProfile?.name || '';
    profileModal.style.display = 'flex';
    profileName.focus();
}

async function saveProfile() {
    const name = profileName.value.trim();

    try {
        const response = await fetch('/profile', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: name
            })
        });

        const data = await response.json();

        if (response.ok) {
            userProfile = data.profile;
            updateUserDisplay();
            closeProfileModal();
        } else {
            showError(data.error || 'Failed to update profile');
        }
    } catch (error) {
        console.error('Error saving profile:', error);
        showError('Failed to save profile. Please try again.');
    }
}

async function saveRename() {
    const newTitle = chatTitle.value.trim();

    if (!newTitle) {
        showError('Chat title cannot be empty');
        return;
    }

    try {
        const response = await fetch(`/chats/${currentRenameId}/rename`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                title: newTitle
            })
        });

        if (response.ok) {
            await loadChatSessions();
            closeRenameModal();
        } else {
            const data = await response.json();
            showError(data.error || 'Failed to rename chat');
        }
    } catch (error) {
        console.error('Error renaming chat:', error);
        showError('Failed to rename chat. Please try again.');
    }
}

// Utility functions for UI
function clearChatMessages() {
    chatMessages.innerHTML = '';
    conversationStarted = false;
}

function showWelcomeMessage() {
    chatMessages.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-content">
                <i class="fas fa-comments"></i>
                <h2>Welcome to AI Chat!</h2>
                <p>Start a conversation with our AI assistant powered by Groq. Ask questions, get help, or just chat!</p>
            </div>
        </div>
    `;
    conversationStarted = false;
}

// Show error modal
function showError(message) {
    errorMessage.textContent = message;
    errorModal.style.display = 'flex';
}

// Modal functions
function closeErrorModal() {
    errorModal.style.display = 'none';
}

function closeProfileModal() {
    profileModal.style.display = 'none';
}

function closeRenameModal() {
    renameModal.style.display = 'none';
}

// Close modal with close button
document.querySelector('.modal-close').addEventListener('click', closeErrorModal);
