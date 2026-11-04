"""Per-test X.509 credentials for a secured sjd: a certificate authority, the server
certificate, one client certificate per principal, and the policy granting each principal the
reader, writer and corrector roles in its namespaces."""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SERVER_NAME = "sjd.test"
DATA_ROLES = ["reader", "writer", "corrector"]


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _usage(*, authority: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=not authority, content_commitment=False, key_encipherment=False,
        data_encipherment=False, key_agreement=False, key_cert_sign=authority,
        crl_sign=authority, encipher_only=False, decipher_only=False,
    )


def _builder(subject: str, issuer: x509.Name, key: ec.EllipticCurvePrivateKey) -> x509.CertificateBuilder:
    now = datetime.datetime.now(datetime.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
    )


class Credentials:
    """PEM files and policy.json in `directory`. `grants` maps each principal to the
    (tenant, space) namespaces it may use."""

    def __init__(self, directory: Path, grants: dict[str, list[tuple[str, str]]]) -> None:
        directory.mkdir(parents=True)
        self.directory = directory
        self._ca_key = ec.generate_private_key(ec.SECP256R1())
        self._ca = (
            _builder("alexandria test CA", _name("alexandria test CA"), self._ca_key)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(_usage(authority=True), critical=True)
            .sign(self._ca_key, hashes.SHA256())
        )
        self.path("ca.pem").write_bytes(self._ca.public_bytes(serialization.Encoding.PEM))
        server_names = [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName(SERVER_NAME)]
        self._leaf("server", ExtendedKeyUsageOID.SERVER_AUTH, server_names)
        principals = [
            {
                "name": name,
                "certificate_sha256": self._leaf(name, ExtendedKeyUsageOID.CLIENT_AUTH, []),
                "namespaces": [
                    {"tenant": tenant, "space": space, "roles": DATA_ROLES}
                    for tenant, space in namespaces
                ],
            }
            for name, namespaces in grants.items()
        ]
        policy = {"format": "spacejar-memory-policy", "version": 1, "principals": principals}
        self.path("policy.json").write_text(json.dumps(policy))

    def path(self, name: str) -> Path:
        return self.directory / name

    def _leaf(self, name: str, usage: x509.ObjectIdentifier, names: list[x509.GeneralName]) -> str:
        """Writes `name`.pem and `name`.key; returns the SHA-256 of the certificate's DER."""
        key = ec.generate_private_key(ec.SECP256R1())
        builder = (
            _builder(name, self._ca.subject, key)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(_usage(authority=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        )
        if names:
            builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
        certificate = builder.sign(self._ca_key, hashes.SHA256())
        self.path(f"{name}.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        self.path(f"{name}.key").write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
