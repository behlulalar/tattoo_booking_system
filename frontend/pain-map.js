/**
 * İnteraktif acı haritası — manus_art_tattoo_web PainMap.tsx portu
 */
(function () {
  const PAIN_ZONES = [
    { id: 'head', label: 'Kafa', pain: 4, x: 148, y: 22, w: 34, h: 34 },
    { id: 'neck', label: 'Boyun', pain: 3, x: 152, y: 58, w: 26, h: 18 },
    { id: 'shoulder-l', label: 'Sol Omuz', pain: 2, x: 112, y: 78, w: 34, h: 20 },
    { id: 'shoulder-r', label: 'Sağ Omuz', pain: 2, x: 184, y: 78, w: 34, h: 20 },
    { id: 'chest', label: 'Göğüs', pain: 3, x: 140, y: 85, w: 50, h: 35 },
    { id: 'sternum', label: 'Sternum', pain: 4, x: 155, y: 95, w: 20, h: 25 },
    { id: 'upper-arm-l', label: 'Sol Üst Kol', pain: 2, x: 96, y: 100, w: 22, h: 45 },
    { id: 'upper-arm-r', label: 'Sağ Üst Kol', pain: 2, x: 212, y: 100, w: 22, h: 45 },
    { id: 'ribs-l', label: 'Sol Kaburga', pain: 4, x: 124, y: 110, w: 20, h: 30 },
    { id: 'ribs-r', label: 'Sağ Kaburga', pain: 4, x: 186, y: 110, w: 20, h: 30 },
    { id: 'abs', label: 'Karın', pain: 3, x: 145, y: 125, w: 40, h: 30 },
    { id: 'forearm-l', label: 'Sol Ön Kol', pain: 2, x: 80, y: 150, w: 20, h: 50 },
    { id: 'forearm-r', label: 'Sağ Ön Kol', pain: 2, x: 230, y: 150, w: 20, h: 50 },
    { id: 'wrist-l', label: 'Sol Bilek', pain: 3, x: 70, y: 200, w: 18, h: 15 },
    { id: 'wrist-r', label: 'Sağ Bilek', pain: 3, x: 242, y: 200, w: 18, h: 15 },
    { id: 'hand-l', label: 'Sol El', pain: 4, x: 60, y: 215, w: 22, h: 22 },
    { id: 'hand-r', label: 'Sağ El', pain: 4, x: 248, y: 215, w: 22, h: 22 },
    { id: 'hip', label: 'Kalça', pain: 3, x: 140, y: 160, w: 50, h: 25 },
    { id: 'thigh-l', label: 'Sol Uyluk', pain: 2, x: 125, y: 190, w: 30, h: 55 },
    { id: 'thigh-r', label: 'Sağ Uyluk', pain: 2, x: 175, y: 190, w: 30, h: 55 },
    { id: 'knee-l', label: 'Sol Diz', pain: 4, x: 128, y: 248, w: 24, h: 20 },
    { id: 'knee-r', label: 'Sağ Diz', pain: 4, x: 178, y: 248, w: 24, h: 20 },
    { id: 'calf-l', label: 'Sol Baldır', pain: 2, x: 125, y: 270, w: 25, h: 50 },
    { id: 'calf-r', label: 'Sağ Baldır', pain: 2, x: 180, y: 270, w: 25, h: 50 },
    { id: 'ankle-l', label: 'Sol Ayak Bileği', pain: 4, x: 127, y: 322, w: 20, h: 15 },
    { id: 'ankle-r', label: 'Sağ Ayak Bileği', pain: 4, x: 183, y: 322, w: 20, h: 15 },
    { id: 'foot-l', label: 'Sol Ayak', pain: 4, x: 120, y: 338, w: 25, h: 18 },
    { id: 'foot-r', label: 'Sağ Ayak', pain: 4, x: 185, y: 338, w: 25, h: 18 },
  ];

  const PAIN_COLORS = {
    1: 'rgba(34, 197, 94, 0.55)',
    2: 'rgba(250, 204, 21, 0.55)',
    3: 'rgba(249, 115, 22, 0.55)',
    4: 'rgba(239, 68, 68, 0.55)',
  };

  const PAIN_COLORS_SOLID = {
    1: 'rgba(34, 197, 94, 1)',
    2: 'rgba(250, 204, 21, 1)',
    3: 'rgba(249, 115, 22, 1)',
    4: 'rgba(239, 68, 68, 1)',
  };

  const PAIN_LABELS = {
    1: 'Düşük Acı',
    2: 'Orta Acı',
    3: 'Yüksek Acı',
    4: 'Çok Yüksek Acı',
  };

  /** PainMap zone id → backend region id */
  const PAIN_MAP_TO_REGION = {
    head: 'head',
    neck: 'neck',
    'shoulder-l': 'shoulder',
    'shoulder-r': 'shoulder',
    chest: 'chest',
    sternum: 'chest',
    'upper-arm-l': 'upper_arm',
    'upper-arm-r': 'upper_arm',
    'ribs-l': 'ribs',
    'ribs-r': 'ribs',
    abs: 'stomach',
    'forearm-l': 'forearm',
    'forearm-r': 'forearm',
    'wrist-l': 'wrist',
    'wrist-r': 'wrist',
    'hand-l': 'hand',
    'hand-r': 'hand',
    hip: 'thigh',
    'thigh-l': 'thigh',
    'thigh-r': 'thigh',
    'knee-l': 'knee',
    'knee-r': 'knee',
    'calf-l': 'calf',
    'calf-r': 'calf',
    'ankle-l': 'ankle',
    'ankle-r': 'ankle',
    'foot-l': 'foot',
    'foot-r': 'foot',
  };

  const SVG_NS = 'http://www.w3.org/2000/svg';

  let selectedRegionId = '';
  let hoveredZoneId = null;
  let onSelectCallback = null;
  let onHoverCallback = null;
  let rootEl = null;
  let tooltipEl = null;
  let zoneEls = {};

  function regionToZoneIds(regionId) {
    if (!regionId) return [];
    return PAIN_ZONES.filter((z) => PAIN_MAP_TO_REGION[z.id] === regionId).map((z) => z.id);
  }

  function getZoneById(zoneId) {
    return PAIN_ZONES.find((z) => z.id === zoneId) || null;
  }

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
  }

  function buildBodySilhouette(parent) {
    const outline = svgEl('g', { class: 'pain-map-outline', 'aria-hidden': 'true' });
    outline.appendChild(svgEl('ellipse', { cx: 165, cy: 38, rx: 22, ry: 26, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('rect', { x: 152, y: 56, width: 26, height: 20, rx: 6, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('path', {
      d: 'M 115 78 Q 165 68 215 78 L 225 100 Q 225 150 225 150 L 210 150 L 210 100 Q 165 90 120 100 L 120 150 L 105 150 Q 105 150 105 100 Z',
      fill: 'url(#painMapBodyGrad)',
      stroke: 'rgba(201,168,108,0.35)',
      'stroke-width': 1,
    }));
    outline.appendChild(svgEl('rect', { x: 126, y: 82, width: 78, height: 80, rx: 8, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('rect', { x: 96, y: 98, width: 24, height: 50, rx: 10, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('rect', { x: 210, y: 98, width: 24, height: 50, rx: 10, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('rect', { x: 82, y: 145, width: 22, height: 55, rx: 8, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('rect', { x: 226, y: 145, width: 22, height: 55, rx: 8, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('ellipse', { cx: 73, cy: 225, rx: 14, ry: 12, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('ellipse', { cx: 257, cy: 225, rx: 14, ry: 12, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('path', {
      d: 'M 126 158 Q 165 175 204 158 L 204 185 Q 204 195 195 200 L 195 250 L 195 270 Q 195 330 190 345 L 175 345 L 180 270 L 180 200 L 165 195 L 150 200 L 150 270 L 155 345 L 140 345 Q 135 330 135 270 L 135 250 L 135 200 Q 126 195 126 185 Z',
      fill: 'url(#painMapBodyGrad)',
      stroke: 'rgba(201,168,108,0.35)',
      'stroke-width': 1,
    }));
    outline.appendChild(svgEl('ellipse', { cx: 147, cy: 348, rx: 16, ry: 8, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    outline.appendChild(svgEl('ellipse', { cx: 183, cy: 348, rx: 16, ry: 8, fill: 'url(#painMapBodyGrad)', stroke: 'rgba(201,168,108,0.35)', 'stroke-width': 1 }));
    parent.appendChild(outline);
  }

  function paintZone(rect, zone) {
    const selectedZones = regionToZoneIds(selectedRegionId);
    const isSelected = selectedZones.includes(zone.id);
    const isHovered = hoveredZoneId === zone.id;
    const isDimmed = !!selectedRegionId && !isSelected;

    rect.setAttribute('fill', isSelected ? 'rgba(201,168,108,0.65)' : PAIN_COLORS[zone.pain]);
    rect.setAttribute('stroke', isHovered || isSelected ? 'rgba(201,168,108,0.95)' : 'rgba(255,255,255,0.12)');
    rect.setAttribute('stroke-width', isHovered || isSelected ? 2 : 1);
    rect.style.opacity = isDimmed ? '0.38' : isHovered || isSelected ? '1' : '0.72';
    rect.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
  }

  function updateTooltip(zone) {
    if (!tooltipEl) return;
    if (!zone) {
      tooltipEl.hidden = true;
      return;
    }
    tooltipEl.hidden = false;
    tooltipEl.innerHTML =
      `<p class="pain-map-tooltip-title">${zone.label}</p>` +
      `<p class="pain-map-tooltip-pain" style="color:${PAIN_COLORS_SOLID[zone.pain]}">${PAIN_LABELS[zone.pain]}</p>` +
      `<div class="pain-map-tooltip-dots">${[1, 2, 3, 4].map((i) =>
        `<span class="pain-map-tooltip-dot${i <= zone.pain ? ' is-active' : ''}" style="${i <= zone.pain ? `background:${PAIN_COLORS_SOLID[zone.pain]}` : ''}"></span>`
      ).join('')}</div>`;
  }

  function refreshAllZones() {
    PAIN_ZONES.forEach((zone) => {
      const rect = zoneEls[zone.id];
      if (rect) paintZone(rect, zone);
    });
  }

  function setHoveredZone(zoneId) {
    hoveredZoneId = zoneId;
    refreshAllZones();
    updateTooltip(zoneId ? getZoneById(zoneId) : null);
    const regionId = zoneId ? PAIN_MAP_TO_REGION[zoneId] : null;
    if (onHoverCallback) onHoverCallback(regionId, !!zoneId);
  }

  function buildLegend(container) {
    if (!container) return;
    container.className = 'pain-map-legend';
    container.innerHTML = Object.entries(PAIN_LABELS).map(([level, label]) =>
      `<span class="pain-map-legend-item">` +
      `<i class="pain-map-legend-swatch" style="background:${PAIN_COLORS[Number(level)].replace('0.55', '0.85')}"></i>` +
      `${label}</span>`
    ).join('');
  }

  function init(wrapEl, legendEl, options) {
    if (!wrapEl) return;
    onSelectCallback = options?.onSelect || null;
    onHoverCallback = options?.onHover || null;
    selectedRegionId = options?.selectedRegion || '';
    hoveredZoneId = null;
    zoneEls = {};

    wrapEl.innerHTML = '';
    wrapEl.className = 'pain-map-wrap';

    rootEl = document.createElement('div');
    rootEl.className = 'pain-map-root';

    tooltipEl = document.createElement('div');
    tooltipEl.className = 'pain-map-tooltip';
    tooltipEl.hidden = true;
    rootEl.appendChild(tooltipEl);

    const svg = svgEl('svg', {
      viewBox: '0 0 330 380',
      class: 'pain-map-svg body-silhouette',
      role: 'img',
      'aria-label': 'Vücut bölgesi acı haritası',
    });

    const defs = svgEl('defs');
    const grad = svgEl('linearGradient', { id: 'painMapBodyGrad', x1: '0%', y1: '0%', x2: '0%', y2: '100%' });
    grad.appendChild(svgEl('stop', { offset: '0%', 'stop-color': 'rgba(201,168,108,0.18)' }));
    grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': 'rgba(168,85,247,0.12)' }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    buildBodySilhouette(svg);

    const zonesGroup = svgEl('g', { class: 'pain-map-zones' });
    PAIN_ZONES.forEach((zone) => {
      const rect = svgEl('rect', {
        x: zone.x,
        y: zone.y,
        width: zone.w,
        height: zone.h,
        rx: 6,
        class: 'pain-map-zone',
        'data-zone-id': zone.id,
        tabindex: 0,
        role: 'button',
        'aria-label': `${zone.label}, ${PAIN_LABELS[zone.pain]}`,
      });
      paintZone(rect, zone);

      rect.addEventListener('mouseenter', () => setHoveredZone(zone.id));
      rect.addEventListener('mouseleave', () => setHoveredZone(null));
      rect.addEventListener('focus', () => setHoveredZone(zone.id));
      rect.addEventListener('blur', () => setHoveredZone(null));
      rect.addEventListener('click', () => {
        const regionId = PAIN_MAP_TO_REGION[zone.id];
        if (regionId && onSelectCallback) onSelectCallback(regionId);
      });
      rect.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          const regionId = PAIN_MAP_TO_REGION[zone.id];
          if (regionId && onSelectCallback) onSelectCallback(regionId);
        }
      });

      zoneEls[zone.id] = rect;
      zonesGroup.appendChild(rect);
    });
    svg.appendChild(zonesGroup);
    rootEl.appendChild(svg);
    wrapEl.appendChild(rootEl);

    buildLegend(legendEl);
  }

  function syncSelection(regionId) {
    selectedRegionId = regionId || '';
    refreshAllZones();
  }

  window.PainMap = {
    init,
    syncSelection,
    regionToZoneIds,
    PAIN_MAP_TO_REGION,
    PAIN_ZONES,
    PAIN_LABELS,
  };
})();
