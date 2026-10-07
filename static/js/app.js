/* ═══════════════════════════════════════════════════════════════════════════
   GameLibrarian — Frontend
   ═══════════════════════════════════════════════════════════════════════════ */

'use strict';

// ── Constants ─────────────────────────────────────────────────────────────────

const PLATFORMS = {
  steam:          { label: 'Steam',       cls: 'steam' },
  epic:           { label: 'Epic Games',  cls: 'epic' },
  ea_origin:      { label: 'EA Origin',   cls: 'ea' },
  nintendo:       { label: 'Nintendo',    cls: 'nintendo' },
  sega:           { label: 'Sega',        cls: 'sega' },
  xbox:           { label: 'Xbox',        cls: 'xbox' },
  playstation:    { label: 'PlayStation', cls: 'playstation' },
  gog:            { label: 'GoG',         cls: 'gog' },
  blizzard:       { label: 'Blizzard',    cls: 'blizzard' },
  microsoft:      { label: 'Microsoft',   cls: 'microsoft' },
};

const STATUSES = {
  currently_playing: { label: 'Now Playing',     cls: 'currently_playing' },
  unplayed:          { label: 'Unplayed',         cls: 'unplayed' },
  unfinished:        { label: 'Unfinished',       cls: 'unfinished' },
  completed:         { label: 'Completed',        cls: 'completed' },
  abandoned:         { label: 'Abandoned',        cls: 'abandoned' },
  multiplayer_only:  { label: 'Multiplayer',      cls: 'multiplayer_only' },
  cant_complete:     { label: "Can't Complete",   cls: 'cant_complete' },
};

// ── State ─────────────────────────────────────────────────────────────────────

const state = {
  allGames:        [],   // full result from API (search + sort only)
  games:           [],   // after client-side filters — used by renderers
  view:            'grid',
  page:            'library',
  sortField:       'name',
  sortDir:         'asc',
  igdbConfigured:  false,
  editingGameId:   null,
  currentRating:   0,
  igdbTimer:       null,
  filterPlatforms: new Set(),
  filterStatuses:  new Set(),
  filterRatings:   new Set(),
  hideCompleted:   false,
};

// ── API helpers ───────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body:    body ? JSON.stringify(body) : undefined,
  };
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

const GET    = (p)    => api('GET',    p);
const POST   = (p, b) => api('POST',   p, b);
const PUT    = (p, b) => api('PUT',    p, b);
const DELETE = (p)    => api('DELETE', p);

// ── Initialisation ────────────────────────────────────────────────────────────

async function init() {
  try {
    const cfg = await GET('/api/config');
    state.igdbConfigured = cfg.igdb_configured;
  } catch (_) { /* offline or error — ignore */ }

  // Nav
  document.querySelectorAll('.nav-btn').forEach(btn =>
    btn.addEventListener('click', () => switchPage(btn.dataset.page))
  );

  // View toggle
  document.querySelectorAll('.view-btn').forEach(btn =>
    btn.addEventListener('click', () => switchView(btn.dataset.view))
  );

  // Add game button
  document.getElementById('addGameBtn').addEventListener('click', openAddModal);

  // Search input with clear button
  const searchInput    = document.getElementById('searchInput');
  const searchClearBtn = document.getElementById('searchClearBtn');
  const debouncedLoad  = debounce(loadGames, 250);
  searchInput.addEventListener('input', () => {
    searchClearBtn.classList.toggle('hidden', searchInput.value === '');
    debouncedLoad();
  });
  searchClearBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchClearBtn.classList.add('hidden');
    searchInput.focus();
    loadGames();
  });

  // Build multi-select filter dropdowns
  buildFilterDropdowns();

  // Close any open panel when clicking outside
  document.addEventListener('click', () => {
    document.querySelectorAll('.filter-panel').forEach(p => p.classList.add('hidden'));
  });

  // Hide-completed checkbox
  document.getElementById('hideCompleted').addEventListener('change', e => {
    state.hideCompleted = e.target.checked;
    applyFiltersAndRender();
    updateClearFiltersBtn();
  });

  // Clear-all-filters button
  document.getElementById('clearFiltersBtn').addEventListener('click', clearAllFilters);

  document.getElementById('sortField')     .addEventListener('change', e => { state.sortField = e.target.value; loadGames(); });
  document.getElementById('sortDirBtn')    .addEventListener('click',  toggleSortDir);

  // List-header sort
  document.querySelectorAll('.list-table .sortable').forEach(th =>
    th.addEventListener('click', () => {
      if (state.sortField === th.dataset.sort) {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortField = th.dataset.sort;
        state.sortDir   = 'asc';
        document.getElementById('sortField').value = state.sortField;
      }
      loadGames();
    })
  );

  // Modal controls
  document.getElementById('modalCloseBtn') .addEventListener('click', closeModal);
  document.getElementById('cancelModalBtn').addEventListener('click', closeModal);
  document.getElementById('saveGameBtn')   .addEventListener('click', saveGame);
  document.getElementById('deleteGameBtn') .addEventListener('click', () => confirmDelete(state.editingGameId));
  document.getElementById('gameModal')     .addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });

  // Confirm-delete modal
  document.getElementById('confirmCancelBtn').addEventListener('click', () => hide('confirmModal'));
  document.getElementById('confirmModal')    .addEventListener('click', e => { if (e.target === e.currentTarget) hide('confirmModal'); });

  // IGDB search
  document.getElementById('igdbSearchInput').addEventListener('input', e => {
    clearTimeout(state.igdbTimer);
    const q = e.target.value.trim();
    if (q.length < 2) { hide('igdbResults'); return; }
    state.igdbTimer = setTimeout(() => searchIGDB(q), 350);
  });
  document.getElementById('igdbSearchInput').addEventListener('blur', () => {
    setTimeout(() => hide('igdbResults'), 200);
  });

  // Cover URL toggle
  document.getElementById('coverUrlBtn').addEventListener('click', toggleCoverUrlInput);
  document.getElementById('coverUrlInput').addEventListener('change', e => applyCoverUrl(e.target.value));

  // Steam platform checkbox → show/hide App ID field
  document.querySelector('input[name="platform"][value="steam"]')
    .addEventListener('change', e => onSteamToggle(e.target.checked));

  // Settings + wishlist
  document.getElementById('settingsBtn')       .addEventListener('click', () => switchPage('settings'));
  document.getElementById('saveSettingsBtn')   .addEventListener('click', saveSettings);
  document.getElementById('igdbTestBtn')       .addEventListener('click', () => checkIgdbStatus(true));
  document.getElementById('syncSteamBtn')      .addEventListener('click', syncSteamData);
  document.getElementById('wishlistRefreshBtn').addEventListener('click', () => loadWishlist(true));

  // Star picker
  initStarPicker();

  // Comment counter
  document.getElementById('formComment').addEventListener('input', updateCharCount);

  // Status -> auto disable rating if abandoned
  document.getElementById('formStatus').addEventListener('change', e => {
    const isAbandoned = e.target.value === 'abandoned';
    setRating(isAbandoned ? 0 : state.currentRating);
    document.getElementById('starPicker').style.opacity = isAbandoned ? '0.3' : '1';
    document.getElementById('starPicker').style.pointerEvents = isAbandoned ? 'none' : 'auto';
  });

  await loadGames();
}

