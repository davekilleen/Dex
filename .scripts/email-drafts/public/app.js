'use strict';

// ──────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────
const STATUS_LABELS = {
  queued:       'Queued',
  needs_email:  'Needs Email',
  pushed_draft: 'Drafted',
  sent:         'Sent',
  failed:       'Failed',
};

// ──────────────────────────────────────────────────────────────────
// State
// ──────────────────────────────────────────────────────────────────
let allDrafts  = [];
let selectedId = null;

// ──────────────────────────────────────────────────────────────────
// DOM refs
// ──────────────────────────────────────────────────────────────────
const draftListEl      = document.getElementById('draftList');
const emptyStateEl     = document.getElementById('emptyState');
const countsEl         = document.getElementById('counts');
const sidebarCountEl   = document.getElementById('sidebarCount');
const editorContent    = document.getElementById('editorContent');
const editorPlaceholder = document.getElementById('editorPlaceholder');

// Editor field refs
const edContactName  = document.getElementById('edContactName');
const edCompany      = document.getElementById('edCompany');
const edStatusBadge  = document.getElementById('edStatusBadge');
const edTo           = document.getElementById('edTo');
const edCc           = document.getElementById('edCc');
const edSubject      = document.getElementById('edSubject');
const edBody         = document.getElementById('edBody');
const edSendMode     = document.getElementById('edSendMode');
const edSaveBtn      = document.getElementById('edSaveBtn');
const edPushBtn      = document.getElementById('edPushBtn');
const edRemoveBtn    = document.getElementById('edRemoveBtn');
const sfBar          = document.getElementById('sfBar');
const sfDetail       = document.getElementById('sfDetail');
const sfLookupBtn    = document.getElementById('sfLookupBtn');
const rewritePrompt  = document.getElementById('rewritePrompt');
const rewriteBtn     = document.getElementById('rewriteBtn');
const rewriteStatus  = document.getElementById('rewriteStatus');

// ──────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function selectedDraft() {
  return allDrafts.find((d) => d.id === selectedId) || null;
}

// ──────────────────────────────────────────────────────────────────
// Render sidebar list
// ──────────────────────────────────────────────────────────────────
function renderSidebar() {
  sidebarCountEl.textContent = allDrafts.length;
  emptyStateEl.hidden = allDrafts.length > 0;

  draftListEl.innerHTML = allDrafts.map((d) => `
    <li class="draft-row${d.id === selectedId ? ' active' : ''}" data-id="${esc(d.id)}">
      <div class="draft-row-top">
        <span class="draft-row-name">${esc(d.contactName || '(no name)')}</span>
        <span class="badge status-badge status-${d.status}">${STATUS_LABELS[d.status] || d.status}</span>
      </div>
      <div class="draft-row-company">${esc(d.company || '')}</div>
      <div class="draft-row-subject">${esc(d.subject || '')}</div>
    </li>
  `).join('');
}

// ──────────────────────────────────────────────────────────────────
// Render topbar counts
// ──────────────────────────────────────────────────────────────────
function renderCounts() {
  const counts = {};
  for (const d of allDrafts) counts[d.status] = (counts[d.status] || 0) + 1;
  countsEl.innerHTML = Object.entries(counts)
    .map(([s, n]) => `<span class="count-badge">${STATUS_LABELS[s] || s}: ${n}</span>`)
    .join('') || `<span class="count-badge">No drafts</span>`;
}

// ──────────────────────────────────────────────────────────────────
// Load draft into right-panel editor
// ──────────────────────────────────────────────────────────────────
function loadEditor(draft) {
  if (!draft) {
    editorContent.hidden = true;
    editorPlaceholder.style.display = '';
    return;
  }

  editorPlaceholder.style.display = 'none';
  editorContent.hidden = false;

  // Header
  edContactName.textContent = draft.contactName || '(no name)';
  edCompany.textContent = draft.company || '';
  edStatusBadge.textContent = STATUS_LABELS[draft.status] || draft.status;
  edStatusBadge.className = `badge status-badge status-${draft.status}`;

  // Fields
  edTo.value      = draft.to || '';
  edTo.className  = draft.to ? '' : 'input-missing';
  edCc.value      = draft.cc || '';
  edSubject.value = draft.subject || '';
  edBody.value    = draft.body || '';
  edSendMode.checked = draft.sendMode === 'send';
  updatePushBtn();

  // Reset SF bar & rewrite state
  sfDetail.innerHTML = '<em>Not loaded &mdash; click Look up in SF</em>';
  rewritePrompt.value = '';
  rewriteStatus.hidden = true;
  rewriteStatus.textContent = '';
}

