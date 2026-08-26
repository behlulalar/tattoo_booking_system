// Tattoo booking flow (static frontend)
// Tel -> Code -> Artist -> Tattoo details -> Request created

function getApiBaseUrl() {
  const stored = localStorage.getItem('API_BASE_URL');
  if (stored) return stored.replace(/\/$/, '');

  // Local dev fallback: frontend served from a static server (e.g. :8000) and backend on :3000
  const isLocal =
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1';
  const isLikelyStaticPort =
    window.location.port && window.location.port !== '3000';

  if (isLocal && isLikelyStaticPort) return 'http://127.0.0.1:3000';
  return ''; // production (reverse proxy) or same-origin
}

const API_BASE_URL = getApiBaseUrl();

function formatPersonName(value) {
  return String(value || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLocaleLowerCase('tr-TR');
      return lower.charAt(0).toLocaleUpperCase('tr-TR') + lower.slice(1);
    })
    .join(' ');
}

// =============================================
// SPLASH / LOADING SCREEN
// =============================================
document.addEventListener('DOMContentLoaded', () => {
  const splash = document.getElementById('splash-screen');
  const bgVideo = document.querySelector('.bg-video');
  if (bgVideo) {
    bgVideo.muted = true;
    bgVideo.defaultMuted = true;
    bgVideo.volume = 0;
    bgVideo.setAttribute('muted', '');
    const tryPlay = () => {
      const playPromise = bgVideo.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch(() => {});
      }
    };
    if (bgVideo.readyState >= 2) tryPlay();
    else bgVideo.addEventListener('canplay', tryPlay, { once: true });
  }

  // Reveal app after a short premium splash
  const reveal = () => {
    document.body.classList.add('app-ready');
    if (splash) splash.classList.add('hide');
    // Remove from layout after transition ends
    setTimeout(() => {
      if (splash) splash.style.display = 'none';
    }, 650);
  };

  // If splash element missing, just reveal immediately
  if (!splash) {
    document.body.classList.add('app-ready');
    return;
  }

  // Match sefa_web LoadingScreen timings (reveal ends ~2.8s) + short hold + fade out
  requestAnimationFrame(() => splash.classList.add('show'));
  const isMobile = window.matchMedia('(max-width: 768px)').matches;
  setTimeout(reveal, isMobile ? 1750 : 2300);
});

function applyKeyboardInset() {
  const vv = window.visualViewport;
  if (!vv) return;
  const covered = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
  document.documentElement.style.setProperty('--keyboard-inset', `${covered}px`);
}
window.visualViewport?.addEventListener('resize', applyKeyboardInset);
window.visualViewport?.addEventListener('scroll', applyKeyboardInset);

// =============================================
// SOL DOCK — hızlı erişim ikonları
// =============================================

// Elements: phone + verify
const phoneInput = document.getElementById('phone');
const phoneForm = document.getElementById('phone-form');
const phoneCheckBtn = document.getElementById('phone-check-btn');

const verifyOverlay = document.getElementById('verify-overlay');
const verifyForm = document.getElementById('verify-form');
const codeInput = document.getElementById('code');
const timerDisplay = document.getElementById('timer');
const countdownTimer = document.getElementById('countdown-timer');
const resendBtn = document.getElementById('resend-btn');
const verifyError = document.getElementById('verify-error');

const verifyOtpApi = setupOtpInput(
  document.getElementById('verify-otp-boxes'),
  codeInput
);

const phoneSection = document.querySelector('.step-content');
const welcomeOverlay = document.getElementById('welcome-overlay');
const welcomeName = document.getElementById('welcome-name');
const welcomeContinueBtn = document.getElementById('welcome-continue-btn');
const successOverlay = document.getElementById('success-overlay');
const successTitle = document.getElementById('success-title');
const successMessage = document.getElementById('success-message');
const successOkBtn = document.getElementById('success-ok-btn');

// Stepper
const steps = document.querySelectorAll('.step');
function updateStepper(stepNumber) {
  steps.forEach((step, index) => {
    step.classList.remove('active', 'completed');
    if (index + 1 < stepNumber) step.classList.add('completed');
    else if (index + 1 === stepNumber) step.classList.add('active');
  });
}

// Artist selection
const artistSection = document.getElementById('artist-section');
const artistCards = document.getElementById('artist-cards');
const artistContinueBtn = document.getElementById('artist-continue-btn');

// Customer info
const customerInfoSection = document.getElementById('customer-info-section');
const customerInfoForm = document.getElementById('customer-info-form');
const customerNameInput = document.getElementById('customer-name');
const customerSurnameInput = document.getElementById('customer-surname');
const customerInfoError = document.getElementById('customer-info-error');

[customerNameInput, customerSurnameInput].forEach((el) => {
  el?.addEventListener('blur', () => {
    el.value = formatPersonName(el.value);
  });
});

