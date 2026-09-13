// --- Unified Authentication & Session Layer for Virtual Recipe Box ---
(function() {
    window.Auth = {
        user: null,
        initialized: false,
        initPromise: null,

        // Initialize and check if user is logged in
        async init() {
            if (this.initPromise) return this.initPromise;
            this.initPromise = (async () => {
                try {
                    const res = await fetch('/api/auth/me', { credentials: 'include' });
                    if (res.ok) {
                        const data = await res.json();
                        this.user = data.user;
                    } else {
                        this.user = null;
                    }
                } catch (e) {
                    console.warn('Auth check error:', e);
                    this.user = null;
                }
                this.initialized = true;
                this.renderNav();
                return this.user;
            })();
            return this.initPromise;
        },

        getUser() {
            return this.user;
        },

        isLoggedIn() {
            return !!this.user;
        },

        async login(usernameOrEmail, password) {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ username: usernameOrEmail, password })
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Login failed');
            }
            this.user = data.user;
            this.renderNav();
            return data.user;
        },

        async register(username, email, password, displayName) {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    username,
                    email,
                    password,
                    display_name: displayName || username
                })
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Registration failed');
            }
            this.user = data.user;
            this.renderNav();
            return data.user;
        },

        async logout() {
            try {
                await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
            } catch (e) {
                console.warn('Logout error:', e);
            }
            this.user = null;
            this.renderNav();
            window.location.href = 'login.html';
        },

        async updateProfile({ displayName, currentPassword, newPassword }) {
            const res = await fetch('/api/auth/profile', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    display_name: displayName,
                    current_password: currentPassword,
                    new_password: newPassword
                })
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Failed to update profile');
            }
            if (displayName && this.user) {
                this.user.display_name = displayName;
                this.renderNav();
            }
            return data;
        },

        // Guard a page: if not logged in, show login prompt or redirect to login.html
        async requireAuth(onAuthenticated) {
            const user = await this.init();
            if (!user) {
                const currentPage = window.location.pathname.split('/').pop() || 'index.html';
                if (currentPage !== 'login.html') {
                    window.location.href = `login.html?redirect=${encodeURIComponent(window.location.href)}`;
                    return;
                }
            } else if (typeof onAuthenticated === 'function') {
                onAuthenticated(user);
            }
        },

        // Render user button / dropdown in header navigation
        renderNav() {
            let container = document.getElementById('userNavWidget');
            if (!container) {
                const nav = document.querySelector('header nav ul');
                if (nav) {
                    const li = document.createElement('li');
                    li.id = 'userNavWidget';
                    li.style.marginLeft = 'auto';
                    li.style.position = 'relative';
                    nav.appendChild(li);
                    container = li;
                }
            }

            if (!container) return;

            if (this.user) {
                const initial = (this.user.display_name || this.user.username || 'U')[0].toUpperCase();
                const name = this.user.display_name || this.user.username;
                container.innerHTML = `
                    <div class="user-pill-btn" id="userPillBtn" onclick="window.Auth.toggleUserMenu(event)">
                        <span class="user-avatar-initial">${initial}</span>
                        <span class="user-display-name">${escapeAuthHtml(name)}</span>
                        <span class="user-arrow">▾</span>
                    </div>
                    <div class="user-dropdown-menu" id="userDropdownMenu">
                        <div class="user-dropdown-header">
                            <div class="user-dropdown-avatar">${initial}</div>
                            <div class="user-dropdown-info">
                                <div class="user-dropdown-name">${escapeAuthHtml(name)}</div>
                                <div class="user-dropdown-email">${escapeAuthHtml(this.user.email || '')}</div>
                            </div>
                        </div>
                        <div class="user-dropdown-divider"></div>
                        <a href="feed.html?filter=my_posts" class="user-dropdown-item">👤 <strong>My Posts & Activity</strong></a>
                        <a href="feed.html?filter=close_friends" class="user-dropdown-item">⭐ Close Friends Feed</a>
                        <a href="recipes.html" class="user-dropdown-item">🍲 My Recipe Box</a>
                        <a href="planner.html" class="user-dropdown-item">📅 Weekly Planner</a>
                        <div class="user-dropdown-divider"></div>
                        <a href="javascript:void(0)" onclick="window.Auth.openProfileModal()" class="user-dropdown-item">⚙️ Account Settings</a>
                        <a href="javascript:void(0)" onclick="window.Auth.logout()" class="user-dropdown-item text-danger">🚪 Log Out</a>
                    </div>
                `;
            } else {
                container.innerHTML = `
                    <a href="login.html?redirect=${encodeURIComponent(window.location.href)}" class="auth-login-link-btn">
                        🔐 Log In / Sign Up
                    </a>
                `;
            }
        },

        toggleUserMenu(e) {
            e.stopPropagation();
            const menu = document.getElementById('userDropdownMenu');
            if (menu) {
                menu.classList.toggle('show');
            }
        },

        openProfileModal() {
            const menu = document.getElementById('userDropdownMenu');
            if (menu) menu.classList.remove('show');

            let modal = document.getElementById('userProfileModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'userProfileModal';
                modal.className = 'auth-modal-overlay';
                document.body.appendChild(modal);
            }

            const name = this.user ? (this.user.display_name || this.user.username) : '';
            const email = this.user ? this.user.email : '';
            const username = this.user ? this.user.username : '';

            modal.innerHTML = `
                <div class="auth-modal-content">
                    <div class="auth-modal-header">
                        <h3>👤 Account Settings</h3>
                        <button class="auth-modal-close" onclick="window.Auth.closeProfileModal()">&times;</button>
                    </div>
                    <form id="profileSettingsForm" onsubmit="window.Auth.handleProfileSubmit(event)">
                        <div class="auth-form-group">
                            <label>Username</label>
                            <input type="text" value="${escapeAuthHtml(username)}" disabled style="opacity:0.7; cursor:not-allowed;" />
                        </div>
                        <div class="auth-form-group">
                            <label>Email Address</label>
                            <input type="email" value="${escapeAuthHtml(email)}" disabled style="opacity:0.7; cursor:not-allowed;" />
                        </div>
                        <div class="auth-form-group">
                            <label>Display Name</label>
                            <input type="text" id="profDisplayName" value="${escapeAuthHtml(name)}" required />
                        </div>
                        <div class="auth-form-divider"><span>Change Password (Optional)</span></div>
                        <div class="auth-form-group">
                            <label>Current Password</label>
                            <input type="password" id="profCurrentPassword" placeholder="Required only if changing password" />
                        </div>
                        <div class="auth-form-group">
                            <label>New Password (min. 8 characters)</label>
                            <input type="password" id="profNewPassword" placeholder="Leave blank to keep current password" />
                        </div>
                        <div id="profStatusMsg" class="auth-msg-banner" style="display:none;"></div>
                        <div class="auth-modal-footer">
                            <button type="button" class="btn-cancel" onclick="window.Auth.closeProfileModal()">Cancel</button>
                            <button type="submit" class="btn-save" id="profSaveBtn">Save Changes</button>
                        </div>
                    </form>
                </div>
            `;
            modal.style.display = 'flex';
        },

        closeProfileModal() {
            const modal = document.getElementById('userProfileModal');
            if (modal) modal.style.display = 'none';
        },

        async handleProfileSubmit(e) {
            e.preventDefault();
            const displayName = document.getElementById('profDisplayName').value.trim();
            const currentPassword = document.getElementById('profCurrentPassword').value;
            const newPassword = document.getElementById('profNewPassword').value;
            const statusMsg = document.getElementById('profStatusMsg');
            const saveBtn = document.getElementById('profSaveBtn');

            statusMsg.style.display = 'none';
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';

            try {
                await this.updateProfile({ displayName, currentPassword, newPassword });
                statusMsg.className = 'auth-msg-banner success';
                statusMsg.textContent = '✅ Profile updated successfully!';
                statusMsg.style.display = 'block';
                setTimeout(() => {
                    this.closeProfileModal();
                }, 1200);
            } catch (err) {
                statusMsg.className = 'auth-msg-banner error';
                statusMsg.textContent = '❌ ' + err.message;
                statusMsg.style.display = 'block';
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Changes';
            }
        }
    };

    function escapeAuthHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // Close dropdown menu on outside click
    document.addEventListener('click', (e) => {
        const menu = document.getElementById('userDropdownMenu');
        const btn = document.getElementById('userPillBtn');
        if (menu && menu.classList.contains('show')) {
            if (!menu.contains(e.target) && !btn.contains(e.target)) {
                menu.classList.remove('show');
            }
        }
    });

    // Inject Auth Styles
    const style = document.createElement('style');
    style.textContent = `
        .user-pill-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(255, 255, 255, 0.22);
            padding: 5px 14px 5px 6px;
            border-radius: 24px;
            cursor: pointer;
            color: white;
            font-weight: 600;
            font-size: 0.9em;
            transition: all 0.2s ease;
            user-select: none;
            backdrop-filter: blur(4px);
            border: 1px solid rgba(255,255,255,0.3);
        }
        .user-pill-btn:hover {
            background: rgba(255, 255, 255, 0.35);
            transform: translateY(-1px);
        }
        .user-avatar-initial {
            width: 26px;
            height: 26px;
            border-radius: 50%;
            background: white;
            color: var(--primary-pink, #FF6B81);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 0.85em;
            box-shadow: 0 1px 3px rgba(0,0,0,0.15);
        }
        .user-arrow {
            font-size: 0.8em;
            opacity: 0.85;
            transition: transform 0.2s ease;
        }
        .user-dropdown-menu {
            display: none;
            position: absolute;
            right: 0;
            top: 115%;
            background: var(--card-background, #ffffff);
            color: var(--text-color, #333333);
            border: 1px solid var(--border-color, #e0e0e0);
            border-radius: 12px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.18);
            min-width: 230px;
            z-index: 1000;
            padding: 8px 0;
            overflow: hidden;
            animation: authFadeIn 0.15s ease-out;
        }
        .user-dropdown-menu.show {
            display: block;
        }
        .user-dropdown-header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            background: rgba(0,0,0,0.03);
        }
        body.dark-mode .user-dropdown-header {
            background: rgba(255,255,255,0.04);
        }
        .user-dropdown-avatar {
            width: 38px;
            height: 38px;
            border-radius: 50%;
            background: var(--primary-pink, #FF6B81);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 1.1em;
            flex-shrink: 0;
        }
        .user-dropdown-info {
            overflow: hidden;
        }
        .user-dropdown-name {
            font-weight: 700;
            font-size: 0.95em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--text-color, #333);
        }
        body.dark-mode .user-dropdown-name {
            color: #f0f0f0;
        }
        .user-dropdown-email {
            font-size: 0.78em;
            opacity: 0.7;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .user-dropdown-divider {
            height: 1px;
            background: var(--border-color, #e0e0e0);
            margin: 6px 0;
        }
        .user-dropdown-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 16px;
            color: var(--text-color, #333);
            text-decoration: none;
            font-size: 0.9em;
            font-weight: 600;
            transition: background 0.15s ease;
        }
        body.dark-mode .user-dropdown-item {
            color: #f0f0f0;
        }
        .user-dropdown-item:hover {
            background: var(--light-pink, #FFE8EE);
            color: var(--primary-pink, #FF6B81);
        }
        body.dark-mode .user-dropdown-item:hover {
            background: rgba(254, 155, 163, 0.15);
            color: var(--primary-pink, #FE9BA3);
        }
        .user-dropdown-item.text-danger {
            color: #e74c3c;
        }
        .user-dropdown-item.text-danger:hover {
            background: rgba(231, 76, 60, 0.1);
            color: #c0392b;
        }
        .auth-login-link-btn {
            background: rgba(255, 255, 255, 0.2);
            color: white !important;
            padding: 6px 16px !important;
            border-radius: 20px;
            font-weight: 600;
            text-decoration: none;
            display: inline-block;
            transition: all 0.2s ease;
            border: 1px solid rgba(255,255,255,0.4);
        }
        .auth-login-link-btn:hover {
            background: rgba(255, 255, 255, 0.35) !important;
            transform: translateY(-1px);
        }
        .auth-modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.6);
            backdrop-filter: blur(4px);
            z-index: 9999;
            align-items: center;
            justify-content: center;
            padding: 15px;
        }
        .auth-modal-content {
            background: var(--card-background, #ffffff);
            color: var(--text-color, #333333);
            border-radius: 16px;
            width: 100%;
            max-width: 440px;
            padding: 24px;
            box-shadow: 0 15px 35px rgba(0,0,0,0.25);
            border: 1px solid var(--border-color, #e0e0e0);
            animation: authModalPop 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }
        @keyframes authModalPop {
            from { transform: scale(0.9); opacity: 0; }
            to { transform: scale(1); opacity: 1; }
        }
        @keyframes authFadeIn {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .auth-modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 18px;
            border-bottom: 1px solid var(--border-color, #e0e0e0);
            padding-bottom: 12px;
        }
        .auth-modal-header h3 {
            margin: 0;
            font-family: 'Playfair Display', serif;
            color: var(--primary-pink, #FF6B81);
            font-size: 1.3em;
        }
        .auth-modal-close {
            background: none;
            border: none;
            font-size: 1.6em;
            cursor: pointer;
            color: var(--text-color, #888);
            line-height: 1;
            padding: 0 4px;
        }
        .auth-modal-close:hover {
            color: var(--primary-pink, #FF6B81);
        }
        .auth-form-group {
            margin-bottom: 14px;
            text-align: left;
        }
        .auth-form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            font-size: 0.85em;
            color: var(--text-color, #444);
        }
        body.dark-mode .auth-form-group label {
            color: #ddd;
        }
        .auth-form-group input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--border-color, #ccc);
            border-radius: 8px;
            background: var(--background-color, #fff);
            color: var(--text-color, #333);
            box-sizing: border-box;
            font-size: 0.95em;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }
        .auth-form-group input:focus {
            outline: none;
            border-color: var(--primary-pink, #FF6B81);
            box-shadow: 0 0 0 3px rgba(255, 107, 129, 0.2);
        }
        .auth-form-divider {
            text-align: center;
            border-bottom: 1px dashed var(--border-color, #ccc);
            line-height: 0.1em;
            margin: 20px 0 16px 0;
        }
        .auth-form-divider span {
            background: var(--card-background, #fff);
            padding: 0 10px;
            font-size: 0.8em;
            color: var(--text-color, #888);
            font-weight: 600;
        }
        .auth-msg-banner {
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 14px;
            font-size: 0.88em;
            font-weight: 600;
        }
        .auth-msg-banner.error {
            background: #fde8e8;
            color: #c81e1e;
            border: 1px solid #f8b4b4;
        }
        .auth-msg-banner.success {
            background: #def7ec;
            color: #03543f;
            border: 1px solid #bcf0da;
        }
        body.dark-mode .auth-msg-banner.error {
            background: #4e1919;
            color: #fca5a5;
            border: 1px solid #7f1d1d;
        }
        body.dark-mode .auth-msg-banner.success {
            background: #133a28;
            color: #86efac;
            border: 1px solid #14532d;
        }
        .auth-modal-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 18px;
        }
        .auth-modal-footer button {
            padding: 9px 18px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 0.9em;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .auth-modal-footer .btn-cancel {
            background: transparent;
            border: 1px solid var(--border-color, #ccc);
            color: var(--text-color, #555);
        }
        body.dark-mode .auth-modal-footer .btn-cancel {
            color: #ddd;
        }
        .auth-modal-footer .btn-save {
            background: var(--primary-pink, #FF6B81);
            color: white;
            border: none;
        }
        .auth-modal-footer .btn-save:hover {
            background: var(--button-hover, #E85B70);
        }
    `;
    document.head.appendChild(style);

    // Auto initialize on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.Auth.init());
    } else {
        window.Auth.init();
    }
})();
