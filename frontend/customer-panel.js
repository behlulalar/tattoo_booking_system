// =============================================
// CUSTOMER PANEL - JAVASCRIPT
// Roof Tattoo Gallery
// =============================================

console.log('customer-panel.js YÜKLENDI');

// API Base URL — local dev'de backend port 3000'de çalışır
function getApiBase() {
    const stored = localStorage.getItem('API_BASE_URL');
    if (stored) return stored.replace(/\/$/, '') + '/api';
    const isLocal =
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1';
    const isStaticPort = window.location.port && window.location.port !== '3000';
    if (isLocal && isStaticPort) return 'http://127.0.0.1:3000/api';
    return '/api';
}
const API_BASE = getApiBase();

// State
let customer = null;
let currentFilter = 'upcoming';
let appointments = [];
let currentAppointmentIdForCancel = null;

// =============================================
// INITIALIZATION
// =============================================

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    checkAuth();
    setupEventListeners();
});

// =============================================
// THEME MANAGEMENT
// =============================================

function initTheme() {
    const savedTheme = localStorage.getItem('customerTheme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-theme');
        updateThemeIcon(true);
    }
}

function toggleTheme() {
    console.log('toggleTheme çağrıldı');
    const isDark = document.body.classList.toggle('dark-theme');
    console.log('Dark mode:', isDark);
    localStorage.setItem('customerTheme', isDark ? 'dark' : 'light');
    updateThemeIcon(isDark);
}

function updateThemeIcon(isDark) {
    const icon = document.querySelector('#theme-toggle i');
    if (icon) {
        icon.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    }
}

function checkAuth() {
    const token = localStorage.getItem('customerToken');
    const customerData = localStorage.getItem('customerData');

    if (!token || !customerData) {
        // Redirect to main page
        window.location.href = 'customer-login.html';
        return;
    }

    customer = JSON.parse(customerData);
    displayCustomerInfo();
    loadAppointments('upcoming');
    loadLoyaltySummary();
}

function displayCustomerInfo() {
    const fullName = `${customer.name} ${customer.surname}`;
    document.getElementById('user-name').textContent = fullName;
    document.getElementById('user-phone').textContent = `0${customer.phone}`;
    document.getElementById('profile-name').textContent = fullName;
    document.getElementById('profile-phone').textContent = `0${customer.phone}`;
}

// =============================================
// EVENT LISTENERS
// =============================================

function setupEventListeners() {
    try {
        // New Appointment Button
        document.getElementById('new-appointment-btn').addEventListener('click', () => {
            window.location.href = 'index.html';
        });

        // Navigation
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const section = item.dataset.section;
                navigateTo(section);
            });
        });

        // Logout
        document.getElementById('logout-btn').addEventListener('click', handleLogout);

        const redeemBtn = document.getElementById('loyalty-redeem-btn');
        if (redeemBtn) {
            redeemBtn.addEventListener('click', redeemLoyaltyDiscount);
        }

        // Mobile menu
        const mobileMenuBtn = document.getElementById('mobile-menu-btn');
        if (mobileMenuBtn) {
            mobileMenuBtn.addEventListener('click', toggleMobileSidebar);
        }
        const sidebarOverlay = document.getElementById('sidebar-overlay');
        if (sidebarOverlay) {
            sidebarOverlay.addEventListener('click', closeMobileSidebar);
        }

        // Theme toggle
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', toggleTheme);
            console.log('Theme toggle listener eklendi');
        } else {
            console.error('theme-toggle elementi bulunamadı!');
        }

        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // Get parent section to know which section's filters we're dealing with
                const section = btn.closest('.content-section').id;

                // Remove active from siblings
                btn.parentElement.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const filter = btn.dataset.filter;

                if (section === 'section-appointments') {
                    loadAppointments(filter);
                } else if (section === 'section-history') {
                    loadHistory(filter);
                }
            });
        });
    } catch (e) {
        console.error('setupEventListeners hatası:', e);
    }
}

function toggleMobileSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const open = !sidebar.classList.contains('active');
    sidebar.classList.toggle('active', open);
    if (overlay) overlay.classList.toggle('active', open);
}

function closeMobileSidebar() {
    document.querySelector('.sidebar')?.classList.remove('active');
    document.getElementById('sidebar-overlay')?.classList.remove('active');
}