// Tattoo config (region + size)
const tattooConfigSection = document.getElementById('tattoo-config-section');
const regionButtonsEl = document.getElementById('region-buttons');
const configSizePanel = document.getElementById('config-size-panel');
const configSizeButtonsEl = document.getElementById('config-size-buttons');
const tattooConfigError = document.getElementById('tattoo-config-error');
const tattooConfigBackBtn = document.getElementById('tattoo-config-back-btn');
const tattooConfigContinueBtn = document.getElementById('tattoo-config-continue-btn');
const tattooConfigUndecidedBtn = document.getElementById('tattoo-config-undecided-btn');
const tattooConfigConsultationBtn = document.getElementById('tattoo-config-consultation-btn');
const bookingLeftEl = document.querySelector('.booking-left');
const regionScrollWrap = document.getElementById('region-scroll-wrap');
const tattooPageScrollHints = document.getElementById('tattoo-page-scroll-hints');
const tattooPageScrollUp = document.getElementById('tattoo-page-scroll-up');
const tattooPageScrollDown = document.getElementById('tattoo-page-scroll-down');

// State
let savedPhone = '';
let countdownInterval = null;
let savedArtistId = null;
let savedArtistPhone = '';
let savedArtistName = '';
let tattooConfigMeta = null;
let savedBodyRegion = '';
let savedConfigSize = '';
let savedConfigSizeId = '';
let savedConfigUndecided = false;

const TATTOO_SIZES = [
  { id: 'minimal', value: 'Minimal (2–5 cm)', label: 'Minimal (2–5 cm)' },
  { id: 'small_medium', value: 'Küçük - Orta (5–10 cm)', label: 'Küçük - Orta (5–10 cm)' },
  { id: 'medium', value: 'Orta (10–20 cm)', label: 'Orta (10–20 cm)' },
  { id: 'large', value: 'Büyük (20 cm ve üzeri)', label: 'Büyük (20 cm ve üzeri)' },
  { id: 'full', value: 'Tam Bölge (Sleeve/Back)', label: 'Tam Bölge (Sleeve/Back)' },
];

const TATTOO_REGIONS_FALLBACK = [
  { id: 'head', label: 'Baş / ense' },
  { id: 'neck', label: 'Boyun' },
  { id: 'chest', label: 'Göğüs', private: true },
  { id: 'ribs', label: 'Kaburga', private: true },
  { id: 'stomach', label: 'Karın', private: true },
  { id: 'back_upper', label: 'Üst sırt' },
  { id: 'back_lower', label: 'Alt sırt / bel', private: true },
  { id: 'shoulder', label: 'Omuz' },
  { id: 'upper_arm', label: 'Üst kol' },
  { id: 'forearm', label: 'Ön kol' },
  { id: 'wrist', label: 'Bilek' },
  { id: 'hand', label: 'El / parmak' },
  { id: 'thigh', label: 'Uyluk', private: true },
  { id: 'knee', label: 'Diz' },
  { id: 'calf', label: 'Baldır' },
  { id: 'ankle', label: 'Ayak bileği' },
  { id: 'foot', label: 'Ayak üstü' },
];

async function loadTattooConfigMeta() {
  if (tattooConfigMeta) return tattooConfigMeta;

  const { ok, data } = await api('/api/tattoo-config', { method: 'GET' });
  if (ok && data.success) {
    tattooConfigMeta = data;
    return tattooConfigMeta;
  }
  tattooConfigMeta = {
    private_zone: {
      enabled: true,
      schedule_summary: 'Salı 14:00-18:00, Perşembe 14:00-18:00',
    },
    regions: TATTOO_REGIONS_FALLBACK.map((r) => ({ ...r })),
  };
  return tattooConfigMeta;
}

function getRegionMeta(regionId) {
  const regions = tattooConfigMeta?.regions || [];
  return regions.find((r) => r.id === regionId) || null;
}

function buildRegionButtons() {
  if (!regionButtonsEl) return;
  const regions = tattooConfigMeta?.regions || TATTOO_REGIONS_FALLBACK;
  regionButtonsEl.innerHTML = '';
  regions.forEach((region) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'region-btn';
    btn.dataset.regionId = region.id;
    btn.innerHTML = `<span class="region-btn-label">${escapeHtml(region.label)}</span>`;
    btn.addEventListener('click', () => selectBodyRegion(region.id));
    regionButtonsEl.appendChild(btn);
  });
}

function buildSizeButtons() {
  if (!configSizeButtonsEl) return;
  configSizeButtonsEl.innerHTML = '';
  TATTOO_SIZES.forEach((sz) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'size-btn';
    btn.dataset.sizeId = sz.id;
    btn.textContent = sz.label;
    btn.addEventListener('click', () => selectConfigSize(sz.value, sz.id));
    configSizeButtonsEl.appendChild(btn);
  });
}

function updatePrivateZoneNotice() {
  const noticeEl = document.getElementById('private-zone-notice');
  const textEl = document.getElementById('private-zone-notice-text');
  if (!noticeEl || !textEl) return;
  const region = getRegionMeta(savedBodyRegion);
  const pz = tattooConfigMeta?.private_zone;
  if (region?.private && pz?.enabled !== false && pz?.schedule_summary) {
    textEl.textContent =
      `Bu bölge için randevular yalnızca ${pz.schedule_summary} saatlerinde alınabilir. ` +
      'Mahremiyetiniz için diğer gün ve saatlerde randevu oluşturulamaz.';
    noticeEl.style.display = 'flex';
  } else {
    noticeEl.style.display = 'none';
    textEl.textContent = '';
  }
}

