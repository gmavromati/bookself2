"""Free, offline readers that turn shelf photos into spine texts."""

from .base import SpineText
from .ocr import OcrReader
from .ollama import OllamaReader

__all__ = ["SpineText", "OcrReader", "OllamaReader"]
