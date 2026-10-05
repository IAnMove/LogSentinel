"""A log source reads logs, not shell histories, VPN keys or saved Wi-Fi passwords."""

import pytest

from logsentinel.portal.source_paths import UnsafeSourcePath, is_sensitive, validate_source_path

SECRETS = [
    "/root/.bash_history",
    "/home/user/.bash_history",
    "/home/user/.zsh_history",
    "/home/user/.mysql_history",
    "/home/user/.psql_history",
    "/home/user/.python_history",
    "/home/user/.my.cnf",
    "/var/www/site/.htpasswd",
    "/etc/wireguard/wg0.conf",
    "/etc/wireguard/privatekey",
    "/etc/ssl/private/server.pem",
    "/etc/NetworkManager/system-connections/Home.nmconnection",
    "/etc/wpa_supplicant/wpa_supplicant.conf",
    "/etc/shadow",
    "/home/user/.ssh/id_ed25519",
    "/home/user/.aws/credentials",
    "/home/user/.bash_history.gz",
]

LOGS = [
    "/var/log/syslog",
    "/var/log/nginx/access.log",
    "/var/log/nginx/access.log.1.gz",
    "/var/log/auth.log",
    "/var/log/wireguard-status.log",
    "/home/user/app/logs/server.log",
    "/srv/private-tools/output.log",
    "/var/log/mysql/error.log",
]


@pytest.mark.parametrize("path", SECRETS)
def test_credential_stores_and_histories_are_refused(path):
    assert is_sensitive(path), path


@pytest.mark.parametrize("path", LOGS)
def test_ordinary_logs_are_not_swept_up_by_the_blocklist(path):
    assert not is_sensitive(path), path


def test_validation_raises_for_a_history_file(tmp_path):
    history = tmp_path / ".bash_history"
    history.write_text("ls\n")
    with pytest.raises(UnsafeSourcePath):
        validate_source_path(history, tmp_path / "data")
