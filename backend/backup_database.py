"""
PostgreSQL Veritabanı Yedekleme Scripti
Sefa Pertev Hair Studio - Randevu Sistemi

Kullanım: python backup_database.py
Windows Task Scheduler ile günlük çalıştırılabilir.
"""

import os
import subprocess
import datetime
import glob
from dotenv import load_dotenv

# .env dosyasından veritabanı bilgilerini yükle
load_dotenv()

# Yapılandırma
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
KEEP_DAYS = 7  # Kaç günlük yedek tutulsun

# Veritabanı bilgileri
DB_HOST = os.getenv('DATABASE_HOST', 'localhost')
DB_PORT = os.getenv('DATABASE_PORT', '5432')
DB_NAME = os.getenv('DATABASE_NAME', 'tattoo_db')
DB_USER = os.getenv('DATABASE_USER', 'postgres')
DB_PASSWORD = os.getenv('DATABASE_PASSWORD', '')


def create_backup():
    """PostgreSQL veritabanını yedekler"""
    
    # Backup klasörünü oluştur
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"📁 Backup klasörü oluşturuldu: {BACKUP_DIR}")
    
    # Dosya adı: backup_2024-12-28_03-00-00.sql
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    backup_filename = f"backup_{timestamp}.sql"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    
    # pg_dump komutu
    # Windows'ta pg_dump.exe PostgreSQL bin klasöründe olmalı
    pg_dump_cmd = [
        'pg_dump',
        '-h', DB_HOST,
        '-p', DB_PORT,
        '-U', DB_USER,
        '-d', DB_NAME,
        '-f', backup_path,
        '--no-password'
    ]
    
    # PGPASSWORD ortam değişkeni ile şifre geç
    env = os.environ.copy()
    env['PGPASSWORD'] = DB_PASSWORD
    
    try:
        print(f"🔄 Yedekleme başlıyor: {DB_NAME}")
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            file_size = os.path.getsize(backup_path) / (1024 * 1024)  # MB
            print(f"✅ Yedekleme tamamlandı!")
            print(f"   📄 Dosya: {backup_filename}")
            print(f"   📊 Boyut: {file_size:.2f} MB")
            return True, backup_path
        else:
            print(f"❌ Yedekleme hatası: {result.stderr}")
            return False, result.stderr
            
    except FileNotFoundError:
        error_msg = "pg_dump bulunamadı! PostgreSQL bin klasörünü PATH'e ekleyin."
        print(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        return False, str(e)


def cleanup_old_backups():
    """Eski yedekleri temizler"""
    
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
    backup_pattern = os.path.join(BACKUP_DIR, 'backup_*.sql')
    
    deleted_count = 0
    
    for backup_file in glob.glob(backup_pattern):
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(backup_file))
        
        if file_time < cutoff_date:
            try:
                os.remove(backup_file)
                print(f"🗑️ Eski yedek silindi: {os.path.basename(backup_file)}")
                deleted_count += 1
            except Exception as e:
                print(f"⚠️ Dosya silinemedi: {backup_file} - {e}")
    
    if deleted_count > 0:
        print(f"📋 Toplam {deleted_count} eski yedek temizlendi")
    else:
        print(f"✓ Temizlenecek eski yedek yok ({KEEP_DAYS} günden yeni)")


def list_backups():
    """Mevcut yedekleri listeler"""
    
    backup_pattern = os.path.join(BACKUP_DIR, 'backup_*.sql')
    backups = sorted(glob.glob(backup_pattern), reverse=True)
    
    if not backups:
        print("📭 Henüz yedek yok")
        return
    
    print(f"\n📦 Mevcut Yedekler ({len(backups)} adet):")
    print("-" * 50)
    
    for backup in backups:
        file_size = os.path.getsize(backup) / (1024 * 1024)  # MB
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(backup))
        print(f"  {os.path.basename(backup)} - {file_size:.2f} MB - {file_time.strftime('%d.%m.%Y %H:%M')}")


if __name__ == '__main__':
    print("=" * 50)
    print("🗄️ PostgreSQL Veritabanı Yedekleme")
    print("=" * 50)
    print()
    
    # 1. Yedek al
    success, result = create_backup()
    print()
    
    # 2. Eski yedekleri temizle
    cleanup_old_backups()
    print()
    
    # 3. Mevcut yedekleri listele
    list_backups()
    print()
    
    print("=" * 50)
    if success:
        print("✅ Yedekleme işlemi başarıyla tamamlandı!")
    else:
        print("❌ Yedekleme işlemi başarısız!")
    print("=" * 50)