function syncConfigSelectionUI() {
  document.querySelectorAll('.region-btn').forEach((b) => {
    b.classList.toggle('selected', b.dataset.regionId === savedBodyRegion);
  });
  document.querySelectorAll('.size-btn').forEach((b) => {
    b.classList.toggle('selected', b.dataset.sizeId === savedConfigSizeId);
  });
  updatePrivateZoneNotice();
  if (configSizePanel) configSizePanel.style.display = 'block';
  updateConfigContinueState();
  refreshTattooScrollHints();
}

function selectBodyRegion(regionId) {
  savedConfigUndecided = false;
  savedBodyRegion = regionId;
  syncConfigSelectionUI();
}

function selectConfigSize(sizeValue, sizeId = '') {
  savedConfigSize = sizeValue;
  savedConfigSizeId = sizeId || TATTOO_SIZES.find((sz) => sz.value === sizeValue)?.id || '';
  syncConfigSelectionUI();
}

function updateConfigContinueState() {
  const ready = !!(savedBodyRegion && savedConfigSize);
  if (tattooConfigContinueBtn) tattooConfigContinueBtn.disabled = !ready;
}

function isTattooConfigVisible() {
  return tattooConfigSection && tattooConfigSection.style.display !== 'none';
}

function setTattooConfigStepActive(isActive) {
  bookingLeftEl?.classList.toggle('is-tattoo-config-active', isActive);
  if (!isActive) {
    if (tattooPageScrollHints) tattooPageScrollHints.hidden = true;
    tattooConfigSection?.classList.remove('tattoo-show-scroll-fade');
  } else {
    refreshTattooScrollHints();
  }
}

function refreshTattooScrollHints() {
  regionScrollWrap?._updateScrollHints?.();
  requestAnimationFrame(updateTattooPageScrollHints);
}

function updateTattooPageScrollHints() {
  if (!tattooPageScrollHints || !bookingLeftEl) return;
  const isMobile = window.matchMedia('(max-width: 768px)').matches;
  if (!isTattooConfigVisible() || !isMobile) {
    tattooPageScrollHints.hidden = true;
    tattooConfigSection?.classList.remove('tattoo-show-scroll-fade');
    return;
  }

  const canScroll = bookingLeftEl.scrollHeight > bookingLeftEl.clientHeight + 16;
  if (!canScroll) {
    tattooPageScrollHints.hidden = true;
    tattooConfigSection?.classList.remove('tattoo-show-scroll-fade');
    return;
  }

  const atTop = bookingLeftEl.scrollTop <= 16;
  const continueVisible = isContinueButtonInView();
  const atBottom =
    continueVisible ||
    bookingLeftEl.scrollTop + bookingLeftEl.clientHeight >= bookingLeftEl.scrollHeight - 120;
  if (atBottom) {
    tattooPageScrollHints.hidden = true;
    tattooConfigSection?.classList.remove('tattoo-show-scroll-fade');
    return;
  }

  tattooPageScrollHints.hidden = false;
  tattooPageScrollHints.classList.toggle('is-at-top', atTop);
  tattooPageScrollHints.classList.remove('is-at-bottom');
  tattooPageScrollHints.classList.toggle('is-scrolled', !atTop);
  tattooConfigSection?.classList.add('tattoo-show-scroll-fade');
}

function isContinueButtonInView() {
  if (!tattooConfigContinueBtn || !bookingLeftEl) return false;
  const btnRect = tattooConfigContinueBtn.getBoundingClientRect();
  const wrapRect = bookingLeftEl.getBoundingClientRect();
  return btnRect.top < wrapRect.bottom - 8 && btnRect.bottom > wrapRect.top + 8;
}

function setupInlineScrollHints(wrapEl, scrollerEl) {
  if (!wrapEl || !scrollerEl) return;
  const upBtn = wrapEl.querySelector('.region-scroll-hint--up');
  const downBtn = wrapEl.querySelector('.region-scroll-hint--down');

  const update = () => {
    const canScroll = scrollerEl.scrollHeight > scrollerEl.clientHeight + 4;
    wrapEl.classList.toggle('has-scroll', canScroll);
    if (!canScroll) {
      wrapEl.classList.remove('has-scroll-up', 'has-scroll-down');
      return;
    }
    const atTop = scrollerEl.scrollTop <= 4;
    const atBottom = scrollerEl.scrollTop + scrollerEl.clientHeight >= scrollerEl.scrollHeight - 4;
    wrapEl.classList.toggle('has-scroll-up', !atTop);
    wrapEl.classList.toggle('has-scroll-down', !atBottom);
  };

  scrollerEl.addEventListener('scroll', update, { passive: true });
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(update).observe(scrollerEl);
  }
  upBtn?.addEventListener('click', () => scrollerEl.scrollBy({ top: -100, behavior: 'smooth' }));
  downBtn?.addEventListener('click', () => scrollerEl.scrollBy({ top: 100, behavior: 'smooth' }));
  wrapEl._updateScrollHints = update;
  update();
}

function setupTattooScrollHints() {
  bookingLeftEl?.addEventListener('scroll', updateTattooPageScrollHints, { passive: true });
  window.addEventListener('resize', updateTattooPageScrollHints, { passive: true });

  tattooPageScrollUp?.addEventListener('click', () => {
    bookingLeftEl?.scrollBy({ top: -(window.innerHeight * 0.55), behavior: 'smooth' });
  });
  tattooPageScrollDown?.addEventListener('click', () => {
    bookingLeftEl?.scrollBy({ top: window.innerHeight * 0.55, behavior: 'smooth' });
  });

  setupInlineScrollHints(regionScrollWrap, regionButtonsEl);
}