// ── Navigation ────────────────────────────────────────────────────────────────

function switchPage(page) {
  state.page = page;
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  document.getElementById('settingsBtn').classList.toggle('active', page === 'settings');
  document.getElementById('libraryPage') .classList.toggle('hidden', page !== 'library');
  document.getElementById('statsPage')   .classList.toggle('hidden', page !== 'stats');
  document.getElementById('wishlistPage').classList.toggle('hidden', page !== 'wishlist');
  document.getElementById('settingsPage').classList.toggle('hidden', page !== 'settings');
  document.getElementById('viewToggle').style.visibility = page === 'library' ? 'visible' : 'hidden';
  document.getElementById('addGameBtn').style.display    = page === 'library' ? '' : 'none';
  if (page === 'stats')    loadStats();
  if (page === 'wishlist') loadWishlist();
  if (page === 'settings') loadSettings();
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  document.getElementById('gridView').classList.toggle('hidden', view !== 'grid');
  document.getElementById('listView').classList.toggle('hidden', view !== 'list');
  renderGames();
}

function toggleSortDir() {
  state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
  const icon = document.getElementById('sortDirIcon');
  icon.style.transform = state.sortDir === 'desc' ? 'scaleY(-1)' : '';
  loadGames();
}

// ── Load & render games ───────────────────────────────────────────────────────

async function loadGames() {
  const search = document.getElementById('searchInput').value.trim();
  const params = new URLSearchParams({ sort: state.sortField, dir: state.sortDir });
  if (search) params.set('search', search);

  try {
    state.allGames = await GET(`/api/games?${params}`);
    applyFiltersAndRender();
  } catch (e) {
    showToast('Failed to load games: ' + e.message, 'error');
  }
}

function applyFiltersAndRender() {
  let games = state.allGames;

  if (state.filterPlatforms.size > 0)
    games = games.filter(g => [...state.filterPlatforms].some(p => (g.platforms || []).includes(p)));

  if (state.filterStatuses.size > 0)
    games = games.filter(g => state.filterStatuses.has(g.status));

  if (state.filterRatings.size > 0)
    games = games.filter(g => state.filterRatings.has(String(g.rating)));

  if (state.hideCompleted)
    games = games.filter(g => !['completed', 'abandoned'].includes(g.status));

  state.games = games;
  renderGames();
}

function renderGames() {
  const count = state.games.length;
  document.getElementById('gameCount').textContent =
    count === 0 ? 'No games' : `${count} game${count !== 1 ? 's' : ''}`;

  const isEmpty = count === 0;
  const emptyEl = document.getElementById('emptyState');
  const hasFilters =
    document.getElementById('searchInput').value ||
    state.filterPlatforms.size > 0 ||
    state.filterStatuses.size  > 0 ||
    state.filterRatings.size   > 0 ||
    state.hideCompleted;

  if (isEmpty) {
    document.getElementById('emptyTitle').textContent    = hasFilters ? 'No games match your filters' : 'No games yet';
    document.getElementById('emptySubtitle').textContent = hasFilters ? 'Try adjusting your filters.' : 'Click "Add Game" to get started.';
    emptyEl.classList.remove('hidden');
    document.getElementById('gridView').classList.add('hidden');
    document.getElementById('listView').classList.add('hidden');
    return;
  }

  emptyEl.classList.add('hidden');
  if (state.view === 'grid') {
    document.getElementById('gridView').classList.remove('hidden');
    document.getElementById('listView').classList.add('hidden');
    renderGrid();
  } else {
    document.getElementById('gridView').classList.add('hidden');
    document.getElementById('listView').classList.remove('hidden');
    renderList();
  }
}

function renderGrid() {
  const el = document.getElementById('gridView');
  const nowPlaying = state.games.filter(g => g.status === 'currently_playing');
  const rest       = state.games.filter(g => g.status !== 'currently_playing');

  function cardHtml(g) {
    return `
      <div class="game-card" data-id="${g.id}" data-status="${g.status}">
        ${g.cover_local_url
          ? `<img class="game-card-cover" src="${g.cover_local_url}" alt="${escHtml(g.name)}" loading="lazy" />`
          : `<div class="game-card-cover-placeholder">
               <svg viewBox="0 0 48 64" fill="none"><rect x="2" y="2" width="44" height="60" rx="4" stroke="currentColor" stroke-width="2"/><circle cx="24" cy="28" r="8" stroke="currentColor" stroke-width="2"/></svg>
               No Cover
             </div>`
        }
        <span class="status-badge ${STATUSES[g.status]?.cls || ''}">
          ${STATUSES[g.status]?.label || g.status}
        </span>
        <div class="game-card-info">
          <div class="game-card-title">${escHtml(g.name)}</div>
          <div class="game-card-meta">
            <div class="card-platforms">${renderPlatformPills(g.platforms || [])}</div>
            <div class="card-stars">${renderStars(g.rating)}</div>
          </div>
        </div>
      </div>
    `;
  }

  let html = '';

  if (nowPlaying.length > 0) {
    html += `
      <div class="now-playing-section">
        <div class="now-playing-header">
          <span class="now-playing-dot"></span>
          Now Playing
        </div>
        <div class="game-grid">${nowPlaying.map(cardHtml).join('')}</div>
      </div>
    `;
    if (rest.length > 0) html += `<div class="library-divider"></div>`;
  }

  if (rest.length > 0) {
    html += `<div class="game-grid">${rest.map(cardHtml).join('')}</div>`;
  }

  el.innerHTML = html;
  el.querySelectorAll('.game-card').forEach(card =>
    card.addEventListener('click', () => openEditModal(Number(card.dataset.id)))
  );
}

