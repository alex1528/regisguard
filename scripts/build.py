#!/usr/bin/env python3
"""Offline build script: reads from SQLite database, generates index.html and Nginx config."""

import json
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BASE_DIR))

from config import WEB_ROOT, NGINX_CONF_PATH, JSON_PATH, SSL_DIR, DB_PATH
from db import init_db, get_all_domains


def generate_html(domains_data):
    js_routes = ""
    for idx, item in enumerate(domains_data):
        condition = "if" if idx == 0 else "else if"
        js_routes += (
            f"            {condition} (hostname.includes('{item['keyword']}')) {{\n"
            f"                setTheme(\"{item['domain'].upper()}\", \"{item['gradient']}\");\n"
            f"            }}\n"
        )

    return f"""<!DOCTYPE html>
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


def generate_nginx(domains_data, settings=None):
    """Generate Nginx config: each domain gets its own server block with its own certificate.

    Every server block includes the ACME challenge location so Certbot webroot
    validation works even when the domain already has SSL enabled.
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

        has_ssl = item.get("https_enabled", False)

        # Cert may live under bare domain or www.{bare} depending on
        # which domains resolved at issue time. Check both paths.
        bare_cert = os.path.join(SSL_DIR, bare, "fullchain.pem")
        www_cert = os.path.join(SSL_DIR, f"www.{bare}", "fullchain.pem")
        cert_path = bare_cert if os.path.exists(bare_cert) else www_cert
        key_path = cert_path.replace("fullchain.pem", "privkey.pem")
        ssl_ready = has_ssl and os.path.exists(cert_path)

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

    return "# Auto-generated by RegisGuard build script\n\n" + "\n".join(blocks)


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    domains = data.get("domains", [])
    if not domains:
        print("[WARN] No domains found in domains.json")
        return

    # Generate HTML
    os.makedirs(WEB_ROOT, exist_ok=True)
    html_path = os.path.join(WEB_ROOT, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(generate_html(domains))
    print(f"[OK] Static page generated: {html_path}")

    # Generate Nginx config
    settings = data.get("settings", {})
    conf_dir = os.path.dirname(NGINX_CONF_PATH)
    os.makedirs(conf_dir, exist_ok=True)
    with open(NGINX_CONF_PATH, "w", encoding="utf-8") as f:
        f.write(generate_nginx(domains, settings))
    print(f"[OK] Nginx config generated: {NGINX_CONF_PATH}")

    # Test and reload Nginx
    print("Testing Nginx config...")
    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if test.returncode == 0:
        subprocess.run(["nginx", "-s", "reload"], capture_output=True)
        print("[OK] Nginx reloaded successfully")
    else:
        print(f"[ERROR] Nginx config test failed:\n{test.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
