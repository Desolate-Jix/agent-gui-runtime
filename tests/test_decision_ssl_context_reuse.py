"""默认 CA 上下文复用与本机 TLS 验证，不读取真实凭据或访问外网。"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import ssl
from threading import RLock, Thread

import certifi
import httpx
import pytest

from app.judgment import http_deadline as module
from tests.test_decision_connection_reuse import _loopback_server, loopback_network_only


@pytest.fixture
def ca_bundle(tmp_path, monkeypatch):
    bundle = b"# bundle A\n" + Path(certifi.where()).read_bytes()
    path = tmp_path / "ca.pem"
    path.write_bytes(bundle)
    monkeypatch.setattr(certifi, "where", lambda: str(path))
    monkeypatch.setattr(module, "_DEFAULT_SSL_CONTEXTS", OrderedDict(), raising=False)
    monkeypatch.setattr(module, "_DEFAULT_SSL_LOCK", RLock(), raising=False)
    return path, bundle


@pytest.fixture
def ca_loads(monkeypatch):
    calls = []
    original = ssl.create_default_context

    def create(*args, **kwargs):
        calls.append(kwargs.get("cafile"))
        return original(*args, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", create)
    return calls


def test_second_transport_reuses_verified_context_but_owns_an_independent_pool(ca_bundle, ca_loads):
    first = module.DeadlineHTTPTransport()
    second = module.DeadlineHTTPTransport()
    try:
        assert len(ca_loads) == 1
        assert first._transport._pool is not second._transport._pool
        context = first._transport._pool._ssl_context
        assert context is second._transport._pool._ssl_context
        assert context.check_hostname is True and context.verify_mode == ssl.CERT_REQUIRED
        with _loopback_server() as (url, state):
            with httpx.Client(transport=first) as client:
                assert client.post(url + "/v1/decisions", json={}).status_code == 200
            with httpx.Client(transport=second) as client:
                assert client.post(url + "/v1/decisions", json={}).status_code == 200
                assert client.post(url + "/v1/decisions", json={}).status_code == 200
        assert [item["connection"] for item in state.requests] == [1, 2, 2]
    finally:
        first.close()
        second.close()


def test_same_path_size_and_mtime_with_changed_ca_bytes_reloads(ca_bundle, ca_loads):
    path, bundle = ca_bundle
    first = module.DeadlineHTTPTransport()
    original_stat = path.stat()
    path.write_bytes(bundle.replace(b"# bundle A", b"# bundle B", 1))
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = module.DeadlineHTTPTransport()
    try:
        assert len(ca_loads) == 2
        assert first._transport._pool._ssl_context is not second._transport._pool._ssl_context
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("fault", ["corrupt", "missing"])
def test_corrupt_or_unreadable_ca_does_not_reuse_old_context(ca_bundle, fault):
    path, _ = ca_bundle
    first = module.DeadlineHTTPTransport()
    try:
        if fault == "corrupt":
            path.write_bytes(b"invalid certificate bundle")
        else:
            path.unlink()
        with pytest.raises(OSError):
            module.DeadlineHTTPTransport()
    finally:
        first.close()


def test_ca_change_during_load_is_not_cached(ca_bundle, monkeypatch):
    path, bundle = ca_bundle
    original = ssl.create_default_context
    calls = []

    def changed(*args, **kwargs):
        calls.append(1)
        context = original(*args, **kwargs)
        path.write_bytes(bundle.replace(b"# bundle A", b"# bundle B", 1))
        return context

    monkeypatch.setattr(ssl, "create_default_context", changed)
    with pytest.raises(OSError, match="decision_ca_bundle_changed"):
        module.DeadlineHTTPTransport()
    assert module._DEFAULT_SSL_CONTEXTS == {}
    transport = module.DeadlineHTTPTransport()
    transport.close()
    assert len(calls) == 2


def test_concurrent_transports_load_ca_once(ca_bundle, ca_loads):
    with ThreadPoolExecutor(max_workers=4) as workers:
        transports = list(workers.map(lambda _: module.DeadlineHTTPTransport(), range(4)))
    try:
        assert len(ca_loads) == 1
        assert len({id(t._transport._pool) for t in transports}) == 4
        assert len({id(t._transport._pool._ssl_context) for t in transports}) == 1
    finally:
        for transport in transports:
            transport.close()


def test_ca_context_cache_is_bounded(ca_bundle, ca_loads, tmp_path, monkeypatch):
    _, bundle = ca_bundle
    paths = []
    for number in range(5):
        path = tmp_path / f"ca-{number}.pem"
        path.write_bytes(bundle)
        paths.append(path)
        monkeypatch.setattr(certifi, "where", lambda _path=path: str(_path))
        transport = module.DeadlineHTTPTransport()
        transport.close()
    assert len(module._DEFAULT_SSL_CONTEXTS) <= 4
    monkeypatch.setattr(certifi, "where", lambda: str(paths[0]))
    transport = module.DeadlineHTTPTransport()
    transport.close()
    assert len(ca_loads) == 6


@pytest.mark.parametrize("patch", [
    {"verify": False}, {"verify": "custom.pem"}, {"trust_env": True},
    {"cert": "client.pem"}, {"http1": False}, {"http2": True}])
def test_nondefault_policy_is_left_to_httpx_without_shared_context(ca_bundle, ca_loads, patch):
    options = {"trust_env": False, **patch}
    before = dict(options)
    assert module._shared_default_ssl_context(options) is None
    assert options == before and ca_loads == []


@pytest.fixture
def tls_material(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from ipaddress import ip_address

    def generate(name, issuer_cert=None, issuer_key=None, *, is_ca=False, correct_host=True):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = datetime.now(timezone.utc)
        builder = (x509.CertificateBuilder().subject_name(subject)
            .issuer_name(issuer_cert.subject if issuer_cert else subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2)).add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), True))
        if not is_ca:
            builder = builder.add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ip_address("127.0.0.1")) if correct_host else x509.DNSName("wrong.invalid")]), False)
        cert = builder.sign(issuer_key or key, hashes.SHA256())
        cert_path, key_path = tmp_path / (name + ".pem"), tmp_path / (name + ".key")
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        return cert, key, cert_path, key_path

    ca = generate("test-ca", is_ca=True)
    other_ca = generate("other-ca", is_ca=True)
    good = generate("good-host", ca[0], ca[1])
    wrong = generate("wrong-host", ca[0], ca[1], correct_host=False)
    return ca, other_ca, good, wrong


@contextmanager
def tls_server(cert_path, key_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


@pytest.mark.parametrize("case", ["trusted", "untrusted", "hostname_mismatch"])
def test_shared_context_keeps_real_tls_certificate_and_hostname_checks(
        ca_bundle, tls_material, monkeypatch, case):
    ca, other_ca, good, wrong = tls_material
    selected_ca = other_ca if case == "untrusted" else ca
    monkeypatch.setattr(certifi, "where", lambda: str(selected_ca[2]))
    first = module.DeadlineHTTPTransport()
    second = module.DeadlineHTTPTransport()
    first.close()
    server_material = wrong if case == "hostname_mismatch" else good
    try:
        with tls_server(server_material[2], server_material[3]) as url:
            with httpx.Client(transport=second) as client:
                if case == "trusted":
                    assert client.post(url, json={}).status_code == 200
                else:
                    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                        client.post(url, json={})
    finally:
        second.close()
