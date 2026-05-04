/* ── Constants ───────────────────────────────────────────────────────────────
   CAT_CONFIG and CAT_KEYS are injected by the template via inline <script>.
   DATE_MIN / DATE_MAX are also injected.
*/

const SCORE_COLORS = ['#f0f0f0', '#fee5d9', '#fcae91', '#fb6a4a', '#de2d26', '#a50f15', '#67000d'];

const BOROUGHS = { 1: 'Manhattan', 2: 'Bronx', 3: 'Brooklyn', 4: 'Queens', 5: 'Staten Island' };

function cdtaLabel(cdta) {
  const n = parseInt(cdta, 10);
  const boro = Math.floor(n / 100);
  const cd = n % 100;
  return `${BOROUGHS[boro] || 'NYC'} CD ${cd}`;
}

// ── State ─────────────────────────────────────────────────────────────────────

let currentDate = DATE_DEFAULT;
let selectedCats = new Set(CAT_KEYS.filter(k => k !== 'ventilation'));
let shiiData = {};
let geoLayer = null;
let playTimer = null;
let allDates = [];   // sorted list of available date strings (YYYY-MM-DD)

// ── Map init ──────────────────────────────────────────────────────────────────

const map = L.map('map', { zoomControl: false }).setView([40.71, -73.97], 11);
L.control.zoom({ position: 'topright' }).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; OSM contributors',
  maxZoom: 18,
}).addTo(map);

const loadingEl = document.createElement('div');
loadingEl.id = 'loading';
loadingEl.textContent = 'Loading…';
document.getElementById('map').appendChild(loadingEl);

// ── Colour helpers ────────────────────────────────────────────────────────────

function scoreColor(score, maxScore) {
  if (score === 0 || maxScore === 0) return SCORE_COLORS[0];
  const idx = Math.round((score / maxScore) * (SCORE_COLORS.length - 1));
  return SCORE_COLORS[Math.min(idx, SCORE_COLORS.length - 1)];
}

function featureStyle(feature) {
  const cdta = feature.properties.cdta;
  const d = shiiData[cdta];
  const score = d ? d.shii_total : 0;
  return {
    fillColor: scoreColor(score, selectedCats.size),
    fillOpacity: score > 0 ? 0.80 : 0.15,
    color: '#555',
    weight: 0.6,
    opacity: 0.7,
  };
}

function updateLegend() {
  const max = selectedCats.size;
  const el = document.getElementById('legend');
  if (max === 0) { el.innerHTML = '<div class="legend-row"><span class="swatch" style="background:#f0f0f0"></span><span>No categories selected</span></div>'; return; }
  let html = '';
  for (let i = 0; i <= max; i++) {
    const color = scoreColor(i, max);
    const label = i === 0 ? '0 — No signal' : i === max ? `${max} — All` : String(i);
    html += `<div class="legend-row"><span class="swatch" style="background:${color}"></span><span>${label}</span></div>`;
  }
  el.innerHTML = html;
}

// ── Tooltip ───────────────────────────────────────────────────────────────────

const tooltip = document.getElementById('tooltip');

function showTooltip(e, feature) {
  const cdta = feature.properties.cdta;
  const d = shiiData[cdta];
  if (!d) { tooltip.classList.add('hidden'); return; }

  const score = d.shii_total;
  const maxScore = selectedCats.size;

  let html = `<div class="tt-title">${cdtaLabel(cdta)}</div>`;
  html += `<div class="tt-score" style="color:${scoreColor(score, selectedCats.size)}">${score}</div>`;
  html += `<div class="tt-score-label">of ${maxScore} selected threshold${maxScore !== 1 ? 's' : ''} exceeded</div>`;
  html += `<div class="tt-cats">`;

  for (const key of CAT_KEYS) {
    const cfg = CAT_CONFIG[key];
    const flag = d.flags[key];
    const val = d.vals[key];
    const active = selectedCats.has(key) && flag;
    html += `
      <div class="tt-cat ${active ? '' : 'inactive'}">
        <span class="tt-cat-dot" style="background:${cfg.color}"></span>
        <span>${cfg.label}</span>
        <span class="tt-val">&nbsp;${val}/100k</span>
        ${flag ? '<span>✓</span>' : ''}
      </div>`;
  }
  html += `</div>`;

  tooltip.innerHTML = html;
  tooltip.classList.remove('hidden');
  moveTooltip(e);
}

