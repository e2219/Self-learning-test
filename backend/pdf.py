import os
import re
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader

from . import limits


class PDFError(ValueError):
    pass


class PDFSizeError(PDFError):
    pass


def text_quality_issue(text: str) -> str:
    """Conservative signal for broken PDF text layers; never rewrite source text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 12 and sum(len(line) == 1 for line in lines) / len(lines) >= .6:
        return "文本存在大量逐字断行，PDF 文本层可能异常。建议对照原页进行图片识别。"
    if "�" in text:
        return "文本含无法识别的字符，建议对照原页进行图片识别。"
    return ""


def reusable_pdf_text(text: str) -> bool:
    return len(re.sub(r"\s+", "", text)) >= 40 and not text_quality_issue(text)


def save_and_extract_pdf(source: BinaryIO, destination: Path):
    """Copy the spooled multipart upload in bounded chunks, then parse from disk.

    Passing a path to PdfReader would load the entire PDF into a BytesIO. An
    already-open file lets it seek instead, particularly useful for image-heavy
    textbooks. Individual decoded PDF objects can still consume memory.
    """
    source.seek(0)
    size = 0
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            while chunk := source.read(limits.UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > limits.MAX_PDF_BYTES:
                    raise PDFSizeError(f"PDF 不能超过 {limits.MAX_PDF_MB} MB。")
                output.write(chunk)
        with destination.open("rb") as stream:
            return extract_pdf(stream)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def extract_pdf(stream: BinaryIO):
    stream.seek(0)
    if not stream.read(1024).lstrip().startswith(b"%PDF-"):
        raise PDFError("文件不是有效的 PDF。")
    stream.seek(0)
    reader = None
    try:
        reader = PdfReader(stream)
        if reader.is_encrypted and not reader.decrypt(""):
            raise PDFError("暂不支持带密码的 PDF，请先解密。")
        if not 1 <= len(reader.pages) <= limits.MAX_PDF_PAGES:
            raise PDFError(f"每份 PDF 应包含 1 至 {limits.MAX_PDF_PAGES} 页。")
        pages, warnings = [], []
        for index, page in enumerate(reader.pages, 1):
            # Normal text extraction preserves reading order better than layout
            # mode on mixed Chinese/math books; equations still need inspection.
            try:
                text = (page.extract_text() or "").replace("\x00", "")
                text = re.sub(r"[ \t]+", " ", text).strip()[:50_000]
                warning = "文本较少，可能是扫描页或图片页，可使用「文字与公式识别」或手动补充。" if len(text) < 40 else ""
                warning = text_quality_issue(text) or warning
            except Exception:
                text, warning = "", "此页文本提取失败，可以手动补充。"
            pages.append({"number": index, "text": text, "warning": warning})
        low = sum(bool(p["warning"]) for p in pages)
        if low:
            warnings.append(f"{low} 页需要检查，扫描页可使用「文字与公式识别」。")
        warnings.append("公式、上下标和数学符号可能在提取时失真，请预览出题范围内的内容。")
        outline = []

        def walk(items, depth=0):
            for item in items:
                if isinstance(item, list):
                    walk(item, depth + 1)
                else:
                    try:
                        number = reader.get_destination_page_number(item)
                        if number is not None and number >= 0:
                            outline.append({"title": str(item.title)[:200], "page": number + 1, "depth": depth})
                    except Exception:
                        pass

        try:
            walk(reader.outline)
        except Exception:
            pass
        return pages, outline[:500], warnings
    except PDFError:
        raise
    except Exception as exc:
        raise PDFError("无法读取 PDF，文件可能损坏或格式不受支持。") from exc
    finally:
        if reader is not None:
            reader.close()


IMAGE_MAX_BYTES = 20 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000


def save_image_as_pdf(source: BinaryIO, destination: Path):
    """Normalize an image into a single-page document, without sending it to any API."""
    import io
    from PIL import Image, ImageOps, UnidentifiedImageError
    source.seek(0)
    data = source.read(IMAGE_MAX_BYTES + 1)
    if len(data) > IMAGE_MAX_BYTES:
        raise PDFSizeError("单张图片不能超过 20 MB。")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP') or getattr(image, 'n_frames', 1) != 1:
                raise PDFError("支持静态 JPG、PNG、WebP 图片，不支持动画或多帧文件。")
            if image.width * image.height > IMAGE_MAX_PIXELS:
                raise PDFError("图片不能超过 4000 万像素，请缩小后上传。")
            image.load()
            oriented = ImageOps.exif_transpose(image)
            try:
                with oriented.convert('RGBA') as rgba:
                    with Image.new('RGB', rgba.size, 'white') as rgb:
                        rgb.paste(rgba, mask=rgba.getchannel('A'))
                        with destination.open('xb') as out:
                            rgb.save(out, format='PDF', resolution=144, quality=95)
                destination.chmod(0o600)
            finally:
                oriented.close()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        destination.unlink(missing_ok=True)
        raise PDFError(str(exc) if isinstance(exc, PDFError) else '图片无法解码，请使用有效的 JPG、PNG 或 WebP。') from exc
    return ([{'number': 1, 'text': '', 'warning': '图片资料，请点击识别所选页读取文字与公式。'}], [], ['图片已作为单页资料导入，识别时才会调用 API。'])
