import io

import pytest
from pypdf import PdfReader, PdfWriter

from backend import limits, pdf
from tests.test_api import sample_pdf


def test_upload_copy_is_bounded_and_reader_receives_disk_stream(tmp_path, monkeypatch):
    class BoundedSource(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= limits.UPLOAD_CHUNK_BYTES
            return super().read(size)

    def reader(stream):
        assert isinstance(stream, io.BufferedReader)
        return PdfReader(stream)

    monkeypatch.setattr(pdf, "PdfReader", reader)
    data = sample_pdf()
    destination = tmp_path / "copy.pdf"
    pages, _, _ = pdf.save_and_extract_pdf(BoundedSource(data), destination)
    assert destination.read_bytes() == data
    assert "Probability" in pages[0]["text"]


def test_unknown_size_upload_stops_at_limit_and_removes_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "UPLOAD_CHUNK_BYTES", 8)
    monkeypatch.setattr(limits, "MAX_PDF_BYTES", 16)
    destination = tmp_path / "partial.pdf"
    source = io.BytesIO(b"x" * 100)
    with pytest.raises(pdf.PDFSizeError):
        pdf.save_and_extract_pdf(source, destination)
    assert source.tell() == 24
    assert not destination.exists()


def test_more_than_800_pages_and_configurable_page_limit(monkeypatch):
    writer = PdfWriter()
    for _ in range(801):
        writer.add_blank_page(width=595, height=842)
    stream = io.BytesIO()
    writer.write(stream)
    pages, _, _ = pdf.extract_pdf(stream)
    assert len(pages) == 801
    monkeypatch.setattr(limits, "MAX_PDF_PAGES", 800)
    with pytest.raises(pdf.PDFError, match="800"):
        pdf.extract_pdf(stream)
