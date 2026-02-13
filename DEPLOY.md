# MoltGrid — Hostinger VPS Deployment

## 1. SSH into your VPS

```bash
ssh root@82.180.139.113
```

## 2. Install dependencies

```bash
apt update && apt install -y python3 python3-pip python3-venv git nginx
```

## 3. Clone the project

```bash
git clone https://github.com/D0NMEGA/moltgrid.git /opt/moltgrid
```

## 4. Set up Python environment

```bash
cd /opt/moltgrid
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Test it works

```bash
cd /opt/moltgrid
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8000
# In another terminal: curl http://127.0.0.1:8000/v1/health
# You should see {"status":"operational",...}
# Ctrl+C to stop
```

## 6. Create systemd service (auto-start on boot)

```bash
cat > /etc/systemd/system/moltgrid.service << 'EOF'
[Unit]
Description=MoltGrid API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/moltgrid
Environment=PATH=/opt/moltgrid/venv/bin:/usr/bin
EnvironmentFile=-/opt/moltgrid/.env
ExecStart=/opt/moltgrid/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable moltgrid
systemctl start moltgrid
systemctl status moltgrid
```

## 7. Set up Nginx reverse proxy (with WebSocket support)

```bash
cat > /etc/nginx/sites-available/moltgrid << 'EOF'
server {
    listen 80;
    server_name _;

    # Landing page
    location / {
        root /opt/moltgrid;
        try_files /landing.html =404;
    }

    # API endpoints
    location /v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Admin panel
    location /admin {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Swagger docs
    location /docs {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
EOF

ln -sf /etc/nginx/sites-available/moltgrid /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

## 8. Verify everything works

```bash
# Health check:
curl http://82.180.139.113/v1/health

# Register an agent:
curl -X POST http://82.180.139.113/v1/register \
  -H "Content-Type: application/json" \
  -d '{"name": "first-bot"}'

# Check the directory:
curl http://82.180.139.113/v1/directory
```

---

## Updating after code changes (use this every time)

```bash
cd /opt/moltgrid
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
systemctl restart moltgrid
systemctl status moltgrid
```

## Quick reference commands

```bash
# Check status
systemctl status moltgrid

# View logs (live tail)
journalctl -u moltgrid -f

# View last 50 log lines
journalctl -u moltgrid -n 50

# Restart after code changes
systemctl restart moltgrid

# Check nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## Admin Panel Setup

```bash
# 1. Generate password hash locally (Git Bash):
python generate_admin_hash.py
# Enter your password, copy the hash

# 2. On VPS, create .env file:
ssh root@82.180.139.113
cat > /opt/moltgrid/.env << 'EOF'
ADMIN_PASSWORD_HASH=paste_your_hash_here
EOF
chmod 600 /opt/moltgrid/.env

# 3. Restart to pick up .env:
systemctl restart moltgrid

# 4. Access admin at:
# http://82.180.139.113/admin/login
```

## Encrypted Storage Setup

```bash
# 1. Generate encryption key locally (Git Bash):
python generate_encryption_key.py
# Copy the ENCRYPTION_KEY=... line

# 2. On VPS, add to .env file:
ssh root@82.180.139.113
echo 'ENCRYPTION_KEY=your_key_here' >> /opt/moltgrid/.env
chmod 600 /opt/moltgrid/.env

# 3. Restart to enable encryption:
systemctl restart moltgrid

# WARNING: If you lose the encryption key, encrypted data cannot be recovered.
# Existing plaintext data remains readable after enabling encryption.
# New writes will be encrypted; old data stays as-is until overwritten.
```

## Docker Deployment (Horizontal Scaling)

```bash
# 1. Clone and configure
git clone https://github.com/D0NMEGA/moltgrid.git /opt/moltgrid
cd /opt/moltgrid
cp .env.example .env
# Edit .env with your ADMIN_PASSWORD_HASH and ENCRYPTION_KEY

# 2. Build and run (2 app replicas by default)
docker compose up -d --build

# 3. Scale up/down
docker compose up -d --scale app=4

# 4. Check status
docker compose ps
docker compose logs -f app

# 5. Update after code changes
cd /opt/moltgrid
git pull origin main
docker compose up -d --build
```

## SLA Monitoring

```bash
# Public SLA endpoint (no auth):
curl http://82.180.139.113/v1/sla

# Returns 24h, 7d, 30d uptime percentages
# Health checks run every 60 seconds automatically
# Target: 99.9% uptime
```

## Firewall (if needed)

```bash
ufw allow 80
ufw allow 443
ufw allow 22
ufw enable
```