function moveTooltip(e) {
  const raw = e.originalEvent || e;
  const x = raw.clientX;
  const y = raw.clientY;
  // Flip to left/above if near viewport edge
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  tooltip.style.left = (x + 230 > vw ? x - 234 : x + 14) + 'px';
  tooltip.style.top  = (y + 200 > vh ? y - 204 : y + 14) + 'px';
}

function hideTooltip() { tooltip.classList.add('hidden'); }

// ── GeoJSON layer ─────────────────────────────────────────────────────────────

async function loadGeometry() {
  const res = await fetch('/api/geometry');
  const geojson = await res.json();

  // Build sorted list of dates from DATE_MIN → DATE_MAX
  let d = new Date(DATE_MIN);
  const end = new Date(DATE_MAX);
  while (d <= end) {
    allDates.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }

  geoLayer = L.geoJSON(geojson, {
    style: featureStyle,
    onEachFeature(feature, layer) {
      layer.on({
        mousemove(e) { showTooltip(e, feature); },
        mouseout()   { hideTooltip(); },
        click()      { showTimeline(feature.properties.cdta); },
      });
    },
  }).addTo(map);
}

// ── SHII data fetch ───────────────────────────────────────────────────────────

async function fetchShii() {
  loadingEl.classList.remove('hidden');
  const cats = [...selectedCats].join(',');
  const res = await fetch(`/api/shii?date=${currentDate}&categories=${cats}`);
  const json = await res.json();
  shiiData = json.data || {};

  // Update temperature badge
  const tmaxEl = document.getElementById('tmax-badge');
  if (json.tmax != null) {
    tmaxEl.textContent = `🌡️ Max ${json.tmax}°C`;
  } else {
    tmaxEl.textContent = '';
  }

  if (geoLayer) geoLayer.setStyle(featureStyle);
  loadingEl.classList.add('hidden');
}

// ── Date navigation ───────────────────────────────────────────────────────────

function setDate(dateStr) {
  if (dateStr < DATE_MIN) dateStr = DATE_MIN;
  if (dateStr > DATE_MAX) dateStr = DATE_MAX;
  currentDate = dateStr;
  document.getElementById('date-picker').value = dateStr;
  fetchShii();
  if (selectedCdta) {
    // Reload data on year change; otherwise just move the annotation line
    if (currentDate.slice(0, 4) !== timelineYear) {
      showTimeline(selectedCdta);
    } else if (timelineChart) {
      const idx = currentDateIdx(timelineChart.data.labels);
      if (idx !== -1) {
        const ann = timelineChart.options.plugins.annotation.annotations.currentDate;
        ann.xMin = idx;
        ann.xMax = idx;
      }
      timelineChart.update('none');
    }
  }
}

function stepDate(delta) {
  const idx = allDates.indexOf(currentDate);
  if (idx === -1) return;
  const newIdx = Math.max(0, Math.min(allDates.length - 1, idx + delta));
  setDate(allDates[newIdx]);
}

document.getElementById('date-picker').addEventListener('change', e => setDate(e.target.value));
document.getElementById('btn-prev').addEventListener('click', () => stepDate(-1));
document.getElementById('btn-next').addEventListener('click', () => stepDate(+1));

document.addEventListener('keydown', e => {
  if (document.activeElement.tagName === 'INPUT') return;
  if (e.key === 'ArrowLeft')  stepDate(-1);
  if (e.key === 'ArrowRight') stepDate(+1);
});

// ── Play animation ────────────────────────────────────────────────────────────

const btnPlay = document.getElementById('btn-play');

btnPlay.addEventListener('click', () => {
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
    btnPlay.textContent = '▶ Play';
    btnPlay.classList.remove('playing');
  } else {
    // If at the end, restart from beginning
    if (currentDate === DATE_MAX) setDate(DATE_MIN);
    btnPlay.textContent = '⏸ Pause';
    btnPlay.classList.add('playing');
    playTimer = setInterval(() => {
      if (currentDate >= DATE_MAX) {
        clearInterval(playTimer);
        playTimer = null;
        btnPlay.textContent = '▶ Play';
        btnPlay.classList.remove('playing');
        return;
      }
      stepDate(+1);
    }, 350);
  }
});

// ── Category toggles ──────────────────────────────────────────────────────────

function updateCategories() {
  selectedCats = new Set(
    [...document.querySelectorAll('.cat-cb:checked')].map(el => el.dataset.key)
  );
  updateLegend();
  fetchShii();
  if (selectedCdta) showTimeline(selectedCdta);
}

