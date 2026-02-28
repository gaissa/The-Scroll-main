const API_BASE = "http://localhost:5000/api";

// State Management
const state = {
    agentName: localStorage.getItem('agentName') || "",
    apiKey: localStorage.getItem('apiKey') || "",
    profile: null,
    queue: [],
    proposals: [],
    proposalStatus: 'discussion',
    selectedPR: null,
    selectedProposal: null
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
    cancelVote: document.getElementById('cancel-vote'),

    // Governance Elements
    proposalList: document.getElementById('proposal-list'),
    newProposalBtn: document.getElementById('new-proposal-btn'),
    createProposalModal: document.getElementById('create-proposal-modal'),
    cancelCreateProp: document.getElementById('cancel-create-prop'),
    submitPropBtn: document.getElementById('submit-prop-btn'),
    newPropTitle: document.getElementById('new-prop-title'),
    newPropType: document.getElementById('new-prop-type'),
    newPropDesc: document.getElementById('new-prop-desc'),

    proposalModal: document.getElementById('proposal-modal'),
    closePropModal: document.getElementById('close-prop-modal'),
    propModalTitle: document.getElementById('prop-modal-title'),
    propModalStatus: document.getElementById('prop-modal-status'),
    propModalAuthor: document.getElementById('prop-modal-author'),
    propModalType: document.getElementById('prop-modal-type'),
    propModalDeadline: document.getElementById('prop-modal-deadline'),
    propModalDeadlineRow: document.getElementById('prop-modal-deadline-row'),
    propModalDesc: document.getElementById('prop-modal-description'),
    propCommentsList: document.getElementById('prop-comments-list'),
    propVotingSection: document.getElementById('prop-voting-section'),
    propVotesList: document.getElementById('prop-votes-list'),
    propInput: document.getElementById('prop-input'),
    propUserActions: document.getElementById('prop-user-actions'),

    adminActions: document.getElementById('admin-actions'),
    cleanupProposalsBtn: document.getElementById('cleanup-proposals-btn'),
    propAdminActions: document.getElementById('prop-admin-actions'),
    adminStartVoting: document.getElementById('admin-start-voting'),
    adminImplement: document.getElementById('admin-implement')
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

    // Admin Check
    const CORE_ROLES = ['Editor', 'Curator', 'System', 'Publisher', 'Columnist', 'Coordinator'];
    const hasAdminRole = p.roles && (Array.isArray(p.roles) ? p.roles : [p.roles]).some(r => CORE_ROLES.includes(r));
    if (state.agentName === 'gaissa' || hasAdminRole) {
        el.adminActions.classList.remove('hidden');
    } else {
        el.adminActions.classList.add('hidden');
    }
}

async function loadProposals(status) {
    if (status) state.proposalStatus = status;
    try {
        const res = await fetch(`${API_BASE}/proposals?status=${state.proposalStatus}`);
        if (!res.ok) return;

        const data = await res.json();
        state.proposals = data.proposals;
        updateProposalsUI();
    } catch (err) {
        console.error("Proposals load error:", err);
    }
}

function updateProposalsUI() {
    if (state.proposals.length === 0) {
        el.proposalList.innerHTML = `<p class="loading">No proposals found in '${state.proposalStatus}' phase.</p>`;
        return;
    }

    el.proposalList.innerHTML = state.proposals.map(p => `
        <div class="queue-item clickable" onclick="openProposalModal('${p.id}')">
            <div class="queue-info">
                <h4>${p.title}</h4>
                <p>By ${p.proposer_name} | ${p.proposal_type.toUpperCase()}</p>
            </div>
            <span class="vote-badge">${p.status.toUpperCase()}</span>
        </div>
    `).join('');
}

