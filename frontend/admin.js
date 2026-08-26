// Minimal admin panel for tattoo request offer flow
function getApiBase() {
  const stored = localStorage.getItem('API_BASE_URL');
  if (stored) return `${stored.replace(/\/$/, '')}/api`;

  const isLocal =
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1';
  const isLikelyStaticPort =
    window.location.port && window.location.port !== '3000';

  if (isLocal && isLikelyStaticPort) return 'http://127.0.0.1:3000/api';
  return '/api';
}

const API_BASE = getApiBase();

function hasStudioAccess(role = getLoggedInStaff()?.role) {
  return role === 'super_admin' || role === 'tech_support';
}

function canAccessIncome(role = getLoggedInStaff()?.role) {
  return role === 'super_admin';
}

function canAccessTattooRequests(role = getLoggedInStaff()?.role) {
  return role === 'super_admin' || role === 'staff';
}

function isBookableStaffRole(role) {
  return role !== 'tech_support';
}

const ADMIN_TOKEN_KEY = 'adminToken';
const ADMIN_STAFF_KEY = 'adminStaff';
const ADMIN_REMEMBER_KEY = 'adminRememberMe';
const ADMIN_REMEMBER_PHONE_KEY = 'adminRememberPhone';
const ADMIN_SESSION_ACTIVE_KEY = 'adminSessionActive';

function getAdminToken() {
  return localStorage.getItem(ADMIN_TOKEN_KEY) || sessionStorage.getItem(ADMIN_TOKEN_KEY) || '';
}

function getAdminStaffRaw() {
  return localStorage.getItem(ADMIN_STAFF_KEY) || sessionStorage.getItem(ADMIN_STAFF_KEY);
}

function getAdminStaff() {
  try {
    return JSON.parse(getAdminStaffRaw() || 'null');
  } catch {
    return null;
  }
}

function getAdminSessionStorage() {
  if (localStorage.getItem(ADMIN_TOKEN_KEY)) return localStorage;
  if (sessionStorage.getItem(ADMIN_TOKEN_KEY)) return sessionStorage;
  return null;
}

function setAdminSession(token, staff, rememberMe) {
  localStorage.removeItem(ADMIN_TOKEN_KEY);
  localStorage.removeItem(ADMIN_STAFF_KEY);
  sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  sessionStorage.removeItem(ADMIN_STAFF_KEY);

  const store = rememberMe ? localStorage : sessionStorage;
  store.setItem(ADMIN_TOKEN_KEY, token);
  store.setItem(ADMIN_STAFF_KEY, JSON.stringify(staff));

  if (rememberMe) {
    localStorage.setItem(ADMIN_REMEMBER_KEY, '1');
  } else {
    localStorage.removeItem(ADMIN_REMEMBER_KEY);
    localStorage.removeItem(ADMIN_REMEMBER_PHONE_KEY);
  }
}

function clearAdminSession({ keepRememberPrefs = false, softLogout = false } = {}) {
  sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  sessionStorage.removeItem(ADMIN_STAFF_KEY);
  sessionStorage.removeItem(ADMIN_SESSION_ACTIVE_KEY);

  if (softLogout && keepRememberPrefs && isAdminRememberMe()) {
    return;
  }

  localStorage.removeItem(ADMIN_TOKEN_KEY);
  localStorage.removeItem(ADMIN_STAFF_KEY);
  if (!keepRememberPrefs) {
    localStorage.removeItem(ADMIN_REMEMBER_KEY);
    localStorage.removeItem(ADMIN_REMEMBER_PHONE_KEY);
  }
}

function hasRememberSession() {
  return isAdminRememberMe() && !!getAdminToken() && !!getAdminStaffRaw();
}

function updateLoginModeUI() {
  const quickWrap = $('login-quick-wrap');
  const loginForm = $('login-form');
  if (!quickWrap || !loginForm) return;

  if (hasRememberSession()) {
    const staff = getAdminStaff();
    const phone = localStorage.getItem(ADMIN_REMEMBER_PHONE_KEY) || '';
    if ($('login-quick-name')) $('login-quick-name').textContent = staff?.name || 'Admin';
    if ($('login-quick-phone')) {
      $('login-quick-phone').textContent = phone ? formatPhonePretty(phone) : '';
    }
    quickWrap.style.display = 'block';
    loginForm.style.display = 'none';
  } else {
    quickWrap.style.display = 'none';
    loginForm.style.display = '';
    initRememberMeForm();
  }
}

function isAdminRememberMe() {
  return localStorage.getItem(ADMIN_REMEMBER_KEY) === '1';
}

function syncRememberCheckboxUI() {
  const cb = $('login-remember-me');
  const wrap = $('login-remember-wrap');
  if (!cb || !wrap) return;
  wrap.classList.toggle('is-checked', cb.checked);
  wrap.setAttribute('aria-pressed', cb.checked ? 'true' : 'false');
}

function initRememberMeForm() {
  const remember = isAdminRememberMe();
  const phone = localStorage.getItem(ADMIN_REMEMBER_PHONE_KEY) || '';
  if ($('login-remember-me')) $('login-remember-me').checked = remember;
  if ($('login-phone') && phone) $('login-phone').value = phone;
  syncRememberCheckboxUI();
}

function initRememberMeToggle() {
  const wrap = $('login-remember-wrap');
  const cb = $('login-remember-me');
  if (!wrap || !cb || wrap.dataset.bound === '1') return;
  wrap.dataset.bound = '1';

  const toggleRemember = () => {
    cb.checked = !cb.checked;
    syncRememberCheckboxUI();
  };

  wrap.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    toggleRemember();
  });

  wrap.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleRemember();
    }
  });

  syncRememberCheckboxUI();
}

function persistAdminStaff(staff) {
  const store = getAdminSessionStorage() || localStorage;
  store.setItem(ADMIN_STAFF_KEY, JSON.stringify(staff));
}

function $(id) { return document.getElementById(id); }

// =============================================
// CUSTOM MODAL HELPERS (prompt / confirm yerine)
// =============================================
let _promptResolve  = null;
let _confirmResolve = null;
let _offerFormResolve = null;
let _offerFormLoyalty = null;
let _offerPriceInputHandler = null;

function updateOfferDiscountPreview() {
  const preview = $('offer-form-discount-preview');
  const priceInput = $('offer-form-price');
  if (!preview || !_offerFormLoyalty || _offerFormLoyalty.used) {
    if (preview) preview.hidden = true;
    return;
  }
  const listPrice = parseFloat(priceInput?.value || '0') || 0;
  if (listPrice <= 0) {
    preview.hidden = true;
    return;
  }
  const pct = _offerFormLoyalty.discount_percent || 10;
  const finalPrice = Math.round(listPrice * (1 - pct / 100) * 100) / 100;
  preview.hidden = false;
  preview.textContent =
    `Müşteriye gönderilecek fiyat: ${finalPrice.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺ ` +
    `(liste ${listPrice.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺, %${pct} indirim)`;
}

// Offer form modal — süre + fiyat
function openOfferFormModal(desc = '', defaultPrice = null, loyaltyDiscount = null) {
  return new Promise((resolve) => {
    _offerFormResolve = resolve;
    _offerFormLoyalty = loyaltyDiscount;
    const overlay = $('offer-form-overlay');
    const banner = $('offer-form-loyalty-banner');
    const priceHint = $('offer-form-price-hint');
    const priceInput = $('offer-form-price');

    $('offer-form-desc').textContent = desc;
    $('offer-form-duration').value   = '120';
    $('offer-form-price').value      =
      defaultPrice != null && Number(defaultPrice) > 0 ? String(Number(defaultPrice)) : '';

    if (banner) {
      if (loyaltyDiscount && !loyaltyDiscount.used) {
        banner.hidden = false;
        banner.innerHTML =
          `<i class="fas fa-gift"></i> Sadakat kodu: <strong>${escapeHtml(loyaltyDiscount.code)}</strong> ` +
          `(%${loyaltyDiscount.discount_percent} indirim — liste fiyatı girin, müşteriye indirimli gönderilir)`;
      } else if (loyaltyDiscount?.used) {
        banner.hidden = false;
        banner.innerHTML =
          `<i class="fas fa-check-circle"></i> Kod <strong>${escapeHtml(loyaltyDiscount.code)}</strong> daha önce kullanıldı.`;
      } else {
        banner.hidden = true;
        banner.innerHTML = '';
      }
    }

    if (priceHint) {
      priceHint.textContent = loyaltyDiscount && !loyaltyDiscount.used
        ? 'Liste fiyatını girin; sadakat indirimi otomatik uygulanır.'
        : 'Randevu tamamlandığında gelir raporuna otomatik eklenir.';
    }

    if (priceInput) {
      if (_offerPriceInputHandler) {
        priceInput.removeEventListener('input', _offerPriceInputHandler);
      }
      _offerPriceInputHandler = () => updateOfferDiscountPreview();
      priceInput.addEventListener('input', _offerPriceInputHandler);
    }
    updateOfferDiscountPreview();

    overlay.style.display = 'flex';
    setTimeout(() => $('offer-form-duration')?.focus(), 50);
  });
}

function closeOfferFormModal() {
  $('offer-form-overlay').style.display = 'none';
  if (_offerFormResolve) { _offerFormResolve(null); _offerFormResolve = null; }
}

function resolveOfferForm() {
  const durationRaw = parseInt($('offer-form-duration')?.value || '0', 10);
  const priceRaw    = parseFloat($('offer-form-price')?.value  || '0') || 0;
  if (!durationRaw || durationRaw < 60 || durationRaw % 60 !== 0) {
    alert('Süre 60\'ın katı olmalı (örn: 60, 120, 180)');
    return;
  }
  $('offer-form-overlay').style.display = 'none';
  if (_offerFormResolve) {
    _offerFormResolve({ duration_minutes: durationRaw, price: priceRaw });
    _offerFormResolve = null;
  }
}

function customPrompt(title, desc, defaultValue = '') {
  return new Promise((resolve) => {
    _promptResolve = resolve;
    const overlay = $('custom-prompt-overlay');
    $('custom-prompt-title').textContent = title;
    $('custom-prompt-desc').textContent = desc;
    const input = $('custom-prompt-input');
    input.value = defaultValue;
    overlay.style.display = 'flex';
    setTimeout(() => input.focus(), 50);
    input.onkeydown = (e) => { if (e.key === 'Enter') customPromptResolve(input.value); };
  });
}

function customPromptResolve(value) {
  $('custom-prompt-overlay').style.display = 'none';
  if (_promptResolve) { _promptResolve(value); _promptResolve = null; }
}

function customConfirm(title, message) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    $('custom-confirm-title').textContent = title;
    $('custom-confirm-message').textContent = message;
    $('custom-confirm-overlay').style.display = 'flex';
  });
}

function customConfirmResolve(value) {
  $('custom-confirm-overlay').style.display = 'none';
  if (_confirmResolve) { _confirmResolve(value); _confirmResolve = null; }
}

// Time-off form modal
let _timeOffResolve = null;

function openTimeOffFormModal() {
  return new Promise((resolve) => {
    _timeOffResolve = resolve;
    const overlay = $('time-off-form-overlay');
    $('tof-date').value = new Date().toISOString().slice(0, 10);
    $('tof-fullday').checked = true;
    $('tof-time-range').style.display = 'none';
    $('tof-reason').value = '';
    overlay.style.display = 'flex';

    $('tof-fullday').onchange = function() {
      $('tof-time-range').style.display = this.checked ? 'none' : 'flex';
    };
  });
}

function closeTimeOffFormModal() {
  $('time-off-form-overlay').style.display = 'none';
  if (_timeOffResolve) { _timeOffResolve(null); _timeOffResolve = null; }
}

function submitTimeOffForm() {
  const date = $('tof-date').value;
  if (!date) return;
  const fullDay = $('tof-fullday').checked;
  const result = {
    date,
    off_date: date,
    start_time: fullDay ? null : ($('tof-start').value || '10:00'),
    end_time: fullDay ? null : ($('tof-end').value || '12:00'),
    reason: $('tof-reason').value || '',
  };
  $('time-off-form-overlay').style.display = 'none';
  if (_timeOffResolve) { _timeOffResolve(result); _timeOffResolve = null; }
}

// Offer URL Modal
function showOfferUrlModal(offerUrl, whatsappSent) {
  const overlay = $('offer-url-overlay');
  if (!overlay) return;
  $('offer-url-input').value = offerUrl || '';
  const statusEl = $('offer-url-whatsapp-status');
  if (whatsappSent) {
    statusEl.textContent = '✅ WhatsApp mesajı müşteriye gönderildi (Evolution).';
    statusEl.style.background = 'rgba(111, 154, 111, 0.16)';
    statusEl.style.color = '#6F9A6F';
    statusEl.style.border = '1px solid rgba(111, 154, 111, 0.28)';
  } else {
    statusEl.innerHTML =
      '⚠️ WhatsApp mesajı <strong>ulaşmadı</strong> — teklif kaydı oluştu. Linki kopyalayıp müşterinin numarasına manuel gönderin.';
    statusEl.style.background = 'rgba(201, 154, 74, 0.16)';
    statusEl.style.color = '#C99A4A';
    statusEl.style.border = '1px solid rgba(201, 154, 74, 0.32)';
  }
  overlay.style.display = 'flex';
}

function closeOfferUrlModal() {
  const overlay = $('offer-url-overlay');
  if (overlay) overlay.style.display = 'none';
}

function copyOfferUrl() {
  const input = $('offer-url-input');
  if (!input) return;
  navigator.clipboard.writeText(input.value).then(() => {
    const btn = $('copy-offer-btn');
    if (btn) { btn.innerHTML = '<i class="fas fa-check"></i> Kopyalandı'; setTimeout(() => { btn.innerHTML = '<i class="fas fa-copy"></i> Kopyala'; }, 2000); }
  }).catch(() => {
    input.select();
    document.execCommand('copy');
  });
}

function showToast(message, type = 'success') {
  const toast = $('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.className = `toast ${type} show`;
  setTimeout(() => toast.classList.remove('show'), 3000);
}

function roleLabel(role) {
  if (role === 'super_admin') return 'Super Admin';
  if (role === 'tech_support') return 'Teknik Destek';
  return 'Personel Sanatçı';
}

function normalizePhone10(phone) {
  return String(phone || '').replace(/\D/g, '').slice(-10);
}

function updateSidebarStaffInfo(partial) {
  const staff = getAdminStaff();
  if (!staff) return;
  const next = { ...staff, ...partial };
  persistAdminStaff(next);

  if ($('user-name')) $('user-name').textContent = next.name || '-';
  if ($('user-role')) $('user-role').textContent = roleLabel(next.role);
  setRoleVisibility(next.role);
}

function passwordsTooSimilar(oldPassword, newPassword) {
  if (!oldPassword || !newPassword) return false;
  const oldPw = oldPassword.trim();
  const newPw = newPassword.trim();
  if (oldPw === newPw) return true;
  if (oldPw.toLowerCase() === newPw.toLowerCase()) return true;
  const oldLow = oldPw.toLowerCase();
  const newLow = newPw.toLowerCase();
  if (oldLow.length >= 3 && newLow.includes(oldLow)) return true;
  if (newLow.length >= 3 && oldLow.includes(newLow)) return true;
  return false;
}

function openProfileModal() {
  const staff = getLoggedInStaff();
  if (!staff) {
    showToast('Oturum bilgisi bulunamadı', 'error');
    return;
  }

  const nameEl = $('profile-name');
  const roleEl = $('profile-role');
  if (nameEl) nameEl.textContent = staff.name || '-';
  if (roleEl) roleEl.textContent = roleLabel(staff.role);

  const errEl = $('password-error');
  if (errEl) errEl.textContent = '';
  $('change-password-form')?.reset();

  const igErr = $('instagram-profile-error');
  if (igErr) igErr.textContent = '';
  const igInput = $('profile-instagram-url');
  if (igInput) igInput.value = '';

  const overlay = $('profile-overlay');
  if (overlay) overlay.style.display = 'flex';

  apiCall('/admin/me', { method: 'GET' }).then(({ ok, data }) => {
    if (!ok || !data.success || !igInput) return;
    igInput.value = data.staff?.instagram_url || '';
  });
}

function closeProfileModal() {
  const overlay = $('profile-overlay');
  if (overlay) overlay.style.display = 'none';
  $('change-password-form')?.reset();
  $('instagram-profile-form')?.reset();
  const errEl = $('password-error');
  if (errEl) errEl.textContent = '';
  const igErr = $('instagram-profile-error');
  if (igErr) igErr.textContent = '';
}

async function submitInstagramProfile(e) {
  e.preventDefault();
  const errEl = $('instagram-profile-error');
  if (errEl) errEl.textContent = '';

  const instagramUrl = ($('profile-instagram-url')?.value || '').trim();

  const { ok, data } = await apiCall('/admin/my-profile', {
    method: 'PATCH',
    body: JSON.stringify({ instagram_url: instagramUrl }),
  });

  if (!ok || !data.success) {
    if (errEl) errEl.textContent = data?.message || 'Instagram linki kaydedilemedi';
    return;
  }

  showToast(data.message || 'Instagram linki kaydedildi', 'success');
  if ($('profile-instagram-url')) {
    $('profile-instagram-url').value = data.instagram_url || '';
  }
}

async function submitChangePassword(e) {
  e.preventDefault();
  const errEl = $('password-error');
  if (errEl) errEl.textContent = '';

  const oldPassword = ($('old-password')?.value || '').trim();
  const newPassword = ($('new-password')?.value || '').trim();
  const confirmPassword = ($('confirm-password')?.value || '').trim();

  if (!oldPassword || !newPassword || !confirmPassword) {
    if (errEl) errEl.textContent = 'Tüm alanları doldurun';
    return;
  }
  if (newPassword.length < 6) {
    if (errEl) errEl.textContent = 'Yeni şifre en az 6 karakter olmalı';
    return;
  }
  if (newPassword !== confirmPassword) {
    if (errEl) errEl.textContent = 'Yeni şifreler eşleşmiyor';
    return;
  }
  if (passwordsTooSimilar(oldPassword, newPassword)) {
    if (errEl) errEl.textContent = 'Yeni şifre mevcut şifre ile aynı veya çok benzer olamaz';
    return;
  }

  const { ok, data } = await apiCall('/admin/change-password', {
    method: 'POST',
    body: JSON.stringify({
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
  });

  if (!ok || !data.success) {
    if (errEl) errEl.textContent = data?.message || 'Şifre değiştirilemedi';
    return;
  }

  showToast(data.message || 'Şifre başarıyla değiştirildi', 'success');
  closeProfileModal();
}

// =============================================
// SESSION / INACTIVITY TIMEOUT (30 dakika)
// =============================================
const SESSION_TIMEOUT_MS  = 30 * 60 * 1000;  // 30 dakika
const SESSION_WARNING_SEC = 60;               // Uyarı kaç saniye önce gelsin

let _inactivityTimer   = null;
let _warningTimer      = null;
let _countdownInterval = null;

function resetInactivityTimer() {
  clearTimeout(_inactivityTimer);
  clearTimeout(_warningTimer);
  // Uyarı modalı açıksa kapat
  const overlay = $('session-timeout-overlay');
  if (overlay && overlay.style.display !== 'none') return; // Uyarı gösteriliyorsa timer sıfırlama

  // (30 dk - 60 sn) sonra uyarıyı göster
  _warningTimer = setTimeout(showSessionWarning, SESSION_TIMEOUT_MS - SESSION_WARNING_SEC * 1000);
  // 30 dk sonra çıkış yap
  _inactivityTimer = setTimeout(sessionLogoutNow, SESSION_TIMEOUT_MS);
}

function showSessionWarning() {
  const overlay = $('session-timeout-overlay');
  if (!overlay) return;
  overlay.style.display = 'flex';
  let secs = SESSION_WARNING_SEC;
  $('session-countdown').textContent = secs;
  clearInterval(_countdownInterval);
  _countdownInterval = setInterval(() => {
    secs--;
    const el = $('session-countdown');
    if (el) el.textContent = secs;
    if (secs <= 0) clearInterval(_countdownInterval);
  }, 1000);
}

function sessionExtend() {
  clearInterval(_countdownInterval);
  const overlay = $('session-timeout-overlay');
  if (overlay) overlay.style.display = 'none';
  resetInactivityTimer();
}

function sessionLogoutNow() {
  clearTimeout(_inactivityTimer);
  clearTimeout(_warningTimer);
  clearInterval(_countdownInterval);
  const overlay = $('session-timeout-overlay');
  if (overlay) overlay.style.display = 'none';
  logout({ soft: isAdminRememberMe() });
}

function startInactivityWatcher() {
  ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click'].forEach((evt) => {
    document.addEventListener(evt, () => {
      // Sadece uyarı yokken timer'ı sıfırla
      const overlay = $('session-timeout-overlay');
      if (!overlay || overlay.style.display === 'none') resetInactivityTimer();
    }, { passive: true });
  });
  resetInactivityTimer();
}

function stopInactivityWatcher() {
  clearTimeout(_inactivityTimer);
  clearTimeout(_warningTimer);
  clearInterval(_countdownInterval);
}

// =============================================
// API CALL
// =============================================
async function apiCall(endpoint, options = {}) {
  const token = getAdminToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));

  // 401 gelirse token geçersiz/süresi dolmuş — login ekranına at
  if (res.status === 401 && endpoint !== '/admin/login') {
    stopInactivityWatcher();
    clearAdminSession({ keepRememberPrefs: true });
    setPage(false);
    updateLoginModeUI();
    return { ok: false, status: 401, data };
  }

  return { ok: res.ok, status: res.status, data };
}