function renderList() {
  const body = document.getElementById('listBody');

  // Update sort indicators
  document.querySelectorAll('.list-table .sortable').forEach(th => {
    th.classList.toggle('sort-active', th.dataset.sort === state.sortField);
  });

  const nowPlaying = state.games.filter(g => g.status === 'currently_playing');
  const rest       = state.games.filter(g => g.status !== 'currently_playing');

  function rowHtml(g) {
    return `
      <tr data-id="${g.id}" data-status="${g.status}">
        <td>
          ${g.cover_local_url
            ? `<img class="list-thumb" src="${g.cover_local_url}" alt="${escHtml(g.name)}" loading="lazy" />`
            : `<div class="list-thumb-placeholder"><svg viewBox="0 0 20 20" fill="currentColor"><path d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm0 2h12v10H4V5z"/></svg></div>`
          }
        </td>
        <td>
          <div class="list-title">${escHtml(g.name)}</div>
          ${g.release_date ? `<div class="list-subtitle">${g.release_date.slice(0,4)}</div>` : ''}
        </td>
        <td><div class="list-platforms">${renderPlatformPills(g.platforms || [])}</div></td>
        <td><span class="status-text ${STATUSES[g.status]?.cls || ''}">${STATUSES[g.status]?.label || g.status}</span></td>
        <td><span class="list-stars">${renderStars(g.rating)}</span></td>
        <td><span class="list-comment" title="${escHtml(g.comment || '')}">${escHtml(g.comment || '')}</span></td>
        <td>
          <div class="list-actions">
            <button class="action-btn edit-btn" data-id="${g.id}" title="Edit">
              <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
              Edit
            </button>
            <button class="action-btn danger del-btn" data-id="${g.id}" title="Delete">
              <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  let html = '';

  if (nowPlaying.length > 0) {
    html += `
      <tr class="now-playing-header-row">
        <td colspan="7">
          <span class="now-playing-dot"></span>
          Now Playing
        </td>
      </tr>
    `;
    html += nowPlaying.map(rowHtml).join('');
    if (rest.length > 0) html += `<tr class="library-divider-row"><td colspan="7"></td></tr>`;
  }

  html += rest.map(rowHtml).join('');

  body.innerHTML = html;

  body.querySelectorAll('.edit-btn').forEach(btn =>
    btn.addEventListener('click', e => { e.stopPropagation(); openEditModal(Number(btn.dataset.id)); })
  );
  body.querySelectorAll('.del-btn').forEach(btn =>
    btn.addEventListener('click', e => { e.stopPropagation(); confirmDelete(Number(btn.dataset.id)); })
  );
  body.querySelectorAll('tr[data-id]').forEach(tr =>
    tr.addEventListener('click', () => openEditModal(Number(tr.dataset.id)))
  );
}

// ── Stats ─────────────────────────────────────────────────────────────────────

async function loadStats() {
  document.getElementById('statsContainer').innerHTML =
    '<div class="loading-spinner"><div class="spinner"></div></div>';
  try {
    const stats = await GET('/api/stats');
    renderStats(stats);
  } catch (e) {
    document.getElementById('statsContainer').innerHTML =
      `<p style="color:var(--s-abandoned);padding:40px">Failed to load stats: ${e.message}</p>`;
  }
}

