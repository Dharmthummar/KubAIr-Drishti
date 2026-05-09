let lastBatchData = null;

document.addEventListener('DOMContentLoaded', loadConfig);

async function loadConfig() {
    const status = document.getElementById('config-status');
    try {
        const response = await fetch('/api/config');
        const config = await response.json();

        document.getElementById('config-api-key').value = '';
        document.getElementById('config-api-key').placeholder = config.gemini_api_key_set
            ? `Saved: ${config.gemini_api_key_masked}`
            : 'Paste Gemini API key';
        document.getElementById('config-model').value = config.gemini_model || 'gemini-3.1-flash-lite-preview';
        document.getElementById('config-ocr-model').value = config.gemini_ocr_model || config.gemini_model || 'gemini-3.1-flash-lite-preview';
        document.getElementById('config-fast-mode').checked = Boolean(config.fast_mode);
        document.getElementById('config-pdf-ocr').checked = Boolean(config.pdf_ocr_enabled);

        status.innerText = config.gemini_api_key_set ? 'API key saved' : 'API key missing';
        status.className = config.gemini_api_key_set ? 'subtitle status-ok' : 'subtitle status-warn';
    } catch (error) {
        status.innerText = 'Configuration unavailable';
        status.className = 'subtitle status-warn';
    }
}

async function saveConfig() {
    const status = document.getElementById('config-status');
    const payload = {
        gemini_api_key: document.getElementById('config-api-key').value.trim(),
        gemini_model: document.getElementById('config-model').value.trim(),
        gemini_ocr_model: document.getElementById('config-ocr-model').value.trim(),
        fast_mode: document.getElementById('config-fast-mode').checked,
        pdf_ocr_enabled: document.getElementById('config-pdf-ocr').checked
    };

    status.innerText = 'Saving configuration...';
    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!result.success) throw new Error(result.error || 'Config save failed');

        document.getElementById('config-api-key').value = '';
        document.getElementById('config-api-key').placeholder = result.gemini_api_key_set
            ? `Saved: ${result.gemini_api_key_masked}`
            : 'Paste Gemini API key';
        status.innerText = 'Configuration saved';
        status.className = 'subtitle status-ok';
    } catch (error) {
        status.innerText = error.message || 'Config save failed';
        status.className = 'subtitle status-warn';
    }
}

async function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    document.getElementById('processing-status').classList.remove('hidden');
    document.getElementById('upload-prompt').classList.add('hidden');
    document.getElementById('main-content').classList.add('hidden');
    document.getElementById('history-content').classList.add('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/upload-excel', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        
        if (result.success) {
            lastBatchData = result;
            updateDashboard(result);
            document.getElementById('main-content').classList.remove('hidden');
        } else {
            alert("Upload Error: " + result.error);
            document.getElementById('upload-prompt').classList.remove('hidden');
        }
    } catch (error) {
        console.error("Upload failed", error);
        alert("A network error occurred during upload.");
        document.getElementById('upload-prompt').classList.remove('hidden');
    } finally {
        document.getElementById('processing-status').classList.add('hidden');
    }
}