async function initTattooConfigStep() {
  showInlineError(tattooConfigError, '');
  savedConfigUndecided = false;
  await loadTattooConfigMeta();
  buildRegionButtons();
  buildSizeButtons();
  syncConfigSelectionUI();
  refreshTattooScrollHints();
}

function isValidPhone(value) {
  return /^[0-9]{10}$/.test(value);
}

function showInlineError(el, message) {
  if (!el) return;
  el.textContent = message;
  el.style.display = message ? 'block' : 'none';
}

function showVerifyError(message) {
  if (!verifyError) return;
  verifyError.textContent = message;
  setTimeout(() => (verifyError.textContent = ''), 3000);
}

const successRefBlock = document.getElementById('success-ref-block');
const successRefCode = document.getElementById('success-ref-code');
const successRefCopyBtn = document.getElementById('success-ref-copy-btn');
const successWhatsappBlock = document.getElementById('success-whatsapp-block');
const successWhatsappBtn = document.getElementById('success-whatsapp-btn');
const successWhatsappHint = document.getElementById('success-whatsapp-hint');
const successModalEl = document.getElementById('success-modal');
let successRefCopyHandler = null;
let successWhatsappClickHandler = null;

function hideSuccessRefBlock() {
  if (successRefBlock) successRefBlock.style.display = 'none';
  if (successRefCopyBtn && successRefCopyHandler) {
    successRefCopyBtn.removeEventListener('click', successRefCopyHandler);
    successRefCopyHandler = null;
  }
}

function hideSuccessWhatsappBlock() {
  if (successWhatsappBlock) successWhatsappBlock.style.display = 'none';
  if (successWhatsappBtn) {
    successWhatsappBtn.removeAttribute('href');
    if (successWhatsappClickHandler) {
      successWhatsappBtn.removeEventListener('click', successWhatsappClickHandler);
      successWhatsappClickHandler = null;
    }
  }
  successModalEl?.classList.remove('is-whatsapp-required');
  if (successOkBtn) successOkBtn.style.display = '';
}

function phoneToWhatsAppIntl(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  if (!digits) return null;
  if (digits.startsWith('90') && digits.length === 12) return digits;
  if (digits.startsWith('0') && digits.length === 11) return `90${digits.slice(1)}`;
  if (digits.length === 10) return `90${digits}`;
  if (digits.length >= 11) return digits;
  return null;
}

function buildArtistWhatsAppUrl(phone, message) {
  const intl = phoneToWhatsAppIntl(phone);
  if (!intl || !message) return null;
  return `https://wa.me/${intl}?text=${encodeURIComponent(message)}`;
}

function appendRefAndArtist(lines, ref, artistName) {
  if (ref) lines.push(`Referans No: ${ref}`);
  if (artistName) lines.push(`Sanatçı: ${artistName}`);
}

function buildTattooRequestWhatsAppHint(summary = {}) {
  if (summary.preConsultation) {
    return 'Ön görüşme talebiniz için sanatçıya WhatsApp üzerinden ulaşabilirsiniz. Mesaj kutusu otomatik doldurulur; önce bu mesajı gönderin, ardından uygun zamanlarınızı veya sorularınızı yazabilirsiniz.';
  }
  if (summary.undecided) {
    return 'Henüz karar vermediğiniz talep için sanatçıya WhatsApp üzerinden ulaşabilirsiniz. Mesaj kutusu otomatik doldurulur; önce bu mesajı gönderin, ardından fikirlerinizi veya referanslarınızı paylaşabilirsiniz.';
  }
  return 'Referans görseliniz veya aklınızda bir tasarım varsa sanatçıya WhatsApp üzerinden ulaşabilirsiniz. Mesaj kutusu otomatik doldurulur; önce bu mesajı gönderin, ardından görsel veya notunuzu ekleyebilirsiniz.';
}

function buildTattooRequestWhatsAppMessage(ref, summary = {}) {
  const artistName = summary.artistName || '';

  if (summary.preConsultation) {
    const lines = [
      'Merhaba,',
      '',
      'Ön görüşme talep ettim.',
      '',
    ];
    appendRefAndArtist(lines, ref, artistName);
    lines.push(
      '',
      'Randevu planlamak ve dövme süreci hakkında bilgi almak istiyorum.',
      'Lütfen bu mesajı gönderdikten sonra uygun olduğunuz zamanları veya sorularınızı yazabilirsiniz.'
    );
    return lines.join('\n');
  }

  if (summary.undecided) {
    const lines = [
      'Merhaba,',
      '',
      'Dövme talebi oluşturdum; tarz, bölge ve boyutu henüz belirlemedim.',
      '',
    ];
    appendRefAndArtist(lines, ref, artistName);
    lines.push(
      '',
      'Birlikte seçenekleri konuşmak ve yönlendirme almak istiyorum.',
      'Lütfen bu mesajı gönderdikten sonra varsa referans görsellerinizi veya fikirlerinizi paylaşabilirsiniz.'
    );
    return lines.join('\n');
  }

  const lines = ['Merhaba,', '', 'Dövme talebi oluşturdum.', ''];
  appendRefAndArtist(lines, ref, artistName);
  if (summary.styleLabel) lines.push(`Tarz: ${summary.styleLabel}`);
  if (summary.regionLabel) lines.push(`Bölge: ${summary.regionLabel}`);
  if (summary.size) lines.push(`Boyut: ${summary.size}`);
  lines.push(
    '',
    'Referans görselim veya aklımdaki tasarım var; paylaşmak istiyorum.',
    'Lütfen bu mesajı gönderdikten sonra görsel veya notlarımı ekleyeceğim.'
  );
  return lines.join('\n');
}