function renderStats(s) {
  const sc = s.status_counts || {};
  const rc = s.rating_counts || {};
  const pc = s.platform_counts || {};
  const total = s.total || 1; // avoid /0

  const statusOrder = [
    ['currently_playing','Now Playing',   'var(--s-currently-playing)'],
    ['unplayed',        'Unplayed',       'var(--s-unplayed)'],
    ['unfinished',      'Unfinished',     'var(--s-unfinished)'],
    ['completed',       'Completed',      'var(--s-completed)'],
    ['abandoned',       'Abandoned',      'var(--s-abandoned)'],
    ['multiplayer_only','Multiplayer',    'var(--s-multiplayer)'],
    ['cant_complete',   "Can't Complete", 'var(--s-cant-complete)'],
  ];

  const platformOrder = Object.keys(PLATFORMS);

  function pct(n) { return Math.round((n / total) * 100); }
  function bar(n, color) {
    const w = pct(n);
    return `<div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${color}"></div></div>`;
  }
  function starsLabel(n) {
    if (n == 0) return '☆☆☆☆☆ Unrated';
    return '★'.repeat(n) + '☆'.repeat(5 - n) + ` ${n}★`;
  }
  const maxRating = Math.max(1, ...Object.values(rc).map(Number));

  document.getElementById('statsContainer').innerHTML = `
    <h2 class="stats-section-title" style="margin-top:0">Overview</h2>
    <div class="stats-hero">
      <div class="stat-card total">
        <span class="stat-number">${s.total}</span>
        <span class="stat-label">Total Games</span>
      </div>
      <div class="stat-card completed">
        <span class="stat-number">${sc.completed || 0}</span>
        <span class="stat-label">Completed</span>
      </div>
      <div class="stat-card currently-playing">
        <span class="stat-number">${sc.currently_playing || 0}</span>
        <span class="stat-label">Now Playing</span>
      </div>
      <div class="stat-card abandoned">
        <span class="stat-number">${sc.abandoned || 0}</span>
        <span class="stat-label">Abandoned</span>
      </div>
      <div class="stat-card unplayed">
        <span class="stat-number">${sc.unplayed || 0}</span>
        <span class="stat-label">Unplayed</span>
      </div>
      <div class="stat-card rated">
        <span class="stat-number">${s.rated || 0}</span>
        <span class="stat-label">Rated Games</span>
      </div>
      <div class="stat-card hours">
        <span class="stat-number">${s.total_hours || 0}</span>
        <span class="stat-label">Hours Played</span>
      </div>
    </div>

    <div class="stats-charts">
      <div class="stats-panel">
        <h3 class="stats-section-title">Completion Status</h3>
        <div class="bar-chart">
          ${statusOrder.map(([key, label, color]) => {
            const n = sc[key] || 0;
            return n === 0 ? '' : `
              <div class="bar-row">
                <div class="bar-label-row">
                  <span class="bar-label-name">${label}</span>
                  <span class="bar-label-val">${n} &nbsp; <span style="color:var(--text-disabled)">${pct(n)}%</span></span>
                </div>
                ${bar(n, color)}
              </div>`;
          }).join('')}
          ${Object.values(sc).every(v => !v) ? '<p style="color:var(--text-muted);font-size:0.85rem">No data yet</p>' : ''}
        </div>
      </div>

      <div class="stats-panel">
        <h3 class="stats-section-title">Rating Distribution</h3>
        <div class="rating-dist">
          ${[0,1,2,3,4,5].map(n => {
            const count = rc[String(n)] || 0;
            const w = Math.round((count / maxRating) * 100);
            return `
              <div class="rating-row">
                <span class="rating-stars">${starsLabel(n)}</span>
                <div class="rating-bar-wrap">
                  <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:#f59e0b"></div></div>
                </div>
                <span class="rating-count">${count}</span>
              </div>`;
          }).join('')}
        </div>
      </div>
    </div>

    <div class="stats-panel">
      <h3 class="stats-section-title">By Platform</h3>
      <div class="bar-chart" style="max-width:540px">
        ${platformOrder.map(key => {
          const n  = pc[key] || 0;
          const info = PLATFORMS[key];
          const colorMap = { steam:'var(--p-steam)', epic:'var(--p-epic)', ea_origin:'var(--p-ea)', nintendo:'var(--p-nintendo)', sega:'var(--p-sega)', xbox:'var(--p-xbox)', playstation:'var(--p-playstation)', gog:'var(--p-gog)', blizzard:'var(--p-blizzard)', microsoft:'var(--p-microsoft)' };
          return n === 0 ? '' : `
            <div class="bar-row">
              <div class="bar-label-row">
                <span class="bar-label-name"><span class="plat-pill ${info.cls}" style="font-size:.6rem">${info.label}</span></span>
                <span class="bar-label-val">${n}</span>
              </div>
              ${bar(n, colorMap[key] || 'var(--accent)')}
            </div>`;
        }).join('')}
        ${Object.values(pc).every(v => !v) ? '<p style="color:var(--text-muted);font-size:0.85rem">No data yet</p>' : ''}
      </div>
    </div>
  `;
}

// ── Settings ──────────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const s = await GET('/api/settings');
    document.getElementById('steamUrlInput').value         = s.steam_wishlist_url  || '';
    document.getElementById('steamApiKeyInput').value      = s.steam_api_key       || '';
    document.getElementById('igdbClientIdInput').value     = s.igdb_client_id      || '';
    document.getElementById('igdbClientSecretInput').value = s.igdb_client_secret  || '';
    if (s.steam_last_sync) {
      const d  = new Date(s.steam_last_sync + 'Z');
      const ts = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
               + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      document.getElementById('steamSyncStatus').textContent = 'Last synced: ' + ts;
    } else {
      document.getElementById('steamSyncStatus').textContent = '';
    }
  } catch (e) {
    showToast('Failed to load settings: ' + e.message, 'error');
  }
  checkIgdbStatus();
}

const SYNC_ICON = `<svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>`;

