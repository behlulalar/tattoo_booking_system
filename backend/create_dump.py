#!/usr/bin/env python3
"""
Yerel veritabanından SQL dump dosyası oluşturma scripti
Basit ve hızlı - sadece dump alır
"""

import os
import subprocess
import sys
from datetime import datetime
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Veritabanı bilgileri
DB_HOST = os.getenv('DATABASE_HOST', 'localhost')
DB_PORT = os.getenv('DATABASE_PORT', '5432')
DB_NAME = os.getenv('DATABASE_NAME', 'tattoo_db')
DB_USER = os.getenv('DATABASE_USER', 'postgres')
DB_PASSWORD = os.getenv('DATABASE_PASSWORD', '')

def create_dump():
    """Veritabanından SQL dump dosyası oluştur"""
    
    # Dosya adı: dump_2024-12-28_15-30-45.sql
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    dump_filename = f"dump_{timestamp}.sql"
    dump_path = os.path.join(os.path.dirname(__file__), dump_filename)
    
    print("="*60)
    print("📥 Veritabanı Dump Alınıyor...")
    print("="*60)
    print(f"Host: {DB_HOST}")
    print(f"Port: {DB_PORT}")
    print(f"Database: {DB_NAME}")
    print(f"User: {DB_USER}")
    print(f"\nDosya: {dump_filename}")
    print()
    
    pg_dump_cmd = [
        'pg_dump',
        '-h', DB_HOST,
        '-p', DB_PORT,
        '-U', DB_USER,
        '-d', DB_NAME,
        '-f', dump_path,
        '--no-owner',
        '--no-acl'
    ]
    
    env = os.environ.copy()
    env['PGPASSWORD'] = DB_PASSWORD
    
    try:
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            if os.path.exists(dump_path) and os.path.getsize(dump_path) > 0:
                file_size = os.path.getsize(dump_path) / (1024 * 1024)  # MB
                print(f"✅ Dump başarıyla oluşturuldu!")
                print(f"📄 Dosya: {dump_filename}")
                print(f"📊 Boyut: {file_size:.2f} MB")
                print(f"📁 Konum: {dump_path}")
                return dump_path
            else:
                print(f"❌ Dump dosyası oluşturulamadı veya boş")
                return None
        else:
            print(f"❌ Dump hatası:")
            print(result.stderr)
            return None
            
    except FileNotFoundError:
        print("❌ pg_dump bulunamadı!")
        print("   PostgreSQL client tools yüklü olmalıdır.")
        print("   macOS: brew install postgresql")
        return None
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        return None

if __name__ == '__main__':
    dump_path = create_dump()
    if dump_path:
        print("\n" + "="*60)
        print("✅ İşlem tamamlandı!")
        print("="*60)
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("❌ İşlem başarısız!")
        print("="*60)
        sys.exit(1)

