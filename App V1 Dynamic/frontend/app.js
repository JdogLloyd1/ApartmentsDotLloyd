// Alewife Apartment Intelligence Dashboard
// Client-side controller. Fetches building data + isochrones from the
// backend, renders the Leaflet map and table, and wires filter/sort
// controls.

import {
  walkIsoPolygons,
  driveIsoPolygons,
  anchorPoints,
} from './isochrones.js';

const state = {
  buildings: [],
  markers: {},
  map: null,
  activeRow: null,
  sort: { key: 'score', asc: false },
};

const SCORE_HIGH = 65;
const SCORE_MID = 48;
const RATING_HIGH = 4.4;
const RATING_MID = 3.8;
const WALK_FAST = 5;
const WALK_SLOW = 12;
const DRIVE_FAST = 2;
const DRIVE_SLOW = 6;
const HIGHLIGHT_AMENITIES = new Set(['W/D in unit', 'Shuttle to T', 'Gym']);

// ─── API helpers ──────────────────────────────────────────────────────────

function buildUrlForApi(path) {
  const override = window.ALEWIFE_API_ORIGIN;
  const origin = override || window.location.origin;
  return `${origin.replace(/\/$/, '')}${path}`;
}

async function loadBuildings() {
  const response = await fetch(buildUrlForApi('/api/buildings'));
  if (!response.ok) {
    throw new Error(`Failed to load buildings: HTTP ${response.status}`);
  }
  const ageHeader = response.headers.get('X-Data-Freshness');
  const buildings = await response.json();
  return { buildings, freshnessSeconds: ageHeader ? Number(ageHeader) : null };
}

async function loadIsochrones() {
  try {
    const response = await fetch(buildUrlForApi('/api/isochrones'));
    if (!response.ok) {
      return null;
    }
    const data = await response.json();
    if (!data.walk?.length && !data.drive?.length) {
      return null;
    }
    return data;
  } catch (err) {
    console.warn('Live isochrones unavailable, falling back to static polygons', err);
    return null;
  }
}

// ─── Map setup ────────────────────────────────────────────────────────────

function initMap() {
  const map = L.map('map', { center: [42.401, -71.147], zoom: 13 });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap',
    maxZoom: 18,
  }).addTo(map);
  return map;
}

const ISO_STYLES = {
  walk: {
    15: { color: '#2a6fa8', fill: 0.08, weight: 1,   dash: '6 4' },
    10: { color: '#3d8fd9', fill: 0.12, weight: 1,   dash: null },
    5:  { color: '#58a6ff', fill: 0.22, weight: 1.5, dash: null },
  },
  drive: {
    10: { color: '#8a2c28', fill: 0.06, weight: 1,   dash: '6 4' },
    5:  { color: '#c4403a', fill: 0.12, weight: 1,   dash: null },
    2:  { color: '#f85149', fill: 0.25, weight: 1.5, dash: null },
  },
};

function renderLiveIsochrones(map, data) {
  const buckets = [
    ...data.walk.map((f) => ({ ...f, style: ISO_STYLES.walk[f.minutes] })),
    ...data.drive.map((f) => ({ ...f, style: ISO_STYLES.drive[f.minutes] })),
  ];
  buckets
    .filter((b) => b.style)
    .sort((a, b) => b.minutes - a.minutes)
    .forEach(({ geojson, style }) => {
      L.geoJSON(geojson, {
        style: {
          color: style.color,
          fillColor: style.color,
          fillOpacity: style.fill,
          weight: style.weight,
          dashArray: style.dash,
          opacity: 0.85,
        },
      }).addTo(map);
    });
}