document.querySelectorAll('.cat-cb').forEach(cb =>
  cb.addEventListener('change', updateCategories)
);

document.getElementById('btn-all').addEventListener('click', () => {
  document.querySelectorAll('.cat-cb').forEach(cb => cb.checked = true);
  updateCategories();
});

document.getElementById('btn-none').addEventListener('click', () => {
  document.querySelectorAll('.cat-cb').forEach(cb => cb.checked = false);
  updateCategories();
});


// ── Timeline ──────────────────────────────────────────────────────────────────

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

let timelineChart = null;
let selectedCdta = null;
let timelineYear = null;

function currentDateIdx(labels) {
  let idx = labels.indexOf(currentDate);
  if (idx === -1) {
    for (let i = labels.length - 1; i >= 0; i--) {
      if (labels[i] <= currentDate) { idx = i; break; }
    }
  }
  return idx;
}

async function showTimeline(cdta) {
  selectedCdta = cdta;
  const year = currentDate.slice(0, 4);
  timelineYear = year;
  const cats = [...selectedCats].join(',');

  document.getElementById('timeline-title').textContent = `${cdtaLabel(cdta)} — ${year}`;
  document.getElementById('timeline-panel').classList.remove('hidden');

  const res = await fetch(`/api/timeline?cdta=${cdta}&year=${year}&categories=${cats}`);
  const json = await res.json();
  renderTimeline(json.data);
}

function renderTimeline(data) {
  const dates  = data.map(d => d.date);
  const scores = data.map(d => d.shii);
  const tmax   = data.map(d => d.tmax);
  const max    = selectedCats.size;
  const colors = scores.map(s => scoreColor(s, max));

  if (timelineChart) { timelineChart.destroy(); timelineChart = null; }
  // Replace canvas to avoid stale context after destroy
  const wrap = document.getElementById('timeline-chart-wrap');
  wrap.innerHTML = '<canvas id="timeline-chart"></canvas>';
  const ctx = document.getElementById('timeline-chart').getContext('2d');

  timelineChart = new Chart(ctx, {
    data: {
      labels: dates,
      datasets: [
        {
          type: 'bar',
          label: 'SHII Score',
          data: scores,
          backgroundColor: colors,
          borderWidth: 0,
          barPercentage: 1.0,
          categoryPercentage: 1.0,
          yAxisID: 'y',
          order: 2,
        },
        {
          type: 'line',
          label: 'Max Temp (°C)',
          data: tmax,
          borderColor: '#222',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
          yAxisID: 'yTemp',
          fill: false,
          order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            title: items => items[0]?.label ?? '',
            label: item => item.dataset.label + ': ' + item.raw,
          },
        },
        annotation: {
          annotations: {
            currentDate: {
              type: 'line',
              xMin: currentDateIdx(dates),
              xMax: currentDateIdx(dates),
              borderColor: 'rgba(0,0,0,0.7)',
              borderWidth: 2,
              borderDash: [4, 3],
            },
          },
        },
      },
      scales: {
        x: {
          ticks: {
            maxRotation: 0,
            callback(_, i) {
              const d = dates[i];
              return d && d.slice(8) === '01' ? MONTHS[parseInt(d.slice(5, 7)) - 1] : '';
            },
          },
          grid: { display: false },
        },
        y: {
          min: 0,
          max: Math.max(max, 1),
          ticks: { stepSize: 1 },
          title: { display: true, text: 'SHII', font: { size: 10 } },
        },
        yTemp: {
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: true, text: '°C', font: { size: 10 } },
        },
      },
    },
  });
}

function closeTimeline() {
  selectedCdta = null;
  timelineYear = null;
  document.getElementById('timeline-panel').classList.add('hidden');
  if (timelineChart) { timelineChart.destroy(); timelineChart = null; }
}

document.getElementById('timeline-close').addEventListener('click', closeTimeline);

// ── Sidebar toggle ────────────────────────────────────────────────────────────

const btnToggle = document.getElementById('btn-sidebar-toggle');
btnToggle.addEventListener('click', () => {
  const collapsed = document.body.classList.toggle('sidebar-collapsed');
  btnToggle.innerHTML = collapsed ? '&#8250;' : '&#8249;';
  setTimeout(() => map.invalidateSize(), 310);
});

// ── Bootstrap ─────────────────────────────────────────────────────────────────

(async () => {
  updateLegend();
  await loadGeometry();
  document.getElementById('date-picker').value = DATE_DEFAULT;
  await fetchShii();
})();
