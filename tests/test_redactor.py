"""Tests for log redaction patterns."""

from llmwiki.core.secrets.redactor import REDACTED, Redactor


class TestRedactor:
    def setup_method(self) -> None:
        self.r = Redactor()

    def test_bearer_token(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.stuff.sig"
        result = self.r.redact(text)
        assert "eyJ" not in result
        assert REDACTED in result

    def test_github_pat_classic(self) -> None:
        text = "token=ghp_abcdefghijklmnop1234567890"
        result = self.r.redact(text)
        assert "ghp_" not in result

    def test_github_pat_fine_grained(self) -> None:
        text = "github_pat_11ABCDEFG0abcdefghijklmno"
        result = self.r.redact(text)
        assert "github_pat" not in result

    def test_anthropic_key(self) -> None:
        text = "key: sk-ant-api03-abcdefghijklmnopqrstuvwx"
        result = self.r.redact(text)
        assert "sk-ant" not in result

    def test_openai_key(self) -> None:
        text = "sk-1234567890abcdefghijklmnop"
        result = self.r.redact(text)
        assert "sk-1234" not in result

    def test_api_key_in_url(self) -> None:
        text = "https://api.example.com/v1?api_key=secret123&other=val"
        result = self.r.redact(text)
        assert "secret123" not in result
        assert "other=val" in result

    def test_password_field(self) -> None:
        text = "password=my_secret_password"
        result = self.r.redact(text)
        assert "my_secret_password" not in result

    def test_client_secret(self) -> None:
        text = "client_secret=abcdef12345"
        result = self.r.redact(text)
        assert "abcdef12345" not in result

    def test_jwt_token(self) -> None:
        text = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123abc"
        result = self.r.redact(text)
        assert "eyJhbGci" not in result

    def test_aws_key(self) -> None:
        text = "AKIAIOSFODNN7EXAMPLE"
        result = self.r.redact(text)
        assert "AKIAIOSFODNN7" not in result

    def test_no_false_positives(self) -> None:
        text = "This is a normal log message with no secrets."
        assert self.r.redact(text) == text

    def test_preserves_context(self) -> None:
        text = "Connection to host:8080 failed"
        assert self.r.redact(text) == text
