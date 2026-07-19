lucide.createIcons();

function switchTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    
    if (window.event && window.event.currentTarget) {
        window.event.currentTarget.classList.add('active');
    } else {
        const items = document.querySelectorAll('.nav-item');
        for (let item of items) {
            if (item.getAttribute('onclick') && item.getAttribute('onclick').includes(tabId)) {
                item.classList.add('active');
                break;
            }
        }
    }
    
    document.getElementById('tab-' + tabId).classList.add('active');
    
    if (tabId === 'stats') {
        renderStats();
    } else if (tabId === 'activities') {
        loadActivities();
    }
}

let allChannels = {};
let sortColumn = 'name';
let sortDirection = 'asc';
let activeFilters = ['all'];

function updateWorkerLimitColor(limit) {
    let input = document.getElementById('worker-limit-input');
    if (!input) return;
    input.classList.remove('limit-green', 'limit-yellow', 'limit-red');
    if (limit <= 3) {
        input.classList.add('limit-green');
    } else if (limit == 4) {
        input.classList.add('limit-yellow');
    } else {
        input.classList.add('limit-red');
    }
}

async function changeWorkerLimit(val) {
    let limit = parseInt(val);
    if (isNaN(limit) || limit < 1 || limit > 10) return;
    updateWorkerLimitColor(limit);
    try {
        await fetch('/api/settings', {
            method: 'POST',
            body: JSON.stringify({ worker_limit: limit.toString() })
        });
    } catch(e) {}
}

async function killTask(channel) {
    if (confirm(`Möchtest du den Worker für ${channel} wirklich beenden?`)) {
        await fetch('/api/action', {
            method: 'POST',
            body: JSON.stringify({ action: 'kill_worker', channel: channel })
        });
        fetchStatus();
    }
}

async function fetchStatus() {
    try {
        let res = await fetch('/api/status');
        let data = await res.json();
        
        let dot = document.getElementById('bot-status-dot');
        let txt = document.getElementById('bot-status-text');
        let btnStart = document.getElementById('btn-start');
        
        if(data.is_running) {
            dot.style.background = '#4ade80';
            txt.innerText = 'Bot läuft';
            if (btnStart) btnStart.innerText = 'Stopp';
            document.querySelectorAll('.save-settings-btn').forEach(btn => {
                btn.innerText = 'Speichern & Bot neustarten';
            });
        } else {
            dot.style.background = '#ef4444';
            txt.innerText = 'Bot gestoppt';
            if (btnStart) btnStart.innerText = 'Start';
            document.querySelectorAll('.save-settings-btn').forEach(btn => {
                btn.innerText = 'Einstellungen speichern';
            });
        }
        
        document.getElementById('worker-count').innerText = data.active_workers_count;
        
        // Aktualisiere das Limit-Eingabefeld nur, wenn der Benutzer nicht gerade aktiv darin schreibt
        let limitInput = document.getElementById('worker-limit-input');
        if (limitInput && document.activeElement !== limitInput) {
            limitInput.value = data.worker_limit;
            updateWorkerLimitColor(data.worker_limit);
        }
        
        // Aktive Tasks in der Sidebar anzeigen
        let container = document.getElementById('active-tasks-container');
        if (container) {
            if (data.active_tasks && data.active_tasks.length > 0) {
                let html = '';
                data.active_tasks.forEach(t => {
                    let name = t.name;
                    let isWatch = name.startsWith('Watch:');
                    let killHtml = '';
                    if (isWatch) {
                        let channel = name.substring(6).trim();
                        killHtml = `<button class="task-kill-btn" onclick="killTask('${channel}')" title="Worker stoppen">×</button>`;
                    }
                    html += `
                        <div class="active-task-item ${isWatch ? '' : 'syncing'}">
                            <span class="task-name" title="${name}">${name}</span>
                            ${killHtml}
                        </div>
                    `;
                });
                container.innerHTML = html;
            } else {
                container.innerHTML = `<div style="color: var(--text-muted); text-align: center; margin-top: 42px; font-style: italic; opacity: 0.6;">Keine aktiven Aktivitäten</div>`;
            }
        }
        
        let actTab = document.getElementById('tab-activities');
        if (actTab && actTab.classList.contains('active')) {
            loadActivities();
        }
    } catch(e) {}
}