// =========================
// STAFF MODAL (create/edit)
// =========================

let staffModalState = { mode: 'create', staffId: null };
let staffPhotoData = undefined;
let staffPhotoChanged = false;

function resetStaffPhotoPreview(photoUrl) {
  const img = $('staff-photo-img');
  const icon = $('staff-photo-icon');
  const removeBtn = $('staff-photo-remove-btn');
  const input = $('staff-photo-input');
  if (input) input.value = '';

  if (photoUrl) {
    if (img) {
      img.src = photoUrl;
      img.style.display = 'block';
    }
    if (icon) icon.style.display = 'none';
    if (removeBtn) removeBtn.style.display = '';
  } else {
    if (img) {
      img.src = '';
      img.style.display = 'none';
    }
    if (icon) icon.style.display = '';
    if (removeBtn) removeBtn.style.display = 'none';
  }
}

function setStaffPhotoFromFile(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    showToast('Geçerli bir görsel dosyası seçin', 'error');
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showToast('Fotoğraf en fazla 2 MB olabilir', 'error');
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    staffPhotoData = reader.result;
    staffPhotoChanged = true;
    resetStaffPhotoPreview(staffPhotoData);
  };
  reader.onerror = () => showToast('Fotoğraf okunamadı', 'error');
  reader.readAsDataURL(file);
}

function closeStaffModal() {
  const overlay = $('staff-modal-overlay');
  if (overlay) overlay.style.display = 'none';
  $('staff-error').textContent = '';
  $('staff-id').value = '';
  $('staff-name').value = '';
  $('staff-phone').value = '';
  $('staff-password').value = '';
  $('staff-role').value = 'staff';
  if ($('staff-instagram-url')) $('staff-instagram-url').value = '';
  staffPhotoData = undefined;
  staffPhotoChanged = false;
  resetStaffPhotoPreview(null);
}

function openStaffModal({ mode, staff } = { mode: 'create', staff: null }) {
  staffModalState = { mode, staffId: staff?.id ?? null };

  const overlay = $('staff-modal-overlay');
  const title = $('staff-modal-title');
  const idEl = $('staff-id');
  const nameEl = $('staff-name');
  const phoneEl = $('staff-phone');
  const passEl = $('staff-password');
  const roleEl = $('staff-role');
  const roleSelectEl = $('staff-role-select');

  if (title) {
    title.innerHTML = mode === 'edit'
      ? '<i class="fas fa-user-pen"></i> Personeli Düzenle'
      : '<i class="fas fa-user-plus"></i> Yeni Personel';
  }

  if (idEl) idEl.value = staff?.id ? String(staff.id) : '';
  if (nameEl) nameEl.value = staff?.name || '';
  if (phoneEl) phoneEl.value = staff?.phone || '';
  if (passEl) passEl.value = '';
  if (roleEl) roleEl.value = staff?.role || 'staff';
  if (roleSelectEl) {
    const superOpt = [...roleSelectEl.options].find((o) => o.value === 'super_admin');
    if (superOpt) {
      const allowSuper = canAccessIncome();
      superOpt.hidden = !allowSuper;
      superOpt.disabled = !allowSuper;
    }
    const wanted = staff?.role || 'staff';
    const canSelect = [...roleSelectEl.options].some((o) => o.value === wanted && !o.disabled);
    roleSelectEl.value = canSelect ? wanted : 'staff';
    roleEl.value = roleSelectEl.value;
  }
  if ($('staff-instagram-url')) $('staff-instagram-url').value = staff?.instagram_url || '';

  staffPhotoData = undefined;
  staffPhotoChanged = false;
  resetStaffPhotoPreview(staff?.profile_photo || null);

  if (overlay) overlay.style.display = 'flex';
}

function setPage(loggedIn) {
  $('login-page').style.display = loggedIn ? 'none' : 'block';
  $('dashboard-page').style.display = loggedIn ? 'block' : 'none';
  // Footer sadece login ekranında görünsün
  const footer = document.querySelector('.dev-footer');
  if (footer) footer.style.display = loggedIn ? 'none' : 'block';
}

function showSection(page) {
  if (page !== 'api-settings') stopWapioStatusPolling();
  document.querySelectorAll('.nav-item').forEach((i) => i.classList.remove('active'));
  document.querySelectorAll('.content-section').forEach((s) => (s.style.display = 'none'));

  const nav = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (nav) nav.classList.add('active');

  const sec = $(`section-${page}`);
  if (sec) sec.style.display = 'block';
}

function setRoleVisibility(role) {
  const studio = hasStudioAccess(role);
  const income = canAccessIncome(role);
  const tattoo = canAccessTattooRequests(role);

  document.querySelectorAll('.super-admin-only').forEach((el) => {
    const page = el.getAttribute('data-page');
    const incomeOnly = page === 'reports' || el.classList.contains('income-only');
    const tattooOnly = page === 'all-tattoo-requests' || el.classList.contains('tattoo-request-nav');
    let show = studio;
    if (incomeOnly) show = income;
    if (tattooOnly) show = role === 'super_admin';
    el.style.display = show ? '' : 'none';
  });

  document.querySelectorAll('.tattoo-request-nav').forEach((el) => {
    if (el.classList.contains('super-admin-only')) return;
    el.style.display = tattoo ? '' : 'none';
  });
}

function formatTodayDdMmYyyy() {
  const d = new Date();
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = String(d.getFullYear());
  return `${dd}.${mm}.${yyyy}`;
}

function statusText(status) {
  const map = {
    pending: 'Bekliyor',
    confirmed: 'Onaylandı',
    completed: 'Tamamlandı',
    cancelled: 'İptal',
    no_show: 'Gelmedi',
  };
  return map[status] || status || '-';
}

function appointmentSourceKey(source) {
  const key = String(source || 'admin').toLowerCase();
  return ['customer', 'admin', 'google'].includes(key) ? key : 'admin';
}

function appointmentSourceText(source) {
  const map = {
    customer: 'Müşteri',
    admin: 'Admin',
    google: 'Google',
  };
  return map[appointmentSourceKey(source)];
}

function appointmentSourceBadgeHtml(source) {
  const key = appointmentSourceKey(source);
  return `<span class="source-badge source-${key}">${escapeHtml(appointmentSourceText(key))}</span>`;
}

const APT_STATUS_OPTIONS = [
  { value: 'confirmed', label: 'Onaylandı' },
  { value: 'completed', label: 'Tamamlandı' },
  { value: 'cancelled', label: 'İptal' },
  { value: 'no_show', label: 'Gelmedi' },
];

function isAppointmentStartInFuture(appointment) {
  if (!appointment) return false;
  if (typeof appointment.can_complete === 'boolean') {
    return !appointment.can_complete;
  }
  const dateStr = String(appointment.date || '');
  const timeStr = String(appointment.time || '00:00').slice(0, 5);
  const [d, m, y] = dateStr.split('.');
  const [hh, mm] = timeStr.split(':');
  if (!d || !m || !y) return false;
  const pad = (n) => String(n).padStart(2, '0');
  const iso = `${y}-${pad(m)}-${pad(d)}T${pad(hh || 0)}:${pad(mm || 0)}:00+03:00`;
  const start = new Date(iso);
  if (Number.isNaN(start.getTime())) return false;
  return start.getTime() > Date.now();
}

function renderAppointmentStatusControls(appointmentId, currentStatus, appointment) {
  const futureStart = isAppointmentStartInFuture(appointment);
  const buttons = APT_STATUS_OPTIONS.map((opt) => {
    const isCurrent = opt.value === currentStatus;
    const blockComplete = opt.value === 'completed' && futureStart && !isCurrent;
    const disabled = isCurrent || blockComplete;
    const extraClass = blockComplete ? ' is-blocked' : '';
    const title = blockComplete
      ? ' title="Randevu saati gelmeden tamamlandı işaretlenemez"'
      : '';
    return `<button type="button" class="apt-status-btn${isCurrent ? ' is-current' : ''}${extraClass}" data-status-id="${appointmentId}" data-status-val="${opt.value}" ${disabled ? 'disabled' : ''}${title}>${opt.label}</button>`;
  }).join('');
  return `<div class="apt-status-grid"><span class="apt-status-grid-label">Durum değiştir</span><div class="apt-status-grid-btns">${buttons}</div></div>`;
}

