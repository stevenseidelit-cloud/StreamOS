lucide.createIcons();

function switchTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    
    event.currentTarget.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');
}

let allChannels = {};

async function fetchStatus() {
    try {
        let res = await fetch('/api/status');
        let data = await res.json();
        
        let dot = document.getElementById('bot-status-dot');
        let txt = document.getElementById('bot-status-text');
        
        if(data.is_running) {
            dot.style.background = '#4ade80';
            txt.innerText = 'Bot läuft';
        } else {
            dot.style.background = '#ef4444';
            txt.innerText = 'Bot gestoppt';
        }
        
        document.getElementById('worker-count').innerText = data.active_workers;
        document.getElementById('worker-limit').innerText = data.worker_limit;
    } catch(e) {}
}

async function fetchChannels() {
    try {
        let res = await fetch('/api/channels');
        allChannels = await res.json();
        renderTable();
        updateKpis();
    } catch(e) {}
}

function updateKpis() {
    let total = 0;
    let live = 0;
    let ready = 0;
    let done = 0;
    let error = 0;
    
    for(let c in allChannels) {
        let d = allChannels[c];
        total++;
        if(d.is_live) live++;
        if(d.status === 'Bereit') ready++;
        if(d.status === 'Erledigt') done++;
        if(d.status === 'Fehler') error++;
    }
    
    document.getElementById('kpi-total').innerText = total;
    document.getElementById('kpi-live').innerText = live;
    document.getElementById('kpi-ready').innerText = ready;
    document.getElementById('kpi-done').innerText = done;
    document.getElementById('kpi-error').innerText = error;
}

function renderTable() {
    let search = document.getElementById('search-input').value.toLowerCase();
    let filter = document.getElementById('filter-select').value;
    
    let tbody = document.getElementById('channel-table-body');
    tbody.innerHTML = '';
    
    let keys = Object.keys(allChannels).sort();
    for(let c of keys) {
        let d = allChannels[c];
        
        if(search && !c.includes(search)) continue;
        if(filter !== 'all' && d.status !== filter && filter !== 'Fehlt: Initiale Erfassung') {
            if(filter === 'Fehlt: Initiale Erfassung' && d.status !== 'baseline') continue;
            if(d.status !== filter && d.status !== 'baseline') continue;
            // Wait, logic is slightly complex. Simple approach:
            if(filter === 'Fehlt: Initiale Erfassung' && d.status !== 'baseline') continue;
            if(filter !== 'Fehlt: Initiale Erfassung' && d.status !== filter) continue;
        }
        
        let tr = document.createElement('tr');
        
        // Status color mapping
        let statusColor = '#9ca3af'; // baseline
        let displayStatus = d.status;
        if(d.status === 'baseline') { displayStatus = 'Fehlt: Initiale Erfassung'; statusColor = '#9ca3af'; }
        else if(d.status === 'Bereit') statusColor = '#eab308';
        else if(d.status.includes('Live')) statusColor = '#3b82f6';
        else if(d.status === 'Erledigt') statusColor = '#22c55e';
        else if(d.status === 'Offline-Warteschleife') statusColor = '#a855f7';
        else if(d.status === 'Fehler') statusColor = '#ef4444';
        
        tr.innerHTML = `
            <td><strong>${c}</strong></td>
            <td>${d.streak}</td>
            <td>${d.is_live ? '<span style="color:#ef4444">Live</span>' : 'Offline'}</td>
            <td style="color: ${statusColor}">${displayStatus}</td>
            <td>
                <button onclick="resetChannel('${c}')" class="btn-small">Reset</button>
            </td>
        `;
        tbody.appendChild(tr);
    }
}

async function resetChannel(name) {
    await fetch('/api/action', {
        method: 'POST',
        body: JSON.stringify({action: 'reset_channel', channel: name})
    });
    fetchChannels();
}

async function toggleBot() {
    let txt = document.getElementById('bot-status-text').innerText;
    let action = txt === 'Bot gestoppt' ? 'start' : 'stop';
    await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: action}) });
    setTimeout(fetchStatus, 500);
}

async function startSync() {
    await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: 'sync'}) });
}

async function fetchLogs() {
    try {
        let res = await fetch('/api/logs');
        let data = await res.json();
        let c = document.getElementById('log-container');
        c.innerHTML = data.logs.join('<br>');
        c.scrollTop = c.scrollHeight;
    } catch(e) {}
}

async function checkToken() {
    try {
        let res = await fetch('/api/token/status');
        let data = await res.json();
        if(!data.has_token) {
            document.getElementById('token-modal').style.display = 'flex';
        }
    } catch(e) {}
}

async function saveToken() {
    let t = document.getElementById('auth-token-input').value;
    if(t) {
        await fetch('/api/token', { method: 'POST', body: JSON.stringify({token: t}) });
        document.getElementById('token-modal').style.display = 'none';
        toggleBot(); // start automatically
    }
}

