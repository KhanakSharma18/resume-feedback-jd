// script.js — FINAL (complete)
// Features: chat store, chat switching, per-chat modes, resumelyzer, file upload previews,
// voice-to-text, notes panel, export to PDF, typing indicator, dark-mode persistence,
// analyze_file upload integration (if back-end present).

// ----------------------
// In-memory store
// ----------------------
const Store = { chats: {}, order: [] };
let activeChatId = null;

// ----------------------
// Helpers
// ----------------------
const $ = id => document.getElementById(id);
const now = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const uid = (p = 'id') => `${p}_${Date.now()}_${Math.floor(Math.random() * 999999)}`;

function escapeHtml(s) {
  return (s || '')
    .toString()
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

// ----------------------
// Chat CRUD & selection
// ----------------------
function createChat(name = 'New chat', mode = 'general') {
  const id = uid('chat');
  Store.chats[id] = {
    id,
    title: name,
    messages: [],
    mode,
    resumelyzer: mode === 'resumelyzer',
    resumeFile: null
  };
  Store.order.unshift(id);
  renderChatList();
  selectChat(id);
  return id;
}

function selectChat(id) {
  if (!Store.chats[id]) return;
  activeChatId = id;
  const chat = Store.chats[id];

  // Header and subtitle
  if ($('headerTitle')) $('headerTitle').textContent = chat.title || 'AI Assistant';
  if ($('chatSub')) {
    $('chatSub').textContent = chat.messages.length
      ? `${chat.messages.length} messages • updated ${chat.messages.at(-1).time}`
      : 'No messages yet';
  }

  // Update UI controls
  if ($('modeSelect')) $('modeSelect').value = chat.mode || 'general';
  if ($('resumelyzerBtn')) $('resumelyzerBtn').classList.toggle('active', !!chat.resumelyzer);

  highlightActiveChat();
  renderMessages();
  updateHeaderModeBadge();
  syncResumePanel();
}

function deleteChat(id) {
  if (!Store.chats[id]) return;
  delete Store.chats[id];
  Store.order = Store.order.filter(x => x !== id);
  if (activeChatId === id) activeChatId = Store.order[0] || null;
  renderChatList();
  if (activeChatId) selectChat(activeChatId);
  else {
    if ($('output')) $('output').innerHTML = '';
    if ($('chatSub')) $('chatSub').textContent = 'No chats';
  }
}

// ----------------------
// Rendering
// ----------------------
function renderChatList() {
  const container = $('chatList');
  if (!container) return;
  container.innerHTML = '';
  for (const id of Store.order) {
    const c = Store.chats[id];
    const item = document.createElement('div');
    item.className = 'chat-item' + (id === activeChatId ? ' active' : '');
    item.dataset.id = id;
    item.innerHTML = `
      <div class="avatar">A</div>
      <div class="meta">
        <div class="title">${escapeHtml(c.title)}</div>
        <div class="sub">${c.messages.length ? escapeHtml(c.messages.at(-1).text.slice(0, 40)) : 'Start the conversation'}</div>
      </div>
    `;
    item.addEventListener('click', () => selectChat(id));
    container.appendChild(item);
  }
}

function highlightActiveChat() {
  document.querySelectorAll('.chat-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === activeChatId);
  });
}

function renderMessages() {
  const out = $('output');
  if (!out) return;
  out.innerHTML = '';
  if (!activeChatId) return;
  const chat = Store.chats[activeChatId];

  for (const m of chat.messages) {
    const row = document.createElement('div');
    row.className = 'chat-message ' + (m.role === 'user' ? 'user' : 'ai');

    const bubble = document.createElement('div');
    bubble.className = 'bubble ' + (m.role === 'user' ? 'user' : 'ai');

    // Allow simple line breaks for preview
    const safeText = escapeHtml(m.text).replaceAll('\n', '<br>');
    bubble.innerHTML = `
      <div>${safeText}</div>
      <div class="meta" style="font-size:0.8rem;margin-top:6px;color:rgba(0,0,0,0.35)">
        ${m.role === 'user' ? 'You' : 'Assistant'} • ${m.time || ''}
      </div>
    `;
    row.appendChild(bubble);
    out.appendChild(row);
  }

  // ensure only the chat messages scroll, not whole page
  out.scrollTop = out.scrollHeight;
}

function updateHeaderModeBadge() {
  const chat = Store.chats[activeChatId];
  if (!chat) return;
  const titleEl = $('headerTitle');
  if (!titleEl) return;

  const existing = titleEl.querySelector('.mode-badge');
  if (existing) existing.remove();

  if (chat.mode && chat.mode !== 'general') {
    const span = document.createElement('span');
    span.className = 'mode-badge';
    span.textContent = chat.mode.toUpperCase();
    span.style.cssText = 'margin-left:8px;font-size:0.75rem;padding:3px 8px;border-radius:999px;background:rgba(0,0,0,0.06);';
    titleEl.appendChild(span);
  }
}

// ----------------------
// Chat send / receive
// ----------------------
async function sendMessage(text) {
  text = (text || '').trim();
  if (!text || !activeChatId) return;
  const chat = Store.chats[activeChatId];

  // push user
  chat.messages.push({ role: 'user', text, time: now() });
  renderMessages();
  if ($('commandInput')) $('commandInput').value = '';
  if ($('chatSub')) $('chatSub').textContent = `${chat.messages.length} messages • updated ${now()}`;
  renderChatList();

  // mode enforcement (soft)
  if (chat.mode !== 'general') {
    const block = modeEnforce(chat.mode, text);
    if (block) {
      chat.messages.push({ role: 'ai', text: block, time: now() });
      return renderMessages();
    }
  }

  // resumelyzer check
  if (chat.resumelyzer && !detectResumeIntent(text) && !chat.resumeFile) {
    chat.messages.push({ role: 'ai', text: 'Resumelyzer: Please upload a resume (PDF) or ask a resume-specific question.', time: now() });
    return renderMessages();
  }

  // show typing placeholder
  chat.messages.push({ role: 'ai', text: 'Typing...', time: '' });
  renderMessages();

  try {
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chatId: activeChatId,
        message: text,
        mode: chat.mode,
        use_pdf: !!chat.pdfReady   // a PDF attached to this chat is used automatically
      })
    });
    if (!resp.ok) throw new Error('Network error');
    const json = await resp.json();
    chat.messages.pop(); // remove typing
    chat.messages.push({ role: 'ai', text: json.reply || 'No reply', time: now() });
    renderMessages();
    renderChatList();
  } catch (err) {
    chat.messages.pop();
    chat.messages.push({ role: 'ai', text: offlineReply(text), time: now() });
    renderMessages();
    renderChatList();
  }
}

