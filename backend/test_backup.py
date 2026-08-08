#!/usr/bin/env python3
"""
Test script for database backup functionality
Manuel olarak backup ve Google Drive yükleme işlemini test eder
"""

import os
import sys
from dotenv import load_dotenv

# app.py'yi import etmeden önce çalışma dizinini ayarla
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

# app.py'den fonksiyonları import et
from app import create_database_backup, logger

if __name__ == '__main__':
    print("=" * 60)
    print("DATABASE BACKUP TEST")
    print("=" * 60)
    print()
    
    print("🔄 Backup işlemi başlatılıyor...")
    print()
    
    try:
        result = create_database_backup()
        
        print()
        print("=" * 60)
        if result:
            print("✅ BACKUP BAŞARILI!")
        else:
            print("❌ BACKUP BAŞARISIZ!")
            print("   Log dosyasını kontrol edin: backend/app.log")
        print("=" * 60)
        
        sys.exit(0 if result else 1)
        
    except Exception as e:
        print(f"❌ Hata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