async function updateAppointmentStatus(appointmentId, newStatus) {
  const { ok, data } = await apiCall(`/admin/appointments/${appointmentId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status: newStatus }),
  });
  if (!ok || !data.success) {
    showToast(data?.message || 'Durum güncellenemedi', 'error');
    return false;
  }
  showToast('Durum güncellendi', 'success');
  return true;
}

async function reloadActiveAdminAppointments() {
  const active = document.querySelector('.nav-item.active')?.getAttribute('data-page');
  if (active === 'dashboard') await loadDashboard();
  if (active === 'appointments') await loadAppointments();
  if (active === 'pending') await loadPending();
  if (active === 'all-appointments') await loadAllAppointments();
  if (active === 'past-appointments') await loadPastAppointments();
}

// =============================================
// MANUEL RANDEVU
// =============================================

function getLoggedInStaff() {
  try {
    return getAdminStaff();
  } catch {
    return null;
  }
}

function isoDateToTr(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

function getManualApptStaffId() {
  const staff = getLoggedInStaff();
  const group = $('manual-appt-staff-group');
  const sel = $('manual-appt-staff');
  if (hasStudioAccess(staff?.role) && group?.style.display !== 'none' && sel?.value) {
    return parseInt(sel.value, 10);
  }
  return staff?.id != null ? parseInt(staff.id, 10) : null;
}

async function populateManualApptStaffSelect() {
  const staff = getLoggedInStaff();
  const group = $('manual-appt-staff-group');
  const sel = $('manual-appt-staff');
  if (!group || !sel) return;
  if (!hasStudioAccess(staff?.role)) {
    group.style.display = 'none';
    return;
  }
  group.style.display = 'block';
  const { ok, data } = await apiCall('/admin/staff', { method: 'GET' });
  if (!ok || !data.success) return;
  const list = (data.staff || []).filter((s) => isBookableStaffRole(s.role));
  sel.innerHTML = list.map((s) =>
    `<option value="${s.id}">${escapeHtml(s.name || '')}</option>`
  ).join('');
  const preferred = list.find((s) => String(s.id) === String(staff?.id)) || list[0];
  if (preferred) sel.value = String(preferred.id);
}

function localIsoDate(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

let manualApptDatePicker = null;

function initManualApptDatePicker() {
  const el = $('manual-appt-date');
  if (!el || typeof flatpickr === 'undefined') return;

  if (manualApptDatePicker) {
    manualApptDatePicker.destroy();
    manualApptDatePicker = null;
  }

  manualApptDatePicker = flatpickr(el, {
    locale: 'tr',
    dateFormat: 'Y-m-d',
    altInput: true,
    altFormat: 'd.m.Y',
    minDate: 'today',
    disableMobile: true,
    allowInput: false,
    clickOpens: true,
    onChange: () => loadManualAppointmentTimeSlots(),
  });
}

async function loadManualAppointmentTimeSlots() {
  const timeSel = $('manual-appt-time');
  const errEl = $('manual-appt-error');
  if (!timeSel) return;

  const dateIso = manualApptDatePicker?.selectedDates?.[0]
    ? manualApptDatePicker.formatDate(manualApptDatePicker.selectedDates[0], 'Y-m-d')
    : ($('manual-appt-date')?.value || '');
  const duration = parseInt($('manual-appt-duration')?.value || '0', 10);
  const staffId = getManualApptStaffId();

  if (!dateIso || !staffId || !duration || duration < 60) {
    timeSel.innerHTML = '<option value="">Önce tarih ve süre seçin</option>';
    timeSel.disabled = true;
    return;
  }

  timeSel.disabled = true;
  timeSel.innerHTML = '<option value="">Saatler yükleniyor...</option>';
  if (errEl) errEl.style.display = 'none';

  const dateTr = isoDateToTr(dateIso);
  const qs = new URLSearchParams({
    staff_id: String(staffId),
    date: dateTr,
    duration_minutes: String(duration),
  });

  try {
    const { ok, data } = await apiCall(`/admin/manual-appointment/available-slots?${qs.toString()}`, {
      method: 'GET',
    });
    if (!ok || !data.success) {
      timeSel.innerHTML = '<option value="">Uygun saat bulunamadı</option>';
      return;
    }
    if (data.is_day_closed) {
      timeSel.innerHTML = '<option value="">Bu gün kapalı</option>';
      return;
    }
    const slots = data.available_start_slots || [];
    if (!slots.length) {
      const hint = data.work_start && data.work_end
        ? ` (${data.work_start}–${data.work_end} mesai)`
        : '';
      timeSel.innerHTML = `<option value="">Bu gün için uygun saat yok${hint}</option>`;
      return;
    }
    const rangeHint = data.work_start && data.work_end
      ? ` — mesai ${data.work_start}–${data.work_end}`
      : '';
    timeSel.innerHTML = `<option value="">Saat seçin${rangeHint}</option>` +
      slots.map((t) => `<option value="${t}">${t}</option>`).join('');
    timeSel.disabled = false;
  } catch (e) {
    console.error(e);
    timeSel.innerHTML = '<option value="">Yükleme hatası</option>';
  }
}

function openManualAppointmentModal() {
  const overlay = $('manual-appointment-overlay');
  if (!overlay) return;
  $('manual-appointment-form')?.reset();
  if ($('manual-appt-duration')) $('manual-appt-duration').value = '120';
  if ($('manual-appt-whatsapp')) $('manual-appt-whatsapp').checked = true;
  const errEl = $('manual-appt-error');
  if (errEl) { errEl.textContent = ''; errEl.style.display = 'none'; }
  overlay.style.display = 'flex';
  document.documentElement.classList.add('manual-appt-modal-open');
  document.body.classList.add('manual-appt-modal-open');
  initManualApptDatePicker();
  if (manualApptDatePicker) {
    manualApptDatePicker.setDate(localIsoDate(), false);
  } else if ($('manual-appt-date')) {
    $('manual-appt-date').value = localIsoDate();
  }
  populateManualApptStaffSelect().then(() => loadManualAppointmentTimeSlots());
  setTimeout(() => $('manual-appt-phone')?.focus(), 80);
}

function closeManualAppointmentModal() {
  const overlay = $('manual-appointment-overlay');
  if (overlay) overlay.style.display = 'none';
  document.documentElement.classList.remove('manual-appt-modal-open');
  document.body.classList.remove('manual-appt-modal-open');
}

async function submitManualAppointment(e) {
  e.preventDefault();
  const errEl = $('manual-appt-error');
  const phone = normalizePhone10($('manual-appt-phone')?.value);
  const name = formatPersonName($('manual-appt-name')?.value || '');
  const surname = formatPersonName($('manual-appt-surname')?.value || '');
  const dateIso = manualApptDatePicker?.selectedDates?.[0]
    ? manualApptDatePicker.formatDate(manualApptDatePicker.selectedDates[0], 'Y-m-d')
    : ($('manual-appt-date')?.value || '');
  const time = $('manual-appt-time')?.value;
  const duration = parseInt($('manual-appt-duration')?.value || '0', 10);
  const price = parseFloat($('manual-appt-price')?.value || '0') || 0;
  const sendWhatsapp = $('manual-appt-whatsapp')?.checked !== false;
  const staffId = getManualApptStaffId();

  if (!phone || phone.length !== 10) {
    if (errEl) { errEl.textContent = 'Geçerli 10 haneli telefon girin'; errEl.style.display = 'block'; }
    return;
  }
  if (!name || !surname) {
    if (errEl) { errEl.textContent = 'Ad ve soyad zorunludur'; errEl.style.display = 'block'; }
    return;
  }
  if (!dateIso || !time) {
    if (errEl) { errEl.textContent = 'Tarih ve saat seçin'; errEl.style.display = 'block'; }
    return;
  }
  if (!duration || duration < 60 || duration % 60 !== 0) {
    if (errEl) { errEl.textContent = 'Süre 60\'ın katı olmalı'; errEl.style.display = 'block'; }
    return;
  }

  const btn = $('submit-manual-appointment-btn');
  if (btn) btn.disabled = true;
  if (errEl) errEl.style.display = 'none';

  // Gönderimden hemen önce takvimi yeniden kontrol et
  await loadManualAppointmentTimeSlots();
  const timeSel = $('manual-appt-time');
  const stillValid = timeSel && Array.from(timeSel.options).some(
    (o) => o.value === time && !o.disabled
  );
  if (!stillValid) {
    if (btn) btn.disabled = false;
    if (errEl) {
      errEl.textContent = 'Seçilen saat artık uygun değil. Lütfen listeden yeni saat seçin.';
      errEl.style.display = 'block';
    }
    return;
  }

  const body = {
    phone,
    name,
    surname,
    date: isoDateToTr(dateIso),
    time,
    duration_minutes: duration,
    price,
    send_whatsapp: sendWhatsapp,
  };
  if (staffId) body.staff_id = staffId;

  const { ok, data } = await apiCall('/admin/appointments/manual', {
    method: 'POST',
    body: JSON.stringify(body),
  });

  if (btn) btn.disabled = false;

  if (!ok || !data.success) {
    if (errEl) {
      errEl.textContent = data?.message || 'Randevu oluşturulamadı';
      errEl.style.display = 'block';
    }
    return;
  }

  showToast(data.message || 'Randevu oluşturuldu', 'success');
  closeManualAppointmentModal();
  await reloadActiveAdminAppointments();
}

function bindAppointmentStatusControls(container, afterSuccess) {
  container.querySelectorAll('.apt-status-btn[data-status-id]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (btn.disabled || btn.classList.contains('is-current')) return;
      const id = btn.getAttribute('data-status-id');
      const status = btn.getAttribute('data-status-val');
      btn.disabled = true;
      const ok = await updateAppointmentStatus(id, status);
      btn.disabled = false;
      if (!ok) return;
      if (typeof afterSuccess === 'function') await afterSuccess();
      else await reloadActiveAdminAppointments();
    });
  });
}

function renderDisabled(sectionId, title, message) {
  const sec = $(sectionId);
  if (!sec) return;
  const container = sec.querySelector('.services-list, .appointments-list, .working-hours-container, .time-off-container, .all-appointments-container') || sec;
  container.innerHTML = `
    <div style="padding:16px; border:1px dashed rgba(0,0,0,.2); border-radius:12px;">
      <div style="font-weight:400; margin-bottom:8px;">${escapeHtml(title)}</div>
      <div style="color: var(--text-secondary); line-height:1.5;">${escapeHtml(message)}</div>
    </div>
  `;
}

function wapioCompatStatusIcon(status) {
  if (status === 'ok') return '✅';
  if (status === 'warn') return '⚠️';
  return '❌';
}

function renderWapioCompatReport(report) {
  const el = $('wapio-compat-results');
  if (!el || !report) return;
  const checks = report.checks || [];
  const rows = checks.map((c) => {
    const details = c.details || {};
    const detailLines = [];
    if (details.http_status != null) detailLines.push(`HTTP ${details.http_status}`);
    if (details.session_state) detailLines.push(`Oturum: ${details.session_state}`);
    if (details.endpoint_exists === false) detailLines.push('Endpoint bulunamadı (404) — API değişmiş olabilir');
    if (details.missing?.length) detailLines.push(`Eksik: ${details.missing.join(', ')}`);
    if (details.note) detailLines.push(details.note);
    if (details.error) detailLines.push(String(details.error));
    return `<div class="wapio-compat-row wapio-compat-row--${escapeHtml(c.status || 'fail')}">
      <div class="wapio-compat-row-head">${wapioCompatStatusIcon(c.status)} <strong>${escapeHtml(c.label || c.id)}</strong></div>
      ${detailLines.length ? `<div class="wapio-compat-row-detail">${detailLines.map((d) => escapeHtml(d)).join(' · ')}</div>` : ''}
    </div>`;
  }).join('');
  el.innerHTML = `
    <div class="wapio-compat-summary wapio-compat-summary--${report.compatible ? 'ok' : 'fail'}">
      ${report.compatible ? '✅ Kritik endpoint\'ler uyumlu görünüyor' : '❌ Uyumsuzluk tespit edildi — Wapio dokümanını kontrol edin'}
    </div>
    <div class="wapio-compat-meta">Kontrol: ${escapeHtml(report.checked_at || '—')} · Sözleşme: ${escapeHtml(report.contract_version || '—')}</div>
    ${report.webhook_url ? `<div class="wapio-compat-meta">Webhook: <code>${escapeHtml(report.webhook_url)}</code></div>` : ''}
    ${rows}
    ${report.action_required ? `<p class="wapio-compat-action">${escapeHtml(report.action_required)}</p>` : ''}
  `;
  el.hidden = false;
}

let whatsAppProvider = 'evolution'; // Wapio devre dışı — yalnızca Evolution

function whatsAppAdminPaths() {
  // if (whatsAppProvider === 'wapio') { ... Wapio uçları devre dışı }
  return {
    settings: '/admin/evolution-settings',
    status: '/admin/evolution/session-status',
    create: '/admin/evolution/create-instance',
    qr: '/admin/evolution/connect',
    webhook: '/admin/evolution/update-webhook',
  };
}

async function applyWhatsAppProviderUi() {
  const hint = $('whatsapp-provider-hint');
  const advanced = $('wapio-advanced-panel');
  const urlGroup = $('whatsapp-api-url-group');
  whatsAppProvider = 'evolution';
  try {
    const res = await apiCall('/admin/whatsapp/provider');
    if (res.data?.provider === 'evolution') {
      whatsAppProvider = 'evolution';
    }
  } catch (_) {
    /* backend yanıt vermezse Evolution varsayılan */
  }

  if (hint) hint.textContent = 'Sağlayıcı: Evolution API (self-hosted)';
  if (advanced) advanced.hidden = true;
  if (urlGroup) urlGroup.style.display = '';

  const labelKey = $('label-wapio-api-key');
  const labelSession = $('label-wapio-session-id');
  const labelDevice = $('label-wapio-device-name');
  const createBtn = $('wapio-create-device-btn');
  if (labelKey) labelKey.textContent = 'Evolution API Key (apikey header)';
  if (labelSession) labelSession.textContent = 'Instance name';
  if (labelDevice) labelDevice.textContent = 'Yeni instance adı';
  if (createBtn) createBtn.innerHTML = '<i class="fas fa-plus"></i> Instance Oluştur';
}

async function loadWapioSettingsPage() {
  const versionEl = $('wapio-contract-version');
  const resultsEl = $('wapio-compat-results');
  if (resultsEl) resultsEl.hidden = true;

  await applyWhatsAppProviderUi();

  if (versionEl) versionEl.textContent = 'Evolution API v2';
  // Wapio sözleşme/compat devre dışı

  const paths = whatsAppAdminPaths();
  const settingsRes = await apiCall(paths.settings);
  if (settingsRes.ok && settingsRes.data?.settings) {
    const s = settingsRes.data.settings;
    if ($('wapio-api-key')) $('wapio-api-key').value = s.api_key || s.api_token || '';
    if ($('wapio-session-id')) {
      $('wapio-session-id').value = s.session_id || s.instance_id || s.instance_name || '';
    }
    if ($('wapio-device-name')) {
      $('wapio-device-name').value = s.device_name || s.instance_name || 'roof-tattoo';
    }
    if ($('whatsapp-api-url') && s.api_url) $('whatsapp-api-url').value = s.api_url;
    if ($('wapio-welcome-enabled')) {
      $('wapio-welcome-enabled').checked = s.welcome_message_enabled !== false;
    }
    if ($('wapio-otp-keyboard-enabled')) {
      $('wapio-otp-keyboard-enabled').checked = s.otp_keyboard_hint_enabled !== false;
    }
  }

  await refreshWapioConnectionStatus({ silent: true });

  const sessionId = ($('wapio-session-id')?.value || '').trim();
  if (sessionId) startWapioStatusPolling({ intervalMs: 5000 });
}

let wapioStatusPollTimer = null;
let whatsAppStatusStickyUntil = 0;

function renderWapioConnectionStatus(connection) {
  const badge = $('wapio-connection-status');
  if (!badge) return;

  const labelEl = badge.querySelector('.wapio-connection-status-label');
  let state = connection?.state || 'unknown';
  let label = connection?.label || 'Başarısız';
  let detail = connection?.detail || '';

  if (connection?.connected) {
    whatsAppStatusStickyUntil = Date.now() + 45000;
  } else if (
    state === 'pending' &&
    whatsAppStatusStickyUntil > Date.now() &&
    (connection?.raw_state === 'connecting' || (detail && detail.includes('yenileniyor')))
  ) {
    state = 'connected';
    label = 'Başarılı';
    detail = 'WhatsApp bağlı (kısa süreli yenileme)';
  }

  badge.className = `wapio-connection-status wapio-connection-status--${state}`;
  if (labelEl) {
    labelEl.textContent = state === 'connected' ? label : (detail ? `${label} — ${detail}` : label);
  }
}

function stopWapioStatusPolling() {
  if (wapioStatusPollTimer) {
    clearInterval(wapioStatusPollTimer);
    wapioStatusPollTimer = null;
  }
}

function startWapioStatusPolling({ intervalMs = 5000, stopWhenConnected = false } = {}) {
  stopWapioStatusPolling();
  wapioStatusPollTimer = setInterval(async () => {
    const connected = await refreshWapioConnectionStatus({ silent: true, fromPoll: true });
    if (stopWhenConnected && connected) {
      stopWapioStatusPolling();
      startWapioStatusPolling({ intervalMs: 5000, stopWhenConnected: false });
    }
  }, intervalMs);
}

async function refreshWapioConnectionStatus({ silent = false, fromPoll = false } = {}) {
  const badge = $('wapio-connection-status');
  if (badge && !fromPoll) {
    badge.className = 'wapio-connection-status wapio-connection-status--checking';
    const labelEl = badge.querySelector('.wapio-connection-status-label');
    if (labelEl) labelEl.textContent = 'Kontrol ediliyor…';
  }

  const res = await apiCall(whatsAppAdminPaths().status);
  if (res.ok && res.data?.connection) {
    renderWapioConnectionStatus(res.data.connection);
    if (!silent) {
      const ok = res.data.connection.connected;
      showToast(
        ok ? 'WhatsApp bağlantısı aktif' : (res.data.connection.detail || 'Bağlantı yok'),
        ok ? 'success' : 'error',
      );
    }
    return !!res.data.connection.connected;
  }

  renderWapioConnectionStatus({
    state: 'error',
    label: 'Başarısız',
    detail: res.data?.message || 'Durum alınamadı',
  });
  if (!silent) showToast('Bağlantı durumu alınamadı', 'error');
  return false;
}

async function saveWapioSettings({ silent = false, reload = true } = {}) {
  const apiKey = ($('wapio-api-key')?.value || '').trim();
  const sessionId = ($('wapio-session-id')?.value || '').trim();
  const deviceName = ($('wapio-device-name')?.value || 'roof-tattoo').trim();
  const welcomeEnabled = !!$('wapio-welcome-enabled')?.checked;
  const otpKeyboardEnabled = !!$('wapio-otp-keyboard-enabled')?.checked;
  const apiUrl = ($('whatsapp-api-url')?.value || '').trim();
  if (!apiKey) {
    if (!silent) showToast('API Key zorunludur', 'error');
    return false;
  }
  const body =
    whatsAppProvider === 'wapio'
      ? {
          api_key: apiKey,
          session_id: sessionId,
          device_name: deviceName,
          welcome_message_enabled: welcomeEnabled,
        }
      : {
          api_key: apiKey,
          instance_name: sessionId || deviceName,
          api_url: apiUrl || undefined,
          welcome_message_enabled: welcomeEnabled,
          otp_keyboard_hint_enabled: otpKeyboardEnabled,
        };
  const res = await apiCall(whatsAppAdminPaths().settings, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  if (res.ok) {
    if (!silent) showToast(res.data?.message || 'Kaydedildi', 'success');
    if (reload) await loadWapioSettingsPage();
    return true;
  }
  if (!silent) showToast(res.data?.message || 'Kaydedilemedi', 'error');
  return false;
}

function showWapioQrImage(qrImage) {
  const wrap = $('wapio-qr-wrap');
  const img = $('wapio-qr-image');
  if (!wrap || !img || !qrImage) return;
  const src = qrImage.startsWith('data:') ? qrImage : `data:image/png;base64,${qrImage}`;
  img.src = src;
  wrap.hidden = false;
}

async function wapioCreateDevice() {
  const deviceName = ($('wapio-device-name')?.value || 'roof-tattoo').trim();
  const payload =
    whatsAppProvider === 'wapio'
      ? { device_name: deviceName }
      : { instance_name: deviceName, device_name: deviceName };
  const res = await apiCall(whatsAppAdminPaths().create, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const instanceId = res.data?.session_id || res.data?.instance_name;
  if (res.ok && instanceId && $('wapio-session-id')) {
    $('wapio-session-id').value = instanceId;
    if (res.data?.qr_image) showWapioQrImage(res.data.qr_image);
    showToast(
      whatsAppProvider === 'wapio'
        ? `Cihaz oluşturuldu — Session: ${instanceId}`
        : `Instance oluşturuldu: ${instanceId}`,
      'success',
    );
    await saveWapioSettings();
  } else {
    showToast(res.data?.message || 'Oluşturulamadı', 'error');
  }
}

async function wapioGetQr() {
  const sessionId = ($('wapio-session-id')?.value || '').trim();
  const deviceName = ($('wapio-device-name')?.value || 'roof-tattoo').trim();
  if (!sessionId) {
    showToast('Önce instance oluşturun veya adını girin', 'error');
    return;
  }
  const payload =
    whatsAppProvider === 'wapio'
      ? { session_id: sessionId, device_name: deviceName }
      : { instance_name: sessionId, session_id: sessionId };
  const res = await apiCall(whatsAppAdminPaths().qr, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (res.ok && res.data?.qr_image) {
    showWapioQrImage(res.data.qr_image);
    showToast('QR kod hazır — WhatsApp ile okutun', 'success');
    renderWapioConnectionStatus({
      state: 'pending',
      label: 'Beklemede',
      detail: 'QR kod okutulması bekleniyor',
    });
    startWapioStatusPolling({ intervalMs: 3000, stopWhenConnected: true });
  } else {
    showToast('QR kod alınamadı', 'error');
  }
}

async function wapioCheckSessionStatus() {
  await refreshWapioConnectionStatus();
}

async function wapioSaveWebhook() {
  const sessionId = ($('wapio-session-id')?.value || '').trim();
  const deviceName = ($('wapio-device-name')?.value || 'roof-tattoo').trim();
  const payload =
    whatsAppProvider === 'wapio'
      ? { session_id: sessionId, device_name: deviceName }
      : { instance_name: sessionId, session_id: sessionId };
  const res = await apiCall(whatsAppAdminPaths().webhook, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    showToast(`Webhook kaydedildi: ${res.data?.webhook || ''}`, 'success');
  } else {
    showToast('Webhook kaydedilemedi', 'error');
  }
}

async function runWapioCompatCheck() {
  if (whatsAppProvider !== 'wapio') {
    showToast('Evolution modunda Wapio uyumluluk testi kullanılmaz', 'info');
    return;
  }
  const btn = $('wapio-compat-check-btn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Kontrol ediliyor…';
  }
  try {
    const res = await apiCall('/admin/wapio-compat-check');
    if (res.ok && res.data?.report) {
      renderWapioCompatReport(res.data.report);
      showToast(res.data.report.compatible ? 'API uyumlu' : 'Uyumsuzluk var — detaylara bakın', res.data.report.compatible ? 'success' : 'error');
    } else {
      showToast(res.data?.message || 'Kontrol başarısız', 'error');
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-sync-alt"></i> Uyumluluk Kontrolü Çalıştır';
    }
  }
}

async function enterAdminDashboard(staff) {
  $('user-name').textContent = staff.name || '-';
  $('user-role').textContent = roleLabel(staff.role);
  setRoleVisibility(staff.role);
  sessionStorage.setItem(ADMIN_SESSION_ACTIVE_KEY, '1');
  setPage(true);
  startInactivityWatcher();
  await loadDashboard();
}

async function validateStoredAdminSession() {
  const token = getAdminToken();
  if (!token) return { ok: false, status: 401, staff: null };

  const res = await fetch(`${API_BASE}/admin/me`, {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  if (res.status === 401) {
    return { ok: false, status: 401, staff: null };
  }
  return { ok: res.ok, status: res.status, staff: getAdminStaff() };
}

async function quickLogin() {
  if ($('login-error')) $('login-error').textContent = '';
  const btn = $('login-quick-btn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Giriş yapılıyor...';
  }

  const { ok, status, staff } = await validateStoredAdminSession();

  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-sign-in-alt"></i> Giriş Yap';
  }

  if (!ok || status === 401 || !staff) {
    clearAdminSession({ keepRememberPrefs: true });
    if ($('login-error')) {
      $('login-error').textContent = 'Oturum süresi doldu. Lütfen telefon ve şifrenizle tekrar giriş yapın.';
    }
    updateLoginModeUI();
    initRememberMeForm();
    return;
  }

  await enterAdminDashboard(staff);
}

function switchLoginAccount() {
  if ($('login-error')) $('login-error').textContent = '';
  clearAdminSession();
  if ($('login-remember-me')) $('login-remember-me').checked = false;
  updateLoginModeUI();
}

async function login(phone, password, rememberMe = false) {
  const { ok, data } = await apiCall('/admin/login', {
    method: 'POST',
    body: JSON.stringify({ phone, password, remember_me: rememberMe }),
  });

  if (!ok || !data.success) {
    if ($('login-error')) $('login-error').textContent = data.message || 'Giriş başarısız';
    return;
  }

  setAdminSession(data.token, data.staff, rememberMe);
  if (rememberMe) {
    localStorage.setItem(ADMIN_REMEMBER_PHONE_KEY, phone);
  }

  await enterAdminDashboard(data.staff);
}

async function handleAdminLoginSubmit(e) {
  if (e) e.preventDefault();
  if ($('login-error')) $('login-error').textContent = '';
  const phone = ($('login-phone')?.value || '').trim();
  const password = ($('login-password')?.value || '').trim();
  const rememberMe = !!$('login-remember-me')?.checked;
  await login(phone, password, rememberMe);
}

function logout({ soft = false } = {}) {
  stopInactivityWatcher();
  const remember = isAdminRememberMe();
  if (soft && remember) {
    clearAdminSession({ keepRememberPrefs: true, softLogout: true });
  } else {
    clearAdminSession();
  }
  setPage(false);
  updateLoginModeUI();
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

function formatPhonePretty(phone10) {
  const p = String(phone10 || '').replace(/\D/g, '').slice(-10);
  if (p.length !== 10) return p;
  return `${p.slice(0, 3)} ${p.slice(3, 6)} ${p.slice(6, 8)} ${p.slice(8, 10)}`;
}

function formatPersonName(name) {
  return String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLocaleLowerCase('tr-TR');
      return lower.charAt(0).toLocaleUpperCase('tr-TR') + lower.slice(1);
    })
    .join(' ');
}

/** wa.me için uluslararası format (örn. 905551234567) */
function phoneToWhatsAppIntl(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  if (!digits) return null;
  if (digits.startsWith('90') && digits.length === 12) return digits;
  if (digits.startsWith('0') && digits.length === 11) return `90${digits.slice(1)}`;
  if (digits.length === 10) return `90${digits}`;
  if (digits.length >= 11) return digits;
  return null;
}

function buildWhatsAppChatUrl(phone) {
  const intl = phoneToWhatsAppIntl(phone);
  return intl ? `https://wa.me/${intl}` : null;
}

function renderWhatsAppBtnHtml(phone) {
  const waUrl = buildWhatsAppChatUrl(phone);
  if (waUrl) {
    return `<a class="action-btn whatsapp-btn" href="${escapeHtml(waUrl)}" target="_blank" rel="noopener noreferrer" title="WhatsApp'ta müşteriyle yazış">
      <i class="fab fa-whatsapp"></i> WhatsApp'ta Aç
    </a>`;
  }
  return `<button type="button" class="action-btn whatsapp-btn" disabled title="Telefon numarası yok">
    <i class="fab fa-whatsapp"></i> WhatsApp'ta Aç
  </button>`;
}

function renderTattooRequests(items, containerId = 'tattoo-requests-list', isOffered = false, emptyMessage = '') {
  const container = $(containerId);
  if (!container) return;
  if (!items || items.length === 0) {
    const fallback = isOffered
      ? 'Henüz gönderilmiş teklif yok'
      : 'Bekleyen talep yok';
    container.innerHTML = `<p class="empty-message">${emptyMessage || fallback}</p>`;
    return;
  }

  container.innerHTML = items
    .map((tr) => {
      const createdAt = tr.created_at || '-';
      const customerName = formatPersonName((tr.customer?.full_name || '').trim() || 'Müşteri');
      const phoneDigits = String(tr.customer?.phone || '').replace(/\D/g, '').slice(-10);
      const customerPhone = phoneDigits ? `0${formatPhonePretty(phoneDigits)}` : 'Telefon yok';
      const phoneHtml = phoneDigits
        ? `<a class="tr-customer-phone" href="tel:0${phoneDigits}"><i class="fas fa-phone"></i> ${escapeHtml(customerPhone)}</a>`
        : `<span class="tr-customer-phone is-missing"><i class="fas fa-phone"></i> Telefon yok</span>`;

      const statusRaw = String(tr.status || 'new');
      const statusLabel = statusRaw === 'new' ? 'Yeni' : statusRaw;

      const refNo = tr.reference_number ? escapeHtml(tr.reference_number) : '';
      const refBadge = refNo
        ? `<span class="tr-ref-code" title="Talep referansı — müşteriye iletin">${refNo}</span>`
        : '';

      const waBtn = renderWhatsAppBtnHtml(tr.customer?.phone);

      const specRows = [
        ['Sanatçı', tr.staff?.name || '—'],
        ['Bölge', tr.body_area || 'Belirtilmedi'],
        ['Boyut', tr.size || 'Belirtilmedi'],
      ];
      if (tr.tattoo_style) specRows.push(['Stil', tr.tattoo_style]);
      if (tr.loyalty_discount) {
        specRows.push([
          'Sadakat',
          `${tr.loyalty_discount.code} · %${tr.loyalty_discount.discount_percent}${tr.loyalty_discount.used ? ' (kullanıldı)' : ''}`,
        ]);
      }
      const specsHtml = specRows
        .map(([label, value]) => `
          <div class="tr-spec">
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value)}</dd>
          </div>
        `)
        .join('');

      return `
        <div class="appointment-card tattoo-request-card status-pending" data-ref="${refNo}">
          <div class="tr-main">
            <div class="tr-topbar">
              <div class="tr-topbar-left">
                ${refBadge}
                <span class="tr-created"><i class="fas fa-calendar-alt"></i> ${escapeHtml(createdAt)}</span>
              </div>
              <span class="status-badge pending">${escapeHtml(statusLabel)}</span>
            </div>

            <div class="tr-identity">
              <div class="tr-customer-name">${escapeHtml(customerName)}</div>
              ${phoneHtml}
            </div>

            <dl class="tr-specs">${specsHtml}</dl>
          </div>

          <div class="appointment-actions tattoo-request-actions">
            ${isOffered
              ? `<button class="action-btn" data-resend="${tr.id}">
                   <i class="fas fa-rotate-right"></i> Yeni Link Gönder
                 </button>`
              : `<button class="action-btn review-btn" data-offer="${tr.id}">
                   <i class="fas fa-paper-plane"></i> Süre Belirle & Link Gönder
                 </button>`
            }
            ${waBtn}
          </div>
        </div>
      `;
    })
    .join('');

  // Yeni teklif gönder (Dövme Talepleri)
  container.querySelectorAll('button[data-offer]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-offer');
      const tr = items.find((item) => String(item.id) === String(id));
      const result = await openOfferFormModal(
        'Müşteriye gönderilecek teklif bilgilerini girin.',
        null,
        tr?.loyalty_discount || null
      );
      if (!result) return;
      btn.disabled = true;
      try {
        const { ok, data } = await apiCall(`/admin/tattoo-requests/${id}/offer`, {
          method: 'POST',
          body: JSON.stringify({ duration_minutes: result.duration_minutes, price: result.price }),
        });
        if (!ok || !data.success) {
          showToast(data.message || 'Link gönderilemedi', 'error');
          return;
        }
        showOfferUrlModal(data.offer_url, data.whatsapp_sent);
        if (data.whatsapp_sent) {
          showToast(data.message || 'Teklif gönderildi', 'success');
        } else {
          showToast(data.message || 'Teklif oluşturuldu — WhatsApp mesajı gitmedi, linki manuel gönderin', 'error');
        }
        await reloadNewTattooRequestPages();
        await loadOfferedRequests();
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Yeniden link gönder (Gönderilen Teklifler)
  container.querySelectorAll('button[data-resend]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-resend');
      const tr = items.find((item) => String(item.id) === String(id));
      const result = await openOfferFormModal(
        'Mevcut teklif iptal edilir, yeni link oluşturulur.',
        null,
        tr?.loyalty_discount || null
      );
      if (!result) return;
      btn.disabled = true;
      try {
        const { ok, data } = await apiCall(`/admin/tattoo-requests/${id}/offer`, {
          method: 'POST',
          body: JSON.stringify({ duration_minutes: result.duration_minutes, price: result.price }),
        });
        if (!ok || !data.success) {
          showToast(data.message || 'Link gönderilemedi', 'error');
          return;
        }
        showOfferUrlModal(data.offer_url, data.whatsapp_sent);
        if (data.whatsapp_sent) {
          showToast(data.message || 'Teklif gönderildi', 'success');
        } else {
          showToast(
            data.message || 'Teklif oluşturuldu — WhatsApp mesajı müşteriye ulaşmadı, linki manuel gönderin',
            'error'
          );
        }
        await loadOfferedRequests();
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function getTattooRefSearchParam(inputId) {
  const el = $(inputId);
  const q = (el?.value || '').trim().toUpperCase();
  return q ? `&reference=${encodeURIComponent(q)}` : '';
}

function getMyTattooRequestsQuery(refInputId, kind = 'standard') {
  const refQ = getTattooRefSearchParam(refInputId);
  const scopeQ = getLoggedInStaff()?.role === 'super_admin' ? '&scope=mine' : '';
  const kindQ = kind ? `&kind=${encodeURIComponent(kind)}` : '';
  return `?status=new${scopeQ}${refQ}${kindQ}`;
}

function updateNewRequestsBadge(badgeId, count) {
  const badge = $(badgeId);
  if (!badge) return;
  badge.textContent = String(count);
  badge.style.display = count > 0 ? 'inline-flex' : 'none';
}

async function refreshNewTattooRequestBadges() {
  if (!canAccessTattooRequests()) return;
  const staff = getLoggedInStaff();
  const mineQs = staff?.role === 'super_admin' ? '?status=new&scope=mine' : '?status=new';
  const requests = [
    apiCall(`/admin/tattoo-requests${mineQs}&kind=standard`, { method: 'GET' }),
    apiCall(`/admin/tattoo-requests${mineQs}&kind=undecided`, { method: 'GET' }),
    apiCall(`/admin/tattoo-requests${mineQs}&kind=pre_consultation`, { method: 'GET' }),
  ];
  if (staff?.role === 'super_admin') {
    requests.push(apiCall('/admin/tattoo-requests?status=new&kind=standard', { method: 'GET' }));
  }
  const [mineRes, undecidedRes, preconsultRes, allRes] = await Promise.all(requests);
  if (mineRes.ok && mineRes.data.success) {
    updateNewRequestsBadge('my-new-requests-badge', (mineRes.data.tattoo_requests || []).length);
  }
  if (undecidedRes.ok && undecidedRes.data.success) {
    updateNewRequestsBadge('undecided-requests-badge', (undecidedRes.data.tattoo_requests || []).length);
  }
  if (preconsultRes.ok && preconsultRes.data.success) {
    updateNewRequestsBadge('preconsult-requests-badge', (preconsultRes.data.tattoo_requests || []).length);
  }
  if (allRes?.ok && allRes.data.success) {
    updateNewRequestsBadge('all-new-requests-badge', (allRes.data.tattoo_requests || []).length);
  }
}

async function loadMyTattooRequests() {
  if (!canAccessTattooRequests()) return;
  const container = $('my-tattoo-requests-list');
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  const qs = getMyTattooRequestsQuery('tattoo-ref-search');
  const { ok, data } = await apiCall(`/admin/tattoo-requests${qs}`, { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  const items = data.tattoo_requests || [];
  updateNewRequestsBadge('my-new-requests-badge', items.length);
  renderTattooRequests(items, 'my-tattoo-requests-list', false);
}

async function loadKindTattooRequests(kind, containerId, refInputId, badgeId, emptyMessage) {
  if (!canAccessTattooRequests()) return;
  const container = $(containerId);
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  const qs = getMyTattooRequestsQuery(refInputId, kind);
  const { ok, data } = await apiCall(`/admin/tattoo-requests${qs}`, { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  const items = data.tattoo_requests || [];
  updateNewRequestsBadge(badgeId, items.length);
  renderTattooRequests(items, containerId, false, emptyMessage);
}

async function loadUndecidedRequests() {
  await loadKindTattooRequests(
    'undecided',
    'undecided-requests-list',
    'undecided-ref-search',
    'undecided-requests-badge',
    'Kararını henüz vermemiş talep yok'
  );
}

async function loadPreconsultRequests() {
  await loadKindTattooRequests(
    'pre_consultation',
    'preconsult-requests-list',
    'preconsult-ref-search',
    'preconsult-requests-badge',
    'Bekleyen ön görüşme talebi yok'
  );
}

async function loadAllTattooRequests() {
  if (getLoggedInStaff()?.role !== 'super_admin') return;
  const container = $('all-tattoo-requests-list');
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  const refQ = getTattooRefSearchParam('all-tattoo-ref-search');
  const { ok, data } = await apiCall(`/admin/tattoo-requests?status=new&kind=standard${refQ}`, { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  const items = data.tattoo_requests || [];
  updateNewRequestsBadge('all-new-requests-badge', items.length);
  renderTattooRequests(items, 'all-tattoo-requests-list', false);
}

async function reloadNewTattooRequestPages() {
  if (!canAccessTattooRequests()) return;
  await Promise.all([
    loadMyTattooRequests(),
    loadUndecidedRequests(),
    loadPreconsultRequests(),
  ]);
  if (getLoggedInStaff()?.role === 'super_admin') {
    await loadAllTattooRequests();
  }
}

async function loadOfferedRequests() {
  if (!canAccessTattooRequests()) return;
  const container = $('offered-requests-list');
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  const refQ = getTattooRefSearchParam('offered-ref-search');
  const { ok, data } = await apiCall(`/admin/tattoo-requests?status=offered${refQ}`, { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  const items = data.tattoo_requests || [];
  // pending-badge (Gönderilen Teklifler sayacı) güncelle
  const badge = $('pending-badge');
  if (badge) badge.textContent = String(items.length);
  renderTattooRequests(items, 'offered-requests-list', true);
}

function renderAppointmentsGrouped(containerId, items) {
  const container = $(containerId);
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-message">Kayıt yok</p>';
    return;
  }

  // Tarihe göre grupla
  const groups = {};
  items.forEach((a) => {
    if (!groups[a.date]) groups[a.date] = [];
    groups[a.date].push(a);
  });

  // Tarihleri sırala (en yakın önce)
  const sortedDates = Object.keys(groups).sort((x, y) => {
    const parse = (s) => { const [d,m,yr] = s.split('.'); return new Date(yr, m-1, d); };
    return parse(x) - parse(y);
  });

  let html = '';
  sortedDates.forEach((date) => {
    const dayItems = groups[date];
    const { label, dayName, dayNum, monthName, year } = formatDateParts(date);
    const isToday = (() => {
      const [d,m,y] = date.split('.').map(Number);
      const t = new Date(); return t.getFullYear()===y && t.getMonth()+1===m && t.getDate()===d;
    })();
    html += `<div class="apt-date-group">
      <div class="apt-date-card${isToday ? ' apt-date-card--today' : ''}">
        <div class="apt-date-card-left">
          <span class="apt-date-num">${dayNum}</span>
          <span class="apt-date-month">${monthName} ${year}</span>
        </div>
        <div class="apt-date-card-right">
          <span class="apt-date-dayname">${dayName}</span>
          <span class="apt-date-count">${dayItems.length} randevu</span>
        </div>
      </div>
      <div class="apt-date-cards">`;
    dayItems.forEach((a) => {
      const customer = a.customer?.full_name ? a.customer.full_name : `0${a.customer?.phone || '-'}`;
      const artist   = a.staff?.name || '-';
      const tr       = a.tattoo_request || {};
      const price    = parseFloat(a.price || 0);
      const priceRow = price > 0
        ? `<div class="apt-detail-row">
             <span class="apt-detail-icon"><i class="fas fa-tag"></i></span>
             <span class="apt-detail-label">Fiyat:</span>
             <span class="apt-detail-value" style="color:var(--accent);font-weight:400;">${price.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺</span>
           </div>`
        : '';
      html += `
        <div class="appointment-card status-${escapeHtml(a.status)}" data-apt-id="${a.id}">
          <div class="apt-card-top">
            <div class="apt-datetime">
              <div class="appointment-time"><i class="fas fa-clock"></i> ${escapeHtml(a.time)}</div>
            </div>
            <div class="apt-card-badges">
              ${appointmentSourceBadgeHtml(a.source)}
              <span class="status-badge ${escapeHtml(a.status)}">${escapeHtml(statusText(a.status))}</span>
            </div>
          </div>
          <div class="apt-card-body">
            <div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-user"></i></span>
              <span class="apt-detail-label">Müşteri:</span>
              <span class="apt-detail-value">${escapeHtml(customer)}</span>
            </div>
            <div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-paint-brush"></i></span>
              <span class="apt-detail-label">Sanatçı:</span>
              <span class="apt-detail-value">${escapeHtml(artist)}</span>
            </div>
            <div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-clock"></i></span>
              <span class="apt-detail-label">Süre:</span>
              <span class="apt-detail-value">${a.duration_minutes || 30} dk</span>
            </div>
            ${tr.body_area ? `<div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-map-marker-alt"></i></span>
              <span class="apt-detail-label">Bölge:</span>
              <span class="apt-detail-value">${escapeHtml(tr.body_area)}</span>
            </div>` : ''}
            ${priceRow}
          </div>
          <div class="apt-card-footer">
            ${renderAppointmentStatusControls(a.id, a.status, a)}
            ${renderWhatsAppBtnHtml(a.customer?.phone)}
          </div>
        </div>`;
    });
    html += `</div></div>`;
  });

  container.innerHTML = html;
  bindAppointmentStatusControls(container, loadAllAppointments);
}

function formatDateParts(dateStr) {
  const [d, m, y] = dateStr.split('.').map(Number);
  const months = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
  const days   = ['Pazar','Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi'];
  const dateObj = new Date(y, m - 1, d);
  return {
    label:     `${d} ${months[m-1]} ${y}`,
    dayNum:    String(d).padStart(2, '0'),
    monthName: months[m - 1],
    year:      y,
    dayName:   days[dateObj.getDay()],
  };
}

function renderAppointments(containerId, items) {
  const container = $(containerId);
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-message">Kayıt yok</p>';
    return;
  }

  container.innerHTML = items
    .map((a) => {
      const customer = a.customer?.full_name ? a.customer.full_name : `0${a.customer?.phone || '-'}`;
      const artist = a.staff?.name || '-';
      const tr = a.tattoo_request || {};
      const price = parseFloat(a.price || 0);
      const priceRow = price > 0
        ? `<div class="apt-detail-row">
             <span class="apt-detail-icon"><i class="fas fa-tag"></i></span>
             <span class="apt-detail-label">Fiyat:</span>
             <span class="apt-detail-value" style="color:var(--accent);font-weight:400;">${price.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺</span>
           </div>`
        : '';

      return `
        <div class="appointment-card status-${escapeHtml(a.status)}">
          <div class="apt-card-top">
            <div class="apt-datetime">
              <div class="appointment-date"><i class="fas fa-calendar-alt"></i> ${escapeHtml(a.date)}</div>
              <div class="appointment-time"><i class="fas fa-clock"></i> ${escapeHtml(a.time)}</div>
            </div>
            <div class="apt-card-badges">
              ${appointmentSourceBadgeHtml(a.source)}
              <span class="status-badge ${escapeHtml(a.status)}">${escapeHtml(statusText(a.status))}</span>
            </div>
          </div>
          <div class="apt-card-body">
            <div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-user"></i></span>
              <span class="apt-detail-label">Müşteri:</span>
              <span class="apt-detail-value">${escapeHtml(customer)}</span>
            </div>
            <div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-paint-brush"></i></span>
              <span class="apt-detail-label">Sanatçı:</span>
              <span class="apt-detail-value">${escapeHtml(artist)}</span>
            </div>
            <div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-clock"></i></span>
              <span class="apt-detail-label">Süre:</span>
              <span class="apt-detail-value">${a.duration_minutes || 30} dk</span>
            </div>
            ${tr.body_area ? `<div class="apt-detail-row">
              <span class="apt-detail-icon"><i class="fas fa-map-marker-alt"></i></span>
              <span class="apt-detail-label">Bölge:</span>
              <span class="apt-detail-value">${escapeHtml(tr.body_area)}</span>
            </div>` : ''}
            ${priceRow}
          </div>
          <div class="apt-card-footer">
            ${renderAppointmentStatusControls(a.id, a.status, a)}
            ${renderWhatsAppBtnHtml(a.customer?.phone)}
          </div>
        </div>
      `;
    })
    .join('');

  bindAppointmentStatusControls(container);
}

async function loadDashboard() {
  showSection('dashboard');
  const { ok, data } = await apiCall('/admin/dashboard', { method: 'GET' });
  if (!ok || !data.success) {
    showToast(data.message || 'Dashboard yüklenemedi', 'error');
    return;
  }
  const d = data.dashboard;
  $('dashboard-date').textContent = d.date || '-';
  $('stat-today-total').textContent = d.today.total ?? 0;
  $('stat-today-pending').textContent = d.today.pending ?? 0;
  $('stat-today-confirmed').textContent = d.today.confirmed ?? 0;
  $('stat-today-completed').textContent = d.today.completed ?? 0;

  // Today's appointments list (tamamlananlar Geçmiş Randevular'da)
  const today = formatTodayDdMmYyyy();
  const ap = await apiCall(
    `/admin/appointments?date=${encodeURIComponent(today)}&exclude_completed=true`,
    { method: 'GET' }
  );
  if (ap.ok && ap.data.success) {
    renderAppointments('today-appointments', ap.data.appointments || []);
  } else {
    $('today-appointments').innerHTML = '<p class="empty-message">Yüklenemedi</p>';
  }

  // Sidebar badge'lerini arka planda güncelle (dashboard'da görünür olsun)
  if (canAccessTattooRequests()) {
    refreshNewTattooRequestBadges();
    apiCall('/admin/tattoo-requests?status=offered', { method: 'GET' }).then(({ ok, data }) => {
      if (!ok || !data.success) return;
      const cnt = (data.tattoo_requests || []).length;
      const badge = $('pending-badge');
      if (badge) badge.textContent = String(cnt);
    });
  }
}

async function loadAppointments() {
  const container = $('all-appointments');
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';

  const status = $('filter-status')?.value || '';
  const start = $('appointments-start-date')?.value || '';
  const end = $('appointments-end-date')?.value || '';

  const qs = new URLSearchParams();
  if (status) {
    qs.set('status', status);
  } else {
    // Durum seçilmemişse tamamlananları hariç tut — onlar Geçmiş Randevular'da
    qs.set('exclude_completed', 'true');
  }
  if (start) qs.set('start_date', start);
  if (end) qs.set('end_date', end);

  const { ok, data } = await apiCall(`/admin/appointments?${qs.toString()}`, { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  _appointmentsData = data.appointments || [];
  renderAppointmentsGrouped('all-appointments', _appointmentsData);

  // Tabloyu liste ile senkronla: randevuların olduğu haftaya konumlan
  setWeekStart('all-appointments-table', pickRelevantWeekStart(_appointmentsData));

  // Tablo görünümü aktifse onu da güncelle
  const tableView = $('appointments-table-view');
  if (tableView && tableView.style.display !== 'none') {
    void renderAppointmentsTable(_appointmentsData, 'all-appointments-table');
  }
}

// =============================================
// TABLE VIEW
// =============================================
function timeToMinutes(t) {
  const [h, m] = t.split(':').map(Number);
  return h * 60 + m;
}
function minutesToTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
}

const DEFAULT_SCHEDULE_START_MINS = 9 * 60;   // 09:00
const DEFAULT_SCHEDULE_END_MINS = 24 * 60;    // 24:00 (son slot 23:30)
const _scheduleRangeCache = {};

function buildScheduleTimeSlots(startMins = DEFAULT_SCHEDULE_START_MINS, endMins = DEFAULT_SCHEDULE_END_MINS) {
  const times = [];
  for (let m = startMins; m < endMins; m += 30) {
    times.push(minutesToTime(m));
  }
  return times;
}

function workingHoursToRange(workingHours) {
  let minM = null;
  let maxM = null;
  (workingHours || []).forEach((wh) => {
    if (wh.is_available === false) return;
    const st = timeToMinutes((wh.start_time || '09:00').slice(0, 5));
    let en;
    const endRaw = (wh.end_time || '20:00').slice(0, 5);
    if (endRaw === '00:00' || endRaw === '24:00') {
      en = 24 * 60;
    } else {
      en = timeToMinutes(endRaw);
    }
    if (en <= st) en = 24 * 60;
    minM = minM === null ? st : Math.min(minM, st);
    maxM = maxM === null ? en : Math.max(maxM, en);
  });
  if (minM === null) {
    return { start: DEFAULT_SCHEDULE_START_MINS, end: DEFAULT_SCHEDULE_END_MINS };
  }
  return { start: minM, end: maxM };
}

function getTableStaffIdForHours(tableContainerId) {
  if (tableContainerId === 'all-appointments-table-container') {
    const v = $('all-appointments-staff-filter')?.value;
    return v ? parseInt(v, 10) : null;
  }
  try {
    const staff = getAdminStaff();
    return staff?.id != null ? parseInt(staff.id, 10) : null;
  } catch {
    return null;
  }
}

function jsDateToDbDayOfWeek(dateObj) {
  // Backend: 0=Pazar, 1=Pazartesi, ... 6=Cumartesi (JS getDay() ile aynı)
  return dateObj.getDay();
}

function dayWorkingHoursToRange(wh) {
  if (!wh || wh.is_available === false) return null;
  const st = timeToMinutes((wh.start_time || '09:00').slice(0, 5));
  let en;
  const endRaw = (wh.end_time || '20:00').slice(0, 5);
  if (endRaw === '00:00' || endRaw === '24:00') {
    en = 24 * 60;
  } else {
    en = timeToMinutes(endRaw);
  }
  if (en <= st) en = 24 * 60;
  return { start: st, end: en };
}

function extendRangeFromAppointment(range, apt) {
  if (!apt?.time) return range;
  const st = timeToMinutes(apt.time.slice(0, 5));
  const en = st + (apt.duration_minutes || 30);
  return {
    start: Math.min(range.start, st),
    end: Math.max(range.end, en),
  };
}

async function fetchScheduleWorkingHours(staffId) {
  const cacheKey = staffId ? `wh_s${staffId}` : 'wh_all';
  if (_scheduleRangeCache[cacheKey]) return _scheduleRangeCache[cacheKey];

  let workingHours = [];

  if (staffId) {
    const { ok, data } = await apiCall(`/admin/working-hours?staff_id=${staffId}`, { method: 'GET' });
    if (ok && data.success) workingHours = data.working_hours || [];
  } else {
    let staff = getAdminStaff();
    if (hasStudioAccess(staff?.role)) {
      const { ok, data } = await apiCall('/admin/staff', { method: 'GET' });
      if (ok && data.success && (data.staff || []).length) {
        const merged = new Map();
        for (const s of data.staff) {
          const whRes = await apiCall(`/admin/working-hours?staff_id=${s.id}`, { method: 'GET' });
          if (!whRes.ok || !whRes.data.success) continue;
          (whRes.data.working_hours || []).forEach((wh) => {
            const key = wh.day_of_week;
            const existing = merged.get(key);
            if (!existing) {
              merged.set(key, { ...wh });
              return;
            }
            const a = dayWorkingHoursToRange(existing);
            const b = dayWorkingHoursToRange(wh);
            if (!a) return;
            if (!b) return;
            merged.set(key, {
              ...existing,
              is_available: true,
              start_time: minutesToTime(Math.min(a.start, b.start)),
              end_time: minutesToTime(Math.max(a.end, b.end)),
            });
          });
        }
        workingHours = [...merged.values()];
      }
    } else {
      const { ok, data } = await apiCall('/admin/working-hours', { method: 'GET' });
      if (ok && data.success) workingHours = data.working_hours || [];
    }
  }

  _scheduleRangeCache[cacheKey] = workingHours;
  return workingHours;
}

/** Takvim tablosu saat sütunları — backend ile aynı kaynak (randevuya göre daralmaz) */
async function fetchScheduleGridTimes(staffId) {
  const cacheKey = `grid_${staffId || 'all'}`;
  if (_scheduleRangeCache[cacheKey]) return _scheduleRangeCache[cacheKey];

  const qs = new URLSearchParams();
  if (staffId) qs.set('staff_id', String(staffId));

  const { ok, data } = await apiCall(`/admin/schedule-grid-times?${qs.toString()}`, { method: 'GET' });
  let times = buildScheduleTimeSlots();
  if (ok && data.success && Array.isArray(data.times) && data.times.length) {
    times = data.times.map((t) => String(t).slice(0, 5));
  }

  _scheduleRangeCache[cacheKey] = times;
  return times;
}

/** Randevu çalışma saatleri dışındaysa sütunlara ekle */
function ensureAppointmentTimesInGrid(times, appointmentsInWeek) {
  const set = new Set(times);
  let minM = times.length ? timeToMinutes(times[0]) : DEFAULT_SCHEDULE_START_MINS;
  let maxM = times.length ? timeToMinutes(times[times.length - 1]) + 30 : DEFAULT_SCHEDULE_END_MINS;

  (appointmentsInWeek || []).forEach((apt) => {
    if (!apt?.time) return;
    const st = timeToMinutes(apt.time.slice(0, 5));
    const en = st + (apt.duration_minutes || 30);
    minM = Math.min(minM, st);
    maxM = Math.max(maxM, en);
    for (let m = st; m < en; m += 30) {
      set.add(minutesToTime(m));
    }
  });

  return [...set].sort((a, b) => timeToMinutes(a) - timeToMinutes(b));
}

function isDayClosedForSchedule(workingHours, dateObj) {
  const whByDay = new Map();
  (workingHours || []).forEach((wh) => whByDay.set(Number(wh.day_of_week), wh));
  const wh = whByDay.get(jsDateToDbDayOfWeek(dateObj));
  return !wh || wh.is_available === false || !dayWorkingHoursToRange(wh);
}

let _appointmentsData    = [];   // Randevular section
let _allAppointmentsData = [];   // Tüm Randevular section
const _tableWeekStartByContainer = {};

function normalizeDateOnly(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}
function addDays(base, days) {
  const d = new Date(base.getTime());
  d.setDate(d.getDate() + days);
  return d;
}
function formatTrDate(d) {
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;
}
function formatWeekDayShort(d) {
  return new Intl.DateTimeFormat('tr-TR', { weekday: 'short' }).format(d);
}
/** Takvim haftası: Pazartesi başlangıç */
function getMondayOfWeek(dateObj) {
  const d = normalizeDateOnly(dateObj);
  const dow = d.getDay(); // 0 Pazar, 1 Pazartesi
  const diff = dow === 0 ? -6 : 1 - dow;
  return addDays(d, diff);
}

function getWeekStart(tableContainerId) {
  if (!_tableWeekStartByContainer[tableContainerId]) {
    _tableWeekStartByContainer[tableContainerId] = getMondayOfWeek(new Date());
  }
  return normalizeDateOnly(_tableWeekStartByContainer[tableContainerId]);
}

function setWeekStart(tableContainerId, dateObj) {
  _tableWeekStartByContainer[tableContainerId] = getMondayOfWeek(dateObj);
}

/** "gg.aa.yyyy" -> Date (geçersizse null) */
function parseTrDate(s) {
  const parts = String(s || '').split('.');
  if (parts.length !== 3) return null;
  const d = parseInt(parts[0], 10);
  const mo = parseInt(parts[1], 10);
  const y = parseInt(parts[2], 10);
  if (!d || !mo || !y) return null;
  return new Date(y, mo - 1, d);
}

/** Tablo görünümünü liste ile senkron tutmak için: randevuların bulunduğu haftaya konumlan.
 *  Öncelik bugünden itibaren en yakın gelecekteki randevu, yoksa en yakın geçmiş randevu. */
function pickRelevantWeekStart(items) {
  const dates = (items || [])
    .map((a) => parseTrDate(a.date))
    .filter(Boolean)
    .map(normalizeDateOnly);
  if (!dates.length) return getMondayOfWeek(new Date());
  const today = normalizeDateOnly(new Date());
  const upcoming = dates.filter((d) => d >= today).sort((a, b) => a - b);
  const chosen = upcoming.length ? upcoming[0] : dates.sort((a, b) => b - a)[0];
  return getMondayOfWeek(chosen);
}

/** Çakışan randevular için sütun yerleşimi (Google Calendar tarzı) */
function layoutOverlappingEvents(dayAppointments) {
  const events = dayAppointments
    .filter((a) => a?.time)
    .map((a) => ({
      apt: a,
      start: timeToMinutes(a.time.slice(0, 5)),
      end: timeToMinutes(a.time.slice(0, 5)) + (a.duration_minutes || 30),
    }))
    .sort((a, b) => a.start - b.start || b.end - a.end);

  const clusters = [];
  let cluster = [];
  let clusterEnd = -1;

  events.forEach((ev) => {
    if (cluster.length && ev.start >= clusterEnd) {
      clusters.push(cluster);
      cluster = [];
      clusterEnd = -1;
    }
    cluster.push(ev);
    clusterEnd = Math.max(clusterEnd, ev.end);
  });
  if (cluster.length) clusters.push(cluster);

  const laidOut = [];
  clusters.forEach((cl) => {
    const columnEnds = [];
    cl.forEach((ev) => {
      let col = 0;
      while (columnEnds[col] && columnEnds[col] > ev.start) col += 1;
      columnEnds[col] = ev.end;
      ev.col = col;
    });
    const totalCols = columnEnds.length || 1;
    cl.forEach((ev) => {
      ev.totalCols = totalCols;
      laidOut.push(ev);
    });
  });

  return laidOut;
}

function formatGcalDayHeader(dateObj) {
  const day = new Intl.DateTimeFormat('tr-TR', { weekday: 'short' }).format(dateObj).replace('.', '').toUpperCase();
  return { day, dateNum: dateObj.getDate() };
}

function formatGcalMonthYear(dateObj) {
  const raw = new Intl.DateTimeFormat('tr-TR', { month: 'long', year: 'numeric' }).format(dateObj);
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function buildGcalEventBlock(ev, gridStartMins, slotHeight) {
  const a = ev.apt;
  const startMins = ev.start;
  const duration = a.duration_minutes || 30;
  const topPx = ((startMins - gridStartMins) / 30) * slotHeight;
  const heightPx = Math.max((duration / 30) * slotHeight - 3, 28);
  const widthPct = 100 / ev.totalCols;
  const leftPct = ev.col * widthPct;

  const statusColors = {
    confirmed: 'gcal-event--confirmed',
    pending: 'gcal-event--pending',
    completed: 'gcal-event--completed',
    cancelled: 'gcal-event--cancelled',
    no_show: 'gcal-event--noshow',
  };
  const statusClass = statusColors[a.status] || 'gcal-event--default';

  const customer = a.customer?.full_name || (a.customer?.phone ? `0${a.customer.phone}` : 'Müşteri');
  const phone = a.customer?.phone ? `0${a.customer.phone}` : '';
  const tr = a.tattoo_request || {};
  const detailParts = [tr.description, tr.body_area, tr.size].filter(Boolean);
  const detailLine = detailParts.join(' · ');
  const startT = a.time.slice(0, 5);
  const endT = minutesToTime(startMins + duration);

  const sourceLabel = appointmentSourceText(a.source);
  return `<div class="gcal-event ${statusClass}" style="top:${topPx}px;height:${heightPx}px;left:calc(${leftPct}% + 2px);width:calc(${widthPct}% - 4px);" title="${escapeHtml(customer)} · ${escapeHtml(sourceLabel)}">
    <div class="gcal-event-title">${escapeHtml(customer)}</div>
    ${phone ? `<div class="gcal-event-line">${escapeHtml(phone)}</div>` : ''}
    ${detailLine ? `<div class="gcal-event-line">${escapeHtml(detailLine)}</div>` : ''}
    ${a.staff?.name ? `<div class="gcal-event-line gcal-event-staff">${escapeHtml(a.staff.name)}</div>` : ''}
    <div class="gcal-event-time">${startT} – ${endT} · ${escapeHtml(sourceLabel)}</div>
  </div>`;
}

async function renderAppointmentsTable(itemsRaw, tableContainerId) {
  const SLOT_HEIGHT = 48;
  let items = [...(itemsRaw || [])];
  const wrap = $(tableContainerId);
  if (!wrap) return;

  const weekStart = getWeekStart(tableContainerId);
  const weekDates = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const weekDateStrings = weekDates.map(formatTrDate);
  const weekDateSet = new Set(weekDateStrings);
  const todayStr = formatTrDate(normalizeDateOnly(new Date()));

  items = items.filter((a) => a.date && weekDateSet.has(a.date));

  const staffIdForHours = getTableStaffIdForHours(tableContainerId);
  const workingHours = await fetchScheduleWorkingHours(staffIdForHours);
  let times = await fetchScheduleGridTimes(staffIdForHours);
  times = ensureAppointmentTimesInGrid(times, items);

  if (!times.length) times = buildScheduleTimeSlots();

  const gridStartMins = timeToMinutes(times[0]);
  const gridEndMins = timeToMinutes(times[times.length - 1]) + 30;
  const totalHeight = times.length * SLOT_HEIGHT;
  const monthLabel = formatGcalMonthYear(weekDates[3] || weekDates[0]);
  const rangeLabel = `${weekDateStrings[0]} – ${weekDateStrings[6]}`;

  const itemsByDate = {};
  weekDateStrings.forEach((d) => { itemsByDate[d] = []; });
  items.forEach((a) => {
    if (itemsByDate[a.date]) itemsByDate[a.date].push(a);
  });

  const now = new Date();
  const nowMins = now.getHours() * 60 + now.getMinutes();

  const dayHeaders = weekDates.map((dateObj, i) => {
    const { day, dateNum } = formatGcalDayHeader(dateObj);
    const isToday = weekDateStrings[i] === todayStr;
    return `<div class="gcal-day-head${isToday ? ' gcal-day-head--today' : ''}">
      <span class="gcal-day-name">${escapeHtml(day)}</span>
      <span class="gcal-day-num">${dateNum}</span>
    </div>`;
  }).join('');

  const timeGutter = times.map((t, idx) => {
    const isHour = t.endsWith(':00');
    const firstClass = idx === 0 ? ' gcal-time-slot--first' : '';
    return `<div class="gcal-time-slot${isHour ? ' gcal-time-slot--hour' : ''}${firstClass}" style="height:${SLOT_HEIGHT}px">
      ${isHour ? `<span>${t}</span>` : ''}
    </div>`;
  }).join('');

  const dayColumns = weekDates.map((dateObj, idx) => {
    const dateStr = weekDateStrings[idx];
    const dayClosed = isDayClosedForSchedule(workingHours, dateObj);
    const hasAppts = (itemsByDate[dateStr] || []).length > 0;
    const isToday = dateStr === todayStr;

    const slotLines = times.map(() =>
      `<div class="gcal-grid-line" style="height:${SLOT_HEIGHT}px"></div>`
    ).join('');

    const laidOut = layoutOverlappingEvents(itemsByDate[dateStr] || []);
    const eventsHtml = laidOut
      .map((ev) => buildGcalEventBlock(ev, gridStartMins, SLOT_HEIGHT))
      .join('');

    let nowLine = '';
    if (isToday && nowMins >= gridStartMins && nowMins <= gridEndMins) {
      const nowTop = ((nowMins - gridStartMins) / 30) * SLOT_HEIGHT;
      nowLine = `<div class="gcal-now-line" style="top:${nowTop}px"></div>`;
    }

    return `<div class="gcal-day-col${dayClosed && !hasAppts ? ' gcal-day-col--closed' : ''}${isToday ? ' gcal-day-col--today' : ''}">
      <div class="gcal-slots-bg" style="height:${totalHeight}px">${slotLines}</div>
      <div class="gcal-events-layer" style="height:${totalHeight}px">${eventsHtml}${nowLine}</div>
    </div>`;
  }).join('');

  wrap.innerHTML = `
    <div class="sch-week-nav gcal-week-nav">
      <button type="button" class="sch-week-btn secondary" data-week-nav="today">Bugün</button>
      <div class="gcal-week-nav-center">
        <button type="button" class="gcal-nav-arrow" data-week-nav="prev" aria-label="Önceki hafta">‹</button>
        <div class="gcal-month-label">${escapeHtml(monthLabel)}</div>
        <button type="button" class="gcal-nav-arrow" data-week-nav="next" aria-label="Sonraki hafta">›</button>
      </div>
      <div class="sch-week-range">${escapeHtml(rangeLabel)}</div>
    </div>
    <div class="gcal-scroll">
      <div class="gcal-grid">
        <div class="gcal-header">
          <div class="gcal-corner"><span class="gcal-tz">GMT+3</span></div>
          <div class="gcal-days-header">${dayHeaders}</div>
        </div>
        <div class="gcal-body">
          <div class="gcal-times">${timeGutter}</div>
          <div class="gcal-days" style="height:${totalHeight}px">${dayColumns}</div>
        </div>
      </div>
    </div>`;

  const nav = (dir) => {
    if (dir === 'today') {
      setWeekStart(tableContainerId, new Date());
    } else {
      const offset = dir === 'prev' ? -7 : 7;
      setWeekStart(tableContainerId, addDays(getWeekStart(tableContainerId), offset));
    }
    void renderAppointmentsTable(itemsRaw, tableContainerId);
  };
  wrap.querySelector('[data-week-nav="prev"]')?.addEventListener('click', () => nav('prev'));
  wrap.querySelector('[data-week-nav="next"]')?.addEventListener('click', () => nav('next'));
  wrap.querySelector('[data-week-nav="today"]')?.addEventListener('click', () => nav('today'));
}

function setupViewToggle(listBtnId, tableBtnId, listViewId, tableViewId, tableContainerId) {
  const listBtn   = $(listBtnId);
  const tableBtn  = $(tableBtnId);
  const listView  = $(listViewId);
  const tableView = $(tableViewId);
  if (!listBtn || !tableBtn) return;

  listBtn.addEventListener('click', () => {
    listBtn.classList.add('active');
    tableBtn.classList.remove('active');
    if (listView)  listView.style.display  = 'block';
    if (tableView) tableView.style.display = 'none';
  });

  tableBtn.addEventListener('click', () => {
    tableBtn.classList.add('active');
    listBtn.classList.remove('active');
    if (listView)  listView.style.display  = 'none';
    if (tableView) tableView.style.display = 'block';
    // İlk kez tablo açılıyorsa render et
    const data = tableContainerId === 'all-appointments-table' ? _appointmentsData : _allAppointmentsData;
    void renderAppointmentsTable(data, tableContainerId);
  });
}

async function loadAllAppointments() {
  showSection('all-appointments');
  await populateStaffFilter('all-appointments-staff-filter');
  delete _tableWeekStartByContainer['all-appointments-table-container'];
  const container = $('all-appointments-container');
  if (container) container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';

  const staffFilter = $('all-appointments-staff-filter')?.value || '';
  const startDate   = $('all-appointments-start-date')?.value || '';
  const endDate     = $('all-appointments-end-date')?.value || '';

  const qs = new URLSearchParams();
  qs.set('scope', 'all'); // Tüm Randevular: super_admin tüm personeli görür
  if (staffFilter) qs.set('staff_id', staffFilter);
  if (startDate)   qs.set('start_date', startDate);
  if (endDate)     qs.set('end_date', endDate);
  qs.set('exclude_completed', 'true'); // Tamamlananlar Geçmiş Randevular'a taşındı

  const { ok, data } = await apiCall(`/admin/appointments?${qs.toString()}`, { method: 'GET' });
  if (!ok || !data.success) {
    if (container) container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  _allAppointmentsData = data.appointments || [];
  renderAppointmentsGrouped('all-appointments-container', _allAppointmentsData);

  // Tabloyu liste ile senkronla: randevuların olduğu haftaya konumlan
  setWeekStart('all-appointments-table-container', pickRelevantWeekStart(_allAppointmentsData));

  const tableView = $('all-appointments-table-view');
  if (tableView && tableView.style.display !== 'none') {
    void renderAppointmentsTable(_allAppointmentsData, 'all-appointments-table-container');
  }
}

async function populateStaffFilter(selectId) {
  const sel = $(selectId);
  if (!sel || sel.options.length > 1) return; // already populated
  const { ok, data } = await apiCall('/admin/staff', { method: 'GET' });
  if (!ok || !data.success) return;
  (data.staff || []).filter((s) => isBookableStaffRole(s.role)).forEach((s) => {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.name;
    sel.appendChild(opt);
  });
}

async function loadPastAppointments() {
  showSection('past-appointments');
  populateStaffFilter('past-appointments-staff-filter');
  const container = $('past-appointments-container');
  if (container) container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';

  const staffFilter = $('past-appointments-staff-filter')?.value || '';
  const startDate   = $('past-appointments-start-date')?.value || '';
  const endDate     = $('past-appointments-end-date')?.value || '';

  const qs = new URLSearchParams();
  qs.set('scope', 'all'); // Geçmiş Randevular: super_admin tüm personeli görür
  qs.set('status', 'completed');
  if (staffFilter) qs.set('staff_id', staffFilter);
  if (startDate)   qs.set('start_date', startDate);
  if (endDate)     qs.set('end_date', endDate);

  const { ok, data } = await apiCall(`/admin/appointments?${qs.toString()}`, { method: 'GET' });
  if (!ok || !data.success) {
    if (container) container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  renderPastAppointments('past-appointments-container', data.appointments || []);
}

function renderPastAppointments(containerId, items) {
  const container = $(containerId);
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-message">Tamamlanan randevu yok</p>';
    return;
  }
  container.innerHTML = items.map((a) => {
    const customer = a.customer?.full_name ? a.customer.full_name : `0${a.customer?.phone || '-'}`;
    const artist   = a.staff?.name || '-';
    const tr       = a.tattoo_request || {};
    const price    = parseFloat(a.price || 0);
    const priceRow = price > 0
      ? `<div class="apt-detail-row">
           <span class="apt-detail-icon"><i class="fas fa-tag"></i></span>
           <span class="apt-detail-label">Fiyat:</span>
           <span class="apt-detail-value" style="color:var(--accent);font-weight:400;">${price.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺</span>
         </div>`
      : '';
    return `
      <div class="appointment-card status-completed">
        <div class="apt-card-top">
          <div class="apt-datetime">
            <div class="appointment-date"><i class="fas fa-calendar-alt"></i> ${escapeHtml(a.date)}</div>
            <div class="appointment-time"><i class="fas fa-clock"></i> ${escapeHtml(a.time)}</div>
          </div>
          <div class="apt-card-badges">
            ${appointmentSourceBadgeHtml(a.source)}
            <span class="status-badge completed">${escapeHtml(statusText('completed'))}</span>
          </div>
        </div>
        <div class="apt-card-body">
          <div class="apt-detail-row">
            <span class="apt-detail-icon"><i class="fas fa-user"></i></span>
            <span class="apt-detail-label">Müşteri:</span>
            <span class="apt-detail-value">${escapeHtml(customer)}</span>
          </div>
          <div class="apt-detail-row">
            <span class="apt-detail-icon"><i class="fas fa-paint-brush"></i></span>
            <span class="apt-detail-label">Sanatçı:</span>
            <span class="apt-detail-value">${escapeHtml(artist)}</span>
          </div>
          <div class="apt-detail-row">
            <span class="apt-detail-icon"><i class="fas fa-clock"></i></span>
            <span class="apt-detail-label">Süre:</span>
            <span class="apt-detail-value">${a.duration_minutes || 30} dk</span>
          </div>
          ${tr.body_area ? `<div class="apt-detail-row">
            <span class="apt-detail-icon"><i class="fas fa-map-marker-alt"></i></span>
            <span class="apt-detail-label">Bölge:</span>
            <span class="apt-detail-value">${escapeHtml(tr.body_area)}</span>
          </div>` : ''}
          ${tr.size ? `<div class="apt-detail-row">
            <span class="apt-detail-icon"><i class="fas fa-ruler-combined"></i></span>
            <span class="apt-detail-label">Boyut:</span>
            <span class="apt-detail-value">${escapeHtml(tr.size)}</span>
          </div>` : ''}
          ${priceRow}
        </div>
      </div>
    `;
  }).join('');
}

async function loadPending() {
  const container = $('pending-appointments');
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  const { ok, data } = await apiCall('/admin/appointments?status=pending', { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  renderAppointments('pending-appointments', data.appointments || []);
}

async function loadSchedule() {
  if (!hasStudioAccess()) return;
  const canEditHours = true;
  const saveWh = $('save-working-hours-btn');
  if (saveWh) saveWh.style.display = canEditHours ? '' : 'none';

  const whContainer = $('working-hours-table');
  const toContainer = $('time-off-list');
  if (whContainer) whContainer.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  if (toContainer) toContainer.innerHTML = '<p class="empty-message">Yükleniyor...</p>';

  const wh = await apiCall('/admin/working-hours', { method: 'GET' });
  if (!wh.ok || !wh.data.success) {
    if (whContainer) whContainer.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(wh.data.message || 'Yüklenemedi')}</p>`;
  } else {
    const hours = wh.data.working_hours || [];
    renderWorkingHours(hours, { containerId: 'working-hours-table', readOnly: !canEditHours });
    const notice = $('working-hours-notice');
    const noticeText = $('working-hours-notice-text');
    if (notice) {
      if (!canEditHours) {
        notice.style.display = 'flex';
        if (noticeText) {
          noticeText.textContent = hours.length
            ? 'Çalışma saatleriniz Super Admin tarafından belirlenmiştir. Değişiklik için stüdyo yöneticisine başvurun.'
            : 'Çalışma saatleri henüz belirlenmemiş. Super Admin kaydettikten sonra burada görünür.';
        }
      } else {
        notice.style.display = hours.length === 0 ? 'flex' : 'none';
        if (noticeText) {
          noticeText.innerHTML = 'Çalışma saatleri henüz kaydedilmemiş. Aşağıdaki saatler önizlemedir — müşteri tarafında da aynı aralık (10:00–20:00) kullanılır. Kesinleştirmek için <strong>Kaydet</strong>’e basın.';
        }
      }
    }
  }

  const to = await apiCall('/admin/time-off', { method: 'GET' });
  if (!to.ok || !to.data.success) {
    if (toContainer) toContainer.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(to.data.message || 'Yüklenemedi')}</p>`;
  } else {
    renderTimeOff(to.data.time_offs || to.data.time_off || []);
  }
}

function collectWorkingHoursPayload(container) {
  const payload = [];
  for (let day = 0; day <= 6; day++) {
    const start = container?.querySelector(`input[data-wh-start="${day}"]`)?.value || '10:00';
    const end = container?.querySelector(`input[data-wh-end="${day}"]`)?.value || '20:00';
    const isAvailable = !!container?.querySelector(`input[data-wh-open="${day}"]`)?.checked;
    payload.push({ day_of_week: day, start_time: start, end_time: end, is_available: isAvailable });
  }
  return payload;
}

function renderWorkingHours(items, { containerId = 'working-hours-table', readOnly = false } = {}) {
  const container = $(containerId);
  if (!container) return;
  const dayNames = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];
  const disabledAttr = readOnly ? 'disabled' : '';

  // Map by day_of_week
  const byDay = new Map();
  (items || []).forEach((w) => byDay.set(Number(w.day_of_week), w));

  container.classList.toggle('is-readonly', readOnly);
  container.innerHTML = dayNames
    .map((name, idx) => {
      const day = idx; // backend uses 0..6
      const w = byDay.get(day) || { day_of_week: day, start_time: '10:00', end_time: '20:00', is_available: true };
      const isOpen = !!w.is_available;
      return `
        <div class="working-hour-row">
          <div class="wh-day">${escapeHtml(name)}</div>
          <div class="wh-toggle">
            <label class="switch" title="Açık/Kapalı">
              <input type="checkbox" data-wh-open="${day}" ${isOpen ? 'checked' : ''} ${disabledAttr} />
              <span class="slider"></span>
            </label>
          </div>
          <div class="wh-times ${isOpen ? '' : 'disabled'}">
            <input type="time" data-wh-start="${day}" value="${escapeHtml(w.start_time || '10:00')}" ${isOpen && !readOnly ? '' : 'disabled'} />
            <span style="color: var(--text-muted);">-</span>
            <input type="time" data-wh-end="${day}" value="${escapeHtml(w.end_time || '20:00')}" ${isOpen && !readOnly ? '' : 'disabled'} />
          </div>
        </div>
      `;
    })
    .join('');

  if (readOnly) return;

  // Toggle enable/disable time inputs
  container.querySelectorAll('input[data-wh-open]').forEach((chk) => {
    chk.addEventListener('change', () => {
      const day = chk.getAttribute('data-wh-open');
      const start = container.querySelector(`input[data-wh-start="${day}"]`);
      const end = container.querySelector(`input[data-wh-end="${day}"]`);
      const row = chk.closest('.working-hour-row');
      const times = row?.querySelector('.wh-times');
      const open = chk.checked;
      if (start) start.disabled = !open;
      if (end) end.disabled = !open;
      if (times) times.classList.toggle('disabled', !open);
    });
  });
}

function renderTimeOff(items, { containerId = 'time-off-list', deleteUrlFor } = {}) {
  const container = $(containerId);
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-message">İzin günü yok</p>';
    return;
  }
  container.innerHTML = items
    .map((t) => {
      return `
        <div class="appointment-card status-cancelled">
          <div class="appointment-header">
            <div>
              <div class="appointment-date"><i class="fas fa-calendar-alt"></i> ${escapeHtml(t.date)}</div>
              <div class="appointment-time"><i class="fas fa-clock"></i> ${escapeHtml(t.start_time || 'Tüm gün')} ${t.end_time ? `- ${escapeHtml(t.end_time)}` : ''}</div>
            </div>
            <button class="filter-btn secondary" data-timeoff-del="${t.id}"><i class="fas fa-trash"></i> Sil</button>
          </div>
          <div class="appointment-details">
            <div class="detail-row"><i class="fas fa-note-sticky"></i><span class="detail-label">Açıklama</span><span class="detail-value">${escapeHtml(t.reason || '-')}</span></div>
          </div>
        </div>
      `;
    })
    .join('');

  container.querySelectorAll('button[data-timeoff-del]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-timeoff-del');
      const url = deleteUrlFor ? deleteUrlFor(id) : `/admin/time-off/${id}`;
      const { ok, data } = await apiCall(url, { method: 'DELETE' });
      if (!ok || !data.success) {
        showToast(data.message || 'Silinemedi', 'error');
        return;
      }
      showToast('Silindi', 'success');
      if (containerId === 'staff-time-off-list') await loadStaffSchedule();
      else await loadSchedule();
    });
  });
}

function renderStaff(items) {
  const container = $('staff-list');
  if (!container) return;
  if (!items || items.length === 0) {
    container.innerHTML = '<p class="empty-message">Personel yok</p>';
    return;
  }

  const viewerStudio = hasStudioAccess();
  const viewerIncome = canAccessIncome();

  container.innerHTML = items
    .map((s) => {
      const roleClass = s.role === 'super_admin' ? 'super_admin' : (s.role === 'tech_support' ? 'tech_support' : '');
      const canEditTarget = viewerIncome || s.role !== 'super_admin';
      const phonePretty = formatPhonePretty(s.phone);
      return `
        <div class="staff-card">
          <div class="staff-order-badge">#${escapeHtml(String(s.display_order ?? 0))}</div>
          <div class="staff-avatar">
            ${s.profile_photo ? `<img src="${escapeHtml(s.profile_photo)}" alt="${escapeHtml(s.name)}" />` : '<i class="fas fa-user"></i>'}
          </div>
          <div class="staff-name">${escapeHtml(s.name)}</div>
          <div class="staff-role ${roleClass}">${escapeHtml(roleLabel(s.role))}</div>
          <div class="staff-phone"><i class="fas fa-phone"></i> ${escapeHtml(phonePretty)}</div>

          <div class="staff-order-input-group">
            <label>Sıra:</label>
            <input class="staff-order-input" type="number" min="0" value="${escapeHtml(String(s.display_order ?? 0))}" data-staff-order="${s.id}" />
          </div>

          <div class="staff-icon-actions">
            ${viewerStudio ? `
            ${viewerIncome ? `<button class="icon-btn stats" type="button" title="Kazanç Detayı" data-staff-stats="${s.id}">
              <i class="fas fa-chart-bar"></i>
            </button>` : ''}
            <button class="icon-btn schedule" type="button" title="Çalışma Saatleri" data-staff-schedule="${s.id}">
              <i class="fas fa-clock"></i>
            </button>` : ''}
            ${canEditTarget ? `<button class="icon-btn edit" type="button" title="Düzenle" data-staff-edit="${s.id}">
              <i class="fas fa-pen"></i>
            </button>
            <button class="icon-btn delete" type="button" title="Sil" data-staff-delete="${s.id}">
              <i class="fas fa-trash"></i>
            </button>` : ''}
          </div>
        </div>
      `;
    })
    .join('');

  // Auto-save order on change (no extra button)
  container.querySelectorAll('input[data-staff-order]').forEach((input) => {
    input.addEventListener('change', async () => {
      const id = input.getAttribute('data-staff-order');
      const display_order = parseInt(input.value || '0', 10);
      const { ok, data } = await apiCall(`/admin/staff/${id}/display-order`, {
        method: 'PATCH',
        body: JSON.stringify({ display_order }),
      });
      if (!ok || !data.success) {
        showToast(data.message || 'Sıra kaydedilemedi', 'error');
        return;
      }
      showToast('Sıra kaydedildi', 'success');
      await loadStaff();
    });
  });

  // Edit
  container.querySelectorAll('button[data-staff-edit]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-staff-edit');
      const current = items.find((x) => String(x.id) === String(id));
      if (!current) return;
      openStaffModal({ mode: 'edit', staff: current });
    });
  });

  // Delete
  container.querySelectorAll('button[data-staff-delete]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-staff-delete');
      const confirmed = await customConfirm('Personeli Sil', 'Bu personeli silmek istediğinizden emin misiniz? Bu işlem geri alınamaz.');
      if (!confirmed) return;
      const { ok, data } = await apiCall(`/admin/staff/${id}?force=true`, { method: 'DELETE' });
      if (!ok || !data.success) {
        showToast(data.message || 'Silinemedi', 'error');
        return;
      }
      showToast('Silindi', 'success');
      await loadStaff();
    });
  });

  // Kazanç detayı (super admin)
  container.querySelectorAll('button[data-staff-stats]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-staff-stats');
      const staff = items.find((x) => String(x.id) === String(id));
      if (!staff) return;
      openStaffStatsModal(staff);
    });
  });

  container.querySelectorAll('button[data-staff-schedule]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.getAttribute('data-staff-schedule');
      const staff = items.find((x) => String(x.id) === String(id));
      if (!staff) return;
      openStaffScheduleModal(staff);
    });
  });
}

