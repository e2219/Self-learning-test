import io
import re

from pypdf import PdfReader


class PDFError(ValueError):
    pass


def extract_pdf(data: bytes):
    if not data.lstrip().startswith(b"%PDF-"):
        raise PDFError("文件不是有效的 PDF。")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PDFError("暂不支持带密码的 PDF，请先解密。")
        if not 1 <= len(reader.pages) <= 800:
            raise PDFError("每份 PDF 应包含 1 至 800 页。")
        pages, warnings = [], []
        for index, page in enumerate(reader.pages, 1):
            # Normal text extraction preserves reading order better than layout
            # mode on mixed Chinese/math books; equations still need inspection.
            try:
                text = (page.extract_text() or "").replace("\x00", "")
                text = re.sub(r"[ \t]+", " ", text).strip()[:50_000]
                warning = "文本较少，可能是扫描页或图片页，请检查或手动补充。" if len(text) < 40 else ""
                if "�" in text:
                    warning = "存在无法识别的字符，请检查公式和文字。"
            except Exception:
                text, warning = "", "此页文本提取失败，可以手动补充。"
            pages.append({"number": index, "text": text, "warning": warning})
        low = sum(bool(p["warning"]) for p in pages)
        if low:
            warnings.append(f"{low} 页需要检查，当前不包含扫描页 OCR。")
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
