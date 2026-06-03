"""OCR engine — Tesseract (pytesseract) + rapidocr unified interface."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from deepx.config.settings import get_settings

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None


@dataclass
class OCRResult:
    """Result from OCR extraction."""

    text: str
    confidence: float
    blocks: list[dict]  # List of text blocks with position


def _tesseract_data_dir() -> Path | None:
    """Find Tesseract tessdata directory."""
    # Common macOS brew locations
    candidates = [
        Path("/usr/local/share/tessdata"),
        Path.home() / ".tessdata",
        Path("/opt/homebrew/share/tessdata"),
    ]
    for p in candidates:
        if p.exists() and (p / "eng.traineddata").exists():
            return p
    return None


def _has_rapidocr() -> bool:
    try:
        from rapidocr_onnxruntime import RapidOCR
        return True
    except ImportError:
        return False


class OCREngine:
    """
    Unified OCR engine.

    Priority: rapidocr > pytesseract.
    - rapidocr: ONNX-based, fast, no extra deps, works on all platforms.
    - pytesseract: uses system Tesseract, needs language packs installed.
    """

    def __init__(self):
        self.settings = get_settings()
        self._engine = None
        self._engine_type: str | None = None

    def _lazy_init(self):
        if self._engine is not None:
            return

        # Try rapidocr first (ONNX, no system deps)
        if _has_rapidocr():
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._engine = RapidOCR()
                self._engine_type = "rapidocr"
                return
            except Exception:
                pass

        # Fall back to pytesseract
        if shutil.which("tesseract") is None:
            self._engine_type = "none"
            return

        self._engine = pytesseract
        self._engine_type = "tesseract"
        self._tessdata = _tesseract_data_dir()

    async def extract(self, image_path: str | Path) -> OCRResult:
        """
        Extract text from an image.

        Returns OCRResult with text, confidence, and per-block positions.
        """
        self._lazy_init()
        path = Path(image_path)
        if not path.exists():
            return OCRResult(text="", confidence=0.0, blocks=[])

        if self._engine_type == "none":
            return OCRResult(
                text="[OCR unavailable — no tesseract binary found]",
                confidence=0.0,
                blocks=[],
            )

        if self._engine_type == "rapidocr":
            return await self._extract_rapidocr(path)
        elif self._engine_type == "tesseract":
            return await self._extract_tesseract(path)

        return OCRResult(text="", confidence=0.0, blocks=[])

    async def _extract_rapidocr(self, path: Path) -> OCRResult:
        result, elapse = self._engine(str(path))
        if not result:
            return OCRResult(text="", confidence=0.0, blocks=[])

        blocks = []
        texts = []
        total_conf = 0.0

        for item in result:
            # rapidocr result: [box, text, score]
            box, text, score = item[0], item[1], item[2]
            total_conf += score
            texts.append(text)
            blocks.append({
                "text": text,
                "confidence": float(score),
                "bbox": box,  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            })

        avg_conf = total_conf / len(result) if result else 0.0
        text = "\n".join(texts)

        return OCRResult(text=text, confidence=avg_conf, blocks=blocks)

    async def _extract_tesseract(self, path: Path) -> OCRResult:
        import subprocess, os

        # Workaround: tesseract 5.5 on macOS has issues reading /tmp.
        # Use current working directory instead.
        cwd = os.getcwd()
        img_path = path.resolve()
        img_path_str = str(img_path)

        # If path is in /tmp or similar, copy to cwd
        if str(img_path).startswith('/tmp') or str(img_path).startswith('/var/folders'):
            import shutil
            tmp_copy = Path(cwd) / f".ocr_tmp_{os.getpid()}_{img_path.name}"
            shutil.copy(img_path, tmp_copy)
            img_path_str = str(tmp_copy)
            cleanup = tmp_copy
        else:
            cleanup = None

        try:
            out_base = str(Path(cwd) / f".ocr_out_{os.getpid()}")
            result = subprocess.run(
                ['tesseract', img_path_str, out_base],
                capture_output=True, timeout=30,
            )
            txt_file = out_base + '.txt'
            if os.path.exists(txt_file):
                text = Path(txt_file).read_text(encoding='utf-8', errors='replace').strip()
                return OCRResult(text=text, confidence=0.8, blocks=[])
            return OCRResult(
                text=f"[OCR error] tesseract returncode={result.returncode}",
                confidence=0.0, blocks=[],
            )
        finally:
            if cleanup and cleanup.exists():
                cleanup.unlink()
            out_file = Path(cwd) / f".ocr_out_{os.getpid()}.txt"
            if out_file.exists():
                out_file.unlink()

    @property
    def engine_name(self) -> str:
        self._lazy_init()
        return self._engine_type or "none"

    @property
    def is_available(self) -> bool:
        self._lazy_init()
        return self._engine_type != "none"

    async def extract_text(self, image_path: str | Path) -> str:
        """Convenience: just return the text, no blocks."""
        result = await self.extract(image_path)
        return result.text