async function loadStaff() {
  const container = $('staff-list');
  if (!container) return;
  container.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  const { ok, data } = await apiCall('/admin/staff', { method: 'GET' });
  if (!ok || !data.success) {
    container.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(data.message || 'Yüklenemedi')}</p>`;
    return;
  }
  renderStaff(data.staff || []);
}

function fmtMoney(value) {
  const n = Number(value || 0);
  return `${n.toFixed(2)} ₺`;
}

let _staffStatsTargetId = null;
let _staffStatsIsOwner = false;

function populateYearSelect(selectEl, selectedYear) {
  if (!selectEl) return;
  const currentYear = new Date().getFullYear();
  selectEl.innerHTML = '';
  for (let y = currentYear; y >= currentYear - 6; y--) {
    const opt = document.createElement('option');
    opt.value = String(y);
    opt.textContent = String(y);
    selectEl.appendChild(opt);
  }
  if (selectedYear) selectEl.value = String(selectedYear);
}

function openStaffStatsModal(staff) {
  _staffStatsTargetId = staff.id;
  _staffStatsIsOwner = staff.role === 'super_admin';
  const nameEl = $('staff-stats-name');
  if (nameEl) nameEl.textContent = staff.name || 'Personel';

  const now = new Date();
  const monthSel = $('staff-stats-month');
  const yearSel = $('staff-stats-year');
  if (monthSel) monthSel.value = String(now.getMonth() + 1);
  populateYearSelect(yearSel, now.getFullYear());

  const overlay = $('staff-stats-overlay');
  overlay?.classList.toggle('is-owner-stats', _staffStatsIsOwner);
  if (overlay) overlay.style.display = 'flex';
  loadStaffStats();
}

function closeStaffStatsModal() {
  _staffStatsTargetId = null;
  _staffStatsIsOwner = false;
  const overlay = $('staff-stats-overlay');
  overlay?.classList.remove('is-owner-stats');
  if (overlay) overlay.style.display = 'none';
}

let _staffScheduleTargetId = null;

function openStaffScheduleModal(staff) {
  _staffScheduleTargetId = staff.id;
  const nameEl = $('staff-schedule-name');
  if (nameEl) nameEl.textContent = staff.name || 'Personel';
  const overlay = $('staff-schedule-overlay');
  if (overlay) overlay.style.display = 'flex';
  loadStaffSchedule();
}

function closeStaffScheduleModal() {
  _staffScheduleTargetId = null;
  const overlay = $('staff-schedule-overlay');
  if (overlay) overlay.style.display = 'none';
}

async function loadStaffSchedule() {
  if (!_staffScheduleTargetId) return;
  const whContainer = $('staff-working-hours-table');
  const toContainer = $('staff-time-off-list');
  if (whContainer) whContainer.innerHTML = '<p class="empty-message">Yükleniyor...</p>';
  if (toContainer) toContainer.innerHTML = '<p class="empty-message">Yükleniyor...</p>';

  const wh = await apiCall(`/admin/staff/${_staffScheduleTargetId}/working-hours`, { method: 'GET' });
  if (!wh.ok || !wh.data.success) {
    if (whContainer) whContainer.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(wh.data.message || 'Yüklenemedi')}</p>`;
  } else {
    renderWorkingHours(wh.data.working_hours || [], { containerId: 'staff-working-hours-table' });
  }

  const to = await apiCall(`/admin/staff/${_staffScheduleTargetId}/time-off`, { method: 'GET' });
  if (!to.ok || !to.data.success) {
    if (toContainer) toContainer.innerHTML = `<p class="empty-message">Hata: ${escapeHtml(to.data.message || 'Yüklenemedi')}</p>`;
  } else {
    renderTimeOff(to.data.time_offs || to.data.time_off || [], {
      containerId: 'staff-time-off-list',
      deleteUrlFor: (id) => `/admin/staff/${_staffScheduleTargetId}/time-off/${id}`,
    });
  }
}

