"""
Operatör hata kodları.

Log satırındaki kod ile buradaki açıklama eşleşir.
Arama örneği: grep E-WA-001 /opt/roof_tattoo/backend/logs/app.log
"""

# Veritabanı
E_DB_001 = "E-DB-001"  # bağlantı havuzu oluşturulamadı
E_DB_002 = "E-DB-002"  # havuz tükendi / bağlantı alınamadı
E_DB_003 = "E-DB-003"  # bağlantı geri verilemedi
E_DB_004 = "E-DB-004"  # sorgu veya transaction hatası

# Kimlik
E_AUTH_001 = "E-AUTH-001"  # admin/müşteri girişi veya token hatası

# WhatsApp / Evolution
E_WA_001 = "E-WA-001"  # mesaj gönderilemedi
E_WA_002 = "E-WA-002"  # webhook işlenemedi
E_WA_003 = "E-WA-003"  # yapılandırma eksik
E_WA_004 = "E-WA-004"  # doğrulama kodu / hatırlatma gönderilemedi

# Google Takvim
E_GCAL_001 = "E-GCAL-001"  # senkron veya silme hatası
E_GCAL_002 = "E-GCAL-002"  # senkron kuyruğu (outbox) hatası
E_GCAL_003 = "E-GCAL-003"  # kuyruk işi tüm denemelerde başarısız (kalıcı)

# Randevu / talep
E_BOOK_001 = "E-BOOK-001"  # randevu oluşturulamadı
E_REQ_001 = "E-REQ-001"  # dövme talebi / teklif hatası

# Yedekleme / scheduler
E_BKP_001 = "E-BKP-001"  # veritabanı yedekleme veya Drive yükleme
E_SCH_001 = "E-SCH-001"  # zamanlayıcı başlatılamadı

# Bilinmeyen
E_UNK_001 = "E-UNK-001"

# Yapılandırma uyarısı (ERROR değil)
W_CFG_001 = "W-CFG-001"

CODE_HELP = {
    E_DB_001: "PostgreSQL bağlantı havuzu açılamadı. .env DATABASE_* ve SSL ayarını kontrol et.",
    E_DB_002: "DB havuzu doldu veya bağlantı alınamadı. Yoğunluk veya kopuk bağlantı.",
    E_DB_003: "Kullanılan DB bağlantısı havuza geri verilemedi.",
    E_DB_004: "SQL/transaction hatası. Satırdaki fonksiyon adına bak.",
    E_AUTH_001: "Giriş veya oturum hatası (telefon, şifre, token).",
    E_WA_001: "Evolution API mesaj gönderemedi. Instance bağlantısı ve API key.",
    E_WA_002: "WhatsApp webhook işlenirken hata. Gelen event ve traceback.",
    E_WA_003: "Evolution api_key veya instance_name eksik.",
    E_WA_004: "OTP, hatırlatma veya karşılama mesajı gönderilemedi.",
    E_GCAL_001: "Google Takvim yazılamadı/silinemedi. credentials ve calendar_id.",
    E_GCAL_002: "Takvim senkron kuyruğuna yazılamadı/okunamadı. google_calendar_queue tablosu.",
    E_GCAL_003: "Takvim işi tüm denemelerden sonra bırakıldı. Kuyrukta dead_at dolu satıra bak.",
    E_BOOK_001: "Randevu kaydı oluşmadı (slot çakışması hariç beklenmeyen hata).",
    E_REQ_001: "Dövme talebi veya teklif linki oluşturulamadı.",
    E_BKP_001: "pg_dump veya Google Drive (rclone) yedekleme hatası.",
    E_SCH_001: "APScheduler başlatılamadı. Kilit veya process çakışması.",
    E_UNK_001: "Kod bağlanmamış genel hata. Kaynak sütunundaki dosya:satır.",
    W_CFG_001: "Eksik yapılandırma; işlem atlandı.",
}
