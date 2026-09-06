from logsentinel.config import PrefilterConfig
from logsentinel.core.models import LogEntry, Category
from logsentinel.core.prefilter import PreFilter


def test_noise_substring_cannot_hide_authentication_failure():
    text = 'Failed password for api/tags from 192.0.2.1 port 22 ssh2'
    analyze, category = PreFilter(PrefilterConfig()).should_analyze(LogEntry(service='sshd', message=text, raw=text))
    assert analyze
    assert category == Category.SECURITY


def test_journal_escaped_json_does_not_hide_apparmor_denial():
    text = 'apparmor="DENIED" operation="open"'
    import json
    analyze, category = PreFilter(PrefilterConfig()).should_analyze(LogEntry(service='kernel', message=text, raw=json.dumps({'MESSAGE': text}), priority=5))
    assert analyze
    assert category == Category.SECURITY