async function loadStaffStats() {
  if (!_staffStatsTargetId) return;

  const month = $('staff-stats-month')?.value || '';
  const year = $('staff-stats-year')?.value || '';
  const qs = new URLSearchParams();
  if (month) qs.set('month', month);
  if (year) qs.set('year', year);

  const { ok, data } = await apiCall(`/admin/staff/${_staffStatsTargetId}/stats?${qs.toString()}`, { method: 'GET' });
  if (!ok || !data.success) {
    showToast(data?.message || 'İstatistikler alınamadı', 'error');
    return;
  }

  const stats = data.stats || {};
  if (data.staff?.role === 'super_admin') _staffStatsIsOwner = true;
  $('staff-stats-overlay')?.classList.toggle('is-owner-stats', _staffStatsIsOwner);

  const incomeEl = $('staff-stat-income');
  const shareEl = $('staff-stat-share');
  const customersEl = $('staff-stat-customers');
  const appointmentsEl = $('staff-stat-appointments');
  const commissionPct = Number(stats.commission_percent || 50);
  if (incomeEl) incomeEl.textContent = fmtMoney(stats.total_income);
  if (shareEl && !_staffStatsIsOwner) {
    shareEl.textContent = fmtMoney(stats.staff_share_total ?? (Number(stats.total_income || 0) * 0.5));
  }
  if (customersEl) customersEl.textContent = String(stats.customer_count || 0);
  if (appointmentsEl) appointmentsEl.textContent = String(stats.appointment_count || 0);

  const durEl = $('staff-duration-summary');
  if (durEl) {
    durEl.innerHTML = stats.total_duration_minutes
      ? `Toplam dövme süresi: <strong>${stats.total_duration_minutes} dk</strong>`
      : 'Bu dönemde tamamlanmış randevu yok.';
  }

  const revList = $('staff-revenue-list');
  if (revList) {
    const items = stats.completed_revenue_items || [];
    if (!items.length) {
      revList.innerHTML = '<p class="empty-message">Bu dönemde tamamlanan randevu geliri yok.</p>';
    } else {
      revList.innerHTML = items.map((item) => {
        const full = Number(item.amount || 0);
        const share = Number(item.staff_share ?? full * 0.5);
        const shareHtml = _staffStatsIsOwner
          ? ''
          : `<span class="adj-share">Kazanç %${commissionPct}: ${fmtMoney(share)}</span>`;
        return `
        <div class="adj-row">
          <div class="adj-info">
            <div class="adj-desc">Randevu #${item.appointment_id} · ${escapeHtml(item.customer_name)}</div>
            <div class="adj-meta">${escapeHtml(item.date)} ${escapeHtml(item.time)}</div>
          </div>
          <div class="adj-right adj-right-stack">
            <span class="adj-amount" style="color:var(--success, #4caf50);">${_staffStatsIsOwner ? fmtMoney(full) : `Tam ${fmtMoney(full)}`}</span>
            ${shareHtml}
          </div>
        </div>
      `;
      }).join('');
    }
  }
}

