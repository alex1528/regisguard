import subprocess
import os
import logging
from datetime import datetime

import dns.resolver

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


def issue_certificate(domain, webroot=None, email=None):
    """Use Certbot webroot mode to request a per-domain certificate.

    Only includes domains that actually resolve (have A/AAAA records).
    If neither the www nor bare domain resolves, returns an error.
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

    domains_to_request = []
    if www_ok:
        domains_to_request.extend(["-d", www_domain])
    if bare_ok:
        domains_to_request.extend(["-d", bare_domain])

    cmd = [
        CERTBOT, "certonly",
        "--webroot", "-w", webroot,
    ] + domains_to_request + [
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
        return {
            "status": "success",
            "message": f"Certificate for {domain} issued successfully",
            "cert_path": f"/etc/letsencrypt/live/{bare_domain}/fullchain.pem",
            "key_path": f"/etc/letsencrypt/live/{bare_domain}/privkey.pem",
        }
    logger.error("Certificate issue failed for %s: %s", domain, result.stderr)
    return {"status": "error", "message": result.stderr}


def check_cert_status(bare_domain):
    """Check certificate existence and expiry for a domain."""
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
    """Renew certificate for a domain."""
    webroot = webroot or DEFAULT_WEBROOT
    bare_domain = domain.replace("www.", "")
    cert_path = f"/etc/letsencrypt/live/{bare_domain}/cert.pem"

    if not os.path.exists(cert_path):
        return {"status": "error",
                "message": f"No certificate found for {bare_domain}"}

    www_domain = f"www.{bare_domain}"
    www_ok = _check_domain_resolvable(www_domain)
    bare_ok = _check_domain_resolvable(bare_domain)

    domains_to_request = []
    if www_ok:
        domains_to_request.extend(["-d", www_domain])
    if bare_ok:
        domains_to_request.extend(["-d", bare_domain])

    if not domains_to_request:
        msg = (f"Neither {www_domain} nor {bare_domain} resolves, "
               f"skipping renewal")
        logger.warning("Certificate renewal skipped for %s: %s", domain, msg)
        return {"status": "error", "message": msg}

    cmd = [
        CERTBOT, "certonly",
        "--webroot", "-w", webroot,
    ] + domains_to_request + [
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
            cert_path = f"/etc/letsencrypt/live/{bare}/cert.pem"
            if os.path.exists(cert_path):
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