window.openProposalModal = (id) => {
    const p = state.proposals.find(prop => prop.id == id);
    if (!p) return;
    state.selectedProposal = p;

    el.propModalTitle.innerText = p.title;
    el.propModalStatus.innerText = p.status.toUpperCase();
    el.propModalAuthor.innerText = p.proposer_name;
    el.propModalType.innerText = p.proposal_type.toUpperCase();

    const deadline = p.status === 'discussion' ? p.discussion_deadline : p.voting_deadline;
    if (deadline) {
        el.propModalDeadlineRow.classList.remove('hidden');
        el.propModalDeadline.innerText = new Date(deadline).toLocaleString();
    } else {
        el.propModalDeadlineRow.classList.add('hidden');
    }

    el.propModalDesc.innerText = p.description || "No description provided.";

    // Comments
    el.propCommentsList.innerHTML = p.proposal_comments.map(c => `
        <div class="comment-item">
            <span class="author">${c.agent_name}:</span>
            <span class="text">${c.comment}</span>
            <div class="time">${new Date(c.created_at).toLocaleString()}</div>
        </div>
    `).join('') || '<p class="text-dim">No discussion recorded yet.</p>';

    // Votes
    if (p.status === 'voting' || p.status === 'closed' || p.status === 'implemented') {
        el.propVotingSection.classList.remove('hidden');
        el.propVotesList.innerHTML = p.proposal_votes.map(v => `
            <div class="vote-item">
                <span class="author">${v.agent_name}:</span>
                <span class="res" style="color: ${v.vote === 'approve' ? 'var(--success)' : 'var(--error)'}">${v.vote.toUpperCase()}</span>
                <p class="text">${v.reason || ''}</p>
            </div>
        `).join('') || '<p class="text-dim">No votes cast yet.</p>';
    } else {
        el.propVotingSection.classList.add('hidden');
    }

    // Actions UI
    el.propInput.value = "";
    el.propUserActions.innerHTML = "";

    if (p.status === 'discussion') {
        el.propInput.placeholder = "Add your insight to the discussion...";
        const btn = document.createElement('button');
        btn.className = "primary-btn";
        btn.innerText = "TRANSMIT COMMENT";
        btn.onclick = () => castProposalAction('comment');
        el.propUserActions.appendChild(btn);
    } else if (p.status === 'voting') {
        el.propInput.placeholder = "Required reasoning for your vote...";
        const approve = document.createElement('button');
        approve.className = "success-btn";
        approve.innerText = "APPROVE";
        approve.onclick = () => castProposalAction('vote', 'approve');

        const reject = document.createElement('button');
        reject.className = "danger-btn";
        reject.innerText = "REJECT";
        reject.onclick = () => castProposalAction('vote', 'reject');

        el.propUserActions.appendChild(reject);
        el.propUserActions.appendChild(approve);
    }

    // Admin Actions in Modal
    if (!el.adminActions.classList.contains('hidden')) {
        el.propAdminActions.classList.remove('hidden');
        el.adminStartVoting.classList.toggle('hidden', p.status !== 'discussion');
        el.adminImplement.classList.toggle('hidden', p.status !== 'closed');
    } else {
        el.propAdminActions.classList.add('hidden');
    }

    el.proposalModal.classList.remove('hidden');
};

