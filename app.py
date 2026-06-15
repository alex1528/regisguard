import json
import os
import subprocess
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import dns.resolver
from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, session, flash,
)
from flask_wtf.csrf import CSRFProtect

from config import (
    WEB_ROOT, NGINX_CONF_PATH, SSL_DIR,
    SECRET_KEY, ADMIN_PASSWORD, ADMIN_ALLOWED_IPS,
)
from db import (
    init_db, get_all_domains, add_domain, update_domain, delete_domain,
    get_domain_by_index, update_domain_https,
    get_setting, set_setting, get_all_settings,
)
from scripts.ssl_manager import (
    issue_certificate, check_cert_status,
    renew_certificate, renew_all_certificates,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
csrf = CSRFProtect(app)

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), "logs", "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# --- IP Whitelist ACL ---

def get_client_ip():
    """Get real client IP, supporting X-Forwarded-For and X-Real-IP."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers["X-Real-IP"].strip()
    return request.remote_addr


def get_allowed_ips():
    """Get IP whitelist from settings, fallback to env var."""
    allowed_ips = get_setting("allowed_ips", "")
    if allowed_ips:
        return allowed_ips
    return ADMIN_ALLOWED_IPS


def ip_allowed(f):
    """Decorator: reject requests not in the IP whitelist."""
    @wraps(f)
    def decorated(*args, **kwargs):
        allowed_ips = get_allowed_ips()
        if allowed_ips:
            allowed = [ip.strip() for ip in allowed_ips.split(",")
                       if ip.strip()]
            client_ip = get_client_ip()
            if client_ip not in allowed:
                logger.warning("Blocked access from %s", client_ip)
                if (request.is_json
                        or request.headers.get("X-Requested-With")
                        == "XMLHttpRequest"):
                    return jsonify({"status": "error",
                                    "message": "IP not allowed"}), 403
                return render_template("403.html", message="您的 IP 不在白名单中"), 403
        return f(*args, **kwargs)
    return decorated


# --- Helpers ---

def load_data():
    """Return data in legacy JSON-compatible format."""
    domains = get_all_domains()
    settings = get_all_settings()
    return {"domains": domains, "settings": settings}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if (request.is_json
                    or request.headers.get("X-Requested-With")
                    == "XMLHttpRequest"):
                return jsonify({"status": "error",
                                "message": "Unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def generate_html(domains_data):
    js_routes = ""
    for idx, item in enumerate(domains_data):
        condition = "if" if idx == 0 else "else if"
        js_routes += (
            f"            {condition} (hostname.includes('{item['keyword']}')) {{\n"
            f"                setTheme(\"{item['domain'].upper()}\", \"{item['gradient']}\");\n"
            f"            }}\n"
        )

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noarchive, noindex">
    <title>系统提示</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif; }}
        body {{ background: radial-gradient(circle at top right, #0a1128, #020617); color: #f1f5f9; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: space-between; padding: 2rem 1rem; }}
        .main-content {{ flex: 1; display: flex; align-items: center; justify-content: center; width: 100%; }}
        .container {{ text-align: center; padding: 4rem 2rem; max-width: 500px; width: 100%; background: rgba(255, 255, 255, 0.02); border-radius: 20px; backdrop-filter: blur(15px); border: 1px solid rgba(255, 255, 255, 0.06); box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }}
        .logo {{ font-size: 2.6rem; font-weight: 800; letter-spacing: 1px; margin-bottom: 0.5rem; line-height: 1.2; }}
        .notice-banner {{ display: inline-flex; align-items: center; gap: 8px; margin-top: 1.5rem; padding: 12px 28px; background: linear-gradient(135deg, #ff4d4f, #ff7875); color: #ffffff; font-size: 1.3rem; font-weight: bold; border-radius: 8px; box-shadow: 0 0 25px rgba(255, 77, 79, 0.35); animation: pulse 2s infinite ease-in-out; }}
        .footer {{ text-align: center; font-size: 0.8rem; color: #475569; margin-top: 2rem; width: 100%; letter-spacing: 0.5px; }}
        @keyframes pulse {{ 0% {{ transform: scale(1); box-shadow: 0 0 25px rgba(255, 77, 79, 0.35); }} 50% {{ transform: scale(1.03); box-shadow: 0 0 40px rgba(255, 77, 79, 0.6); }} 100% {{ transform: scale(1); box-shadow: 0 0 25px rgba(255, 77, 79, 0.35); }} }}
        @media (max-width: 480px) {{ .logo {{ font-size: 1.8rem; }} .notice-banner {{ font-size: 1.1rem; padding: 10px 20px; }} }}
    </style>
</head>
<body>
    <div class="main-content">
        <div class="container">
            <div id="web-logo" class="logo">载入中...</div>
            <div class="notice-banner"><span>⚠️</span><span>网站正处于建设中</span></div>
        </div>
    </div>
    <div class="footer"><p>© <span id="current-year"></span> 版权所有</p></div>
    <script>
        (function() {{
            document.getElementById('current-year').innerText = new Date().getFullYear();
            const hostname = window.location.hostname.toLowerCase();
            const logoEl = document.getElementById('web-logo');

{js_routes}
            else {{
                const defaultName = window.location.host.toUpperCase() || "SYSTEM";
                setTheme(defaultName, "linear-gradient(45deg, #9fa8da, #c5cae9)");
            }}

            function setTheme(name, gradient) {{
                document.title = name + " - 网站正处于建设中";
                logoEl.innerText = name;
                logoEl.style.background = gradient;
                logoEl.style.webkitBackgroundClip = "text";
                logoEl.style.webkitTextFillColor = "transparent";
            }}
        }})();
    </script>
</body>
</html>"""
    return html_content