async function updateToken() {
    let t = document.getElementById('set-auth-token').value;
    if(t) {
        await fetch('/api/token', { method: 'POST', body: JSON.stringify({token: t}) });
        alert('Token gespeichert!');
    }
}

async function fetchSettings() {
    try {
        let res = await fetch('/api/settings');
        let data = await res.json();
        for(let k in data) {
            let el = document.getElementById('set-' + k);
            if(el) {
                if(el.type === 'checkbox') el.checked = data[k] === '1';
                else el.value = data[k];
            }
        }
    } catch(e){}
}

async function saveSettings() {
    let data = {};
    document.querySelectorAll('.setting-input').forEach(el => {
        let k = el.id.replace('set-', '');
        data[k] = el.value;
    });
    document.querySelectorAll('.setting-cb').forEach(el => {
        let k = el.id.replace('set-', '');
        data[k] = el.checked ? '1' : '0';
    });
    await fetch('/api/settings', { method: 'POST', body: JSON.stringify(data) });
    alert('Einstellungen gespeichert!');
}

async function backupDb() {
    await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: 'backup_db'}) });
    alert('Backup erstellt!');
}

async function readApiResponse(response) {
    let data = await response.json();
    if(!response.ok || data.success === false) {
        throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
}

async function checkUpdates() {
    let status = document.getElementById('update-status');
    let result = document.getElementById('update-result');
    let portableButton = document.getElementById('btn-download-portable');
    let setupButton = document.getElementById('btn-install-update');

    status.innerText = 'GitHub-Release wird geprüft...';
    result.innerText = '';
    portableButton.disabled = true;
    setupButton.disabled = true;

    try {
        let response = await fetch('/api/update/status');
        let data = await readApiResponse(response);
        if(data.update_available) {
            status.innerText = `Neue Version ${data.latest_version} verfügbar (installiert: ${data.current_version}).`;
        } else {
            status.innerText = `Aktuelle Version: ${data.current_version}. Neuestes Release: ${data.latest_version}.`;
        }
        portableButton.disabled = !data.portable_available;
        setupButton.disabled = !data.setup_available;
    } catch(error) {
        status.innerText = `Update-Prüfung fehlgeschlagen: ${error.message}`;
    }
}

async function downloadPortableVersion() {
    let result = document.getElementById('update-result');
    let openFolderButton = document.getElementById('btn-open-update-folder');
    result.innerText = 'Portable Version wird heruntergeladen und geprüft...';
    openFolderButton.classList.add('hidden');

    try {
        let response = await fetch('/api/update/download', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind: 'portable'})
        });
        let data = await readApiResponse(response);
        result.innerText = `Portable Version wurde geprüft und gespeichert: ${data.local_path}`;
        openFolderButton.classList.remove('hidden');
    } catch(error) {
        result.innerText = `Portable Download fehlgeschlagen: ${error.message}`;
    }
}

async function installUpdate() {
    let result = document.getElementById('update-result');
    result.innerText = 'Installer wird heruntergeladen und geprüft...';

    try {
        let downloadResponse = await fetch('/api/update/download', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({kind: 'setup'})
        });
        let data = await readApiResponse(downloadResponse);
        result.innerText = `Installer wurde geprüft und gespeichert: ${data.local_path}`;

        if(!confirm(`StreamOS ${data.version} jetzt sichtbar starten und installieren?`)) {
            result.innerText += ' Installation wurde nicht gestartet.';
            return;
        }

        let installResponse = await fetch('/api/update/install', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}'
        });
        await readApiResponse(installResponse);
        result.innerText = 'Der verifizierte Installer wurde sichtbar gestartet.';
    } catch(error) {
        result.innerText = `Update fehlgeschlagen: ${error.message}`;
    }
}

async function openUpdateFolder() {
    let result = document.getElementById('update-result');
    try {
        let response = await fetch('/api/update/open-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: '{}'
        });
        await readApiResponse(response);
    } catch(error) {
        result.innerText = `Ordner konnte nicht geöffnet werden: ${error.message}`;
    }
}

async function resetDb() {
    if(confirm('Wirklich alles zurücksetzen?')) {
        await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: 'delete_db'}) });
        alert('Datenbank geleert.');
        fetchChannels();
    }
}

function uninstallBot() {
    if(confirm('StreamOS entfernen?\n(Diese Funktion ruft in der finalen Version den Windows Uninstaller auf)')) {
        alert('Deinstallation wird simuliert...');
    }
}

setInterval(fetchStatus, 2000);
setInterval(fetchChannels, 5000);
setInterval(fetchLogs, 3000);

checkToken();
fetchSettings();
fetchChannels();
fetchStatus();
fetchLogs();
