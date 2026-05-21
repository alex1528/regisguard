import subprocess
import os
import logging
from datetime import datetime

import dns.resolver

from config import SSL_DIR

logger = logging.getLogger(__name__)

CERTBOT = "/usr/bin/certbot"
DEFAULT_WEBROOT = "/var/www/construction_page"


def _check_domain_resolvable(domain):
    """Check if a domain has a valid A or AAAA record."""
    for record_type in ("A", "AAAA"):
        try:
            dns.resolver.resolve(domain, record_type)
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN,
                dns.resolver.Timeout):
            continue
    return False


def _get_cert_path(domain):
    """Find the actual cert directory for a domain (bare or www prefix)."""
    bare = domain.replace("www.", "")
    bare_cert = os.path.join(SSL_DIR, bare, "fullchain.pem")
    www_cert = os.path.join(SSL_DIR, f"www.{bare}", "fullchain.pem")
    if os.path.exists(bare_cert):
        return bare_cert
    if os.path.exists(www_cert):
        return www_cert
    return None


def issue_certificate(domain, webroot=None, email=None):
    """Use Certbot webroot mode to request a per-domain certificate.

    Checks DNS resolution for www.{bare} and {bare} independently.
    Only resolvable domains are included in the certbot -d list, so
    the request succeeds even if one side lacks DNS. Both names are
    requested together in a single certbot call (same certificate).
    If neither resolves, returns an error without calling certbot.
    """
    webroot = webroot or DEFAULT_WEBROOT
    bare_domain = domain.replace("www.", "")
    if email is None:
        email = f"info@{bare_domain}"

    www_domain = f"www.{bare_domain}"
    www_ok = _check_domain_resolvable(www_domain)
    bare_ok = _check_domain_resolvable(bare_domain)

    if not www_ok and not bare_ok:
        msg = (
            f"Neither {www_domain} nor {bare_domain} has a valid A/AAAA "
            f"record. Please configure DNS before enabling HTTPS."
        )
        logger.error("Certificate issue skipped for %s: %s", domain, msg)
        return {"status": "error", "message": msg}

    # Build -d list conditionally based on DNS resolution.
    # Both domains belong to the same certificate; only include
    # resolvable ones to avoid Certbot validation failures.
    domains_to_request = []
    if www_ok:
        domains_to_request.extend(["-d", www_domain])
    if bare_ok:
        domains_to_request.extend(["-d", bare_domain])

    cmd = [
        CERTBOT, "certonly",
        "--webroot", "-w", webroot,
        *domains_to_request,
        "--non-interactive",
        "--agree-tos",
        "--email", email,
        "--force-renewal",
    ]

    logger.info("Requesting certificate for %s (www_ok=%s, bare_ok=%s)",
                domain, www_ok, bare_ok)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        logger.info("Certificate issued for %s", domain)
        # Certbot creates the directory using the first -d argument.
        cert_dir = _get_cert_path(domain)
        cert_path = cert_dir if cert_dir else (
            f"/etc/letsencrypt/live/{bare_domain}/fullchain.pem"
        )
        key_path = cert_path.replace("fullchain.pem", "privkey.pem")
        return {
            "status": "success",
            "message": f"Certificate for {domain} issued successfully",
            "cert_path": cert_path,
            "key_path": key_path,
        }
    logger.error("Certificate issue failed for %s: %s", domain, result.stderr)
    return {"status": "error", "message": result.stderr}


def check_cert_status(bare_domain):
    """Check certificate existence and expiry for a domain."""
    cert_path = _get_cert_path(bare_domain)
    if not cert_path:
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
    """Renew certificate for a domain."""
    webroot = webroot or DEFAULT_WEBROOT
    bare_domain = domain.replace("www.", "")

    cert_path = _get_cert_path(domain)
    if not cert_path:
        return {"status": "error",
                "message": f"No certificate found for {bare_domain}"}

    www_domain = f"www.{bare_domain}"
    www_ok = _check_domain_resolvable(www_domain)
    bare_ok = _check_domain_resolvable(bare_domain)

    if not www_ok and not bare_ok:
        msg = (f"Neither {www_domain} nor {bare_domain} resolves, "
               f"skipping renewal")
        logger.warning("Certificate renewal skipped for %s: %s", domain, msg)
        return {"status": "error", "message": msg}

    # Build -d list conditionally based on DNS resolution.
    domains_to_request = []
    if www_ok:
        domains_to_request.extend(["-d", www_domain])
    if bare_ok:
        domains_to_request.extend(["-d", bare_domain])

    cmd = [
        CERTBOT, "certonly",
        "--webroot", "-w", webroot,
        *domains_to_request,
        "--non-interactive",
        "--agree-tos",
        "--force-renewal",
        "--deploy-hook", "nginx -s reload",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        logger.info("Certificate renewed for %s", domain)
        return {"status": "success",
                "message": f"Certificate for {domain} renewed successfully"}
    logger.error("Certificate renewal failed for %s: %s", domain, result.stderr)
    return {"status": "error", "message": result.stderr}


def renew_all_certificates(domains_data, webroot=None):
    """Renew certificates for all domains that have SSL enabled."""
    webroot = webroot or DEFAULT_WEBROOT
    results = []
    for item in domains_data:
        if item.get("https_enabled"):
            bare = item["domain"].replace("www.", "")
            cert_path = _get_cert_path(item["domain"])
            if cert_path:
                result = renew_certificate(item["domain"], webroot)
                results.append({"domain": item["domain"], **result})
            else:
                results.append({"domain": item["domain"], "status": "skipped",
                                "message": "No certificate found"})

    if not results:
        return {"status": "success",
                "message": "No SSL-enabled domains to renew"}

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "success" if success_count > 0 else "error",
        "message": f"Renewed {success_count}/{len(results)} certificates",
        "details": results,
    }