async function loadIncomeReport() {
  if (!canAccessIncome()) {
    showToast('Bu rapora erişim yetkiniz yok', 'error');
    return;
  }

  const month = $('report-month')?.value || '';
  const year  = $('report-year')?.value  || '';
  const qs    = new URLSearchParams();
  if (month) qs.set('month', month);
  if (year)  qs.set('year',  year);

  const { ok, data } = await apiCall(`/admin/reports/income?${qs.toString()}`, { method: 'GET' });
  if (!ok || !data.success) {
    showToast(data?.message || 'Rapor alınamadı', 'error');
    return;
  }

  // Özet kartları
  const totalEl = $('report-total-income');
  const aptIncomeEl = $('report-appointment-income');
  const countEl = $('report-appointment-count');
  if (totalEl) totalEl.textContent = fmtMoney(data.total_income);
  if (aptIncomeEl) aptIncomeEl.textContent = fmtMoney(data.appointment_income);
  if (countEl) countEl.textContent = String(data.appointment_count || 0);

  const sb = $('service-breakdown');
  if (sb) {
    const durText = data.total_duration_minutes
      ? `Toplam dövme süresi: <strong>${data.total_duration_minutes} dk</strong>`
      : 'Bu dönemde tamamlanmış randevu yok.';
    const manualExtra = data.manual_adjustments_total
      ? `<br>Manuel ayarlamalar (net): <strong>${fmtMoney(data.manual_adjustments_total)}</strong>`
      : '';
    sb.innerHTML = `<p class="empty-message" style="text-align:left;">${durText}${manualExtra}</p>`;
  }

  const revList = $('completed-revenue-list');
  if (revList) {
    const items = data.completed_revenue_items || [];
    if (!items.length) {
      revList.innerHTML = '<p class="empty-message">Bu dönemde tamamlanan randevu geliri yok.</p>';
    } else {
      revList.innerHTML = items.map((item) => `
        <div class="adj-row">
          <div class="adj-info">
            <div class="adj-desc">Randevu #${item.appointment_id} · ${escapeHtml(item.customer_name)}</div>
            <div class="adj-meta">${escapeHtml(item.date)} ${escapeHtml(item.time)} · ${escapeHtml(item.staff_name || '')}</div>
          </div>
          <div class="adj-right">
            <span class="adj-amount" style="color:var(--success, #4caf50);">+${fmtMoney(item.amount)}</span>
          </div>
        </div>
      `).join('');
    }
  }

  // Günlük trend (₺)
  const dt   = $('daily-trend');
  if (dt) {
    const rows = data.daily_trend || [];
    if (!rows.length) {
      dt.innerHTML = '<p class="empty-message">Bu dönemde veri yok.</p>';
    } else {
      dt.innerHTML = rows.map((r) => `
        <div class="trend-row">
          <span class="trend-date">${escapeHtml(r.date)}</span>
          <span class="trend-details">
            <span><i class="fas fa-calendar-check"></i> ${r.count} randevu</span>
            <span><i class="fas fa-money-bill-wave"></i> ${fmtMoney(r.income)}</span>
          </span>
        </div>
      `).join('');
    }
  }

  // Manuel ayarlamalar
  const adjList  = $('adjustments-list');
  const adjTotal = $('adjustments-total');
  const sumBox   = document.querySelector('.adjustments-summary');
  if (adjList) {
    const items = data.manual_adjustments || [];
    if (!items.length) {
      adjList.innerHTML = '<p class="empty-message">Bu dönemde ayarlama yok.</p>';
    } else {
      adjList.innerHTML = items.map((a) => {
        const isIncome = a.type === 'income';
        const sign     = isIncome ? '+' : '-';
        const color    = isIncome ? 'var(--success, #4caf50)' : '#e53935';
        return `
          <div class="adj-row">
            <div class="adj-info">
              <div class="adj-desc">${escapeHtml(a.description)}</div>
              <div class="adj-meta">${escapeHtml(a.date)} · ${escapeHtml(a.created_by_name || 'Admin')}</div>
            </div>
            <div class="adj-right">
              <span class="adj-amount" style="color:${color};">${sign}${fmtMoney(a.amount)}</span>
              <button class="icon-btn delete-adj-btn" data-id="${a.id}" title="Sil">
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </div>
        `;
      }).join('');
      // Silme butonları
      adjList.querySelectorAll('.delete-adj-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteAdjustment(Number(btn.dataset.id)));
      });
    }
  }
  if (adjTotal) adjTotal.textContent = fmtMoney(data.manual_adjustments_total);
  if (sumBox)   sumBox.style.display = 'block';
}