async function syncSteamData() {
  const btn    = document.getElementById('syncSteamBtn');
  const status = document.getElementById('steamSyncStatus');
  btn.disabled = true;
  btn.innerHTML = SYNC_ICON + ' Starting…';
  status.textContent = '';
  try {
    const r = await POST('/api/steam/sync', {});
    if (r.error) {
      status.textContent = r.error;
      showToast('Steam sync: ' + r.error, 'error');
    } else {
      status.textContent = 'Syncing in background — this may take a few minutes for large libraries.';
      showToast('Steam sync started.', 'success');
    }
  } catch (e) {
    status.textContent = 'Sync failed: ' + e.message;
    showToast('Steam sync failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = SYNC_ICON + ' Sync Steam Data';
  }
}

async function saveSettings() {
  const steamUrl   = document.getElementById('steamUrlInput').value.trim();
  const steamKey   = document.getElementById('steamApiKeyInput').value.trim();
  const igdbId     = document.getElementById('igdbClientIdInput').value.trim();
  const igdbSecret = document.getElementById('igdbClientSecretInput').value.trim();
  const btn = document.getElementById('saveSettingsBtn');
  btn.disabled    = true;
  btn.textContent = 'Saving…';
  try {
    await PUT('/api/settings', {
      steam_wishlist_url: steamUrl,
      steam_api_key:      steamKey,
      igdb_client_id:     igdbId,
      igdb_client_secret: igdbSecret,
    });
    // Refresh IGDB status (config + live test)
    try {
      const cfg = await GET('/api/config');
      state.igdbConfigured = cfg.igdb_configured;
    } catch (_) {}
    showToast('Settings saved.', 'success');
    checkIgdbStatus();
  } catch (e) {
    showToast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Save Settings';
  }
}

async function checkIgdbStatus(explicit = false) {
  const badge  = document.getElementById('igdbStatusBadge');
  const result = document.getElementById('igdbTestResult');
  badge.className = 'igdb-status-badge checking';
  badge.textContent = 'Checking…';
  if (explicit) result.textContent = '';
  try {
    const s = await GET('/api/igdb/status');
    if (s.connected) {
      badge.className   = 'igdb-status-badge ok';
      badge.textContent = '● Connected';
      if (explicit) result.textContent = 'IGDB is working.';
    } else {
      badge.className   = 'igdb-status-badge error';
      badge.textContent = '● Error';
      if (explicit) result.textContent = s.message;
    }
  } catch (e) {
    badge.className   = 'igdb-status-badge error';
    badge.textContent = '● Error';
    if (explicit) result.textContent = e.message;
  }
}

// ── Wishlist ──────────────────────────────────────────────────────────────────

async function loadWishlist(force = false) {
  document.getElementById('wishlistContainer').innerHTML =
    '<div class="loading-spinner"><div class="spinner"></div></div>';
  document.getElementById('wishlistRefreshTs').textContent = '';
  try {
    const data = await GET('/api/wishlist' + (force ? '?refresh=1' : ''));
    renderWishlist(data);
  } catch (e) {
    document.getElementById('wishlistContainer').innerHTML =
      `<div class="wishlist-error">Failed to load wishlist: ${escHtml(e.message)}</div>`;
  }
}

function renderWishlist(data) {
  const container = document.getElementById('wishlistContainer');

  if (data.error === 'no_url') {
    container.innerHTML = `
      <div class="wishlist-config-prompt">
        <svg viewBox="0 0 48 48" fill="none" width="64" height="64"><circle cx="24" cy="24" r="22" stroke="currentColor" stroke-width="2" opacity=".3"/><path d="M24 14v10l6 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity=".5"/></svg>
        <p>No Steam wishlist URL configured.</p>
        <button class="btn-primary" onclick="switchPage('settings')">Open Settings</button>
      </div>`;
    return;
  }

  if (data.error) {
    container.innerHTML = `<div class="wishlist-error">${escHtml(data.error)}</div>`;
    return;
  }

  if (data.fetched_at) {
    const d   = new Date(data.fetched_at + 'Z');
    const ts  = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
              + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    document.getElementById('wishlistRefreshTs').textContent =
      'Last refreshed: ' + ts + (data.cached ? ' (cached)' : '');
  }

  const games  = data.games || [];
  const owned  = games.filter(g => g.library_match);
  const wanted = games.filter(g => !g.library_match);

  if (games.length === 0) {
    container.innerHTML = `<div class="wishlist-empty">Your Steam wishlist appears to be empty or private.</div>`;
    return;
  }

  let html = '';

  if (owned.length > 0) {
    html += `
      <div class="wishlist-section-header">
        <span class="wishlist-section-title">Already Own <span style="opacity:.6">(${owned.length})</span></span>
        <button class="wishlist-toggle-btn" id="ownedToggleBtn">Hide ▲</button>
      </div>
      <div id="ownedGrid" class="wishlist-grid">
        ${owned.map(g => wishlistCardHtml(g, true, -1)).join('')}
      </div>`;
  }

  if (owned.length > 0 && wanted.length > 0) {
    html += `<div class="library-divider" style="margin: 0 28px"></div>`;
  }

  if (wanted.length > 0) {
    if (owned.length > 0) {
      html += `
        <div class="wishlist-section-header">
          <span class="wishlist-section-title">Want to Play <span style="opacity:.6">(${wanted.length})</span></span>
        </div>`;
    }
    html += `<div class="wishlist-grid">${wanted.map((g, i) => wishlistCardHtml(g, false, i)).join('')}</div>`;
  }

  container.innerHTML = html;

  // Toggle owned section
  const toggleBtn  = document.getElementById('ownedToggleBtn');
  const ownedGrid  = document.getElementById('ownedGrid');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const hidden = ownedGrid.classList.toggle('hidden');
      toggleBtn.textContent = hidden ? 'Show ▼' : 'Hide ▲';
    });
  }

  // Owned cards → open library edit modal
  container.querySelectorAll('.wishlist-card.owned').forEach(card => {
    card.addEventListener('click', () => openEditModal(Number(card.dataset.libId)));
  });

  // Add to Library buttons
  container.querySelectorAll('.btn-add-wishlist').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      addFromWishlist(wanted[Number(btn.dataset.idx)]);
    });
  });
}

function wishlistCardHtml(game, isOwned, idx) {
  const match = game.library_match;

  const coverHtml = game.capsule
    ? `<img class="wishlist-card-cover" src="${escHtml(game.capsule)}" alt="${escHtml(game.name)}" loading="lazy"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
       <div class="wishlist-card-cover-placeholder" style="display:none">No Image</div>`
    : `<div class="wishlist-card-cover-placeholder">No Image</div>`;

  let footer = '';
  if (isOwned && match) {
    footer = `
      <div class="wishlist-own-info">
        ${renderPlatformPills(match.platforms || [])}
        <span class="status-badge ${STATUSES[match.status]?.cls || ''}">
          ${STATUSES[match.status]?.label || match.status}
        </span>
      </div>`;
  } else {
    footer = `<button class="btn-add-wishlist" data-idx="${idx}">+ Add to Library</button>`;
  }

  return `
    <div class="wishlist-card${isOwned ? ' owned' : ''}"
         ${isOwned && match ? `data-lib-id="${match.id}"` : ''}>
      ${coverHtml}
      <div class="wishlist-card-info">
        <div class="wishlist-card-title">${escHtml(game.name)}</div>
        <div class="wishlist-card-meta">
          ${game.price        ? `<span class="wishlist-price">${escHtml(game.price)}</span>` : '<span></span>'}
          ${game.release_date ? `<span>${escHtml(game.release_date)}</span>`                 : ''}
        </div>
        ${footer}
      </div>
    </div>`;
}

async function addFromWishlist(game) {
  openAddModal();
  document.getElementById('formName').value = game.name || '';

  if (game.igdb_id && state.igdbConfigured) {
    try {
      const igdbData = await GET(`/api/igdb/game?id=${game.igdb_id}`);
      fillFromIGDB(igdbData);
    } catch {
      if (game.capsule) applyCoverUrl(game.capsule);
    }
  } else if (game.capsule) {
    applyCoverUrl(game.capsule);
  }
}

// ── Modal: open / close ───────────────────────────────────────────────────────

function openAddModal() {
  state.editingGameId = null;
  clearForm();
  document.getElementById('modalTitle').textContent = 'Add Game';
  hide('deleteGameBtn');
  show('gameModal');
  setupIgdbSection();
  document.getElementById('igdbSearchInput').focus();
}