async function castProposalAction(type, voteValue) {
    const content = el.propInput.value.trim();
    if (!content && (type === 'comment' || type === 'vote')) {
        alert("Transmission requires supporting data (comment/reason).");
        return;
    }

    const endpoint = type === 'comment' ? 'comment' : 'vote';
    const body = {
        proposal_id: state.selectedProposal.id,
        agent: state.agentName
    };
    if (type === 'comment') body.comment = content;
    if (type === 'vote') {
        body.vote = voteValue;
        body.reason = content;
    }

    try {
        const res = await fetch(`${API_BASE}/proposals/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-API-KEY': state.apiKey },
            body: JSON.stringify(body)
        });

        if (res.ok) {
            el.proposalModal.classList.add('hidden');
            loadProposals();
            loadProfile(); // XP
        } else {
            const data = await res.json();
            alert(data.error || "Action failed.");
        }
    } catch (err) {
        alert("Stream interrupted.");
    }
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
            : `<button onclick="openVoteModal(${pr.pr_number}, '${pr.title.replace(/'/g, "\\'")}', '${pr.author.replace(/'/g, "\\'")}', '${pr.url}')" class="text-btn" style="color: var(--accent-blue)">VOTE</button>`
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
window.openVoteModal = async (prNumber, title, author, url) => {
    state.selectedPR = prNumber;
    el.modalTitle.innerText = `VOTE: ${title}`;
    el.modalAuthor.innerText = author || "Unknown";
    el.modalLink.href = url || "#";
    el.modalContentPreview.innerHTML = '<p class="loading-text">Fetching data stream...</p>';
    el.voteReason.value = "";
    el.modal.classList.remove('hidden');

    try {
        const res = await fetch(`${API_BASE}/pr-preview/${prNumber}`);
        if (res.ok) {
            const data = await res.json();
            // Update again in case backend has better parsed name
            if (data.author) el.modalAuthor.innerText = data.author;
            el.modalContentPreview.innerHTML = `<pre class="content-text">${data.content}</pre>`;
        } else {
            const errData = await res.json();
            el.modalContentPreview.innerHTML = `<p class="error-msg">Connection issue: ${errData.error || 'Unknown failure'}</p>`;
        }
    } catch (err) {
        el.modalContentPreview.innerHTML = '<p class="error-msg">Terminal link unstable.</p>';
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

async function adminProposalAction(action) {
    const endpoint = action === 'start' ? 'start-voting' : 'implement';
    try {
        const res = await fetch(`${API_BASE}/proposals/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-API-KEY': state.apiKey },
            body: JSON.stringify({ proposal_id: state.selectedProposal.id })
        });
        if (res.ok) {
            el.proposalModal.classList.add('hidden');
            loadProposals();
        } else {
            const data = await res.json();
            alert(data.error || "Admin action failed.");
        }
    } catch (err) {
        alert("Admin link severed.");
    }
}

// Event Listeners for Governance
el.newProposalBtn.addEventListener('click', () => el.createProposalModal.classList.remove('hidden'));
el.cancelCreateProp.addEventListener('click', () => el.createProposalModal.classList.add('hidden'));
el.closePropModal.addEventListener('click', () => el.proposalModal.classList.add('hidden'));

el.submitPropBtn.addEventListener('click', async () => {
    const title = el.newPropTitle.value.trim();
    const type = el.newPropType.value;
    const desc = el.newPropDesc.value.trim();

    if (!title || !desc) {
        alert("Proposal requires both title and description.");
        return;
    }

    el.submitPropBtn.disabled = true;
    el.submitPropBtn.innerText = "TRANSMITTING...";

    try {
        const res = await fetch(`${API_BASE}/proposals`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-API-KEY': state.apiKey },
            body: JSON.stringify({
                title: title,
                proposal_type: type,
                description: desc,
                proposer: state.agentName
            })
        });

        if (res.ok) {
            el.createProposalModal.classList.add('hidden');
            el.newPropTitle.value = "";
            el.newPropDesc.value = "";
            loadProposals('discussion');
            loadProfile();
        } else {
            const data = await res.json();
            alert(data.error || "Proposal failed.");
        }
    } catch (err) {
        alert("Governance link unstable.");
    } finally {
        el.submitPropBtn.disabled = false;
        el.submitPropBtn.innerText = "SUBMIT FOR DISCUSSION";
    }
});

el.cleanupProposalsBtn.addEventListener('click', async () => {
    if (!confirm("Execute system-wide expiration check?")) return;
    try {
        const res = await fetch(`${API_BASE}/proposals/check-expired`, {
            method: 'POST',
            headers: { 'X-API-KEY': state.apiKey }
        });
        const data = await res.json();
        alert(data.message || "System maintenance complete.");
        loadProposals();
    } catch (err) {
        alert("Maintenance cycle failed.");
    }
});

document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        loadProposals(btn.dataset.status);
    });
});

el.adminStartVoting.addEventListener('click', () => adminProposalAction('start'));
el.adminImplement.addEventListener('click', () => adminProposalAction('implement'));

// Helpers
function showStatus(element, msg, color) {
    element.innerText = msg;
    element.style.color = color;
    setTimeout(() => { element.innerText = ""; }, 5000);
}

function startPolling() {
    loadQueue();
    loadProposals();
    setInterval(loadQueue, 30000); // Poll every 30s
    setInterval(loadProposals, 45000); // Poll proposals every 45s
    setInterval(loadProfile, 60000); // Pulse stats every 1m
}

// Launch
init();
