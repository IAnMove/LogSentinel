import json
import time

import pytest

from logsentinel.portal.analysis import Analyzer, grouping_key
from logsentinel.portal.models import Destination, Machine, Source
from logsentinel.portal.notify import enqueue
from logsentinel.portal.ssh_notifications import rejection_form
from logsentinel.portal.store import Store


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    store = Store(tmp_path)
    machine = store.put('machine', Machine(name='SSH test host').model_dump())
    source = store.put('source', Source(name='Authentication', machine_id=machine, kind='push',
                                     enabled=True, ssh_rejection_notify_seconds=3600).model_dump())
    dest = store.put('destination', Destination(name='Local only', kind='file', enabled=True,
                                              min_severity='LOW', cooldown_seconds=0).model_dump())
    clock = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    return store, machine, source, dest, clock


def finding(scenario, number, message=None, *, severity='HIGH', source=None, extra=(), status='open', notify=True):
    store, machine, sid, _, _ = scenario
    sid = source or sid
    message = message or f'Invalid user user{number} from 203.0.113.1 port {10000+number}'
    entries = [dict(origin=f'{number}-{i}', message=m, service='sshd') for i, m in enumerate([message, *extra])]
    store.ingest(dict(id=sid, machine_id=machine), entries)
    events = [e for e in store.events(source_id=sid, limit=5000) if e['origin'].startswith(str(number)+'-')]
    ids = [e['id'] for e in events]
    # Separate findings reproduce the model + deterministic duplicate-notification case.
    pid = Analyzer(store).save_finding(machine, dict(title='SSH test', summary='Inspect originals', severity=severity,
            category='authentication', evidence_ids=ids[:100]), ids, fingerprint='test-'+str(number), status=status, notify=notify)
    return pid


def latest(store, pid):
    with store.connect() as db:
        row = db.execute('select * from deliveries where problem_id=? order by rowid desc limit 1', (pid,)).fetchone()
        return dict(row)


def test_different_findings_share_interval_and_muted_events_do_not_extend_it(scenario):
    store, _, _, _, clock = scenario
    first = finding(scenario, 1)
    assert latest(store, first)['status'] == 'pending'
    clock[0] += 3500
    second = finding(scenario, 2, 'Failed password for root from 2001:db8::1 port 55223 ssh2')
    assert latest(store, second)['status'] == 'muted'
    assert latest(store, second)['error'] == 'ssh_rejection_cooldown'
    assert store.problem(second)['notification_decisions'][0]['reason'] == 'ssh_rejection_cooldown'
    clock[0] += 101
    third = finding(scenario, 3)
    assert latest(store, third)['status'] == 'pending'
    assert len(store.events()) == 3
    assert len(store.rows('problems')) == 3


def test_escalation_critical_recovery_and_other_sources_are_not_suppressed(scenario):
    store, machine, _, _, clock = scenario
    low = finding(scenario, 1, severity='MEDIUM')
    high = finding(scenario, 2, severity='HIGH')
    critical = finding(scenario, 3, severity='CRITICAL')
    recovered = finding(scenario, 4, status='resolved')
    other = store.put('source', Source(name='Other authentication', machine_id=machine, kind='push',
                                      ssh_rejection_notify_seconds=3600).model_dump())
    separate = finding(scenario, 5, source=other)
    for pid in (low, high, critical, recovered, separate):
        assert latest(store, pid)['status'] == 'pending'
    assert 'notification_group' not in json.loads(latest(store, critical)['payload'])
    second_dest = store.put('destination', Destination(name='Another local outbox', kind='file', enabled=True,
                                                      min_severity='LOW', cooldown_seconds=0).model_dump())
    again = finding(scenario, 6)
    with store.connect() as db:
        assert db.execute('select status from deliveries where problem_id=? and destination_id=?', (again, second_dest)).fetchone()[0] == 'pending'