async function openEditModal(id) {
  try {
    const game = await GET(`/api/games/${id}`);
    state.editingGameId = id;
    clearForm();
    populateForm(game);
    document.getElementById('modalTitle').textContent = 'Edit Game';
    show('deleteGameBtn');
    show('gameModal');
    setupIgdbSection();
  } catch (e) {
    showToast('Failed to load game: ' + e.message, 'error');
  }
}

function closeModal() {
  hide('gameModal');
  state.editingGameId = null;
  hide('igdbResults');
}

function setupIgdbSection() {
  if (state.igdbConfigured) {
    show('igdbSearchWrap');
    hide('igdbDisabledNote');
    document.getElementById('igdbSearchInput').value = '';
    hide('igdbResults');
  } else {
    hide('igdbSearchWrap');
    show('igdbDisabledNote');
  }
}

function clearForm() {
  document.getElementById('formName').value         = '';
  document.getElementById('formReleaseDate').value  = '';
  document.getElementById('formDeveloper').value    = '';
  document.getElementById('formPublisher').value    = '';
  document.getElementById('formSummary').value      = '';
  document.getElementById('formStatus').value       = 'unplayed';
  document.getElementById('formComment').value      = '';
  document.getElementById('formCoverUrl').value     = '';
  document.getElementById('formIgdbId').value       = '';
  document.getElementById('coverUrlInput').value    = '';
  document.getElementById('coverUrlInput').classList.add('hidden');

  const preview = document.getElementById('coverPreview');
  preview.innerHTML = `<svg viewBox="0 0 48 64" fill="none"><rect x="2" y="2" width="44" height="60" rx="4" stroke="currentColor" stroke-width="2" opacity="0.3"/><circle cx="24" cy="28" r="8" stroke="currentColor" stroke-width="2" opacity="0.3"/><path d="M10 46c0-7.732 6.268-14 14-14s14 6.268 14 14" stroke="currentColor" stroke-width="2" opacity="0.3"/></svg><span>No Cover</span>`;

  document.querySelectorAll('input[name="platform"]').forEach(cb => cb.checked = false);
  document.getElementById('steamAppIdWrap').style.display = 'none';
  document.getElementById('formSteamAppId').value         = '';
  document.getElementById('steamAppIdStatus').textContent = '';
  document.getElementById('formHoursPlayed').value        = '';
  hide('steamAchievementsWrap');
  hide('modalSteamLink');

  setRating(0);
  updateCharCount();
  document.getElementById('starPicker').style.opacity      = '1';
  document.getElementById('starPicker').style.pointerEvents = 'auto';
}

function populateForm(game) {
  document.getElementById('formName').value        = game.name || '';
  document.getElementById('formReleaseDate').value = game.release_date || '';
  document.getElementById('formDeveloper').value   = game.developer || '';
  document.getElementById('formPublisher').value   = game.publisher || '';
  document.getElementById('formSummary').value     = game.summary || '';
  document.getElementById('formStatus').value      = game.status || 'unplayed';
  document.getElementById('formComment').value     = game.comment || '';
  document.getElementById('formCoverUrl').value    = game.cover_url || '';
  document.getElementById('formIgdbId').value      = game.igdb_id || '';

  if (game.cover_local_url) {
    document.getElementById('coverPreview').innerHTML =
      `<img src="${game.cover_local_url}" alt="cover" style="width:100%;height:100%;object-fit:cover" />`;
  }

  (game.platforms || []).forEach(p => {
    const cb = document.querySelector(`input[name="platform"][value="${p}"]`);
    if (cb) cb.checked = true;
  });

  const hasSteam = (game.platforms || []).includes('steam');
  document.getElementById('steamAppIdWrap').style.display = hasSteam ? '' : 'none';
  document.getElementById('formSteamAppId').value         = game.steam_app_id || '';
  document.getElementById('steamAppIdStatus').textContent = '';
  document.getElementById('formHoursPlayed').value        = game.hours_played > 0 ? game.hours_played : '';

  const achTotal    = game.achievements_total    || 0;
  const achUnlocked = game.achievements_unlocked || 0;
  if (achTotal > 0) {
    const pct = Math.round((achUnlocked / achTotal) * 100);
    document.getElementById('steamAchievementsDisplay').innerHTML = `
      <div class="achievements-row">
        <span class="ach-count">${achUnlocked} / ${achTotal}</span>
        <div class="ach-bar-track"><div class="ach-bar-fill" style="width:${pct}%"></div></div>
        <span class="ach-pct">${pct}%</span>
      </div>`;
    show('steamAchievementsWrap');
  } else {
    hide('steamAchievementsWrap');
  }

  const steamLink = document.getElementById('modalSteamLink');
  if (game.steam_app_id && hasSteam) {
    steamLink.href = `https://store.steampowered.com/app/${game.steam_app_id}/`;
    show('modalSteamLink');
  } else {
    hide('modalSteamLink');
  }

  const isAbandoned = game.status === 'abandoned';
  setRating(isAbandoned ? 0 : (game.rating || 0));
  document.getElementById('starPicker').style.opacity      = isAbandoned ? '0.3' : '1';
  document.getElementById('starPicker').style.pointerEvents = isAbandoned ? 'none' : 'auto';
  updateCharCount();
}

// ── Cover URL helper ──────────────────────────────────────────────────────────

function toggleCoverUrlInput() {
  const inp = document.getElementById('coverUrlInput');
  inp.classList.toggle('hidden');
  if (!inp.classList.contains('hidden')) {
    inp.value = document.getElementById('formCoverUrl').value || '';
    inp.focus();
  }
}

function applyCoverUrl(url) {
  if (!url) return;
  document.getElementById('formCoverUrl').value = url;
  document.getElementById('coverPreview').innerHTML =
    `<img src="${escHtml(url)}" alt="cover" style="width:100%;height:100%;object-fit:cover"
          onerror="this.parentElement.innerHTML='<span style=color:var(--s-abandoned)>Invalid URL</span>'" />`;
}

// ── Save / delete ─────────────────────────────────────────────────────────────