function renderStaticIsochrones(map) {
  const asLatLng = (poly) => poly.map(([lat, lng]) => [lat, lng]);
  const walkLayers = [
    { poly: walkIsoPolygons.w15, ...ISO_STYLES.walk[15] },
    { poly: walkIsoPolygons.w10, ...ISO_STYLES.walk[10] },
    { poly: walkIsoPolygons.w5,  ...ISO_STYLES.walk[5] },
  ];
  const driveLayers = [
    { poly: driveIsoPolygons.d10, ...ISO_STYLES.drive[10] },
    { poly: driveIsoPolygons.d5,  ...ISO_STYLES.drive[5] },
    { poly: driveIsoPolygons.d2,  ...ISO_STYLES.drive[2] },
  ];
  [...walkLayers, ...driveLayers].forEach(({ poly, color, fill, weight, dash }) => {
    L.polygon(asLatLng(poly), {
      color,
      fillColor: color,
      fillOpacity: fill,
      weight,
      dashArray: dash,
      opacity: 0.85,
    }).addTo(map);
  });
}

function renderIsochrones(map, liveData) {
  if (liveData) {
    renderLiveIsochrones(map, liveData);
  } else {
    renderStaticIsochrones(map);
  }
}

function renderAnchors(map) {
  const tIcon = L.divIcon({
    className: '',
    html: `<div style="background:#58a6ff;color:#0d1117;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:bold;border:2px solid #0d1117;box-shadow:0 2px 10px rgba(0,0,0,0.7);font-family:'IBM Plex Sans',sans-serif;">T</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
  L.marker(anchorPoints.alewifeT, { icon: tIcon }).addTo(map).bindPopup(
    '<div class="popup-name">Alewife MBTA</div><div class="popup-detail">Red Line Terminus &middot; Cambridge, MA</div>'
  );

  const rtIcon = L.divIcon({
    className: '',
    html: `<div style="background:#f85149;color:#fff;width:26px;height:26px;border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:bold;border:2px solid #0d1117;box-shadow:0 2px 8px rgba(0,0,0,0.7);font-family:'IBM Plex Mono',monospace;">2</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
  L.marker(anchorPoints.rt2Ramp, { icon: rtIcon }).addTo(map).bindPopup(
    '<div class="popup-name">Route 2 On-Ramp</div><div class="popup-detail">Concord Tpke at Alewife Brook Pkwy</div>'
  );
}

function renderMarkers(map, buildings) {
  state.markers = {};
  buildings.forEach((b) => {
    const col = scoreColor(b.score);
    const icon = L.divIcon({
      className: '',
      html: `<div style="background:${col};color:#0d1117;width:24px;height:24px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;border:1.5px solid rgba(0,0,0,0.6);box-shadow:0 2px 8px rgba(0,0,0,0.6);font-family:'IBM Plex Mono',monospace;cursor:pointer;">${b.score}</div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    const priceLabel = b.oneBR ? `$${formatNumber(b.oneBR)}/mo 1BR` : 'Call for pricing';
    const popup = `<div class="popup-name">${escape(b.name)}</div>
      <div class="popup-detail">${escape(b.address)}</div>
      <div class="popup-rating">${b.rating ?? '-'} &middot; ${b.rc ?? 0} reviews</div>
      <div class="popup-detail">${b.walk ?? '-'} min to T &middot; ${b.drive ?? '-'} min to Rt.2</div>
      <div class="popup-price">${priceLabel}</div>
      <div class="popup-score">Score: ${b.score}/100</div>`;
    state.markers[b.slug] = L.marker([b.lat, b.lng], { icon }).addTo(map).bindPopup(popup);
  });
}

// ─── Table ────────────────────────────────────────────────────────────────

function scoreColor(score) {
  if (score >= SCORE_HIGH) return '#3fb950';
  if (score >= SCORE_MID)  return '#d29922';
  return '#f85149';
}

function scoreClass(score) {
  if (score >= SCORE_HIGH) return 'sh';
  if (score >= SCORE_MID)  return 'sm';
  return 'sl';
}

function ratingClass(rating) {
  if (rating >= RATING_HIGH) return 'r-high';
  if (rating >= RATING_MID)  return 'r-mid';
  return 'r-low';
}

function timeClass(minutes, fastCap, slowCap) {
  if (minutes <= fastCap) return 'tf';
  if (minutes <= slowCap) return 'tm';
  return 'ts';
}

function formatNumber(n) {
  return n.toLocaleString();
}

function escape(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatPrice(price, source) {
  if (!price) return '<span class="pna">&mdash;</span>';
  const src = source ? `<span class="price-source">${escape(source)}</span>` : '';
  return `<span class="pv">$${formatNumber(price)}</span>${src}`;
}

function filterBuildings(buildings) {
  const maxWalk  = parseInt(document.getElementById('maxWalk').value, 10) || Infinity;
  const maxDrive = parseInt(document.getElementById('maxDrive').value, 10) || Infinity;
  const maxPrice = parseInt(document.getElementById('maxPrice').value, 10) || Infinity;
  return buildings.filter((b) => {
    const walk = b.walk ?? 0;
    const drive = b.drive ?? 0;
    if (walk > maxWalk) return false;
    if (drive > maxDrive) return false;
    if (b.oneBR && b.oneBR > maxPrice) return false;
    return true;
  });
}

function sortBuildings(buildings) {
  const { key, asc } = state.sort;
  const pick = (b) => {
    switch (key) {
      case 'name':     return b.name ?? '';
      case 'address':  return b.address ?? '';
      case 'rating':   return b.rating ?? 0;
      case 'walk':     return b.walk ?? Infinity;
      case 'drive':    return b.drive ?? Infinity;
      case 'price1br': return b.oneBR ?? Infinity;
      case 'price2br': return b.twoBR ?? Infinity;
      case 'studio':   return b.studio ?? Infinity;
      default:         return b.score ?? 0;
    }
  };
  return [...buildings].sort((a, b) => {
    const va = pick(a);
    const vb = pick(b);
    if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
    return asc ? va - vb : vb - va;
  });
}

function buildRow(b) {
  const tr = document.createElement('tr');
  tr.dataset.slug = b.slug;
  const amenityTags = (b.amenities ?? [])
    .map((am) => {
      const hl = HIGHLIGHT_AMENITIES.has(am) ? ' hl' : '';
      return `<span class="atag${hl}">${escape(am)}</span>`;
    })
    .join('');
  const walk = b.walk ?? 0;
  const drive = b.drive ?? 0;
  tr.innerHTML = `
    <td><div class="cell-name">${escape(b.name)}<span class="nbhd">${escape(b.nbhd)}</span></div></td>
    <td class="cell-address">${escape(b.address)}</td>
    <td><div class="rating"><div class="rdot ${ratingClass(b.rating ?? 0)}"></div>${b.rating ?? '-'} <span style="color:var(--muted);font-size:10px">(${b.rc ?? 0})</span></div></td>
    <td class="cell-overview">${escape(b.overview)}</td>
    <td><div class="amenity-list">${amenityTags}</div></td>
    <td class="cell-price">${formatPrice(b.studio, b.studioSrc)}</td>
    <td class="cell-price">${formatPrice(b.oneBR,  b.oneBRSrc)}</td>
    <td class="cell-price">${formatPrice(b.twoBR,  b.twoBRSrc)}</td>
    <td class="time-cell ${timeClass(walk, WALK_FAST, WALK_SLOW)}">${walk} min</td>
    <td class="time-cell ${timeClass(drive, DRIVE_FAST, DRIVE_SLOW)}">${drive} min</td>
    <td class="link-cell">${b.website ? `<a href="${escape(b.website)}" target="_blank" rel="noopener">${escape(b.wlabel ?? b.website)}</a>` : ''}</td>
    <td class="score-cell"><div class="score-wrap ${scoreClass(b.score)}"><div class="score-num">${b.score}</div><div class="score-bar"><div class="score-bar-fill" style="width:${b.score}%"></div></div></div></td>
  `;

  tr.addEventListener('click', () => focusBuilding(tr, b));
  return tr;
}

function focusBuilding(row, building) {
  if (state.activeRow) state.activeRow.classList.remove('active-row');
  row.classList.add('active-row');
  state.activeRow = row;
  const marker = state.markers[building.slug];
  if (!marker) return;
  state.map.flyTo([building.lat, building.lng], 15, { duration: 0.8 });
  setTimeout(() => marker.openPopup(), 900);
  document.getElementById('map').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function renderTable() {
  const visible = sortBuildings(filterBuildings(state.buildings));
  const tbody = document.getElementById('tableBody');
  tbody.replaceChildren(...visible.map(buildRow));

  document.querySelectorAll('th[data-sort]').forEach((th) => {
    th.classList.toggle('sorted', th.dataset.sort === state.sort.key);
  });
}

// ─── Controls wiring ──────────────────────────────────────────────────────

function wireControls() {
  document.getElementById('sortSelect').addEventListener('change', (event) => {
    state.sort.key = event.target.value;
    state.sort.asc = ['name', 'address'].includes(state.sort.key);
    renderTable();
  });

  ['maxWalk', 'maxDrive', 'maxPrice'].forEach((id) => {
    document.getElementById(id).addEventListener('input', renderTable);
  });

  document.querySelectorAll('th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.asc = !state.sort.asc;
      } else {
        state.sort.key = key;
        state.sort.asc = ['name', 'address'].includes(key);
      }
      document.getElementById('sortSelect').value = key;
      renderTable();
    });
  });
}

// ─── Bootstrap ────────────────────────────────────────────────────────────

function formatFreshness(seconds) {
  if (seconds === null || Number.isNaN(seconds)) return 'Freshness: \u2014';
  if (seconds < 60) return `Fresh (${Math.max(0, Math.floor(seconds))}s)`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Fresh ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Fresh ${hours}h ago`;
  return `Fresh ${Math.floor(hours / 24)}d ago`;
}

function updateFreshnessChip(seconds) {
  const chip = document.getElementById('freshnessChip');
  if (!chip) return;
  chip.textContent = formatFreshness(seconds);
  chip.classList.toggle('badge-warn', typeof seconds === 'number' && seconds > 6 * 3600);
  chip.classList.toggle('badge-muted', !(typeof seconds === 'number' && seconds > 6 * 3600));
}

async function triggerManualRefresh() {
  const button = document.getElementById('refreshButton');
  const token = window.ALEWIFE_REFRESH_TOKEN;
  if (!token) {
    alert('Set window.ALEWIFE_REFRESH_TOKEN in the page to enable manual refresh.');
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = 'Refreshing\u2026';
  }
  try {
    const response = await fetch(buildUrlForApi('/api/refresh'), {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    setTimeout(() => window.location.reload(), 1500);
  } catch (err) {
    console.error('Manual refresh failed', err);
    alert(`Refresh failed: ${err.message}`);
    if (button) {
      button.disabled = false;
      button.textContent = 'Refresh now';
    }
  }
}

function wireRefreshButton() {
  const button = document.getElementById('refreshButton');
  if (!button) return;
  if (window.ALEWIFE_REFRESH_TOKEN) {
    button.hidden = false;
    button.addEventListener('click', triggerManualRefresh);
  }
}

async function main() {
  state.map = initMap();
  renderAnchors(state.map);
  wireControls();
  wireRefreshButton();

  const [result, isochrones] = await Promise.all([
    loadBuildings().catch((err) => {
      document.getElementById('sectionSub').textContent = `Failed to load data: ${err.message}`;
      console.error(err);
      return null;
    }),
    loadIsochrones(),
  ]);
  if (!result) return;
  state.buildings = result.buildings;
  updateFreshnessChip(result.freshnessSeconds);

  renderIsochrones(state.map, isochrones);
  document.getElementById('buildingCountBadge').textContent = `${state.buildings.length} Buildings`;
  document.getElementById('sectionSub').textContent =
    `Score: cost 30% \u00b7 rating 25% \u00b7 walk 25% \u00b7 drive 20%`;

  renderMarkers(state.map, state.buildings);
  renderTable();
}

window.addEventListener('DOMContentLoaded', () => {
  main().catch((err) => {
    console.error('Dashboard bootstrap failed', err);
  });
});
