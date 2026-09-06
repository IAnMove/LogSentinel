"""Configuration errors must not silently enable defaults."""
import pytest
from logsentinel.config import Config, JournaldSourceConfig


def test_invalid_explicit_config_fails_closed(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('llm:\n  timeout_seconds: definitely-not-a-number\n')
    with pytest.raises(ValueError):
        Config.load(path)


def test_missing_explicit_config_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        Config.load(tmp_path / 'missing.yaml')


def test_default_journal_includes_info_for_successful_logins():
    assert JournaldSourceConfig().priority == 'info'


@pytest.mark.parametrize('data', [
    {'aggregator': {'window_seconds': 0}},
    {'aggregator': {'max_batch_size': 0}},
    {'sources': {'files': {'poll_interval_seconds': -1}}},
    {'llm': {'timeout_seconds': 0}},
    {'llm': {'max_tokens': -1}},
    {'llm': {'provider': 'typo'}},
    {'memory': {'max_semantic_rules_in_prompt': -1}},
    {'behavior': {'timezone': 'Not/A_Timezone'}},
    {'notifiers': {'min_severity': 'HGIH'}},
])
def test_invalid_operational_config_is_rejected(data):
    with pytest.raises(ValueError):
        Config.model_validate(data)
