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

  function pathFromPoints(points) {
    const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p[1]},${p[2]}`).join(" ") + " Z";
    return d;
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
