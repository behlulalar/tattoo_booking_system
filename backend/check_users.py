import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

# Database config
db_config = {
    'host': os.getenv('DATABASE_HOST', 'localhost'),
    'port': os.getenv('DATABASE_PORT', '5432'),
    'user': os.getenv('DATABASE_USER'),
    'password': os.getenv('DATABASE_PASSWORD'),
    'database': os.getenv('DATABASE_NAME')
}

try:
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name, phone, role FROM artists;")
    users = cursor.fetchall()
    
    print("\n=== ARTISTS IN DATABASE ===\n")
    if users:
        for user in users:
            print(f"┌─ User ID: {user[0]}")
            print(f"│  Name: {user[1]}")
            print(f"│  Phone: {user[2]}")
            print(f"└─ Role: {user[3]}")
            print()
    else:
        print("❌ NO USERS FOUND!")
    
    cursor.close()
    conn.close()
    
except Exception as e:
    print(f"❌ ERROR: {e}")
