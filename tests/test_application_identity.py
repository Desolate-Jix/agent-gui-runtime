from __future__ import annotations

from app.learn.application_identity import normalize_application_identity


def test_browser_identity_uses_canonical_domain_instead_of_edge_process() -> None:
    identity = normalize_application_identity(
        {
            "name": "Microsoft Edge",
            "process": "msedge.exe",
            "url": "https://www.seek.co.nz/jobs?keywords=developer",
        }
    )

    assert identity["kind"] == "web"
    assert identity["identity_key"] == "web:seek.co.nz"
    assert identity["canonical_domain"] == "seek.co.nz"
    assert identity["identity_status"] == "resolved"
    assert identity["executable_identity"] == "msedge.exe"


def test_browser_subdomains_remain_separate_application_identities() -> None:
    mail = normalize_application_identity(
        {"process": "msedge.exe", "url": "https://mail.google.com/mail/u/0/"}
    )
    accounts = normalize_application_identity(
        {"process": "msedge.exe", "url": "https://accounts.google.com/signin"}
    )

    assert mail["identity_key"] == "web:mail.google.com"
    assert accounts["identity_key"] == "web:accounts.google.com"
    assert mail["identity_key"] != accounts["identity_key"]


def test_browser_without_domain_evidence_is_not_grouped_by_browser_process() -> None:
    identity = normalize_application_identity(
        {
            "name": "Microsoft Edge",
            "process": "msedge.exe",
            "window_title": "New tab - Microsoft Edge",
        }
    )

    assert identity["kind"] == "web"
    assert identity["identity_key"] is None
    assert identity["identity_status"] == "needs_domain_review"
    assert identity["canonical_domain"] is None


def test_native_application_uses_executable_and_product_identity() -> None:
    identity = normalize_application_identity(
        {
            "name": "Apple Music",
            "process": "AppleMusic.exe",
            "product": "Apple Music",
        }
    )

    assert identity["kind"] == "native"
    assert identity["identity_key"] == "native:applemusic.exe:apple-music"
    assert identity["identity_status"] == "resolved"
    assert identity["executable_identity"] == "applemusic.exe"
    assert identity["product_identity"] == "apple-music"
