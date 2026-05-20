import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Data file path
JSON_PATH = os.path.join(BASE_DIR, "domains.json")

# Web root for static construction page
WEB_ROOT = "/var/www/construction_page"

# Nginx configuration path
NGINX_CONF_PATH = "/etc/nginx/conf.d/regisguard.conf"

# SSL certificate directory
SSL_DIR = "/etc/letsencrypt/live"

# Flask settings
SECRET_KEY = os.environ.get("REGISGUARD_SECRET_KEY", "change-me-in-production")
ADMIN_PASSWORD = os.environ.get("REGISGUARD_ADMIN_PASSWORD", "admin123")

# Admin panel IP whitelist (comma-separated, empty means allow all)
# Fallback when domains.json has no allowed_ips configured
ADMIN_ALLOWED_IPS = os.environ.get("REGISGUARD_ALLOWED_IPS", "")