function offlineReply(userText) {
  const chat = Store.chats[activeChatId];
  if (chat && chat.resumelyzer && chat.resumeFile) {
    return `Resumelyzer offline demo: Found ${chat.resumeFile.name}. Summary: skills X, experience Y.`;
  }
  return `I heard: "${userText}". (Demo offline reply)`;
}

// ----------------------
// Mode enforcement
// ----------------------
function modeEnforce(mode, text) {
  const t = (text || '').toLowerCase();
  if (mode === 'email' && !/email|subject|dear|regards|sincerely|@/.test(t)) {
    return 'Email Mode: please provide an email-related request (subject, recipient, or message body).';
  }
  if (mode === 'code' && !/code|function|class|error|compile|syntax/.test(t)) {
    return 'Code Mode: please ask coding-related questions or paste code.';
  }
  if (mode === 'study' && (t.length < 6)) {
    return 'Study Mode: provide a topic or text to summarize/ask questions about.';
  }
  if (mode === 'resumelyzer' && !detectResumeIntent(text) && !Store.chats[activeChatId].resumeFile) {
    return 'Resumelyzer: upload a resume (PDF/DOCX) or ask resume-specific questions.';
  }
  return null;
}

// ----------------------
// Resume intent detector
// ----------------------
function detectResumeIntent(text) {
  if (!text) return false;
  const keys = ['resume', 'cv', 'experience', 'skills', 'work', 'education', 'linkedin'];
  const t = text.toLowerCase();
  return keys.some(k => t.includes(k));
}

// ----------------------
// File upload handler (client preview + server analyze fallback)
// ----------------------
$('fileUpload')?.addEventListener('change', async function () {
  const file = this.files[0];
  if (!file) return;

  // ensure chat exists
  if (!activeChatId) createChat('File Chat', 'general');
  const chat = Store.chats[activeChatId];
  chat.resumeFile = file;
  chat.pdfReady = false;
  syncResumePanel();

  // immediate lightweight client-side previews for common types
  if (file.type.includes('pdf')) {
    chat.messages.push({ role: 'ai', text: `PDF attached: ${file.name}. Reading it...`, time: now() });
    renderMessages();
    // /upload_pdf (in app.py) extracts the text and keeps it in the Flask session
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/upload_pdf', { method: 'POST', body: form });
      const json = await res.json();
      if (res.ok) {
        chat.pdfReady = true;
        syncResumePanel();
        chat.messages.push({ role: 'ai', text: `${file.name} is ready. Ask me anything about it (e.g. "analyse my resume").`, time: now() });
      } else {
        chat.messages.push({ role: 'ai', text: `Could not read the PDF: ${json.error || 'unknown error'}`, time: now() });
      }
    } catch (e) {
      chat.messages.push({ role: 'ai', text: `Upload error: ${String(e)}`, time: now() });
    }
  } else if (file.type === 'text/plain') {
    const txt = await file.text();
    chat.messages.push({ role: 'ai', text: `TXT preview (${file.name}):\n${txt.slice(0, 2000)}`, time: now() });
  } else if (file.name.endsWith('.docx')) {
    // use Mammoth client-side to extract text quickly
    try {
      const ab = await file.arrayBuffer();
      const { value } = await mammoth.extractRawText({ arrayBuffer: ab });
      chat.messages.push({ role: 'ai', text: `DOCX preview (${file.name}):\n${value.slice(0, 2000)}`, time: now() });
      // also try server analyze if available
      try {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch('/analyze_file', { method: 'POST', body: form });
        const json = await res.json();
        if (res.ok) {
          if (json.summary) chat.messages.push({ role: 'ai', text: `Server analysis: ${json.summary}`, time: now() });
        }
      } catch (e) { /* ignore server analyze failure */ }
    } catch (e) {
      chat.messages.push({ role: 'ai', text: `DOCX preview error: ${String(e)}`, time: now() });
    }
  } else {
    // generic fallback: say file attached, and attempt server analyze if available
    chat.messages.push({ role: 'ai', text: `File attached: ${file.name}. Sending to server for analysis...`, time: now() });
    renderMessages();
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/analyze_file', { method: 'POST', body: form });
      const json = await res.json();
      if (res.ok) {
        if (json.summary) chat.messages.push({ role: 'ai', text: `Analysis: ${json.summary}`, time: now() });
        if (json.text_preview) chat.messages.push({ role: 'ai', text: `Preview:\n${json.text_preview.slice(0, 2000)}`, time: now() });
      } else {
        chat.messages.push({ role: 'ai', text: `Server analysis failed: ${json.error || 'unknown'}`, time: now() });
      }
    } catch (e) {
      chat.messages.push({ role: 'ai', text: `Upload error: ${String(e)}`, time: now() });
    }
  }

  renderMessages();
  renderChatList();
});

// ----------------------
// Voice-to-text (Web Speech API)
// ----------------------
let recognition;
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  $('micBtn')?.addEventListener('click', () => {
    try {
      recognition.start();
      $('micBtn')?.classList.add('listening');
    } catch (e) {
      // ignore multiple start errors
    }
  });

  recognition.onresult = e => {
    const spoken = e.results[0][0].transcript;
    if ($('commandInput')) $('commandInput').value = spoken;
    $('micBtn')?.classList.remove('listening');
    // don't auto-send by default; user can edit then press Enter
  };
  recognition.onerror = () => $('micBtn')?.classList.remove('listening');
  recognition.onend = () => $('micBtn')?.classList.remove('listening');
}

// ----------------------
// Buttons & UI handlers
// ----------------------