async function saveGame() {
  const name = document.getElementById('formName').value.trim();
  if (!name) {
    document.getElementById('formName').focus();
    showToast('Game title is required.', 'error');
    return;
  }

  // Duplicate check — only when adding a new game
  if (!state.editingGameId) {
    const nameLower = name.toLowerCase();
    const duplicate = state.allGames.find(g => g.name.toLowerCase() === nameLower);
    if (duplicate) {
      document.getElementById('formName').focus();
      showToast(`"${name}" is already in your Inventory.`, 'warn');
      return;
    }
  }

  const platforms = Array.from(
    document.querySelectorAll('input[name="platform"]:checked')
  ).map(cb => cb.value);

  const status = document.getElementById('formStatus').value;
  const rating = status === 'abandoned' ? 0 : state.currentRating;

  const payload = {
    igdb_id:      document.getElementById('formIgdbId').value || null,
    name,
    release_date: document.getElementById('formReleaseDate').value,
    developer:    document.getElementById('formDeveloper').value.trim(),
    publisher:    document.getElementById('formPublisher').value.trim(),
    summary:      document.getElementById('formSummary').value.trim(),
    cover_url:    document.getElementById('formCoverUrl').value.trim(),
    status,
    rating,
    comment:      document.getElementById('formComment').value.slice(0, 400),
    platforms,
    steam_app_id: document.getElementById('formSteamAppId').value.trim(),
    hours_played: parseFloat(document.getElementById('formHoursPlayed').value) || 0,
  };

  const btn = document.getElementById('saveGameBtn');
  btn.disabled    = true;
  btn.textContent = 'Saving…';

  try {
    if (state.editingGameId) {
      await PUT(`/api/games/${state.editingGameId}`, payload);
      showToast(`"${name}" updated.`, 'success');
    } else {
      await POST('/api/games', payload);
      showToast(`"${name}" added to your library!`, 'success');
    }
    closeModal();
    await loadGames();
  } catch (e) {
    showToast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Save Game';
  }
}

function confirmDelete(id) {
  if (!id) return;
  const game = state.allGames.find(g => g.id === id);
  document.getElementById('confirmGameName').textContent = game ? game.name : 'this game';
  document.getElementById('confirmDeleteBtn').onclick = () => deleteGame(id);
  hide('gameModal');
  show('confirmModal');
}

async function deleteGame(id) {
  hide('confirmModal');
  try {
    await DELETE(`/api/games/${id}`);
    const game = state.allGames.find(g => g.id === id);
    showToast(`"${game?.name || 'Game'}" removed.`, 'success');
    await loadGames();
  } catch (e) {
    showToast('Delete failed: ' + e.message, 'error');
  }
}

// ── IGDB search ───────────────────────────────────────────────────────────────

async function searchIGDB(query) {
  const el = document.getElementById('igdbResults');
  el.innerHTML = '<div style="padding:12px 14px;color:var(--text-muted);font-size:0.85rem">Searching…</div>';
  show('igdbResults');

  try {
    const results = await GET(`/api/igdb/search?q=${encodeURIComponent(query)}`);
    if (!Array.isArray(results) || results.length === 0) {
      el.innerHTML = '<div style="padding:12px 14px;color:var(--text-muted);font-size:0.85rem">No results found.</div>';
      return;
    }
    el.innerHTML = results.map((g, i) => `
      <div class="igdb-result-item" data-idx="${i}">
        ${g.cover_url
          ? `<img class="igdb-result-thumb" src="${g.cover_url}" alt="" loading="lazy" />`
          : `<div class="igdb-result-thumb-placeholder">IMG</div>`
        }
        <div>
          <div class="igdb-result-name">${escHtml(g.name)}</div>
          <div class="igdb-result-year">${g.release_date ? g.release_date.slice(0, 4) : ''}${g.platforms_igdb?.length ? ' · ' + g.platforms_igdb.slice(0, 3).join(', ') : ''}</div>
        </div>
      </div>
    `).join('');

    el.querySelectorAll('.igdb-result-item').forEach(item =>
      item.addEventListener('mousedown', () => fillFromIGDB(results[item.dataset.idx]))
    );
  } catch (e) {
    el.innerHTML = `<div style="padding:12px 14px;color:var(--s-abandoned);font-size:0.85rem">${e.message}</div>`;
  }
}

function fillFromIGDB(g) {
  hide('igdbResults');
  document.getElementById('igdbSearchInput').value = '';

  document.getElementById('formIgdbId').value      = g.igdb_id || '';
  document.getElementById('formName').value        = g.name || '';
  document.getElementById('formReleaseDate').value = g.release_date || '';
  document.getElementById('formDeveloper').value   = g.developer || '';
  document.getElementById('formPublisher').value   = g.publisher || '';
  document.getElementById('formSummary').value     = g.summary || '';

  if (g.cover_url) {
    document.getElementById('formCoverUrl').value = g.cover_url;
    document.getElementById('coverPreview').innerHTML =
      `<img src="${escHtml(g.cover_url)}" alt="cover" style="width:100%;height:100%;object-fit:cover" />`;
  }

  // If Steam is already checked, auto-fetch App ID by the (now-filled) game name
  const steamCb = document.querySelector('input[name="platform"][value="steam"]');
  if (steamCb && steamCb.checked && g.name && !document.getElementById('formSteamAppId').value) {
    fetchAndFillSteamAppId(g.name);
  }

  showToast(`"${g.name}" data imported from IGDB.`, 'success');
}

function onSteamToggle(checked) {
  const wrap = document.getElementById('steamAppIdWrap');
  wrap.style.display = checked ? '' : 'none';
  if (checked) {
    const name    = document.getElementById('formName').value.trim();
    const current = document.getElementById('formSteamAppId').value.trim();
    if (name && !current) fetchAndFillSteamAppId(name);
  }
}

async function fetchAndFillSteamAppId(name) {
  if (!name) return;
  const status = document.getElementById('steamAppIdStatus');
  status.textContent = 'Looking up…';
  try {
    const r = await GET(`/api/steam/find-appid?name=${encodeURIComponent(name)}`);
    if (r.appid) {
      document.getElementById('formSteamAppId').value = r.appid;
      status.textContent = '✓';
      setTimeout(() => { status.textContent = ''; }, 2000);
    } else {
      status.textContent = 'Not found on Steam';
      setTimeout(() => { status.textContent = ''; }, 3000);
    }
  } catch {
    status.textContent = '';
  }
}

