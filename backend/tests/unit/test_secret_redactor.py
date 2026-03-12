"""
Unit tests for app/services/secret_redactor.py

Covers all secret patterns and edge cases.
"""
import pytest

from app.services.secret_redactor import redact_secrets


class TestRedactSecrets:
    def test_empty_string_returns_unchanged(self):
        result, count = redact_secrets("")
        assert result == ""
        assert count == 0

    def test_none_returns_unchanged(self):
        result, count = redact_secrets(None)
        assert result is None
        assert count == 0

    def test_clean_text_returns_unchanged(self):
        text = "This is a normal log message with no secrets."
        result, count = redact_secrets(text)
        assert result == text
        assert count == 0

    def test_aws_access_key_redacted(self):
        text = "Using key AKIAIOSFODNN7EXAMPLE for auth"
        result, count = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED]" in result
        assert count >= 1

    def test_aws_secret_access_key_redacted(self):
        text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result, count = redact_secrets(text)
        assert "wJalrXUtnFEMI" not in result
        assert "[REDACTED]" in result
        assert count >= 1

    def test_password_kv_redacted(self):
        text = "Connecting with password=supersecret123"
        result, count = redact_secrets(text)
        assert "supersecret123" not in result
        assert "[REDACTED]" in result
        assert count >= 1

    def test_password_colon_redacted(self):
        text = "password: mysecretpassword"
        result, count = redact_secrets(text)
        assert "mysecretpassword" not in result
        assert count >= 1

    def test_secret_kv_redacted(self):
        text = "secret=abcdefghij1234"
        result, count = redact_secrets(text)
        assert "abcdefghij1234" not in result
        assert "[REDACTED]" in result
        assert count >= 1

    def test_api_key_redacted(self):
        text = "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
        result, count = redact_secrets(text)
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result
        assert count >= 1

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
        result, count = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert count >= 1

    def test_generic_token_kv_redacted(self):
        text = "token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result, count = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert count >= 1

    def test_pem_private_key_header_redacted(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK..."
        result, count = redact_secrets(text)
        assert "-----BEGIN RSA PRIVATE KEY-----" not in result
        assert count >= 1

    def test_pem_ec_private_key_header_redacted(self):
        text = "-----BEGIN EC PRIVATE KEY-----"
        result, count = redact_secrets(text)
        assert "-----BEGIN EC PRIVATE KEY-----" not in result
        assert count >= 1

    def test_pem_openssh_private_key_header_redacted(self):
        text = "-----BEGIN OPENSSH PRIVATE KEY-----"
        result, count = redact_secrets(text)
        assert "-----BEGIN OPENSSH PRIVATE KEY-----" not in result
        assert count >= 1

    def test_pem_generic_private_key_header_redacted(self):
        text = "-----BEGIN PRIVATE KEY-----"
        result, count = redact_secrets(text)
        assert "-----BEGIN PRIVATE KEY-----" not in result
        assert count >= 1

    def test_dsn_password_postgres_redacted(self):
        text = "Using postgres://user:mypassword@localhost:5432/mydb"
        result, count = redact_secrets(text)
        assert "mypassword" not in result
        assert count >= 1

    def test_dsn_password_mysql_redacted(self):
        text = "mysql://admin:secret123@db.example.com/app"
        result, count = redact_secrets(text)
        assert "secret123" not in result
        assert count >= 1

    def test_dsn_password_mongodb_redacted(self):
        text = "mongodb://user:pass123@cluster.mongodb.net/db"
        result, count = redact_secrets(text)
        assert "pass123" not in result
        assert count >= 1

    def test_hex_secret_redacted(self):
        text = "key=0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d"
        result, count = redact_secrets(text)
        assert "0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d" not in result
        assert count >= 1

    def test_multiple_secrets_all_redacted(self):
        text = (
            "password=abc123 and api_key=xyz789abcdefgh "
            "and AKIAIOSFODNN7EXAMPLE is the key"
        )
        result, count = redact_secrets(text)
        assert count >= 2
        assert "abc123" not in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_returns_tuple_of_str_and_int(self):
        result = redact_secrets("normal text")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], int)

    def test_case_insensitive_password(self):
        text = "PASSWORD=secret123"
        result, count = redact_secrets(text)
        assert "secret123" not in result
        assert count >= 1

    def test_case_insensitive_api_key(self):
        text = "API_KEY=someapikey123"
        result, count = redact_secrets(text)
        assert "someapikey123" not in result
        assert count >= 1

    def test_short_secret_not_redacted(self):
        # secret pattern requires 8+ chars
        text = "secret=abc"
        result, count = redact_secrets(text)
        # Should not match because it's under 8 chars
        assert count == 0 or "abc" in result

    def test_redacted_placeholder_present(self):
        text = "api_key=mysecretapikey123"
        result, count = redact_secrets(text)
        assert "[REDACTED]" in result
