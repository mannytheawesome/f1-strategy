  const TOKEN_KEY = 'f1_admin_token';
  let currentDays = 30;

  function getToken() { return localStorage.getItem(TOKEN_KEY); }

  async function fetchStats(days) {
    const res = await fetch(`/api/admin/stats?days=${days}`, {
      headers: { 'X-Admin-Token': getToken() },
    });
    if (res.status === 403) throw new Error('forbidden');
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  function showGate(errorMsg) {
    document.getElementById('gate').style.display = 'flex';
    document.getElementById('dashboard').style.display = 'none';
    document.getElementById('gate-error').textContent = errorMsg || '';
  }

  function showDashboard() {
    document.getElementById('gate').style.display = 'none';
    document.getElementById('dashboard').style.display = 'block';
  }

  async function tryUnlock(token) {
    localStorage.setItem(TOKEN_KEY, token);
    try {
      const stats = await fetchStats(currentDays);
      showDashboard();
      render(stats);
    } catch (e) {
      localStorage.removeItem(TOKEN_KEY);
      showGate(e.message === 'forbidden' ? 'Invalid token.' : `Failed to load: ${e.message}`);
    }
  }

  function tile(n, label) {
    return `<div class="card tile"><div class="n">${n}</div><div class="l">${label}</div></div>`;
  }

  function barRows(items, colour) {
    if (!items.length) return '<div class="notice">Nothing yet.</div>';
    const max = Math.max(...items.map(i => i.count), 1);
    return items.map(i => `
      <div class="bar-row">
        <span class="bar-label" title="${i.label || i.page}">${i.label || i.page}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${(i.count / max * 100).toFixed(1)}%;background:${colour}"></div></div>
        <span class="bar-count">${i.count}</span>
      </div>`).join('');
  }

  function dailyChart(daily) {
    if (!daily.length) return '<div class="notice">No pageviews in this window yet.</div>';
    const max = Math.max(...daily.map(d => d.pageviews), 1);
    const bars = daily.map(d =>
      `<div class="daily-bar" style="height:${Math.max(d.pageviews / max * 100, 2)}%" title="${d.date}: ${d.pageviews} views, ${d.unique_visitors} visitors"></div>`
    ).join('');
    return `<div class="daily-chart">${bars}</div>
      <div class="daily-axis"><span>${daily[0].date}</span><span>${daily[daily.length - 1].date}</span></div>`;
  }

  function eventsTable(recent) {
    if (!recent.length) return '<div class="notice">No events yet.</div>';
    const rows = recent.map(e => `<tr>
      <td>${e.ts.replace('T', ' ').slice(0, 19)}</td>
      <td class="et-${e.event_type}">${e.event_type}</td>
      <td>${e.page || ''}</td>
      <td>${e.label || ''}</td>
    </tr>`).join('');
    return `<table class="events"><tr><th>TIME (UTC)</th><th>TYPE</th><th>PAGE</th><th>LABEL</th></tr>${rows}</table>`;
  }

  function render(s) {
    const content = document.getElementById('content');
    content.innerHTML = `
      <div class="tile-row">
        ${tile(s.total_visitors, 'total visitors')}
        ${tile(s.visitors_today, 'visitors today')}
        ${tile(s.visitors_7d, 'visitors, last 7d')}
        ${tile(s.total_events, 'total events')}
      </div>
      <div class="card" style="margin-bottom:12px">
        <h2>Daily pageviews</h2>
        ${dailyChart(s.daily)}
      </div>
      <div class="grid-2">
        <div class="card">
          <h2>Pageviews by page</h2>
          ${barRows(s.pageviews_by_page.map(p => ({ label: p.page, count: p.count })), 'var(--green)')}
        </div>
        <div class="card">
          <h2>Most-viewed races</h2>
          ${barRows(s.top_races, 'var(--purple)')}
        </div>
        <div class="card">
          <h2>Most-used features</h2>
          ${barRows(s.top_features, '#ffd700')}
        </div>
      </div>
      <div class="card">
        <h2>Recent activity</h2>
        ${eventsTable(s.recent)}
      </div>`;
  }

  document.getElementById('unlock-btn').onclick = () => {
    const token = document.getElementById('token-input').value.trim();
    if (token) tryUnlock(token);
  };
  document.getElementById('token-input').onkeydown = e => {
    if (e.key === 'Enter') document.getElementById('unlock-btn').click();
  };
  document.getElementById('signout-btn').onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    showGate();
  };
  document.querySelectorAll('.days-select button').forEach(btn => {
    btn.onclick = async () => {
      document.querySelectorAll('.days-select button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentDays = parseInt(btn.dataset.days);
      try { render(await fetchStats(currentDays)); }
      catch (e) { showGate('Session expired — re-enter token.'); }
    };
  });

  const saved = getToken();
  if (saved) tryUnlock(saved); else showGate();
