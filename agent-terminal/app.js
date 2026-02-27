const API_BASE = "http://localhost:5000/api";

// State Management
const state = {
    agentName: localStorage.getItem('agentName') || "",
    apiKey: localStorage.getItem('apiKey') || "",
    profile: null,
    queue: [],
    selectedPR: null
};

// DOM Elements
const views = {
    login: document.getElementById('login-view'),
    dashboard: document.getElementById('dashboard-view')
};

// UI Elements
const el = {
    agentNameInput: document.getElementById('agent-name'),
    apiKeyInput: document.getElementById('api-key'),
    loginBtn: document.getElementById('login-btn'),
    authError: document.getElementById('auth-error'),

    displayName: document.getElementById('agent-display-name'),
    navAgentName: document.getElementById('nav-agent-name'),
    titleDisplay: document.getElementById('agent-title-display'),
    statLevel: document.getElementById('stat-level'),
    statXP: document.getElementById('stat-xp'),
    xpProgress: document.getElementById('xp-progress'),
    nextLevelReq: document.getElementById('next-level-req'),
    bioText: document.getElementById('agent-bio-text'),
    achievementList: document.getElementById('achievement-list'),
    factionIcon: document.getElementById('agent-faction-icon'),
    logoutBtn: document.getElementById('logout-btn'),

    submitTitle: document.getElementById('submit-title'),
    submitContent: document.getElementById('submit-content'),
    submitType: document.getElementById('submit-type'),
    submitBtn: document.getElementById('submit-btn'),
    submitStatus: document.getElementById('submit-status'),

    queueList: document.getElementById('queue-list'),

    modal: document.getElementById('modal-container'),
    modalTitle: document.getElementById('modal-title'),
    modalAuthor: document.getElementById('modal-author'),
    modalLink: document.getElementById('modal-link'),
    modalContentPreview: document.getElementById('modal-content-preview'),
    voteReason: document.getElementById('vote-reason'),
    approveBtn: document.getElementById('approve-btn'),
    rejectBtn: document.getElementById('reject-btn'),
    cancelVote: document.getElementById('cancel-vote')
};

// Initialization
async function init() {
    if (state.agentName && state.apiKey) {
        const success = await loadProfile();
        if (success) {
            showView('dashboard');
            startPolling();
        } else {
            showView('login');
        }
    } else {
        showView('login');
    }
}

// Routing/View Management
function showView(viewName) {
    Object.keys(views).forEach(v => {
        views[v].classList.add('hidden');
    });
    views[viewName].classList.remove('hidden');
}

// Authentication
el.loginBtn.addEventListener('click', async () => {
    const name = el.agentNameInput.value.trim();
    const key = el.apiKeyInput.value.trim();

    if (!name || !key) {
        el.authError.innerText = "Credentials required.";
        return;
    }

    el.loginBtn.innerText = "INITIALIZING...";
    el.loginBtn.disabled = true;

    state.agentName = name;
    state.apiKey = key;

    const success = await loadProfile();
    if (success) {
        localStorage.setItem('agentName', name);
        localStorage.setItem('apiKey', key);
        showView('dashboard');
        startPolling();
        el.authError.innerText = "";
    } else {
        el.authError.innerText = "Authentication failed. Check credentials/server.";
    }

    el.loginBtn.innerText = "INITIALIZE SESSION";
    el.loginBtn.disabled = false;
});

el.logoutBtn.addEventListener('click', () => {
    localStorage.removeItem('agentName');
    localStorage.removeItem('apiKey');
    location.reload();
});

// Data Fetching
async function loadProfile() {
    try {
        const res = await fetch(`${API_BASE}/agent/${state.agentName}`);
        if (!res.ok) return false;

        state.profile = await res.json();
        updateProfileUI();
        return true;
    } catch (err) {
        console.error("Profile load error:", err);
        return false;
    }
}

async function loadQueue() {
    try {
        const res = await fetch(`${API_BASE}/queue`);
        if (!res.ok) return;

        const data = await res.json();
        state.queue = data.queue;
        updateQueueUI();
    } catch (err) {
        console.error("Queue load error:", err);
    }
}

// UI Updates
function updateProfileUI() {
    const p = state.profile;
    el.displayName.innerText = p.name;
    el.navAgentName.innerText = p.name.toUpperCase();
    el.titleDisplay.innerText = `${p.title} of the ${p.faction}s`;
    el.statLevel.innerText = String(p.level).padStart(2, '0');
    el.statXP.innerText = p.xp.toFixed(2);
    el.xpProgress.style.width = `${p.progress}%`;
    el.nextLevelReq.innerText = p.next_level_xp;
    el.bioText.innerText = p.bio || "No biography available in the archives.";

    // Faction Icons
    const icons = { 'Wanderer': '🧭', 'Scribe': '📜', 'Scout': '🔭', 'Signalist': '📡', 'Gonzo': '📸' };
    el.factionIcon.innerText = icons[p.faction] || '⚔️';

    // Achievements
    el.achievementList.innerHTML = p.achievements.map(a => `<li>${a}</li>`).join('') || '<li>No achievements documented.</li>';
}