function navigateTo(section) {
    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    document.querySelector(`[data-section="${section}"]`).classList.add('active');

    // Hide all sections
    document.querySelectorAll('.content-section').forEach(sec => {
        sec.classList.remove('active');
    });

    // Show selected section
    document.getElementById(`section-${section}`).classList.add('active');

    // Update header title
    const titles = {
        'appointments': 'Randevularım',
        'requests': 'Randevu Talepleri',
        'history': 'Geçmiş Randevular',
        'profile': 'Profil'
    };
    document.getElementById('section-title').textContent = titles[section];

    // Load data if needed
    if (section === 'appointments') {
        loadAppointments(currentFilter);
    } else if (section === 'requests') {
        loadRequests();
    } else if (section === 'history') {
        loadHistory('completed');
    } else if (section === 'profile') {
        loadLoyaltySummary();
    }

    closeMobileSidebar();
}

function handleLogout() {
    document.getElementById('logout-modal-overlay').classList.add('show');
    document.getElementById('confirm-logout-btn').onclick = confirmLogout;
}

function closeLogoutModal() {
    document.getElementById('logout-modal-overlay').classList.remove('show');
}

function confirmLogout() {
    localStorage.removeItem('customerToken');
    localStorage.removeItem('customerData');
    window.location.href = 'index.html';
}

// =============================================
// API CALLS
// =============================================

async function apiCall(endpoint, options = {}) {
    const token = localStorage.getItem('customerToken');
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
    };

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers: { ...headers, ...options.headers }
        });

        const data = await response.json();

        if (response.status === 401) {
            // Token expired
            showToast('Oturum süresi doldu. Lütfen tekrar giriş yapın', 'error');
            setTimeout(() => {
                localStorage.removeItem('customerToken');
                localStorage.removeItem('customerData');
                window.location.href = 'customer-login.html';
            }, 2000);
            return null;
        }

        return data;
    } catch (error) {
        console.error('API Error:', error);
        showToast('Bağlantı hatası', 'error');
        return null;
    }
}

// =============================================
// LOAD APPOINTMENTS
// =============================================

async function loadAppointments(filter = 'upcoming') {
    currentFilter = filter;
    const container = document.getElementById('appointments-container');
    container.innerHTML = '<p class="loading-text"><i class="fas fa-spinner fa-spin"></i> Yükleniyor...</p>';

    const data = await apiCall(`/customer/appointments?filter=${filter}`);

    if (data && data.success) {
        appointments = data.appointments;
        renderAppointments(container, appointments);
    } else {
        container.innerHTML = '<p class="empty-message"><i class="fas fa-calendar-times"></i><br>Randevu bulunamadı</p>';
    }
}

async function loadRequests() {
    const container = document.getElementById('requests-container');
    container.innerHTML = '<p class="loading-text"><i class="fas fa-spinner fa-spin"></i> Yükleniyor...</p>';

    const data = await apiCall('/customer/tattoo-requests');

    if (data && data.success) {
        renderRequests(container, data.requests);
    } else {
        container.innerHTML = '<p class="empty-message"><i class="fas fa-inbox"></i><br>Talepler yüklenemedi</p>';
    }
}

async function loadHistory(filter = 'completed') {
    const container = document.getElementById('history-container');
    container.innerHTML = '<p class="loading-text"><i class="fas fa-spinner fa-spin"></i> Yükleniyor...</p>';

    const data = await apiCall(`/customer/appointments?filter=${filter === 'all' ? 'past' : filter}`);

    if (data && data.success) {
        renderHistory(container, data.appointments);
    } else {
        container.innerHTML = '<p class="empty-message"><i class="fas fa-calendar-times"></i><br>Randevu bulunamadı</p>';
    }
}

// =============================================
// RENDER APPOINTMENTS
// =============================================

