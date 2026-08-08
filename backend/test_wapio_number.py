#!/usr/bin/env python3
"""
Wapio numara geçerliliği test script'i
Bir WhatsApp numarasının Wapio'da geçerli olup olmadığını test eder
"""

import sys
import os
import json
import requests
from dotenv import load_dotenv

# Backend klasörüne git
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_wapio_config

load_dotenv()

def test_wapio_number(phone):
    """Bir numaranın Wapio'da geçerli olup olmadığını test et"""
    
    wapio_config = get_wapio_config()
    
    if not wapio_config.get('instance_id') or not wapio_config.get('api_token'):
        print("❌ Wapio ayarları eksik! (.env veya wapio_settings.json)")
        return False
    
    api_url = wapio_config['api_url']
    api_token = wapio_config['api_token']
    instance_id = wapio_config['instance_id']
    
    print(f"\n{'='*60}")
    print(f"🔍 Wapio Numarası Test: {phone}")
    print(f"{'='*60}\n")
    
    # TEST 1: GetContact API ile numara bilgisini kontrol et
    if '@lid' in phone or '@c.us' in phone:
        print("📋 TEST 1: GetContact API (sadece @lid/@c.us için)")
        try:
            url = f"{api_url}/GetContact"
            headers = {
                'token': api_token,
                'session_id': instance_id
            }
            params = {'number': phone}
            
            print(f"   URL: {url}")
            print(f"   Number: {phone}")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            print(f"   Status Code: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ GetContact başarılı!")
                print(f"   Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
            else:
                print(f"   ❌ GetContact başarısız!")
                print(f"   Response: {response.text}")
                
        except requests.exceptions.Timeout:
            print(f"   ⏱️  GetContact timeout!")
        except Exception as e:
            print(f"   ❌ GetContact hatası: {e}")
    
    # TEST 2: Send-Text API ile test mesajı gönder (kısa bir test mesajı)
    print(f"\n📤 TEST 2: Send-Text API (Test mesajı gönder)")
    try:
        url = f"{api_url}/send-text"
        headers = {
            'token': api_token,
            'session_id': instance_id,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'phone': phone,
            'is_group': False,
            'data': {
                'message': '🧪 Test mesajı - Lütfen görmezden gelin',
                'messageId': ''
            }
        }
        
        print(f"   URL: {url}")
        print(f"   Phone: {phone}")
        print(f"   Timeout: 12 saniye")
        
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Mesaj gönderme başarılı!")
            print(f"   Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return True
        else:
            print(f"   ❌ Mesaj gönderme başarısız!")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"   ⏱️  Send-Text timeout! (12 saniye)")
        print(f"   ⚠️  Bu numara için Wapio timeout veriyor - numara geçersiz veya Wapio sorunu olabilir")
        return False
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else None
        print(f"   ❌ HTTP Hatası ({status_code}): {e}")
        if status_code == 408:
            print(f"   ⚠️  408 Timeout - Wapio bu numara için timeout veriyor")
        return False
    except Exception as e:
        print(f"   ❌ Send-Text hatası: {e}")
        return False
    
    print(f"\n{'='*60}\n")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Kullanım: python3 test_wapio_number.py <numara>")
        print("\nÖrnekler:")
        print("  python3 test_wapio_number.py 82863491944495@lid")
        print("  python3 test_wapio_number.py 905301234567")
        print("  python3 test_wapio_number.py 153906294354033@lid")
        sys.exit(1)
    
    phone = sys.argv[1]
    test_wapio_number(phone)