async function fetchChannels() {
    try {
        let res = await fetch('/api/channels');
        allChannels = await res.json();
        renderTable();
        updateKpis();
        let statsTab = document.getElementById('tab-stats');
        if (statsTab && statsTab.classList.contains('active')) {
            renderStats();
        }
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
        if(d.is_ignored) continue;
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

function setSort(col) {
    if (sortColumn === col) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        sortColumn = col;
        sortDirection = 'asc';
    }
    renderTable();
}

function toggleFilter(val) {
    if (val === 'all') {
        activeFilters = ['all'];
    } else {
        // Remove 'all'
        activeFilters = activeFilters.filter(f => f !== 'all');
        if (activeFilters.includes(val)) {
            activeFilters = activeFilters.filter(f => f !== val);
        } else {
            activeFilters.push(val);
        }
        if (activeFilters.length === 0) {
            activeFilters = ['all'];
        }
    }
    
    // Update visual button active class
    document.querySelectorAll('.filter-chip').forEach(btn => {
        let filterVal = btn.getAttribute('data-val');
        if (activeFilters.includes(filterVal)) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    renderTable();
}

async function toggleFavorite(name) {
    let currentPrio = (allChannels[name] && allChannels[name].favorite_priority) || 0;
    
    let favorites = [];
    for (let c in allChannels) {
        let p = allChannels[c].favorite_priority || 0;
        if (p > 0) {
            favorites.push({ name: c, priority: p });
        }
    }
    favorites.sort((a, b) => a.priority - b.priority);
    
    if (currentPrio === 0) {
        // Activate: Assign next available rank
        let nextPrio = 1;
        if (favorites.length > 0) {
            nextPrio = favorites[favorites.length - 1].priority + 1;
        }
        if (allChannels[name]) {
            allChannels[name].favorite_priority = nextPrio;
        }
        await setFavoritePriority(name, nextPrio);
    } else {
        // Deactivate: Set to 0 and shift other favorites to prevent gaps
        if (allChannels[name]) {
            allChannels[name].favorite_priority = 0;
        }
        await setFavoritePriority(name, 0);
        
        let index = 1;
        for (let fav of favorites) {
            if (fav.name === name) continue;
            if (fav.priority !== index) {
                if (allChannels[fav.name]) {
                    allChannels[fav.name].favorite_priority = index;
                }
                await setFavoritePriority(fav.name, index);
            }
            index++;
        }
    }
    renderTable();
}

async function moveFavorite(name, direction) {
    let currentPrio = (allChannels[name] && allChannels[name].favorite_priority) || 0;
    if (currentPrio === 0) return;
    
    let favorites = [];
    for (let c in allChannels) {
        let p = allChannels[c].favorite_priority || 0;
        if (p > 0) {
            favorites.push({ name: c, priority: p });
        }
    }
    favorites.sort((a, b) => a.priority - b.priority);
    
    let idx = favorites.findIndex(f => f.name === name);
    if (idx === -1) return;
    
    let swapIdx = -1;
    if (direction === 'up' && idx > 0) {
        swapIdx = idx - 1;
    } else if (direction === 'down' && idx < favorites.length - 1) {
        swapIdx = idx + 1;
    }
    
    if (swapIdx !== -1) {
        let other = favorites[swapIdx];
        
        // Swap local values
        allChannels[name].favorite_priority = other.priority;
        allChannels[other.name].favorite_priority = currentPrio;
        
        // Sync to database
        await setFavoritePriority(name, other.priority);
        await setFavoritePriority(other.name, currentPrio);
        
        renderTable();
    }
}

async function setFavoritePriority(channelName, priorityVal) {
    let priority = parseInt(priorityVal);
    if (isNaN(priority) || priority < 0) priority = 0;
    try {
        await fetch('/api/channels/set_favorite', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channel: channelName, priority: priority})
        });
    } catch (e) {
        console.error("Fehler beim Speichern der Favoriten-Priorität: ", e);
    }
    if (allChannels[channelName]) {
        allChannels[channelName].favorite_priority = priority;
    }
}

