(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const TYPE_COLOR = { SC: "var(--sc)", VSC: "var(--vsc)", REDFLAG: "var(--redflag)" };
  const TYPE_LABEL = { SC: "SC", VSC: "VSC", REDFLAG: "RED" };
  const TYPE_TAG_CLASS = { SC: "sc", VSC: "vsc", REDFLAG: "redflag" };

  const params = new URLSearchParams(location.search);
  const circuit = (params.get("circuit") || "baku").toLowerCase();

  const $ = (id) => document.getElementById(id);

  function el(tag, attrs, text) {
    const e = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }

  // A true hairpin (Monaco's Fairmont/Grand Hotel hairpin is the extreme
  // case, but every circuit has at least one tight corner) reverses
  // direction by upwards of 150 degrees in a small physical space. Fed
  // straight into the Catmull-Rom spline below, a single sparse vertex at
  // that kind of angle renders as a narrow pointed "V" wedge, not a rounded
  // loop -- there simply isn't enough point density there for the spline to
  // show the real curvature, no matter how the tangents are fit. Detour
  // sharp vertices (deflection angle past ANGLE_THRESHOLD_DEG) through a
  // real circular arc, tangent to both adjacent edges, and feed the spline
  // several sampled points along that arc instead of the one sharp vertex --
  // this is the standard "rounded polygon corner" construction (the same
  // idea as a rounded-rect corner), just applied per-vertex at whatever
  // angle that vertex actually turns through. Gentle corners (most of any
  // track) are far under the threshold and pass through untouched.
  function roundSharpCorners(points) {
    const ANGLE_THRESHOLD_DEG = 100;
    const EDGE_FRACTION = 0.35; // cap tangent distance to this fraction of the shorter adjacent edge
    const ARC_SAMPLES = 3;
    const n = points.length;
    const result = [];
    for (let i = 0; i < n; i++) {
      const prev = points[(i - 1 + n) % n], curr = points[i], next = points[(i + 1) % n];
      const ax = prev[1], ay = prev[2], bx = curr[1], by = curr[2], cx = next[1], cy = next[2];
      const v1x = bx - ax, v1y = by - ay, v2x = cx - bx, v2y = cy - by;
      const len1 = Math.hypot(v1x, v1y), len2 = Math.hypot(v2x, v2y);
      const dot = (v1x * v2x + v1y * v2y) / (len1 * len2 || 1);
      const deflectionDeg = Math.acos(Math.max(-1, Math.min(1, dot))) * 180 / Math.PI;
      if (deflectionDeg < ANGLE_THRESHOLD_DEG) { result.push(curr); continue; }

      // interior angle at the vertex, between (vertex->prev) and (vertex->next)
      const uax = ax - bx, uay = ay - by, wcx = cx - bx, wcy = cy - by;
      const ulen = Math.hypot(uax, uay), wlen = Math.hypot(wcx, wcy);
      const cosPhi = (uax * wcx + uay * wcy) / (ulen * wlen || 1);
      const phi = Math.acos(Math.max(-1, Math.min(1, cosPhi)));
      if (phi < 1e-3) { result.push(curr); continue; } // degenerate (near-180 straight-back), leave as-is

      const t = EDGE_FRACTION * Math.min(len1, len2);
      const r = t * Math.tan(phi / 2);
      const uax_n = uax / ulen, uay_n = uay / ulen, wcx_n = wcx / wlen, wcy_n = wcy / wlen;
      const T1x = bx + uax_n * t, T1y = by + uay_n * t;
      const T2x = bx + wcx_n * t, T2y = by + wcy_n * t;
      let bisx = uax_n + wcx_n, bisy = uay_n + wcy_n;
      const bisLen = Math.hypot(bisx, bisy) || 1;
      bisx /= bisLen; bisy /= bisLen;
      const centerDist = r / Math.sin(phi / 2);
      const Ox = bx + bisx * centerDist, Oy = by + bisy * centerDist;
      const a1 = Math.atan2(T1y - Oy, T1x - Ox), a2 = Math.atan2(T2y - Oy, T2x - Ox);
      let delta = a2 - a1;
      while (delta > Math.PI) delta -= 2 * Math.PI;
      while (delta < -Math.PI) delta += 2 * Math.PI;

      result.push([curr[0], T1x, T1y]);
      for (let s = 1; s <= ARC_SAMPLES; s++) {
        const a = a1 + delta * (s / (ARC_SAMPLES + 1));
        result.push([curr[0], Ox + r * Math.cos(a), Oy + r * Math.sin(a)]);
      }
      result.push([curr[0], T2x, T2y]);
    }
    return result;
  }

  // Straight-line segments between corner points read as an artificial,
  // faceted polygon no matter how many points are used -- real corners are
  // curved, not pointed, and stroke-linejoin:round only softens the joint at
  // a fixed radius scaled to stroke-width, not to the corner's real geometry.
  // Fit a closed centripetal Catmull-Rom spline through the points instead
  // (converted to cubic Bezier segments) so the track reads as a continuous
  // curve. Centripetal (alpha=0.5), not the simpler uniform parametrization,
  // specifically because point spacing here is wildly uneven -- long gaps on
  // straights, tightly clustered points through a hairpin -- and uniform
  // Catmull-Rom is prone to overshoot loops/cusps exactly in that situation.
  function pathFromPoints(rawPoints) {
    if (rawPoints.length < 3) {
      return rawPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p[1]},${p[2]}`).join(" ") + " Z";
    }
    const points = roundSharpCorners(rawPoints);
    const pts = points.map(p => [p[1], p[2]]);
    const n = pts.length;

    const alpha = 0.5;
    const at = (i) => pts[((i % n) + n) % n];
    const dist = (a, b) => Math.max(Math.hypot(b[0] - a[0], b[1] - a[1]), 1e-6);

    let d = `M ${pts[0][0]},${pts[0][1]}`;
    for (let i = 0; i < n; i++) {
      const p0 = at(i - 1), p1 = at(i), p2 = at(i + 1), p3 = at(i + 2);
      const t1 = Math.pow(dist(p0, p1), alpha);
      const t2 = t1 + Math.pow(dist(p1, p2), alpha);
      const t3 = t2 + Math.pow(dist(p2, p3), alpha);

      const m1x = (t2 - t1) * ((p1[0] - p0[0]) / t1 - (p2[0] - p0[0]) / t2 + (p2[0] - p1[0]) / (t2 - t1));
      const m1y = (t2 - t1) * ((p1[1] - p0[1]) / t1 - (p2[1] - p0[1]) / t2 + (p2[1] - p1[1]) / (t2 - t1));
      const m2x = (t2 - t1) * ((p2[0] - p1[0]) / (t2 - t1) - (p3[0] - p1[0]) / (t3 - t1) + (p3[0] - p2[0]) / (t3 - t2));
      const m2y = (t2 - t1) * ((p2[1] - p1[1]) / (t2 - t1) - (p3[1] - p1[1]) / (t3 - t1) + (p3[1] - p2[1]) / (t3 - t2));

      const c1x = p1[0] + m1x / 3, c1y = p1[1] + m1y / 3;
      const c2x = p2[0] - m2x / 3, c2y = p2[1] - m2y / 3;

      d += ` C ${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2[0]},${p2[1]}`;
    }
    return d + " Z";
  }

  function buildMap(svg, guide) {
    const [x0, y0, w, h] = guide.view_box;
    svg.setAttribute("viewBox", `${x0} ${y0} ${w} ${h}`);

    const d = pathFromPoints(guide.points);
    svg.appendChild(el("path", {
      d, fill: "none", stroke: "var(--ink-faint)", "stroke-width": 11,
      "stroke-linejoin": "round", "stroke-linecap": "round", opacity: 0.9,
    }));
    svg.appendChild(el("path", {
      d, fill: "none", stroke: "var(--panel-2)", "stroke-width": 6,
      "stroke-linejoin": "round", "stroke-linecap": "round",
    }));

    // start/finish
    const sf = guide.start_finish;
    if (sf) {
      const g = el("g", {});
      g.appendChild(el("line", { x1: sf.x1, y1: sf.y1, x2: sf.x2, y2: sf.y2, stroke: "var(--ink)", "stroke-width": 3 }));
      const t = el("text", { x: sf.label_x, y: sf.label_y, "font-family": "IBM Plex Mono", "font-size": 10, fill: "var(--ink-dim)" }, "START");
      g.appendChild(t);
      svg.appendChild(g);
    }

    // corner numbers
    const labelsG = el("g", { "font-family": "IBM Plex Mono", "font-size": 10.5, fill: "var(--ink-faint)" });
    for (const [label, lx, ly] of (guide.corner_labels || [])) {
      labelsG.appendChild(el("text", { x: lx, y: ly }, label));
    }
    svg.appendChild(labelsG);

    // highlight ring on the repeat flashpoint, if any
    if (guide.highlight_point) {
      svg.appendChild(el("circle", {
        cx: guide.highlight_point[0], cy: guide.highlight_point[1], r: 30,
        fill: "var(--sc)", opacity: 0.12,
      }));
    }

    // incidents: one marker per unique point, one stacked label per incident.
    // Stacked top-to-bottom in the same order as their real track position
    // (not authored order) so leader lines flow roughly parallel instead of
    // crossing every which way.
    const seenPoints = new Set();
    const leftX = 30, lineEndX = 300;
    let stackY = 16;
    const rowH = 46;

    const ordered = [...guide.incidents].sort((a, b) => a.point[1] - b.point[1]);
    for (const inc of ordered) {
      const [px, py] = inc.point;
      const key = `${px},${py}`;
      if (!seenPoints.has(key)) {
        seenPoints.add(key);
        const color = TYPE_COLOR[inc.type] || "var(--sc)";
        if (inc.type === "REDFLAG") {
          svg.appendChild(el("rect", {
            x: px - 8.5, y: py - 8.5, width: 17, height: 17,
            fill: color, stroke: "var(--ground)", "stroke-width": 2,
          }));
        } else {
          svg.appendChild(el("circle", {
            cx: px, cy: py, r: 9, fill: color, stroke: "var(--ground)", "stroke-width": 2,
          }));
        }
      }

      const color = TYPE_COLOR[inc.type] || "var(--sc)";
      const labelY = stackY;
      svg.appendChild(el("line", {
        x1: px, y1: py, x2: lineEndX, y2: labelY + 6,
        stroke: color, "stroke-width": 1.5, opacity: 0.85,
      }));

      const g = el("g", { transform: `translate(${leftX},${labelY})` });
      g.appendChild(el("text", {
        "font-family": "Big Shoulders Display", "font-weight": 700, "font-size": 15, fill: color,
      }, `${inc.year} · ${inc.corner_label}`));
      g.appendChild(el("text", {
        y: 16, "font-family": "IBM Plex Sans", "font-size": 10.5, fill: "var(--ink-dim)",
      }, `${inc.who}, lap ${inc.lap}. ${TYPE_LABEL[inc.type] || inc.type}.`));
      svg.appendChild(g);

      stackY += rowH;
    }
  }

  function renderPitLoss(container, pitLoss) {
    const rows = [
      ["Green flag", pitLoss.green, "var(--ink-faint)", pitLoss.green],
      ["Full Safety Car", pitLoss.sc, "var(--sc)", pitLoss.green],
      ["Virtual SC", pitLoss.vsc, "var(--vsc)", pitLoss.green],
      ["Red flag", pitLoss.redflag, "var(--redflag)", pitLoss.green],
    ];
    for (const [name, val, color, base] of rows) {
      const pct = Math.max(2, (val / base) * 100);
      const row = document.createElement("div");
      row.className = "pit-row";
      row.innerHTML = `
        <div class="pit-name">${name}</div>
        <div class="pit-bar-track"><div class="pit-bar" style="width:${pct}%;background:${color}"></div></div>
        <div class="pit-val">${val}s</div>`;
      container.appendChild(row);
    }
  }

  function renderIncidentRows(tbody, incidents) {
    for (const inc of incidents) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="yr">${inc.year}</td>
        <td>${inc.corner_label}</td>
        <td class="note">${inc.who}</td>
        <td class="lap">${inc.lap}</td>
        <td><span class="tag ${TYPE_TAG_CLASS[inc.type] || ""}">${TYPE_LABEL[inc.type] || inc.type}</span></td>`;
      tbody.appendChild(tr);
    }
  }

  async function main() {
    let guide;
    try {
      const res = await fetch(`/api/circuit_guide?circuit=${encodeURIComponent(circuit)}`);
      if (!res.ok) throw new Error(`${res.status}`);
      guide = await res.json();
    } catch (e) {
      $("loading").hidden = true;
      const err = $("error");
      err.hidden = false;
      err.textContent = `No circuit guide for "${circuit}" yet.`;
      return;
    }

    document.title = `${guide.name} — Circuit Guide`;
    const shortName = guide.name.replace(/\s*(Circuit|Street Circuit|International)\s*$/i, "");
    document.querySelector("#page h1").innerHTML =
      `Where <em>${shortName}</em><br>Goes Wrong.`;

    $("meta").innerHTML = `
      ${guide.location}<br>
      ${guide.corners} corners &middot; ${guide.length_km} km<br>
      <b>${guide.incidents.length} incidents on file</b>`;

    $("dek").innerHTML = guide.dek;
    $("map-title").textContent = guide.headline;

    buildMap($("map"), guide);

    renderPitLoss($("pitchart"), guide.pit_loss);
    $("pit-method").innerHTML =
      `Green/SC/VSC figures are circuit- and condition-measured from the live site's own strategy engine. ` +
      `Red flag = 0s is a regulatory fact (free tyre change under red flag), not necessarily something this circuit's own incidents include.`;

    renderIncidentRows($("incident-rows"), guide.incidents);

    $("method-note").innerHTML =
      `<b>Sourcing:</b> every incident here is individually verified against public race reporting ` +
      `(not derived from any live feed), for the corner, driver(s), lap and neutralisation type. ` +
      (guide.incidents_note || "");

    $("loading").hidden = true;
    $("page").hidden = false;
  }

  main();
})();
