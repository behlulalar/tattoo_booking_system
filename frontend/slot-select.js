function getApiBaseUrl() {
  const stored = localStorage.getItem('API_BASE_URL');
  if (stored) return stored.replace(/\/$/, '');
  const isLocal =
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1';
  const isLikelyStaticPort =
    window.location.port && window.location.port !== '3000';
  if (isLocal && isLikelyStaticPort) return 'http://127.0.0.1:3000';
  return '';
}

const API_BASE_URL = getApiBaseUrl();
const token = new URLSearchParams(window.location.search).get('token') || '';

function $(id) { return document.getElementById(id); }

let durationMinutes = 0;
let selectedTime = '';

// ── UI state helpers ──────────────────────────────────────────────
function showLoading() {
  $('loading-state').style.display = 'block';
  $('error-state').style.display  = 'none';
  $('main-ui').style.display      = 'none';
  $('success-state').style.display = 'none';
}

function showError(title, desc) {
  $('loading-state').style.display = 'none';
  $('main-ui').style.display       = 'none';
  $('success-state').style.display = 'none';
  $('error-title').textContent = title;
  $('error-desc').textContent  = desc || '';
  $('error-state').style.display = 'flex';
}

function showMain() {
  $('loading-state').style.display = 'none';
  $('error-state').style.display   = 'none';
  $('success-state').style.display = 'none';
  $('main-ui').style.display       = 'block';
}

function showSuccess(dateStr, timeStr, duration) {
  $('loading-state').style.display = 'none';
  $('error-state').style.display   = 'none';
  $('main-ui').style.display       = 'none';
  $('success-detail').textContent  =
    `📅 ${dateStr}  ⏰ ${timeStr}  🕒 ${duration} dk`;
  $('success-state').style.display = 'flex';
}

function setSlotError(msg) {
  const el = $('slot-error');
  el.textContent    = msg;
  el.style.display  = msg ? 'block' : 'none';
}