def test_unknown_successful_mixed_and_missing_evidence_fail_open(scenario):
    store, _, _, _, _ = scenario
    finding(scenario, 1)
    accepted = 'Accepted publickey for admin from 203.0.113.1 port 55444 ssh2: ED25519 SHA256:synthetic'
    for number, message in enumerate((accepted, 'channel 1: open failed: connect failed: Connection refused',
                                    'Invalid user admin from 203.0.113.1 port 55333\nAccepted password for root'), 2):
        pid = finding(scenario, number, message)
        assert latest(store, pid)['status'] == 'pending'
        assert 'notification_group' not in json.loads(latest(store, pid)['payload'])
    # The accepted event is outside the first 100 cited examples: all originals matter.
    extra = [f'Invalid user someone{i} from 203.0.113.2 port 4455' for i in range(101)] + [accepted]
    mixed = finding(scenario, 10, extra=extra)
    assert latest(store, mixed)['status'] == 'pending'
    assert 'notification_group' not in json.loads(latest(store, mixed)['payload'])
    from logsentinel.portal.ssh_notifications import subject_for
    assert subject_for(store.events(limit=1), ['missing-original']) is None


def test_grouping_does_not_depend_on_user_port_address_or_model_category():
    base = dict(source_id='s', service='sshd', message='Invalid user alice from 203.0.113.1 port 22334')
    assert grouping_key(base) == grouping_key(dict(base, message='Invalid user bob from 2001:db8::2 port 54321'))
    assert grouping_key(base) != grouping_key(dict(base, message='Failed password for bob from 203.0.113.1 port 22334 ssh2'))
    assert rejection_form(dict(base, service='application')) is None
    assert rejection_form(dict(base, message=base['message']+' extra warning')) is None
    assert rejection_form(dict(base, message='Invalid user x from invalid-address port 22')) is None
    pam = 'pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost=203.0.113.1  user=root'
    assert rejection_form(dict(base, message=pam)) == 'pam_authentication_failure'
    repeated = pam.replace('pam_unix(sshd:auth): authentication failure;', 'PAM 4 more authentication failures;')
    assert rejection_form(dict(base, message=repeated)) == 'pam_authentication_failures'
    assert rejection_form(dict(base, message=pam+' Accepted password for root')) is None
    assert rejection_form(dict(base, message=pam.replace('sshd:auth', 'sudo:auth'))) is None
    assert rejection_form(dict(base, message='message repeated 3 times: [ '+base['message']+']')) == 'invalid_user'
    assert rejection_form(dict(base, message='message repeated 3 times: [ Accepted password for root]')) is None
    assert rejection_form(dict(base, message='Invalid user  from 203.0.113.2 port 33333')) == 'invalid_user'
    assert rejection_form(dict(base, message='Failed none for invalid user admin from 203.0.113.2 port 33333 ssh2')) == 'failed_none'


def test_failed_delivery_does_not_consume_interval_and_default_is_opt_in(scenario):
    store, _, sid, _, _ = scenario
    first = finding(scenario, 1)
    with store.connect() as db:
        db.execute("update deliveries set status='failed' where problem_id=?", (first,))
    second = finding(scenario, 2)
    assert latest(store, second)['status'] == 'pending'
    src = store.get('source', sid);src.pop('id');src['ssh_rejection_notify_seconds'] = 0
    store.put('source', src, sid)
    third = finding(scenario, 3)
    assert latest(store, third)['status'] == 'pending'
    assert 'notification_group' not in json.loads(latest(store, third)['payload'])
    assert Source(name='Defaults', machine_id='m', kind='push').ssh_rejection_notify_seconds == 0


def test_verification_prose_cannot_add_or_remove_the_original_based_subject(scenario):
    store, _, _, _, _ = scenario
    first = finding(scenario, 1)
    second = finding(scenario, 2, notify=False)
    with store.connect() as db:
        data = json.loads(db.execute('select data from problems where id=?', (second,)).fetchone()[0])
        data.update(summary='Different model interpretation', verification_status='confirmed')
        db.execute('update problems set data=? where id=?', (json.dumps(data), second))
    enqueue(store, second)
    assert latest(store, second)['error'] == 'ssh_rejection_cooldown'
    with store.connect() as db:
        db.execute('delete from problems where id=?', (second,))
        assert not db.execute('select * from notification_subjects where problem_id=?', (second,)).fetchall()
