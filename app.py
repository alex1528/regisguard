import json
import os
import re
import subprocess
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

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


# --- Token helpers (Construction_Page inlining) ---

TOKENS_CSS_PATH = Path(__file__).parent / "static" / "css" / "tokens.css"
# Matches a single ``--rg-*`` custom-property declaration, capturing the
# token name (group 1) and its raw value (group 2). The ``[a-z0-9-]+``
# character class enforces the project convention of lowercase token
# names; uppercase or other prefixes are intentionally not matched.
RG_TOKEN_PATTERN = re.compile(r"(--rg-[a-z0-9-]+)\s*:\s*([^;]+);")


def _load_tokens_css():
    """Return the contents of ``static/css/tokens.css``.

    Construction_Page generation must never crash when ``tokens.css`` is
    missing or unreadable. ``OSError`` (covering both ``FileNotFoundError``
    and ``PermissionError``) is caught, logged at ``ERROR`` level, and
    surfaces as an empty string so callers can continue with degraded
    behaviour rather than aborting ``apply_config``.
    """
    try:
        return TOKENS_CSS_PATH.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("Failed to read tokens.css at %s: %s",
                     TOKENS_CSS_PATH, e)
        return ""


def _extract_tokens(css_text):
    """Parse ``css_text`` into ``{selector: {token_name: token_value}}``.

    The result groups every ``--rg-*`` custom property by the
    (top-level) selector block it appears in. Values are ``strip()``-ed
    so leading / trailing whitespace does not affect later comparison;
    internal whitespace inside the value is preserved verbatim. Token
    names are case-sensitive — the regex enforces lowercase per project
    convention.

    Robustness contract: on malformed input (unbalanced braces, missing
    semicolons, junk between declarations) the function never raises.
    Instead it returns the largest parseable subset, which is exactly
    what the design's "解析失败时返回最大可解析子集" rule asks for.
    """
    result = {}
    if not css_text:
        return result

    # Strip block comments first; otherwise tokens declared *inside* a
    # comment (e.g. examples, deprecated values) would leak into the
    # output. ``re.DOTALL`` lets ``.`` cross newlines.
    cleaned = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)

    pos = 0
    length = len(cleaned)
    while pos < length:
        brace_open = cleaned.find("{", pos)
        if brace_open == -1:
            break
        selector = cleaned[pos:brace_open].strip()

        # Walk braces to find the matching ``}``. Plain rule bodies have
        # no nested blocks, but ``@media`` / ``@supports`` wrappers do —
        # depth tracking lets the loop skip past those wrappers cleanly
        # when they appear at the top level (their inner ``--rg-*``
        # declarations are picked up via their own selector pass once we
        # advance ``pos`` past the wrapper).
        depth = 1
        i = brace_open + 1
        while i < length and depth > 0:
            ch = cleaned[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body_end = i - 1 if depth == 0 else length
        body = cleaned[brace_open + 1:body_end]

        if selector:
            tokens = {}
            for match in RG_TOKEN_PATTERN.finditer(body):
                name = match.group(1)
                value = match.group(2).strip()
                tokens[name] = value
            if tokens:
                # Same selector may appear in multiple blocks; merge with
                # last-write-wins semantics matching the CSS cascade.
                if selector in result:
                    result[selector].update(tokens)
                else:
                    result[selector] = tokens

        pos = i

    return result


def _compare_tokens(source, inlined):
    """Return token names that differ between ``source`` and ``inlined``.

    Both inputs are the per-selector dictionaries returned by
    ``_extract_tokens``. A name is reported when, in any selector group
    appearing on either side, the token is missing on one side or its
    value differs after ``strip()`` (character-by-character, case
    preserved). Returned names are de-duplicated while preserving first-
    seen order so the resulting list reads cleanly in log output, e.g.
    ``logger.warning("...: %s", names)``.

    An empty list means the two sides are equivalent under the design's
    comparison rule (token name set equality + per-token value equality
    after ``strip()``).
    """
    inconsistent = []
    seen = set()

    selectors = set(source.keys()) | set(inlined.keys())
    for selector in selectors:
        src_tokens = source.get(selector, {})
        inl_tokens = inlined.get(selector, {})
        names = set(src_tokens.keys()) | set(inl_tokens.keys())
        for name in names:
            src_val = src_tokens.get(name)
            inl_val = inl_tokens.get(name)
            if src_val is None or inl_val is None:
                differs = True
            else:
                differs = src_val.strip() != inl_val.strip()
            if differs and name not in seen:
                inconsistent.append(name)
                seen.add(name)

    return inconsistent


def generate_html(domains_data):
    js_routes = ""
    for idx, item in enumerate(domains_data):
        condition = "if" if idx == 0 else "else if"
        js_routes += (
            f"            {condition} (hostname.includes('{item['keyword']}')) {{\n"
            f"                setTheme(\"{item['domain'].upper()}\", \"{item['gradient']}\");\n"
            f"            }}\n"
        )

    # Read the canonical tokens.css and prepare to inline it verbatim.
    # When the file is missing _load_tokens_css already logged ERROR and
    # returned ""; the page still renders (var(--rg-*) references fall
    # through to browser defaults) so apply_config stays non-blocking.
    tokens_text = _load_tokens_css()
    source_tokens = _extract_tokens(tokens_text)

    # Public-page FOUC suppression script — matchMedia only. The
    # Construction_Page is shown to anonymous visitors so we deliberately
    # do not read or write localStorage and never reference the
    # ``regisguard-theme`` storage key (Property 14, R3.10/R4.3).
    fouc_script = """    <script>
    (function () {
        var resolved = 'light';
        try {
            var mql = window.matchMedia('(prefers-color-scheme: dark)');
            if (mql && mql.matches) resolved = 'dark';
        } catch (e) { /* matchMedia unavailable: keep light */ }
        document.documentElement.setAttribute('data-theme', resolved);
    })();
    </script>"""

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noarchive, noindex">
    <title>系统提示</title>
    <style>
{tokens_text}
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: var(--rg-font-family); }}
        body {{ background: var(--rg-color-bg-default); color: var(--rg-color-fg-default); min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: space-between; padding: var(--rg-space-lg) var(--rg-space-md); }}
        .main-content {{ flex: 1; display: flex; align-items: center; justify-content: center; width: 100%; }}
        .container {{ text-align: center; padding: 4rem var(--rg-space-lg); max-width: 500px; width: 100%; background: var(--rg-color-bg-surface); border: 1px solid var(--rg-color-border-default); border-radius: var(--rg-radius-lg); box-shadow: var(--rg-shadow-lg); }}
        .logo {{ font-size: 2.6rem; font-weight: 800; letter-spacing: 1px; margin-bottom: var(--rg-space-sm); line-height: 1.2; }}
        .notice-banner {{ display: inline-flex; align-items: center; gap: var(--rg-space-sm); margin-top: var(--rg-space-lg); padding: 12px 28px; background: var(--rg-color-danger); color: var(--rg-color-on-accent); font-size: var(--rg-font-size-lg); font-weight: bold; border-radius: var(--rg-radius-md); box-shadow: var(--rg-shadow-lg); animation: pulse 2s infinite ease-in-out; }}
        .footer {{ text-align: center; font-size: var(--rg-font-size-sm); color: var(--rg-color-fg-muted); margin-top: var(--rg-space-lg); width: 100%; letter-spacing: 0.5px; }}
        @keyframes pulse {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(1.03); }} 100% {{ transform: scale(1); }} }}
        @media (max-width: 480px) {{ .logo {{ font-size: 1.8rem; }} .notice-banner {{ font-size: var(--rg-font-size-base); padding: var(--rg-space-sm) var(--rg-space-md); }} }}
        @supports not (background-clip: text) {{ .logo {{ color: var(--rg-color-fg-default); -webkit-text-fill-color: var(--rg-color-fg-default); }} }}
        /* :focus-visible 焦点指示器（R12.2、R12.3、R12.4）。
           本页面无交互元素，但保留通用规则与其余 CSS 源保持一致。 */
        :focus-visible {{ outline: 2px solid var(--rg-color-focus-ring); outline-offset: 2px; }}
        /* Reduced-motion (Property 21, R13.1–R13.4)：!important 仅作用于动效时长，
           不用于颜色（不违反 R11.5）。.notice-banner 关停 pulse 动画并消除 transform，
           保留 background / color / border-radius / box-shadow 作为视觉强调。 */
        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                transition-duration: 0.01s !important;
                animation-duration: 0.01s !important;
                animation-iteration-count: 1 !important;
            }}
            .notice-banner {{ animation: none; transform: none; }}
        }}
    </style>
{fouc_script}
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
                setTheme(defaultName, "linear-gradient(45deg, var(--rg-color-accent), var(--rg-color-accent-hover))");
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

    # Re-parse the emitted <style> block to verify the inlined tokens
    # match the canonical source. The check is informational — it must
    # never block apply_config; on drift we just log a WARNING so ops
    # can investigate (R10.5/R10.6, Property 12).
    style_match = re.search(r"<style[^>]*>(.*?)</style>",
                            html_content, re.DOTALL)
    inlined_tokens = (
        _extract_tokens(style_match.group(1)) if style_match else {}
    )
    drift = _compare_tokens(source_tokens, inlined_tokens)
    if drift:
        logger.warning("Construction page tokens out of sync: %s", drift)

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
    gradient = request.json.get("gradient", "")

    if not domain or not keyword:
        return jsonify({"status": "error",
                        "message": "Domain and keyword are required"}), 400

    success, message = add_domain(domain, keyword, gradient)
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
    gradient = request.json.get("gradient", "")

    if not domain or not keyword:
        return jsonify({"status": "error",
                        "message": "Domain and keyword are required"}), 400

    success, message = update_domain(item["id"], domain, keyword, gradient)
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
