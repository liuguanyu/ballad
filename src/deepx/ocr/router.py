"""OCR smart router — decide between local OCR and LLM vision."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from deepx.ocr.engine import OCREngine, OCRResult


_CODE_INDICATORS = [
    "def ", "func ", "fn ", "class ", "import ", "from ",
    "interface ", "struct {", "const ", "var ",
    "()", "=>", "->", "//", "/*", "*/",
    "public ", "private ", "async ", "await ",
    "function ", "const ", "let ", "var ",
]
_ERROR_INDICATORS = [
    "error", "exception", "failed", "traceback", "panic",
    "fatal", "warning", "assert", "fail", "errno",
]
_TERMINAL_INDICATORS = [
    "\x1b[", "$ ", "# ", "~$",
    "[1m", "[0m", "[31m", "[32m", "[33m",
]


class OCRRouter:
    """
    Three-layer router for image processing:

    Layer 1 (0ms): Filename heuristics
    Layer 2 (~100ms): OCR text quality assessment
    Layer 3 (~500ms): LLM as judge (only if uncertain)
    """

    def __init__(self):
        self.engine = OCREngine()

    async def process(
        self,
        image_path: str | Path,
        llm_client=None,
    ) -> tuple[Literal["ocr", "vision"], str]:
        """
        Process an image and return (method, result_text).

        method: "ocr" — local OCR was sufficient
               "vision" — LLM vision was used
        result_text: the extracted/described text
        """
        path = Path(image_path)
        filename = path.name.lower()

        # Layer 1: Fast rules
        if self._layer1_ocr_sufficient(filename):
            result = await self.engine.extract(path)
            return "ocr", result.text

        # Layer 2: OCR quality assessment
        result = await self.engine.extract(path)
        assessment = self._assess_ocr_quality(result, path)

        if assessment == "ocr":
            return "ocr", result.text

        if assessment == "vision":
            return "vision", ""

        # Layer 3: LLM as judge (uncertain)
        if llm_client:
            verdict = await self._llm_judge(result.text, llm_client)
            if verdict == "ocr":
                return "ocr", result.text

        return "vision", ""

    def _layer1_ocr_sufficient(self, filename: str) -> bool:
        """Layer 1: Fast filename-based rules."""
        ocr_triggers = ["error", "screenshot", "log", "output", "traceback", "截屏"]
        return any(t in filename for t in ocr_triggers)

    def _assess_ocr_quality(self, result: OCRResult, path: Path) -> Literal["ocr", "vision", "uncertain"]:
        """Layer 2: Assess whether OCR result is sufficient."""
        text = result.text

        # Not available
        if not self.engine.is_available:
            return "vision"

        # Too little text
        if len(text) < 15:
            return "vision"

        # High乱码 rate
        readable = sum(1 for c in text if c.isprintable() or c.isspace())
        if len(text) > 0 and readable / len(text) < 0.7:
            return "vision"

        # Code indicators
        code_hits = sum(1 for kw in _CODE_INDICATORS if kw in text)
        if code_hits >= 2:
            return "ocr"

        # Error indicators
        if any(kw in text.lower() for kw in _ERROR_INDICATORS):
            return "ocr"

        # Terminal indicators
        if any(ind in text for ind in _TERMINAL_INDICATORS):
            return "ocr"

        # Good confidence
        if result.confidence > 0.8 and len(text) > 30:
            return "ocr"

        return "uncertain"

    async def _llm_judge(self, ocr_text: str, llm_client) -> Literal["ocr", "vision"]:
        """
        Layer 3: Ask LLM whether OCR result is sufficient.
        Used only when Layer 2 is uncertain.

        Ask the LLM: does this text look complete and readable,
        or is it likely a visual/cognitive task requiring vision?
        """
        if not llm_client:
            return "vision"

        try:
            from langchain_core.messages import HumanMessage

            response = await llm_client.chat(
                messages=[
                    HumanMessage(content=f"""\
You are a classifier. Given OCR-extracted text from a screenshot, decide:

OCR result:
---
{ocr_text[:500]}
---

Is this text complete and readable, suggesting a normal screenshot with text?
Or does it look incomplete/garbled, suggesting a visual task (diagram, UI, chart)?

Reply with ONLY one word: "ocr" or "vision".""")
                ],
                model="flash",
            )
            content = ""
            if hasattr(response, "content"):
                content = response.content
            elif isinstance(response, str):
                content = str(response)

            content_lower = content.lower().strip()
            if "vision" in content_lower and "ocr" not in content_lower:
                return "vision"
            return "ocr"
        except Exception:
            return "vision"

    @property
    def ocr_available(self) -> bool:
        return self.engine.is_available

    @property
    def ocr_engine_name(self) -> str:
        return self.engine.engine_name