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

function showErr(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

(function initCustomerLoginPage() {
  if (localStorage.getItem('customerToken') && localStorage.getItem('customerData')) {
    window.location.replace('customer-panel.html');
    return;
  }

  const loginStep = document.getElementById('customer-login-step');
  const verifyStep = document.getElementById('customer-verify-step');
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

  function showLoginStep() {
    verifyStep.hidden = true;
    loginStep.hidden = false;
    if (verifyForm) verifyForm.reset();
    customerOtpApi.clearOtp();
    showErr(verifyError, '');
    clearInterval(timerInterval);
  }

  function showVerifyStep() {
    loginStep.hidden = true;
    verifyStep.hidden = false;
    customerOtpApi.clearOtp();
    customerOtpApi.focusFirst();
    startTimer(120);
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

  verifyBackBtn?.addEventListener('click', showLoginStep);

  loginForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const value = (loginPhone?.value || '').trim();
    if (!/^[0-9]{10}$/.test(value)) {
      showErr(loginError, 'Lütfen geçerli bir telefon numarası girin.');
      return;
    }
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
    customerOtpApi.clearOtp();
    customerOtpApi.focusFirst();
    startTimer(120);
  });

  loginPhone?.focus();
})();