function setSuccessModalOpen(isOpen) {
  document.body.classList.toggle('success-modal-open', isOpen);
}

function closeSuccessModal(callback = null) {
  if (successOverlay) successOverlay.style.display = 'none';
  setSuccessModalOpen(false);
  hideSuccessRefBlock();
  hideSuccessWhatsappBlock();
  if (callback) callback();
}

function showSuccess(title, message, callback = null) {
  hideSuccessRefBlock();
  hideSuccessWhatsappBlock();
  successTitle.textContent = title;
  successMessage.textContent = message;
  successOverlay.style.display = 'flex';
  setSuccessModalOpen(true);
  successOkBtn.onclick = () => closeSuccessModal(callback);
}

function showTattooRequestSuccess(data, defaultMessage, onClose = null, whatsappContext = null) {
  const ref = data?.reference_number;
  successTitle.textContent = 'Talebiniz Alındı';
  hideSuccessWhatsappBlock();

  const summary = whatsappContext?.summary || {};
  const requiresWhatsapp = !!(summary.preConsultation || summary.undecided);

  if (ref && successRefBlock && successRefCode) {
    successRefCode.textContent = ref;
    successRefBlock.style.display = 'flex';
    if (summary.preConsultation) {
      successMessage.textContent = 'Ön görüşme talebiniz alındı. Lütfen sanatçıya aşağıdaki butondan mesajınızı gönderiniz.';
    } else if (summary.undecided) {
      successMessage.textContent = 'Talebiniz alındı. Lütfen sanatçıya aşağıdaki butondan mesajınızı gönderiniz.';
    } else {
      successMessage.textContent = 'Sanatçı inceleyince size randevu linki gönderilecek.';
    }

    if (successRefCopyBtn) {
      successRefCopyHandler = async () => {
        try {
          await navigator.clipboard.writeText(ref);
          successRefCopyBtn.innerHTML = '<i class="fas fa-check"></i> Kopyalandı!';
          successRefCopyBtn.classList.add('copied');
          setTimeout(() => {
            successRefCopyBtn.innerHTML = '<i class="fas fa-copy"></i> Numarayı Kopyala';
            successRefCopyBtn.classList.remove('copied');
          }, 2200);
        } catch {
          successRefCopyBtn.innerHTML = '<i class="fas fa-copy"></i> Kopyalanamadı';
        }
      };
      successRefCopyBtn.addEventListener('click', successRefCopyHandler);
    }
  } else {
    hideSuccessRefBlock();
    successMessage.textContent = data?.message || defaultMessage;
  }

  const ctx = whatsappContext || {};
  const waSummary = ctx.summary || summary;
  const waMessage = buildTattooRequestWhatsAppMessage(ref, waSummary);
  const waUrl = buildArtistWhatsAppUrl(ctx.artistPhone, waMessage);
  if (waUrl && successWhatsappBlock && successWhatsappBtn) {
    successWhatsappBtn.href = waUrl;
    if (successWhatsappHint) {
      successWhatsappHint.textContent = buildTattooRequestWhatsAppHint(waSummary);
    }
    successWhatsappBlock.style.display = 'block';

    if (requiresWhatsapp) {
      successModalEl?.classList.add('is-whatsapp-required');
      if (successOkBtn) successOkBtn.style.display = 'none';
      successWhatsappClickHandler = () => {
        setTimeout(() => closeSuccessModal(onClose), 400);
      };
      successWhatsappBtn.addEventListener('click', successWhatsappClickHandler);
    }
  }

  successOverlay.style.display = 'flex';
  setSuccessModalOpen(true);
  if (!requiresWhatsapp || !waUrl) {
    if (successOkBtn) successOkBtn.style.display = '';
    successOkBtn.onclick = () => closeSuccessModal(onClose);
  } else {
    successOkBtn.onclick = null;
  }
}

function updateTimerDisplay(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  timerDisplay.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
}

function startCountdown(seconds) {
  let remaining = seconds;
  if (countdownInterval) clearInterval(countdownInterval);
  countdownTimer.className = '';
  resendBtn.style.display = 'none';
  updateTimerDisplay(remaining);

  countdownInterval = setInterval(() => {
    remaining--;
    updateTimerDisplay(remaining);
    if (remaining <= 30 && remaining > 0) countdownTimer.className = 'warning';
    if (remaining <= 0) {
      clearInterval(countdownInterval);
      countdownTimer.className = 'expired';
      timerDisplay.textContent = 'Süre doldu!';
      resendBtn.style.display = 'inline-block';
    }
  }, 1000);
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

phoneInput?.addEventListener('focus', () => {
  setTimeout(() => {
    phoneForm?.querySelector('.primary-btn')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, 280);
});

phoneCheckBtn?.addEventListener('click', () => {
  phoneForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
});

phoneForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const value = (phoneInput.value || '').trim();

  if (!isValidPhone(value)) {
    showInlineError(document.getElementById('phone-form-error'), 'Lütfen geçerli bir telefon numarası girin.');
    return;
  }

  showInlineError(document.getElementById('phone-form-error'), '');

  const { ok, data } = await api('/api/send-code', {
    method: 'POST',
    body: JSON.stringify({ phone: value }),
  });

  if (!ok || !data.success) {
    showInlineError(document.getElementById('phone-form-error'), data.message || 'Kod gönderilemedi');
    return;
  }

  savedPhone = value;
  verifyOverlay.style.display = 'flex';
  startCountdown(120);
  verifyOtpApi.applyCode('123456');
  verifyOtpApi.focusFirst();
});

verifyForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = verifyOtpApi.getCode();
  if (!code || code.length !== 6) {
    showVerifyError('Lütfen 6 haneli doğrulama kodunu girin.');
    return;
  }

  const { ok, data } = await api('/api/verify-code', {
    method: 'POST',
    body: JSON.stringify({ phone: savedPhone, code }),
  });

  if (!ok || !data.success) {
    showVerifyError(data.message || 'Doğrulama başarısız');
    return;
  }

  clearInterval(countdownInterval);
  verifyOverlay.style.display = 'none';
  verifyOtpApi.stopAutofill();
  phoneSection.style.display = 'none';
  document.querySelector('.booking-page')?.classList.remove('is-phone-step');

  const customer = data.customer || null;
  const hasName = !!(customer && (customer.name || '').trim());
  const hasSurname = !!(customer && (customer.surname || '').trim());

  if (hasName || hasSurname) {
    updateStepper(3);
    if (welcomeName) welcomeName.textContent = `Hoş geldiniz, ${(customer.name || '').trim()} ${(customer.surname || '').trim()}`.trim();
    if (welcomeOverlay) welcomeOverlay.style.display = 'flex';
  } else {
    updateStepper(2);
    if (customerInfoSection) customerInfoSection.style.display = 'block';
    if (customerNameInput) customerNameInput.focus();
  }
});

welcomeContinueBtn?.addEventListener('click', async () => {
  if (welcomeOverlay) welcomeOverlay.style.display = 'none';
  if (customerInfoSection) customerInfoSection.style.display = 'none';
  updateStepper(3);
  artistSection.style.display = 'block';
  await loadArtists();
});

customerInfoForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  showInlineError(customerInfoError, '');

  const name = formatPersonName(customerNameInput?.value || '');
  const surname = formatPersonName(customerSurnameInput?.value || '');

  if (!name || !surname) {
    showInlineError(customerInfoError, 'Lütfen ad ve soyad girin.');
    return;
  }

  if (customerNameInput) customerNameInput.value = name;
  if (customerSurnameInput) customerSurnameInput.value = surname;

  const { ok, data } = await api('/api/register-customer', {
    method: 'POST',
    body: JSON.stringify({ phone: savedPhone, name, surname }),
  });

  if (!ok || !data.success) {
    showInlineError(customerInfoError, data.message || 'Kayıt yapılamadı');
    return;
  }

  const savedName = formatPersonName(data.customer?.name || name);
  const savedSurname = formatPersonName(data.customer?.surname || surname);
  updateStepper(3);
  if (welcomeName) welcomeName.textContent = `Hoş geldiniz, ${savedName} ${savedSurname}`;
  if (welcomeOverlay) welcomeOverlay.style.display = 'flex';
});

document.getElementById('verify-cancel-btn')?.addEventListener('click', () => {
  if (countdownInterval) clearInterval(countdownInterval);
  verifyOverlay.style.display = 'none';
  verifyOtpApi.stopAutofill();
  verifyOtpApi.clearOtp();
  if (verifyError) verifyError.textContent = '';
});

resendBtn?.addEventListener('click', async () => {
  const { ok, data } = await api('/api/send-code', {
    method: 'POST',
    body: JSON.stringify({ phone: savedPhone }),
  });
  if (!ok || !data.success) {
    showVerifyError(data.message || 'Kod gönderilemedi');
    return;
  }
  verifyOtpApi.applyCode('123456');
  verifyOtpApi.focusFirst();
  startCountdown(120);
  showSuccess('Kod Gönderildi', 'Yeni doğrulama kodu WhatsApp üzerinden gönderildi.');
});

document.getElementById('verify-paste-btn')?.addEventListener('click', async () => {
  const ok = await verifyOtpApi.pasteFromClipboard();
  if (!ok) {
    showVerifyError('Panoda 6 haneli kod yok. WhatsApp mesajından kodu kopyalayın.');
    return;
  }
  if (verifyError) verifyError.textContent = '';
});