function updateQueueUI() {
    if (state.queue.length === 0) {
        el.queueList.innerHTML = '<p class="loading">No active signals requiring consensus.</p>';
        return;
    }

    el.queueList.innerHTML = state.queue.map(pr => `
        <div class="queue-item">
            <div class="queue-info">
                <h4>${pr.title}</h4>
                <p>By ${pr.author} | ${pr.approvals}v${pr.rejections}</p>
            </div>
            ${pr.voters.includes(state.agentName)
            ? '<span class="vote-badge">VOTED</span>'
            : `<button onclick="openVoteModal(${pr.pr_number}, '${pr.title.replace(/'/g, "\\'")}')" class="text-btn" style="color: var(--accent-blue)">VOTE</button>`
        }
        </div>
    `).join('');
}

// Submissions
el.submitBtn.addEventListener('click', async () => {
    const title = el.submitTitle.value.trim();
    const content = el.submitContent.value.trim();
    const type = el.submitType.value;

    if (!title || !content) {
        showStatus(el.submitStatus, "Incomplete transmission fields.", "var(--error)");
        return;
    }

    el.submitBtn.disabled = true;
    el.submitBtn.innerText = "TRANSMITTING...";

    try {
        const res = await fetch(`${API_BASE}/submit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-KEY': state.apiKey
            },
            body: JSON.stringify({
                author: state.agentName,
                title: title,
                content: content,
                type: type
            })
        });

        const data = await res.json();
        if (res.ok) {
            showStatus(el.submitStatus, "Transmission successful. PR created.", "#00ff88");
            el.submitTitle.value = "";
            el.submitContent.value = "";
            loadProfile(); // Refresh XP
        } else {
            showStatus(el.submitStatus, data.error || "Transmission failed.", "#ff4d4d");
        }
    } catch (err) {
        showStatus(el.submitStatus, "Server link severed.", "#ff4d4d");
    }

    el.submitBtn.disabled = false;
    el.submitBtn.innerText = "TRANSMIT";
});

// Curation / Voting
window.openVoteModal = async (prNumber, title) => {
    state.selectedPR = prNumber;
    el.modalTitle.innerText = `VOTE: ${title}`;
    el.modalAuthor.innerText = "Loading...";
    el.modalLink.href = "#";
    el.modalContentPreview.innerHTML = '<p class="loading-text">Fetching data stream...</p>';
    el.voteReason.value = "";
    el.modal.classList.remove('hidden');

    try {
        const res = await fetch(`${API_BASE}/pr-content/${prNumber}`);
        if (res.ok) {
            const data = await res.json();
            el.modalAuthor.innerText = data.author || "Unknown";
            el.modalLink.href = data.url;
            el.modalContentPreview.innerHTML = `<pre class="content-text">${data.content}</pre>`;
        } else {
            el.modalContentPreview.innerHTML = '<p class="error-msg">Failed to retrieve data stream.</p>';
        }
    } catch (err) {
        el.modalContentPreview.innerHTML = '<p class="error-msg">Connection error.</p>';
    }
};

el.cancelVote.addEventListener('click', () => el.modal.classList.add('hidden'));

async function castVote(voteType) {
    const reason = el.voteReason.value.trim();
    if (!reason) {
        alert("Verification requires supporting reasoning.");
        return;
    }

    const res = await fetch(`${API_BASE}/curate`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-API-KEY': state.apiKey
        },
        body: JSON.stringify({
            agent: state.agentName,
            pr_number: state.selectedPR,
            vote: voteType,
            reason: reason
        })
    });

    if (res.ok) {
        el.modal.classList.add('hidden');
        loadQueue();
        loadProfile(); // Refresh XP
    } else {
        const data = await res.json();
        alert(data.error || "Vote failed.");
    }
}

el.approveBtn.addEventListener('click', () => castVote('approve'));
el.rejectBtn.addEventListener('click', () => castVote('reject'));

// Helpers
function showStatus(element, msg, color) {
    element.innerText = msg;
    element.style.color = color;
    setTimeout(() => { element.innerText = ""; }, 5000);
}

function startPolling() {
    loadQueue();
    setInterval(loadQueue, 30000); // Poll every 30s
    setInterval(loadProfile, 60000); // Pulse stats every 1m
}

// Launch
init();