async function deleteAdjustment(id) {
  const confirmed = await customConfirm('Bu ayarlamayı silmek istiyor musunuz?');
  if (!confirmed) return;
  const { ok, data } = await apiCall(`/admin/income-adjustments/${id}`, { method: 'DELETE' });
  if (ok && data.success) {
    showToast('Ayarlama silindi', 'success');
    loadIncomeReport();
  } else {
    showToast(data?.message || 'Silinemedi', 'error');
  }
}

async function submitAdjustment() {
  const amount      = $('adjustment-amount')?.value?.trim();
  const adjType     = $('adjustment-type')?.value || 'income';
  const description = $('adjustment-description')?.value?.trim();
  const adjDate     = $('adjustment-date')?.value || new Date().toISOString().split('T')[0];

  if (!amount || isNaN(Number(amount)) || Number(amount) <= 0) {
    showToast('Geçerli bir tutar girin', 'error'); return;
  }
  if (!description) {
    showToast('Açıklama zorunlu', 'error'); return;
  }

  const { ok, data } = await apiCall('/admin/income-adjustments', {
    method: 'POST',
    body: JSON.stringify({ amount: Number(amount), type: adjType, description, date: adjDate }),
  });
  if (ok && data.success) {
    showToast('Ayarlama eklendi', 'success');
    // Formu sıfırla
    if ($('adjustment-amount'))      $('adjustment-amount').value = '';
    if ($('adjustment-description')) $('adjustment-description').value = '';
    loadIncomeReport();
  } else {
    showToast(data?.message || 'Eklenemedi', 'error');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  // Populate report year options dynamically (current year down to -6 years)
  populateYearSelect($('report-year'), new Date().getFullYear());
  populateYearSelect($('staff-stats-year'), new Date().getFullYear());

  // Login form
  initRememberMeToggle();
  $('login-form')?.addEventListener('submit', handleAdminLoginSubmit);
  ['login-phone', 'login-password'].forEach((id) => {
    $(id)?.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const form = $('login-form');
      if (form?.requestSubmit) form.requestSubmit();
      else handleAdminLoginSubmit(e);
    });
  });

  $('logout-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    logout();
  });

  // Profil / şifre değiştir
  $('profile-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    openProfileModal();
  });
  $('close-profile-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeProfileModal();
  });
  $('profile-overlay')?.addEventListener('click', (e) => {
    if (e.target === $('profile-overlay')) closeProfileModal();
  });
  $('change-password-form')?.addEventListener('submit', submitChangePassword);
  $('instagram-profile-form')?.addEventListener('submit', submitInstagramProfile);

  // Staff modal close
  $('close-staff-modal-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeStaffModal();
  });
  $('staff-modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === $('staff-modal-overlay')) closeStaffModal();
  });

  $('staff-photo-select-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    $('staff-photo-input')?.click();
  });
  $('staff-photo-input')?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) setStaffPhotoFromFile(file);
  });
  $('staff-photo-remove-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    staffPhotoData = null;
    staffPhotoChanged = true;
    resetStaffPhotoPreview(null);
  });

  // Staff modal submit
  $('staff-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    $('staff-error').textContent = '';

    const name = ($('staff-name').value || '').trim();
    const phone = ($('staff-phone').value || '').trim();
    const password = ($('staff-password').value || '').trim();
  const role = (($('staff-role-select')?.value) || $('staff-role').value || 'staff').trim();
  $('staff-role').value = role;

    if (!name || !phone) {
      $('staff-error').textContent = 'Ad ve telefon gerekli';
      return;
    }

    const payload = { name, phone, role, instagram_url: ($('staff-instagram-url')?.value || '').trim() };
    if (password) payload.password = password;
    if (staffModalState.mode === 'create' && staffPhotoData) {
      payload.profile_photo = staffPhotoData;
    }
    if (staffModalState.mode === 'edit' && staffPhotoChanged) {
      payload.profile_photo = staffPhotoData ?? null;
    }

    if (staffModalState.mode === 'create' && !password) {
      $('staff-error').textContent = 'Yeni personel için şifre gerekli';
      return;
    }

    const endpoint =
      staffModalState.mode === 'edit'
        ? `/admin/staff/${encodeURIComponent(String(staffModalState.staffId))}`
        : '/admin/staff';

    const method = staffModalState.mode === 'edit' ? 'PUT' : 'POST';

    const { ok, data } = await apiCall(endpoint, {
      method,
      body: JSON.stringify(payload),
    });

    if (!ok || !data.success) {
      $('staff-error').textContent = data.message || 'İşlem başarısız';
      return;
    }

    // If user edited their own profile, update sidebar + localStorage
    try {
      const adminStaff = getAdminStaff();
      if (
        staffModalState.mode === 'edit' &&
        adminStaff &&
        (
          (adminStaff.id !== undefined && String(adminStaff.id) === String(staffModalState.staffId)) ||
          (normalizePhone10(adminStaff.phone) && normalizePhone10(adminStaff.phone) === normalizePhone10(phone))
        )
      ) {
        updateSidebarStaffInfo({ name, phone, role });
      }
    } catch {}

    showToast(staffModalState.mode === 'edit' ? 'Personel güncellendi' : 'Personel eklendi', 'success');
    closeStaffModal();
    await loadStaff();
  });

  // Dashboard shortcut (logo click etc.)
  document.querySelector('.nav-item[data-page="dashboard"]')?.addEventListener('click', async (e) => {
    e.preventDefault();
    await loadDashboard();
  });

  // Filters
  $('filter-btn')?.addEventListener('click', async (e) => {
    e.preventDefault();
    await loadAppointments();
  });
  $('clear-filter-btn')?.addEventListener('click', async (e) => {
    e.preventDefault();
    if ($('filter-status')) $('filter-status').value = '';
    if ($('appointments-start-date')) $('appointments-start-date').value = '';
    if ($('appointments-end-date')) $('appointments-end-date').value = '';
    await loadAppointments();
  });

  // Staff stats modal
  $('close-staff-stats-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeStaffStatsModal();
  });
  $('staff-stats-overlay')?.addEventListener('click', (e) => {
    if (e.target === $('staff-stats-overlay')) closeStaffStatsModal();
  });
  $('load-staff-stats-btn')?.addEventListener('click', async (e) => {
    e.preventDefault();
    await loadStaffStats();
  });

  $('close-staff-schedule-btn')?.addEventListener('click', (e) => {
    e.preventDefault();
    closeStaffScheduleModal();
  });
  $('staff-schedule-overlay')?.addEventListener('click', (e) => {
    if (e.target === $('staff-schedule-overlay')) closeStaffScheduleModal();
  });
  $('save-staff-working-hours-btn')?.addEventListener('click', async () => {
    if (!_staffScheduleTargetId) return;
    const payload = collectWorkingHoursPayload($('staff-working-hours-table'));
    const { ok, data } = await apiCall(`/admin/staff/${_staffScheduleTargetId}/working-hours`, {
      method: 'PUT',
      body: JSON.stringify({ working_hours: payload }),
    });
    if (!ok || !data.success) {
      showToast(data.message || 'Kaydedilemedi', 'error');
      return;
    }
    showToast('Çalışma saatleri kaydedildi', 'success');
    Object.keys(_scheduleRangeCache).forEach((k) => delete _scheduleRangeCache[k]);
    await loadStaffSchedule();
  });
  $('add-staff-time-off-btn')?.addEventListener('click', async () => {
    if (!_staffScheduleTargetId) return;
    const timeOffData = await openTimeOffFormModal();
    if (!timeOffData) return;
    const { ok, data } = await apiCall(`/admin/staff/${_staffScheduleTargetId}/time-off`, {
      method: 'POST',
      body: JSON.stringify(timeOffData),
    });
    if (!ok || !data.success) {
      showToast(data.message || 'Eklenemedi', 'error');
      return;
    }
    showToast('İzin eklendi', 'success');
    await loadStaffSchedule();
  });

  // Reports
  $('load-report-btn')?.addEventListener('click', async (e) => {
    e.preventDefault();
    const now = new Date();
    const monthSel = $('report-month');
    const yearSel  = $('report-year');
    if (monthSel && !monthSel.value) monthSel.value = String(now.getMonth() + 1);
    if (yearSel  && !yearSel.value)  yearSel.value  = String(now.getFullYear());
    await loadIncomeReport();
  });

  // Manuel ayarlama ekle — modal aç
  $('add-adjustment-btn')?.addEventListener('click', () => {
    // Bugünün tarihini otomatik set et
    const dateInput = $('adjustment-date');
    if (dateInput && !dateInput.value) {
      dateInput.value = new Date().toISOString().split('T')[0];
    }
    const overlay = $('adjustment-modal-overlay');
    if (overlay) overlay.style.display = 'flex';
  });

  $('close-adjustment-modal-btn')?.addEventListener('click', () => {
    const overlay = $('adjustment-modal-overlay');
    if (overlay) overlay.style.display = 'none';
  });

  $('adjustment-modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === $('adjustment-modal-overlay')) {
      $('adjustment-modal-overlay').style.display = 'none';
    }
  });

  // Adjustment form submit
  $('adjustment-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitAdjustment();
    $('adjustment-modal-overlay').style.display = 'none';
  });

  // Schedule save
  $('save-working-hours-btn')?.addEventListener('click', async () => {
    if (!hasStudioAccess()) {
      showToast('Çalışma saatlerini düzenleme yetkiniz yok', 'error');
      return;
    }
    const payload = collectWorkingHoursPayload($('working-hours-table'));
    const { ok, data } = await apiCall('/admin/working-hours', {
      method: 'PUT',
      body: JSON.stringify({ working_hours: payload }),
    });
    if (!ok || !data.success) {
      showToast(data.message || 'Kaydedilemedi', 'error');
      return;
    }
    showToast('Kaydedildi', 'success');
    const notice = $('working-hours-notice');
    if (notice) notice.style.display = 'none';
    await loadSchedule();
  });

  $('add-time-off-btn')?.addEventListener('click', async () => {
    const timeOffData = await openTimeOffFormModal();
    if (!timeOffData) return;
    const { ok, data } = await apiCall('/admin/time-off', {
      method: 'POST',
      body: JSON.stringify(timeOffData),
    });
    if (!ok || !data.success) {
      showToast(data.message || 'Eklenemedi', 'error');
      return;
    }
    showToast('İzin eklendi', 'success');
    await loadSchedule();
  });

  // Add staff (super admin)
  $('add-staff-btn')?.addEventListener('click', async () => {
    openStaffModal({ mode: 'create' });
  });

  // Nav
  $('open-manual-appointment-btn-dash')?.addEventListener('click', openManualAppointmentModal);
  $('open-manual-appointment-btn-appt')?.addEventListener('click', openManualAppointmentModal);
  $('nav-manual-appointment')?.addEventListener('click', (e) => {
    e.preventDefault();
    document.querySelectorAll('.nav-item').forEach((i) => i.classList.remove('active'));
    e.currentTarget.classList.add('active');
    openManualAppointmentModal();
  });
  $('close-manual-appointment-btn')?.addEventListener('click', closeManualAppointmentModal);
  $('cancel-manual-appointment-btn')?.addEventListener('click', closeManualAppointmentModal);
  $('manual-appointment-overlay')?.addEventListener('click', (e) => {
    if (e.target === $('manual-appointment-overlay')) closeManualAppointmentModal();
  });
  $('manual-appointment-form')?.addEventListener('submit', submitManualAppointment);
  ['manual-appt-name', 'manual-appt-surname'].forEach((id) => {
    $(id)?.addEventListener('blur', (e) => {
      e.target.value = formatPersonName(e.target.value);
    });
  });
  $('manual-appt-date-btn')?.addEventListener('click', () => manualApptDatePicker?.open());
  ['manual-appt-duration', 'manual-appt-staff'].forEach((id) => {
    $(id)?.addEventListener('change', loadManualAppointmentTimeSlots);
  });

  document.querySelectorAll('.nav-item').forEach((item) => {
    if (item.id === 'nav-manual-appointment') return;
    item.addEventListener('click', async (e) => {
      e.preventDefault();
      const page = item.getAttribute('data-page');
      showSection(page);
      if (page === 'dashboard') await loadDashboard();
      if (page === 'appointments') await loadAppointments();
      if (page === 'pending') await loadPending();
      if (page === 'my-tattoo-requests' || page === 'undecided-requests' || page === 'preconsult-requests' || page === 'offered') {
        if (!canAccessTattooRequests()) {
          showToast('Bu sayfaya erişim yetkiniz yok', 'error');
          showSection('dashboard');
          await loadDashboard();
          return;
        }
      }
      if (page === 'my-tattoo-requests') await loadMyTattooRequests();
      if (page === 'undecided-requests') await loadUndecidedRequests();
      if (page === 'preconsult-requests') await loadPreconsultRequests();
      if (page === 'all-tattoo-requests') {
        if (getLoggedInStaff()?.role !== 'super_admin') {
          showToast('Bu sayfaya erişim yetkiniz yok', 'error');
          showSection('dashboard');
          await loadDashboard();
          return;
        }
        await loadAllTattooRequests();
      }
      if (page === 'offered') await loadOfferedRequests();
      if (page === 'staff') {
        if (!hasStudioAccess()) {
          showToast('Bu sayfaya erişim yetkiniz yok', 'error');
          showSection('dashboard');
          await loadDashboard();
          return;
        }
        await loadStaff();
      }
      if (page === 'schedule') {
        if (!hasStudioAccess()) {
          showToast('Bu sayfaya erişim yetkiniz yok', 'error');
          showSection('dashboard');
          await loadDashboard();
          return;
        }
        await loadSchedule();
      }

      // Degraded/disabled sections in tattoo demo build
      if (page === 'reports') {
        if (!canAccessIncome()) {
          showToast('Bu sayfaya erişim yetkiniz yok', 'error');
          showSection('dashboard');
          await loadDashboard();
          return;
        }
        // Gelir raporuna girildiğinde her zaman mevcut ay/yılı seç
        const now = new Date();
        const monthSel = $('report-month');
        const yearSel  = $('report-year');
        if (monthSel) monthSel.value = String(now.getMonth() + 1);
        if (yearSel)  yearSel.value  = String(now.getFullYear());
        await loadIncomeReport();
      }
      if (page === 'api-settings') await loadWapioSettingsPage();
      if (page === 'google-calendar') {
        if (!hasStudioAccess()) {
          showToast('Bu sayfaya erişim yetkiniz yok', 'error');
          showSection('dashboard');
          await loadDashboard();
          return;
        }
        await loadGoogleCalendarSettings();
      }
      if (page === 'all-appointments') await loadAllAppointments();
      if (page === 'past-appointments') await loadPastAppointments();
    });
  });

  $('save-wapio-settings-btn')?.addEventListener('click', saveWapioSettings);
  $('gcal-save-btn')?.addEventListener('click', saveGoogleCalendarSettings);
  $('gcal-test-btn')?.addEventListener('click', testGoogleCalendarSettings);
  $('gcal-copy-email-btn')?.addEventListener('click', copyGcalServiceEmail);
  $('gcal-calendar-select')?.addEventListener('change', (e) => {
    const val = (e.target.value || '').trim();
    if (val && $('gcal-calendar-id')) $('gcal-calendar-id').value = val;
  });
  $('wapio-welcome-enabled')?.addEventListener('change', async () => {
    const enabled = !!$('wapio-welcome-enabled')?.checked;
    const { ok, data } = await apiCall('/admin/evolution-settings', {
      method: 'PUT',
      body: JSON.stringify({ welcome_message_enabled: enabled }),
    });
    const saved =
      ok && data.success && data.settings?.welcome_message_enabled !== undefined
        ? !!data.settings.welcome_message_enabled
        : enabled;
    if (ok && data.success) {
      if ($('wapio-welcome-enabled')) $('wapio-welcome-enabled').checked = saved;
      showToast(
        saved ? 'Karşılama mesajı açıldı (webhook senkron)' : 'Karşılama mesajı kapatıldı (webhook senkron)',
        'success',
      );
    } else {
      showToast(data?.message || 'Ayar kaydedilemedi', 'error');
      if ($('wapio-welcome-enabled')) $('wapio-welcome-enabled').checked = !enabled;
    }
  });
  $('wapio-otp-keyboard-enabled')?.addEventListener('change', async () => {
    const enabled = !!$('wapio-otp-keyboard-enabled')?.checked;
    const { ok, data } = await apiCall('/admin/evolution-settings', {
      method: 'PUT',
      body: JSON.stringify({ otp_keyboard_hint_enabled: enabled }),
    });
    const saved =
      ok && data.success && data.settings?.otp_keyboard_hint_enabled !== undefined
        ? !!data.settings.otp_keyboard_hint_enabled
        : enabled;
    if (ok && data.success) {
      if ($('wapio-otp-keyboard-enabled')) $('wapio-otp-keyboard-enabled').checked = saved;
      showToast(
        saved
          ? 'Doğrulama kodu klavye formatı açık'
          : 'Doğrulama kodu eski mesaj formatına döndü',
        'success',
      );
    } else {
      showToast(data?.message || 'Ayar kaydedilemedi', 'error');
      if ($('wapio-otp-keyboard-enabled')) $('wapio-otp-keyboard-enabled').checked = !enabled;
    }
  });
  $('wapio-compat-check-btn')?.addEventListener('click', runWapioCompatCheck);
  $('wapio-create-device-btn')?.addEventListener('click', wapioCreateDevice);
  $('wapio-get-qr-btn')?.addEventListener('click', wapioGetQr);
  $('wapio-session-status-btn')?.addEventListener('click', wapioCheckSessionStatus);
  $('wapio-save-webhook-btn')?.addEventListener('click', wapioSaveWebhook);

  $('refresh-my-tattoo-requests-btn')?.addEventListener('click', loadMyTattooRequests);
  $('tattoo-ref-search-btn')?.addEventListener('click', loadMyTattooRequests);
  $('tattoo-ref-search')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadMyTattooRequests();
  });
  $('refresh-undecided-requests-btn')?.addEventListener('click', loadUndecidedRequests);
  $('undecided-ref-search-btn')?.addEventListener('click', loadUndecidedRequests);
  $('undecided-ref-search')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadUndecidedRequests();
  });
  $('refresh-preconsult-requests-btn')?.addEventListener('click', loadPreconsultRequests);
  $('preconsult-ref-search-btn')?.addEventListener('click', loadPreconsultRequests);
  $('preconsult-ref-search')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadPreconsultRequests();
  });
  $('refresh-all-tattoo-requests-btn')?.addEventListener('click', loadAllTattooRequests);
  $('all-tattoo-ref-search-btn')?.addEventListener('click', loadAllTattooRequests);
  $('all-tattoo-ref-search')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadAllTattooRequests();
  });
  $('offered-ref-search-btn')?.addEventListener('click', loadOfferedRequests);
  $('offered-ref-search')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadOfferedRequests();
  });
  $('refresh-offered-btn')?.addEventListener('click', loadOfferedRequests);

  // View toggle — Randevular
  setupViewToggle('view-list-btn', 'view-table-btn',
    'appointments-list-view', 'appointments-table-view', 'all-appointments-table');

  // View toggle — Tüm Randevular (super admin)
  setupViewToggle('all-view-list-btn', 'all-view-table-btn',
    'all-appointments-list-view', 'all-appointments-table-view', 'all-appointments-table-container');

  // Tüm Randevular filtre butonu
  $('load-all-appointments-btn')?.addEventListener('click', loadAllAppointments);
  $('reset-all-appointments-btn')?.addEventListener('click', () => {
    const s = $('all-appointments-start-date'); if (s) s.value = '';
    const e = $('all-appointments-end-date');   if (e) e.value = '';
    const sf = $('all-appointments-staff-filter'); if (sf) sf.value = '';
    Object.keys(_scheduleRangeCache).forEach((k) => delete _scheduleRangeCache[k]);
    loadAllAppointments();
  });
  $('all-appointments-staff-filter')?.addEventListener('change', () => {
    Object.keys(_scheduleRangeCache).forEach((k) => delete _scheduleRangeCache[k]);
    const tableView = $('all-appointments-table-view');
    if (tableView && tableView.style.display !== 'none') {
      void renderAppointmentsTable(_allAppointmentsData, 'all-appointments-table-container');
    }
  });

  // Geçmiş Randevular filtre butonları
  $('load-past-appointments-btn')?.addEventListener('click', loadPastAppointments);
  $('reset-past-appointments-btn')?.addEventListener('click', () => {
    const s = $('past-appointments-start-date'); if (s) s.value = '';
    const e = $('past-appointments-end-date');   if (e) e.value = '';
    const sf = $('past-appointments-staff-filter'); if (sf) sf.value = '';
    loadPastAppointments();
  });

  // Giriş ekranı: tarayıcı yeniden açılınca login; aynı oturumda F5 ise panele devam
  const token = getAdminToken();
  const staffRaw = getAdminStaffRaw();
  const sessionActive = sessionStorage.getItem(ADMIN_SESSION_ACTIVE_KEY) === '1';

  if (sessionActive && token && staffRaw) {
    try {
      const staff = JSON.parse(staffRaw);
      const { ok, status } = await validateStoredAdminSession();
      if (ok && status !== 401) {
        await enterAdminDashboard(staff);
        return;
      }
      clearAdminSession({ keepRememberPrefs: true });
    } catch {
      clearAdminSession({ keepRememberPrefs: true });
    }
  }

  updateLoginModeUI();
  setPage(false);

  $('login-quick-btn')?.addEventListener('click', quickLogin);
  $('login-switch-account-btn')?.addEventListener('click', switchLoginAccount);
});

