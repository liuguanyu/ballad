"""OCR tool — local image text extraction with smart routing."""
from __future__ import annotations

from pathlib import Path

from deepx.tools.base import Tool
from deepx.ocr.router import OCRRouter


_ocr_router: OCRRouter | None = None


def _get_router() -> OCRRouter:
    global _ocr_router
    if _ocr_router is None:
        _ocr_router = OCRRouter()
    return _ocr_router


class OCR(Tool):
    """Extract text from images using local OCR. Routes to LLM vision for complex images."""

    name = "OCR"
    description = "Extract text from an image file. Uses local OCR (fast, free, offline) for text-heavy images (screenshots, error logs, code). Routes to LLM vision for complex visual content (diagrams, charts, UI designs) when needed."
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Absolute path to the image file.",
            },
            "force_vision": {
                "type": "boolean",
                "description": "Force LLM vision processing instead of local OCR. Default false.",
            },
        },
        "required": ["image_path"],
    }

    async def execute(self, image_path: str, force_vision: bool = False, llm_client=None, **kwargs) -> str:
        """
        Extract text from image using OCR.

        Args:
            image_path: Absolute path to the image file
            force_vision: If True, skip local OCR and route to LLM vision
            llm_client: LLM client for vision fallback (optional)

        Returns:
            Extracted text from the image
        """
        path = Path(image_path)
        if not path.exists():
            return f"[OCR error] 文件不存在: {image_path}"

        if not path.is_absolute():
            return f"[OCR error] 请使用绝对路径: {image_path}"

        if not _get_router().ocr_available:
            return "[OCR error] 本地 OCR 引擎不可用（未找到 tesseract）"

        if force_vision:
            return "[OCR] Vision mode not implemented — add vision=true only when LLM vision is set up"

        router = _get_router()
        method, text = await router.process(image_path, llm_client=llm_client)

        if method == "ocr":
            if text.strip():
                return text.strip()
            return "[OCR] 未在图片中识别到文字"
        else:
            return "[OCR] 图片内容需要视觉理解，当前未配置 LLM 视觉模型"


class OCRStatus(Tool):
    """Check OCR engine status and availability."""

    name = "OCRStatus"
    description = "Check the status of the local OCR engine (Tesseract or RapidOCR)."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs) -> str:
        router = _get_router()
        if router.ocr_available:
            return f"[OCR] ✅ 可用，引擎: {router.ocr_engine_name}"
        else:
            return "[OCR] ❌ 不可用，请安装 tesseract: brew install tesseract tesseract-lang"