async function loadArtists() {
  artistCards.innerHTML = '<p class="loading-text">Yükleniyor...</p>';
  artistContinueBtn.disabled = true;
  savedArtistId = null;
  savedArtistPhone = '';
  savedArtistName = '';

  const { ok, data } = await api('/api/artists', { method: 'GET' });
  if (!ok || !Array.isArray(data)) {
    artistCards.innerHTML = '<p class="empty-message">Personel yüklenemedi</p>';
    return;
  }

  artistCards.innerHTML = '';
  data.forEach((artist) => {
    const card = document.createElement('div');
    card.className = 'artist-card';
    const instagramUrl = (artist.instagram_url || '').trim();
    const portfolioHtml = instagramUrl
      ? `<a class="artist-portfolio-link" href="${escapeHtml(instagramUrl)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(artist.name)} Instagram portfolyosu">
          <i class="fab fa-instagram"></i>
          <span>Portfolyoya Göz At</span>
        </a>`
      : '';
    card.innerHTML = `
      <div class="artist-radio"></div>
      <div class="artist-photo">
        ${artist.profile_photo ? `<img src="${escapeHtml(artist.profile_photo)}" alt="${escapeHtml(artist.name)}">` : '<i class="fas fa-user"></i>'}
      </div>
      <div class="artist-info">
        <div class="artist-name">${escapeHtml(artist.name)}</div>
        <div class="artist-title"><i class="fas fa-pen-nib"></i> Dövme Sanatçısı</div>
      </div>
      ${portfolioHtml}
    `;
    card.querySelector('.artist-portfolio-link')?.addEventListener('click', (e) => {
      e.stopPropagation();
    });
    card.addEventListener('click', () => {
      document.querySelectorAll('.artist-card').forEach((c) => c.classList.remove('selected'));
      card.classList.add('selected');
      savedArtistId = artist.id;
      savedArtistPhone = artist.phone || '';
      savedArtistName = artist.name || '';
      artistContinueBtn.disabled = false;
    });
    artistCards.appendChild(card);
  });
}

artistContinueBtn?.addEventListener('click', async () => {
  if (!savedArtistId) return;
  artistSection.style.display = 'none';
  if (tattooConfigSection) tattooConfigSection.style.display = 'block';
  setTattooConfigStepActive(true);
  updateStepper(4);
  bookingLeftEl?.scrollTo({ top: 0, behavior: 'instant' });
  await initTattooConfigStep();
});

tattooConfigBackBtn?.addEventListener('click', () => {
  if (tattooConfigSection) tattooConfigSection.style.display = 'none';
  setTattooConfigStepActive(false);
  artistSection.style.display = 'block';
  updateStepper(3);
});

tattooConfigContinueBtn?.addEventListener('click', () => {
  if (!savedBodyRegion || !savedConfigSize) {
    showInlineError(
      tattooConfigError,
      !savedBodyRegion ? 'Lütfen bir vücut bölgesi seçin.' : 'Lütfen dövme büyüklüğünü seçin.'
    );
    updateConfigContinueState();
    return;
  }
  submitTattooRequest();
});

const loyaltyPointsInfoBtn = document.getElementById('loyalty-points-info-btn');
const loyaltyPointsInfo = document.getElementById('loyalty-points-info');

function setLoyaltyPointsInfoOpen(isOpen) {
  if (!loyaltyPointsInfo || !loyaltyPointsInfoBtn) return;
  loyaltyPointsInfo.hidden = !isOpen;
  loyaltyPointsInfoBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

loyaltyPointsInfoBtn?.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  setLoyaltyPointsInfoOpen(!!loyaltyPointsInfo?.hidden);
});

document.addEventListener('click', (e) => {
  if (!loyaltyPointsInfo || loyaltyPointsInfo.hidden) return;
  if (loyaltyPointsInfo.contains(e.target) || loyaltyPointsInfoBtn?.contains(e.target)) return;
  setLoyaltyPointsInfoOpen(false);
});

const configConfirmOverlay = document.getElementById('config-confirm-overlay');
const configConfirmTitle = document.getElementById('config-confirm-title');
const configConfirmMessage = document.getElementById('config-confirm-message');
const configConfirmIcon = document.getElementById('config-confirm-icon');
const configConfirmBackBtn = document.getElementById('config-confirm-back-btn');
const configConfirmOkBtn = document.getElementById('config-confirm-ok-btn');

const CONFIG_CONFIRM = {
  consultation: {
    title: 'Ön görüşme talebi',
    message: 'Bölge ve büyüklük seçmeden ön görüşme talebi oluşturulacak. Sanatçı sizinle iletişime geçecek. Onaylıyor musunuz?',
    icon: 'fas fa-comments',
    submit: { preConsultation: true },
  },
  undecided: {
    title: 'Karar verilmedi',
    message: 'Bölge ve büyüklük seçmeden talep oluşturulacak. Sanatçı sizinle iletişime geçecek. Onaylıyor musunuz?',
    icon: 'fas fa-forward',
    submit: { undecided: true },
  },
};

let pendingConfigConfirm = null;

function closeConfigConfirm() {
  pendingConfigConfirm = null;
  if (!configConfirmOverlay) return;
  configConfirmOverlay.classList.remove('is-open');
  configConfirmOverlay.style.display = 'none';
}

function openConfigConfirm(kind) {
  const meta = CONFIG_CONFIRM[kind];
  if (!meta) return;
  pendingConfigConfirm = kind;
  if (configConfirmTitle) configConfirmTitle.textContent = meta.title;
  if (configConfirmMessage) configConfirmMessage.textContent = meta.message;
  const iconEl = configConfirmIcon?.querySelector('i');
  if (iconEl) iconEl.className = meta.icon;
  if (configConfirmOverlay) {
    configConfirmOverlay.style.display = 'flex';
    configConfirmOverlay.classList.add('is-open');
  }
  configConfirmOkBtn?.focus();
}

