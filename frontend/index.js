  // Column configs per session mode
  const MODE_COLS = {
    RACE:   '36px 44px 90px 44px 90px 80px 100px 110px 76px 60px 60px 60px 60px 60px 60px 70px 80px 100px 80px 130px',
    FP:     '36px 90px 110px 120px 80px 80px 76px 62px 62px 62px 70px 120px',
    QUALI:  '36px 90px 110px 72px 80px 62px 62px 62px 76px 120px',
    SPRINT: '36px 44px 90px 44px 90px 80px 100px 110px 76px 60px 60px 60px 70px 130px',
  };
  const MODE_HEADERS = {
    RACE:   ['POS','Δ','DRIVER','LAP','GAP','INTERVAL','COMPOUND','TYRE AGE','LAST LAP','S1','S2','S3','BST S1','BST S2','BST S3','HISTORY','LEFT','PIT WINDOW','STATUS','TEAM'],
    FP:     ['POS','DRIVER','COMPOUND','TYRE AGE','BEST LAP','LAST LAP','DEG/LAP','S1','S2','S3','HISTORY','TEAM'],
    QUALI:  ['POS','DRIVER','COMPOUND','GAP','BEST LAP','S1','S2','S3','THEORY','TEAM'],
    SPRINT: ['POS','Δ','DRIVER','LAP','GAP','INTERVAL','COMPOUND','TYRE AGE','LAST LAP','S1','S2','S3','STATUS','TEAM'],
  };

  let currentMode = 'RACE';

  function setMode(mode) {
    if (!MODE_COLS[mode]) mode = 'RACE';
    currentMode = mode;
    const cols = MODE_COLS[mode];
    document.documentElement.style.setProperty('--cols', cols);

    // Update header
    const header = document.querySelector('.board-header');
    header.innerHTML = MODE_HEADERS[mode].map(h => `<span>${h}</span>`).join('');

    // Update mode badge
    const badge = document.getElementById('mode-badge');
    badge.textContent = mode;
    badge.className = `mode-${mode}`;

    // Show/hide left panels
    document.getElementById('panel-race-strategy').style.display =
      (mode === 'RACE' || mode === 'SPRINT') ? '' : 'none';
    document.getElementById('panel-fp').style.display =
      mode === 'FP' ? '' : 'none';
    document.getElementById('panel-quali').style.display =
      mode === 'QUALI' ? '' : 'none';
    document.getElementById('panel-inventory').style.display =
      (mode === 'FP' || mode === 'RACE' || mode === 'SPRINT') ? '' : 'none';
    document.getElementById('panel-predict').style.display =
      (mode === 'RACE' || mode === 'SPRINT') ? '' : 'none';

    // Clear row cache when switching modes
    Object.keys(rowMap).forEach(k => { rowMap[k].remove(); delete rowMap[k]; });
    document.getElementById('board-rows').style.height = '0';
  }

  document.documentElement.style.setProperty('--cols', MODE_COLS.RACE);

  let sessionKey = null;
  let countdown = 5;
  let lastData = null;
  let overallBest = { s1: null, s2: null, s3: null };

  const ROW_H = 34; // px — must match padding + line-height
  const MAX_TYRE_LIFE = { SOFT: 25, MEDIUM: 40, HARD: 55, INTERMEDIATE: 30, WET: 40 };

  function loadSession() {
    const val = document.getElementById('session-input').value.trim();
    sessionKey = val ? parseInt(val) : null;
    strategyFetched = false;
    predictLastLap = -1;
    trackNoData = false;
    locEmptyPolls = 0;
    fetchData().then(() => {
      if (currentMode === 'FP' || currentMode === 'QUALI') fetchLeftPanel(currentMode);
      else fetchAndDrawStrategies(true);
    });
  }

  async function fetchData() {
    const url = sessionKey ? `/api/live?session_key=${sessionKey}` : `/api/live`;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      lastData = data;
      computeOverallBest(data.drivers);
      render(data);
      document.getElementById('error-banner').style.display = 'none';
    } catch (e) {
      showError(e.message);
    }
    countdown = 5;
  }

  // Compound colours (match CSS vars)
  const COMPOUND_COLOUR = {
    SOFT: '#e8002d', MEDIUM: '#ffd700', HARD: '#ffffff',
    INTERMEDIATE: '#39b54a', WET: '#0067ff', UNKNOWN: '#555'
  };

  // Live sector state — only used during a live (non-replay, non-historical) session
  let liveSectors = {};
  let isLiveSession = false;  // set true only when session is currently running

  async function fetchSectors() {
    if (replayMode || !isLiveSession) return;
    const url = sessionKey ? `/api/sectors?session_key=${sessionKey}` : `/api/sectors`;
    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      // Empty object = historical session (server signals this)
      if (Object.keys(data).length === 0) { isLiveSession = false; return; }
      liveSectors = data;
      updateSectorCells();
    } catch(e) {}
  }

  async function fetchIntervals() {
    // In replay mode: intervals come from the full state render (already correct per lap)
    // In live mode: poll separately for sub-5s updates
    if (replayMode || !isLiveSession) return;
    const url = sessionKey
      ? `/api/intervals_live?session_key=${sessionKey}`
      : `/api/intervals_live`;
    try {
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      updateIntervalCells(data);
    } catch(e) {}
  }

  // Sector cells: show S1/S2/S3 as they complete, yellow = in progress
  function updateSectorCells() {
    for (const [numStr, sec] of Object.entries(liveSectors)) {
      const row = rowMap[parseInt(numStr)];
      if (!row) continue;
      const s1Cell = row.querySelector('.live-s1');
      const s2Cell = row.querySelector('.live-s2');
      const s3Cell = row.querySelector('.live-s3');
      if (!s1Cell) continue;

      // S1
      if (sec.s1 != null) {
        s1Cell.textContent = sec.s1.toFixed(3);
        s1Cell.style.color = sec.complete || sec.s2 != null ? '' : '#ffd700';
      } else {
        s1Cell.textContent = '…';
        s1Cell.style.color = '#ffd700';
      }
      // S2
      if (s2Cell) {
        if (sec.s2 != null) {
          s2Cell.textContent = sec.s2.toFixed(3);
          s2Cell.style.color = sec.complete || sec.s3 != null ? '' : '#ffd700';
        } else if (sec.s1 != null) {
          s2Cell.textContent = '…';
          s2Cell.style.color = '#ffd700';
        }
      }
      // S3
      if (s3Cell) {
        if (sec.s3 != null) {
          s3Cell.textContent = sec.s3.toFixed(3);
          s3Cell.style.color = sec.complete ? '' : '#ffd700';
        } else if (sec.s2 != null) {
          s3Cell.textContent = '…';
          s3Cell.style.color = '#ffd700';
        }
      }
    }
  }

  // Gap/interval cells: direct patch without full re-render
  function updateIntervalCells(liveData) {
    for (const [numStr, iv] of Object.entries(liveData)) {
      const row = rowMap[parseInt(numStr)];
      if (!row) continue;
      const gapCell = row.querySelector('.live-gap');
      const ivlCell = row.querySelector('.live-ivl');
      if (!gapCell || !ivlCell) continue;

      const gap = iv.gap_to_leader;
      const ivl = iv.interval;

      // Flash yellow briefly to show data changed
      gapCell.style.transition = 'color 0.3s';
      if (typeof gap === 'string' && gap.toUpperCase().includes('LAP')) {
        gapCell.textContent = gap;
        gapCell.style.color = '#aaa';
      } else if (typeof gap === 'number') {
        const newText = gap > 0 ? `+${gap.toFixed(3)}` : 'LEADER';
        if (gapCell.textContent !== newText) {
          gapCell.style.color = '#ffd700';
          gapCell.textContent = newText;
          setTimeout(() => { gapCell.style.color = ''; }, 600);
        }
      }

      if (typeof ivl === 'number' && ivlCell) {
        const newIvl = ivl > 0 ? `+${ivl.toFixed(3)}` : '—';
        if (ivlCell.textContent !== newIvl) {
          ivlCell.style.color = '#ffd700';
          ivlCell.textContent = newIvl;
          setTimeout(() => { ivlCell.style.color = ''; }, 600);
        }
      }
    }
  }

  // Poll every 2s — only fires during live sessions, and only while the tab
  // is actually visible (backgrounded/minimized tabs stop pulling from
  // OpenF1 entirely rather than burning rate-limit budget unwatched).
  setInterval(() => { if (!document.hidden) fetchSectors(); }, 2000);
  setInterval(() => { if (!document.hidden) fetchIntervals(); }, 2000);
  setInterval(() => { if (!document.hidden) fetchLocations(); }, 2000);

  function computeOverallBest(drivers) {
    overallBest = { s1: null, s2: null, s3: null };
    for (const d of drivers) {
      const bs = d.best_sectors;
      if (bs.s1 && (overallBest.s1 === null || bs.s1 < overallBest.s1)) overallBest.s1 = bs.s1;
      if (bs.s2 && (overallBest.s2 === null || bs.s2 < overallBest.s2)) overallBest.s2 = bs.s2;
      if (bs.s3 && (overallBest.s3 === null || bs.s3 < overallBest.s3)) overallBest.s3 = bs.s3;
    }
  }

  function sectorDiv(value, personalBest, overallFastest) {
    if (value == null) return '<div class="sector">—</div>';
    const fmt = value.toFixed(3);
    const isPurple = overallFastest != null && Math.abs(value - overallFastest) < 0.001;
    const isGreen  = !isPurple && personalBest != null && Math.abs(value - personalBest) < 0.001;
    const cls = isPurple ? 'sector sector-best' : isGreen ? 'sector sector-pb' : 'sector';
    return `<div class="${cls}">${fmt}</div>`;
  }

  // driver_number → absolutely-positioned .board-row div
  const rowMap = {};

  function render(data) {
    const s = data.session;
    const up = data.upcoming;
    document.getElementById('session-label').textContent =
      `${s.country_name} — ${s.session_name} (${s.year})` +
      (up ? `  ·  NEXT: ${up.country_name} ${up.session_name} ${(up.date_start || '').slice(5, 16).replace('T', ' ')} UTC` : '');
    document.getElementById('status').textContent = data.drivers.length
      ? `Updated ${new Date().toLocaleTimeString()}`
      : 'Session live — waiting for first timing data…';

    // Determine if this is a live (currently running) session
    if (s.date_end) {
      const endDt = new Date(s.date_end);
      isLiveSession = (Date.now() - endDt.getTime()) < 5 * 60 * 1000;
    }

    // Switch layout if mode changed
    const newMode = data.session_mode || 'RACE';
    if (newMode !== currentMode) {
      setMode(newMode);
      fetchLeftPanel(newMode);
    }

    const container = document.getElementById('board-rows');
    const seen = new Set();

    // Dispatch to mode-specific row builder
    const buildRow = currentMode === 'FP' ? buildFPRow
                   : currentMode === 'QUALI' ? buildQualiRow
                   : buildRaceRow;

    data.drivers.forEach((d, index) => {
      seen.add(d.driver_number);
      const innerHTML = buildRow(d);
      const rowClass  = buildRowClass(d);

      let row = rowMap[d.driver_number];
      if (!row) {
        row = document.createElement('div');
        row.className = 'board-row';
        row.style.transform = `translateY(${index * ROW_H}px)`;
        container.appendChild(row);
        rowMap[d.driver_number] = row;
      }
      row.className = rowClass;
      row.innerHTML = innerHTML;
      row.style.transform = `translateY(${index * ROW_H}px)`;
    });

    // Update container height and remove gone drivers
    container.style.height = `${data.drivers.length * ROW_H}px`;
    for (const num of Object.keys(rowMap)) {
      if (!seen.has(parseInt(num))) {
        rowMap[num].remove();
        delete rowMap[num];
      }
    }

    drawTrackMap(data.drivers, s.session_key);

    // Prediction panel: refetch when the leader's lap changes (max 1/lap)
    if (currentMode === 'RACE' || currentMode === 'SPRINT') {
      const leaderLap = Math.max(...data.drivers.map(d => d.current_lap || 0));
      fetchPredictions(leaderLap);
    }

    // Tyre inventory panel: refetch when the leader's lap changes (max 1/lap)
    if (currentMode === 'RACE' || currentMode === 'SPRINT' || currentMode === 'FP') {
      const leaderLap = Math.max(...data.drivers.map(d => d.current_lap || 0));
      fetchInventory(s.session_key, leaderLap);
    }
  }

  // ── Prediction panel ──────────────────────────────────────────────────────
  let predictLastLap = -1;
  let predictInFlight = false;

  async function fetchPredictions(leaderLap) {
    if (predictInFlight || leaderLap === predictLastLap) return;
    predictInFlight = true;
    try {
      const url = sessionKey
        ? `/api/predict?session_key=${sessionKey}${replayMode ? `&lap=${leaderLap}` : ''}`
        : `/api/predict`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      predictLastLap = leaderLap;
      renderPredictions(data);
    } catch(e) {} finally {
      predictInFlight = false;
    }
  }

  // ── Tyre inventory panel ────────────────────────────────────────────────
  // New sets only ever appear when a driver pits, so gate on lap like predictions.
  let inventoryLastLap = -1;
  let inventoryInFlight = false;

  async function fetchInventory(resolvedSessionKey, leaderLap) {
    if (!resolvedSessionKey || inventoryInFlight || leaderLap === inventoryLastLap) return;
    inventoryInFlight = true;
    try {
      const res = await fetch(`/api/tyre_inventory?session_key=${resolvedSessionKey}`);
      if (!res.ok) return;
      const data = await res.json();
      inventoryLastLap = leaderLap;
      renderInventoryPanel(data);
    } catch(e) {} finally {
      inventoryInFlight = false;
    }
  }

  function renderPredictions(data) {
    // Ensure panel is visible (setMode may not have fired if page loaded in RACE mode)
    document.getElementById('panel-predict').style.display = '';
    const el = document.getElementById('predict-panel');
    const forecasts = data.forecasts || [];
    if (!forecasts.length) {
      el.innerHTML = '<div style="color:var(--muted)">Race finished — no prediction</div>';
      return;
    }

    const scActive = (data.sc_events || []).some(e =>
      e.start_lap <= data.lap && data.lap <= e.end_lap + 1);
    document.getElementById('predict-lap').innerHTML = scActive
      ? `LAP ${data.lap}/${data.total_laps} · <span style="color:var(--medium)">⚠ SC — CHEAP PIT WINDOW</span>`
      : `LAP ${data.lap}/${data.total_laps} · SC ${(data.sc_probability_remaining*100).toFixed(0)}%`;

    let html = '<div class="pred-rows">';
    forecasts.slice(0, 10).forEach(f => {
      const delta = f.current_position - f.predicted_position;
      const deltaHTML = delta > 0 ? `<span class="pred-up">▲${delta}</span>`
                      : delta < 0 ? `<span class="pred-down">▼${-delta}</span>`
                      : `<span class="pred-neu">—</span>`;
      const winPct = (f.win_probability * 100);
      const winHTML = winPct >= 1
        ? `<span class="pred-win">${winPct.toFixed(0)}%</span>`
        : `<span class="pred-win dim">·</span>`;
      const pits = (f.strategy.pits_remaining || []);
      const pitHTML = pits.length
        ? pits.map(p => `<span class="pred-pit ${p.compound}">${p.compound[0]}@${p.lap}</span>`).join(' ')
        : `<span class="pred-stay">stays out</span>`;
      const ucHTML = (f.undercut && f.undercut.viable)
        ? `<div class="pred-uc">⚡ undercut ${f.undercut.target}: ${f.undercut.recommendation}</div>` : '';

      html += `<div class="pred-row">
        <span class="pred-pos">P${f.predicted_position}</span>
        ${deltaHTML}
        <span class="pred-name">${f.acronym}</span>
        ${winHTML}
        <span class="pred-range">P${f.position_range[0]}–${f.position_range[1]}</span>
        <span class="pred-strategy">${pitHTML}</span>
      </div>${ucHTML}`;
    });
    html += '</div>';
    el.innerHTML = html;
  }

  // ── Row class helper ────────────────────────────────────────────────────
  function buildRowClass(d) {
    if (currentMode === 'FP' || currentMode === 'QUALI') return 'board-row';
    const isRetired = d.retired === true;
    const isLapped  = typeof d.gap_to_leader === 'string' && d.gap_to_leader.includes('LAP');
    return 'board-row' + (isRetired ? ' retired' : isLapped ? ' lapped' : '');
  }

  // ── Shared tyre age bar ─────────────────────────────────────────────────
  function tyreAgeBar(compound, age) {
    const maxLife = MAX_TYRE_LIFE[compound] || 40;
    const agePct  = Math.min(100, Math.round((age / maxLife) * 100));
    const ageClass = agePct > 85 ? 'age-crit' : agePct > 65 ? 'age-warn' : '';
    const barColor = COMPOUND_COLOUR[compound] || '#888';
    const wearOpacity = Math.max(0.35, 1 - agePct / 130).toFixed(2);
    return `<div class="age-bar-wrap">
      <span class="${ageClass}">${age}L</span>
      <div class="age-bar"><div class="age-bar-fill" style="width:${agePct}%;background:${barColor};opacity:${wearOpacity}"></div></div>
    </div>`;
  }

  // ── RACE row ────────────────────────────────────────────────────────────
  function buildRaceRow(d) {
    const isRetired = d.retired === true;
    const isLapped  = typeof d.gap_to_leader === 'string' && d.gap_to_leader.includes('LAP');
    const compound  = d.compound || 'UNKNOWN';
    const age       = d.tyre_age ?? 0;
    const colour    = (d.team_colour || 'ffffff').replace('#','');
    const bs        = d.best_sectors || {};
    const partial   = liveSectors[d.driver_number];
    const ls = (partial && !partial.complete)
      ? { s1: partial.s1, s2: partial.s2, s3: partial.s3 }
      : (d.last_sectors || {});
    const historyDots = (d.stints || []).map(st =>
      `<div class="stint-dot ${st.compound}" title="${st.compound} L${st.lap_start}–${st.lap_end ?? '?'}"></div>`
    ).join('');
    const posHTML = isRetired
      ? `<div><span style="color:#e8002d;font-size:9px;letter-spacing:1px">RET</span></div>`
      : `<div class="pos">${d.position ?? '—'}</div>`;
    const delta = d.positions_delta;
    let deltaHTML = '<div class="delta-neu">—</div>';
    if (!isRetired && delta != null) {
      if (delta > 0)      deltaHTML = `<div class="delta-pos">▲${delta}</div>`;
      else if (delta < 0) deltaHTML = `<div class="delta-neg">▼${Math.abs(delta)}</div>`;
      else                deltaHTML = `<div class="delta-neu">●</div>`;
    }
    const gapText  = d.gap_to_leader ?? '—';
    const ivlText  = d.interval ?? '—';
    const gapStyle = isLapped ? 'color:#aaa' : isRetired ? 'color:#e8002d' : '';
    return `
      ${posHTML}${deltaHTML}
      <div class="drv"><span class="team-dot" style="background:#${colour}"></span>${d.acronym}</div>
      <div>${d.current_lap}</div>
      <div class="sector live-gap" style="${gapStyle}">${gapText}</div>
      <div class="sector live-ivl">${isRetired ? '—' : ivlText}</div>
      <div><span class="compound-pill ${compound}">${compound}</span></div>
      <div>${tyreAgeBar(compound, age)}</div>
      <div class="sector">${d.last_lap_time ? formatTime(d.last_lap_time) : '—'}</div>
      <div class="sector live-s1">${ls.s1 != null ? ls.s1.toFixed(3) : '—'}</div>
      <div class="sector live-s2">${ls.s2 != null ? ls.s2.toFixed(3) : '—'}</div>
      <div class="sector live-s3">${ls.s3 != null ? ls.s3.toFixed(3) : '—'}</div>
      <div class="sector">${bs.s1 ? bs.s1.toFixed(3) : '—'}</div>
      <div class="sector">${bs.s2 ? bs.s2.toFixed(3) : '—'}</div>
      <div class="sector">${bs.s3 ? bs.s3.toFixed(3) : '—'}</div>
      <div><div class="stint-history">${historyDots}</div></div>
      <div class="sector">${d.laps_remaining != null ? d.laps_remaining + 'L' : '—'}</div>
      <div class="sector" style="font-size:10px">${d.pit_earliest != null ? 'L'+d.pit_earliest+'–'+d.pit_latest : '—'}</div>
      <div class="status-${d.status || 'OK'}">${d.status || '—'}</div>
      <div style="color:var(--muted);font-size:11px">${d.team}</div>`;
  }

  // ── FP row ──────────────────────────────────────────────────────────────
  function buildFPRow(d) {
    const compound = d.compound || 'UNKNOWN';
    const age      = d.tyre_age ?? 0;
    const colour   = (d.team_colour || 'ffffff').replace('#','');
    const ls       = d.last_sectors || {};
    const bs       = d.best_sectors || {};

    // Compute best and avg from lap_times array — filter out outliers (>110% of best)
    const allLaps = (d.lap_times || []).map(([, t]) => t).filter(t => t < 600);
    const bestLap = allLaps.length ? Math.min(...allLaps) : null;
    const cleanLaps = bestLap ? allLaps.filter(t => t <= bestLap * 1.08) : [];
    const avgLap  = cleanLaps.length > 1
      ? cleanLaps.reduce((a, b) => a + b, 0) / cleanLaps.length
      : null;

    // Current stint laps for avg-on-tyre
    const stint = d.stints && d.stints[d.stints.length - 1];
    const stintLaps = stint
      ? (d.lap_times || []).filter(([l]) => l >= stint.lap_start && (!stint.lap_end || l <= stint.lap_end)).map(([,t]) => t).filter(t => t < 600)
      : [];
    const stintClean = stintLaps.filter(t => t <= (bestLap || 999) * 1.08);
    const stintAvg = stintClean.length > 1
      ? stintClean.reduce((a,b) => a+b, 0) / stintClean.length
      : null;

    const historyDots = (d.stints || []).map(st =>
      `<div class="stint-dot ${st.compound}" title="${st.compound} age ${st.tyre_age_at_start}L"></div>`
    ).join('');

    // Best sectors for S1/S2/S3 in FP
    const s1 = bs.s1 ?? ls.s1;
    const s2 = bs.s2 ?? ls.s2;
    const s3 = bs.s3 ?? ls.s3;

    // DEG rate for current compound
    const driverDeg = fpDegRates[d.driver_number] || {};
    const degRate   = driverDeg[compound];
    let degHTML = '<div class="sector" style="color:var(--muted)">—</div>';
    if (degRate != null) {
      const sign = degRate > 0 ? '+' : '';
      const col  = degRate > 0.15 ? '#e8002d'
                 : degRate > 0.06 ? '#ff6b00'
                 : degRate > 0    ? '#ffd700'
                 : 'var(--green)';  // improving = green
      degHTML = `<div class="sector" style="color:${col}">${sign}${degRate.toFixed(3)}s/L</div>`;
    }

    return `
      <div class="pos">${d.position ?? '—'}</div>
      <div class="drv"><span class="team-dot" style="background:#${colour}"></span>${d.acronym}</div>
      <div><span class="compound-pill ${compound}">${compound}</span></div>
      <div>${tyreAgeBar(compound, age)}</div>
      <div class="sector" style="color:var(--green)">${bestLap ? formatTime(bestLap) : '—'}</div>
      <div class="sector">${d.last_lap_time ? formatTime(d.last_lap_time) : '—'}</div>
      ${degHTML}
      <div class="sector live-s1">${s1 != null ? s1.toFixed(3) : '—'}</div>
      <div class="sector live-s2">${s2 != null ? s2.toFixed(3) : '—'}</div>
      <div class="sector live-s3">${s3 != null ? s3.toFixed(3) : '—'}</div>
      <div><div class="stint-history">${historyDots}</div></div>
      <div style="color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis">${d.team}</div>`;
  }

  // ── QUALI row ───────────────────────────────────────────────────────────
  function buildQualiRow(d) {
    const colour   = (d.team_colour || 'ffffff').replace('#','');
    const compound = d.compound || 'SOFT';
    const bs       = d.best_sectors || {};
    const ls       = d.last_sectors || {};

    // Best lap = minimum clean lap time
    const allLaps = (d.lap_times || []).map(([, t]) => t).filter(t => t < 200 && t > 50);
    const bestLap = allLaps.length ? Math.min(...allLaps) : d.last_lap_time;

    // Gap to leader from the sorted position (position 1 = 0 gap)
    const gap = d.gap_to_leader;
    const gapText = (!gap || gap === 'LEADER') ? '—' : gap;

    // Best S1/S2/S3 (personal bests across all laps)
    const s1 = bs.s1 ?? ls.s1;
    const s2 = bs.s2 ?? ls.s2;
    const s3 = bs.s3 ?? ls.s3;
    const theo = (s1 && s2 && s3) ? (s1 + s2 + s3).toFixed(3) : '—';

    return `
      <div class="pos">${d.position ?? '—'}</div>
      <div class="drv"><span class="team-dot" style="background:#${colour}"></span>${d.acronym}</div>
      <div><span class="compound-pill ${compound}">${compound}</span></div>
      <div class="sector live-gap" style="color:var(--muted)">${gapText}</div>
      <div class="sector" style="color:var(--green)">${bestLap ? formatTime(bestLap) : '—'}</div>
      <div class="sector live-s1">${s1 != null ? s1.toFixed(3) : '—'}</div>
      <div class="sector live-s2">${s2 != null ? s2.toFixed(3) : '—'}</div>
      <div class="sector live-s3">${s3 != null ? s3.toFixed(3) : '—'}</div>
      <div class="sector" style="color:var(--purple)">${theo}</div>
      <div style="color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis">${d.team}</div>`;
  }

  // ── Left panel loader ───────────────────────────────────────────────────
  // FP deg rates keyed by driver_number → compound → rate
  let fpDegRates = {};

  async function fetchLeftPanel(mode) {
    if (!sessionKey) return;
    if (mode === 'FP') {
      try {
        const res = await fetch(`/api/fp_analysis?session_key=${sessionKey}`);
        if (!res.ok) return;
        const data = await res.json();
        // Store deg rates for use in row builder
        fpDegRates = {};
        for (const drv of data.drivers) {
          fpDegRates[drv.driver_number] = drv.deg_rates || {};
        }
        renderFPPanel(data);
      } catch(e) {}
    } else if (mode === 'QUALI') {
      try {
        const res = await fetch(`/api/quali_analysis?session_key=${sessionKey}`);
        if (!res.ok) return;
        renderQualiPanel(await res.json());
      } catch(e) {}
    }
  }

  function renderInventoryPanel(data) {
    document.getElementById('panel-inventory').style.display = '';
    const el = document.getElementById('inventory-panel');
    const sessions = (data.sessions_counted || []).join(' + ');
    el.innerHTML = `<div style="font-size:9px;color:var(--muted);margin-bottom:6px">After: ${sessions}</div>
      <div class="inv-row inv-header">
        <span>DRV</span><span>SOFT</span><span>MED</span><span>HARD</span>
      </div>`;

    // Sort by least soft remaining (most at risk in quali)
    const sorted = [...data.drivers].sort((a,b) =>
      a.inventory.SOFT.remaining - b.inventory.SOFT.remaining
    );

    for (const drv of sorted) {
      const colour = (drv.team_colour || 'ffffff').replace('#','');
      const inv = drv.inventory;

      const dots = (compound, col) => {
        const { remaining, total } = inv[compound];
        let html = '';
        for (let i = 0; i < total; i++) {
          html += `<div class="inv-dot ${i < remaining ? 'new' : 'used'}" style="background:${col}"></div>`;
        }
        return `<div class="inv-dots" title="${remaining}/${total} new ${compound}">${html}</div>`;
      };

      // Flag shortage warnings
      const softLeft = inv.SOFT.remaining;
      const softStyle = softLeft <= 4 ? 'color:#e8002d;font-weight:700' : softLeft <= 5 ? 'color:#ff6b00' : '';

      el.innerHTML += `<div class="inv-row">
        <span class="drv" style="font-size:10px">
          <span class="team-dot" style="background:#${colour}"></span>${drv.acronym}
        </span>
        <span style="${softStyle}">${dots('SOFT', '#e8002d')}</span>
        ${dots('MEDIUM', '#ffd700')}
        ${dots('HARD', '#cccccc')}
      </div>`;
    }
  }

  function renderFPPanel(data) {
    const el = document.getElementById('fp-panel');
    el.innerHTML = '';

    for (const drv of data.drivers) {
      const colour = (drv.team_colour || 'ffffff').replace('#','');
      const degByCompound = drv.deg_rates || {};
      let html = `<div class="fp-driver">
        <div class="fp-driver-header">
          <span class="team-dot" style="background:#${colour.replace('#','')}"></span>
          <span class="fp-driver-name">${drv.acronym}</span>
        </div>`;

      for (const cs of (drv.compound_summaries || [])) {
        const deg = degByCompound[cs.compound];
        const degStr = deg != null
          ? `<span style="color:${deg>0.1?'#e8002d':deg>0.05?'#ff6b00':deg>0?'#ffd700':'var(--green)'}"> ${deg>0?'+':''}${deg.toFixed(3)}s/L</span>`
          : '';

        html += `<div style="padding:3px 0 3px 8px;border-bottom:1px solid #1e1e1e">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
            <span class="compound-pill ${cs.compound}" style="font-size:8px">${cs.compound}</span>
            ${degStr}
          </div>`;

        if (cs.hotlap_count > 0) {
          const best = cs.best_hotlap ? formatTime(cs.best_hotlap) : '—';
          html += `<div class="fp-stint">
            <span style="color:#9b00ff;font-size:8px;letter-spacing:1px">HOTLAP ×${cs.hotlap_count}</span>
            <span style="color:var(--green)">${best}</span>
          </div>`;
        }

        for (const stint of (cs.short_runs || [])) {
          if (!stint.best_lap) continue;
          html += `<div class="fp-stint">
            <span style="color:var(--muted);font-size:8px">SHORT ${stint.timed_laps}L</span>
            <span>${formatTime(stint.best_lap)}</span>
            ${stint.avg_pace ? `<span style="color:var(--muted);font-size:9px">${formatTime(stint.avg_pace)} avg</span>` : ''}
          </div>`;
        }

        for (const stint of (cs.long_runs || [])) {
          if (!stint.best_lap) continue;
          html += `<div class="fp-stint">
            <span style="color:#ff6b00;font-size:8px;letter-spacing:1px">RACE SIM ${stint.timed_laps}L</span>
            <span>${formatTime(stint.best_lap)}</span>
            ${stint.avg_pace ? `<span style="color:var(--muted);font-size:9px">${formatTime(stint.avg_pace)} avg</span>` : ''}
          </div>`;
        }

        html += `</div>`;
      }

      html += `</div>`;
      el.innerHTML += html;
    }
  }

  function renderQualiPanel(data) {
    const el = document.getElementById('quali-panel');
    el.innerHTML = `<div class="quali-row quali-header">
      <span>POS</span><span>DRV</span><span>BEST</span><span>GAP</span><span>THEORY</span><span>CMP</span>
    </div>`;
    for (const drv of data.drivers) {
      const colour = (drv.team_colour || 'ffffff').replace('#','');
      const best = drv.best_lap ? formatTime(drv.best_lap) : '—';
      const gap  = drv.gap_to_p1 ? `+${drv.gap_to_p1.toFixed(3)}` : 'P1';
      const theo = drv.theoretical_best ? formatTime(drv.theoretical_best) : '—';
      el.innerHTML += `<div class="quali-row">
        <span class="q-pos">${drv.position}</span>
        <span class="drv" style="font-size:11px"><span class="team-dot" style="background:#${colour.replace('#','')}"></span>${drv.acronym}</span>
        <span class="q-best">${best}</span>
        <span class="q-gap">${gap}</span>
        <span class="q-theo">${theo}</span>
        <span><span class="compound-pill ${drv.best_compound || 'SOFT'}" style="font-size:8px">${(drv.best_compound || 'S')[0]}</span></span>
      </div>`;
    }
  }

  // Track outline is fixed for the whole session — fetch once, cache the
  // transform, and reuse it for both the backdrop and the live dots so cars
  // don't jitter/rescale every refresh.
  let trackLayoutSessionKey = undefined;
  let trackLayoutPoints = null;   // [{x,y}, ...] or [] if unavailable
  let trackToCanvas = null;       // (x, y) => [cx, cy]

  function computeTrackTransform(points, W, H, pad) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of points) {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
    }
    const scaleX = (W - pad*2) / (maxX - minX || 1);
    const scaleY = (H - pad*2) / (maxY - minY || 1);
    const scale  = Math.min(scaleX, scaleY);
    return (x, y) => [
      pad + (x - minX) * scale,
      H - pad - (y - minY) * scale,   // flip Y
    ];
  }

  async function fetchTrackLayout(resolvedSessionKey) {
    if (trackLayoutSessionKey === resolvedSessionKey && trackLayoutPoints !== null) return;
    trackLayoutSessionKey = resolvedSessionKey;
    try {
      const url = `/api/track_layout?session_key=${resolvedSessionKey}`;
      const res = await fetch(url);
      const data = res.ok ? await res.json() : { points: [] };
      trackLayoutPoints = data.points || [];
      if (trackLayoutPoints.length >= 10) {
        const canvas = document.getElementById('track-canvas');
        trackToCanvas = computeTrackTransform(trackLayoutPoints, canvas.width, canvas.height, 16);
      } else {
        trackToCanvas = null;
      }
    } catch (e) {
      trackLayoutPoints = [];
      trackToCanvas = null;
    }
  }

  // ── track map: interpolated dots ─────────────────────────────────────────
  // Positions arrive in bursts (full /api/live every 5s, light /api/locations
  // every 2s during live sessions). Dots don't jump to each new fix — a
  // requestAnimationFrame loop eases them toward their latest target, so
  // movement reads as continuous motion instead of teleporting.
  const trackDots = {};      // driver_number → {x, y, tx, ty, colour, acronym}
  let trackNoData = false;   // true once we conclude positions won't arrive (stop "Fetching…")
  let locEmptyPolls = 0;     // consecutive empty /api/locations responses
  let lastDotFrame = 0;

  function setDotTargets(list) {
    const seen = new Set();
    for (const d of list) {
      if (d.track_x == null || d.track_y == null) continue;
      if (!d.track_x && !d.track_y) continue;   // (0,0) = no telemetry yet
      seen.add(d.driver_number);
      let dot = trackDots[d.driver_number];
      if (!dot) {
        dot = trackDots[d.driver_number] = {
          x: d.track_x, y: d.track_y,
          colour: '#' + (d.team_colour || 'ffffff').replace('#', ''),
          acronym: d.acronym || '',
        };
      }
      dot.tx = d.track_x; dot.ty = d.track_y;
      if (d.team_colour) dot.colour = '#' + String(d.team_colour).replace('#', '');
      if (d.acronym) dot.acronym = d.acronym;
    }
    return seen;
  }

  function drawTrackMap(drivers, resolvedSessionKey) {
    fetchTrackLayout(resolvedSessionKey);   // fire-and-forget; uses cached result once loaded
    // Full update: refresh targets + metadata, prune retired/vanished drivers
    const seen = setDotTargets(drivers.filter(d => !d.retired));
    for (const k of Object.keys(trackDots)) {
      if (!seen.has(parseInt(k))) delete trackDots[k];
    }
    paintTrack(1);   // hidden/backgrounded tabs still get a fresh static frame
  }

  async function fetchLocations() {
    if (replayMode) return;   // finished sessions still expose a final snapshot
    try {
      const url = sessionKey ? `/api/locations?session_key=${sessionKey}` : '/api/locations';
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const locs = data.locations || [];
      if (!locs.length) {
        // No positions. Give it a short grace period, then conclude they won't
        // arrive so paintTrack stops resetting the label to "Fetching…" every
        // frame. Live sessions only expose position over MQTT (not this REST
        // feed), so a live race legitimately gets no dots here.
        if (!Object.keys(trackDots).length && ++locEmptyPolls >= 3) trackNoData = true;
        return;
      }
      locEmptyPolls = 0;
      trackNoData = false;
      setDotTargets(locs.map(l => ({
        driver_number: l.driver_number, track_x: l.x, track_y: l.y,
      })));
    } catch (e) { /* transient — next poll retries */ }
  }

  function paintTrack(k) {
    // k = easing factor for this paint: 1 snaps dots straight to target,
    // fractional values (from the animation loop) glide them
    const canvas = document.getElementById('track-canvas');
    const loadingEl = document.getElementById('track-loading');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height, PAD = 16;

    const dots = Object.values(trackDots);
    if (!dots.length) {
      if (loadingEl) loadingEl.textContent = trackNoData
        ? (isLiveSession ? 'Live track map unavailable (positions not published)'
                         : 'No track-position data for this session')
        : 'Fetching positions…';
      return;
    }

    for (const d of dots) {
      d.x += (d.tx - d.x) * k;
      d.y += (d.ty - d.y) * k;
    }

    // Fall back to a bounding box over current targets if the fixed track
    // outline isn't ready yet (fewer than 3 laps completed so far)
    const toCanvas = trackToCanvas || computeTrackTransform(
      dots.map(d => ({ x: d.tx, y: d.ty })), W, H, PAD);
    if (loadingEl) {
      loadingEl.textContent = trackToCanvas
        ? `${dots.length} drivers located`
        : `${dots.length} drivers located (outline pending)`;
    }

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, W, H);

    if (trackToCanvas && trackLayoutPoints && trackLayoutPoints.length >= 10) {
      ctx.beginPath();
      trackLayoutPoints.forEach((p, i) => {
        const [cx, cy] = trackToCanvas(p.x, p.y);
        if (i === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
      });
      ctx.closePath();
      ctx.strokeStyle = '#444';
      ctx.lineWidth = 3;
      ctx.stroke();
    }

    for (const d of dots) {
      const [cx, cy] = toCanvas(d.x, d.y);
      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.fillStyle = d.colour;
      ctx.fill();
      ctx.font = 'bold 7px Courier New';
      ctx.fillStyle = '#ffffff';
      ctx.fillText(d.acronym, cx + 7, cy + 3);
    }
  }

  function renderTrackFrame(ts) {
    requestAnimationFrame(renderTrackFrame);
    if (document.hidden) return;   // rAF pauses in background; data updates still snap-paint
    const dt = Math.min(0.1, Math.max(0.001, (ts - lastDotFrame) / 1000));
    lastDotFrame = ts;
    paintTrack(Math.min(1, dt * 2.5));   // ease ~92% of the way in ~1s
  }
  requestAnimationFrame(renderTrackFrame);

  // ── Strategy chart ──────────────────────────────────────────────────────
  // Strategies are fixed at race start — only fetch once per session load
  let strategySessionKey = null;
  let strategyFetched = false;

  async function fetchAndDrawStrategies(forceRefetch = false) {
    if (!forceRefetch && strategyFetched && strategySessionKey === sessionKey) return;

    // For replay, use lap 1 as the basis (strategy set at race start)
    const lap = 5; // use lap 5 — past safety car / formation lap chaos
    const url = sessionKey
      ? `/api/strategies?session_key=${sessionKey}&lap=${lap}`
      : `/api/strategies?lap=${lap}`;
    try {
      const res = await fetch(url);
      if (!res.ok) return;             // leave unfetched so a later poll retries
      const data = await res.json();
      drawStrategyChart(data);
      // only lock in once we've actually drawn — a transient failure must retry
      strategyFetched = true;
      strategySessionKey = sessionKey;
    } catch(e) { /* transient — allow retry */ }
  }

  function drawStrategyChart(data) {
    const canvas = document.getElementById('strategy-canvas');
    const strats = data.strategies || [];
    if (!strats.length) {
      canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
      document.getElementById('strategy-ref').textContent = 'No strategy data for this session';
      return;
    }

    const totalLaps = data.total_laps || 70;
    const currentLap = data.lap || 0;
    const ROW = 34, PAD_L = 52, PAD_R = 8, PAD_T = 8, PAD_B = 24;
    const W = canvas.width;
    const H = PAD_T + strats.length * ROW + PAD_B;
    canvas.height = H;
    canvas.style.height = H + 'px';

    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, W, H);

    const chartW = W - PAD_L - PAD_R;
    const lapToX = lap => PAD_L + ((lap - 1) / (totalLaps - 1)) * chartW;
    const nowX = lapToX(Math.max(1, currentLap));

    // Draw lap axis ticks
    ctx.fillStyle = '#444';
    ctx.font = '8px Courier New';
    ctx.fillStyle = '#555';
    for (let l = 10; l <= totalLaps; l += 10) {
      const x = lapToX(l);
      ctx.fillStyle = '#333';
      ctx.fillRect(x, PAD_T, 1, strats.length * ROW);
      ctx.fillStyle = '#555';
      ctx.fillText(l, x - 4, H - 8);
    }

    // Draw current lap line
    if (currentLap > 0) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(nowX, PAD_T);
      ctx.lineTo(nowX, PAD_T + strats.length * ROW);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Draw each strategy
    strats.forEach((s, i) => {
      const y = PAD_T + i * ROW;

      // Label
      ctx.fillStyle = '#888';
      ctx.font = '8px Courier New';
      ctx.fillText(`S${i+1}`, 2, y + ROW/2 + 3);

      // Stop count badge
      ctx.fillStyle = '#333';
      ctx.fillText(`${s.stop_count}✦`, 16, y + ROW/2 + 3);

      // Draw stints
      s.stints.forEach(stint => {
        const x1 = Math.max(PAD_L, lapToX(stint.start_lap));
        const x2 = Math.min(W - PAD_R, lapToX(stint.end_lap + 1));
        const bw = Math.max(1, x2 - x1 - 1);
        const bh = ROW - 6;
        const by = y + 3;

        const col = COMPOUND_COLOUR[stint.compound] || '#666';
        ctx.fillStyle = col;
        ctx.globalAlpha = 0.85;
        ctx.fillRect(x1, by, bw, bh);
        ctx.globalAlpha = 1;

        // Compound initial label inside bar
        if (bw > 14) {
          ctx.fillStyle = ['#ffffff','#ffd700'].includes(col) ? '#000' : '#fff';
          ctx.font = 'bold 8px Courier New';
          ctx.fillText(stint.compound[0], x1 + 3, by + bh/2 + 3);
        }

        // Lap range label
        if (bw > 28) {
          ctx.fillStyle = ['#ffffff','#ffd700'].includes(col) ? '#000' : '#fff';
          ctx.font = '7px Courier New';
          ctx.fillText(`${stint.start_lap}-${stint.end_lap}`, x1 + 11, by + bh/2 + 3);
        }
      });

      // Pit stop markers
      for (let j = 1; j < s.stints.length; j++) {
        const pitLap = s.stints[j].start_lap;
        const px = lapToX(pitLap);
        ctx.fillStyle = '#00d246';
        ctx.fillRect(px - 1, y + 2, 3, ROW - 4);
      }
    });

    // Legend
    const legendItems = [['SOFT','#e8002d'],['MEDIUM','#ffd700'],['HARD','#ffffff'],['PIT','#00d246']];
    let lx = PAD_L;
    legendItems.forEach(([label, col]) => {
      ctx.fillStyle = col;
      ctx.fillRect(lx, H - 10, 8, 6);
      ctx.fillStyle = '#666';
      ctx.font = '7px Courier New';
      ctx.fillText(label, lx + 10, H - 5);
      lx += label.length * 5 + 18;
    });

    // Reference driver
    document.getElementById('strategy-ref').textContent =
      data.reference_driver ? `Based on: ${data.reference_driver}` : '';
  }

  function formatTime(secs) {
    const m = Math.floor(secs / 60);
    const s = (secs % 60).toFixed(3).padStart(6, '0');
    return m > 0 ? `${m}:${s}` : `${s}s`;
  }

  function showError(msg) {
    const el = document.getElementById('error-banner');
    el.textContent = `Error: ${msg}`;
    el.style.display = 'block';
    document.getElementById('status').textContent = 'Failed to fetch';
  }

  // ── Live mode auto-refresh ──────────────────────────────────────────────
  setInterval(() => {
    if (replayMode || document.hidden) return;   // paused in background — resumed below on refocus
    countdown--;
    document.getElementById('countdown').textContent = countdown;
    if (countdown <= 0) {
      countdown = 5;
      fetchData().then(() => {
        // retry the (once-only) strategy draw until it lands — self-gates once drawn
        if (currentMode !== 'FP' && currentMode !== 'QUALI') fetchAndDrawStrategies();
      });
    }
  }, 1000);

  // Refresh immediately on refocus rather than waiting out the rest of a
  // stale countdown — a tab backgrounded for 10 minutes shouldn't show data
  // that's 10 minutes old for another 5 seconds after you look back at it.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !replayMode) {
      countdown = 5;
      fetchData();
    }
  });

  // ── Replay mode ─────────────────────────────────────────────────────────
  let replayMode  = false;
  let replayLap   = 1;
  let replayMax   = 70;
  let replayTimer = null;
  let replayPlaying = false;

  function toggleReplayMode() {
    replayMode = !replayMode;
    const bar = document.getElementById('replay-bar');
    const btn = document.getElementById('replay-mode-btn');
    const liveLabel = document.getElementById('auto-label');
    if (replayMode) {
      // need a session key to replay
      const val = document.getElementById('session-input').value.trim();
      if (!val) {
        alert('Enter a session key first, then click REPLAY.');
        replayMode = false;
        return;
      }
      sessionKey = parseInt(val);
      bar.classList.add('active');
      btn.textContent = '✕ EXIT REPLAY';
      liveLabel.style.opacity = '0.3';
      initReplay();
    } else {
      stopReplay();
      bar.classList.remove('active');
      btn.textContent = 'REPLAY';
      liveLabel.style.opacity = '1';
      fetchData();
    }
  }

  async function initReplay() {
    document.getElementById('replay-status').textContent = 'Loading…';
    try {
      const res = await fetch(`/api/session/total_laps?session_key=${sessionKey}`);
      const d = await res.json();
      replayMax = d.total_laps || 70;
      replayLap = 1;
      const slider = document.getElementById('lap-slider');
      slider.max = replayMax;
      slider.value = 1;
      document.getElementById('lap-max').textContent = `/ ${replayMax}`;
      document.getElementById('replay-status').textContent = 'Ready';
      strategyFetched = false;
      fetchAndDrawStrategies(true); // fixed at race start
      await fetchReplayLap(replayLap);
    } catch(e) {
      document.getElementById('replay-status').textContent = `Error: ${e.message}`;
    }
  }

  async function fetchReplayLap(lap) {
    document.getElementById('lap-display').textContent = `LAP ${lap}`;
    document.getElementById('lap-slider').value = lap;
    document.getElementById('replay-status').textContent = `Lap ${lap} / ${replayMax}${replayPlaying ? ' ▶' : ''}`;
    try {
      const res = await fetch(`/api/replay?session_key=${sessionKey}&lap=${lap}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      computeOverallBest(data.drivers);
      render(data);
      document.getElementById('error-banner').style.display = 'none';
      return data;
    } catch(e) {
      showError(e.message);
      stopReplay();
      return null;
    }
  }

  function togglePlay() {
    replayPlaying ? stopReplay() : startReplay();
  }

  function startReplay() {
    replayPlaying = true;
    document.getElementById('play-btn').textContent = '⏸ PAUSE';
    advanceReplay();
  }

  function stopReplay() {
    replayPlaying = false;
    document.getElementById('play-btn').textContent = '▶ PLAY';
    if (replayTimer) { clearTimeout(replayTimer); replayTimer = null; }
  }

  let lastReplayData = null;

  async function advanceReplay() {
    if (!replayPlaying) return;
    if (replayLap >= replayMax) { stopReplay(); return; }
    replayLap++;
    lastReplayData = await fetchReplayLap(replayLap);
    if (replayPlaying) {
      const speedVal = document.getElementById('replay-speed').value;
      let ms;
      if (speedVal === 'real') {
        // Use the leader's actual lap time for this lap (in ms)
        ms = getLeaderLapMs(lastReplayData, replayLap);
      } else {
        ms = parseInt(speedVal);
      }
      replayTimer = setTimeout(advanceReplay, ms);
    }
  }

  function getLeaderLapMs(data, lap) {
    if (!data || !data.drivers) return 90000; // fallback 90s
    // Leader = first driver in sorted list that isn't retired
    const leader = data.drivers.find(d => !d.retired);
    if (!leader) return 90000;
    const entry = (leader.lap_times || []).find(([l]) => l === lap);
    if (!entry) return 90000;
    return Math.round(entry[1] * 1000); // seconds → ms
  }

  function stepLap(delta) {
    stopReplay();
    replayLap = Math.max(1, Math.min(replayMax, replayLap + delta));
    fetchReplayLap(replayLap);
  }

  function onSlider(val) {
    stopReplay();
    replayLap = parseInt(val);
    fetchReplayLap(replayLap);
  }

  fetchData();
  fetchAndDrawStrategies();
