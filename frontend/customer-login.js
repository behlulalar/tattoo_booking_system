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

function setupOtpBoxes(containerEl, hiddenInputEl) {
  return setupOtpInput(containerEl, hiddenInputEl);
}

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

function parseTrMobile(value) {
  let d = String(value || '').replace(/\D/g, '');
  if (d.startsWith('90')) d = d.slice(2);
  if (d.startsWith('0')) d = d.replace(/^0+/, '');
  return /^5\d{9}$/.test(d) ? d : '';
}

function bindTrMobileInput(el) {
  if (!el || el.dataset.trMobileBound === '1') return;
  el.dataset.trMobileBound = '1';
  el.setAttribute('inputmode', 'numeric');
  el.setAttribute('maxlength', '10');
  el.addEventListener('input', () => {
    const parsed = parseTrMobile(el.value);
    if (parsed) {
      el.value = parsed;
      return;
    }
    let d = String(el.value || '').replace(/\D/g, '');
    if (d.startsWith('90')) d = d.slice(2);
    if (d.startsWith('0')) d = d.replace(/^0+/, '');
    el.value = d.slice(0, 10);
  });
}

function showErr(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

(function initCustomerLoginPage() {
  const loginStep = document.getElementById('customer-login-step');
  const verifyStep = document.getElementById('customer-verify-step');
  const sessionStep = document.getElementById('customer-session-step');
  const loginForm = document.getElementById('customer-login-form');
  const loginPhone = document.getElementById('customer-login-phone');
  const loginError = document.getElementById('customer-login-error');
  const verifyForm = document.getElementById('customer-verify-form');
  const codeInput = document.getElementById('customer-code');
  const customerOtpApi = setupOtpBoxes(
    document.getElementById('customer-verify-otp-boxes'),
    codeInput
  );
  const verifyError = document.getElementById('customer-verify-error');
  const timerSpan = document.getElementById('customer-timer');
  const resendBtn = document.getElementById('customer-resend-btn');
  const verifyBackBtn = document.getElementById('customer-verify-back-btn');

  let phone = '';
  let timerInterval = null;

  function setKeyboardInset() {
    const vv = window.visualViewport;
    if (!vv) return;
    const covered = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    document.documentElement.style.setProperty('--keyboard-inset', `${covered}px`);
  }

  function scrollActionIntoView(form) {
    const action = form?.querySelector('button[type="submit"], .customer-login-submit');
    if (!action) return;
    requestAnimationFrame(() => {
      action.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }

  window.visualViewport?.addEventListener('resize', () => {
    setKeyboardInset();
    const openForm = verifyStep?.hidden === false ? verifyForm : loginForm;
    scrollActionIntoView(openForm);
  });
  window.visualViewport?.addEventListener('scroll', setKeyboardInset);

  const hasSession = !!(localStorage.getItem('customerToken') && localStorage.getItem('customerData'));

  function showLoginStep() {
    document.body.classList.remove('is-verify-open');
    if (sessionStep) sessionStep.hidden = true;
    verifyStep.hidden = true;
    loginStep.hidden = false;
    if (verifyForm) verifyForm.reset();
    customerOtpApi.clearOtp();
    showErr(verifyError, '');
    clearInterval(timerInterval);
    loginPhone?.focus({ preventScroll: true });
    setTimeout(() => scrollActionIntoView(loginForm), 280);
  }

  function showVerifyStep() {
    document.body.classList.add('is-verify-open');
    if (sessionStep) sessionStep.hidden = true;
    loginStep.hidden = true;
    verifyStep.hidden = false;
    customerOtpApi.applyCode('123456');
    customerOtpApi.focusFirst();
    startTimer(120);
    setTimeout(() => scrollActionIntoView(verifyForm), 320);
  }

  function startTimer(seconds) {
    clearInterval(timerInterval);
    let remaining = seconds;
    if (resendBtn) resendBtn.style.display = 'none';
    updateTimer(remaining);
    timerInterval = setInterval(() => {
      remaining--;
      updateTimer(remaining);
      if (remaining <= 0) {
        clearInterval(timerInterval);
        if (timerSpan) timerSpan.textContent = 'Süre doldu!';
        if (resendBtn) resendBtn.style.display = 'inline-block';
      }
    }, 1000);
  }

  function updateTimer(s) {
    if (!timerSpan) return;
    const m = Math.floor(s / 60);
    timerSpan.textContent = `${m}:${String(s % 60).padStart(2, '0')}`;
  }

  if (hasSession && sessionStep) {
    loginStep.hidden = true;
    verifyStep.hidden = true;
    sessionStep.hidden = false;
  }

  document.getElementById('customer-session-continue')?.addEventListener('click', () => {
    window.location.replace('customer-panel.html');
  });
  document.getElementById('customer-session-switch')?.addEventListener('click', () => {
    localStorage.removeItem('customerToken');
    localStorage.removeItem('customerData');
    showLoginStep();
  });

  verifyBackBtn?.addEventListener('click', showLoginStep);

  bindTrMobileInput(loginPhone);

  loginPhone?.addEventListener('focus', () => setTimeout(() => scrollActionIntoView(loginForm), 280));

  loginForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const value = parseTrMobile(loginPhone?.value);
    if (!value) {
      showErr(loginError, 'Geçerli bir cep numarası girin (5XX XXX XX XX). Başında 0 olmasın.');
      return;
    }
    if (loginPhone) loginPhone.value = value;
    showErr(loginError, '');
    const { ok, data } = await api('/api/send-code', {
      method: 'POST',
      body: JSON.stringify({ phone: value }),
    });
    if (!ok || !data.success) {
      showErr(loginError, data.message || 'Kod gönderilemedi');
      return;
    }
    phone = value;
    showVerifyStep();
  });

  verifyForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = customerOtpApi.getCode();
    if (!code || code.length !== 6) {
      showErr(verifyError, 'Lütfen 6 haneli kodu girin.');
      return;
    }
    showErr(verifyError, '');
    const { ok, data } = await api('/api/customer/login', {
      method: 'POST',
      body: JSON.stringify({ phone, code }),
    });
    if (!ok || !data.success) {
      showErr(verifyError, data.message || 'Doğrulama başarısız');
      return;
    }
    clearInterval(timerInterval);
    localStorage.setItem('customerToken', data.token);
    localStorage.setItem('customerData', JSON.stringify(data.customer));
    document.body.classList.add('is-redirecting');
    const submitBtn = verifyForm?.querySelector('.customer-login-submit');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Yönlendiriliyor...';
    }
    window.location.replace('customer-panel.html');
  });

  document.getElementById('customer-verify-paste-btn')?.addEventListener('click', async () => {
    const ok = await customerOtpApi.pasteFromClipboard();
    if (!ok) {
      showErr(verifyError, 'Panoda 6 haneli kod yok. WhatsApp mesajından kodu kopyalayın.');
      return;
    }
    showErr(verifyError, '');
  });

  resendBtn?.addEventListener('click', async () => {
    const { ok, data } = await api('/api/send-code', {
      method: 'POST',
      body: JSON.stringify({ phone }),
    });
    if (!ok || !data.success) {
      showErr(verifyError, data.message || 'Kod gönderilemedi');
      return;
    }
    customerOtpApi.applyCode('123456');
    customerOtpApi.focusFirst();
    startTimer(120);
  });

  if (!hasSession && window.matchMedia('(min-width: 769px)').matches) {
    loginPhone?.focus({ preventScroll: true });
  }
})();