tattooConfigConsultationBtn?.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  openConfigConfirm('consultation');
});

tattooConfigUndecidedBtn?.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  openConfigConfirm('undecided');
});

configConfirmBackBtn?.addEventListener('click', () => {
  closeConfigConfirm();
});

configConfirmOverlay?.addEventListener('click', (e) => {
  if (e.target === configConfirmOverlay) closeConfigConfirm();
});

configConfirmOkBtn?.addEventListener('click', () => {
  const meta = CONFIG_CONFIRM[pendingConfigConfirm];
  if (!meta) {
    closeConfigConfirm();
    return;
  }
  const kind = pendingConfigConfirm;
  closeConfigConfirm();
  const triggerBtn = kind === 'consultation' ? tattooConfigConsultationBtn : tattooConfigUndecidedBtn;
  submitTattooRequest({ ...meta.submit, triggerBtn });
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && configConfirmOverlay?.classList.contains('is-open')) {
    closeConfigConfirm();
  }
});

function getTattooWhatsAppContext(extra = {}) {
  const region = getRegionMeta(savedBodyRegion);
  return {
    artistPhone: savedArtistPhone,
    summary: {
      styleLabel: extra.styleLabel || '',
      regionLabel: region?.label || extra.regionLabel || '',
      size: savedConfigSize || extra.size || '',
      undecided: !!extra.undecided,
      preConsultation: !!extra.preConsultation,
      artistName: savedArtistName,
    },
  };
}

async function submitTattooRequest({ preConsultation = false, undecided = false, triggerBtn = null } = {}) {
  if (!savedArtistId) {
    showInlineError(tattooConfigError, 'Lütfen önce bir sanatçı seçin.');
    return;
  }

  showInlineError(tattooConfigError, '');

  if (!undecided && !preConsultation) {
    if (!savedBodyRegion) {
      showInlineError(tattooConfigError, 'Lütfen bir vücut bölgesi seçin.');
      return;
    }
    if (!savedConfigSize) {
      showInlineError(tattooConfigError, 'Lütfen dövme büyüklüğünü seçin.');
      return;
    }
  }

  const buttons = [tattooConfigContinueBtn, tattooConfigUndecidedBtn, tattooConfigConsultationBtn, triggerBtn].filter(Boolean);
  buttons.forEach((b) => { b.disabled = true; });

  const regionMeta = getRegionMeta(savedBodyRegion);
  const loyaltyCodeRaw = document.getElementById('tattoo-loyalty-code')?.value?.trim() || '';

  const payload = {
    phone: savedPhone,
    staff_id: savedArtistId,
    config_undecided: undecided,
    reference_image: '',
    description: '',
  };

  if (loyaltyCodeRaw) {
    payload.loyalty_code = loyaltyCodeRaw.toUpperCase();
    try {
      const check = await api('/api/loyalty/validate-code', {
        method: 'POST',
        body: JSON.stringify({ phone: savedPhone, loyalty_code: payload.loyalty_code }),
      });
      if (!check.ok || !check.data.success) {
        showInlineError(tattooConfigError, check.data?.message || 'İndirim kodu geçersiz');
        buttons.forEach((b) => { b.disabled = false; });
        return;
      }
    } catch (_e) {
      showInlineError(tattooConfigError, 'İndirim kodu doğrulanamadı');
      buttons.forEach((b) => { b.disabled = false; });
      return;
    }
  }

  if (preConsultation) {
    Object.assign(payload, {
      pre_consultation: true,
      tattoo_style: 'pre_consultation',
      body_area: 'Ön görüşme',
    });
  } else if (undecided) {
    Object.assign(payload, {
      tattoo_style: 'undecided',
      body_area: 'Henüz belirlenmedi',
      size: null,
      body_region: '',
    });
  } else {
    Object.assign(payload, {
      size: savedConfigSize,
      body_region: savedBodyRegion,
      body_area: regionMeta?.label || '',
    });
  }

  const waCtx = getTattooWhatsAppContext({
    undecided,
    preConsultation,
    regionLabel: payload.body_area,
    styleLabel: preConsultation ? 'Ön görüşme' : undecided ? 'Henüz belirlenmedi' : '',
  });

  try {
    const { ok, data } = await api('/api/tattoo-requests', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (!ok || !data.success) {
      showInlineError(tattooConfigError, data.message || 'Talep gönderilemedi');
      return;
    }

    if (tattooConfigSection) tattooConfigSection.style.display = 'none';
    setTattooConfigStepActive(false);
    updateStepper(5);

    let defaultMessage = 'Talebiniz alındı. Sanatçı süre belirleyip link gönderecek.';
    if (data.loyalty_discount?.code) {
      defaultMessage += ` İndirim kodunuz (${data.loyalty_discount.code}) talebe eklendi.`;
    }
    if (preConsultation) {
      defaultMessage = 'Ön görüşme talebiniz alındı. Lütfen sanatçıya aşağıdaki butondan mesajınızı gönderiniz.';
    } else if (undecided) {
      defaultMessage = 'Talebiniz alındı. Lütfen sanatçıya aşağıdaki butondan mesajınızı gönderiniz.';
    }

    showTattooRequestSuccess(data, defaultMessage, () => location.reload(), waCtx);
  } finally {
    buttons.forEach((b) => { b.disabled = false; });
  }
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

setupTattooScrollHints();
