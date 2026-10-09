import io
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from backend import db, limits, presentations
from backend.pdf import PDFError, PDFSizeError
from tests.test_api import client, setup, sample_pdf  # noqa: F401
from tests.ppt_fixture import pptx_bytes


def mock_converter(monkeypatch):
    paths = []
    monkeypatch.setattr(presentations, 'libreoffice_path', lambda: 'libreoffice')
    def convert(program, source, output_dir, profile):
        paths.append(source.parent)
        pdf = output_dir / 'slides.pdf'
        pdf.write_bytes(sample_pdf())
        return pdf
    monkeypatch.setattr(presentations, 'convert_to_pdf', convert)
    return paths


def upload(client, setup, name='lesson.pptx', data=None):
    return client.post(f'/api/courses/{setup[0]["id"]}/documents',
                       files={'file':(name, pptx_bytes() if data is None else data, 'application/octet-stream')})


@pytest.mark.parametrize('suffix,data', [('.PPTX', None), ('.ppt', presentations.OLE_HEADER+b'placeholder')])
def test_upload_uses_pdf_pipeline_and_cleans_temporary_deck(client, setup, monkeypatch, suffix, data):
    paths = mock_converter(monkeypatch)
    response = upload(client, setup, 'lesson'+suffix, data)
    assert response.status_code == 201
    doc = response.json()
    assert doc['name'] == 'lesson'+suffix and doc['page_count'] == 1
    assert '不消耗 AI tokens' in doc['warnings'][0]
    assert 'Probability' in client.get(f'/api/documents/{doc["id"]}/pages/1').json()['text']
    assert client.get(f'/api/documents/{doc["id"]}/file').content.startswith(b'%PDF')
    assert client.get(f'/api/documents/{doc["id"]}/pages/1/image').status_code == 200
    assert not paths[0].exists()
    assert client.delete(f'/api/documents/{doc["id"]}').status_code == 200
    assert not (db.DATA_DIR / 'uploads' / (doc['id']+'.pdf')).exists()


def test_missing_converter_has_actionable_error_and_no_orphan(client, setup, monkeypatch):
    def missing(): raise PDFError('导入 PPT/PPTX 需要本机安装 LibreOffice')
    monkeypatch.setattr(presentations, 'libreoffice_path', missing)
    before = set((db.DATA_DIR / 'uploads').iterdir())
    response = upload(client, setup)
    assert response.status_code == 422 and 'LibreOffice' in response.text
    assert set((db.DATA_DIR / 'uploads').iterdir()) == before
    assert db.one('SELECT count(*) AS n FROM documents')['n'] == 1


@pytest.mark.parametrize('suffix,data', [('.pptx', b'not a zip'), ('.ppt', b'not OLE')])
def test_invalid_deck_rejected_before_converter(client, setup, monkeypatch, suffix, data):
    paths = mock_converter(monkeypatch)
    assert upload(client, setup, 'bad'+suffix, data).status_code == 422
    assert not paths and db.one('SELECT count(*) AS n FROM documents')['n'] == 1


def test_pptx_page_limit_and_non_presentation_zip(client, setup, monkeypatch):
    paths = mock_converter(monkeypatch)
    monkeypatch.setattr(limits, 'MAX_PDF_PAGES', 1)
    assert upload(client, setup).status_code == 422
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z: z.writestr('word/document.xml', '<document/>')
    assert upload(client, setup, data=out.getvalue()).status_code == 422
    assert not paths


def test_streamed_size_limit_and_failed_conversion_cleanup(client, setup, monkeypatch, tmp_path):
    mock_converter(monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(limits, 'MAX_PDF_BYTES', 10)
        with pytest.raises(PDFSizeError):
            presentations.save_presentation_as_pdf(io.BytesIO(pptx_bytes()), tmp_path/'output.pdf', '.pptx')
        assert upload(client, setup).status_code == 413
    paths = []
    def broken(program, source, output_dir, profile):
        paths.append(source.parent)
        raise PDFError('PPT 转换失败')
    monkeypatch.setattr(presentations, 'convert_to_pdf', broken)
    assert upload(client, setup).status_code == 422
    assert not paths[0].exists() and db.one('SELECT count(*) AS n FROM documents')['n'] == 1


def test_converter_timeout_stops_process_and_uses_private_profile(monkeypatch, tmp_path):
    source = tmp_path/'slides.pptx'; source.write_bytes(pptx_bytes())
    class Process:
        pid = 12345
        waits = 0
        killed = False
        def wait(self, timeout=None):
            self.waits += 1
            if timeout is not None: raise subprocess.TimeoutExpired('soffice', timeout)
            return -9
        def kill(self): self.killed = True
    process = Process()
    def launch(command, **kw):
        assert '--headless' in command and any('ExportHiddenSlides' in s for s in command)
        assert '-env:UserInstallation='+(tmp_path/'profile').as_uri() in command
        assert '<value>3</value>' in (tmp_path/'profile/user/registrymodifications.xcu').read_text()
        return process
    monkeypatch.setattr(presentations.subprocess, 'Popen', launch)
    monkeypatch.setattr(presentations.os, 'killpg', lambda *args: process.kill(), raising=False)
    with pytest.raises(PDFError, match='超时'):
        presentations.convert_to_pdf('soffice', source, tmp_path, tmp_path/'profile')
    assert process.killed and process.waits == 2


@pytest.mark.skipif(not shutil.which('libreoffice'), reason='LibreOffice not installed')
def test_real_pptx_and_legacy_ppt_conversion(client, setup, tmp_path):
    response = upload(client, setup)
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc['page_count'] == 2  # Includes hidden slide, keeping original slide numbers.
    for number in (1, 2):
        page = client.get(f'/api/documents/{doc["id"]}/pages/{number}').json()
        assert f'Slide {number}:' in page['text']
    source = tmp_path/'slides.pptx'; source.write_bytes(pptx_bytes())
    subprocess.run([shutil.which('libreoffice'), '-env:UserInstallation='+(tmp_path/'legacy-profile').as_uri(),
                    '--headless', '--convert-to', 'ppt:MS PowerPoint 97', '--outdir', str(tmp_path), str(source)],
                   check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    legacy = tmp_path/'slides.ppt'
    assert legacy.read_bytes().startswith(presentations.OLE_HEADER)
    response = upload(client, setup, 'legacy.ppt', legacy.read_bytes())
    assert response.status_code == 201, response.text
    assert response.json()['page_count'] == 2
