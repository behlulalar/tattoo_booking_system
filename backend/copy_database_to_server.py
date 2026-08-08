#!/usr/bin/env python3
"""
Yerel veritabanını sunucu veritabanına kopyalama scripti
PostgreSQL dump ve restore işlemi

Kullanım:
    python copy_database_to_server.py
"""

import os
import subprocess
import sys
import tempfile
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Yerel veritabanı bilgileri (.env'den)
LOCAL_DB = {
    'host': os.getenv('DATABASE_HOST', 'localhost'),
    'port': os.getenv('DATABASE_PORT', '5432'),
    'name': os.getenv('DATABASE_NAME', 'tattoo_db'),
    'user': os.getenv('DATABASE_USER', 'postgres'),
    'password': os.getenv('DATABASE_PASSWORD', '')
}

# Sunucu veritabanı bilgileri (kullanıcıdan alınacak veya .env'den SERVER_ prefix'i ile)
SERVER_DB = {
    'host': os.getenv('SERVER_DATABASE_HOST', ''),
    'port': os.getenv('SERVER_DATABASE_PORT', '5432'),
    'name': os.getenv('SERVER_DATABASE_NAME', os.getenv('DATABASE_NAME', 'tattoo_db')),
    'user': os.getenv('SERVER_DATABASE_USER', ''),
    'password': os.getenv('SERVER_DATABASE_PASSWORD', '')
}


def get_server_info():
    """Sunucu veritabanı bilgilerini kullanıcıdan al"""
    print("\n" + "="*60)
    print("📍 Sunucu Veritabanı Bilgilerini Girin")
    print("="*60)
    
    if not SERVER_DB['host']:
        SERVER_DB['host'] = input("Sunucu Host (örn: example.com veya IP): ").strip()
    
    if not SERVER_DB['port']:
        port = input(f"Port [{SERVER_DB['port']}]: ").strip()
        SERVER_DB['port'] = port if port else SERVER_DB['port']
    
    if not SERVER_DB['name']:
        db_name = input(f"Veritabanı Adı [{SERVER_DB['name']}]: ").strip()
        SERVER_DB['name'] = db_name if db_name else SERVER_DB['name']
    
    if not SERVER_DB['user']:
        SERVER_DB['user'] = input("Kullanıcı Adı: ").strip()
    
    if not SERVER_DB['password']:
        SERVER_DB['password'] = input("Şifre: ").strip()
    
    print()


def print_db_info(db_config, label):
    """Veritabanı bilgilerini yazdır (şifre hariç)"""
    print(f"{label}:")
    print(f"  Host: {db_config['host']}")
    print(f"  Port: {db_config['port']}")
    print(f"  Database: {db_config['name']}")
    print(f"  User: {db_config['user']}")
    print()


def check_pg_tools():
    """pg_dump ve psql araçlarının varlığını kontrol et"""
    try:
        subprocess.run(['pg_dump', '--version'], capture_output=True, check=True)
        subprocess.run(['psql', '--version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ pg_dump veya psql bulunamadı!")
        print("   PostgreSQL client tools yüklü olmalıdır.")
        print("   macOS: brew install postgresql")
        return False


def test_local_connection():
    """Yerel veritabanı bağlantısını test et"""
    print("🔍 Yerel veritabanı bağlantısı test ediliyor...")
    test_cmd = [
        'psql',
        '-h', LOCAL_DB['host'],
        '-p', LOCAL_DB['port'],
        '-U', LOCAL_DB['user'],
        '-d', LOCAL_DB['name'],
        '-c', 'SELECT 1;'
    ]
    
    env = os.environ.copy()
    env['PGPASSWORD'] = LOCAL_DB['password']
    
    try:
        result = subprocess.run(
            test_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            print("✅ Yerel veritabanı bağlantısı başarılı")
            return True
        else:
            print(f"❌ Yerel veritabanı bağlantı hatası: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Yerel veritabanı bağlantı hatası: {e}")
        return False


def dump_local_database():
    """Yerel veritabanından dump al"""
    print("="*60)
    print("📥 Yerel Veritabanından Dump Alınıyor...")
    print("="*60)
    
    # Geçici dosya oluştur
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False)
    temp_file.close()
    dump_path = temp_file.name
    
    pg_dump_cmd = [
        'pg_dump',
        '-h', LOCAL_DB['host'],
        '-p', LOCAL_DB['port'],
        '-U', LOCAL_DB['user'],
        '-d', LOCAL_DB['name'],
        '-f', dump_path,
        '--no-owner',  # Owner bilgisini ekleme (sunucuda farklı user olabilir)
        '--no-acl',    # ACL bilgilerini ekleme
        '--clean',     # Önce DROP komutları ekle
        '--if-exists'  # IF EXISTS kullan
    ]
    
    env = os.environ.copy()
    env['PGPASSWORD'] = LOCAL_DB['password']
    
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
                print(f"✅ Dump alındı: {file_size:.2f} MB")
                return dump_path
            else:
                print(f"❌ Dump dosyası oluşturulamadı veya boş")
                if os.path.exists(dump_path):
                    os.remove(dump_path)
                return None
        else:
            print(f"❌ Dump hatası (exit code: {result.returncode})")
            print(f"Stderr: {result.stderr}")
            if result.stdout:
                print(f"Stdout: {result.stdout}")
            if os.path.exists(dump_path):
                os.remove(dump_path)
            return None
            
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        if os.path.exists(dump_path):
            os.remove(dump_path)
        return None


def check_and_create_database():
    """Sunucuda veritabanının var olup olmadığını kontrol et, yoksa oluştur"""
    env = os.environ.copy()
    env['PGPASSWORD'] = SERVER_DB['password']
    
    # Önce postgres veritabanına bağlanıp veritabanının var olup olmadığını kontrol et
    check_cmd = [
        'psql',
        '-h', SERVER_DB['host'],
        '-p', SERVER_DB['port'],
        '-U', SERVER_DB['user'],
        '-d', 'postgres',
        '-tAc', f"SELECT 1 FROM pg_database WHERE datname='{SERVER_DB['name']}';"
    ]
    
    try:
        result = subprocess.run(
            check_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        db_exists = result.stdout.strip() == '1'
        
        if not db_exists:
            print(f"⚠️  '{SERVER_DB['name']}' veritabanı bulunamadı. Oluşturuluyor...")
            create_cmd = [
                'psql',
                '-h', SERVER_DB['host'],
                '-p', SERVER_DB['port'],
                '-U', SERVER_DB['user'],
                '-d', 'postgres',
                '-c', f"CREATE DATABASE {SERVER_DB['name']};"
            ]
            
            create_result = subprocess.run(
                create_cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if create_result.returncode == 0:
                print(f"✅ Veritabanı oluşturuldu: {SERVER_DB['name']}")
                return True
            else:
                print(f"❌ Veritabanı oluşturulamadı: {create_result.stderr}")
                return False
        else:
            print(f"✅ Veritabanı mevcut: {SERVER_DB['name']}")
            return True
            
    except Exception as e:
        print(f"❌ Veritabanı kontrolü hatası: {e}")
        return False


def restore_to_server(dump_path):
    """Dump dosyasını sunucu veritabanına yükle"""
    print("\n" + "="*60)
    print("📤 Sunucu Veritabanına Yükleniyor...")
    print("="*60)
    
    # Önce veritabanı bağlantısını test et
    print("🔍 Sunucu bağlantısı test ediliyor...")
    test_cmd = [
        'psql',
        '-h', SERVER_DB['host'],
        '-p', SERVER_DB['port'],
        '-U', SERVER_DB['user'],
        '-d', 'postgres',  # postgres veritabanına bağlan
        '-c', 'SELECT 1;'  # Basit bir test
    ]
    
    env = os.environ.copy()
    env['PGPASSWORD'] = SERVER_DB['password']
    
    try:
        result = subprocess.run(
            test_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print(f"❌ Sunucu bağlantı hatası (exit code: {result.returncode})")
            print(f"Stderr: {result.stderr}")
            if result.stdout:
                print(f"Stdout: {result.stdout}")
            return False
        
        print("✅ Sunucu bağlantısı başarılı")
        
        # Veritabanının var olup olmadığını kontrol et
        if not check_and_create_database():
            return False
    except subprocess.TimeoutExpired:
        print("❌ Sunucu bağlantısı zaman aşımına uğradı")
        return False
    except Exception as e:
        print(f"❌ Bağlantı hatası: {e}")
        return False
    
    # Veritabanını restore et
    print(f"\n🔄 {SERVER_DB['name']} veritabanına yükleniyor...")
    print("⚠️  Bu işlem mevcut verileri silecek!")
    
    # Kullanıcıdan onay al
    confirm = input("Devam etmek istiyor musunuz? (evet/hayır): ").strip().lower()
    if confirm not in ['evet', 'e', 'yes', 'y']:
        print("❌ İşlem iptal edildi")
        return False
    
    psql_cmd = [
        'psql',
        '-h', SERVER_DB['host'],
        '-p', SERVER_DB['port'],
        '-U', SERVER_DB['user'],
        '-d', SERVER_DB['name'],
        '-f', dump_path
    ]
    
    try:
        result = subprocess.run(
            psql_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300  # 5 dakika timeout
        )
        
        if result.returncode == 0:
            print("✅ Veritabanı başarıyla yüklendi!")
            if result.stdout:
                print("\nÇıktı:")
                print(result.stdout)
            return True
        else:
            print(f"❌ Restore hatası (exit code: {result.returncode})")
            print(f"\nStderr:")
            print(result.stderr)
            if result.stdout:
                print(f"\nStdout:")
                print(result.stdout)
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ İşlem zaman aşımına uğradı (5 dakika)")
        return False
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        return False


def main():
    print("="*60)
    print("🔄 Veritabanı Kopyalama Aracı")
    print("   Yerel -> Sunucu")
    print("="*60)
    
    # Araçları kontrol et
    if not check_pg_tools():
        sys.exit(1)
    
    # Veritabanı bilgilerini göster
    print("\n📋 Yerel Veritabanı Bilgileri:")
    print_db_info(LOCAL_DB, "Yerel")
    
    # Sunucu bilgilerini al
    if not all([SERVER_DB['host'], SERVER_DB['user']]):
        get_server_info()
    
    print("\n📋 Sunucu Veritabanı Bilgileri:")
    print_db_info(SERVER_DB, "Sunucu")
    
    # Yerel veritabanı bağlantısını test et
    if not test_local_connection():
        print("\n❌ Yerel veritabanına bağlanılamadı, işlem sonlandırılıyor")
        print("   Lütfen .env dosyasındaki DATABASE_* değişkenlerini kontrol edin")
        sys.exit(1)
    
    # Yerel veritabanından dump al
    dump_path = dump_local_database()
    if not dump_path:
        print("\n❌ Dump alınamadı, işlem sonlandırılıyor")
        sys.exit(1)
    
    # Sunucuya yükle
    try:
        success = restore_to_server(dump_path)
    except KeyboardInterrupt:
        print("\n\n⚠️  İşlem kullanıcı tarafından iptal edildi")
        success = False
    except Exception as e:
        print(f"\n❌ Beklenmeyen hata: {e}")
        import traceback
        traceback.print_exc()
        success = False
    
    # Geçici dosyayı temizle
    try:
        if os.path.exists(dump_path):
            os.remove(dump_path)
    except Exception as e:
        print(f"⚠️  Geçici dosya silinemedi: {e}")
    
    # Sonuç
    print("\n" + "="*60)
    if success:
        print("✅ İşlem başarıyla tamamlandı!")
    else:
        print("❌ İşlem başarısız!")
    print("="*60)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