// ── Star picker ───────────────────────────────────────────────────────────────

function initStarPicker() {
  const stars = document.querySelectorAll('.star-btn');
  stars.forEach(s => {
    s.addEventListener('click', () => {
      const v = Number(s.dataset.value);
      setRating(v === state.currentRating ? 0 : v); // toggle off if same
    });
    s.addEventListener('mouseenter', () => highlightStars(Number(s.dataset.value)));
    s.addEventListener('mouseleave', () => highlightStars(state.currentRating));
  });
}

function setRating(value) {
  state.currentRating = value;
  document.getElementById('formRating').value = value;
  highlightStars(value);
}

function highlightStars(upTo) {
  document.querySelectorAll('.star-btn').forEach(s => {
    s.classList.toggle('active', Number(s.dataset.value) <= upTo);
  });
}

// ── Render helpers ────────────────────────────────────────────────────────────

function renderStars(rating) {
  let html = '';
  for (let i = 1; i <= 5; i++) {
    html += i <= rating ? '★' : '<span class="empty">★</span>';
  }
  return html;
}

function steamStoreBtn(g) {
  if (!g.steam_app_id || !(g.platforms || []).includes('steam')) return '';
  const url = `https://store.steampowered.com/app/${encodeURIComponent(g.steam_app_id)}/`;
  return `<a class="steam-store-link" href="${url}" target="_blank" rel="noopener"
             title="View on Steam Store" onclick="event.stopPropagation()">
    <svg viewBox="0 0 20 20" fill="currentColor" width="11" height="11">
      <path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z"/>
      <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z"/>
    </svg>
    Steam Store
  </a>`;
}

function renderPlatformPills(platforms) {
  return platforms
    .map(p => {
      const info = PLATFORMS[p];
      if (!info) return '';
      return `<span class="plat-pill ${info.cls}">${info.label}</span>`;
    })
    .join('');
}

// ── Char count ────────────────────────────────────────────────────────────────

function updateCharCount() {
  const len = document.getElementById('formComment').value.length;
  document.getElementById('charCount').textContent = `${len} / 400`;
  document.getElementById('charCount').style.color = len > 380 ? 'var(--s-abandoned)' : '';
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function showToast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const el        = document.createElement('div');
  el.className    = `toast ${type}`;
  el.textContent  = msg;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    el.addEventListener('animationend', () => el.remove());
  }, 3000);
}

// ── Filter dropdowns ──────────────────────────────────────────────────────────

function buildFilterDropdowns() {
  buildDropdown(
    'filterPlatformWrap', 'Platform',
    Object.entries(PLATFORMS).map(([k, v]) => ({ value: k, label: v.label, cls: v.cls })),
    state.filterPlatforms
  );
  buildDropdown(
    'filterStatusWrap', 'Status',
    Object.entries(STATUSES).map(([k, v]) => ({ value: k, label: v.label })),
    state.filterStatuses
  );
  buildDropdown(
    'filterRatingWrap', 'Rating',
    [
      { value: '0', label: '☆ Unrated' },
      { value: '1', label: '★ 1 Star' },
      { value: '2', label: '★★ 2 Stars' },
      { value: '3', label: '★★★ 3 Stars' },
      { value: '4', label: '★★★★ 4 Stars' },
      { value: '5', label: '★★★★★ 5 Stars' },
    ],
    state.filterRatings
  );
}

function buildDropdown(wrapperId, label, options, selectedSet) {
  const wrap  = document.getElementById(wrapperId);
  const count = selectedSet.size;

  wrap.innerHTML = `
    <button class="filter-btn${count > 0 ? ' active' : ''}" data-label="${label}">
      ${count > 0 ? `${label} (${count})` : label}
      <svg viewBox="0 0 20 20" fill="currentColor" width="11" height="11">
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
      </svg>
    </button>
    <div class="filter-panel hidden">
      ${options.map(opt => `
        <label class="filter-panel-item">
          <input type="checkbox" value="${opt.value}" ${selectedSet.has(opt.value) ? 'checked' : ''} />
          ${opt.cls
            ? `<span class="plat-pill ${opt.cls}" style="font-size:.62rem;padding:2px 6px">${opt.label}</span>`
            : `<span>${opt.label}</span>`}
        </label>
      `).join('')}
    </div>
  `;

  const btn   = wrap.querySelector('.filter-btn');
  const panel = wrap.querySelector('.filter-panel');

  btn.addEventListener('click', e => {
    e.stopPropagation();
    document.querySelectorAll('.filter-panel').forEach(p => { if (p !== panel) p.classList.add('hidden'); });
    panel.classList.toggle('hidden');
  });
  panel.addEventListener('click', e => e.stopPropagation());

  wrap.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      if (cb.checked) selectedSet.add(cb.value);
      else            selectedSet.delete(cb.value);
      const n = selectedSet.size;
      btn.classList.toggle('active', n > 0);
      btn.firstChild.textContent = n > 0 ? `${label} (${n}) ` : `${label} `;
      applyFiltersAndRender();
      updateClearFiltersBtn();
    });
  });
}

function updateClearFiltersBtn() {
  const active =
    state.filterPlatforms.size > 0 ||
    state.filterStatuses.size  > 0 ||
    state.filterRatings.size   > 0 ||
    state.hideCompleted;
  document.getElementById('clearFiltersBtn').classList.toggle('hidden', !active);
}

function clearAllFilters() {
  state.filterPlatforms.clear();
  state.filterStatuses.clear();
  state.filterRatings.clear();
  state.hideCompleted = false;
  document.getElementById('hideCompleted').checked = false;
  // Rebuild dropdowns to sync checkbox state
  buildFilterDropdowns();
  document.getElementById('clearFiltersBtn').classList.add('hidden');
  applyFiltersAndRender();
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function show(id) { document.getElementById(id).classList.remove('hidden'); }
function hide(id) { document.getElementById(id).classList.add('hidden'); }

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
