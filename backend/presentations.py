"""Local PowerPoint -> PDF normalization for the existing document pipeline."""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import zipfile

from . import limits
from .pdf import PDFError, PDFSizeError, save_and_extract_pdf

CONVERSION_TIMEOUT = 180
OLE_HEADER = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def libreoffice_path():
    configured = os.environ.get('STUDY_LIBREOFFICE', '').strip()
    if configured:
        found = shutil.which(configured)
        if found: return found
        raise PDFError('STUDY_LIBREOFFICE 指向的程序不存在，请填写 LibreOffice 可执行文件路径。')
    for name in ('libreoffice', 'soffice'):
        found = shutil.which(name)
        if found: return found
    candidates = [Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')]
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)'):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / 'LibreOffice/program/soffice.exe')
    for path in candidates:
        if path.is_file(): return str(path)
    raise PDFError('导入 PPT/PPTX 需要本机安装 LibreOffice（Ubuntu：sudo apt install libreoffice-impress）。'
                   '安装后重启项目；也可先在 PowerPoint/WPS 中另存为 PDF 后上传。')


def validate_presentation(path, suffix):
    with path.open('rb') as stream:
        signature = stream.read(8)
    if suffix == '.ppt':
        if signature != OLE_HEADER:
            raise PDFError('文件不是有效的旧版 PPT，请确认格式，或另存为 PPTX/PDF 后上传。')
        return
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if not {'[Content_Types].xml', 'ppt/presentation.xml'} <= names:
                raise PDFError('文件不是有效的 PPTX 演示文稿。')
            slides = sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml', name)) for name in names)
            if not 1 <= slides <= limits.MAX_PDF_PAGES:
                raise PDFError(f'每份 PPTX 应包含 1 至 {limits.MAX_PDF_PAGES} 张幻灯片。')
            if len(entries) > 100000 or sum(e.file_size for e in entries) > min(4 * limits.MAX_PDF_BYTES, 2 * 1024**3):
                raise PDFError('PPTX 解压后内容过大，请压缩媒体或拆分课件后上传。')
            if any(e.flag_bits & 1 for e in entries):
                raise PDFError('暂不支持带密码的 PPTX，请先解密。')
    except (zipfile.BadZipFile, OSError) as exc:
        raise PDFError('无法读取 PPTX，文件可能损坏或带有密码，请先另存为未加密 PPTX/PDF。') from exc


def convert_to_pdf(program, source, output_dir, profile):
    profile.mkdir(mode=0o700)
    (profile / 'user').mkdir(mode=0o700)
    # Fresh profile avoids connecting to (or altering) the user's open office session.
    (profile / 'user' / 'registrymodifications.xcu').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
        '</item></oor:items>', encoding='utf-8')
    input_filter = 'Impress MS PowerPoint 2007 XML' if source.suffix == '.pptx' else 'MS PowerPoint 97'
    export_filter = 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
    command = [program, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo',
               '--nodefault', '--norestore', '--infilter=' + input_filter,
               '--convert-to', export_filter, '--outdir', str(output_dir), str(source)]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=(os.name == 'posix'))
        try:
            status = process.wait(timeout=CONVERSION_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            if os.name == 'posix':
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            else:
                process.kill()
            process.wait()
            raise PDFError('PPT 转换超时，请将课件拆分，或先另存为 PDF 后上传。') from exc
    except OSError as exc:
        raise PDFError('无法启动 LibreOffice，请检查安装和 STUDY_LIBREOFFICE 配置。') from exc
    pdf = output_dir / (source.stem + '.pdf')
    if status != 0 or not pdf.is_file() or pdf.stat().st_size == 0:
        raise PDFError('PPT 转换失败，文件可能损坏、带密码或格式不受支持。请在 PowerPoint/WPS 中另存为 PDF 后上传。')
    return pdf


def save_presentation_as_pdf(source, destination, suffix):
    """No cloud/model calls. A temporary deck/profile is removed on every exit path."""
    if suffix not in ('.ppt', '.pptx'):
        raise PDFError('支持 .ppt 和 .pptx 演示文稿。')
    program = libreoffice_path()
    with tempfile.TemporaryDirectory(prefix='zhixi-ppt-') as temporary:
        root = Path(temporary).resolve()
        deck = root / ('slides' + suffix)
        source.seek(0)
        size = 0
        with deck.open('xb') as output:
            while chunk := source.read(limits.UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > limits.MAX_PDF_BYTES:
                    raise PDFSizeError(f'PPT/PPTX 不能超过 {limits.MAX_PDF_MB} MB。')
                output.write(chunk)
        validate_presentation(deck, suffix)
        pdf = convert_to_pdf(program, deck, root, root / 'profile')
        with pdf.open('rb') as converted:
            pages, outline, warnings = save_and_extract_pdf(converted, destination)
        warnings.insert(0, '课件已在本机转换为 PDF（不消耗 AI tokens），页码按转换后的幻灯片顺序，包含隐藏幻灯片。'
                        '动画、视频和备注不作为动态内容导入；特殊字体、公式或图表可能存在转换差异。')
        return pages, outline, warnings
