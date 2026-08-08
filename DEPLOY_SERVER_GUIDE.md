## Sunucuya Çakışmasız Deployment (Ubuntu + Nginx + Systemd)

Bu rehber, aynı sunucuda başka sistemler varken güvenli deployment içindir.

### 1) Sunucuya bağlan

```bash
ssh root@45.141.150.48
```

### 2) Çakışma ön kontrolü

```bash
# Dinleyen portlar
ss -tulpn

# Nginx siteleri
ls -la /etc/nginx/sites-enabled
nginx -t
```

Notlar:
- Bu proje backend için **unix socket** kullanır (`/opt/roof_tattoo/run/gunicorn.sock`), yani port çakışması yaşamaz.
- Nginx tarafında çakışma olmaması için **farklı server_name** kullanın.
- Bu rehberde domain: `tattoo.roof.behlulalar.online`

### 3) Sistem kullanıcısı ve dizinler

```bash
adduser --system --group --home /opt/roof_tattoo roofapp
mkdir -p /opt/roof_tattoo
chown -R roofapp:www-data /opt/roof_tattoo
```

### 4) Kodları sunucuya kopyala

Önce `backend/.env` içinde `DATABASE_PASSWORD` ve gerekirse `DATABASE_HOST` değerlerini sunucuya göre doldur.

Yerel makineden (önerilen):

```bash
chmod +x deploy/rsync-to-server.sh
./deploy/rsync-to-server.sh
```

Manuel rsync (**mutlaka `venv/` hariç tut** — aksi halde sunucudaki Gunicorn silinir):

```bash
rsync -avz --delete "/Users/muhammedbehlulalar/Desktop/Dövme_Randevu_Sistemi/" root@45.141.150.48:/opt/roof_tattoo/ \
  --exclude 'venv/' --exclude 'backend/.venv' --exclude 'backend/backups' --exclude 'backend/.env.local' --exclude 'backend/*.log'
```

Rsync sonrası sunucuda venv yoksa:

```bash
bash /opt/roof_tattoo/deploy/setup-server-venv.sh
systemctl restart roof-tattoo-backend
```

### 5) Backend bağımlılıkları ve venv

Sunucuda:

```bash
apt update
apt install -y python3 python3-venv python3-pip nginx postgresql-client

python3 -m venv /opt/roof_tattoo/venv
/opt/roof_tattoo/venv/bin/pip install --upgrade pip
/opt/roof_tattoo/venv/bin/pip install -r /opt/roof_tattoo/backend/requirements.txt
/opt/roof_tattoo/venv/bin/pip install gunicorn
```

### 6) .env oluştur

```bash
cp /opt/roof_tattoo/backend/.env.example /opt/roof_tattoo/backend/.env
nano /opt/roof_tattoo/backend/.env
```

Mutlaka doldur:
- `DATABASE_*`
- `JWT_SECRET`
- `RANDEVU_URL=https://tattoo.roof.behlulalar.online`
- `FRONTEND_ORIGIN=https://tattoo.roof.behlulalar.online`
- `CORS_ALLOWED_ORIGINS=https://tattoo.roof.behlulalar.online`
- gerekiyorsa `WAPIO_*`

Hızlı başlangıç için istersen:

```bash
cp /opt/roof_tattoo/backend/.env.server.example /opt/roof_tattoo/backend/.env
nano /opt/roof_tattoo/backend/.env
```

### 7) Fiyat kolon migration'ı (önemli)

Kod yeni akışta `slot_offers.price` ve `appointments.price` bekler.

```bash
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f /opt/roof_tattoo/backend/migrations/add_price_columns_for_tattoo_flow.sql
```

### 8) Systemd service kur

```bash
cp /opt/roof_tattoo/backend/roof-tattoo-backend.service.example /etc/systemd/system/roof-tattoo-backend.service
nano /etc/systemd/system/roof-tattoo-backend.service
```

Kontrol et:
- `WorkingDirectory=/opt/roof_tattoo/backend`
- `EnvironmentFile=/opt/roof_tattoo/backend/.env`
- `User=roofapp`
- `Environment="GUNICORN_BIND=unix:/opt/roof_tattoo/run/gunicorn.sock"`

Sonra:

```bash
systemctl daemon-reload
systemctl enable roof-tattoo-backend
systemctl start roof-tattoo-backend
systemctl status roof-tattoo-backend --no-pager
```

### 9) Nginx site kur (çakışmasız)

```bash
cp /opt/roof_tattoo/deploy/nginx-tattoo-randevu.conf.example /etc/nginx/sites-available/roof-tattoo.conf
nano /etc/nginx/sites-available/roof-tattoo.conf
```

Değiştir:
- `server_name tattoo.roof.behlulalar.online;`

Aktifleştir:

```bash
ln -s /etc/nginx/sites-available/roof-tattoo.conf /etc/nginx/sites-enabled/roof-tattoo.conf
nginx -t
systemctl reload nginx
```

### 10) Son kontroller

```bash
curl -I http://tattoo.roof.behlulalar.online/
curl http://tattoo.roof.behlulalar.online/api/health
journalctl -u roof-tattoo-backend -n 100 --no-pager
```

`api/health` çıktısında `"database":{"connected":true}` olmalı. `connected:false` ve `SSL connection has been closed` görürsen:

```bash
# .env içinde (uzak/managed PostgreSQL için)
DATABASE_SSLMODE=require
DB_POOL_MIN_CONN=2
DB_POOL_MAX_CONN=20

systemctl restart roof-tattoo-backend
grep register_customer /opt/roof_tattoo/backend/app.log | tail -20
```

Eski berber şemasından kalan DB'de müşteri kaydı için migration:

```bash
psql -h <DB_HOST> -U <DB_USER> -d <DB_NAME> -f /opt/roof_tattoo/backend/migrations/tattoo_revamp_v1.sql
```

---

## Güncelleme akışı (deploy sonrası)

1. `./deploy/rsync-to-server.sh` ile gönder (veya rsync)
2. `chown -R roofapp:www-data /opt/roof_tattoo`
3. Gerekirse migration çalıştır
4. `systemctl restart roof-tattoo-backend`
5. `nginx -t && systemctl reload nginx`
6. `curl -s http://tattoo.roof.behlulalar.online/api/health` → `"connected":true`

## Lokal geliştirmeye geri dönüş

```bash
cp backend/.env.local backend/.env
```
