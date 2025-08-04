// --- START OF COMPLETE frontend/app.js FILE ---

// Wrap the entire application in a try...catch block.
// If any error occurs during initialization, it will be displayed on the screen.
try {
    document.addEventListener('DOMContentLoaded', () => {
        // --- App Setup ---
        if (!window.Telegram || !window.Telegram.WebApp) {
            document.body.innerHTML = '<h1>Error: Telegram WebApp script not found.</h1><p>Please ensure you are opening this in the Telegram app and that telegram-web-app.js is loaded correctly.</p>';
            console.error("Telegram WebApp object is not available.");
            return;
        }
        
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();

        const app = {
            header: document.getElementById('app-header'),
            content: document.getElementById('app-content'),
            state: { currentUser: null, navigationStack: [] },
            apiBaseUrl: 'http://127.0.0.1:8000', // IMPORTANT: Change for production
        };

        // --- API Helper ---
        async function apiFetch(endpoint, options = {}) {
            // No tg.showProgress in this version to simplify debugging
            try {
                const response = await fetch(`${app.apiBaseUrl}${endpoint}`, {
                    ...options,
                    headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg.initData, ...options.headers },
                });
                if (!response.ok) {
                    const error = await response.json().catch(() => ({ detail: `HTTP error! Status: ${response.status}` }));
                    throw new Error(error.detail);
                }
                return response.status === 204 ? null : await response.json();
            } catch (error) {
                // Display API errors directly on the screen for easy debugging
                renderErrorPage('API Error', error.message);
                throw error;
            }
        }
        
        // --- Navigation ---
        function navigateTo(pageFunction, ...args) {
            // Prevent duplicate page pushes
            const currentPage = app.state.navigationStack[app.state.navigationStack.length - 1];
            if (currentPage && currentPage.func === pageFunction && JSON.stringify(currentPage.args) === JSON.stringify(args)) {
                return; // Do not navigate to the same page with the same arguments
            }
            app.state.navigationStack.push({ func: pageFunction, args });
            pageFunction(...args);
        }

        function goBack() {
            app.state.navigationStack.pop(); // Remove current page
            const previousPage = app.state.navigationStack[app.state.navigationStack.length - 1];
            if (previousPage) {
                previousPage.func(...previousPage.args);
            } else {
                navigateTo(renderMainMenu); // Should not happen, but as a fallback
            }
        }
        
        // --- Page & Header Rendering ---
        function renderHeader(title, showBackButton = false) {
            let backButtonHtml = showBackButton ? `<button class="back-button">‹ Back</button>` : '';
            app.header.innerHTML = `${backButtonHtml}<div class="header-title">${title}</div>`;
            if (showBackButton) {
                app.header.querySelector('.back-button').addEventListener('click', goBack);
            }
        }

        function render(contentHtml, eventBinder) {
            app.content.innerHTML = contentHtml;
            if (eventBinder) eventBinder();
            app.content.scrollTop = 0;
        }

        function renderLoading() {
            render(`<div class="loader-container"><div class="loader"></div></div>`);
        }
        
        function renderErrorPage(title, message) {
             renderHeader('Error');
             render(`
                <div class="info-text">
                    <h2>${title}</h2>
                    <p>${message}</p>
                    <button class="button" onclick="location.reload()">Try Again</button>
                </div>
            `);
        }

        async function renderMainMenu() {
            renderHeader('Gadwa App');
            renderLoading();
            const myProfile = await apiFetch('/api/me');
            app.state.currentUser = myProfile;
            const html = `
                <div class="profile-header">
                    <h1>Welcome, ${myProfile.username}</h1>
                    <p>Your UID: <code class="uid">${myProfile.unique_id}</code></p>
                </div>
                <button data-action="chats" class="button">Message History</button>
                <button data-action="friends" class="button">Friends</button>
                <button data-action="requests" class="button">Friend Requests</button>
                <button data-action="search" class="button secondary">Search User by UID</button>
            `;
            render(html, () => {
                app.content.addEventListener('click', (e) => {
                    const action = e.target.dataset.action;
                    if (!action) return;
                    if (action === "chats") navigateTo(renderChatList);
                    if (action === "friends") navigateTo(renderFriendsList);
                    if (action === "requests") navigateTo(renderRequests);
                    if (action === "search") handleSearch();
                });
            });
        }
        
        async function renderChatList() {
            renderHeader('Chats', true);
            renderLoading();
            const chats = await apiFetch('/api/chats');
            const content = chats.length === 0
                ? `<p class="info-text">You have no message history yet.</p>`
                : chats.map(chat => `
                    <div class="list-item" data-uid="${chat.partner_uid}">
                        <div class="item-info">
                            <div class="main-info">${chat.partner_username || 'Unknown User'}</div>
                            <div class="sub-info">${chat.last_message_text || '...'}</div>
                        </div>
                        ${chat.unread_count > 0 ? `<div class="unread-badge">${chat.unread_count}</div>` : ''}
                    </div>
                `).join('');
            render(content, () => {
                app.content.querySelectorAll('.list-item').forEach(item => {
                    item.addEventListener('click', e => navigateTo(renderChat, e.currentTarget.dataset.uid));
                });
            });
        }
        
        // This is a placeholder for a more complex function that would need the full user list
        // For now, we'll just try to get the username from the API response or show the UID
        async function getPartnerUsername(partnerUid) {
            try {
                const profile = await apiFetch(`/api/profile/${partnerUid}`);
                return profile.username;
            } catch (e) {
                return partnerUid; // Fallback to UID if profile fetch fails
            }
        }

        async function renderChat(partnerUid) {
            const partnerUsername = await getPartnerUsername(partnerUid);
            renderHeader(`Chat with ${partnerUsername}`, true);
            render(`<div id="chat-content"><div id="chat-messages" class="loader-container"><div class="loader"></div></div><div class="chat-input-area"><textarea id="message-input" placeholder="Type a message..." rows="1"></textarea><button id="send-btn">➤</button></div></div>`);

            const { messages } = await apiFetch(`/api/chat/${partnerUid}`);
            const messagesHtml = messages.map(msg => {
                const isSent = msg.sender_uid === app.state.currentUser.unique_id;
                return `<div class="chat-bubble ${isSent ? 'sent' : 'received'}">${msg.text}</div>`;
            }).join('');
            
            const chatMessagesDiv = document.getElementById('chat-messages');
            chatMessagesDiv.innerHTML = messagesHtml;
            chatMessagesDiv.scrollTop = chatMessagesDiv.scrollHeight;

            document.getElementById('send-btn').addEventListener('click', async () => {
                const input = document.getElementById('message-input');
                const text = input.value.trim();
                if (text) {
                    input.disabled = true;
                    await apiFetch(`/api/message/${partnerUid}`, { method: 'POST', body: JSON.stringify({ text }) });
                    renderChat(partnerUid); // Re-render chat
                }
            });
        }

        async function renderProfile(targetUid) {
            renderHeader('Profile', true);
            renderLoading();
            const profile = await apiFetch(`/api/profile/${targetUid}`);
            const { relation } = profile;

            let buttonsHtml = '';
            if (!relation.is_me) {
                 if (relation.is_blocked) {
                    buttonsHtml = `<button data-action="unblock" class="button">Unblock User</button>`;
                } else {
                    if (relation.is_friend) {
                        buttonsHtml += `<button data-action="unfriend" class="button secondary">Unfriend</button>`;
                    } else if (relation.sent_request) {
                        buttonsHtml += `<button data-action="cancel_request" class="button secondary">Cancel Request</button>`;
                    } else if (relation.received_request) {
                        buttonsHtml += `<div class="button-group"><button data-action="accept_friend" class="button">Accept</button><button data-action="decline_friend" class="button secondary">Decline</button></div>`;
                    } else {
                        buttonsHtml += `<button data-action="add_friend" class="button">🤝 Add Friend</button>`;
                    }
                    buttonsHtml += `<button data-action="block" class="button destructive">Block User</button>`;
                }
            }

            const html = `
                <div class="profile-header">
                    <h1>${profile.username}</h1>
                    <p>Status: <span class="status">${profile.status}</span></p>
                    <p>UID: <code class="uid">${profile.unique_id}</code></p>
                </div>
                <div id="action-buttons">${buttonsHtml}</div>
            `;

            render(html, () => {
                document.getElementById('action-buttons').addEventListener('click', async (e) => {
                    if (e.target.tagName === 'BUTTON') {
                        const action = e.target.dataset.action;
                        if (action === 'add_friend') {
                            await apiFetch(`/api/friend_request/${targetUid}`, { method: 'POST' });
                        } else {
                            await apiFetch(`/api/action/${action}/${targetUid}`, { method: 'POST' });
                        }
                        tg.showAlert(`Action '${action.replace('_', ' ')}' was successful!`);
                        renderProfile(targetUid);
                    }
                });
            });
        }

        async function renderFriendsList() {
            renderHeader('Friends', true);
            renderLoading();
            const friends = await apiFetch('/api/friends');
            const content = friends.length === 0
                ? `<p class="info-text">You haven't added any friends yet.</p>`
                : friends.map(friend => `
                    <div class="list-item" data-uid="${friend.unique_id}">
                        <div class="main-info">${friend.username}</div>
                        <div class="sub-info">UID: ${friend.unique_id}</div>
                    </div>
                `).join('');
            render(content, () => {
                app.content.querySelectorAll('.list-item').forEach(item => {
                    item.addEventListener('click', e => navigateTo(renderProfile, e.currentTarget.dataset.uid));
                });
            });
        }

        async function renderRequests() {
            renderHeader('Friend Requests', true);
            renderLoading();
            const { received, sent } = await apiFetch('/api/requests');
            const renderRequestList = (list, type) => {
                if (list.length === 0) return `<p class="info-text">None</p>`;
                return list.map(req => `
                    <div class="list-item" style="flex-direction: column; align-items: stretch;">
                        <div style="display: flex; justify-content: space-between; align-items: center; width: 100%; margin-bottom: 10px;">
                            <div class="main-info">${req.username}</div>
                            <div class="sub-info">UID: ${req.unique_id}</div>
                        </div>
                        ${type === 'received' 
                            ? `<div class="button-group"><button data-action="accept_friend" data-uid="${req.unique_id}" class="button">Accept</button><button data-action="decline_friend" data-uid="${req.unique_id}" class="button secondary">Decline</button></div>`
                            : `<button data-action="cancel_request" data-uid="${req.unique_id}" class="button secondary">Cancel</button>`}
                    </div>
                `).join('');
            };
            const html = `
                <div class="section-title">Received Requests</div>
                <div id="received-requests">${renderRequestList(received, 'received')}</div>
                <div class="section-title">Sent Requests</div>
                <div id="sent-requests">${renderRequestList(sent, 'sent')}</div>
            `;
            render(html, () => {
                app.content.addEventListener('click', async (e) => {
                    if (e.target.tagName === 'BUTTON' && e.target.dataset.action) {
                        const action = e.target.dataset.action;
                        const uid = e.target.dataset.uid;
                        await apiFetch(`/api/action/${action}/${uid}`, { method: 'POST' });
                        tg.showAlert('Request updated!');
                        renderRequests();
                    }
                });
            });
        }

        function handleSearch() {
            tg.showPopup({
                title: 'Search User',
                message: 'Enter the 8-digit Unique ID of the user you want to find.',
                buttons: [{ id: 'search', type: 'default', text: 'Search' }, { type: 'cancel' }],
                // The 'text' parameter in the callback is deprecated. We need to use `WebAppPopup.getForm()` if we wanted a real input.
                // For simplicity, we are assuming the basic popup returns the text. If not, this needs adjustment.
            }, (buttonId, text_or_null) => {
                // This part of tg API is tricky and might not work on all platforms as expected.
                // This is a placeholder for a more robust solution.
                // For now, we will prompt the user.
                const uid = prompt("Enter the 8-digit User ID:");
                if (uid && /^\d{8}$/.test(uid)) {
                     navigateTo(renderProfile, uid.trim());
                } else if (uid) {
                    tg.showAlert("Invalid UID format. Please enter 8 digits.");
                }
            });
        }
        
        // --- Initial Load ---
        navigateTo(renderMainMenu);
    });
} catch (e) {
    // If ANY error happens, display it on the screen.
    document.body.innerHTML = `
        <div style="font-family: sans-serif; padding: 15px; color: #E57373; background-color: #121212; height: 100vh;">
            <h1>A Critical Error Occurred</h1>
            <p>The application could not start. This is a bug.</p>
            <p><b>Error Message:</b></p>
            <pre style="background: #212121; padding: 10px; border-radius: 5px; white-space: pre-wrap; word-break: break-all;">${e.message}</pre>
            <p><b>Stack Trace:</b></p>
            <pre style="background: #212121; padding: 10px; border-radius: 5px; white-space: pre-wrap; word-break: break-all;">${e.stack}</pre>
        </div>
    `;
}

// --- END OF COMPLETE frontend/app.js FILE ---