function updateDashboard(data) {
    document.getElementById('count-total').innerText = data.invoices.length;
    
    const tbody = document.getElementById('invoice-tbody');
    tbody.innerHTML = '';
    
    let processedCount = 0;

    data.invoices.forEach((inv, idx) => {
        const row = document.createElement('tr');
        
        const status = inv._status || 'Pending';
        const reviewStatus = inv._review_status || data.auto_processed?.[idx]?.review_status || (status === 'processed' ? 'Clear' : status);
        const hasDebitNote = Boolean(inv._has_debit_note || data.auto_processed?.[idx]?.has_debit_note);
        const hasDueDateStamp = Boolean(inv._has_due_date_stamp || data.auto_processed?.[idx]?.has_due_date_stamp);
        const alerts = data.alerts?.[idx] || data.alerts?.[String(idx)] || [];
        const alertCount = alerts.length || data.auto_processed?.[idx]?.alerts || 0;
        
        if (status === 'processed') processedCount++;
        const processedFile = data.processed?.[idx]?.output_filename;

        row.innerHTML = `
            <td>${escapeHtml(inv.invoice_id || 'N/A')}</td>
            <td>${escapeHtml(inv.invoice_date || '')}</td>
            <td>${escapeHtml(inv.party_name || 'N/A')}</td>
            <td>${escapeHtml(inv.inward_no || inv.mrn_number || '')}</td>
            <td>${escapeHtml(inv.due_date || '')}</td>
            <td class="amount-cell">${formatAmount(inv.amount || '0.00')}</td>
            <td>${escapeHtml(inv.purchase_book || '')}</td>
            <td>${renderYesNo(hasDebitNote)}</td>
            <td>${renderYesNo(hasDueDateStamp)}</td>
            <td>${renderReviewStatus(reviewStatus)}</td>
            <td>${renderAlerts(alerts, alertCount)}</td>
            <td>
                ${processedFile ? renderPdfActions(processedFile) : '<span class="subtitle">Not ready</span>'}
            </td>
        `;
        tbody.appendChild(row);
    });

    document.getElementById('count-processed').innerText = processedCount;
}

function renderYesNo(value) {
    return value
        ? '<span class="badge badge-danger">Yes</span>'
        : '<span class="badge badge-neutral">No</span>';
}

function renderReviewStatus(status) {
    const label = status || 'Clear';
    const normalized = label.toLowerCase();
    let badgeClass = 'badge-success';

    if (
        normalized.includes('debit')
        || normalized.includes('hold')
        || normalized.includes('mismatch')
        || normalized.includes('tax')
        || normalized.includes('failed')
    ) {
        badgeClass = 'badge-danger';
    } else if (
        normalized.includes('due date')
        || normalized.includes('short')
        || normalized.includes('urgent')
        || normalized.includes('review')
    ) {
        badgeClass = 'badge-warning';
    }

    return `<span class="badge ${badgeClass}">${escapeHtml(label)}</span>`;
}

function renderAlerts(alertsOrCount, fallbackCount = null) {
    const alerts = Array.isArray(alertsOrCount) ? alertsOrCount : [];
    const alertCount = Array.isArray(alertsOrCount) ? alerts.length : Number(alertsOrCount || 0);
    const count = fallbackCount === null ? alertCount : Math.max(alertCount, Number(fallbackCount || 0));

    if (count > 0) {
        const tooltip = alerts.length
            ? alerts.map((alert, idx) => {
                const severity = alert.severity ? `${alert.severity}: ` : '';
                const source = alert.source ? ` (${alert.source})` : '';
                return `${idx + 1}. ${severity}${alert.message || 'Alert'}${source}`;
            }).join('\n')
            : `${count} alert${count === 1 ? '' : 's'}`;

        const safeTooltip = escapeAttr(tooltip);
        return `<span class="badge badge-danger alert-badge" data-tooltip="${safeTooltip}" title="${safeTooltip}">${count} Alerts</span>`;
    }
    return `<span class="badge badge-success">0 Alerts</span>`;
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;

    appendMessage('user', msg);
    input.value = '';

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: msg })
        });
        const result = await response.json();
        appendMessage('bot', result.answer || "Error connecting to assistant.");
    } catch (error) {
        appendMessage('bot', "Network error connecting to assistant.");
    }
}