function renderAppointments(container, appointments) {
    if (!appointments || appointments.length === 0) {
        container.innerHTML = '<p class="empty-message"><i class="fas fa-calendar-times"></i><br>Henüz randevunuz yok</p>';
        return;
    }

    container.innerHTML = appointments.map(apt => {
        if (apt.type === 'slot_selection') {
            return renderSlotSelectionCard(apt);
        }

        const staffName = apt.staff?.name || '—';
        const canCancel = (apt.status === 'pending' || apt.status === 'confirmed') && canCancelAppointment(apt);

        return `
            <div class="appointment-card status-${apt.status}">
                <div class="appointment-header">
                    <div>
                        <div class="appointment-date">
                            <i class="fas fa-calendar-alt"></i>
                            ${apt.date}
                        </div>
                        <div class="appointment-time">
                            <i class="fas fa-clock"></i>
                            ${apt.time}
                        </div>
                    </div>
                    <div class="apt-card-badges">
                        ${appointmentSourceBadgeHtml(apt.source)}
                        <span class="status-badge ${apt.status}">${getStatusText(apt.status)}</span>
                    </div>
                </div>

                <div class="appointment-details">
                    <div class="detail-row">
                        <i class="fas fa-user-tie"></i>
                        <span class="detail-label">Sanatçı</span>
                        <span class="detail-value">${escapeHtml(staffName)}</span>
                    </div>
                    ${apt.tattoo ? `
                    <div class="detail-row">
                        <i class="fas fa-ruler-combined"></i>
                        <span class="detail-label">Büyüklük</span>
                        <span class="detail-value">${escapeHtml(apt.tattoo.size || '—')}</span>
                    </div>
                    <div class="detail-row">
                        <i class="fas fa-map-marker-alt"></i>
                        <span class="detail-label">Bölge</span>
                        <span class="detail-value">${escapeHtml(apt.tattoo.body_area || '—')}</span>
                    </div>
                    ` : ''}
                    <div class="detail-row">
                        <i class="fas fa-clock"></i>
                        <span class="detail-label">Süre</span>
                        <span class="detail-value">${apt.duration_minutes} dk</span>
                    </div>
                    <div class="detail-row">
                        <i class="fas fa-tag"></i>
                        <span class="detail-label">Ücret</span>
                        <span class="detail-value">${getPriceText(apt.price)}</span>
                    </div>
                    <div class="detail-row">
                        <i class="fas fa-credit-card"></i>
                        <span class="detail-label">Ödeme</span>
                        <span class="detail-value">${getPaymentText(apt.payment_method)}</span>
                    </div>
                </div>

                ${canCancel ? `
                    <div class="appointment-actions">
                        <button class="action-btn cancel-btn" onclick="openCancelModal(${apt.id})">
                            <i class="fas fa-times"></i> İptal Et
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function renderSlotSelectionCard(apt) {
    const staffName = apt.staff?.name || '—';
    const refLine = apt.reference_number
        ? `<div class="detail-row">
            <i class="fas fa-hashtag"></i>
            <span class="detail-label">Referans</span>
            <span class="detail-value">${escapeHtml(apt.reference_number)}</span>
           </div>`
        : '';
    const expiresLine = apt.expires_at
        ? `<div class="detail-row">
            <i class="fas fa-hourglass-half"></i>
            <span class="detail-label">Link geçerliliği</span>
            <span class="detail-value">${escapeHtml(apt.expires_at)}</span>
           </div>`
        : '';
    const slotUrl = apt.slot_select_url || '#';

    return `
        <div class="appointment-card status-slot_pending">
            <div class="appointment-header">
                <div>
                    <div class="appointment-date">
                        <i class="fas fa-calendar-check"></i>
                        Onaylandı — saat seçin
                    </div>
                    <div class="appointment-time">
                        <i class="fas fa-info-circle"></i>
                        Tarih ve saat seçimi yapılmadı
                    </div>
                </div>
                <span class="status-badge slot_pending">${getStatusText('slot_pending')}</span>
            </div>

            <div class="appointment-details">
                ${refLine}
                <div class="detail-row">
                    <i class="fas fa-user-tie"></i>
                    <span class="detail-label">Sanatçı</span>
                    <span class="detail-value">${escapeHtml(staffName)}</span>
                </div>
                ${apt.tattoo ? `
                <div class="detail-row">
                    <i class="fas fa-palette"></i>
                    <span class="detail-label">Tarz</span>
                    <span class="detail-value">${escapeHtml(apt.tattoo.tattoo_style || '—')}</span>
                </div>
                <div class="detail-row">
                    <i class="fas fa-map-marker-alt"></i>
                    <span class="detail-label">Bölge</span>
                    <span class="detail-value">${escapeHtml(apt.tattoo.body_area || '—')}</span>
                </div>
                ` : ''}
                <div class="detail-row">
                    <i class="fas fa-clock"></i>
                    <span class="detail-label">Süre</span>
                    <span class="detail-value">${apt.duration_minutes} dk</span>
                </div>
                <div class="detail-row">
                    <i class="fas fa-tag"></i>
                    <span class="detail-label">Ücret</span>
                    <span class="detail-value">${getPriceText(apt.price)}</span>
                </div>
                ${expiresLine}
            </div>

            <div class="appointment-actions">
                <a class="action-btn slot-select-btn" href="${escapeHtml(slotUrl)}">
                    <i class="fas fa-link"></i> Saat Seçimi Yap
                </a>
            </div>
        </div>
    `;
}

function renderRequests(container, requests) {
    if (!requests || requests.length === 0) {
        container.innerHTML = '<p class="empty-message"><i class="fas fa-inbox"></i><br>Bekleyen talep yok</p>';
        return;
    }

    container.innerHTML = requests.map(req => {
        const staffName = req.staff?.name || '—';
        const refLine = req.reference_number
            ? `<div class="detail-row">
                <i class="fas fa-hashtag"></i>
                <span class="detail-label">Referans</span>
                <span class="detail-value">${escapeHtml(req.reference_number)}</span>
               </div>`
            : '';

        return `
            <div class="appointment-card status-request_pending request-card">
                <div class="appointment-header">
                    <div>
                        <div class="appointment-date">
                            <i class="fas fa-file-signature"></i>
                            Randevu talebi
                        </div>
                        <div class="appointment-time">
                            <i class="fas fa-calendar-plus"></i>
                            ${escapeHtml(req.created_at || '')}
                        </div>
                    </div>
                    <span class="status-badge request_pending">${escapeHtml(req.status_label || 'Onay bekleniyor')}</span>
                </div>

                <div class="appointment-details">
                    ${refLine}
                    <div class="detail-row">
                        <i class="fas fa-user-tie"></i>
                        <span class="detail-label">Sanatçı</span>
                        <span class="detail-value">${escapeHtml(staffName)}</span>
                    </div>
                    ${req.tattoo_style ? `
                    <div class="detail-row">
                        <i class="fas fa-palette"></i>
                        <span class="detail-label">Tarz</span>
                        <span class="detail-value">${escapeHtml(req.tattoo_style)}</span>
                    </div>
                    ` : ''}
                    ${req.body_area ? `
                    <div class="detail-row">
                        <i class="fas fa-map-marker-alt"></i>
                        <span class="detail-label">Bölge</span>
                        <span class="detail-value">${escapeHtml(req.body_area)}</span>
                    </div>
                    ` : ''}
                    ${req.size ? `
                    <div class="detail-row">
                        <i class="fas fa-ruler-combined"></i>
                        <span class="detail-label">Büyüklük</span>
                        <span class="detail-value">${escapeHtml(req.size)}</span>
                    </div>
                    ` : ''}
                </div>

                <p class="request-wait-note">
                    <i class="fas fa-hourglass-half"></i>
                    Sanatçı talebinizi inceliyor. Onay ve süre belirlendikten sonra saat seçim linki <strong>Randevularım</strong> bölümünde görünecek.
                </p>
            </div>
        `;
    }).join('');
}

function renderHistory(container, appointments) {
    if (!appointments || appointments.length === 0) {
        container.innerHTML = '<p class="empty-message"><i class="fas fa-calendar-times"></i><br>Geçmiş randevu bulunamadı</p>';
        return;
    }

    container.innerHTML = appointments.map(apt => `
            <div class="appointment-card status-${apt.status}">
                <div class="appointment-header">
                    <div>
                        <div class="appointment-date">
                            <i class="fas fa-calendar-alt"></i>
                            ${apt.date}
                        </div>
                        <div class="appointment-time">
                            <i class="fas fa-clock"></i>
                            ${apt.time}
                        </div>
                    </div>
                    <div class="apt-card-badges">
                        ${appointmentSourceBadgeHtml(apt.source)}
                        <span class="status-badge ${apt.status}">${getStatusText(apt.status)}</span>
                    </div>
                </div>

                <div class="appointment-details">
                    <div class="detail-row">
                        <i class="fas fa-user-tie"></i>
                        <span class="detail-label">Sanatçı</span>
                        <span class="detail-value">${escapeHtml(apt.staff?.name || '—')}</span>
                    </div>
                    ${apt.tattoo ? `
                    <div class="detail-row">
                        <i class="fas fa-ruler-combined"></i>
                        <span class="detail-label">Büyüklük</span>
                        <span class="detail-value">${escapeHtml(apt.tattoo.size || '—')}</span>
                    </div>
                    <div class="detail-row">
                        <i class="fas fa-map-marker-alt"></i>
                        <span class="detail-label">Bölge</span>
                        <span class="detail-value">${escapeHtml(apt.tattoo.body_area || '—')}</span>
                    </div>
                    ` : ''}
                    <div class="detail-row">
                        <i class="fas fa-clock"></i>
                        <span class="detail-label">Süre</span>
                        <span class="detail-value">${apt.duration_minutes} dk</span>
                    </div>
                    <div class="detail-row">
                        <i class="fas fa-tag"></i>
                        <span class="detail-label">Ücret</span>
                        <span class="detail-value">${getPriceText(apt.price)}</span>
                    </div>
                </div>
            </div>
        `).join('');
}

// =============================================
// HELPER FUNCTIONS
// =============================================

/**
 * HTML escape function to prevent XSS attacks
 * @param {string} text - Text to escape
 * @returns {string} Escaped HTML-safe text
 */
function escapeHtml(text) {
    if (text === null || text === undefined) {
        return '';
    }
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getStatusText(status) {
    const statusMap = {
        'pending': 'Bekliyor',
        'confirmed': 'Onaylandı',
        'completed': 'Tamamlandı',
        'cancelled': 'İptal',
        'no_show': 'Gelmedi',
        'slot_pending': 'Saat seçimi'
    };
    return statusMap[status] || status;
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

function getPaymentText(method) {
    return method === 'nakit' ? 'Nakit' : 'Havale/EFT';
}

function getPriceText(price) {
    const n = Number(price || 0);
    if (n <= 0) return 'Belirtilmedi';
    return `${n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
}

function canCancelAppointment(appointment) {
    if (!appointment.date || !appointment.time) return false;
    // Check if appointment is at least 2 hours away
    const [day, month, year] = appointment.date.split('.');
    const [hours, minutes] = appointment.time.split(':');
    const apptDate = new Date(year, month - 1, day, hours, minutes);
    const now = new Date();
    const hoursDiff = (apptDate - now) / (1000 * 60 * 60);

    return hoursDiff >= 2;
}

// =============================================
// CANCEL APPOINTMENT
// =============================================

function openCancelModal(appointmentId) {
    currentAppointmentIdForCancel = appointmentId;
    const apt = appointments.find(a => a.id === appointmentId);

    if (!apt) return;

    const tattooInfo = [];
    if (apt.tattoo?.body_area) tattooInfo.push(`Bölge: ${escapeHtml(apt.tattoo.body_area)}`);
    if (apt.tattoo?.size) tattooInfo.push(`Boyut: ${escapeHtml(apt.tattoo.size)}`);
    const tattooLine = tattooInfo.length ? tattooInfo.join(' | ') : 'Dövme randevusu';

    document.getElementById('cancel-appointment-details').innerHTML = `
        <div class="detail-row">
            <i class="fas fa-calendar-alt"></i>
            <span class="detail-label">Tarih</span>
            <span class="detail-value">${apt.date} - ${apt.time}</span>
        </div>
        <div class="detail-row">
            <i class="fas fa-user-tie"></i>
            <span class="detail-label">Sanatçı</span>
                        <span class="detail-value">${apt.staff.name}</span>
        </div>
        <div class="detail-row">
            <i class="fas fa-pen-nib"></i>
            <span class="detail-label">Detay</span>
            <span class="detail-value">${tattooLine}</span>
        </div>
    `;

    document.getElementById('cancel-modal-overlay').classList.add('show');

    document.getElementById('confirm-cancel-btn').onclick = confirmCancel;
}

function closeCancelModal() {
    document.getElementById('cancel-modal-overlay').classList.remove('show');
    currentAppointmentIdForCancel = null;
}

async function confirmCancel() {
    if (!currentAppointmentIdForCancel) return;

    const data = await apiCall(`/customer/appointments/${currentAppointmentIdForCancel}/cancel`, {
        method: 'PUT'
    });

    if (data && data.success) {
        showToast(data.message, 'success');
        closeCancelModal();
        loadAppointments(currentFilter);
    } else {
        showToast(data?.message || 'İptal işlemi başarısız', 'error');
    }
}

// =============================================
// LOYALTY POINTS
// =============================================

let loyaltyData = null;

async function loadLoyaltySummary() {
    const data = await apiCall('/customer/loyalty');
    if (!data || !data.success) return;
    loyaltyData = data.loyalty;
    renderLoyaltyCard(loyaltyData);
}

function renderLoyaltyCard(loyalty) {
    const balanceEl = document.getElementById('loyalty-balance');
    const milestoneText = document.getElementById('loyalty-milestone-text');
    const progressFill = document.getElementById('loyalty-progress-fill');
    const statusMsg = document.getElementById('loyalty-status-msg');
    const activeCode = document.getElementById('loyalty-active-code');
    const redeemBtn = document.getElementById('loyalty-redeem-btn');
    const historyEl = document.getElementById('loyalty-history');
    const sidebarPts = document.getElementById('sidebar-loyalty-points');
    const sidebarVal = document.getElementById('sidebar-points-value');

    if (!balanceEl || !loyalty) return;

    balanceEl.textContent = loyalty.balance;
    if (sidebarPts && sidebarVal) {
        sidebarVal.textContent = loyalty.balance;
        sidebarPts.hidden = false;
    }

    const done = loyalty.completed_tattoos;
    const target = loyalty.milestone_completions;
    const ppc = loyalty.points_per_completion || 100;
    milestoneText.textContent = `${done} / ${target}`;
    const pct = Math.min(100, Math.round((done / target) * 100));
    progressFill.style.width = `${pct}%`;

    if (loyalty.active_redemption) {
        const r = loyalty.active_redemption;
        statusMsg.textContent = `Aktif indirim kodunuz var (%${r.discount_percent}). Randevu alırken kodu paylaşın.`;
        activeCode.hidden = false;
        activeCode.innerHTML = `
            <div class="loyalty-code-box">
                <span class="loyalty-code-label">İndirim kodu</span>
                <strong class="loyalty-code-value">${escapeHtml(r.code)}</strong>
                <span class="loyalty-code-expiry">Geçerlilik: ${escapeHtml(r.expires_at || '-')}</span>
            </div>`;
        redeemBtn.hidden = true;
    } else if (loyalty.can_redeem) {
        statusMsg.textContent =
            `${target}. dövmenizi tamamladınız! ${loyalty.redeem_points_cost} puan ile %${loyalty.discount_percent} indirim alabilirsiniz.`;
        activeCode.hidden = true;
        redeemBtn.hidden = false;
    } else if (done < target) {
        const need = loyalty.completions_until_milestone;
        statusMsg.textContent =
            `Her tamamlanan dövme +${loyalty.points_per_completion} puan. İndirim için ${need} dövme daha tamamlayın.`;
        activeCode.hidden = true;
        redeemBtn.hidden = true;
    } else {
        const needPts = loyalty.points_until_redeem;
        const needDone = loyalty.completions_until_milestone;
        if (needDone > 0) {
            statusMsg.textContent =
                `Her tamamlanan dövme +${ppc} puan. İndirim için ${needDone} dövme daha tamamlayın.`;
        } else {
            statusMsg.textContent =
                `${done} dövme tamamlandı (${done * ppc} puan). İndirim için ${needPts} puan daha kazanın.`;
        }
        activeCode.hidden = true;
        redeemBtn.hidden = true;
    }

    if (historyEl) {
        const items = (loyalty.history || []).slice(0, 8);
        if (!items.length) {
            historyEl.innerHTML = '<p class="loyalty-history-empty">Henüz puan hareketi yok.</p>';
        } else {
            historyEl.innerHTML = `
                <h4 class="loyalty-history-title">Son hareketler</h4>
                <ul class="loyalty-history-list">
                    ${items.map(item => `
                        <li>
                            <span class="loyalty-history-delta ${item.points_delta >= 0 ? 'plus' : 'minus'}">
                                ${item.points_delta >= 0 ? '+' : ''}${item.points_delta}
                            </span>
                            <span class="loyalty-history-desc">${escapeHtml(item.description || '')}</span>
                            <span class="loyalty-history-date">${escapeHtml(item.created_at || '')}</span>
                        </li>
                    `).join('')}
                </ul>`;
        }
    }
}

async function redeemLoyaltyDiscount() {
    const btn = document.getElementById('loyalty-redeem-btn');
    if (btn) btn.disabled = true;
    const data = await apiCall('/customer/loyalty/redeem', { method: 'POST', body: '{}' });
    if (btn) btn.disabled = false;
    if (data && data.success) {
        showToast(data.message, 'success');
        if (data.loyalty) renderLoyaltyCard(data.loyalty);
    } else {
        showToast(data?.message || 'İndirim kodu oluşturulamadı', 'error');
    }
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// =============================================
// TOAST NOTIFICATION
// =============================================

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}