// New chat
$('newChatBtn')?.addEventListener('click', () => {
  const name = prompt('Name this chat (optional)') || 'New chat';
  const mode = (prompt('Mode? (general|resumelyzer|code|study|email)', 'general') || 'general').toLowerCase();
  createChat(name, mode);
});

// Send message
$('sendBtn')?.addEventListener('click', () => sendMessage($('commandInput')?.value || ''));
$('commandInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage($('commandInput')?.value || ''); });

// Chat search
$('chatSearch')?.addEventListener('input', function () {
  const q = (this.value || '').toLowerCase();
  document.querySelectorAll('.chat-item').forEach(item => {
    const title = item.querySelector('.title')?.textContent?.toLowerCase() || '';
    item.style.display = title.includes(q) ? '' : 'none';
  });
});

// Mode select per chat
$('modeSelect')?.addEventListener('change', function () {
  if (!activeChatId) { alert('Select a chat first.'); this.value = 'general'; return; }
  const mode = this.value;
  const chat = Store.chats[activeChatId];
  chat.mode = mode;
  chat.resumelyzer = mode === 'resumelyzer';
  syncResumePanel();
  chat.messages.push({ role: 'ai', text: `Mode set to ${mode}.`, time: now() });
  updateHeaderModeBadge();
  renderMessages();
  renderChatList();
});

// Resumelyzer toggle button
$('resumelyzerBtn')?.addEventListener('click', function () {
  if (!activeChatId) { alert('Create or select a chat first.'); return; }
  const chat = Store.chats[activeChatId];
  chat.resumelyzer = !chat.resumelyzer;
  this.classList.toggle('active', chat.resumelyzer);
  syncResumePanel();
  chat.messages.push({ role: 'ai', text: chat.resumelyzer ? 'Resumelyzer enabled for this chat.' : 'Resumelyzer disabled.', time: now() });
  renderMessages();
  renderChatList();
});

// Export chat to PDF (client-side)
$('exportChatBtn')?.addEventListener('click', async () => {
  if (!activeChatId) return alert('Select a chat first.');
  const chat = Store.chats[activeChatId];
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const margin = 40;
  const maxWidth = doc.internal.pageSize.getWidth() - margin * 2;

  let fullText = `Chat: ${chat.title}\n\n`;
  chat.messages.forEach(m => fullText += `${m.role === 'user' ? 'You' : 'Assistant'} [${m.time}]: ${m.text}\n\n`);

  const lines = doc.splitTextToSize(fullText, maxWidth);
  doc.text(lines, margin, margin);
  const filename = `${chat.title.replaceAll(' ', '_') || 'chat'}_${new Date().toISOString().slice(0, 19).replaceAll(':', '-')}.pdf`;
  doc.save(filename);
});

// Notes panel
const NOTES_KEY = 'chatbot_notes_v1';
function buildNotesPanel() {
  if (document.querySelector('.notes-panel')) return;
  const panel = document.createElement('div');
  panel.className = 'notes-panel';
  panel.style.display = 'none';
  panel.innerHTML = `
    <header style="display:flex;align-items:center;justify-content:space-between">
      <strong>Notes</strong>
      <div>
        <button id="notesSave" class="icon-btn">Save</button>
        <button id="notesClose" class="icon-btn">Close</button>
      </div>
    </header>
    <textarea id="notesArea" placeholder="Type notes..." style="width:100%;height:260px;padding:8px;border-radius:8px;border:none;resize:vertical;"></textarea>
  `;
  document.body.appendChild(panel);
  const saved = localStorage.getItem(NOTES_KEY) || '';
  panel.querySelector('#notesArea').value = saved;
  panel.querySelector('#notesClose').onclick = () => panel.style.display = 'none';
  panel.querySelector('#notesSave').onclick = () => {
    localStorage.setItem(NOTES_KEY, panel.querySelector('#notesArea').value);
    alert('Notes saved locally.');
  };
}
$('notesToggle')?.addEventListener('click', () => {
  buildNotesPanel();
  const panel = document.querySelector('.notes-panel');
  panel.style.display = (panel.style.display === 'flex' || panel.style.display === 'block') ? 'none' : 'flex';
  panel.style.flexDirection = 'column';
});

// ----------------------
// Initialization
// ----------------------
(function init() {
  if (Object.keys(Store.chats).length === 0) {
    createChat('General', 'general');
    Store.chats[activeChatId].messages.push({ role: 'ai', text: 'Hi, how can I assist you?', time: now() });
  }
  renderChatList();
  selectChat(activeChatId);
})();

// ----------------------
// DARK MODE (working)
// ----------------------
const themeBtn = $('themeToggle');

themeBtn?.addEventListener('click', () => {
  document.body.classList.toggle('dark');
  const enabled = document.body.classList.contains('dark');
  localStorage.setItem('theme', enabled ? 'dark' : 'light');
});

// load on startup
(function loadTheme() {
  const saved = localStorage.getItem('theme');
  if (saved === 'dark') document.body.classList.add('dark');
})();

// ----------------------
// RESUMELYZER PANEL (right-hand side): ATS score / weaknesses / improvements
// ----------------------
let rzRun = 0; // guards against out-of-date results when you click quickly

function syncResumePanel() {
  const chat = Store.chats[activeChatId];
  const on = !!(chat && chat.resumelyzer);
  $('resumePanel')?.classList.toggle('open', on);
  document.querySelector('.arc-app')?.classList.toggle('has-panel', on);

  const status = $('resumeStatus');
  const ready = !!(chat && chat.pdfReady);
  if (status) {
    status.textContent = ready
      ? `Resume loaded: ${chat.resumeFile.name}`
      : 'No resume uploaded yet. Use the 📎 button to attach a PDF.';
    status.classList.toggle('ok', ready);
  }
  document.querySelectorAll('.rz-opt').forEach(b => { b.disabled = !ready; });
  syncCurateBtn();
}

async function postResume(payload) {
  const res = await fetch('/resume_analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  let data = {};
  try { data = await res.json(); } catch (_) { data = { error: 'The server sent an unreadable reply. Is app.py updated and restarted?' }; }
  if (!res.ok && !data.error) data.error = 'Request failed.';
  return data;
}

function rzList(items, emptyText) {
  if (!items || !items.length) return `<p class="rz-note">${escapeHtml(emptyText)}</p>`;
  return `<ul class="rz-list">${items.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>`;
}

function renderResumeResult(type, d) {
  const out = $('resumeResult');
  if (type === 'ats') {
    const rows = d.breakdown.map(b => `
      <div class="rz-row">
        <div class="rz-row-top"><span>${escapeHtml(b.name)}</span><span>${b.score}/${b.max}</span></div>
        <div class="rz-bar"><i class="${b.score === b.max ? 'full' : ''}" style="width:${Math.round(100 * b.score / b.max)}%"></i></div>
        <div class="rz-note">${escapeHtml(b.note)}</div>
      </div>`).join('');
    let job = '';
    if (d.job_match) {
      const j = d.job_match;
      const chips = (arr, cls) => arr.map(w => `<span class="rz-chip ${cls}">${escapeHtml(w)}</span>`).join('');
      job = `
        <div class="rz-section">
          <h4>Job match: ${j.percent}%</h4>
          <div class="rz-row">
            <div class="rz-row-top"><span>Wording similarity (TF-IDF cosine)</span><span>${j.similarity}%</span></div>
            <div class="rz-bar"><i style="width:${j.similarity}%"></i></div>
          </div>
          ${j.semantic != null ? `
          <div class="rz-row">
            <div class="rz-row-top"><span>Meaning similarity (sentence embeddings)</span><span>${j.semantic}%</span></div>
            <div class="rz-bar"><i style="width:${j.semantic}%"></i></div>
          </div>` : `<p class="rz-note">Meaning similarity is off. Run <code>pip install sentence-transformers</code> and restart to turn it on.</p>`}
          <div class="rz-row">
            <div class="rz-row-top"><span>Skills and keyword coverage</span><span>${j.coverage}%</span></div>
            <div class="rz-bar"><i style="width:${j.coverage}%"></i></div>
          </div>
          <p class="rz-note">Found in your resume:</p><div>${chips(j.matched, 'ok')}</div>
          ${j.missing.length ? `<p class="rz-note">Job keywords missing:</p><div>${chips(j.missing, '')}</div>` : ''}
          ${j.skills && j.skills.unknown_in_job && j.skills.unknown_in_job.length ? `<p class="rz-note">Also named in the job post (not in the skills database, check them yourself):</p><div>${chips(j.skills.unknown_in_job, '')}</div>` : ''}
          ${j.uncovered && j.uncovered.length ? `<p class="rz-note">Job requirements your resume does not cover yet:</p>${rzList(j.uncovered, '')}` : ''}
          ${j.evidence && j.evidence.length ? `<p class="rz-note">Where your resume backs up the job (closest in meaning):</p>
            <ul class="rz-list">${j.evidence.map(e => `<li><b>${escapeHtml(e.requirement)}</b><br><span class="rz-note">${escapeHtml(e.resume_line)} (${Math.round(e.score * 100)}% similar)</span></li>`).join('')}</ul>` : ''}
        </div>`;
    }
    let skillsBox = '';
    if (d.skills && d.skills.total) {
      const cats = Object.entries(d.skills.by_category).map(([cat, names]) =>
        `<p class="rz-note">${escapeHtml(cat)}:</p><div>${names.map(n => `<span class="rz-chip ok">${escapeHtml(n)}</span>`).join('')}</div>`).join('');
      skillsBox = `<div class="rz-section"><h4>Skills detected (${d.skills.total})</h4>${cats}</div>`;
    }
    out.innerHTML = `
      <div class="rz-score-wrap">
        <div class="rz-score" style="--p:${d.score}"><span>${d.score}</span></div>
        <div><div class="rz-score-label">${escapeHtml(d.label)}</div>
        <div class="rz-score-sub">ATS score out of 100${d.job_match ? ' (60% resume rules + 40% job match)' : ''}</div></div>
      </div>
      ${job}
      ${skillsBox}
      <div class="rz-section">${rows}</div>
      <div class="rz-disclaimer">This is an estimate from common ATS rules. Real ATS software can score differently.</div>`;
  } else if (type === 'weaknesses') {
    out.innerHTML = `
      <div class="rz-section"><h4>Weaknesses found</h4>${rzList(d.weaknesses, 'No major weaknesses found by the quick checks.')}</div>`;
  } else {
    out.innerHTML = `
      <div class="rz-section"><h4>What to improve</h4>${rzList(d.improvements, 'Nothing urgent. Your resume passes the quick checks.')}</div>`;
  }
}

async function runResumeAnalysis(type) {
  const run = ++rzRun;
  const out = $('resumeResult');
  document.querySelectorAll('.rz-opt').forEach(b => b.classList.toggle('active', b.dataset.type === type));
  out.innerHTML = '<div class="rz-loading">Checking your resume...</div>';

  const jd = ($('jobDesc')?.value || '').trim();
  try {
    const data = await postResume({ type, job_description: jd });
    if (run !== rzRun) return;
    if (data.error) { out.innerHTML = `<div class="rz-error">${escapeHtml(data.error)}</div>`; return; }
    renderResumeResult(type, data);

    // Weaknesses / improvements also get a written review from the Llama model
    if (type !== 'ats') {
      const box = document.createElement('div');
      box.className = 'rz-ai';
      box.innerHTML = '<h4>AI review</h4><div class="rz-loading">Asking the model. This can take a minute...</div>';
      out.appendChild(box);
      const ai = await postResume({ type, job_description: jd, ai: true });
      if (run !== rzRun) return;
      box.innerHTML = ai.ai_text
        ? `<h4>AI review</h4><div class="rz-ai-text">${escapeHtml(ai.ai_text)}</div>`
        : '<h4>AI review</h4><div class="rz-note">The model could not be reached (check your Colab link). The checks above still apply.</div>';
    }
  } catch (e) {
    if (run === rzRun) out.innerHTML = `<div class="rz-error">Something went wrong: ${escapeHtml(String(e))}</div>`;
  }
}

// ---- Curate resume for a job: tailor on the server, build the PDF here, download it ----
let lastCurated = null; // { doc, filename }

function syncCurateBtn() {
  const btn = $('curateBtn');
  if (!btn) return;
  const jd = ($('jobDesc')?.value || '').trim();
  const chat = Store.chats[activeChatId];
  btn.hidden = jd.length < 15;           // shows up as soon as a job description is typed
  btn.disabled = !(chat && chat.pdfReady);
  const ib = $('interviewBtn');
  if (ib) { ib.hidden = btn.hidden; ib.disabled = btn.disabled; }
}
$('jobDesc')?.addEventListener('input', syncCurateBtn);

function pdfFileName(name) {
  const base = (name || 'Resume').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'Resume';
  return `${base}_Tailored_Resume.pdf`;
}

function buildCuratedPdf(c) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight();
  const M = 40, maxW = W - 2 * M;
  let y = M + 16;

  const font = (style, size, color) => {
    doc.setFont('helvetica', style); doc.setFontSize(size); doc.setTextColor(...(color || [30, 30, 30]));
  };
  const need = h => { if (y + h > H - M) { doc.addPage(); y = M + 10; } };
  // word wrap that allows a shorter first line (used when something sits beside it)
  const wrap = (txt, w, firstW) => {
    const words = String(txt || '').split(/\s+/).filter(Boolean);
    const lines = []; let cur = '', limit = firstW || w;
    for (const wd of words) {
      const t = cur ? cur + ' ' + wd : wd;
      if (cur && doc.getTextWidth(t) > limit) { lines.push(cur); cur = wd; limit = w; } else cur = t;
    }
    if (cur) lines.push(cur);
    return lines.length ? lines : [''];
  };
  const bulletDot = () => { doc.setFillColor(70, 70, 70); doc.circle(M + 4, y - 3.2, 1.3, 'F'); };

  // header
  font('bold', 20); doc.text(c.header.name || 'Resume', M, y); y += 14;
  font('normal', 9.5, [90, 90, 90]);
  for (const line of c.header.contact) { need(12); doc.text(line, M, y); y += 12; }

  for (const sec of c.sections) {
    y += 8; need(40);
    font('bold', 11, [20, 20, 20]); doc.text(sec.title.toUpperCase(), M, y);
    doc.setDrawColor(150); doc.setLineWidth(0.6); doc.line(M, y + 4, W - M, y + 4);
    y += 17;

    for (const it of sec.items) {
      if (it.type === 'para') {
        font('normal', 10);
        for (const l of wrap(it.text, maxW)) { need(13); doc.text(l, M, y); y += 13; }
        y += 2;
      } else if (it.type === 'kv') {
        const lab = it.label ? it.label + ': ' : '';
        font('bold', 10); const lw = doc.getTextWidth(lab);
        font('normal', 10);
        const lines = wrap(it.text, maxW, maxW - lw);
        need(13);
        font('bold', 10); doc.text(lab, M, y);
        font('normal', 10); doc.text(lines[0], M + lw, y); y += 13;
        for (const l of lines.slice(1)) { need(13); doc.text(l, M, y); y += 13; }
        y += 1;
      } else if (it.type === 'block') {
        font('bold', 10.5);
        const dateW = it.date ? (font('normal', 9.5), doc.getTextWidth(it.date) + 12) : 0;
        font('bold', 10.5);
        const tl = wrap(it.title, maxW - dateW);
        need(14);
        doc.text(tl[0], M, y);
        if (it.date) { font('normal', 9.5, [90, 90, 90]); doc.text(it.date, W - M, y, { align: 'right' }); }
        y += 13.5;
        font('bold', 10.5);
        for (const l of tl.slice(1)) { need(13); doc.text(l, M, y); y += 13.5; }
        font('normal', 10);
        for (const bl of it.bullets) {
          const lines = wrap(bl, maxW - 14);
          need(13); bulletDot();
          for (const l of lines) { need(13); doc.text(l, M + 14, y); y += 13; }
          y += 1.5;
        }
        if (it.tools) {
          font('italic', 9.5, [80, 80, 80]);
          for (const l of wrap('Tools: ' + it.tools, maxW - 14)) { need(12); doc.text(l, M + 14, y); y += 12; }
        }
        y += 5;
      } else { // 'line'
        font('normal', 10);
        const indent = it.bullet ? 14 : 0;
        const rw = it.right ? doc.getTextWidth(it.right) + 12 : 0;
        const lines = wrap(it.text, maxW - indent, maxW - indent - rw);
        need(13);
        if (it.bullet) bulletDot();
        doc.text(lines[0], M + indent, y);
        if (it.right) doc.text(it.right, W - M, y, { align: 'right' });
        y += 13;
        for (const l of lines.slice(1)) { need(13); doc.text(l, M + indent, y); y += 13; }
      }
    }
  }
  return doc;
}

async function runCurate() {
  const run = ++rzRun;
  const out = $('resumeResult');
  document.querySelectorAll('.rz-opt').forEach(b => b.classList.remove('active'));
  out.innerHTML = '<div class="rz-loading">Tailoring your resume to this job...</div>';
  const jd = ($('jobDesc')?.value || '').trim();
  try {
    const data = await postResume2('/resume_curate', { job_description: jd });
    if (run !== rzRun) return;
    if (data.error) { out.innerHTML = `<div class="rz-error">${escapeHtml(data.error)}</div>`; return; }
    if (!window.jspdf) {
      out.innerHTML = '<div class="rz-error">The PDF library did not load. Check your internet connection and refresh the page.</div>';
      return;
    }
    const doc = buildCuratedPdf(data.curated);
    const filename = pdfFileName(data.curated.header.name);
    lastCurated = { doc, filename };
    doc.save(filename);                                   // downloads right away

    const b = data.before, a = data.after;
    const m = v => (v == null ? '' : `<small>job match ${v}%</small>`);
    out.innerHTML = `
      <div class="rz-section">
        <h4>Your tailored resume is ready</h4>
        <p class="rz-note">It should have downloaded as <b>${escapeHtml(filename)}</b>. If it did not, use the button.</p>
        <button id="downloadCuratedBtn" class="rz-curate" type="button">Download PDF</button>
      </div>
      <div class="rz-ba">
        <div><span>Before</span><b>${b.score}</b>${m(b.match)}</div>
        <div class="rz-arrow">&rarr;</div>
        <div><span>After</span><b>${a.score}</b>${m(a.match)}</div>
      </div>
      <div class="rz-section"><h4>What changed</h4>${rzList(data.notes, 'No changes were needed.')}</div>
      <div class="rz-disclaimer">This only reorders and emphasises what is already in your resume. Read the PDF before you send it.</div>`;
    $('downloadCuratedBtn')?.addEventListener('click', () => lastCurated && lastCurated.doc.save(lastCurated.filename));
  } catch (e) {
    if (run === rzRun) out.innerHTML = `<div class="rz-error">Something went wrong: ${escapeHtml(String(e))}</div>`;
  }
}
$('curateBtn')?.addEventListener('click', runCurate);

async function postResume2(url, payload) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  let data = {};
  try { data = await res.json(); } catch (_) { data = { error: 'The server sent an unreadable reply. Did you replace app.py and restart it?' }; }
  if (!res.ok && !data.error) data.error = 'Request failed.';
  return data;
}