def generate_nginx(domains_data, settings=None):
    """Generate Nginx config: each domain gets its own server block.

    Per-domain HTTPS is self-contained: when https_enabled is True and a
    certificate file exists, the domain listens on both 80 and 443 with
    HTTP→HTTPS 301 redirect.

    Every server block includes the ACME challenge location so Certbot webroot
    validation works regardless of SSL state.
    """
    if settings is None:
        settings = {}
    force_https = True  # Always redirect HTTP→HTTPS when HTTPS is enabled

    blocks = []

    for item in domains_data:
        dom = item["domain"]
        bare = dom.replace("www.", "")
        names = sorted(set([dom, bare]))
        names_str = " ".join(names)

        has_https = item.get("https_enabled", False)

        # Cert may live under bare domain or www.{bare} depending on
        # which domains resolved at issue time. Check both paths.
        bare_cert = os.path.join(SSL_DIR, bare, "fullchain.pem")
        www_cert = os.path.join(SSL_DIR, f"www.{bare}", "fullchain.pem")
        cert_path = bare_cert if os.path.exists(bare_cert) else www_cert
        key_path = cert_path.replace("fullchain.pem", "privkey.pem")
        ssl_ready = has_https and os.path.exists(cert_path)

        acme_block = f"""
    # ACME challenge for Certbot
    location /.well-known/acme-challenge/ {{
        root {WEB_ROOT};
    }}
"""

        if ssl_ready:
            block = f"""server {{
    listen 80;
    server_name {names_str};
{acme_block}
    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    server_name {names_str};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    root {WEB_ROOT};
    index index.html;

    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""
        else:
            block = f"""server {{
    listen 80;
    server_name {names_str};

    root {WEB_ROOT};
    index index.html;
{acme_block}
    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""
        blocks.append(block)

    return "# Auto-generated by RegisGuard\n\n" + "\n".join(blocks)


def get_certbot_email_for_domain(domain):
    """Generate Certbot email using info@{bare_domain} rule."""
    bare = domain.replace("www.", "")
    return f"info@{bare}"


def apply_config():
    """Generate HTML and Nginx config, then reload Nginx."""
    domains = get_all_domains()
    if not domains:
        return False, "No domains configured"

    # Generate and write HTML
    html = generate_html(domains)
    os.makedirs(WEB_ROOT, exist_ok=True)
    with open(os.path.join(WEB_ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Static page generated: %s/index.html", WEB_ROOT)

    # Generate and write Nginx config
    settings = get_all_settings()
    nginx_conf = generate_nginx(domains, settings)
    conf_dir = os.path.dirname(NGINX_CONF_PATH)
    os.makedirs(conf_dir, exist_ok=True)
    with open(NGINX_CONF_PATH, "w", encoding="utf-8") as f:
        f.write(nginx_conf)
    logger.info("Nginx config generated: %s", NGINX_CONF_PATH)

    # Test and reload Nginx
    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if test.returncode == 0:
        subprocess.run(["nginx", "-s", "reload"], capture_output=True)
        logger.info("Nginx reloaded successfully")
        return True, "Nginx reloaded successfully"
    else:
        logger.error("Nginx config test failed: %s", test.stderr)
        return False, f"Nginx config test failed: {test.stderr}"


def check_a_record(domain):
    """Query A record for a domain."""
    query_domain = domain if domain.startswith("www.") else f"www.{domain}"
    try:
        answers = dns.resolver.resolve(query_domain, "A")
        return {
            "domain": query_domain,
            "status": "ok",
            "a_records": [str(rdata) for rdata in answers],
            "ttl": answers.ttl,
        }
    except dns.resolver.NoAnswer:
        return {"domain": query_domain, "status": "no_record",
                "a_records": [], "ttl": None}
    except dns.resolver.NXDOMAIN:
        return {"domain": query_domain, "status": "not_found",
                "a_records": [], "ttl": None}
    except dns.resolver.Timeout:
        return {"domain": query_domain, "status": "timeout",
                "a_records": [], "ttl": None}
    except Exception as e:
        return {"domain": query_domain, "status": "error",
                "a_records": [], "ttl": None, "error": str(e)}


# --- Auto SSL Renewal Background Thread ---

RENEWAL_CHECK_INTERVAL = 86400  # 24 hours
RENEWAL_DAYS_BEFORE_EXPIRY = 30  # renew if expiring within 30 days
RENEWAL_URGENT_DAYS = 5  # must renew before cert fully expires (>5 days)
RENEWAL_URGENT_INTERVAL = 3600  # 1 hour for urgent checks


def parse_cert_expiry(expiry_str):
    """Parse Certbot expiry string to timezone-aware UTC datetime."""
    try:
        dt = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def auto_renew_loop():
    """Background thread that checks and renews expiring certificates.

    Two-tier strategy:
    - Normal: check every 24h, renew if expiring within 30 days
    - Urgent: check every 1h, renew if expiring within 5 days
      (ensures renewal completes before cert fully expires)
    """
    time.sleep(60)  # wait for app to fully start
    logger.info("Auto-renewal thread started (normal: %ds/%dd, "
                "urgent: %ds/%dd)",
                RENEWAL_CHECK_INTERVAL, RENEWAL_DAYS_BEFORE_EXPIRY,
                RENEWAL_URGENT_INTERVAL, RENEWAL_URGENT_DAYS)

    while True:
        try:
            domains = get_all_domains()
            now = datetime.now(timezone.utc)

            renewed = 0
            urgent = False
            for item in domains:
                if not item.get("https_enabled"):
                    continue
                bare = item["domain"].replace("www.", "")
                status = check_cert_status(bare)
                if not status["https_enabled"] or not status.get("expiry"):
                    continue
                expiry_dt = parse_cert_expiry(status["expiry"])
                if not expiry_dt:
                    continue

                days_left = (expiry_dt - now).total_seconds() / 86400

                # Urgent tier: <5 days, must renew immediately
                if days_left <= RENEWAL_URGENT_DAYS:
                    urgent = True
                    logger.warning("Certificate for %s critically expiring "
                                   "(%s left), urgent renewal...",
                                   item["domain"], status["expiry"])
                    result = renew_certificate(item["domain"])
                    if result["status"] == "success":
                        renewed += 1
                        logger.info("Urgent renewal succeeded for %s",
                                    item["domain"])
                    else:
                        logger.error("Urgent renewal failed for %s: %s",
                                     item["domain"], result["message"])
                # Normal tier: <=30 days
                elif days_left <= RENEWAL_DAYS_BEFORE_EXPIRY:
                    logger.info("Certificate for %s expiring soon (%s), "
                                "auto-renewing...",
                                item["domain"], status["expiry"])
                    result = renew_certificate(item["domain"])
                    if result["status"] == "success":
                        renewed += 1
                        logger.info("Auto-renewed certificate for %s",
                                    item["domain"])
                    else:
                        logger.error("Auto-renewal failed for %s: %s",
                                     item["domain"], result["message"])

            if renewed > 0:
                logger.info("Auto-renewal cycle complete: "
                            "%d certificates renewed", renewed)
        except Exception as e:
            logger.error("Auto-renewal thread error: %s", e)

        # Use shorter interval when any cert is in urgent window
        sleep_time = (RENEWAL_URGENT_INTERVAL if urgent
                      else RENEWAL_CHECK_INTERVAL)
        time.sleep(sleep_time)


def start_auto_renew_thread():
    """Start the background auto-renewal thread as a daemon."""
    t = threading.Thread(target=auto_renew_loop, daemon=True,
                         name="ssl-auto-renew")
    t.start()
    logger.info("Auto-renewal background thread launched")


# --- Auth Routes ---

def get_admin_password():
    """Get admin password from settings, fallback to env var."""
    stored = get_setting("admin_password", "")
    if stored:
        return stored
    return ADMIN_PASSWORD


@app.route("/login", methods=["GET", "POST"])
@ip_allowed
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == get_admin_password():
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("Invalid password", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


# --- Main Page ---

@app.route("/")
@login_required
def index():
    domains = get_all_domains()
    settings = get_all_settings()
    return render_template("index.html", domains=domains, settings=settings)


# --- Domain CRUD ---

@app.route("/api/domains", methods=["POST"])
@login_required
def add_domain_route():
    domain = request.json.get("domain", "").strip().lower()
    keyword = request.json.get("keyword", "").strip().lower()
    icp_number = request.json.get("icp_number", "").strip()
    gradient = request.json.get("gradient", "")

    if not domain or not keyword:
        return jsonify({"status": "error",
                        "message": "Domain and keyword are required"}), 400

    success, message = add_domain(domain, keyword, icp_number, gradient)
    if success:
        logger.info("Domain added: %s", domain)
    return jsonify({"status": "success" if success else "error",
                    "message": message})


@app.route("/api/domains/<int:index>", methods=["PUT"])
@login_required
def update_domain_route(index):
    item = get_domain_by_index(index)
    if not item:
        return jsonify({"status": "error", "message": "Domain not found"}), 404

    domain = request.json.get("domain", "").strip().lower()
    keyword = request.json.get("keyword", "").strip().lower()
    icp_number = request.json.get("icp_number", "").strip()
    gradient = request.json.get("gradient", "")

    if not domain or not keyword:
        return jsonify({"status": "error",
                        "message": "Domain and keyword are required"}), 400

    success, message = update_domain(
        item["id"], domain, keyword, icp_number, gradient)
    if success:
        logger.info("Domain updated: %s", domain)
    return jsonify({"status": "success" if success else "error",
                    "message": message})


@app.route("/api/domains/<int:index>", methods=["DELETE"])
@login_required
def delete_domain_route(index):
    item = get_domain_by_index(index)
    if not item:
        return jsonify({"status": "error", "message": "Domain not found"}), 404

    success, message, _ = delete_domain(item["id"])
    if success:
        logger.info("Domain deleted: %s", item["domain"])
    return jsonify({"status": "success" if success else "error",
                    "message": message})


# --- Per-Domain HTTPS Toggle ---

@app.route("/api/domains/<int:index>/https", methods=["PUT"])
@login_required
def toggle_domain_https(index):
    """Toggle per-domain HTTPS. When enabling, auto-triggers certificate
    issuance. If DNS is not ready, returns a warning but keeps HTTPS enabled.
    """
    item = get_domain_by_index(index)
    if not item:
        return jsonify({"status": "error", "message": "Domain not found"}), 404

    enable = request.json.get("https_enabled", False)
    domain = item["domain"]

    success, message, domain_name = update_domain_https(item["id"], enable)
    if not success:
        return jsonify({"status": "error", "message": message}), 404

    if enable:
        email = get_certbot_email_for_domain(domain)
        cert_result = issue_certificate(domain, WEB_ROOT, email)
        if cert_result["status"] != "success":
            # Rollback: revert https_enabled to False
            update_domain_https(item["id"], False)
            logger.warning(
                "HTTPS enabled for %s but certificate issuance failed, "
                "rolled back to HTTP: %s",
                domain, cert_result.get("message", ""))
            return jsonify({
                "status": "error",
                "message": (
                    f"域名 {domain} 证书申请失败，已自动关闭 HTTPS 开关。"
                    f"原因：{cert_result.get('message', '')}"
                ),
                "cert_result": cert_result,
            })
        logger.info("Auto-issued certificate for %s (HTTPS enabled)", domain)
        # Regenerate Nginx config with 443 SSL block and reload
        apply_success, apply_msg = apply_config()
        if not apply_success:
            logger.error("Failed to reload Nginx after cert issue: %s",
                         apply_msg)

    logger.info("Domain %s https_enabled=%s", domain, enable)
    return jsonify({"status": "success", "message": message})


# --- Apply Config ---

@app.route("/api/apply", methods=["POST"])
@login_required
def apply():
    success, message = apply_config()
    return jsonify({"status": "success" if success else "error",
                    "message": message})


# --- Settings ---

@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify({
        "ssl_global_enabled": True,
        "force_https_redirect": True,
        "allowed_ips": get_setting("allowed_ips", ""),
    })


@app.route("/api/settings", methods=["PUT"])
@login_required
def update_settings():
    if "allowed_ips" in request.json:
        set_setting("allowed_ips", request.json["allowed_ips"].strip())
        logger.info("Settings updated: allowed_ips=%s",
                    request.json["allowed_ips"].strip())
    return jsonify({"status": "success", "message": "Settings updated"})


# --- Password Management ---

@app.route("/api/password", methods=["PUT"])
@login_required
def change_password():
    new_password = request.json.get("password", "").strip()
    if not new_password:
        return jsonify({"status": "error", "message": "密码不能为空"}), 400

    set_setting("admin_password", new_password)
    logger.info("Admin password changed")
    return jsonify({"status": "success", "message": "密码修改成功"})


# --- SSL Certificate ---

@app.route("/api/ssl/issue", methods=["POST"])
@login_required
def issue_ssl():
    domain = request.json.get("domain", "")
    if not domain:
        return jsonify({"status": "error",
                        "message": "Domain is required"}), 400

    email = get_certbot_email_for_domain(domain)
    result = issue_certificate(domain, WEB_ROOT, email)

    if result["status"] == "success":
        domains = get_all_domains()
        for d in domains:
            if d["domain"] == domain:
                update_domain_https(d["id"], True)
                break

    return jsonify(result)


@app.route("/api/ssl/renew", methods=["POST"])
@login_required
def renew_ssl():
    domain = request.json.get("domain", "")
    if domain:
        result = renew_certificate(domain)
    else:
        domains = get_all_domains()
        result = renew_all_certificates(domains)
    return jsonify(result)


@app.route("/api/ssl/status", methods=["GET"])
@login_required
def ssl_status():
    domains = get_all_domains()
    results = []
    for item in domains:
        bare = item["domain"].replace("www.", "")
        status = check_cert_status(bare)
        status["https_enabled"] = item.get("https_enabled", False)
        results.append({"domain": item["domain"], **status})
    return jsonify({"certificates": results})


# --- DNS Check ---

@app.route("/api/dns/check", methods=["POST"])
@login_required
def batch_dns_check():
    domains = get_all_domains()
    results = []
    for item in domains:
        result = check_a_record(item["domain"])
        result["gradient"] = item.get("gradient", "")
        result["https_enabled"] = item.get("https_enabled", False)
        results.append(result)

    return jsonify({
        "status": "success",
        "total": len(results),
        "results": results,
        "timestamp": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
    init_db()
    start_auto_renew_thread()
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000)