function renderTable() {
    let search = document.getElementById('search-input').value.toLowerCase();
    
    let tbody = document.getElementById('channel-table-body');
    tbody.innerHTML = '';
    
    // Update sort icons
    ['favorite_priority', 'is_ignored', 'name', 'streak', 'last_update', 'is_live', 'status'].forEach(col => {
        let el = document.getElementById('sort-icon-' + col);
        if (el) {
            if (sortColumn === col) {
                el.innerText = sortDirection === 'asc' ? ' ▲' : ' ▼';
            } else {
                el.innerText = '';
            }
        }
    });

    let channelsList = [];
    for(let c in allChannels) {
        channelsList.push({ name: c, ...allChannels[c] });
    }

    // Apply Filter
    let filteredList = channelsList.filter(item => {
        if (search && !item.name.toLowerCase().includes(search)) return false;
        
        if (activeFilters.includes('all')) return true;
        
        let matches = false;
        for (let filter of activeFilters) {
            if (filter === 'live' && item.is_live) matches = true;
            else if (filter === 'offline' && !item.is_live) matches = true;
            else if (filter === 'monitored' && !item.is_ignored) matches = true;
            else if (filter === 'ignored' && item.is_ignored) matches = true;
            else if (filter === 'ready' && item.status === 'Bereit') matches = true;
            else if (filter === 'done' && item.status === 'Erledigt') matches = true;
            else if (filter === 'error' && (item.status === 'Fehler' || item.error_count > 0)) matches = true;
            else if (filter === 'waiting' && item.status === 'Offline-Warteschleife') matches = true;
            else if (filter === 'favorites' && (item.favorite_priority || 0) > 0) matches = true;
        }
        return matches;
    });

    // Apply Sorting
    filteredList.sort((a, b) => {
        // First priority: Favorites always at the top!
        let prioA = a.favorite_priority || 0;
        let prioB = b.favorite_priority || 0;
        
        if (prioA > 0 && prioB === 0) return -1;
        if (prioB > 0 && prioA === 0) return 1;
        if (prioA > 0 && prioB > 0) {
            if (prioA !== prioB) return prioA - prioB; // lowest number first (1, 2, 3...)
        }
        
        let valA, valB;
        if (sortColumn === 'name') {
            valA = a.name.toLowerCase();
            valB = b.name.toLowerCase();
        } else if (sortColumn === 'streak') {
            valA = parseInt(a.streak) || 0;
            valB = parseInt(b.streak) || 0;
        } else if (sortColumn === 'last_update') {
            valA = a.last_update || '';
            valB = b.last_update || '';
        } else if (sortColumn === 'is_live') {
            valA = a.is_live ? 1 : 0;
            valB = b.is_live ? 1 : 0;
        } else if (sortColumn === 'status') {
            valA = (a.is_ignored ? 'Ignoriert' : a.status || '').toLowerCase();
            valB = (b.is_ignored ? 'Ignoriert' : b.status || '').toLowerCase();
        } else if (sortColumn === 'is_ignored') {
            valA = a.is_ignored ? 1 : 0;
            valB = b.is_ignored ? 1 : 0;
        } else if (sortColumn === 'favorite_priority') {
            valA = a.name.toLowerCase();
            valB = b.name.toLowerCase();
        }

        if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
        if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    for(let d of filteredList) {
        let c = d.name;
        let tr = document.createElement('tr');
        
        let statusColor = '#9ca3af'; // baseline
        let displayStatus = d.status;
        if(d.is_ignored) { displayStatus = 'Ignoriert'; statusColor = '#6b7280'; }
        else if(d.status === 'baseline') { displayStatus = 'Fehlt: Initiale Erfassung'; statusColor = '#9ca3af'; }
        else if(d.status === 'Bereit') statusColor = '#eab308';
        else if(d.status.includes('Live')) statusColor = '#3b82f6';
        else if(d.status === 'Erledigt') statusColor = '#22c55e';
        else if(d.status === 'Offline-Warteschleife') statusColor = '#a855f7';
        else if(d.status === 'Fehler') statusColor = '#ef4444';
        
        let isFav = (d.favorite_priority || 0) > 0;
        let rank = d.favorite_priority;
        
        let favoritesList = channelsList
            .filter(item => (item.favorite_priority || 0) > 0)
            .sort((a, b) => a.favorite_priority - b.favorite_priority);
            
        let isFirst = isFav && (favoritesList.length > 0 && favoritesList[0].name === c);
        let isLast = isFav && (favoritesList.length > 0 && favoritesList[favoritesList.length - 1].name === c);
        
        let favCellHtml = '';
        if (!isFav) {
            favCellHtml = `
                <div class="favorite-cell" style="justify-content: center;">
                    <span class="favorite-star inactive" onclick="toggleFavorite('${c}')" title="Als Favorit markieren">☆</span>
                </div>
            `;
        } else {
            favCellHtml = `
                <div class="favorite-cell">
                    <span class="favorite-star active" onclick="toggleFavorite('${c}')" title="Aus Favoriten entfernen">★</span>
                    <span class="favorite-rank">${rank}</span>
                    <div class="favorite-arrows">
                        <button class="arrow-btn" ${isFirst ? 'disabled' : ''} onclick="moveFavorite('${c}', 'up')" title="Nach oben verschieben">▲</button>
                        <button class="arrow-btn" ${isLast ? 'disabled' : ''} onclick="moveFavorite('${c}', 'down')" title="Nach unten verschieben">▼</button>
                    </div>
                </div>
            `;
        }
        
        tr.innerHTML = `
            <td>
                ${favCellHtml}
            </td>
            <td style="text-align: center;">
                <input type="checkbox" ${d.is_ignored ? '' : 'checked'} onchange="toggleIgnore('${c}', this.checked)" style="width: 18px; height: 18px; cursor: pointer;">
            </td>
            <td><a href="https://twitch.tv/${c}" target="_blank" style="color: inherit; text-decoration: none; border-bottom: 1px dashed var(--text-muted);" title="Auf Twitch öffnen"><strong>${c}</strong></a></td>
            <td>${d.streak}</td>
            <td>${d.last_update || 'Nie'}</td>
            <td>${d.is_live ? '<span style="color:#ef4444">Live</span>' : 'Offline'}</td>
            <td style="color: ${statusColor}">${displayStatus}</td>
            <td>
                <div style="display: flex; gap: 4px;">
                    <button onclick="resetChannel('${c}')" class="btn-small" style="padding: 3px 8px; font-size: 11px;">Reset</button>
                    <button onclick="markDone('${c}')" class="btn-small" style="padding: 3px 8px; font-size: 11px; background-color: var(--success);" onmouseover="this.style.backgroundColor='#16a34a'" onmouseout="this.style.backgroundColor='var(--success)'">Erledigt</button>
                </div>
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

async function markDone(name) {
    await fetch('/api/action', {
        method: 'POST',
        body: JSON.stringify({action: 'mark_done', channel: name})
    });
    fetchChannels();
}

async function toggleIgnore(name, enabled) {
    await fetch('/api/channels/toggle_ignore', {
        method: 'POST',
        body: JSON.stringify({channel: name, is_ignored: enabled ? 0 : 1})
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
        let res = await fetch('/api/token', { method: 'POST', body: JSON.stringify({token: t}) });
        let data = await res.json();
        if (data.success) {
            document.getElementById('token-modal').style.display = 'none';
            toggleBot(); // start automatically
        } else {
            alert('Fehler: ' + (data.error || 'Token konnte nicht gespeichert werden.'));
        }
    }
}

async function updateToken() {
    let t = document.getElementById('set-auth-token').value;
    if(t) {
        let res = await fetch('/api/token', { method: 'POST', body: JSON.stringify({token: t}) });
        let data = await res.json();
        if (data.success) {
            alert('Token erfolgreich gespeichert!');
        } else {
            alert('Fehler: ' + (data.error || 'Token konnte nicht gespeichert werden.'));
        }
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
    try {
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
    } catch(e) {
        fetch('/api/log/error', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: 'saveSettings error: ' + e.message, source: 'app.js', line: 181 })
        });
        alert('Fehler beim Speichern: ' + e.message);
    }
}

async function backupDb() {
    await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: 'backup_db'}) });
    alert('Backup erstellt!');
}

async function resetDb() {
    if(confirm('Wirklich alles zurücksetzen?')) {
        await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: 'delete_db'}) });
        alert('Datenbank geleert.');
        fetchChannels();
    }
}

async function uninstallBot() {
    if(confirm('Möchtest du den TwitchBot 2.0 wirklich deinstallieren? Dadurch wird die App geschlossen und der Windows-Deinstaller aufgerufen.')) {
        try {
            let res = await fetch('/api/action', {
                method: 'POST',
                body: JSON.stringify({action: 'uninstall'})
            });
            let data = await res.json();
            if (data.status === 'error') {
                alert('Fehler: ' + data.error);
            }
        } catch(e) {
            alert('Fehler beim Aufruf der Deinstallation: ' + e.message);
        }
    }
}

async function downloadLogs() {
    try {
        let res = await fetch('/api/logs/export', { method: 'POST' });
        let data = await res.json();
        
        if (data.success) {
            if (data.cancelled) {
                return;
            }
            alert('Logs erfolgreich exportiert nach:\n' + data.path);
        } else {
            // Fallback for headless or errors: download directly in browser
            let resFallback = await fetch('/api/logs?limit=5000');
            let dataFallback = await resFallback.json();
            let logText = dataFallback.logs.join('');
            
            let blob = new Blob([logText], { type: 'text/plain;charset=utf-8' });
            let url = URL.createObjectURL(blob);
            let a = document.createElement('a');
            a.href = url;
            a.download = `twitchbot_logs_${new Date().toISOString().slice(0,10)}.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    } catch(e) {
        alert('Fehler beim Exportieren der Logs: ' + e.message);
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

function renderStats() {
    let tbody = document.getElementById('stats-table-body');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    let totalPoints = 0;
    let totalChests = 0;
    let totalStreaks = 0;
    let streakCount = 0;
    
    let channelsList = [];
    for(let c in allChannels) {
        channelsList.push({ name: c, ...allChannels[c] });
    }
    
    // Sort by points earned descending, then by name
    channelsList.sort((a, b) => {
        let ptsA = a.points_earned_by_bot || 0;
        let ptsB = b.points_earned_by_bot || 0;
        if (ptsB !== ptsA) return ptsB - ptsA;
        return a.name.localeCompare(b.name);
    });
    
    channelsList.forEach(d => {
        let ptsEarned = d.points_earned_by_bot || 0;
        let chests = d.chests_claimed || 0;
        let ptsBal = d.points_balance || 0;
        let streak = parseInt(d.streak) || 0;
        
        totalPoints += ptsEarned;
        totalChests += chests;
        
        if (!d.is_ignored && d.streak !== '?') {
            totalStreaks += streak;
            streakCount++;
        }
        
        let tr = document.createElement('tr');
        let subTier = d.sub_tier || 'Keins';
        let subColor = 'var(--text-muted)';
        if (subTier.includes('Tier 1')) subColor = '#a855f7';
        else if (subTier.includes('Tier 2')) subColor = '#c084fc';
        else if (subTier.includes('Tier 3')) subColor = '#f472b6';
        
        tr.innerHTML = `
            <td><a href="https://twitch.tv/${d.name}" target="_blank" style="color: inherit; text-decoration: none; border-bottom: 1px dashed var(--text-muted);" title="Auf Twitch öffnen"><strong>${d.name}</strong></a></td>
            <td style="color: ${subColor}; font-weight: 600;">${subTier}</td>
            <td>${ptsBal.toLocaleString()}</td>
            <td style="color: var(--primary); font-weight: bold;">+${ptsEarned.toLocaleString()}</td>
            <td>🎁 ${chests}</td>
            <td>🔥 ${d.streak}</td>
        `;
        tbody.appendChild(tr);
    });
    
    document.getElementById('stats-total-points').innerText = totalPoints.toLocaleString();
    document.getElementById('stats-total-chests').innerText = totalChests.toLocaleString();
    let avg = streakCount > 0 ? Math.round((totalStreaks / streakCount) * 10) / 10 : 0;
    document.getElementById('stats-avg-streak').innerText = avg + ' Tage';
}

async function loadActivities() {
    let container = document.getElementById('activity-timeline');
    if (!container) return;
    
    try {
        let res = await fetch('/api/activities');
        let data = await res.json();
        let list = data.activities || [];
        
        if (list.length === 0) {
            container.innerHTML = `<p style="color: var(--text-muted); text-align: center; margin-top: 40px; font-style: italic;">Keine Aktivitäten protokolliert.</p>`;
            return;
        }
        
        let html = '';
        list.forEach(act => {
            let icon = '📺';
            let iconClass = act.event_type || 'watch_start';
            
            if (act.event_type === 'watch_start') icon = '📺';
            else if (act.event_type === 'watch_stop') icon = '💤';
            else if (act.event_type === 'chest_claimed') icon = '🎁';
            else if (act.event_type === 'streak_increase') icon = '🎉';
            else if (act.event_type === 'error') icon = '❌';
            
            // Format timestamp: YYYY-MM-DD HH:MM:SS -> HH:MM Uhr (DD.MM.)
            let timeStr = act.timestamp;
            try {
                let parts = act.timestamp.split(' ');
                if (parts.length === 2) {
                    let dateParts = parts[0].split('-');
                    let timeParts = parts[1].split(':');
                    timeStr = `${timeParts[0]}:${timeParts[1]} Uhr (${dateParts[2]}.${dateParts[1]}.`;
                }
            } catch(e) {}
            
            html += `
                <div class="activity-item">
                    <div class="activity-icon ${iconClass}">${icon}</div>
                    <div class="activity-content">
                        <div class="activity-meta">
                            <span class="activity-channel">${act.channel}</span>
                            <span class="activity-time">${timeStr}</span>
                        </div>
                        <span class="activity-message">${act.message}</span>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch(e) {
        container.innerHTML = `<p style="color: var(--text-muted); text-align: center; margin-top: 40px; font-style: italic;">Fehler beim Laden des Aktivitäten-Feeds.</p>`;
    }
}

async function quitApp() {
    if(confirm('Möchtest du den Bot wirklich komplett beenden?')) {
        await fetch('/api/action', { method: 'POST', body: JSON.stringify({action: 'quit'}) });
        window.close();
    }
}

async function refreshStatsData() {
    const btn = document.getElementById('btn-refresh-stats');
    if (!btn) return;
    
    const originalText = btn.innerText;
    btn.innerText = 'Lade...';
    btn.disabled = true;
    
    try {
        const res = await fetch('/api/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'refresh_stats' })
        });
        
        if (res.ok) {
            setTimeout(() => {
                fetchChannels();
                btn.innerText = originalText;
                btn.disabled = false;
            }, 3000);
        } else {
            btn.innerText = originalText;
            btn.disabled = false;
            alert('Fehler beim Starten der Aktualisierung.');
        }
    } catch (e) {
        btn.innerText = originalText;
        btn.disabled = false;
        alert('Netzwerkfehler: ' + e.message);
    }
}