// ---- Interview quiz (popup): answer by typing or speaking, get checked, see the model answer, get a score ----
const Quiz = { all: [], list: [], i: 0, results: [], screen: 'start', count: 10, projects: [], draft: '', lastResult: null, active: false };
let qzRecog = null, qzListening = false, qzCommitted = '';

const QZ_LABELS = {
  technical: { correct: 'Correct', partial: 'Partly correct', incorrect: 'Not quite' },
  open:      { correct: 'Strong answer', partial: 'Decent, but missing parts', incorrect: 'Needs more work' }
};
const qzIcon = v => (v === 'correct' ? '✓' : v === 'partial' ? '½' : '✗');
const qzLabel = (q, v) => (QZ_LABELS[q.kind === 'technical' ? 'technical' : 'open'][v]);

function qzOpen() { $('quizModal').hidden = false; document.body.classList.add('qz-open'); Quiz.active = true; qzRender(); }
function qzClose() { qzStopListening(); $('quizModal').hidden = true; document.body.classList.remove('qz-open'); Quiz.active = false; renderQuizPanelNote(); }
$('quizClose')?.addEventListener('click', qzClose);
$('quizModal')?.addEventListener('mousedown', e => { if (e.target === $('quizModal')) qzClose(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && Quiz.active) qzClose(); });

