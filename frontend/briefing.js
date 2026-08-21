  const COMPOUNDS = ["SOFT", "MEDIUM", "HARD"];
  let currentBriefing = null;
  let editorState = null;   // { driver_number, acronym, stints: [{compound, lap_start, lap_end}], totalLaps }
  let whatifTimer = null;
  let whatifSeq = 0;
  // Customize-panel open/closed — not persisted, just resets to collapsed on
  // page load. Separate per page type since recap and prerace have different
  // section sets and are toggled independently.
  let customizeOpen = { recap: false, prerace: false };

  // ── race list ──────────────────────────────────────────────────────────────
  async function loadRaces() {
    try {
      const [racesRes, nextRes] = await Promise.all([
        fetch('/api/races?year=2026'),
        fetch('/api/next_meeting?year=2026'),
      ]);
      const data = await racesRes.json();
      const next = (await nextRes.json()).meeting;
      const el = document.getElementById('race-items');
      el.classList.remove('spin');
      el.innerHTML = '';
      if (next) {
        const div = document.createElement('div');
        div.className = 'race-item';
        div.style.borderLeft = '3px solid var(--green)';
        div.innerHTML = `<span class="name">${next.country_name}</span>
          <span class="kind" style="color:var(--green)">UPCOMING · PRE-RACE</span>`;
        div.onclick = () => { markActive(div); loadPrerace(next.meeting_key); };
        el.appendChild(div);
      }
      for (const r of data.races) {
        const div = document.createElement('div');
        div.className = 'race-item';
        const kind = r.session_name === 'Sprint' ? 'SPRINT' : 'RACE';
        div.innerHTML = `<span class="name">${r.country_name}</span>
          <span class="kind">${kind} · ${(r.date_start || '').slice(5, 10)}</span>`;
        div.onclick = () => { markActive(div); loadBriefing(r.session_key, r.meeting_key); };
        el.appendChild(div);
      }
      if (!data.races.length && !next) el.textContent = 'No races yet.';
    } catch (e) {
      document.getElementById('race-items').textContent = 'Failed to load races.';
    }
  }

  function markActive(itemEl) {
    document.querySelectorAll('.race-item').forEach(e => e.classList.remove('active'));
    itemEl.classList.add('active');
  }

  // ── briefing ───────────────────────────────────────────────────────────────
  let currentContext = null;   // { sessionKey, meetingKey } for the toggle

  async function loadBriefing(sessionKey, meetingKey) {
    const root = document.getElementById('briefing');
    root.innerHTML = '<div class="card spin" id="loading-overlay">Building briefing… (first load per race can take ~30s while the narrative is written)</div>';
    editorState = null;
    currentContext = { sessionKey, meetingKey };
    try {
      const res = await fetch(`/api/briefing?session_key=${sessionKey}`);
      if (!res.ok) throw new Error((await res.json()).detail || res.status);
      currentBriefing = await res.json();
      renderBriefing(currentBriefing);
    } catch (e) {
      root.innerHTML = `<div class="card"><span class="notice">Briefing failed: ${e.message}</span></div>`;
    }
  }

  function toggleHTML(active) {
    const ctx = currentContext || {};
    if (!ctx.meetingKey) return '';
    return `<div class="btnrow" style="margin-top:8px">
      <button id="tab-debrief" ${active === 'debrief' ? 'style="border-color:var(--red);color:var(--red)"' : ''} ${ctx.sessionKey ? '' : 'disabled'}>DEBRIEF</button>
      <button id="tab-prerace" ${active === 'prerace' ? 'style="border-color:var(--red);color:var(--red)"' : ''}>PRE-RACE</button>
    </div>`;
  }

  function wireToggle(rootEl) {
    const d = rootEl.querySelector('#tab-debrief');
    const p = rootEl.querySelector('#tab-prerace');
    const ctx = currentContext || {};
    if (d && ctx.sessionKey) d.onclick = () => loadBriefing(ctx.sessionKey, ctx.meetingKey);
    if (p && ctx.meetingKey) p.onclick = () => loadPrerace(ctx.meetingKey, ctx.sessionKey);
  }

  // ── customizable section layout (per-browser, via localStorage) ───────────
  // Each briefing's optional/content cards can be shown/hidden and reordered.
  // The header and (for the recap page) the results table + what-if editor
  // stay fixed — the editor is wired directly to specific driver rows in that
  // table, so pulling them apart or hiding either would break the click-to-
  // open interaction. Layout choices are saved on this browser only; there's
  // no account system in this app to sync them across devices.
  function loadLayout(key) {
    try { return JSON.parse(localStorage.getItem('briefingLayout:' + key)) || {}; }
    catch { return {}; }
  }

  function saveLayout(key, layout) {
    localStorage.setItem('briefingLayout:' + key, JSON.stringify(layout));
  }

  // sections: [{id, title, node}] in default order. Returns the subset that
  // isn't hidden, reordered per the saved layout — unknown/removed ids are
  // dropped and any new ids not yet in a saved order are appended at the end.
  function applyLayout(key, sections) {
    const layout = loadLayout(key);
    const hidden = new Set(layout.hidden || []);
    const known = new Set(sections.map(sec => sec.id));
    const order = (layout.order || []).filter(id => known.has(id));
    for (const sec of sections) if (!order.includes(sec.id)) order.push(sec.id);
    const byId = Object.fromEntries(sections.map(sec => [sec.id, sec]));
    return order.map(id => byId[id]).filter(sec => !hidden.has(sec.id));
  }

  function renderCustomizePanel(root, key, sections, rerender) {
    const layout = loadLayout(key);
    const hidden = new Set(layout.hidden || []);
    const order = (layout.order || []).filter(id => sections.some(sec => sec.id === id));
    for (const sec of sections) if (!order.includes(sec.id)) order.push(sec.id);

    const wrap = document.createElement('div');
    wrap.className = 'card';

    function persist() { saveLayout(key, { order, hidden: [...hidden] }); }

    function paint() {
      const rows = order.map((id, i) => {
        const sec = sections.find(s => s.id === id);
        return `<div class="layout-row" data-id="${id}">
          <label><input type="checkbox" ${hidden.has(id) ? '' : 'checked'}> ${sec.title}</label>
          <span class="layout-controls">
            <button class="mv-up" ${i === 0 ? 'disabled' : ''} title="move up">▲</button>
            <button class="mv-down" ${i === order.length - 1 ? 'disabled' : ''} title="move down">▼</button>
          </span>
        </div>`;
      }).join('');
      wrap.innerHTML = `<h2>Customize this layout</h2>
        <div class="meta-row"><span>show/hide and reorder sections — saved on this browser only</span></div>
        <div id="layout-rows">${rows}</div>
        <div class="btnrow"><button id="layout-reset">reset to default</button></div>`;

      wrap.querySelectorAll('.layout-row').forEach(row => {
        const id = row.dataset.id;
        row.querySelector('input').onchange = e => {
          if (e.target.checked) hidden.delete(id); else hidden.add(id);
          persist(); rerender();
        };
        row.querySelector('.mv-up').onclick = () => {
          const i = order.indexOf(id);
          if (i > 0) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; persist(); paint(); rerender(); }
        };
        row.querySelector('.mv-down').onclick = () => {
          const i = order.indexOf(id);
          if (i < order.length - 1) { [order[i + 1], order[i]] = [order[i], order[i + 1]]; persist(); paint(); rerender(); }
        };
      });
      wrap.querySelector('#layout-reset').onclick = () => {
        localStorage.removeItem('briefingLayout:' + key);
        rerender();
      };
    }
    paint();
    root.appendChild(wrap);
  }

  function renderBriefing(b) {
    const d = b.data, n = b.narrative, s = d.session, st = d.stats;
    const root = document.getElementById('briefing');
    root.innerHTML = '';

    // header card
    const head = document.createElement('div');
    head.className = 'card';
    const weather = d.weather && d.weather.track_temp_avg
      ? `track ${d.weather.track_temp_avg}°C · air ${d.weather.air_temp_avg}°C${d.weather.rainfall ? ' · RAIN' : ''}` : '';
    head.innerHTML = `
      <h3>${n ? n.headline : (s.country_name + ' — ' + s.session_name)}</h3>
      <div class="meta-row">
        <span>${s.country_name} · ${s.circuit}</span><span>${(s.date_start || '').slice(0, 10)}</span>
        <span>${s.total_laps} laps</span><span>${weather}</span>
        <span>pit loss ${d.pit_loss}s</span><span>SC: ${st.sc_count}${st.vsc_count ? ' · VSC: ' + st.vsc_count : ''}</span>
      </div>
      ${n ? '' : '<div class="notice">Narrative unavailable (no API key configured) — showing data-only briefing.</div>'}
      ${toggleHTML('debrief')}
      <div class="btnrow" style="margin-top:8px"><button id="btn-customize">⚙ CUSTOMIZE LAYOUT</button></div>`;
    root.appendChild(head);
    wireToggle(head);
    head.querySelector('#btn-customize').onclick = () => {
      customizeOpen.recap = !customizeOpen.recap;
      renderBriefing(b);
    };

    // results + stint bars — fixed, not part of the customizable layout: the
    // what-if editor right below is wired directly to these rows' onclick.
    const resCard = document.createElement('div');
    resCard.className = 'card';
    let rows = '';
    for (const r of d.results) {
      const delta = r.positions_delta;
      const dTxt = delta == null ? '—'
        : delta > 0 ? `<span class="delta-up">▲${delta}</span>`
        : delta < 0 ? `<span class="delta-down">▼${-delta}</span>` : '·';
      rows += `<tr class="clickable" data-driver="${r.driver_number}">
        <td>${r.retired ? 'DNF' : (r.position ?? '—')}</td>
        <td><b>${r.acronym}</b></td>
        <td>${r.grid_position ?? '—'}</td><td>${dTxt}</td><td>${r.stops}</td>
        <td>${stintBarHTML(r.stints, s.total_laps)}</td></tr>`;
    }
    resCard.innerHTML = `<h2>Classification & strategy — click a driver to open the what-if editor</h2>
      <table class="results">
        <tr><th>POS</th><th>DRV</th><th>GRID</th><th>Δ</th><th>STOPS</th><th>STINTS</th></tr>${rows}
      </table>`;
    root.appendChild(resCard);
    resCard.querySelectorAll('tr.clickable').forEach(tr => {
      tr.onclick = () => openEditor(parseInt(tr.dataset.driver), tr);
    });

    // what-if editor placeholder
    const ed = document.createElement('div');
    ed.className = 'card';
    ed.id = 'editor-card';
    ed.innerHTML = `<h2>What-if stint simulator</h2>
      <div class="notice">Pick a driver above, then drag the pit-stop boundaries or click a stint to change compound. The race is re-simulated with everyone else on their actual strategy.</div>`;
    root.appendChild(ed);

    // ── customizable sections below (order/visibility saved per-browser) ───
    const sections = [];

    if (n) {
      sections.push({ id: 'race-story', title: 'The race', node: proseCard('The race', n.race_story) });
    }
    if (n) {
      sections.push({ id: 'tyre-story', title: 'The tyres', node: proseCard('The tyres', n.tyre_story) });
    }
    sections.push({ id: 'deg-curves', title: 'Tyre degradation model', node: degCurveCard(d.deg_curves) });

    // Race in charts — RSS-style panels, fetched separately so they never block
    // or bloat the LLM briefing pack. Fetch is skipped below if this section
    // ends up hidden — no point pulling chart data nobody will see.
    const rcCard = document.createElement('div');
    rcCard.className = 'card';
    rcCard.id = 'race-charts-card';
    rcCard.innerHTML = '<h2>The race in charts</h2>'
      + '<div id="race-charts-body"><span class="notice spin">building race charts…</span></div>';
    sections.push({ id: 'race-charts', title: 'The race in charts', node: rcCard });

    // stint pace — the "which tyre was a rock" read
    if (d.stint_pace && d.stint_pace.field && d.stint_pace.field.length) {
      const sp = d.stint_pace;
      const spCard = document.createElement('div');
      spCard.className = 'card';
      let fRows = sp.field.map(f =>
        `<tr><td><b>${f.compound}</b></td><td>${f.new_set ? 'new' : 'used'}</td>
         <td>${f.median_slope.toFixed(3)} s/lap${Math.abs(f.median_slope) <= sp.fuel_evo_band ? ' <span class="delta-up">flat</span>' : ''}</td>
         <td>${f.stint_count}</td></tr>`).join('');
      const flat = sp.stints.filter(r => r.clean_laps >= 8).slice(0, 5);
      let bRows = flat.map(r =>
        `<tr><td><b>${r.acronym}</b></td><td>${r.compound}${r.new_set ? '' : ' (used)'}</td>
         <td>L${r.laps[0]}–${r.laps[1]}</td><td>${r.median.toFixed(3)}</td>
         <td>${r.slope.toFixed(3)}${r.flat ? ' <span class="delta-up">flat</span>' : ''}</td></tr>`).join('');
      spCard.innerHTML = `<h2>Stint pace — fuel-corrected deg slopes</h2>
        <div class="meta-row"><span>slope = s/lap of tyre age with fuel burn removed · inside ±${sp.fuel_evo_band}s/lap counts as flat (fuel+evolution band)</span></div>
        <table class="results" style="margin-bottom:12px">
          <tr><th>COMPOUND</th><th>SET</th><th>FIELD MEDIAN SLOPE</th><th>STINTS</th></tr>${fRows}</table>
        <div class="meta-row"><span>best-managed long stints (≥8 clean laps)</span></div>
        <table class="results">
          <tr><th>DRV</th><th>TYRE</th><th>LAPS</th><th>MEDIAN</th><th>SLOPE</th></tr>${bRows}</table>`;
      sections.push({ id: 'stint-pace', title: 'Stint pace — fuel-corrected deg slopes', node: spCard });
    }

    // the stops, graded
    if (d.stops_graded && d.stops_graded.length) {
      const sg = d.stops_graded;
      const gCard = document.createElement('div');
      gCard.className = 'card';
      const gradeColor = g => g === 'inspired' || g === 'good' ? 'var(--green)'
        : g === 'neutral' ? 'var(--muted)' : 'var(--red)';
      const row = s =>
        `<tr><td><b>${s.acronym}</b></td><td>L${s.lap}</td>
         <td>${s.from} → ${s.to}</td><td>${s.old_tyre_age}</td>
         <td>${s.neutralised || ''}</td>
         <td>${s.gain_s > 0 ? '+' : ''}${s.gain_s.toFixed(1)}s</td>
         <td style="color:${gradeColor(s.grade)}"><b>${s.grade.toUpperCase()}</b></td></tr>`;
      const best = sg.slice(0, 5), worst = sg.slice(-5).reverse();
      gCard.innerHTML = `<h2>The stops, graded</h2>
        <div class="meta-row"><span>each stop judged over the next ${5} laps: fresh-rubber gain vs staying out on the old set · SC stops bank the discounted pit lane</span></div>
        <div class="meta-row"><span>best calls</span></div>
        <table class="results" style="margin-bottom:12px"><tr><th>DRV</th><th>LAP</th><th>CHANGE</th><th>AGE</th><th></th><th>GAIN</th><th>GRADE</th></tr>${best.map(row).join('')}</table>
        <div class="meta-row"><span>worst calls</span></div>
        <table class="results"><tr><th>DRV</th><th>LAP</th><th>CHANGE</th><th>AGE</th><th></th><th>GAIN</th><th>GRADE</th></tr>${worst.map(row).join('')}</table>`;
      sections.push({ id: 'stops-graded', title: 'The stops, graded', node: gCard });
    }
    if (n && n.the_stops) {
      sections.push({ id: 'stops-story', title: 'The stops (narrative)', node: proseCard('The stops', n.the_stops) });
    }

    if (n) {
      sections.push({ id: 'strategy-verdicts', title: 'Strategy verdicts', node: proseCard('Strategy verdicts', n.strategy_verdicts) });
    }

    // prior check — grade the race-morning briefing against the result
    const sc = d.prerace_scorecard;
    if (sc) {
      const scCard = document.createElement('div');
      scCard.className = 'card';
      const win = sc.winner, pod = sc.podium, mv = sc.mover_calls;
      const yn = ok => ok ? '<span class="delta-up">✓</span>' : '<span class="delta-down">✗</span>';
      const moverRows = (mv.detail || []).map(x =>
        `<tr><td><b>${x.acronym}</b></td><td>P${x.grid} → P${x.finish}</td>
          <td>called ${x.called}</td><td>${yn(x.correct)}</td></tr>`).join('');
      scCard.innerHTML = `<h2>Prior check — how the race-morning call held up</h2>
        <div class="meta-row"><span>the lap-0 projection graded against the result · lower MAE = sharper</span></div>
        <div class="meta-row" style="margin-top:6px">
          <span>projection error: <b>${sc.projection_mae}</b> positions (MAE, ${sc.drivers_scored} cars)</span>
          <span>winner: ${win.projected} → ${win.actual} ${yn(win.hit)}</span>
          <span>podium: ${pod.hits}/3 (${pod.projected.join('·')} → ${pod.actual.join('·')})</span>
          <span>door/mover calls: ${mv.correct}/${mv.total}</span>
        </div>
        ${moverRows ? `<table class="results" style="margin-top:8px"><tr><th>DRV</th><th>GRID→FIN</th><th>CALL</th><th></th></tr>${moverRows}</table>` : ''}`;
      sections.push({ id: 'prior-check', title: 'Prior check — race-morning call', node: scCard });
    }
    if (n && n.prior_check) {
      sections.push({ id: 'prior-check-story', title: 'Prior check (narrative)', node: proseCard('Prior check', n.prior_check) });
    }

    if (customizeOpen.recap) {
      renderCustomizePanel(root, 'recap', sections, () => renderBriefing(b));
    }

    const filtered = applyLayout('recap', sections);
    for (const sec of filtered) root.appendChild(sec.node);

    if (filtered.some(sec => sec.id === 'race-charts') && currentContext && currentContext.sessionKey) {
      loadRaceCharts(currentContext.sessionKey);
    }
  }

  function proseCard(title, text) {
    const c = document.createElement('div');
    c.className = 'card';
    c.innerHTML = `<h2>${title}</h2><div class="prose">${escapeHTML(text)}</div>`;
    return c;
  }

  function escapeHTML(t) {
    return (t || '').replace(/[&<>]/g, m => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[m]));
  }

  function stintBarHTML(stints, totalLaps) {
    let inner = '';
    for (const st of stints) {
      const w = ((st.lap_end - st.lap_start + 1) / totalLaps * 100).toFixed(1);
      inner += `<div class="c-${st.compound}" style="width:${w}%" title="${st.compound} L${st.lap_start}-${st.lap_end}"></div>`;
    }
    return `<div class="stintbar">${inner}</div>`;
  }

  // ── race simulation pace — by team ───────────────────────────────────────
  function teamPaceCard(teamPace) {
    const c = document.createElement('div');
    c.className = 'card';
    if (!teamPace || !teamPace.length) {
      c.innerHTML = '<h2>Race simulation pace — by team</h2><div class="notice">Not enough long-run data yet.</div>';
      return c;
    }
    const MAX_BAR_PX = 420;
    const maxGap = Math.max(...teamPace.map(t => t.gap_s), 0.01);
    const rows = teamPace.map(t => {
      const w = Math.round(t.gap_s / maxGap * MAX_BAR_PX);
      const label = `+${t.gap_s.toFixed(2)}s (${t.gap_pct.toFixed(2)}%)`;
      return `<div class="pace-row">
        <span class="pace-team">${t.team}</span>
        <div class="pace-track">
          <div class="pace-bar" style="width:${w}px;background:#${(t.team_colour || '888888').replace('#', '')}"></div>
          <span class="pace-label">${label}</span>
        </div>
      </div>`;
    }).join('');
    c.innerHTML = `<h2>Race simulation pace — by team</h2>
      <div class="meta-row"><span>fuel- &amp; age-corrected long-run pace, quicker of each team's two cars · gap to the fastest team</span></div>
      <div class="pace-chart">${rows}</div>`;
    return c;
  }

  // ── expected pit stop strategies & windows (Gantt) ───────────────────────
  const LIVE_MARGIN_S_DISPLAY = 10;   // mirrors engine.prerace.LIVE_MARGIN_S — display only

  function pitStrategyGanttCard(strategies, totalLaps) {
    const c = document.createElement('div');
    c.className = 'card';
    if (!strategies || !strategies.length) {
      c.innerHTML = '<h2>Expected pit stop strategies &amp; windows</h2><div class="notice">No viable strategy found.</div>';
      return c;
    }
    const ticks = [];
    for (let l = 10; l < totalLaps; l += 10) ticks.push(l);
    const tickHTML = ticks.map(l =>
      `<span class="gantt-tick" style="left:${(l / totalLaps * 100).toFixed(2)}%">${l}</span>`).join('');
    const rows = strategies.map(s => {
      const segs = [];
      let cursor = 0;
      for (let i = 0; i < s.compound_sequence.length; i++) {
        const isLast = i === s.compound_sequence.length - 1;
        const win = !isLast ? s.pit_windows[i] : null;
        const stintEnd = isLast ? totalLaps : win[0];
        segs.push({ type: 'c-' + s.compound_sequence[i], start: cursor, end: stintEnd, label: '' });
        cursor = stintEnd;
        if (win) {
          segs.push({ type: 'gantt-window', start: win[0], end: win[1],
                     label: `${win[0]}<span>${win[1]}</span>` });
          cursor = win[1];
        }
      }
      const segHTML = segs.map(seg => {
        const left = (seg.start / totalLaps * 100).toFixed(2);
        const width = ((seg.end - seg.start) / totalLaps * 100).toFixed(2);
        return `<div class="gantt-seg ${seg.type}" style="left:${left}%;width:${width}%">${seg.label}</div>`;
      }).join('');
      return `<div class="gantt-row-label">Strategy ${s.stops}-stop</div>
        <div class="gantt-row">${segHTML}</div>`;
    }).join('');
    c.innerHTML = `<h2>Expected pit stop strategies &amp; windows</h2>
      <div class="meta-row"><span>each row is the best plan at that stop count · green = pit window, the range of laps that stays within ${LIVE_MARGIN_S_DISPLAY}s of the optimal stop</span></div>
      <div class="gantt-chart">${rows}<div class="gantt-axis">${tickHTML}</div></div>`;
    return c;
  }

  // ── tyres available for race ──────────────────────────────────────────────
  const TYRE_AVAIL_COLOUR = {
    SOFT:   { new: '#e8002d', used: '#f28ca0' },
    MEDIUM: { new: '#ffd700', used: '#fff3b0' },
    HARD:   { new: '#ffffff', used: '#9a9a9a' },
  };
  const TYRE_AVAIL_TEXT = { SOFT_new: '#fff' };   // everything else reads fine in black

  function tyreAvailabilityCard(grid) {
    const c = document.createElement('div');
    c.className = 'card';
    const rows = grid.filter(g => g.tyres);
    if (!rows.length) {
      c.innerHTML = '<h2>Tyres available for race</h2><div class="notice">No tyre inventory data yet.</div>';
      return c;
    }
    const PX_PER_SET = 22;
    const bodyRows = rows.map(g => {
      let segs = '';
      for (const compound of ['SOFT', 'MEDIUM', 'HARD']) {
        for (const cond of ['new', 'used']) {
          const n = g.tyres[compound][cond];
          if (!n) continue;
          const bg = TYRE_AVAIL_COLOUR[compound][cond];
          const fg = TYRE_AVAIL_TEXT[compound + '_' + cond] || '#000';
          segs += `<div class="tyre-seg" style="width:${n * PX_PER_SET}px;background:${bg};color:${fg}"
                    title="${compound} (${cond}): ${n}">${n}</div>`;
        }
      }
      return `<div class="tyre-row">
        <span class="tyre-driver">${g.acronym}</span>
        <div class="tyre-track">${segs}</div>
      </div>`;
    }).join('');
    c.innerHTML = `<h2>Tyres available for race</h2>
      <div class="meta-row"><span>new = never fitted this weekend · used = already fitted at least once, assumed still holdable (OpenF1 has no per-set ID, so a scrubbed set can't be told apart from a discarded one)</span></div>
      <div class="tyre-chart">${bodyRows}</div>
      <div class="tyre-legend">
        <span><i style="background:${TYRE_AVAIL_COLOUR.SOFT.new}"></i>SN</span>
        <span><i style="background:${TYRE_AVAIL_COLOUR.SOFT.used}"></i>SU</span>
        <span><i style="background:${TYRE_AVAIL_COLOUR.MEDIUM.new}"></i>MN</span>
        <span><i style="background:${TYRE_AVAIL_COLOUR.MEDIUM.used}"></i>MU</span>
        <span><i style="background:${TYRE_AVAIL_COLOUR.HARD.new}"></i>HN</span>
        <span><i style="background:${TYRE_AVAIL_COLOUR.HARD.used}"></i>HU</span>
      </div>`;
    return c;
  }

  // ── pre-race briefing ──────────────────────────────────────────────────────
  async function loadPrerace(meetingKey, sessionKey) {
    const root = document.getElementById('briefing');
    root.innerHTML = '<div class="card spin" id="loading-overlay">Building race-morning briefing… (first load can take ~30s while the narrative is written)</div>';
    editorState = null;
    currentContext = { sessionKey: sessionKey || null, meetingKey };
    try {
      const res = await fetch(`/api/prerace_briefing?meeting_key=${meetingKey}`);
      if (!res.ok) throw new Error((await res.json()).detail || res.status);
      renderPrerace(await res.json());
    } catch (e) {
      root.innerHTML = `<div class="card"><span class="notice">Pre-race briefing failed: ${e.message}</span></div>`;
    }
  }

  function renderPrerace(b) {
    const d = b.data, n = b.narrative, m = d.meeting;
    const root = document.getElementById('briefing');
    root.innerHTML = '';

    const inv = d.inventory;
    const head = document.createElement('div');
    head.className = 'card';
    head.innerHTML = `
      <h3>${n ? n.headline : (m.country_name + ' — Race Morning Briefing')}</h3>
      <div class="meta-row">
        <span>${m.country_name} · ${m.circuit}${m.sprint_weekend ? ' · SPRINT WEEKEND' : ''}</span>
        <span>race: ${(m.race_date || 'TBC').slice(0, 10)}</span>
        <span>${m.total_laps_assumed} laps assumed</span>
        <span>SC probability ${(d.sc_probability * 100).toFixed(0)}%</span>
        <span>pit loss ${d.pit_loss}s (${d.pit_loss_source === 'sprint_measured' ? 'measured in sprint' : 'default'})</span>
      </div>
      <div class="meta-row"><span>built from: ${d.sources.map(s => s.name).join(' · ')}</span></div>
      ${n ? '' : '<div class="notice">Narrative unavailable (no API key configured) — showing data-only briefing.</div>'}
      ${toggleHTML('prerace')}
      <div class="btnrow" style="margin-top:8px"><button id="btn-customize">⚙ CUSTOMIZE LAYOUT</button></div>`;
    root.appendChild(head);
    wireToggle(head);
    head.querySelector('#btn-customize').onclick = () => {
      customizeOpen.prerace = !customizeOpen.prerace;
      renderPrerace(b);
    };

    // ── customizable sections (order/visibility saved per-browser) ─────────
    const sections = [];

    // grid
    const gridCard = document.createElement('div');
    gridCard.className = 'card';
    let gRows = '';
    for (const g of d.grid) {
      gRows += `<tr><td>${g.position}</td><td><b>${g.acronym}</b></td>
        <td>${g.team || ''}</td><td>${g.gap ?? ''}</td></tr>`;
    }
    gridCard.innerHTML = `<h2>The grid — from ${d.grid_source}</h2>
      <table class="results"><tr><th>POS</th><th>DRV</th><th>TEAM</th><th>GAP</th></tr>${gRows}</table>`;
    sections.push({ id: 'grid', title: 'The grid', node: gridCard });
    if (n) sections.push({ id: 'grid-story', title: 'Reading the grid (narrative)', node: proseCard('Reading the grid', n.grid_story) });

    // the real pace order — long runs vs grid slots
    if (d.long_run_pace && d.long_run_pace.length) {
      const pCard = document.createElement('div');
      pCard.className = 'card';
      let pRows = d.long_run_pace.slice(0, 10).map(r => {
        const oop = r.out_of_position;
        const badge = oop == null ? '—'
          : oop > 0 ? `<span class="delta-up">▲${oop} vs grid</span>`
          : oop < 0 ? `<span class="delta-down">▼${-oop} vs grid</span>` : '·';
        return `<tr><td>${r.pace_rank}</td><td><b>${r.acronym}</b></td>
          <td>${r.pace_delta > 0 ? '+' : ''}${r.pace_delta.toFixed(3)}</td>
          <td>${r.grid_position ?? '—'}</td><td>${badge}</td>
          <td>${r.laps} laps · ${r.sessions.join('+')}</td></tr>`;
      }).join('');
      pCard.innerHTML = `<h2>The real pace order — long runs, fuel &amp; age corrected</h2>
        <div class="meta-row"><span>s/lap vs field median · ▲ = quicker than their grid slot suggests (attacker) · ▼ = grid slot better than race pace (vulnerable)</span></div>
        <table class="results"><tr><th>RANK</th><th>DRV</th><th>PACE</th><th>GRID</th><th>OUT OF POSITION</th><th>SAMPLE</th></tr>${pRows}</table>`;
      sections.push({ id: 'pace-order', title: 'The real pace order', node: pCard });
    }

    if (d.team_pace && d.team_pace.length) {
      sections.push({ id: 'team-pace', title: 'Race simulation pace — by team',
                     node: teamPaceCard(d.team_pace) });
    }

    // long-run boards — one per practice/sprint session, grouped as one
    // toggleable/reorderable section since they're all views of the same data.
    {
      const group = document.createElement('div');
      group.style.cssText = 'display:flex;flex-direction:column;gap:12px';
      for (const tb of (d.long_run_tables || [])) {
        if (!tb.drivers.length) continue;
        const maxLaps = Math.max(...tb.drivers.map(r => r.laps.length));
        const minute = Math.floor(Math.min(...tb.drivers.map(r => r.avg)) / 60);
        const strip = t => {
          const m = Math.floor(t / 60);
          const rest = (t - m * 60).toFixed(3).padStart(6, '0');
          return m === minute ? rest : `${m}:${rest}`;   // minute shown only when it differs
        };
        const lrCard = document.createElement('div');
        lrCard.className = 'card';
        let head2 = tb.drivers.map(r =>
          `<th style="background:#${r.team_colour.replace('#','')};color:#000;padding:3px 6px">${r.acronym} (${r.compound})</th>`).join('');
        let body = '';
        for (let i = 0; i < maxLaps; i++) {
          body += '<tr>' + tb.drivers.map(r => {
            const c = r.laps[i];
            if (!c) return '<td style="background:#161616"></td>';
            return c.x ? '<td style="color:var(--muted);text-align:center">X</td>'
                       : `<td style="text-align:center">${strip(c.t)}</td>`;
          }).join('') + '</tr>';
        }
        const avgRow = tb.drivers.map(r =>
          `<td style="color:var(--green);font-weight:700;text-align:center">${strip(r.avg)}</td>`).join('');
        lrCard.innerHTML = `<h2>Long runs — ${tb.session_name}</h2>
          <div class="meta-row"><span>each driver's longest run · times shown without the ${minute}-minute prefix · X = out-lap, traffic spike (>5% over run median) or track-wide yellow — excluded from the average</span></div>
          <div style="overflow-x:auto"><table class="results" style="min-width:${tb.drivers.length * 74}px">
            <tr>${head2}</tr>${body}
            <tr><td colspan="${tb.drivers.length}" style="text-align:center;color:var(--green);font-weight:700;border-top:1px solid var(--border)">AVERAGE STINT PACE</td></tr>
            <tr>${avgRow}</tr>
          </table></div>`;
        group.appendChild(lrCard);
      }
      if (group.children.length) {
        sections.push({ id: 'long-run-tables', title: 'Long runs (practice/sprint)', node: group });
      }
    }

    // where the lap lives — quali sectors & top speed
    if (d.quali_sectors && d.quali_sectors.length) {
      const qs = d.quali_sectors;
      const bests = {
        s1: Math.min(...qs.filter(r => r.s1).map(r => r.s1)),
        s2: Math.min(...qs.filter(r => r.s2).map(r => r.s2)),
        s3: Math.min(...qs.filter(r => r.s3).map(r => r.s3)),
        sp: Math.max(...qs.filter(r => r.top_speed_kmh).map(r => r.top_speed_kmh)),
      };
      const cell = (v, best, fmt) => v == null ? '<td>—</td>'
        : `<td${v === best ? ' style="color:#b57bff;font-weight:bold"' : ''}>${fmt(v)}</td>`;
      const sCard = document.createElement('div');
      sCard.className = 'card';
      let sRows = qs.map(r =>
        `<tr><td><b>${r.acronym}</b></td><td>${r.best_lap.toFixed(3)}</td>
         ${cell(r.s1, bests.s1, v => v.toFixed(3))}${cell(r.s2, bests.s2, v => v.toFixed(3))}${cell(r.s3, bests.s3, v => v.toFixed(3))}
         <td>${r.theoretical ? r.theoretical.toFixed(3) : '—'}</td>
         <td>${r.left_on_table ? '+' + r.left_on_table.toFixed(3) : '—'}</td>
         ${cell(r.top_speed_kmh, bests.sp, v => v + ' km/h')}</tr>`).join('');
      sCard.innerHTML = `<h2>Where the lap lives — qualifying sectors</h2>
        <div class="meta-row"><span>purple = field best · "left on table" = best lap minus theoretical best</span></div>
        <table class="results"><tr><th>DRV</th><th>BEST</th><th>S1</th><th>S2</th><th>S3</th><th>THEORY</th><th>LEFT</th><th>TRAP</th></tr>${sRows}</table>`;
      sections.push({ id: 'quali-sectors', title: 'Where the lap lives — qualifying sectors', node: sCard });
    }

    // the trade, calculated
    const t = d.trade;
    const tradeCard = document.createElement('div');
    tradeCard.className = 'card';
    let pairRows = '';
    for (const p of t.pairs) {
      pairRows += `<tr><td><b>${p.softer}</b> vs <b>${p.harder}</b></td>
        <td>${p.offset_s_per_lap.toFixed(2)}</td><td>${p.deg_gap_s_per_lap.toFixed(3)}</td>
        <td>${p.breakeven_stint_laps ?? '—'}</td><td>${p.verdict}</td></tr>`;
    }
    let lut = '<tr><th>laps to flag</th>' +
      t.lookup_table.offsets.map(o => `<th>offset ${o.toFixed(2)}</th>`).join('') + '</tr>';
    t.lookup_table.laps_to_flag.forEach((nLaps, i) => {
      lut += `<tr><td>N = ${nLaps}</td>` +
        t.lookup_table.thresholds[i].map(v => `<td>${v.toFixed(3)}</td>`).join('') + '</tr>';
    });
    tradeCard.innerHTML = `<h2>The trade, calculated</h2>
      <div class="meta-row"><span>${t.formula}</span></div>
      <table class="results" style="margin-bottom:12px">
        <tr><th>PAIR</th><th>OFFSET s/lap</th><th>DEG GAP s/lap</th><th>BREAK-EVEN</th><th>VERDICT</th></tr>
        ${pairRows}</table>
      <div class="meta-row"><span>max tolerable deg gap (s/lap) = 2 × offset / N</span></div>
      <table class="cmp-table" style="border:1px solid var(--border)">${lut}</table>`;
    sections.push({ id: 'trade', title: 'The trade, calculated', node: tradeCard });
    if (n) sections.push({ id: 'trade-story', title: 'The trade (narrative)', node: proseCard('The trade', n.the_trade) });

    // paper strategies
    const stratCard = document.createElement('div');
    stratCard.className = 'card';
    let sRows = '';
    for (const s of d.strategies) {
      const stints = [];
      let lap = 0;
      s.compound_sequence.forEach((c, i) => {
        stints.push({ compound: c, lap_start: lap + 1, lap_end: lap + s.stint_lengths[i] });
        lap += s.stint_lengths[i];
      });
      // A forced 1/2/3-stop sweep always yields three plans, so say which are
      // genuinely on the table rather than listing a fantasy 3-stopper as a peer.
      const via = s.viability || 'in play';
      const dim = via === 'not on the table';
      const tag = via === 'in play' ? ''
        : via === 'needs a Safety Car'
          ? ` <span style="color:#ffd700">· needs a Safety Car${s.sc_refund_s ? ' (worth ~' + s.sc_refund_s + 's)' : ''}</span>`
          : ` <span style="color:#777">· not on the table</span>`;
      sRows += `<tr${dim ? ' style="opacity:0.5"' : ''}><td><b>${s.compound_sequence.join('-')}</b></td><td>${s.stops}</td>
        <td>${s.pit_laps.map(l => 'L' + l).join(', ') || '—'}</td>
        <td>${stintBarHTML(stints, m.total_laps_assumed)}</td>
        <td>${s.time_delta === 0 ? 'fastest on paper' : '+' + s.time_delta + 's'}${tag}</td></tr>`;
    }
    const sd = d.stop_decision, xo = sd && sd.crossover;
    stratCard.innerHTML = `<h2>The strategies on paper — the candidates</h2>
      <table class="results"><tr><th>PLAN</th><th>STOPS</th><th>PITS</th><th>SHAPE</th><th>Δ</th></tr>${sRows}</table>
      ${sd ? `<div class="meta-row" style="margin-top:8px"><span><b>${sd.optimal_stops}-stop optimal.</b>${xo && xo.runner_stops ? ` A ${xo.runner_stops}-stop's extra pit stop costs <b>${xo.extra_pit_cost_s}s</b> but its fresher rubber only claws back <b>${xo.fresh_rubber_saving_s}s</b> — ${xo.margin_s}s short.` : ''} ${sd.sc_flips_call ? `<span style="color:#ffd700">A Safety Car would flip it to a ${sd.sc_favored_stops}-stop.</span>` : 'A Safety Car doesn\'t change the call.'}</span></div>` : ''}
      ${inv ? `<div class="meta-row" style="margin-top:6px"><span>tyre stock: ${inv.top10_with_new_hard}/${inv.top10_count} of the top 10 hold a new HARD · ${inv.top10_with_new_medium}/${inv.top10_count} a new MEDIUM · ${inv.top10_with_new_soft}/${inv.top10_count} a new SOFT</span></div>` : ''}`;
    sections.push({ id: 'strategies', title: 'The strategies on paper', node: stratCard });
    if (n) sections.push({ id: 'race-shape-story', title: 'Race shape (narrative)', node: proseCard('Race shape', n.race_shape) });

    if (d.strategies && d.strategies.length) {
      sections.push({ id: 'pit-strategy-gantt', title: 'Expected pit stop strategies & windows',
                     node: pitStrategyGanttCard(d.strategies, m.total_laps_assumed) });
    }

    if (d.grid.some(g => g.tyres)) {
      sections.push({ id: 'tyre-availability', title: 'Tyres available for race',
                     node: tyreAvailabilityCard(d.grid) });
    }

    // undercut vs overcut
    if (d.undercut) {
      const u = d.undercut;
      const col = u.verdict === 'undercut' ? '#2ea44f' : u.verdict === 'overcut' ? '#ff8c00' : '#8a8a8a';
      const uCard = document.createElement('div');
      uCard.className = 'card';
      uCard.innerHTML = `<h2>Undercut vs overcut</h2>
        <div class="meta-row"><span>fresh-tyre gain over the ${u.window_laps} laps before a rival covers, net of the cold out-lap</span></div>
        <div class="meta-row" style="margin-top:6px">
          <span>fresh ${u.compound} vs a ${u.rival_tyre_age}-lap tyre: <b>${u.fresh_gain_per_lap}s/lap</b></span>
          <span>out-lap cost: ${u.out_lap_penalty_s}s</span>
          <span>net undercut: <b style="color:${col}">${u.net_undercut_s > 0 ? '+' : ''}${u.net_undercut_s}s</b></span>
          <span>verdict: <b style="color:${col}">${u.verdict.toUpperCase()}</b></span>
        </div>
        <div class="meta-row" style="margin-top:6px"><span>${u.note}</span></div>`;
      sections.push({ id: 'undercut', title: 'Undercut vs overcut', node: uCard });
    }
    if (n && n.the_undercut) {
      sections.push({ id: 'undercut-story', title: 'The undercut (narrative)', node: proseCard('The undercut', n.the_undercut) });
    }

    // grid → flag projection
    if (d.projection && d.projection.forecasts && d.projection.forecasts.length) {
      const pj = d.projection;
      const jCard = document.createElement('div');
      jCard.className = 'card';
      let jRows = pj.forecasts.map(f => {
        const move = f.current_position - f.predicted_position;
        const badge = move > 0 ? `<span class="delta-up">▲${move}</span>`
          : move < 0 ? `<span class="delta-down">▼${-move}</span>` : '·';
        return `<tr><td>${f.predicted_position}</td><td><b>${f.acronym}</b></td>
          <td>${f.current_position}</td><td>${badge}</td>
          <td>${(f.win_probability * 100).toFixed(0)}%</td>
          <td>${(f.podium_probability * 100).toFixed(0)}%</td>
          <td>P${f.position_range[0]}–P${f.position_range[1]}</td></tr>`;
      }).join('');
      jCard.innerHTML = `<h2>Grid → flag — the model's projection</h2>
        <div class="meta-row"><span>full race sim + Monte Carlo · assumes everyone starts on ${pj.start_compound_assumption} · grid spread ${pj.grid_spread_assumption_s}s/slot · range = P5–P95</span></div>
        <table class="results"><tr><th>PROJ</th><th>DRV</th><th>GRID</th><th>Δ</th><th>WIN</th><th>PODIUM</th><th>RANGE</th></tr>${jRows}</table>`;
      sections.push({ id: 'projection', title: "Grid → flag — the model's projection", node: jCard });
    }
    if (n && n.projection) {
      sections.push({ id: 'projection-story', title: 'The projection (narrative)', node: proseCard('The projection', n.projection) });
    }

    // the doors — what a grid slot is worth + overtaking difficulty
    if (d.doors && d.doors.cards && d.doors.cards.length) {
      const dr = d.doors, ov = d.overtaking;
      const dCard = document.createElement('div');
      dCard.className = 'card';
      const cardRows = dr.cards.map(c => {
        const kg = c.keep_grid, pl = c.pit_lane_start, cost = c.cost_positions;
        const costCell = cost == null ? '—'
          : cost >= 2 ? `<span class="delta-down">▼${cost.toFixed(1)}</span>`
          : cost <= 0.5 ? `<span class="delta-up">~${cost.toFixed(1)} · free option</span>`
          : `${cost.toFixed(1)}`;
        const pod = x => `<span style="opacity:.6">(${(x * 100).toFixed(0)}% pod)</span>`;
        return `<tr><td><b>${c.acronym}</b> P${c.grid_position}</td>
          <td>P${kg.expected_finish} ${pod(kg.podium)}</td>
          <td>${pl ? `P${pl.expected_finish} ${pod(pl.podium)}` : '—'}</td>
          <td>${costCell}</td></tr>`;
      }).join('');
      const fmt = (arr, up) => arr.slice(0, 3).map(m =>
        `${m.acronym} <span class="delta-${up ? 'up' : 'down'}">${up ? '▲' : '▼'}${Math.abs(m.delta_vs_grid)}</span>`).join(' · ');
      const g = fmt(dr.expected_movers.gainers, true);
      const l = fmt(dr.expected_movers.losers, false);
      dCard.innerHTML = `<h2>The doors — what a grid slot is worth</h2>
        <div class="meta-row"><span>expected finish keeping the grid slot vs a pit-lane start · cost = positions surrendered for a reversible, bounded-downside bet</span></div>
        <table class="results"><tr><th>CAR</th><th>KEEP GRID</th><th>PIT-LANE START</th><th>COST</th></tr>${cardRows}</table>
        <div class="meta-row" style="margin-top:8px"><span>projected movers — gaining: ${g || '—'} · losing: ${l || '—'}</span></div>
        ${ov ? `<div class="meta-row" style="margin-top:6px"><span>overtaking here: ~${ov.pass_threshold_s_per_lap}s/lap of race pace needed to clear a car (${ov.difficulty}) — recovering places is ${ov.difficulty === 'hard' ? 'expensive' : 'workable'}</span></div>` : ''}
        ${dr.sc_refund ? `<div class="meta-row" style="margin-top:6px"><span>early-SC refund: ~${(dr.sc_refund.p_sc_in_window * 100).toFixed(0)}% chance of a Safety Car in the first ${dr.sc_refund.early_window_laps} laps, worth ~${dr.sc_refund.full_refund_s}s off a pit-lane start if it falls</span></div>` : ''}
        ${d.weather_outlook && d.weather_outlook.rain_risk !== 'low' ? `<div class="meta-row" style="margin-top:6px"><span>⛅ rain risk ${d.weather_outlook.rain_risk.toUpperCase()} — ${d.weather_outlook.implication}</span></div>` : ''}
        ${d.recovery_prior ? `<div class="meta-row" style="margin-top:6px"><span>history: cars starting P${d.recovery_prior.back_grid_threshold}+ here finished ~P${d.recovery_prior.avg_finish_from_back} on average (${d.recovery_prior.sample_size} cars, ${(d.recovery_prior.races_sampled || []).join('/')}) · best recovery ${d.recovery_prior.best_recovery.acronym} ${d.recovery_prior.best_recovery.year} P${d.recovery_prior.best_recovery.grid}→P${d.recovery_prior.best_recovery.finish}</span></div>` : ''}`;
      sections.push({ id: 'doors', title: 'The doors — what a grid slot is worth', node: dCard });
    }
    if (n && n.the_doors) {
      sections.push({ id: 'doors-story', title: 'The doors (narrative)', node: proseCard('The doors', n.the_doors) });
    }

    sections.push({ id: 'deg-curves', title: 'Tyre degradation model', node: degCurveCard(d.deg_curves) });

    // watch list
    const wCard = document.createElement('div');
    wCard.className = 'card';
    let wRows = d.unknowns.map(u =>
      `<tr><td><b>${u.name}</b></td><td>${u.watch}</td></tr>`).join('');
    wCard.innerHTML = `<h2>Fill in the blanks live</h2>
      <table class="results"><tr><th>UNKNOWN</th><th>WATCH FOR</th></tr>${wRows}</table>`;
    sections.push({ id: 'watch-list', title: 'Fill in the blanks live', node: wCard });
    if (n) sections.push({ id: 'watch-list-story', title: 'The watch list (narrative)', node: proseCard('The watch list', n.watch_list) });

    if (customizeOpen.prerace) {
      renderCustomizePanel(root, 'prerace', sections, () => renderPrerace(b));
    }

    const filtered = applyLayout('prerace', sections);
    for (const sec of filtered) root.appendChild(sec.node);
  }

  // ── deg curve chart ────────────────────────────────────────────────────────
  function degCurveCard(curves) {
    const c = document.createElement('div');
    c.className = 'card';
    c.innerHTML = `<h2>Tyre degradation model</h2>`;
    const cv = document.createElement('canvas');
    cv.width = 560; cv.height = 220;
    c.appendChild(cv);
    const ctx = cv.getContext('2d');
    const maxAge = 30, pad = 40;
    const entries = COMPOUNDS.map(k => [k, curves[k]]).filter(([, v]) => v && v.baseline > 0);
    if (!entries.length) return c;
    const times = entries.flatMap(([, v]) => [v.baseline, v.baseline + v.deg_rate * maxAge]);
    const tMin = Math.min(...times) - 0.3, tMax = Math.max(...times) + 0.3;
    const x = a => pad + a / maxAge * (cv.width - pad - 10);
    const y = t => (cv.height - 24) - (t - tMin) / (tMax - tMin) * (cv.height - 40);
    ctx.strokeStyle = '#2a2a2a'; ctx.fillStyle = '#555'; ctx.font = '10px Courier New';
    for (let a = 0; a <= maxAge; a += 5) {
      ctx.beginPath(); ctx.moveTo(x(a), 12); ctx.lineTo(x(a), cv.height - 24); ctx.stroke();
      ctx.fillText(a, x(a) - 4, cv.height - 10);
    }
    ctx.fillText('tyre age (laps)', cv.width / 2 - 40, cv.height - 0.5);
    const colour = { SOFT: '#e8002d', MEDIUM: '#ffd700', HARD: '#ffffff' };
    for (const [k, v] of entries) {
      ctx.strokeStyle = colour[k]; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x(0), y(v.baseline)); ctx.lineTo(x(maxAge), y(v.baseline + v.deg_rate * maxAge)); ctx.stroke();
    }
    // fixed legend stack — never collides, whatever the curves do
    let ly = 22;
    for (const [k, v] of entries) {
      ctx.strokeStyle = colour[k]; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(pad + 4, ly - 3); ctx.lineTo(pad + 22, ly - 3); ctx.stroke();
      ctx.fillStyle = colour[k];
      ctx.fillText(`${k} ${v.baseline.toFixed(1)}s +${v.deg_rate.toFixed(3)}/lap (${v.confidence})`,
                   pad + 28, ly);
      ly += 14;
    }
    return c;
  }

  // ── what-if editor ─────────────────────────────────────────────────────────
  function openEditor(driverNumber, rowEl) {
    document.querySelectorAll('tr.editing').forEach(e => e.classList.remove('editing'));
    rowEl.classList.add('editing');
    const d = currentBriefing.data;
    const r = d.results.find(r => r.driver_number === driverNumber);
    if (!r || !r.stints.length) return;
    editorState = {
      driver_number: driverNumber,
      acronym: r.acronym,
      totalLaps: d.session.total_laps,
      sets: r.sets_at_start || null,
      stints: r.stints.map(s => ({ compound: s.compound, lap_start: s.lap_start,
                                   lap_end: s.lap_end ?? d.session.total_laps,
                                   tyre_age: s.tyre_age || 0 })),
      original: JSON.stringify(r.stints),
    };
    // normalise to contiguous full-race coverage
    normaliseStints();
    renderEditor();
  }

  function normaliseStints() {
    const st = editorState.stints;
    st.sort((a, b) => a.lap_start - b.lap_start);
    st[0].lap_start = 1;
    for (let i = 1; i < st.length; i++) st[i].lap_start = st[i - 1].lap_end + 1;
    st[st.length - 1].lap_end = editorState.totalLaps;
  }

  function renderEditor() {
    const card = document.getElementById('editor-card');
    const es = editorState;
    const garage = es.sets
      ? 'garage at race start: ' + COMPOUNDS.map(c =>
          `${c} ${es.sets[c]?.new ?? 0}N+${es.sets[c]?.used ?? 0}U`).join(' · ')
      : 'set availability unknown for this race';
    card.innerHTML = `<h2>What-if: ${es.acronym}</h2>
      <div id="editor-track"></div>
      <div id="editor-hint">drag ║ boundaries to move pit stops · click a stint to cycle compound · click the N/U corner badge to toggle new/used set</div>
      <div class="meta-row"><span>${garage}</span></div>
      <div class="btnrow">
        <button id="btn-add">+ add stop</button>
        <button id="btn-del">− remove stop</button>
        <button id="btn-reset">reset to actual</button>
      </div>
      <div id="whatif-result"><span class="notice spin">simulating…</span></div>`;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    const track = card.querySelector('#editor-track');
    const W = track.clientWidth || 700;
    const lapToPx = lap => (lap / es.totalLaps) * W;

    // stint segments
    for (let i = 0; i < es.stints.length; i++) {
      const st = es.stints[i];
      const left = lapToPx(st.lap_start - 1), width = lapToPx(st.lap_end) - left;
      const seg = document.createElement('div');
      seg.className = `seg c-${st.compound}`;
      seg.style.left = left + 'px'; seg.style.width = width + 'px';
      const isUsed = (st.tyre_age || 0) > 0;
      seg.innerHTML = `<span class="seg-label">${st.compound[0]} ${st.lap_end - st.lap_start + 1}${isUsed ? ' (U' + st.tyre_age + ')' : ''}</span>
        <span class="seg-age" title="toggle new/used set" style="position:absolute;top:1px;right:3px;font-size:9px;padding:0 3px;border:1px solid rgba(0,0,0,.35);border-radius:2px;cursor:pointer;background:rgba(255,255,255,.25)">${isUsed ? 'U' : 'N'}</span>`;
      seg.onclick = () => {
        st.compound = COMPOUNDS[(COMPOUNDS.indexOf(st.compound) + 1) % COMPOUNDS.length];
        renderEditor();
        scheduleWhatif();
      };
      seg.querySelector('.seg-age').onclick = (ev) => {
        ev.stopPropagation();
        if ((st.tyre_age || 0) > 0) {
          st.tyre_age = 0;
        } else {
          // reuse the real fitted age when this matches the original stint,
          // otherwise assume a typical 3-lap scrub
          const orig = JSON.parse(es.original)[i];
          st.tyre_age = (orig && orig.compound === st.compound && orig.tyre_age > 0)
            ? orig.tyre_age : 3;
        }
        renderEditor();
        scheduleWhatif();
      };
      track.appendChild(seg);
      // lap ticks at boundaries
      if (i > 0) {
        const tick = document.createElement('span');
        tick.className = 'lap-tick';
        tick.style.left = left + 'px';
        tick.textContent = 'L' + (st.lap_start - 1);
        track.appendChild(tick);
      }
    }

    // drag handles between stints
    for (let i = 1; i < es.stints.length; i++) {
      const h = document.createElement('div');
      h.className = 'handle';
      h.style.left = lapToPx(es.stints[i].lap_start - 1) + 'px';
      track.appendChild(h);
      h.onpointerdown = (ev) => {
        ev.preventDefault();
        h.setPointerCapture(ev.pointerId);
        const rect = track.getBoundingClientRect();
        h.onpointermove = (mv) => {
          let lap = Math.round((mv.clientX - rect.left) / W * es.totalLaps);
          const lo = es.stints[i - 1].lap_start + 1;       // ≥2-lap stints
          const hi = es.stints[i].lap_end - 1;
          lap = Math.max(lo, Math.min(hi, lap));
          es.stints[i - 1].lap_end = lap;
          es.stints[i].lap_start = lap + 1;
          h.style.left = lapToPx(lap) + 'px';
        };
        h.onpointerup = () => {
          h.onpointermove = null; h.onpointerup = null;
          renderEditor();
          scheduleWhatif();
        };
      };
    }

    card.querySelector('#btn-add').onclick = () => {
      const st = es.stints;
      if (st.length >= 5) return;
      let idx = 0;
      for (let i = 1; i < st.length; i++)
        if (st[i].lap_end - st[i].lap_start > st[idx].lap_end - st[idx].lap_start) idx = i;
      const s = st[idx];
      if (s.lap_end - s.lap_start < 8) return;
      const mid = Math.floor((s.lap_start + s.lap_end) / 2);
      const next = COMPOUNDS[(COMPOUNDS.indexOf(s.compound) + 1) % COMPOUNDS.length];
      st.splice(idx + 1, 0, { compound: next, lap_start: mid + 1, lap_end: s.lap_end, tyre_age: 0 });
      s.lap_end = mid;
      renderEditor(); scheduleWhatif();
    };
    card.querySelector('#btn-del').onclick = () => {
      const st = es.stints;
      if (st.length <= 2) return;   // two-compound rule needs ≥2 stints
      const last = st.pop();
      st[st.length - 1].lap_end = last.lap_end;
      renderEditor(); scheduleWhatif();
    };
    card.querySelector('#btn-reset').onclick = () => {
      es.stints = JSON.parse(es.original).map(s => ({ compound: s.compound,
        lap_start: s.lap_start, lap_end: s.lap_end ?? es.totalLaps,
        tyre_age: s.tyre_age || 0 }));
      normaliseStints();
      renderEditor(); scheduleWhatif();
    };

    scheduleWhatif();
  }

  function scheduleWhatif() {
    clearTimeout(whatifTimer);
    whatifTimer = setTimeout(runWhatif, 450);
  }

  async function runWhatif() {
    if (!editorState) return;
    const seq = ++whatifSeq;
    const out = document.getElementById('whatif-result');
    out.innerHTML = '<span class="notice spin">simulating…</span>';
    try {
      const res = await fetch('/api/whatif', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_key: currentBriefing.data.session.session_key,
          driver_number: editorState.driver_number,
          stints: editorState.stints,
        }),
      });
      if (seq !== whatifSeq) return;   // superseded by a newer edit
      if (!res.ok) throw new Error((await res.json()).detail || res.status);
      renderWhatifResult(await res.json());
    } catch (e) {
      if (seq === whatifSeq) out.innerHTML = `<span class="notice">simulation failed: ${e.message}</span>`;
    }
  }

  function whatifTraceSVG(trace) {
    const W = 620, H = 300, padL = 40, padR = 92, padT = 16, padB = 28;
    const ref = trace.reference_lap_time, a = trace.anchor_lap, subject = trace.subject_number;
    const COMP = { SOFT: '#e8002d', MEDIUM: '#ffd700', HARD: '#ffffff', UNKNOWN: '#888' };
    const SCEN = ['#e8002d', '#ff8c00', '#2ea44f'];   // no fix / +0.3 / +0.5
    // offset from average pace: below 0 = faster than the field's average lap
    const off = pts => pts.map(p => ({ lap: p.lap, y: p.cumulative - ref * (p.lap - a), compound: p.compound }));
    const field = (trace.field || []).map(f => ({ ...f, o: off(f.points) }));
    const scen = (trace.scenarios || []).map(s => ({ ...s, o: off(s.points) }));
    const actual = off(trace.baseline), edited = off(trace.modified);
    const allY = [0].concat(
      ...field.map(f => f.o.map(p => p.y)), ...scen.map(s => s.o.map(p => p.y)),
      actual.map(p => p.y), edited.map(p => p.y));
    if (allY.length < 2) return '';
    const x0 = a, x1 = trace.total_laps;
    let yMin = Math.min(...allY), yMax = Math.max(...allY);
    const yp = (yMax - yMin) * 0.08 || 1; yMin -= yp; yMax += yp;
    const X = l => padL + (l - x0) / Math.max(1, x1 - x0) * (W - padL - padR);
    const Y = v => padT + (yMax - v) / (yMax - yMin || 1) * (H - padT - padB); // slower (higher) at top
    const path = o => o.map((p, i) => (i ? 'L' : 'M') + X(p.lap).toFixed(1) + ' ' + Y(p.y).toFixed(1)).join(' ');
    const stops = o => o.filter((p, i) => i > 0 && p.compound !== o[i - 1].compound)
      .map(p => `<circle cx="${X(p.lap).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3" fill="${COMP[p.compound] || '#888'}" stroke="#111"/>`).join('');
    // SC/VSC bands
    const bands = (trace.sc_bands || []).map(b => {
      const x = X(b.start), w = Math.max(2, X(b.end + 1) - X(b.start));
      return `<rect x="${x.toFixed(1)}" y="${padT}" width="${w.toFixed(1)}" height="${(H - padT - padB).toFixed(1)}" fill="#ffd700" opacity="0.10"/>`
        + `<text x="${(x + 2).toFixed(1)}" y="${padT + 8}" fill="#b58900" font-size="8">${b.type}</text>`;
    }).join('');
    let gx = '';
    for (let l = Math.ceil(x0 / 5) * 5; l <= x1; l += 5)
      gx += `<line x1="${X(l)}" y1="${padT}" x2="${X(l)}" y2="${H - padB}" stroke="#242424"/><text x="${X(l)}" y="${H - padB + 12}" fill="#666" font-size="9" text-anchor="middle">${l}</text>`;
    const zeroY = Y(0);
    const fieldPaths = field.filter(f => f.driver_number !== subject)
      .map(f => `<path d="${path(f.o)}" fill="none" stroke="#4a4a4a" stroke-width="0.7" opacity="0.5"/>`).join('');
    const scenPaths = scen.map((s, i) => {
      const col = SCEN[i % SCEN.length], e = s.o[s.o.length - 1];
      return `<path d="${path(s.o)}" fill="none" stroke="${col}" stroke-width="1.6" stroke-dasharray="4 3"/>`
        + `<text x="${(X(e.lap) + 4).toFixed(1)}" y="${(Y(e.y) + 3).toFixed(1)}" fill="${col}" font-size="8.5">${s.label} · P${s.race_time_rank}</text>`;
    }).join('');
    const ae = actual[actual.length - 1];
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">
      ${bands}${gx}
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${(W - padR).toFixed(1)}" y2="${zeroY.toFixed(1)}" stroke="#555" stroke-dasharray="3 3"/>
      <text x="${padL + 2}" y="${(zeroY - 4).toFixed(1)}" fill="#777" font-size="8.5">field average pace</text>
      <text x="4" y="${padT + 8}" fill="#666" font-size="9">slower</text>
      <text x="4" y="${H - padB}" fill="#666" font-size="9">faster</text>
      ${fieldPaths}
      <path d="${path(actual)}" fill="none" stroke="#2f6fed" stroke-width="2.4"/>
      ${stops(actual)}${scenPaths}
      <text x="${(X(ae.lap) + 4).toFixed(1)}" y="${(Y(ae.y) + 3).toFixed(1)}" fill="#2f6fed" font-size="8.5">actual</text>
    </svg>`;
  }

  // ── RSS-style per-race charts (data from /api/race_charts) ──────────────────

  const CHART_COMP = { SOFT: '#e8002d', MEDIUM: '#ffd700', HARD: '#ffffff',
                       INTERMEDIATE: '#43b02a', WET: '#0067ad', UNKNOWN: '#888' };

  // Hover state for the interactive race trace (set when the SVG is built).
  let _rtState = null;
  let _rtTooltip = null;

  async function loadRaceCharts(sessionKey) {
    const body = document.getElementById('race-charts-body');
    if (!body) return;
    try {
      const res = await fetch(`/api/race_charts?session_key=${sessionKey}`);
      if (!res.ok) throw new Error((await res.json()).detail || res.status);
      const rc = await res.json();
      body.innerHTML =
        chartBlock('Gap to the leader — the race trace',
                   'reconstructed from public lap times · coloured dots = tyre change · hover for exact gaps', raceTraceSVG(rc.race_trace)) +
        chartBlock('The rejoin trap — cars you drop behind if you box on lap L',
                   `a stop costs ~${rc.rejoin_map.pit_loss}s; the peak marks the DRS-train lap`, rejoinSVG(rc.rejoin_map)) +
        chartBlock('The leader’s lapping tax (estimated)',
                   'cumulative time bled clearing backmarkers — a traffic-density proxy, not a measured delta', lappingTaxSVG(rc.lapping_tax)) +
        chartBlock('The decision on one page',
                   'measured degradation, the pit window, and the rules', decisionPageHTML(rc.decision_page));
      wireRaceTrace();   // attach the hover crosshair + gap tooltip
    } catch (e) {
      body.innerHTML = `<span class="notice">Race charts unavailable: ${e.message}</span>`;
    }
  }

  function chartBlock(title, sub, inner) {
    return `<div style="margin:16px 0">
      <div class="meta-row"><span><b>${title}</b></span></div>
      <div class="meta-row"><span style="color:#777">${sub}</span></div>
      ${inner}</div>`;
  }

  // #5 — per-driver gap to the leader over the race
  function raceTraceSVG(rt) {
    const drivers = (rt.drivers || []).filter(d => d.points && d.points.length > 1);
    if (drivers.length < 2) return '<span class="notice">no trace data</span>';
    const W = 640, H = 340, padL = 40, padR = 48, padT = 16, padB = 26;
    const total = rt.total_laps;
    let maxGap = 1;
    drivers.forEach(d => d.points.forEach(p => { if (p.gap > maxGap) maxGap = p.gap; }));
    const X = l => padL + (l - 1) / Math.max(1, total - 1) * (W - padL - padR);
    const Y = g => padT + (g / maxGap) * (H - padT - padB);   // leader (0) at top
    const path = pts => pts.map((p, i) => (i ? 'L' : 'M') + X(p.lap).toFixed(1) + ' ' + Y(p.gap).toFixed(1)).join(' ');
    const colOf = d => d.team_colour ? ('#' + d.team_colour) : '#8a8a8a';

    let gx = '';
    for (let l = 10; l <= total; l += 10)
      gx += `<line x1="${X(l)}" y1="${padT}" x2="${X(l)}" y2="${H - padB}" stroke="#242424"/><text x="${X(l)}" y="${H - padB + 12}" fill="#666" font-size="9" text-anchor="middle">${l}</text>`;

    // Every driver drawn in their team colour; the second car sharing a colour
    // is dashed so team-mates stay distinguishable.
    const seen = {};
    const lines = drivers.map((d, i) => {
      const c = colOf(d);
      const dash = (seen[c] = (seen[c] || 0) + 1) > 1 ? ' stroke-dasharray="5 3"' : '';
      const lw = i === 0 ? 2.4 : 1.4;
      const stops = d.points.filter((p, j) => j > 0 && p.compound !== d.points[j - 1].compound)
        .map(p => `<circle cx="${X(p.lap).toFixed(1)}" cy="${Y(p.gap).toFixed(1)}" r="2.4" fill="${CHART_COMP[p.compound] || '#888'}" stroke="#111" stroke-width="0.5"/>`).join('');
      return `<path d="${path(d.points)}" fill="none" stroke="${c}" stroke-width="${lw}"${dash} opacity="0.92"/>${stops}`;
    }).join('');

    // Right-edge acronym labels for every finisher, nudged apart so they don't overlap.
    const labels = drivers.map(d => ({ acr: d.acronym, c: colOf(d), y: Y(d.points[d.points.length - 1].gap) }))
      .sort((a, b) => a.y - b.y);
    const MINH = 10;
    for (let i = 1; i < labels.length; i++)
      if (labels[i].y - labels[i - 1].y < MINH) labels[i].y = labels[i - 1].y + MINH;
    const labelSVG = labels.map(l =>
      `<text x="${(W - padR + 3).toFixed(1)}" y="${(Math.min(l.y, H - 4) + 3).toFixed(1)}" fill="${l.c}" font-size="8.5">${l.acr}</text>`).join('');

    // Stash geometry + data so the hover handler can map cursor → lap → gaps.
    _rtState = { drivers, total, maxGap, W, H, padL, padR, padT, padB };

    return `<svg id="race-trace-svg" viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">
      ${gx}
      <line x1="${padL}" y1="${padT}" x2="${(W - padR).toFixed(1)}" y2="${padT}" stroke="#555" stroke-dasharray="3 3"/>
      <text x="${padL + 2}" y="${padT - 4}" fill="#777" font-size="8.5">leader</text>
      <text x="4" y="${H - padB}" fill="#666" font-size="9">behind ↓</text>
      ${lines}${labelSVG}
      <line id="rt-crosshair" x1="0" y1="${padT}" x2="0" y2="${H - padB}" stroke="#aaa" stroke-dasharray="3 3" visibility="hidden"/>
      <g id="rt-hoverdots"></g>
      <rect id="rt-hit" x="${padL}" y="${padT}" width="${(W - padL - padR).toFixed(1)}" height="${(H - padT - padB).toFixed(1)}" fill="transparent" style="cursor:crosshair"/>
    </svg>`;
  }

  // Attach the interactive crosshair + gap tooltip to the race trace. On hover
  // it snaps to the nearest lap, drops a dot on every driver's line at that lap,
  // and shows a tooltip of each driver's actual gap to the leader in seconds.
  function wireRaceTrace() {
    const svg = document.getElementById('race-trace-svg');
    if (!svg || !_rtState) return;
    const st = _rtState;
    const hit = svg.querySelector('#rt-hit');
    const cross = svg.querySelector('#rt-crosshair');
    const dots = svg.querySelector('#rt-hoverdots');
    if (!hit || !cross || !dots) return;

    const X = l => st.padL + (l - 1) / Math.max(1, st.total - 1) * (st.W - st.padL - st.padR);
    const Y = g => st.padT + (g / st.maxGap) * (st.H - st.padT - st.padB);
    const colOf = d => d.team_colour ? ('#' + d.team_colour) : '#8a8a8a';

    // Per-driver lap → gap lookup (drivers may retire, so track available laps).
    const lookups = st.drivers.map(d => {
      const map = {};
      d.points.forEach(p => { map[p.lap] = p.gap; });
      return { acr: d.acronym, colour: colOf(d), map, laps: d.points.map(p => p.lap) };
    });

    if (!_rtTooltip) {
      _rtTooltip = document.createElement('div');
      _rtTooltip.style.cssText = 'position:fixed;z-index:9999;pointer-events:none;display:none;'
        + 'background:#0b0b0b;border:1px solid #333;border-radius:4px;padding:6px 8px;'
        + 'font:11px/1.35 "Courier New",monospace;color:#ddd;box-shadow:0 4px 14px rgba(0,0,0,0.5)';
      document.body.appendChild(_rtTooltip);
    }

    function show(clientX, clientY) {
      const rect = svg.getBoundingClientRect();
      if (!rect.width) return;
      const svgX = (clientX - rect.left) * (st.W / rect.width);
      let lap = Math.round((svgX - st.padL) / Math.max(1, st.W - st.padL - st.padR) * (st.total - 1)) + 1;
      lap = Math.max(1, Math.min(st.total, lap));
      const cx = X(lap);
      cross.setAttribute('x1', cx.toFixed(1));
      cross.setAttribute('x2', cx.toFixed(1));
      cross.setAttribute('visibility', 'visible');

      const rows = [];
      let dotSVG = '';
      lookups.forEach(lu => {
        let g = lu.map[lap];
        if (g === undefined) {
          const before = lu.laps.filter(l => l <= lap);
          if (!before.length) return;           // driver hadn't started / no data
          g = lu.map[before[before.length - 1]];
        }
        rows.push({ acr: lu.acr, colour: lu.colour, gap: g });
        dotSVG += `<circle cx="${cx.toFixed(1)}" cy="${Y(g).toFixed(1)}" r="2.6" fill="${lu.colour}" stroke="#000" stroke-width="0.5"/>`;
      });
      dots.innerHTML = dotSVG;
      rows.sort((a, b) => a.gap - b.gap);

      const body = rows.map(r =>
        `<div style="display:flex;justify-content:space-between;gap:12px">`
        + `<span style="color:${r.colour}">${r.acr}</span>`
        + `<span>${r.gap <= 0.05 ? 'leader' : '+' + r.gap.toFixed(1) + 's'}</span></div>`).join('');
      _rtTooltip.innerHTML = `<div style="color:#888;margin-bottom:3px">LAP ${lap}</div>${body}`;
      _rtTooltip.style.display = 'block';

      const tw = _rtTooltip.offsetWidth, th = _rtTooltip.offsetHeight;
      let left = clientX + 14;
      if (left + tw > window.innerWidth - 8) left = clientX - tw - 14;
      let top = Math.max(8, Math.min(window.innerHeight - th - 8, clientY - th / 2));
      _rtTooltip.style.left = left + 'px';
      _rtTooltip.style.top = top + 'px';
    }

    function hide() {
      cross.setAttribute('visibility', 'hidden');
      dots.innerHTML = '';
      if (_rtTooltip) _rtTooltip.style.display = 'none';
    }

    hit.addEventListener('mousemove', e => show(e.clientX, e.clientY));
    hit.addEventListener('mouseleave', hide);
    hit.addEventListener('touchstart', e => { if (e.touches[0]) { show(e.touches[0].clientX, e.touches[0].clientY); } }, { passive: true });
    hit.addEventListener('touchmove', e => { if (e.touches[0]) { show(e.touches[0].clientX, e.touches[0].clientY); e.preventDefault(); } }, { passive: false });
    hit.addEventListener('touchend', hide);
  }

  // #4a — how many cars the leader rejoins behind if they box on lap L
  function rejoinSVG(rj) {
    const pts = rj.points || [];
    if (pts.length < 2) return '<span class="notice">no data</span>';
    const W = 620, H = 170, padL = 34, padR = 20, padT = 12, padB = 24;
    const total = rj.total_laps;
    const maxC = Math.max(...pts.map(p => p.rejoin_behind), 1);
    const X = l => padL + (l - 1) / Math.max(1, total - 1) * (W - padL - padR);
    const Y = c => padT + (1 - c / maxC) * (H - padT - padB);
    const line = pts.map((p, i) => (i ? 'L' : 'M') + X(p.lap).toFixed(1) + ' ' + Y(p.rejoin_behind).toFixed(1)).join(' ');
    const area = `M${X(pts[0].lap).toFixed(1)} ${(H - padB).toFixed(1)} `
      + pts.map(p => 'L' + X(p.lap).toFixed(1) + ' ' + Y(p.rejoin_behind).toFixed(1)).join(' ')
      + ` L${X(pts[pts.length - 1].lap).toFixed(1)} ${(H - padB).toFixed(1)} Z`;
    let gx = '';
    for (let l = 10; l <= total; l += 10)
      gx += `<line x1="${X(l)}" y1="${padT}" x2="${X(l)}" y2="${H - padB}" stroke="#242424"/><text x="${X(l)}" y="${H - padB + 12}" fill="#666" font-size="9" text-anchor="middle">${l}</text>`;
    const wx = rj.worst_lap ? X(rj.worst_lap) : null;
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">
      ${gx}
      <path d="${area}" fill="#e8002d" opacity="0.15"/>
      <path d="${line}" fill="none" stroke="#e8002d" stroke-width="1.8"/>
      ${wx != null ? `<line x1="${wx.toFixed(1)}" y1="${padT}" x2="${wx.toFixed(1)}" y2="${H - padB}" stroke="#ff8c00" stroke-dasharray="4 3"/><text x="${(wx + 3).toFixed(1)}" y="${padT + 9}" fill="#ff8c00" font-size="8.5">trap: lap ${rj.worst_lap} · behind ${rj.worst_count}</text>` : ''}
      <text x="4" y="${padT + 8}" fill="#666" font-size="9">cars</text>
    </svg>`;
  }

  // #4b — leader's cumulative time lost in backmarker traffic
  function lappingTaxSVG(lt) {
    const pts = lt.points || [];
    if (pts.length < 2) return '<span class="notice">no data</span>';
    const W = 620, H = 150, padL = 34, padR = 54, padT = 12, padB = 24;
    const total = lt.total_laps;
    const maxT = Math.max(...pts.map(p => p.cumulative_tax_s), 1);
    const X = l => padL + (l - 1) / Math.max(1, total - 1) * (W - padL - padR);
    const Y = t => padT + (1 - t / maxT) * (H - padT - padB);
    const line = pts.map((p, i) => (i ? 'L' : 'M') + X(p.lap).toFixed(1) + ' ' + Y(p.cumulative_tax_s).toFixed(1)).join(' ');
    let gx = '';
    for (let l = 10; l <= total; l += 10)
      gx += `<line x1="${X(l)}" y1="${padT}" x2="${X(l)}" y2="${H - padB}" stroke="#242424"/><text x="${X(l)}" y="${H - padB + 12}" fill="#666" font-size="9" text-anchor="middle">${l}</text>`;
    const e = pts[pts.length - 1];
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">
      ${gx}
      <path d="${line}" fill="none" stroke="#ffd700" stroke-width="1.8"/>
      <text x="${(X(e.lap) + 3).toFixed(1)}" y="${(Y(e.cumulative_tax_s) + 3).toFixed(1)}" fill="#ffd700" font-size="9">${lt.total_tax_s}s</text>
      <text x="4" y="${padT + 8}" fill="#666" font-size="9">s lost</text>
    </svg>`;
  }

  // #3 — the decision on one page: deg bars + window + rules
  function decisionPageHTML(dp) {
    const comps = dp.compounds || [];
    const maxDeg = Math.max(...comps.map(c => c.deg_rate || 0), 0.001);
    const bars = comps.map(c => {
      const w = c.deg_rate ? Math.round(c.deg_rate / maxDeg * 100) : 0;
      return `<div style="display:flex;align-items:center;gap:8px;margin:3px 0">
        <span style="width:64px;color:${CHART_COMP[c.compound] || '#ccc'}">${c.compound}</span>
        <div style="flex:1;background:#1c1c1c;border-radius:3px;height:14px"><div style="width:${w}%;height:100%;background:${CHART_COMP[c.compound] || '#888'};opacity:0.85;border-radius:3px"></div></div>
        <span style="width:104px;text-align:right;color:#aaa">${c.deg_rate != null ? c.deg_rate.toFixed(3) + ' s/lap' : '—'}</span></div>`;
    }).join('');
    const w = dp.window;
    const windowTxt = w ? `pit window: laps ${w.earliest}–${w.latest} (target ${w.target})` : 'pit window: n/a';
    const rules = (dp.rules || []).map(r => `<li>${r}</li>`).join('');
    return `<div style="display:flex;flex-direction:column;gap:6px">
      <div>${bars}</div>
      <div class="meta-row"><span>${windowTxt}</span><span>pit loss ${dp.pit_loss}s</span></div>
      <ul style="margin:4px 0 0 16px;color:#bbb;font-size:12px">${rules}</ul>
    </div>`;
  }

  function whatifOrderTable(trace) {
    const orders = trace.tyre_orders || [];
    if (orders.length < 2) return '';
    const fixes = orders[0].scenarios.map(s => s.label);
    // per pace-fix column, the better order is the one on less race time
    const best = fixes.map((_, ci) => {
      let bi = 0, bv = Infinity;
      orders.forEach((o, oi) => { const v = o.scenarios[ci].final_cumulative; if (v < bv) { bv = v; bi = oi; } });
      return bi;
    });
    const head = `<tr><th>TYRE ORDER</th>${fixes.map(f => `<th>${f}</th>`).join('')}</tr>`;
    const rows = orders.map((o, oi) => `<tr><td><b>${o.order}</b></td>${o.scenarios.map((s, ci) =>
      `<td${best[ci] === oi ? ' style="color:#ffd700;font-weight:700"' : ''}>P${s.race_time_rank}</td>`).join('')}</tr>`).join('');
    return `<div class="meta-row" style="font-size:10px;margin-top:4px"><span>tyre order × pace fix — race-time rank · <span style="color:#ffd700">gold</span> = better order</span></div>
      <table class="results" style="font-size:10px">${head}${rows}</table>`;
  }

  function renderWhatifResult(r) {
    const out = document.getElementById('whatif-result');
    const es = editorState;
    const base = r.baseline.find(f => f.driver_number === es.driver_number);
    const mod = r.modified.find(f => f.driver_number === es.driver_number);
    if (!base || !mod) { out.innerHTML = '<span class="notice">driver not simulated (retired before anchor lap?)</span>'; return; }

    const dp = r.delta.position ?? 0, dg = r.delta.gap ?? 0;
    let verdict, cls;
    if (dp > 0)      { verdict = `▲ GAINS ${dp} PLACE${dp > 1 ? 'S' : ''}`; cls = 'delta-up'; }
    else if (dp < 0) { verdict = `▼ LOSES ${-dp} PLACE${dp < -1 ? 'S' : ''}`; cls = 'delta-down'; }
    else if (dg > 0.5)  { verdict = `SAME POSITION, ${dg.toFixed(1)}s FASTER`; cls = 'delta-up'; }
    else if (dg < -0.5) { verdict = `SAME POSITION, ${(-dg).toFixed(1)}s SLOWER`; cls = 'delta-down'; }
    else { verdict = 'NO MATERIAL CHANGE'; cls = ''; }

    const top8 = (rows) => rows.slice(0, 8).map(f =>
      `<td${f.driver_number === es.driver_number ? ' style="color:var(--red);font-weight:700"' : ''}>${f.acronym}</td>`).join('');

    out.innerHTML = `
      <div class="verdict ${cls}">${es.acronym}: ${verdict}</div>
      <div class="meta-row"><span>simulated from lap ${r.anchor_lap}</span>
        <span>modelled: P${base.predicted_position} → P${mod.predicted_position}</span>
        <span>gap to winner: ${base.predicted_gap}s → ${mod.predicted_gap}s</span></div>
      ${r.trace ? `<div style="margin:10px 0">${whatifTraceSVG(r.trace)}
        <div class="meta-row" style="font-size:10px"><span>race time vs an average-pace car from the divergence lap · <b style="color:#2f6fed">blue</b> = ${es.acronym} actual · <b>grey</b> = the field · <b style="color:#e8002d">red</b>/<b style="color:#ff8c00">amber</b>/<b style="color:#2ea44f">green</b> = edited plan with a 0/0.3/0.5s pace fix (P = race-time order) · gold bands = SC/VSC · lower = faster</span></div>
        ${whatifOrderTable(r.trace)}</div>` : ''}
      <table class="cmp-table">
        <tr><th>actual strategy (model)</th>${top8(r.baseline)}</tr>
        <tr><th>your strategy</th>${top8(r.modified)}</tr>
      </table>
      <div class="notice" style="font-size:10px">Both rows are model projections from the same lap-${r.anchor_lap} state, so the difference isolates the strategy change. All other drivers run their actual pit stops. Drivers who retired after lap ${r.anchor_lap} are simulated as finishing.</div>`;
  }

  loadRaces();