function updatePushBtn() {
  if (edSendMode.checked) {
    edPushBtn.textContent = 'Send Now';
    edPushBtn.className = 'btn btn-send';
  } else {
    edPushBtn.textContent = 'Push as Draft';
    edPushBtn.className = 'btn btn-push';
  }
}

edSendMode.addEventListener('change', updatePushBtn);

// ──────────────────────────────────────────────────────────────────
// Full render (sidebar + counts)
// ──────────────────────────────────────────────────────────────────
function render(drafts) {
  allDrafts = drafts;
  renderSidebar();
  renderCounts();
  // If selection was removed, clear editor
  if (selectedId && !selectedDraft()) {
    selectedId = null;
    loadEditor(null);
  }
}

// ──────────────────────────────────────────────────────────────────
// API calls
// ──────────────────────────────────────────────────────────────────
async function fetchDrafts() {
  const res = await fetch('/api/drafts');
  const drafts = await res.json();
  render(drafts);
}

async function saveCurrentDraft() {
  if (!selectedId) return;
  const fields = {
    to:       edTo.value.trim(),
    cc:       edCc.value.trim(),
    subject:  edSubject.value,
    body:     edBody.value,
    sendMode: edSendMode.checked ? 'send' : 'draft',
  };
  const res = await fetch(`/api/drafts/${encodeURIComponent(selectedId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
  const updated = await res.json();
  // Patch local state
  const idx = allDrafts.findIndex((d) => d.id === selectedId);
  if (idx !== -1) allDrafts[idx] = updated;
  renderSidebar();
  renderCounts();
  // Refresh badge in editor
  edStatusBadge.textContent = STATUS_LABELS[updated.status] || updated.status;
  edStatusBadge.className = `badge status-badge status-${updated.status}`;
  edTo.className = updated.to ? '' : 'input-missing';
  return updated;
}

// ──────────────────────────────────────────────────────────────────
// Sidebar click -> select draft
// ──────────────────────────────────────────────────────────────────
draftListEl.addEventListener('click', (e) => {
  const row = e.target.closest('.draft-row');
  if (!row) return;
  selectedId = row.dataset.id;
  renderSidebar(); // re-highlight active row
  loadEditor(selectedDraft());
});

// ──────────────────────────────────────────────────────────────────
// Editor action buttons
// ──────────────────────────────────────────────────────────────────
edSaveBtn.addEventListener('click', async () => {
  edSaveBtn.disabled = true;
  edSaveBtn.textContent = 'Saving...';
  try {
    await saveCurrentDraft();
    edSaveBtn.textContent = 'Saved!';
    setTimeout(() => { edSaveBtn.textContent = 'Save'; }, 1500);
  } catch (err) {
    alert('Save failed: ' + err.message);
    edSaveBtn.textContent = 'Save';
  } finally {
    edSaveBtn.disabled = false;
  }
});

edPushBtn.addEventListener('click', async () => {
  if (!selectedId) return;
  const to = edTo.value.trim();
  if (!to) { alert('Add a recipient email before pushing.'); return; }
  const isSend = edSendMode.checked;
  if (isSend && !confirm(`Send this email to ${to} right now? This cannot be undone.`)) return;

  edPushBtn.disabled = true;
  edPushBtn.textContent = 'Pushing...';
  try {
    await saveCurrentDraft();
    const res = await fetch(`/api/drafts/${encodeURIComponent(selectedId)}/push`, { method: 'POST' });
    const result = await res.json();
    if (!res.ok) {
      alert(`Push failed: ${result.error || 'unknown error'}`);
    } else {
      await fetchDrafts();
      loadEditor(selectedDraft());
    }
  } catch (err) {
    alert('Push error: ' + err.message);
  } finally {
    edPushBtn.disabled = false;
    updatePushBtn();
  }
});

edRemoveBtn.addEventListener('click', async () => {
  if (!selectedId) return;
  if (!confirm('Remove this draft from the queue? This does not delete anything from Outlook.')) return;
  await fetch(`/api/drafts/${encodeURIComponent(selectedId)}`, { method: 'DELETE' });
  selectedId = null;
  loadEditor(null);
  await fetchDrafts();
});

// ──────────────────────────────────────────────────────────────────
// Salesforce contact lookup
// ──────────────────────────────────────────────────────────────────
sfLookupBtn.addEventListener('click', async () => {
  const draft = selectedDraft();
  if (!draft) return;
  sfLookupBtn.disabled = true;
  sfLookupBtn.textContent = 'Looking up...';
  sfDetail.innerHTML = '<em>Searching Salesforce...</em>';
  try {
    const res = await fetch(`/api/sf-lookup?contact=${encodeURIComponent(draft.contactName || '')}&company=${encodeURIComponent(draft.company || '')}`);
    const data = await res.json();
    if (!res.ok || data.error) {
      sfDetail.innerHTML = `<span style="color:#dc2626">${esc(data.error || 'Lookup failed')}</span>`;
    } else if (!data.found) {
      sfDetail.innerHTML = `<span style="color:#d97706">No match found in Salesforce for "${esc(draft.contactName)}"</span>`;
    } else {
      // Auto-fill email if missing
      if (!edTo.value.trim() && data.email) {
        edTo.value = data.email;
        edTo.className = '';
      }
      const parts = [];
      if (data.name)  parts.push(`<strong>${esc(data.name)}</strong>`);
      if (data.title) parts.push(esc(data.title));
      if (data.email) parts.push(`<a href="mailto:${esc(data.email)}">${esc(data.email)}</a>`);
      if (data.phone) parts.push(esc(data.phone));
      if (data.account) parts.push(`@ ${esc(data.account)}`);
      sfDetail.innerHTML = parts.join(' &middot; ');
    }
  } catch (err) {
    sfDetail.innerHTML = `<span style="color:#dc2626">Error: ${esc(err.message)}</span>`;
  } finally {
    sfLookupBtn.disabled = false;
    sfLookupBtn.textContent = '\u26a1 Look up in SF';
  }
});

// ──────────────────────────────────────────────────────────────────
// AI Rewrite
// ──────────────────────────────────────────────────────────────────
rewriteBtn.addEventListener('click', async () => {
  const draft = selectedDraft();
  if (!draft) return;
  const instruction = rewritePrompt.value.trim();
  if (!instruction) { alert('Enter a rewrite instruction first.'); return; }

  rewriteBtn.disabled = true;
  rewriteBtn.textContent = 'Rewriting...';
  rewriteStatus.hidden = false;
  rewriteStatus.textContent = 'Asking AI to rewrite...';

  try {
    const res = await fetch('/api/rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id:          draft.id,
        contactName: draft.contactName,
        company:     draft.company,
        subject:     edSubject.value,
        body:        edBody.value,
        instruction,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      rewriteStatus.textContent = 'Error: ' + (data.error || 'unknown');
      rewriteStatus.style.color = '#dc2626';
    } else {
      edBody.value = data.body;
      if (data.subject) edSubject.value = data.subject;
      rewriteStatus.textContent = 'Done! Review the updated copy above, then hit Save.';
      rewriteStatus.style.color = '#7c3aed';
      setTimeout(() => { rewriteStatus.hidden = true; }, 4000);
    }
  } catch (err) {
    rewriteStatus.textContent = 'Error: ' + err.message;
    rewriteStatus.style.color = '#dc2626';
  } finally {
    rewriteBtn.disabled = false;
    rewriteBtn.textContent = '\u2726 AI Rewrite';
  }
});

// Allow Enter key in rewrite prompt to trigger rewrite
rewritePrompt.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') rewriteBtn.click();
});

// ──────────────────────────────────────────────────────────────────
// Top bar buttons
// ──────────────────────────────────────────────────────────────────
document.getElementById('refreshBtn').addEventListener('click', fetchDrafts);

document.getElementById('pushAllBtn').addEventListener('click', async () => {
  if (!confirm('Push all queued drafts to Outlook now? Items with "Send now" checked will be sent immediately.')) return;
  const btn = document.getElementById('pushAllBtn');
  btn.disabled = true;
  try {
    const res = await fetch('/api/drafts/push-all', { method: 'POST' });
    const result = await res.json();
    if (!res.ok) alert(`Push all failed: ${result.error || 'unknown error'}`);
    else alert(`Pushed ${result.pushed} draft(s).`);
    await fetchDrafts();
    if (selectedId) loadEditor(selectedDraft());
  } finally {
    btn.disabled = false;
  }
});

// ──────────────────────────────────────────────────────────────────
// Boot
// ──────────────────────────────────────────────────────────────────
fetchDrafts();