// ---------- speech to text (Chrome / Edge) ----------
function qzSpeechSupported() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition); }

function qzStopListening() {
  qzListening = false;
  try { qzRecog && qzRecog.stop(); } catch (_) {}
  qzSyncMic();
}

function qzSyncMic(msg) {
  const btn = $('qzMic'), st = $('qzMicStatus');
  if (btn) { btn.classList.toggle('on', qzListening); btn.textContent = qzListening ? '⏹ Stop' : '🎤 Speak'; }
  if (st) st.textContent = msg != null ? msg : (qzListening ? 'Listening... speak your answer' : '');
}

function qzToggleMic() {
  const ta = $('qzAnswer');
  if (!ta) return;
  if (qzListening) { qzStopListening(); return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { qzSyncMic('Speech input needs Chrome or Edge. You can still type.'); return; }
  qzRecog = new SR();
  qzRecog.lang = navigator.language || 'en-US';
  qzRecog.continuous = true;
  qzRecog.interimResults = true;
  qzCommitted = ta.value && !/\s$/.test(ta.value) ? ta.value + ' ' : ta.value;
  qzRecog.onresult = ev => {
    let interim = '';
    for (let k = ev.resultIndex; k < ev.results.length; k++) {
      const r = ev.results[k];
      if (r.isFinal) qzCommitted += r[0].transcript.trim() + ' '; else interim += r[0].transcript;
    }
    ta.value = (qzCommitted + interim).replace(/^\s+/, '');
    Quiz.draft = ta.value;
  };
  qzRecog.onerror = ev => {
    const m = { 'not-allowed': 'Microphone is blocked. Allow it in the browser address bar, then try again.',
                'service-not-allowed': 'Microphone is blocked. Allow it in the browser address bar, then try again.',
                'no-speech': 'I did not hear anything. Try again.', 'audio-capture': 'No microphone found.',
                'network': 'Speech service needs an internet connection.' };
    qzListening = false;
    qzSyncMic(m[ev.error] || 'Speech input stopped (' + ev.error + ').');
  };
  qzRecog.onend = () => { if (qzListening) { qzListening = false; qzSyncMic(''); } };
  try { qzRecog.start(); qzListening = true; qzSyncMic(); } catch (e) { qzSyncMic('Could not start the microphone.'); }
}

// ---------- screens ----------
function qzRender() {
  const body = $('quizBody');
  if (!body) return;
  qzStopListening();
  if (Quiz.screen === 'start') return qzStartScreen(body);
  if (Quiz.screen === 'question') return qzQuestionScreen(body);
  if (Quiz.screen === 'feedback') return qzFeedbackScreen(body);
  return qzResultsScreen(body);
}

function qzStartScreen(body) {
  const max = Quiz.all.length;
  const opts = [5, 10, 15].filter(n => n <= max);
  if (!opts.length || opts[opts.length - 1] < max) opts.push(max);
  if (Quiz.count > max) Quiz.count = max;
  body.innerHTML = `
    <p class="qz-lead">${max} questions are ready${Quiz.projects.length ? ', built from <b>' + Quiz.projects.map(escapeHtml).join(', ') + '</b> and the job post' : ' from the job post'}.</p>
    <ul class="qz-points">
      <li>Type your answer, or press <b>🎤 Speak</b> and say it${qzSpeechSupported() ? '' : ' (speech input needs Chrome or Edge)'}.</li>
      <li>You get instant feedback, and can open the correct answer any time.</li>
      <li>Your score is shown at the end.</li>
    </ul>
    <p class="qz-sub">How many questions?</p>
    <div class="qz-counts">${opts.map(n => `<button type="button" class="qz-chip ${n === Quiz.count ? 'on' : ''}" data-n="${n}">${n}</button>`).join('')}</div>
    <div class="qz-actions"><span class="qz-spacer"></span><button id="qzStart" class="qz-primary" type="button">Start quiz</button></div>`;
  body.querySelectorAll('.qz-chip').forEach(b => b.addEventListener('click', () => { Quiz.count = +b.dataset.n; qzStartScreen(body); }));
  $('qzStart').addEventListener('click', () => {
    Quiz.list = Quiz.all.slice(0, Quiz.count);
    Quiz.i = 0; Quiz.results = []; Quiz.draft = ''; Quiz.lastResult = null;
    Quiz.screen = 'question';
    qzRender();
  });
}

function qzQuestionScreen(body) {
  const q = Quiz.list[Quiz.i], total = Quiz.list.length;
  body.innerHTML = `
    <div class="qz-top"><span class="qz-cat">${escapeHtml(q.category)}</span><span class="qz-count">Question ${Quiz.i + 1} of ${total}</span></div>
    <div class="qz-progress"><i style="width:${Math.round(100 * Quiz.i / total)}%"></i></div>
    <h3 class="qz-q">${escapeHtml(q.question)}</h3>
    <details class="qz-hint"><summary>How to answer</summary><p>${escapeHtml(q.tip)}</p></details>
    <textarea id="qzAnswer" rows="6" placeholder="Type your answer here, or press Speak and say it..."></textarea>
    <div class="qz-actions">
      <button id="qzMic" class="qz-mic" type="button" ${qzSpeechSupported() ? '' : 'title="Speech input needs Chrome or Edge"'}>🎤 Speak</button>
      <span id="qzMicStatus" class="qz-mic-status"></span>
      <span class="qz-spacer"></span>
      <button id="qzSkip" class="qz-ghost" type="button">Skip</button>
      <button id="qzCheck" class="qz-primary" type="button">Check answer</button>
    </div>
    <div id="qzErr" class="rz-error" hidden></div>`;
  const ta = $('qzAnswer');
  ta.value = Quiz.draft || '';
  ta.addEventListener('input', () => { Quiz.draft = ta.value; });
  ta.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') $('qzCheck').click(); });
  ta.focus();
  if (!qzSpeechSupported()) { $('qzMic').disabled = true; qzSyncMic('Speech input needs Chrome or Edge. You can still type.'); }
  $('qzMic').addEventListener('click', qzToggleMic);
  $('qzSkip').addEventListener('click', () => {
    qzFinishQuestion({ verdict: 'incorrect', score: 0, good: [], improve: ['You skipped this question. Read the correct answer below.'],
                       model_answer: q.ref || '', skipped: true, note: '' }, '');
  });
  $('qzCheck').addEventListener('click', async () => {
    const answer = ta.value.trim();
    if (!answer) { const e = $('qzErr'); e.hidden = false; e.textContent = 'Write or speak an answer first, or press Skip.'; return; }
    qzStopListening();
    const btn = $('qzCheck'); btn.disabled = true; btn.textContent = 'Checking...';
    const res = await postResume2('/quiz_check', { question: q, answer });
    if (res.error) {
      btn.disabled = false; btn.textContent = 'Check answer';
      const e = $('qzErr'); e.hidden = false; e.textContent = res.error; return;
    }
    qzFinishQuestion(res, answer);
  });
}

function qzFinishQuestion(res, answer) {
  Quiz.results[Quiz.i] = { ...res, answer };
  Quiz.lastResult = Quiz.results[Quiz.i];
  Quiz.screen = 'feedback';
  qzRender();
}

function qzList(items) { return `<ul class="qz-ul">${items.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>`; }

function qzFeedbackScreen(body) {
  const q = Quiz.list[Quiz.i], r = Quiz.results[Quiz.i], total = Quiz.list.length, last = Quiz.i === total - 1;
  const isTech = q.kind === 'technical';
  body.innerHTML = `
    <div class="qz-top"><span class="qz-cat">${escapeHtml(q.category)}</span><span class="qz-count">Question ${Quiz.i + 1} of ${total}</span></div>
    <div class="qz-progress"><i style="width:${Math.round(100 * (Quiz.i + 1) / total)}%"></i></div>
    <p class="qz-q-small">${escapeHtml(q.question)}</p>
    <div class="qz-verdict v-${r.verdict}"><span class="qz-vicon">${qzIcon(r.verdict)}</span>
      <span>${r.skipped ? 'Skipped' : escapeHtml(qzLabel(q, r.verdict))}</span><span class="qz-vscore">${r.skipped ? '' : r.score + '%'}</span></div>
    ${r.good && r.good.length ? `<div class="qz-block"><h4>What you did well</h4>${qzList(r.good)}</div>` : ''}
    ${r.improve && r.improve.length ? `<div class="qz-block"><h4>What to improve</h4>${qzList(r.improve)}</div>` : ''}
    ${r.answer ? `<details class="qz-hint"><summary>Your answer</summary><p class="qz-pre">${escapeHtml(r.answer)}</p></details>` : ''}
    <div id="qzModel" class="qz-block qz-model" ${r.skipped ? '' : 'hidden'}><h4>${isTech ? 'Correct answer' : 'Suggested answer structure'}</h4><p class="qz-pre">${escapeHtml(r.model_answer || 'No model answer available.')}</p></div>
    <div id="qzAiOut" class="rz-ai" hidden></div>
    ${r.note ? `<p class="qz-note">${escapeHtml(r.note)}</p>` : ''}
    <div class="qz-actions">
      ${r.skipped ? '' : `<button id="qzShow" class="qz-ghost" type="button">Show correct answer</button>`}
      ${r.skipped || !r.answer ? '' : `<button id="qzAi" class="qz-ghost" type="button">Get AI feedback</button>`}
      <span class="qz-spacer"></span>
      <button id="qzNext" class="qz-primary" type="button">${last ? 'See my score' : 'Next question'}</button>
    </div>`;
  $('qzShow')?.addEventListener('click', function () {
    const m = $('qzModel'); m.hidden = !m.hidden;
    this.textContent = m.hidden ? 'Show correct answer' : 'Hide correct answer';
  });
  $('qzAi')?.addEventListener('click', async function () {
    const out = $('qzAiOut'); out.hidden = false;
    out.innerHTML = '<h4>AI feedback</h4><div class="rz-loading">Asking the model. This can take a minute...</div>';
    this.disabled = true;
    const res = await postResume2('/quiz_ai_feedback', { question: q, answer: r.answer });
    this.disabled = false;
    out.innerHTML = res.text ? `<h4>AI feedback</h4><div class="rz-ai-text">${escapeHtml(res.text)}</div>`
      : '<h4>AI feedback</h4><div class="rz-note">The model could not be reached (check your Colab link). The check above still applies.</div>';
  });
  $('qzNext').addEventListener('click', () => {
    Quiz.draft = '';
    if (last) Quiz.screen = 'results'; else { Quiz.i++; Quiz.screen = 'question'; }
    qzRender();
  });
}

function qzResultsScreen(body) {
  const rs = Quiz.results, n = Quiz.list.length;
  const c = rs.filter(r => r && r.verdict === 'correct').length;
  const p = rs.filter(r => r && r.verdict === 'partial').length;
  const w = n - c - p;
  const pct = Math.round(100 * (c + 0.5 * p) / n);
  const msg = pct >= 80 ? 'Excellent. You are interview-ready on these.' : pct >= 55 ? 'Good start. Review the missed ones and try again.' : 'Keep practising. Read the correct answers, then retry.';
  const rows = Quiz.list.map((q, k) => {
    const r = rs[k] || { verdict: 'incorrect', score: 0, answer: '', model_answer: q.ref };
    return `<details class="qz-row v-${r.verdict}"><summary><span class="qz-vicon">${qzIcon(r.verdict)}</span><span class="qz-row-q">${escapeHtml(q.question)}</span><span class="qz-row-s">${r.skipped ? 'skipped' : r.score + '%'}</span></summary>
      ${r.answer ? `<p class="qz-note">Your answer</p><p class="qz-pre">${escapeHtml(r.answer)}</p>` : ''}
      <p class="qz-note">${q.kind === 'technical' ? 'Correct answer' : 'Suggested answer structure'}</p><p class="qz-pre">${escapeHtml(r.model_answer || '')}</p></details>`;
  }).join('');
  const cats = {};
  Quiz.list.forEach((q, k) => { const r = rs[k]; (cats[q.category] = cats[q.category] || { t: 0, s: 0 }); cats[q.category].t++; cats[q.category].s += r ? (r.verdict === 'correct' ? 1 : r.verdict === 'partial' ? 0.5 : 0) : 0; });
  body.innerHTML = `
    <div class="qz-score"><div class="qz-big">${c}<small> / ${n}</small></div><div class="qz-big-sub">questions answered right</div></div>
    <p class="qz-lead qz-center">${escapeHtml(msg)}</p>
    <div class="qz-tally"><span class="v-correct">✓ ${c} correct</span><span class="v-partial">½ ${p} partly</span><span class="v-incorrect">✗ ${w} missed</span><span class="qz-pct">${pct}% overall</span></div>
    <div class="qz-cats">${Object.entries(cats).map(([k, v]) => `<div class="rz-row"><div class="rz-row-top"><span>${escapeHtml(k)}</span><span>${v.s} / ${v.t}</span></div><div class="rz-bar"><i style="width:${Math.round(100 * v.s / v.t)}%"></i></div></div>`).join('')}</div>
    <p class="qz-sub">Review your answers (tap a question)</p>
    <div class="qz-rows">${rows}</div>
    <div class="qz-actions"><button id="qzRetry" class="qz-ghost" type="button">Try again</button><span class="qz-spacer"></span><button id="qzDone" class="qz-primary" type="button">Close</button></div>`;
  $('qzRetry').addEventListener('click', () => { Quiz.screen = 'start'; qzRender(); });
  $('qzDone').addEventListener('click', qzClose);
}

// ---------- panel note + entry point ----------
function renderQuizPanelNote() {
  const out = $('resumeResult');
  if (!out || !Quiz.all.length) return;
  const done = Quiz.screen === 'results';
  const c = Quiz.results.filter(r => r && r.verdict === 'correct').length;
  out.innerHTML = `
    <div class="rz-section"><h4>Interview quiz</h4>
      <p class="rz-note">${done ? `Last score: ${c} / ${Quiz.list.length} right.` : Quiz.screen === 'start' ? `${Quiz.all.length} questions are ready.` : `In progress: question ${Quiz.i + 1} of ${Quiz.list.length}.`}</p>
      <button id="quizReopen" class="rz-copy" type="button">${done ? 'Review or retry' : 'Open quiz'}</button></div>`;
  $('quizReopen')?.addEventListener('click', qzOpen);
}

async function runInterview() {
  const run = ++rzRun;
  const out = $('resumeResult');
  document.querySelectorAll('.rz-opt').forEach(b => b.classList.remove('active'));
  out.innerHTML = '<div class="rz-loading">Preparing your interview quiz from your projects and this job...</div>';
  const jd = ($('jobDesc')?.value || '').trim();
  try {
    const data = await postResume2('/interview_questions', { job_description: jd });
    if (run !== rzRun) return;
    if (data.error) { out.innerHTML = `<div class="rz-error">${escapeHtml(data.error)}</div>`; return; }
    if (!data.questions.length) { out.innerHTML = '<div class="rz-error">Could not build questions from this resume and job post.</div>'; return; }
    Quiz.all = data.questions; Quiz.projects = data.projects || [];
    Quiz.screen = 'start'; Quiz.i = 0; Quiz.results = []; Quiz.draft = ''; Quiz.count = Math.min(10, Quiz.all.length);
    renderQuizPanelNote();
    qzOpen();
  } catch (e) {
    if (run === rzRun) out.innerHTML = `<div class="rz-error">Something went wrong: ${escapeHtml(String(e))}</div>`;
  }
}
$('interviewBtn')?.addEventListener('click', runInterview);

document.querySelectorAll('.rz-opt').forEach(btn => btn.addEventListener('click', () => runResumeAnalysis(btn.dataset.type)));
$('rzClose')?.addEventListener('click', () => {
  // closing the panel just hides it; click the Resumelyzer button again to turn the mode off
  $('resumePanel')?.classList.remove('open');
  document.querySelector('.arc-app')?.classList.remove('has-panel');
});

// ----------------------
// expose store for debugging
// ----------------------
window.__chatStore = Store;
