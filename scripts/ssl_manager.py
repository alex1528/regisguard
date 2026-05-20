import subprocess
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CERTBOT = "/usr/bin/certbot"
DEFAULT_WEBROOT = "/var/www/construction_page"


def issue_certificate(domain, webroot=None, email=None):
    """Use Certbot webroot mode to request a per-domain certificate."""
    webroot = webroot or DEFAULT_WEBROOT
    bare_domain = domain.replace("www.", "")
    if email is None:
        email = f"info@{bare_domain}"

    cmd = [
        CERTBOT, "certonly",
        "--webroot", "-w", webroot,
        "-d", f"www.{bare_domain}",
        "-d", bare_domain,
        "--non-interactive",
        "--agree-tos",
        "--email", email,
        "--force-renewal",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        logger.info("Certificate issued for %s", domain)
        return {
            "status": "success",
            "message": f"Certificate for {domain} issued successfully",
            "cert_path": f"/etc/letsencrypt/live/{bare_domain}/fullchain.pem",
            "key_path": f"/etc/letsencrypt/live/{bare_domain}/privkey.pem",
        }
    logger.error("Certificate issue failed for %s: %s", domain, result.stderr)
    return {"status": "error", "message": result.stderr}


def check_cert_status(bare_domain):
    """Check if a certificate exists for the given domain, including expiry info."""
    cert_path = f"/etc/letsencrypt/live/{bare_domain}/cert.pem"
    if not os.path.exists(cert_path):
        return {"https_enabled": False, "status": "no_cert", "expiry": None}

    # Parse expiry date from the certificate file
    expiry = None
    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", cert_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            # Output: notAfter=Jun 15 12:00:00 2025 GMT
            expiry_str = result.stdout.strip().split("=", 1)[1]
            expiry = expiry_str
    except Exception:
        pass

    return {"https_enabled": True, "status": "active", "expiry": expiry}


def renew_certificate(domain, webroot=None):
    """Renew certificate for a specific domain. Replaces the cert and reloads Nginx."""
    webroot = webroot or DEFAULT_WEBROOT
    bare_domain = domain.replace("www.", "")
    cert_path = f"/etc/letsencrypt/live/{bare_domain}/cert.pem"

    if not os.path.exists(cert_path):
        return {"status": "error", "message": f"No certificate found for {bare_domain}"}

    cmd = [
        CERTBOT, "certonly",
        "--webroot", "-w", webroot,
        "-d", f"www.{bare_domain}",
        "-d", bare_domain,
        "--non-interactive",
        "--agree-tos",
        "--force-renewal",
        "--deploy-hook", "nginx -s reload",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        logger.info("Certificate renewed for %s", domain)
        return {"status": "success", "message": f"Certificate for {domain} renewed successfully"}
    logger.error("Certificate renewal failed for %s: %s", domain, result.stderr)
    return {"status": "error", "message": result.stderr}


def renew_all_certificates(domains_data, webroot=None):
    """Renew certificates for all domains that have SSL enabled."""
    webroot = webroot or DEFAULT_WEBROOT
    results = []
    for item in domains_data:
        if item.get("https_enabled"):
            bare = item["domain"].replace("www.", "")
            cert_path = f"/etc/letsencrypt/live/{bare}/cert.pem"
            if os.path.exists(cert_path):
                result = renew_certificate(item["domain"], webroot)
                results.append({"domain": item["domain"], **result})
            else:
                results.append({"domain": item["domain"], "status": "skipped", "message": "No certificate found"})

    if not results:
        return {"status": "success", "message": "No SSL-enabled domains to renew"}

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "success" if success_count > 0 else "error",
        "message": f"Renewed {success_count}/{len(results)} certificates",
        "details": results,
    }