// =========================
// MOBILE SIDEBAR (hamburger)
// =========================

function toggleSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = $('sidebar-overlay');
  const hamburger = $('hamburger-btn');
  if (!sidebar || !overlay || !hamburger) return;
  sidebar.classList.toggle('active');
  overlay.classList.toggle('active');
  hamburger.classList.toggle('active');
}

function setGcalStatus(kind, label) {
  const wrap = $('gcal-connection-status');
  const labelEl = $('gcal-status-label');
  if (labelEl) labelEl.textContent = label;
  if (!wrap) return;
  wrap.classList.remove(
    'wapio-connection-status--unknown',
    'wapio-connection-status--connected',
    'wapio-connection-status--pending',
    'wapio-connection-status--error',
    'wapio-connection-status--unconfigured'
  );
  const map = { ok: 'connected', err: 'error', warn: 'pending', unknown: 'unknown' };
  wrap.classList.add(`wapio-connection-status--${map[kind] || 'unknown'}`);
}

function fillGcalCalendarSelect(calendars, selectedId) {
  const sel = $('gcal-calendar-select');
  const group = $('gcal-list-group');
  if (!sel || !group) return;
  const list = Array.isArray(calendars) ? calendars : [];
  if (list.length === 0) {
    group.style.display = 'none';
    return;
  }
  group.style.display = '';
  sel.innerHTML = '<option value="">— Seçin veya aşağıya yazın —</option>' +
    list.map((c) => {
      const id = escapeHtml(c.id || '');
      const name = escapeHtml(c.summary || c.id || '');
      const chosen = (c.id || '') === selectedId ? ' selected' : '';
      return `<option value="${id}"${chosen}>${name}</option>`;
    }).join('');
}

function applyGcalSettings(s, calendars) {
  if ($('gcal-enabled')) $('gcal-enabled').checked = !!s.enabled;
  if ($('gcal-sa-email')) $('gcal-sa-email').value = s.service_account_email || '';
  if ($('gcal-calendar-id')) $('gcal-calendar-id').value = s.calendar_id || '';
  fillGcalCalendarSelect(calendars, s.calendar_id || '');
  const sum = $('gcal-current-summary');
  if (sum) {
    if (s.connected && s.calendar_summary) {
      sum.hidden = false;
      sum.textContent = `Aktif takvim: ${s.calendar_summary}`;
    } else {
      sum.hidden = true;
      sum.textContent = '';
    }
  }
  if (!s.credentials_ok) {
    setGcalStatus('err', 'Sunucuda Google kimlik dosyası yok');
  } else if (s.sync_active && s.connected) {
    setGcalStatus('ok', s.calendar_summary ? `Bağlı: ${s.calendar_summary}` : 'Bağlı');
  } else if (s.enabled && s.calendar_id) {
    setGcalStatus('warn', s.probe_message || 'Takvime erişilemiyor — paylaşımı kontrol edin');
  } else if (s.enabled) {
    setGcalStatus('warn', 'Takvim kimliği girilmedi');
  } else {
    setGcalStatus('unknown', 'Senkron kapalı');
  }
}

async function loadGoogleCalendarSettings() {
  setGcalStatus('unknown', 'Kontrol ediliyor…');
  const res = await apiCall('/admin/google-calendar-settings');
  if (!res.ok || !res.data?.success) {
    setGcalStatus('err', res.data?.message || 'Ayarlar yüklenemedi');
    return;
  }
  applyGcalSettings(res.data.settings || {}, res.data.calendars || []);
}

async function saveGoogleCalendarSettings() {
  const payload = {
    enabled: !!$('gcal-enabled')?.checked,
    calendar_id: ($('gcal-calendar-id')?.value || '').trim(),
  };
  const res = await apiCall('/admin/google-calendar-settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.data?.success) {
    showToast(res.data?.message || 'Kaydedilemedi', 'error');
    return;
  }
  showToast(res.data.message || 'Kaydedildi', 'success');
  await loadGoogleCalendarSettings();
}

async function testGoogleCalendarSettings() {
  const calendarId = ($('gcal-calendar-id')?.value || '').trim();
  const btn = $('gcal-test-btn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deneniyor…';
  }
  const res = await apiCall('/admin/google-calendar-settings/test', {
    method: 'POST',
    body: JSON.stringify({ calendar_id: calendarId }),
  });
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-stethoscope"></i> Bağlantıyı dene';
  }
  if (res.ok && res.data?.success) {
    const name = res.data.calendar?.summary || calendarId;
    showToast(`Bağlantı başarılı: ${name}`, 'success');
    setGcalStatus('ok', `Bağlı: ${name}`);
    const sum = $('gcal-current-summary');
    if (sum) {
      sum.hidden = false;
      sum.textContent = `Aktif takvim: ${name}`;
    }
  } else {
    showToast(res.data?.message || 'Takvime erişilemedi', 'error');
    setGcalStatus('warn', res.data?.message || 'Takvime erişilemedi');
  }
}

async function copyGcalServiceEmail() {
  const email = ($('gcal-sa-email')?.value || '').trim();
  if (!email) {
    showToast('Kopyalanacak e-posta yok', 'error');
    return;
  }
  try {
    await navigator.clipboard.writeText(email);
    showToast('E-posta kopyalandı', 'success');
  } catch {
    showToast('Kopyalanamadı', 'error');
  }
}

$('hamburger-btn')?.addEventListener('click', (e) => {
  e.preventDefault();
  toggleSidebar();
});

$('sidebar-overlay')?.addEventListener('click', (e) => {
  e.preventDefault();
  toggleSidebar();
});