function handleEnter(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

function toggleChat() {
    const panel = document.getElementById('chat-panel');
    panel.classList.toggle('minimized');
}

function toggleConfig() {
    const modal = document.getElementById('config-modal');
    modal.classList.toggle('hidden');
}

function appendMessage(sender, text) {
    const container = document.getElementById('chat-messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-bubble ${sender}`;
    msgDiv.innerText = text;
    
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

async function downloadAllZip() {
    window.location.href = '/api/download-all-zip';
}

async function printAll() {
    const res = await fetch('/api/print-all');
    const data = await res.json();
    if (data.success) {
        window.open(data.url, '_blank');
    } else {
        alert("Error generating master print: " + data.error);
    }
}

function downloadPdf(id) {
    window.location.href = `/api/download/${encodeURIComponent(id)}`;
}

function showCurrentBatch() {
    document.getElementById('history-content').classList.add('hidden');
    if (lastBatchData) {
        document.getElementById('upload-prompt').classList.add('hidden');
        document.getElementById('main-content').classList.remove('hidden');
    } else {
        document.getElementById('upload-prompt').classList.remove('hidden');
        document.getElementById('main-content').classList.add('hidden');
    }
}

async function showHistory() {
    document.getElementById('upload-prompt').classList.add('hidden');
    document.getElementById('main-content').classList.add('hidden');
    document.getElementById('history-content').classList.remove('hidden');
    await loadHistory();
}

async function loadHistory() {
    const tbody = document.getElementById('history-tbody');
    const summary = document.getElementById('history-summary');
    tbody.innerHTML = '<tr><td colspan="12" class="text-center">Loading...</td></tr>';

    try {
        const response = await fetch('/api/history');
        const data = await response.json();
        const history = data.history || [];

        summary.innerText = `${history.length} recent processed invoices`;
        if (!history.length) {
            tbody.innerHTML = '<tr><td colspan="12" class="text-center">No history found.</td></tr>';
            return;
        }

        tbody.innerHTML = '';
        history.forEach((item) => {
            const alerts = Array.isArray(item.alerts) ? item.alerts : [];
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${escapeHtml(formatDateTime(item.processed_at))}</td>
                <td>${escapeHtml(item.invoice_id || 'N/A')}</td>
                <td>${escapeHtml(item.party_name || 'N/A')}</td>
                <td>${escapeHtml(item.inward_no || item.mrn_number || '')}</td>
                <td>${escapeHtml(item.invoice_date || '')}</td>
                <td>${escapeHtml(item.due_date || '')}</td>
                <td class="amount-cell">${formatAmount(item.amount || 0)}</td>
                <td>${renderYesNo(Boolean(item.has_debit_note))}</td>
                <td>${renderYesNo(Boolean(item.has_due_date_stamp))}</td>
                <td>${renderReviewStatus(item.review_status || 'Clear')}</td>
                <td>${renderAlerts(alerts)}</td>
                <td>${item.output_pdf_path ? renderPdfActions(item.output_pdf_path) : '<span class="subtitle">Missing</span>'}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="12" class="text-center">Failed to load history.</td></tr>';
    }
}

async function clearHistory() {
    if (!confirm("Are you sure you want to clear all invoice history? This action cannot be undone.")) {
        return;
    }

    try {
        const response = await fetch('/api/clear-history', { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            await loadHistory();
        } else {
            alert("Error clearing history: " + result.error);
        }
    } catch (error) {
        alert("Failed to connect to server.");
    }
}

function renderPdfActions(filename) {
    const safeName = encodeURIComponent(filename);
    return `
        <div class="action-group">
            <button class="btn icon-btn" title="View PDF" aria-label="View PDF" onclick="window.open('/api/view/${safeName}', '_blank')">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"></path><circle cx="12" cy="12" r="3"></circle></svg>
            </button>
            <button class="btn icon-btn" title="Download PDF" aria-label="Download PDF" onclick="window.location.href='/api/download/${safeName}'">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path></svg>
            </button>
        </div>
    `;
}

function formatAmount(value) {
    const number = Number(String(value).replace(/,/g, ''));
    if (!Number.isFinite(number)) return escapeHtml(value || '0.00');
    return number.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function formatDateTime(value) {
    if (!value) return '';
    return String(value).replace('T', ' ').slice(0, 19);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/\r?\n/g, '&#10;');
}
