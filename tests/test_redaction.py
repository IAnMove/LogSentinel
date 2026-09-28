"""Outgoing text must not carry recognisable credentials, nor lose ordinary words."""

import time

import pytest

from logsentinel.portal.rules import redact


@pytest.mark.parametrize(
    "line, secret",
    [
        ('{"password":"hunter2","user":"a"}', "hunter2"),
        ('{"api_key": "abcd1234efgh"}', "abcd1234efgh"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Authorization: Token abcdef123456", "abcdef123456"),
        ("proxy-authorization=Bearer s3cr3tvalue99", "s3cr3tvalue99"),
        ('curl -H "Bearer abc123def456"', "abc123def456"),
        ("postgres://admin:s3cret@db:5432/app", "s3cret"),
        ("https://ghp_abcdefghijklmnopqrstuvwxyz@github.com/x", "ghp_abcdefghijklmnopqrstuvwxyz"),
        ("mysql --password hunter2 -u root", "hunter2"),
        ("mysql -u root -phunter2 mydb", "hunter2"),
        ("sshpass -p hunter2 ssh host", "hunter2"),
        ("curl -u admin:hunter2 https://host", "hunter2"),
        ("passwd=hunter2 secret_key=abc123xyz", "hunter2"),
        ("db_password=x9y8z7", "x9y8z7"),
        ("X-Api-Key: abcdef123456", "abcdef123456"),
        ("token ghp_abcdefghijklmnopqrstuvwxyz0123456789", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
        ("key sk-abcdefghijklmnopqrstuvwxyz012345", "sk-abcdefghijklmnopqrstuvwxyz012345"),
        ("AIzaSyA1234567890abcdefghijklmnopqrstuv", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
        ("Cookie: sessionid=abcdef123456; theme=dark", "abcdef123456"),
        ("Set-Cookie: PHPSESSID=abcdef123456", "abcdef123456"),
        ('password="my secret phrase here"', "phrase"),
        ('password="unterminated secret phrase', "phrase"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEabc123def456", "MIIEabc123def456"),
    ],
)
def test_common_credential_shapes_are_hidden(line, secret):
    assert secret not in redact(line)
    assert "[REDACTED" in redact(line)


@pytest.mark.parametrize(
    "line",
    [
        "Failed password for root from 1.2.3.4 port 22 ssh2",
        "pam_unix(sshd:auth): authentication failure; logname= uid=0 user=bob",
        "Accepted publickey for ina from 10.0.0.1 port 5 ssh2: ED25519 SHA256:abcdef",
        "key=value size=12 token_count=5",
        "token: expired",
        "password: required",
        "sudo: ina : TTY=pts/0 ; PWD=/home/user ; USER=root ; COMMAND=/usr/bin/ls",
        "cwd=/srv pwd=/srv/app",
        "mysql --port=3306 -u root",
    ],
)
def test_ordinary_log_text_is_left_alone(line):
    assert redact(line) == line


def test_a_hidden_value_is_not_hidden_twice():
    once = redact("Authorization: Bearer abcdef123456 password=hunter2")
    assert redact(once) == once


@pytest.mark.parametrize(
    "line",
    ["sshpass " * 40000, "password=aaaaaaaaaa " * 20000, "authorization: " * 20000, "cookie: " + "x" * 250000],
)
def test_hostile_lines_do_not_stall_redaction(line):
    started = time.perf_counter()
    redact(line)
    assert time.perf_counter() - started < 2
