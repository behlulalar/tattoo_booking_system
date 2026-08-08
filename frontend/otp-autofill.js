/**
 * OTP alanı — mobil klavyede tek tıkla kod önerisi (iOS/Android).
 * autocomplete="one-time-code" + Web OTP API + autofill senkronu.
 */
function setupOtpInput(containerEl, hiddenInputEl) {
  if (!containerEl) {
    return {
      clearOtp: () => {},
      focusFirst: () => {},
      stopAutofill: () => {},
      applyCode: () => {},
      pasteFromClipboard: async () => false,
      getCode: () => '',
    };
  }

  const otpInput = containerEl.querySelector('.otp-field-visible, .otp-field');
  const cells = [...containerEl.querySelectorAll('.otp-cell')];
  if (!otpInput) {
    return {
      clearOtp: () => {},
      focusFirst: () => {},
      stopAutofill: () => {},
      applyCode: () => {},
      pasteFromClipboard: async () => false,
      getCode: () => '',
    };
  }

  let autofillAbort = null;
  let autofillPollTimer = null;
  let autofillPollStopTimer = null;

  const render = (raw) => {
    const value = String(raw || '').replace(/\D/g, '').slice(0, 6);
    otpInput.value = value;
    if (hiddenInputEl) hiddenInputEl.value = value;
    if (cells.length === 6) {
      cells.forEach((cell, i) => {
        cell.textContent = value[i] || '';
        cell.classList.toggle('filled', !!value[i]);
        cell.classList.toggle('active', i === value.length && value.length < 6);
      });
    }
    containerEl.classList.toggle('is-complete', value.length === 6);
    return value;
  };

  const syncFromField = () => render(otpInput.value);

  const applyCode = (raw) => render(raw);

  const pasteFromClipboard = async () => {
    if (!navigator.clipboard?.readText) return false;
    try {
      const text = await navigator.clipboard.readText();
      const digits = String(text || '').replace(/\D/g, '');
      const match = digits.match(/\d{6}/);
      if (!match) return false;
      applyCode(match[0]);
      return true;
    } catch {
      return false;
    }
  };

  const stopAutofill = () => {
    autofillAbort?.abort();
    autofillAbort = null;
    if (autofillPollTimer) {
      clearInterval(autofillPollTimer);
      autofillPollTimer = null;
    }
    if (autofillPollStopTimer) {
      clearTimeout(autofillPollStopTimer);
      autofillPollStopTimer = null;
    }
  };

  const startAutofill = () => {
    stopAutofill();
    autofillAbort = new AbortController();
    const { signal } = autofillAbort;

    if (window.OTPCredential && navigator.credentials?.get) {
      navigator.credentials
        .get({ otp: { transport: ['sms'] }, signal })
        .then((cred) => {
          if (cred?.code) render(cred.code);
        })
        .catch(() => {});
    }

    let lastVal = otpInput.value;
    autofillPollTimer = setInterval(() => {
      if (otpInput.value !== lastVal) {
        lastVal = otpInput.value;
        syncFromField();
      }
    }, 200);

    autofillPollStopTimer = setTimeout(stopAutofill, 180000);
  };

  const clearOtp = () => {
    render('');
    containerEl.classList.remove('is-focused');
    stopAutofill();
  };

  const focusFirst = () => {
    otpInput.focus({ preventScroll: true });
    containerEl.classList.add('is-focused');
    startAutofill();
  };

  otpInput.addEventListener('input', syncFromField);
  otpInput.addEventListener('change', syncFromField);
  otpInput.addEventListener('keyup', syncFromField);

  otpInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && otpInput.value.length === 6) {
      containerEl.closest('form')?.requestSubmit();
    }
  });

  otpInput.addEventListener('paste', (e) => {
    e.preventDefault();
    render((e.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, 6));
  });

  otpInput.addEventListener('focus', () => {
    containerEl.classList.add('is-focused');
    startAutofill();
  });

  otpInput.addEventListener('blur', () => containerEl.classList.remove('is-focused'));

  otpInput.addEventListener('animationstart', (e) => {
    if (e.animationName === 'otp-autofill') syncFromField();
  });

  return {
    clearOtp,
    focusFirst,
    stopAutofill,
    applyCode,
    pasteFromClipboard,
    getCode: () => (otpInput.value || hiddenInputEl?.value || '').replace(/\D/g, '').slice(0, 6),
  };
}
