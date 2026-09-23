import json

from app import ops
from app.migrations import MIGRATIONS


def test_credential_status_reports_presence_and_format_without_values(monkeypatch):
    monkeypatch.setenv('DATA_GO_KR_SERVICE_KEY', '공공데이터_키_입력')
    monkeypatch.setenv('SGIS_CONSUMER_KEY', 'abcdef1234567890abcd')
    monkeypatch.delenv('SGIS_CONSUMER_SECRET', raising=False)
    rows = {row['name']: row for row in ops.credential_status()}
    assert rows['DATA_GO_KR_SERVICE_KEY']['configured'] is True
    assert rows['DATA_GO_KR_SERVICE_KEY']['format_problem']
    assert rows['SGIS_CONSUMER_KEY']['format_problem'] is None
    assert rows['SGIS_CONSUMER_SECRET']['configured'] is False
    text = json.dumps(rows, ensure_ascii=False)
    assert 'abcdef1234567890abcd' not in text and '공공데이터_키_입력' not in text


def test_redaction_removes_credential_values_from_any_output(monkeypatch):
    monkeypatch.setenv('VWORLD_API_KEY', 'SECRET-VWORLD-KEY-123')
    assert ops._redact('error for key=SECRET-VWORLD-KEY-123') == 'error for key=[REDACTED]'


def test_raw_summary_counts_files_and_is_order_independent(tmp_path):
    (tmp_path / 'raw' / 'sgis').mkdir(parents=True)
    (tmp_path / 'raw' / 'sgis' / 'a.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'raw' / 'b.csv').write_text('x', encoding='utf-8')
    summary = ops.raw_summary(tmp_path)
    assert summary['files'] == 2 and summary['bytes'] == 3
    assert summary['by_folder'] == {'sgis': 1, '.': 1}
    assert summary == ops.raw_summary(tmp_path)


def test_migration_versions_are_unique_and_ordered():
    versions = [version for version, _ in MIGRATIONS]
    assert versions == sorted(versions) and len(versions) == len(set(versions))


def test_clear_rejections_removes_only_cached_errors(tmp_path):
    folder = tmp_path / 'cache' / 'vworld'
    folder.mkdir(parents=True)
    (folder / 'bad.json').write_text(json.dumps({'error': 'VWorld 인증 실패'}), encoding='utf-8')
    (folder / 'bad.body').write_bytes(b'{}')
    (folder / 'good.json').write_text(json.dumps({'error': None}), encoding='utf-8')
    (folder / 'good.body').write_bytes(b'{}')
    result = ops.clear_rejections('vworld', tmp_path)
    assert result['removed_rejections'] == 1
    assert not (folder / 'bad.json').exists() and not (folder / 'bad.body').exists()
    assert (folder / 'good.json').exists() and (folder / 'good.body').exists()