// ── API helper ────────────────────────────────────────────────────
async function api(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

// ── Slot rendering ────────────────────────────────────────────────
function timeToMinutes(t) {
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}

function minutesToTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

const SLOT_MINUTES = 60;

function renderSlots(dateStr, slotsData) {
  selectedTime = '';
  $('confirm-btn').disabled = true;
  setSlotError('');

  const slotsCount  = Math.max(1, Math.ceil(durationMinutes / SLOT_MINUTES));
  const allSlots    = slotsData.all_slots    || slotsData.available_start_slots || [];
  const bookedSet   = new Set(slotsData.booked_slots || []);
  const availableSet = new Set(slotsData.available_start_slots || []);

  const grid = $('slots-grid');
  grid.innerHTML = '';

  const label = slotsCount > 1
    ? `${dateStr} — Her seçim <strong>${slotsCount} ardışık slot (${durationMinutes} dk)</strong> kapsar`
    : `${dateStr} için uygun saatler (${durationMinutes} dk)`;
  $('slots-title').innerHTML = label;
  $('slots-wrap').style.display = 'block';

  if (!allSlots || allSlots.length === 0) {
    grid.innerHTML = '<p style="color:rgba(255,255,255,0.4);font-size:0.9rem;">Bu tarihte uygun saat bulunamadı.</p>';
    return;
  }

  allSlots.forEach((t) => {
    const isBooked    = bookedSet.has(t);
    const isAvailable = availableSet.has(t);
    const startMins   = timeToMinutes(t);
    const endTime     = minutesToTime(startMins + SLOT_MINUTES);

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.dataset.time = t;

    if (isBooked) {
      btn.className = 'slot-btn booked';
      btn.disabled  = true;
      btn.innerHTML = `<span class="slot-start">${t}</span><span class="slot-end">${endTime}</span>`;
    } else if (isAvailable) {
      btn.className = 'slot-btn';
      btn.innerHTML = `<span class="slot-start">${t}</span><span class="slot-end">${endTime}</span>`;

      btn.addEventListener('click', () => {
        document.querySelectorAll('.slot-btn').forEach((b) => {
          b.classList.remove('selected', 'selected-block');
        });

        for (let i = 0; i < slotsCount; i++) {
          const blockTime = minutesToTime(startMins + i * SLOT_MINUTES);
          const blockBtn  = grid.querySelector(`[data-time="${blockTime}"]`);
          if (blockBtn) blockBtn.classList.add(i === 0 ? 'selected' : 'selected-block');
        }

        selectedTime = t;
        $('confirm-btn').disabled = false;
        setSlotError('');
      });
    } else {
      btn.className = 'slot-btn unavailable';
      btn.disabled  = true;
      btn.innerHTML = `<span class="slot-start">${t}</span><span class="slot-end">${endTime}</span>`;
    }

    grid.appendChild(btn);
  });
}

// ── Load slots for selected date ─────────────────────────────────
let slotsRequestId = 0;

async function loadSlotsForSelectedDate() {
  const date = $('date-select')?.value;
  if (!date) return;

  const requestId = ++slotsRequestId;
  setSlotError('');
  selectedTime = '';
  if ($('confirm-btn')) $('confirm-btn').disabled = true;

  const grid = $('slots-grid');
  const slotsWrap = $('slots-wrap');
  if (slotsWrap) slotsWrap.style.display = 'block';
  if ($('slots-title')) {
    $('slots-title').textContent = `${date} — saatler yükleniyor…`;
  }
  if (grid) grid.innerHTML = '';

  const { ok, data } = await api(`/api/offers/${encodeURIComponent(token)}?date=${encodeURIComponent(date)}`);

  if (requestId !== slotsRequestId) return;

  if (!ok || !data.success) {
    if ($('slots-title')) $('slots-title').textContent = `${date}`;
    setSlotError(data.message || 'Saatler yüklenemedi');
    return;
  }
  renderSlots(date, data.slots || {});
}

// ── Init ──────────────────────────────────────────────────────────
async function init() {
  if (!token) {
    showError('Geçersiz Bağlantı', 'Bu link geçerli bir randevu teklifi içermiyor.');
    return;
  }

  showLoading();
  const { ok, status, data } = await api(`/api/offers/${encodeURIComponent(token)}`);

  if (!ok || !data.success) {
    const msg = data.message || 'Link geçersiz veya süresi dolmuş.';
    if (status === 410 && msg.includes('kullanılmış')) {
      showError('Link Daha Önce Kullanıldı', 'Bu randevu linki daha önce kullanılmış. Yeni bir teklif için stüdyomuzu arayabilirsiniz.');
    } else if (status === 410) {
      showError('Link Süresi Doldu', 'Bu randevu linkinin geçerlilik süresi dolmuş. Yeni bir teklif için stüdyomuzu arayabilirsiniz.');
    } else {
      showError('Hata', msg);
    }
    return;
  }

  durationMinutes = data.offer.duration_minutes;
  const offerPrice = parseFloat(data.offer.price || 0);
  const originalPrice = parseFloat(data.offer.original_price || 0);
  const discountPercent = parseInt(data.offer.discount_percent || 0, 10);
  const tr = data.tattoo_request || {};
  const staffName = tr.staff?.name || '-';

  let priceLabel = '';
  if (offerPrice > 0 && originalPrice > 0 && discountPercent > 0) {
    priceLabel =
      `${offerPrice.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺ ` +
      `(liste ${originalPrice.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺, %${discountPercent} indirim)`;
  } else if (offerPrice > 0) {
    priceLabel = `${offerPrice.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺`;
  }

  // Offer meta badges
  const meta = $('offer-meta');
  meta.innerHTML = '';
  const badges = [
    ['fas fa-user-circle', 'Sanatçı', staffName],
    ['fas fa-clock', 'Süre', `${durationMinutes} dakika`],
    priceLabel ? ['fas fa-tag', 'Ücret', priceLabel] : null,
    tr.body_area ? ['fas fa-map-marker-alt', 'Bölge', tr.body_area] : null,
    tr.size      ? ['fas fa-ruler-combined', 'Boyut', tr.size]       : null,
  ];
  badges.filter(Boolean).forEach(([icon, label, value]) => {
    const isPrice = label === 'Ücret';
    meta.innerHTML += `<div class="meta-badge${isPrice ? ' meta-badge--price' : ''}"><i class="${icon}" style="margin-right:6px;opacity:0.6;"></i>${label}: <span>${value}</span></div>`;
  });

  const pz = data.private_zone || {};
  const banner = $('private-zone-banner');
  const bannerText = $('private-zone-banner-text');
  if (banner && bannerText && pz.active && pz.schedule_summary) {
    bannerText.textContent =
      `Bu bölge için randevular yalnızca ${pz.schedule_summary} saatlerinde alınabilir. ` +
      'Diğer gün ve saatlerde randevu oluşturulamaz.';
    banner.style.display = 'flex';
  } else if (banner) {
    banner.style.display = 'none';
  }

  // Date dropdown
  const dateSelect = $('date-select');
  dateSelect.innerHTML = '';
  (data.dates || []).forEach((d) => {
    const opt = document.createElement('option');
    opt.value = d;
    opt.textContent = d;
    dateSelect.appendChild(opt);
  });

  showMain();

  if (dateSelect.options.length > 0) {
    await loadSlotsForSelectedDate();
  }
}

// ── Event listeners ───────────────────────────────────────────────
$('date-select')?.addEventListener('change', () => {
  loadSlotsForSelectedDate();
});

$('confirm-btn').addEventListener('click', async () => {
  const date = $('date-select').value;
  if (!date || !selectedTime) return;
  $('confirm-btn').disabled = true;
  $('confirm-btn').textContent = 'Kaydediliyor...';
  setSlotError('');

  const { ok, data } = await api(`/api/offers/${encodeURIComponent(token)}/choose-slot`, {
    method: 'POST',
    body: JSON.stringify({ date, time: selectedTime }),
  });

  if (!ok || !data.success) {
    $('confirm-btn').disabled = false;
    $('confirm-btn').textContent = 'Seçimi Onayla';
    setSlotError(data.message || 'Seçim kaydedilemedi');
    return;
  }

  showSuccess(date, selectedTime, durationMinutes);
});

init();
