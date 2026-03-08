import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from time import sleep
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import html2text
import markdown
import requests
import tkinter as tk
from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from selenium import webdriver
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from tkinter import filedialog, messagebox, ttk
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from config import EMAIL, PASSWORD

USE_PREMIUM: bool = True
BASE_SUBSTACK_URL: str = "https://www.thefitzwilliam.com/"
BASE_MD_DIR: str = "substack_md_files"
BASE_HTML_DIR: str = "substack_html_pages"
HTML_TEMPLATE: str = "author_template.html"
JSON_DATA_DIR: str = "data"
NUM_POSTS_TO_SCRAPE: int = 3
DEFAULT_OPENAI_MODEL: str = "gpt-5-mini"
DEFAULT_TIMEOUT: int = 120
DEFAULT_TRANSLATION_CHUNK_SIZE: int = 2000
LANGUAGE_LABELS = {
    "中文": "Chinese",
    "英文": "English",
    "日文": "Japanese",
    "法文": "French",
    "德文": "German",
    "西班牙文": "Spanish",
}


def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def extract_main_part(url: str) -> str:
    parts = urlparse(url).netloc.split(".")
    return parts[1] if parts and parts[0] == "www" and len(parts) > 1 else parts[0]


def normalize_substack_input(url: str) -> Tuple[str, Optional[str]]:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Please provide a valid Substack URL.")

    path = parsed.path.rstrip("/")
    if path.startswith("/p/"):
        base_url = f"{parsed.scheme}://{parsed.netloc}/"
        return base_url, f"{parsed.scheme}://{parsed.netloc}{path}"

    return f"{parsed.scheme}://{parsed.netloc}/", None


def ensure_html_assets(base_html_dir: str) -> None:
    asset_targets = [
        ("assets/css/style.css", os.path.join(base_html_dir, "assets/css/style.css")),
        ("assets/css/essay-styles.css", os.path.join(base_html_dir, "assets/css/essay-styles.css")),
        ("assets/js/populate-essays.js", os.path.join(base_html_dir, "assets/js/populate-essays.js")),
    ]
    for source_rel, destination in asset_targets:
        source = resource_path(source_rel)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)


def generate_html_file(author_name: str, base_html_dir: str = BASE_HTML_DIR) -> None:
    if not os.path.exists(base_html_dir):
        os.makedirs(base_html_dir)
    ensure_html_assets(base_html_dir)

    json_path = os.path.join(JSON_DATA_DIR, f"{author_name}.json")
    with open(json_path, "r", encoding="utf-8") as file:
        essays_data = json.load(file)

    embedded_json_data = json.dumps(essays_data, ensure_ascii=False, indent=4)

    with open(resource_path(HTML_TEMPLATE), "r", encoding="utf-8") as file:
        html_template = file.read()

    html_with_data = html_template.replace("<!-- AUTHOR_NAME -->", author_name).replace(
        '<script type="application/json" id="essaysData"></script>',
        f'<script type="application/json" id="essaysData">{embedded_json_data}</script>',
    )
    html_with_author = html_with_data.replace("author_name", author_name)

    html_output_path = os.path.join(base_html_dir, f"{author_name}.html")
    with open(html_output_path, "w", encoding="utf-8") as file:
        file.write(html_with_author)


@dataclass
class TranslationConfig:
    enabled: bool = False
    api_key: str = ""
    target_language: str = "Chinese"
    model: str = DEFAULT_OPENAI_MODEL
    api_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_mode: str = "auto"
    chunk_size: int = DEFAULT_TRANSLATION_CHUNK_SIZE


@dataclass
class ExportOptions:
    save_markdown: bool = True
    save_html: bool = True
    save_pdf: bool = False
    translate: TranslationConfig = field(default_factory=TranslationConfig)
    overwrite_existing: bool = False
    generate_library_index: bool = False


@dataclass
class ScrapedPost:
    url: str
    title: str
    subtitle: str
    like_count: str
    date: str
    markdown_content: str
    markdown_path: Optional[str] = None
    html_path: Optional[str] = None
    pdf_path: Optional[str] = None
    translated_markdown_path: Optional[str] = None
    translated_html_path: Optional[str] = None
    translated_pdf_path: Optional[str] = None


@dataclass
class ScrapeResult:
    author_name: str
    processed_posts: List[ScrapedPost]
    skipped_urls: List[str]


@dataclass
class TranslationResult:
    source_path: str
    translated_markdown_path: Optional[str] = None
    translated_html_path: Optional[str] = None
    translated_pdf_path: Optional[str] = None


def normalize_api_base_url(api_base_url: str) -> str:
    value = api_base_url.strip() or "https://api.openai.com/v1"
    if value.endswith("/responses"):
        return value[:-10]
    return value.rstrip("/")


class PdfExporter:
    def __init__(self) -> None:
        styles = getSampleStyleSheet()
        self.base_font_name = self._register_base_font()
        self.title_style = ParagraphStyle(
            "ArticleTitle",
            parent=styles["Heading1"],
            fontName=self.base_font_name,
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=14,
        )
        self.subtitle_style = ParagraphStyle(
            "ArticleSubtitle",
            parent=styles["Heading2"],
            fontName=self.base_font_name,
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=12,
        )
        self.meta_style = ParagraphStyle(
            "ArticleMeta",
            parent=styles["BodyText"],
            fontName=self.base_font_name,
            fontSize=10,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=16,
        )
        self.body_style = ParagraphStyle(
            "ArticleBody",
            parent=styles["BodyText"],
            fontName=self.base_font_name,
            fontSize=11,
            leading=17,
            spaceAfter=8,
            textColor=colors.HexColor("#111827"),
        )
        self.heading_styles = {
            1: ParagraphStyle("H1", parent=styles["Heading1"], fontName=self.base_font_name, textColor=colors.HexColor("#111827")),
            2: ParagraphStyle("H2", parent=styles["Heading2"], fontName=self.base_font_name, textColor=colors.HexColor("#1f2937")),
            3: ParagraphStyle("H3", parent=styles["Heading3"], fontName=self.base_font_name, textColor=colors.HexColor("#334155")),
        }

    @staticmethod
    def _register_base_font() -> str:
        font_name = "STSong-Light"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        return font_name

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )

    def markdown_to_story(self, post: ScrapedPost) -> List[object]:
        story: List[object] = [
            Paragraph(self._escape(post.title), self.title_style),
        ]
        if post.subtitle:
            story.append(Paragraph(self._escape(post.subtitle), self.subtitle_style))
        story.append(Paragraph(self._escape(f"{post.date} | Likes: {post.like_count}"), self.meta_style))

        lines = post.markdown_content.splitlines()
        body_lines = lines[4:] if len(lines) > 4 else lines
        buffer: List[str] = []

        def flush_buffer() -> None:
            if not buffer:
                return
            paragraph = " ".join(line.strip() for line in buffer if line.strip())
            if paragraph:
                story.append(Paragraph(self._escape(paragraph), self.body_style))
            buffer.clear()

        for line in body_lines:
            stripped = line.strip()
            if not stripped:
                flush_buffer()
                story.append(Spacer(1, 0.08 * inch))
                continue

            if stripped.startswith("### "):
                flush_buffer()
                story.append(Paragraph(self._escape(stripped[4:]), self.heading_styles[3]))
                continue
            if stripped.startswith("## "):
                flush_buffer()
                story.append(Paragraph(self._escape(stripped[3:]), self.heading_styles[2]))
                continue
            if stripped.startswith("# "):
                flush_buffer()
                story.append(Paragraph(self._escape(stripped[2:]), self.heading_styles[1]))
                continue
            if stripped.startswith(("-", "*", ">")):
                flush_buffer()
                cleaned = stripped.lstrip("-*> ").strip()
                story.append(Paragraph(self._escape(f"- {cleaned}"), self.body_style))
                continue

            buffer.append(stripped)

        flush_buffer()
        return story

    def export(self, filepath: str, post: ScrapedPost) -> None:
        document = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            title=post.title,
            author="Substack2Markdown",
            leftMargin=0.8 * inch,
            rightMargin=0.8 * inch,
            topMargin=0.8 * inch,
            bottomMargin=0.8 * inch,
        )
        document.build(self.markdown_to_story(post))


class OpenAITranslator:
    def __init__(
        self,
        config: TranslationConfig,
        logger: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.config = config
        self.logger = logger or (lambda message: None)
        self.progress_callback = progress_callback or (lambda current, total: None)

    def translate_markdown(self, markdown_text: str) -> str:
        if not self.config.enabled:
            return markdown_text
        if not self.config.api_key.strip():
            raise ValueError("OpenAI API key is required when translation is enabled.")

        chunks = self._chunk_markdown(markdown_text, chunk_size=max(500, self.config.chunk_size))
        self.progress_callback(0, len(chunks))
        translated_chunks: List[str] = []
        for index, chunk in enumerate(chunks, start=1):
            translated_chunks.append(self._translate_chunk(chunk))
            self.progress_callback(index, len(chunks))
        return "\n\n".join(translated_chunks)

    @staticmethod
    def _chunk_markdown(markdown_text: str, chunk_size: int = DEFAULT_TRANSLATION_CHUNK_SIZE) -> List[str]:
        paragraphs = markdown_text.split("\n\n")
        chunks: List[str] = []
        current = ""

        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(paragraph) <= chunk_size:
                current = paragraph
                continue
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start:start + chunk_size])
                start += chunk_size
            current = ""

        if current:
            chunks.append(current)
        return chunks or [markdown_text]

    def _translate_chunk(self, text: str) -> str:
        base_url = normalize_api_base_url(self.config.api_base_url)
        prompt = self._build_translation_prompt(strict=False)
        retry_prompt = self._build_translation_prompt(strict=True)

        modes = [self.config.api_mode]
        if self.config.api_mode == "auto":
            if "api.openai.com" in base_url:
                modes = ["responses", "chat"]
            else:
                modes = ["chat"]

        last_error: Optional[Exception] = None
        for mode in modes:
            try:
                return self._translate_chunk_with_mode(base_url, mode, prompt, retry_prompt, text)
            except Exception as error:
                last_error = error
                self.logger(f"Translation mode '{mode}' failed, trying next mode.")

        if last_error:
            raise last_error
        raise ValueError("Translation failed without a response.")

    def _build_translation_prompt(self, strict: bool) -> str:
        if strict:
            return (
                "You are a deterministic Markdown translation engine.\n"
                f"Translate the user content into {self.config.target_language}.\n"
                "Mandatory rules:\n"
                "1. Translate every sentence completely.\n"
                "2. Preserve Markdown structure and paragraph boundaries exactly.\n"
                "3. Do not summarize, explain, analyze, comment, or answer questions.\n"
                "4. Do not add any preface, note, apology, title, or code fence.\n"
                "5. Keep headings, lists, links, quotes, emphasis, tables, and numbering intact.\n"
                "6. Output only the translated Markdown content.\n"
                "7. If the input is already in the target language, return it unchanged.\n"
                "8. If you are about to summarize or comment, return an empty string instead.\n"
                "Bad output examples:\n"
                "- Summarizing article excerpt\n"
                "- The core idea seems to be\n"
                "- This article argues that\n"
                "Good output example:\n"
                "- A direct line-by-line translation of the Markdown."
            )
        return (
            "You are a strict translation engine.\n"
            f"Translate the provided Markdown into {self.config.target_language}.\n"
            "Rules:\n"
            "1. Preserve Markdown structure exactly.\n"
            "2. Do not summarize.\n"
            "3. Do not explain.\n"
            "4. Do not answer as an assistant.\n"
            "5. Do not add prefaces or notes.\n"
            "6. Return only translated Markdown.\n"
            "7. Keep headings, lists, links, quotes, emphasis, and tables intact.\n"
            "8. Translate the full content, not an excerpt.\n"
            "If you cannot comply, return an empty string."
        )

    def _translate_chunk_with_mode(
        self,
        base_url: str,
        mode: str,
        prompt: str,
        retry_prompt: str,
        text: str,
    ) -> str:
        attempts = [
            ("primary", prompt),
            ("strict-retry", retry_prompt),
        ]
        last_error: Optional[Exception] = None
        for attempt_name, attempt_prompt in attempts:
            try:
                if mode == "responses":
                    translated = self._translate_via_responses(base_url, attempt_prompt, text)
                    self._validate_translated_chunk(translated)
                    return translated
                if mode == "chat":
                    translated = self._translate_via_chat_completions(base_url, attempt_prompt, text)
                    self._validate_translated_chunk(translated)
                    return translated
            except Exception as error:
                last_error = error
                if self._is_summary_like_error(error) and attempt_name == "primary":
                    self.logger("检测到模型返回总结/评论内容，正在用更严格的翻译提示词重试。")
                    continue
                raise
        if last_error:
            raise last_error
        raise ValueError("Translation failed without a response.")

    @staticmethod
    def _is_summary_like_error(error: Exception) -> bool:
        return "总结/评论内容" in str(error)

    def _validate_translated_chunk(self, translated: str) -> None:
        lowered = translated.lower()
        suspicious_phrases = [
            "the user pasted",
            "i can summarize",
            "since there’s no direct question",
            "since there's no direct question",
            "summarizing article excerpt",
            "the core idea seems to be",
            "this is a sharp setup",
            "i could engage by",
            "i appreciate you sharing this content",
            "i appreciate you sharing this text",
            "i need to clarify my role here",
            "i'm claude",
            "made by anthropic",
            "what would be most useful for you",
            "i'm here for that",
            "software engineering tasks",
            "debugging, refactoring",
        ]
        if any(phrase in lowered for phrase in suspicious_phrases):
            raise ValueError("模型没有执行翻译，而是返回了总结/评论内容。请更换模型或接口模式。")
        if not translated.strip():
            raise ValueError("模型返回了空结果。")
        if self._target_language_requires_script_check() and not re.search(r"[\u4e00-\u9fff]", translated):
            raise ValueError("模型返回的内容看起来不是目标语言翻译结果。请更换模型或接口模式。")

    def _target_language_requires_script_check(self) -> bool:
        normalized = self.config.target_language.strip().lower()
        return normalized in {"chinese", "中文"}

    def _request_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _translate_via_responses(self, base_url: str, prompt: str, text: str) -> str:
        response = requests.post(
            f"{base_url}/responses",
            headers=self._request_headers(),
            json={
                "model": self.config.model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": prompt}],
                    },
                    {"role": "user", "content": [{"type": "input_text", "text": text}]},
                ],
            },
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise_for_status(response)
        payload = response.json()
        output_text = payload.get("output_text")
        if output_text:
            return output_text.strip()

        pieces: List[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                text_value = content.get("text")
                if text_value:
                    pieces.append(text_value)
        if not pieces:
            raise ValueError("Responses API did not return translated text.")
        return "\n".join(pieces).strip()

    def _translate_via_chat_completions(self, base_url: str, prompt: str, text: str) -> str:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers=self._request_headers(),
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
            },
            timeout=DEFAULT_TIMEOUT,
        )
        self._raise_for_status(response)
        payload = response.json()
        choices = payload.get("choices", [])
        if not choices:
            raise ValueError("Chat Completions API did not return choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            combined = "\n".join(part for part in parts if part.strip()).strip()
            if combined:
                return combined
        raise ValueError("Chat Completions API did not return translated text.")

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            message = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    error_value = payload.get("error")
                    if isinstance(error_value, dict):
                        message = str(error_value.get("message") or payload)
                    else:
                        message = str(payload)
            except ValueError:
                message = response.text.strip()
            if len(message) > 200:
                message = message[:200] + "..."
            raise RuntimeError(
                f"API 请求失败：HTTP {response.status_code}，地址 {response.url}，响应 {message or 'empty body'}"
            ) from error


def slugify_language(language: str) -> str:
    return language.lower().replace(" ", "-")


def normalize_target_language(language: str) -> str:
    return LANGUAGE_LABELS.get(language, language)


def parse_downloaded_markdown(markdown_path: str) -> ScrapedPost:
    with open(markdown_path, "r", encoding="utf-8") as file:
        markdown_content = file.read()

    lines = markdown_content.splitlines()
    title = lines[0][2:].strip() if lines and lines[0].startswith("# ") else Path(markdown_path).stem
    subtitle = ""
    date = "Date not found"
    like_count = "0"

    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("## ") and not subtitle:
            subtitle = line[3:].strip()
        elif line.startswith("**Likes:**"):
            like_count = line.replace("**Likes:**", "").strip()
        elif line.startswith("**") and line.endswith("**") and "Likes:" not in line:
            date = line.strip("* ").strip()
        if index > 10:
            break

    return ScrapedPost(
        url="",
        title=title,
        subtitle=subtitle,
        like_count=like_count,
        date=date,
        markdown_content=markdown_content,
        markdown_path=markdown_path,
    )


def translate_markdown_file(
    markdown_path: str,
    translation_config: TranslationConfig,
    html_output_dir: Optional[str] = None,
    overwrite: bool = False,
    logger: Optional[Callable[[str], None]] = None,
    save_markdown: bool = True,
    save_html: bool = True,
    save_pdf: bool = True,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> TranslationResult:
    logger = logger or (lambda message: None)
    progress_callback = progress_callback or (lambda current, total: None)
    source_post = parse_downloaded_markdown(markdown_path)
    translator = OpenAITranslator(
        translation_config,
        logger=logger,
        progress_callback=lambda current, total: (progress_callback(current, total), logger(f"TRANSLATION_PROGRESS {current}/{total}")),
    )
    translated_markdown = translator.translate_markdown(source_post.markdown_content)
    translator._validate_translated_chunk(translated_markdown)
    translated_post = ScrapedPost(
        url=source_post.url,
        title=f"{source_post.title} ({translation_config.target_language})",
        subtitle=source_post.subtitle,
        like_count=source_post.like_count,
        date=source_post.date,
        markdown_content=translated_markdown,
    )

    source = Path(markdown_path)
    suffix = slugify_language(translation_config.target_language)
    translated_markdown_path = str(source.with_name(f"{source.stem}.{suffix}.md"))
    translated_html_dir = html_output_dir or str(source.parent)
    os.makedirs(translated_html_dir, exist_ok=True)
    translated_html_path = os.path.join(translated_html_dir, f"{source.stem}.{suffix}.html")
    translated_pdf_path = os.path.join(translated_html_dir, f"{source.stem}.{suffix}.pdf")

    if save_markdown:
        if overwrite or not os.path.exists(translated_markdown_path):
            with open(translated_markdown_path, "w", encoding="utf-8") as file:
                file.write(translated_markdown)
        else:
            logger(f"File already exists: {translated_markdown_path}")
    else:
        translated_markdown_path = None

    if save_html:
        html_content = BaseSubstackScraper.md_to_html(translated_markdown)
        BaseSubstackScraper.save_to_html_file(translated_html_path, html_content)
    else:
        translated_html_path = None

    if save_pdf:
        PdfExporter().export(translated_pdf_path, translated_post)
    else:
        translated_pdf_path = None

    return TranslationResult(
        source_path=markdown_path,
        translated_markdown_path=translated_markdown_path,
        translated_html_path=translated_html_path,
        translated_pdf_path=translated_pdf_path,
    )


def translate_markdown_directory(
    markdown_directory: str,
    translation_config: TranslationConfig,
    html_output_dir: Optional[str] = None,
    overwrite: bool = False,
    logger: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    save_markdown: bool = True,
    save_html: bool = True,
    save_pdf: bool = True,
) -> List[TranslationResult]:
    logger = logger or (lambda message: None)
    progress_callback = progress_callback or (lambda current, total: None)
    markdown_files = sorted(
        [
            str(path)
            for path in Path(markdown_directory).rglob("*.md")
            if f".{slugify_language(translation_config.target_language)}.md" not in path.name
        ]
    )
    results: List[TranslationResult] = []
    total = len(markdown_files)
    for index, markdown_path in enumerate(markdown_files, start=1):
        logger(f"Translating downloaded article {markdown_path}")
        results.append(
            translate_markdown_file(
                markdown_path,
                translation_config=translation_config,
                html_output_dir=html_output_dir,
                overwrite=overwrite,
                logger=logger,
                save_markdown=save_markdown,
                save_html=save_html,
                save_pdf=save_pdf,
                progress_callback=progress_callback,
            )
        )
    return results


class BaseSubstackScraper:
    def __init__(
        self,
        base_substack_url: str,
        md_save_dir: str,
        html_save_dir: str,
        logger: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        target_post_url: Optional[str] = None,
    ):
        if not base_substack_url.endswith("/"):
            base_substack_url += "/"
        self.base_substack_url = base_substack_url
        self.writer_name = extract_main_part(base_substack_url)
        self.md_save_dir = os.path.join(md_save_dir, self.writer_name)
        self.html_save_dir = os.path.join(html_save_dir, self.writer_name)
        self.logger = logger or (lambda message: None)
        self.progress_callback = progress_callback or (lambda current, total: None)
        self.target_post_url = target_post_url
        self.keywords = ["about", "archive", "podcast"]

        os.makedirs(self.md_save_dir, exist_ok=True)
        os.makedirs(self.html_save_dir, exist_ok=True)

        self.post_urls = self.get_all_post_urls()
        if self.target_post_url:
            self.post_urls = [url for url in self.post_urls if url.rstrip("/") == self.target_post_url.rstrip("/")]
            if not self.post_urls:
                self.post_urls = [self.target_post_url]

    def get_all_post_urls(self) -> List[str]:
        urls = self.fetch_urls_from_sitemap()
        if not urls:
            urls = self.fetch_urls_from_feed()
        return self.filter_urls(urls, self.keywords)

    def fetch_urls_from_sitemap(self) -> List[str]:
        sitemap_url = f"{self.base_substack_url}sitemap.xml"
        response = requests.get(sitemap_url, timeout=DEFAULT_TIMEOUT)
        if not response.ok:
            self.logger(f"Error fetching sitemap at {sitemap_url}: {response.status_code}")
            return []
        root = ET.fromstring(response.content)
        return [element.text for element in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if element.text]

    def fetch_urls_from_feed(self) -> List[str]:
        self.logger("Falling back to feed.xml. This will only contain up to the 22 most recent posts.")
        feed_url = f"{self.base_substack_url}feed.xml"
        response = requests.get(feed_url, timeout=DEFAULT_TIMEOUT)
        if not response.ok:
            self.logger(f"Error fetching feed at {feed_url}: {response.status_code}")
            return []
        root = ET.fromstring(response.content)
        urls: List[str] = []
        for item in root.findall(".//item"):
            link = item.find("link")
            if link is not None and link.text:
                urls.append(link.text)
        return urls

    @staticmethod
    def filter_urls(urls: List[str], keywords: List[str]) -> List[str]:
        return [url for url in urls if all(keyword not in url for keyword in keywords)]

    @staticmethod
    def html_to_md(html_content: str) -> str:
        parser = html2text.HTML2Text()
        parser.ignore_links = False
        parser.body_width = 0
        return parser.handle(html_content)

    @staticmethod
    def md_to_html(md_content: str) -> str:
        return markdown.markdown(md_content, extensions=["extra"])

    @staticmethod
    def get_filename_from_url(url: str, filetype: str = ".md") -> str:
        if not filetype.startswith("."):
            filetype = f".{filetype}"
        return url.rstrip("/").split("/")[-1] + filetype

    @staticmethod
    def combine_metadata_and_content(title: str, subtitle: str, date: str, like_count: str, content: str) -> str:
        metadata = f"# {title}\n\n"
        if subtitle:
            metadata += f"## {subtitle}\n\n"
        metadata += f"**{date}**\n\n"
        metadata += f"**Likes:** {like_count}\n\n"
        return metadata + content

    def extract_post_data(self, soup: BeautifulSoup) -> Tuple[str, str, str, str, str]:
        title_element = soup.select_one("h1.post-title, h2")
        title = title_element.text.strip() if title_element else "Untitled"

        subtitle_element = soup.select_one("h3.subtitle")
        subtitle = subtitle_element.text.strip() if subtitle_element else ""

        date = ""
        date_element = soup.select_one("div.pencraft.pc-reset.color-pub-secondary-text-hGQ02T")
        if date_element and date_element.text.strip():
            date = date_element.text.strip()

        if not date:
            script_tag = soup.find("script", {"type": "application/ld+json"})
            if script_tag and script_tag.string:
                try:
                    metadata = json.loads(script_tag.string)
                    if "datePublished" in metadata:
                        date_str = metadata["datePublished"]
                        date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        date = date_obj.strftime("%b %d, %Y")
                except (json.JSONDecodeError, ValueError, KeyError):
                    date = ""

        if not date:
            date = "Date not found"

        like_count_element = soup.select_one("a.post-ufi-button .label")
        like_count = like_count_element.text.strip() if like_count_element and like_count_element.text.strip().isdigit() else "0"

        content_element = soup.select_one("div.available-content")
        content_html = str(content_element) if content_element else ""
        markdown_content = self.html_to_md(content_html)
        combined = self.combine_metadata_and_content(title, subtitle, date, like_count, markdown_content)
        return title, subtitle, like_count, date, combined

    @staticmethod
    def save_to_html_file(filepath: str, content: str) -> None:
        with open(resource_path("assets/css/essay-styles.css"), "r", encoding="utf-8") as css_file:
            embedded_css = css_file.read()
        html_content = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Markdown Content</title>
                <style>{embedded_css}</style>
            </head>
            <body>
                <main class="markdown-content">
                {content}
                </main>
            </body>
            </html>
        """
        with open(filepath, "w", encoding="utf-8") as file:
            file.write(html_content)

    def save_essays_data_to_json(self, essays_data: List[dict]) -> None:
        os.makedirs(JSON_DATA_DIR, exist_ok=True)
        json_path = os.path.join(JSON_DATA_DIR, f"{self.writer_name}.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as file:
                existing_data = json.load(file)
            essays_data = existing_data + [data for data in essays_data if data not in existing_data]
        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(essays_data, file, ensure_ascii=False, indent=4)

    def _write_text_file(self, path: str, content: str, overwrite: bool) -> None:
        if os.path.exists(path) and not overwrite:
            self.logger(f"File already exists: {path}")
            return
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    def scrape_posts(self, num_posts_to_scrape: int = 0, export_options: Optional[ExportOptions] = None) -> ScrapeResult:
        options = export_options or ExportOptions()
        translator = OpenAITranslator(options.translate, logger=self.logger)
        pdf_exporter = PdfExporter()
        processed_posts: List[ScrapedPost] = []
        skipped_urls: List[str] = []

        urls = self.post_urls[:num_posts_to_scrape] if num_posts_to_scrape else self.post_urls
        total = len(urls)
        for index, url in enumerate(urls, start=1):
            self.progress_callback(index - 1, total)
            self.logger(f"Processing {url}")
            try:
                soup = self.get_url_soup(url)
                if soup is None:
                    skipped_urls.append(url)
                    continue

                title, subtitle, like_count, date, markdown_content = self.extract_post_data(soup)
                post = ScrapedPost(
                    url=url,
                    title=title,
                    subtitle=subtitle,
                    like_count=like_count,
                    date=date,
                    markdown_content=markdown_content,
                )

                slug = self.get_filename_from_url(url, "").rstrip(".")
                if options.save_markdown:
                    md_path = os.path.join(self.md_save_dir, f"{slug}.md")
                    self._write_text_file(md_path, markdown_content, options.overwrite_existing)
                    post.markdown_path = md_path
                if options.save_html:
                    html_path = os.path.join(self.html_save_dir, f"{slug}.html")
                    html_content = self.md_to_html(markdown_content)
                    if not os.path.exists(html_path) or options.overwrite_existing:
                        self.save_to_html_file(html_path, html_content)
                    post.html_path = html_path
                if options.save_pdf:
                    pdf_path = os.path.join(self.html_save_dir, f"{slug}.pdf")
                    if not os.path.exists(pdf_path) or options.overwrite_existing:
                        pdf_exporter.export(pdf_path, post)
                    post.pdf_path = pdf_path

                if options.translate.enabled:
                    translated_markdown = translator.translate_markdown(markdown_content)
                    translated_post = ScrapedPost(
                        url=url,
                        title=f"{title} ({options.translate.target_language})",
                        subtitle=subtitle,
                        like_count=like_count,
                        date=date,
                        markdown_content=translated_markdown,
                    )
                    translated_slug = f"{slug}.{options.translate.target_language.lower().replace(' ', '-')}"
                    if options.save_markdown:
                        translated_md_path = os.path.join(self.md_save_dir, f"{translated_slug}.md")
                        self._write_text_file(translated_md_path, translated_markdown, options.overwrite_existing)
                        post.translated_markdown_path = translated_md_path
                    if options.save_html:
                        translated_html_path = os.path.join(self.html_save_dir, f"{translated_slug}.html")
                        if not os.path.exists(translated_html_path) or options.overwrite_existing:
                            self.save_to_html_file(translated_html_path, self.md_to_html(translated_markdown))
                        post.translated_html_path = translated_html_path
                    if options.save_pdf:
                        translated_pdf_path = os.path.join(self.html_save_dir, f"{translated_slug}.pdf")
                        if not os.path.exists(translated_pdf_path) or options.overwrite_existing:
                            pdf_exporter.export(translated_pdf_path, translated_post)
                        post.translated_pdf_path = translated_pdf_path

                processed_posts.append(post)
            except Exception as error:
                self.logger(f"Error scraping {url}: {error}")
                skipped_urls.append(url)
            finally:
                self.progress_callback(index, total)

        if options.generate_library_index and processed_posts:
            essays_data = [
                {
                    "title": post.title,
                    "subtitle": post.subtitle,
                    "like_count": post.like_count,
                    "date": post.date,
                    "file_link": post.markdown_path or "",
                    "html_link": post.html_path or "",
                    "pdf_link": post.pdf_path or "",
                }
                for post in processed_posts
            ]
            self.save_essays_data_to_json(essays_data)
            generate_html_file(author_name=self.writer_name, base_html_dir=os.path.dirname(self.html_save_dir))
        return ScrapeResult(author_name=self.writer_name, processed_posts=processed_posts, skipped_urls=skipped_urls)

    def get_url_soup(self, url: str) -> Optional[BeautifulSoup]:
        raise NotImplementedError


class SubstackScraper(BaseSubstackScraper):
    def get_url_soup(self, url: str) -> Optional[BeautifulSoup]:
        page = requests.get(url, headers=None, timeout=DEFAULT_TIMEOUT)
        soup = BeautifulSoup(page.content, "html.parser")
        if soup.find("h2", class_="paywall-title"):
            self.logger(f"Skipping premium article: {url}")
            return None
        return soup


class PremiumSubstackScraper(BaseSubstackScraper):
    def __init__(
        self,
        base_substack_url: str,
        md_save_dir: str,
        html_save_dir: str,
        headless: bool = False,
        edge_path: str = "",
        edge_driver_path: str = "",
        user_agent: str = "",
        logger: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        target_post_url: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.email = email or EMAIL
        self.password = password or PASSWORD
        super().__init__(
            base_substack_url,
            md_save_dir,
            html_save_dir,
            logger=logger,
            progress_callback=progress_callback,
            target_post_url=target_post_url,
        )

        options = EdgeOptions()
        if headless:
            options.add_argument("--headless=new")
        if edge_path:
            options.binary_location = edge_path
        if user_agent:
            options.add_argument(f"user-agent={user_agent}")

        os.environ.setdefault("SE_DRIVER_MIRROR_URL", "https://msedgedriver.microsoft.com")
        self.driver = None

        if edge_driver_path and os.path.exists(edge_driver_path):
            service = Service(executable_path=edge_driver_path)
            self.driver = webdriver.Edge(service=service, options=options)
        else:
            try:
                service = Service(EdgeChromiumDriverManager().install())
                self.driver = webdriver.Edge(service=service, options=options)
            except Exception:
                self.logger("webdriver_manager failed, falling back to Selenium Manager.")
                try:
                    self.driver = webdriver.Edge(options=options)
                except SessionNotCreatedException as error:
                    raise RuntimeError(
                        "Selenium Manager failed due to driver/browser mismatch. "
                        "Pass --edge-driver-path to a matching Edge WebDriver."
                    ) from error

        self.login()

    def login(self) -> None:
        if not self.email or not self.password or "your-email" in self.email:
            raise ValueError("Premium mode requires valid Substack credentials.")
        self.driver.get("https://substack.com/sign-in")
        sleep(3)
        signin_with_password = self.driver.find_element(By.XPATH, "//a[@class='login-option substack-login__login-option']")
        signin_with_password.click()
        sleep(3)

        email = self.driver.find_element(By.NAME, "email")
        password = self.driver.find_element(By.NAME, "password")
        email.send_keys(self.email)
        password.send_keys(self.password)

        submit = self.driver.find_element(By.XPATH, "//*[@id=\"substack-login\"]/div[2]/div[2]/form/button")
        submit.click()
        sleep(30)

        if self.is_login_failed():
            raise RuntimeError(
                "Login unsuccessful. Check your Substack credentials. "
                "If headless mode is enabled, try running without headless to inspect captcha."
            )

    def is_login_failed(self) -> bool:
        error_container = self.driver.find_elements(By.ID, "error-container")
        return len(error_container) > 0 and error_container[0].is_displayed()

    def get_url_soup(self, url: str) -> Optional[BeautifulSoup]:
        self.driver.get(url)
        return BeautifulSoup(self.driver.page_source, "html.parser")


def build_scraper(
    url: str,
    premium: bool,
    md_directory: str,
    html_directory: str,
    logger: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    headless: bool = False,
    edge_path: str = "",
    edge_driver_path: str = "",
    user_agent: str = "",
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> BaseSubstackScraper:
    base_url, target_post_url = normalize_substack_input(url)
    if premium:
        return PremiumSubstackScraper(
            base_url,
            md_directory,
            html_directory,
            headless=headless,
            edge_path=edge_path,
            edge_driver_path=edge_driver_path,
            user_agent=user_agent,
            logger=logger,
            progress_callback=progress_callback,
            target_post_url=target_post_url,
            email=email,
            password=password,
        )

    return SubstackScraper(
        base_url,
        md_directory,
        html_directory,
        logger=logger,
        progress_callback=progress_callback,
        target_post_url=target_post_url,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape a Substack site and export articles.")
    parser.add_argument("-u", "--url", type=str, help="The Substack site URL or a direct post URL.")
    parser.add_argument("-d", "--directory", type=str, default=BASE_MD_DIR, help="The directory to save markdown files.")
    parser.add_argument("--html-directory", type=str, default=BASE_HTML_DIR, help="The directory to save HTML and PDF files.")
    parser.add_argument("-n", "--number", type=int, default=0, help="The number of posts to scrape. 0 means all.")
    parser.add_argument("-p", "--premium", action="store_true", help="Use the Selenium-based premium scraper.")
    parser.add_argument("--headless", action="store_true", help="Run the premium browser in headless mode.")
    parser.add_argument("--edge-path", type=str, default="", help="Optional path to Microsoft Edge.")
    parser.add_argument("--edge-driver-path", type=str, default="", help="Optional path to Edge WebDriver.")
    parser.add_argument("--user-agent", type=str, default="", help="Optional custom user agent for Selenium.")
    parser.add_argument("--format", action="append", choices=["md", "html", "pdf"], help="Choose output format(s). Repeatable.")
    parser.add_argument("--translate", action="store_true", help="Translate markdown with the OpenAI API.")
    parser.add_argument("--translate-file", type=str, default="", help="Translate an existing downloaded markdown file.")
    parser.add_argument("--translate-directory", type=str, default="", help="Translate all downloaded markdown files in a directory.")
    parser.add_argument("--target-language", type=str, default="Chinese", help="Target language for translation.")
    parser.add_argument("--openai-api-key", type=str, default=os.getenv("OPENAI_API_KEY", ""), help="OpenAI API key.")
    parser.add_argument("--openai-base-url", type=str, default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"), help="OpenAI-compatible API base URL.")
    parser.add_argument("--openai-api-mode", choices=["auto", "responses", "chat"], default=os.getenv("OPENAI_API_MODE", "auto"), help="OpenAI-compatible API mode.")
    parser.add_argument("--openai-model", type=str, default=DEFAULT_OPENAI_MODEL, help="OpenAI model for translation.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--email", type=str, default=os.getenv("SUBSTACK_EMAIL", ""), help="Substack login email for premium mode.")
    parser.add_argument("--password", type=str, default=os.getenv("SUBSTACK_PASSWORD", ""), help="Substack login password for premium mode.")
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI.")
    return parser.parse_args()


def resolve_output_formats(formats: Optional[List[str]], default_formats: Optional[List[str]] = None) -> tuple[bool, bool, bool]:
    chosen = formats or default_formats or ["md", "html"]
    return "md" in chosen, "html" in chosen, "pdf" in chosen


class SubstackDownloaderGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Substack Studio 中文版")
        self.root.geometry("1120x760")
        self.root.minsize(980, 680)
        self.root.configure(bg="#f4efe6")
        self.queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self._build_style()
        self._build_variables()
        self._build_layout()
        self.root.after(100, self._process_queue)

    def _build_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#f4efe6")
        style.configure("Card.TFrame", background="#fbf7f0", relief="flat")
        style.configure("Title.TLabel", background="#f4efe6", foreground="#1f2937", font=("Avenir Next", 24, "bold"))
        style.configure("Subtitle.TLabel", background="#f4efe6", foreground="#6b7280", font=("Avenir Next", 11))
        style.configure("Section.TLabel", background="#fbf7f0", foreground="#111827", font=("Avenir Next", 12, "bold"))
        style.configure("Body.TLabel", background="#fbf7f0", foreground="#4b5563", font=("Avenir Next", 10))
        style.configure("Accent.TButton", background="#c26a2e", foreground="#ffffff", font=("Avenir Next", 11, "bold"), borderwidth=0, padding=10)
        style.map("Accent.TButton", background=[("active", "#a95822")])
        style.configure("Ghost.TButton", background="#efe4d4", foreground="#7c4a23", font=("Avenir Next", 10, "bold"), borderwidth=0, padding=8)
        style.map("Ghost.TButton", background=[("active", "#e2d1bc")])
        style.configure("TCheckbutton", background="#fbf7f0", foreground="#374151", font=("Avenir Next", 10))
        style.configure("TRadiobutton", background="#fbf7f0", foreground="#374151", font=("Avenir Next", 10))
        style.configure("TEntry", fieldbackground="#fffdf8", padding=7)
        style.configure("TCombobox", padding=6)
        style.configure("Horizontal.TProgressbar", troughcolor="#eadfce", background="#c26a2e", thickness=8)

    def _build_variables(self) -> None:
        self.url_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="download")
        self.md_dir_var = tk.StringVar(value=os.path.abspath(BASE_MD_DIR))
        self.html_dir_var = tk.StringVar(value=os.path.abspath(BASE_HTML_DIR))
        self.translation_source_var = tk.StringVar()
        self.translation_output_var = tk.StringVar(value=os.path.abspath(BASE_HTML_DIR))
        self.count_var = tk.StringVar(value="0")
        self.premium_var = tk.BooleanVar(value=False)
        self.headless_var = tk.BooleanVar(value=False)
        self.md_output_var = tk.BooleanVar(value=True)
        self.html_output_var = tk.BooleanVar(value=False)
        self.pdf_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.target_language_var = tk.StringVar(value="中文")
        self.openai_model_var = tk.StringVar(value=DEFAULT_OPENAI_MODEL)
        self.api_key_var = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        self.api_base_url_var = tk.StringVar(value=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        self.api_mode_var = tk.StringVar(value=os.getenv("OPENAI_API_MODE", "auto"))
        self.email_var = tk.StringVar(value=os.getenv("SUBSTACK_EMAIL", EMAIL if "your-email" not in EMAIL else ""))
        self.password_var = tk.StringVar(value=os.getenv("SUBSTACK_PASSWORD", PASSWORD if "your-password" not in PASSWORD else ""))
        self.progress_var = tk.StringVar(value="空闲")
        self.last_output_dir: Optional[str] = None

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=24)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="Root.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Substack Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="下载 Substack、导出 PDF，并对已下载文章进行 OpenAI 翻译。",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(outer, style="Root.TFrame")
        body.pack(fill="both", expand=True, pady=(20, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Card.TFrame", padding=20)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(body, style="Card.TFrame", padding=20)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_form(left)
        self._build_console(right)

    def _build_form(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        row = 0

        def add_label(text: str, subtitle: Optional[str] = None) -> None:
            nonlocal row
            ttk.Label(parent, text=text, style="Section.TLabel").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 2))
            row += 1
            if subtitle:
                ttk.Label(parent, text=subtitle, style="Body.TLabel").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
                row += 1

        add_label("工作模式", "可以直接下载文章，也可以翻译已经下载好的 Markdown 文章。")
        ttk.Radiobutton(parent, text="下载文章", value="download", variable=self.mode_var).grid(row=row, column=0, sticky="w", pady=(0, 12))
        ttk.Radiobutton(parent, text="翻译已下载文章", value="translate", variable=self.mode_var).grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 12))
        row += 1

        add_label("下载目标", "下载模式下可填写 Substack 首页地址或单篇文章链接。")
        ttk.Entry(parent, textvariable=self.url_var).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 16))
        row += 1

        add_label("输出目录")
        ttk.Label(parent, text="Markdown 目录", style="Body.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.md_dir_var).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(parent, text="选择", style="Ghost.TButton", command=lambda: self._pick_directory(self.md_dir_var)).grid(row=row, column=2, sticky="ew")
        row += 1
        ttk.Label(parent, text="HTML / PDF 目录", style="Body.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(parent, textvariable=self.html_dir_var).grid(row=row, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(parent, text="选择", style="Ghost.TButton", command=lambda: self._pick_directory(self.html_dir_var)).grid(row=row, column=2, sticky="ew", pady=(8, 0))
        row += 1

        add_label("翻译来源", "翻译模式下可选择单个 Markdown 文件或整个 Markdown 文件夹。")
        ttk.Entry(parent, textvariable=self.translation_source_var).grid(row=row, column=0, columnspan=2, sticky="ew")
        pick_frame = ttk.Frame(parent, style="Card.TFrame")
        pick_frame.grid(row=row, column=2, sticky="ew")
        ttk.Button(pick_frame, text="文件", style="Ghost.TButton", command=self._pick_translation_file).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(pick_frame, text="文件夹", style="Ghost.TButton", command=self._pick_translation_directory).pack(side="left", fill="x", expand=True)
        row += 1
        ttk.Label(parent, text="翻译后 HTML / PDF 目录", style="Body.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(parent, textvariable=self.translation_output_var).grid(row=row, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(parent, text="选择", style="Ghost.TButton", command=lambda: self._pick_directory(self.translation_output_var)).grid(row=row, column=2, sticky="ew", pady=(8, 0))
        row += 1

        add_label("抓取设置")
        ttk.Label(parent, text="文章数量（0 表示全部）", style="Body.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.count_var, width=8).grid(row=row, column=1, sticky="w", padx=8)
        row += 1
        ttk.Checkbutton(parent, text="付费模式", variable=self.premium_var).grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(parent, text="无头浏览器", variable=self.headless_var).grid(row=row, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(parent, text="覆盖已有文件", variable=self.overwrite_var).grid(row=row, column=2, sticky="w", pady=(8, 0))
        row += 1

        add_label("导出与翻译")
        ttk.Checkbutton(parent, text="输出 Markdown", variable=self.md_output_var).grid(row=row, column=0, sticky="w")
        ttk.Checkbutton(parent, text="输出 HTML", variable=self.html_output_var).grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(parent, text="输出 PDF", variable=self.pdf_var).grid(row=row, column=2, sticky="w")
        row += 1
        ttk.Label(parent, text="目标语言", style="Body.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            parent,
            textvariable=self.target_language_var,
            values=list(LANGUAGE_LABELS.keys()),
            state="normal",
        ).grid(row=row, column=1, sticky="ew", padx=8, pady=(8, 0))
        ttk.Label(parent, text="OpenAI 模型", style="Body.TLabel").grid(row=row, column=2, sticky="w", pady=(8, 0))
        row += 1
        ttk.Entry(parent, textvariable=self.openai_model_var).grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Entry(parent, textvariable=self.api_key_var, show="*").grid(row=row, column=2, sticky="ew", padx=(8, 0))
        row += 1
        ttk.Label(parent, text="OpenAI Base URL", style="Body.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(parent, textvariable=self.api_base_url_var).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(8, 0))
        row += 1
        ttk.Label(parent, text="接口模式", style="Body.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(parent, textvariable=self.api_mode_var, values=["auto", "responses", "chat"], state="readonly").grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(parent, text="auto 会优先 responses，再回退 chat", style="Body.TLabel").grid(row=row, column=2, sticky="w", pady=(8, 0))
        row += 1

        add_label("付费账号信息", "只有下载付费文章时才需要填写。")
        ttk.Entry(parent, textvariable=self.email_var).grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Entry(parent, textvariable=self.password_var, show="*").grid(row=row, column=2, sticky="ew", padx=(8, 0))
        row += 1

        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky="ew", pady=18)
        row += 1
        ttk.Label(parent, textvariable=self.progress_var, style="Body.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.progress_bar = ttk.Progressbar(parent, style="Horizontal.TProgressbar", mode="determinate")
        self.progress_bar.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 16))
        row += 1

        actions = ttk.Frame(parent, style="Card.TFrame")
        actions.grid(row=row, column=0, columnspan=3, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        ttk.Button(actions, text="开始执行", style="Accent.TButton", command=self.start_job).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(actions, text="打开输出目录", style="Ghost.TButton", command=self.open_output).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(actions, text="清空日志", style="Ghost.TButton", command=self.clear_log).grid(row=0, column=2, sticky="ew", padx=(8, 0))

    def _build_console(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="运行日志", style="Section.TLabel").pack(anchor="w")
        ttk.Label(parent, text="这里会显示进度、跳过的文章、翻译状态和输出路径。", style="Body.TLabel").pack(anchor="w", pady=(2, 12))
        self.log_widget = tk.Text(
            parent,
            wrap="word",
            bg="#fffdf8",
            fg="#1f2937",
            bd=0,
            relief="flat",
            font=("Menlo", 11),
            insertbackground="#1f2937",
        )
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.configure(state="disabled")

    def _pick_directory(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get() or os.getcwd())
        if selected:
            variable.set(selected)

    def _pick_translation_file(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=self.translation_source_var.get() or self.md_dir_var.get() or os.getcwd(),
            filetypes=[("Markdown 文件", "*.md")],
        )
        if selected:
            self.translation_source_var.set(selected)

    def _pick_translation_directory(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.translation_source_var.get() or self.md_dir_var.get() or os.getcwd())
        if selected:
            self.translation_source_var.set(selected)

    def clear_log(self) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def log(self, message: str) -> None:
        self.queue.put(("log", message))

    def set_progress(self, current: int, total: int) -> None:
        self.queue.put(("progress", (current, total)))

    def start_job(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Substack Studio", "当前已有任务正在运行。")
            return

        try:
            count = int(self.count_var.get().strip() or "0")
            if count < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("输入错误", "文章数量必须是大于或等于 0 的整数。")
            return

        if self.mode_var.get() == "download":
            url = self.url_var.get().strip()
            if not url:
                messagebox.showerror("缺少链接", "请输入 Substack 链接。")
                return
        else:
            source_path = self.translation_source_var.get().strip()
            if not source_path:
                messagebox.showerror("缺少文件", "请选择已经下载好的 Markdown 文件或文件夹。")
                return
            if not self.api_key_var.get().strip():
                messagebox.showerror("缺少 API Key", "翻译模式需要填写 OpenAI API Key。")
                return
        if not any([self.md_output_var.get(), self.html_output_var.get(), self.pdf_var.get()]):
            messagebox.showerror("缺少格式", "请至少选择一种输出格式。")
            return

        self.progress_var.set("正在准备...")
        self.progress_bar["value"] = 0
        self.log("开始执行任务...")

        self.worker = threading.Thread(target=self._run_job, daemon=True)
        self.worker.start()

    def _run_job(self) -> None:
        try:
            translation_config = TranslationConfig(
                enabled=True,
                api_key=self.api_key_var.get().strip(),
                target_language=normalize_target_language(self.target_language_var.get().strip() or "中文"),
                model=self.openai_model_var.get().strip() or DEFAULT_OPENAI_MODEL,
                api_base_url=self.api_base_url_var.get().strip() or "https://api.openai.com/v1",
                api_mode=self.api_mode_var.get().strip() or "auto",
            )
            if self.mode_var.get() == "translate":
                source_path = self.translation_source_var.get().strip()
                output_dir = self.translation_output_var.get().strip() or self.html_dir_var.get().strip() or BASE_HTML_DIR
                if os.path.isdir(source_path):
                    results = translate_markdown_directory(
                        source_path,
                        translation_config=translation_config,
                        html_output_dir=output_dir,
                        overwrite=self.overwrite_var.get(),
                        logger=self.log,
                        progress_callback=self.set_progress,
                        save_markdown=self.md_output_var.get(),
                        save_html=self.html_output_var.get(),
                        save_pdf=self.pdf_var.get(),
                    )
                else:
                    self.set_progress(0, 1)
                    results = [
                        translate_markdown_file(
                            source_path,
                            translation_config=translation_config,
                            html_output_dir=output_dir,
                            overwrite=self.overwrite_var.get(),
                            logger=self.log,
                            save_markdown=self.md_output_var.get(),
                            save_html=self.html_output_var.get(),
                            save_pdf=self.pdf_var.get(),
                        )
                    ]
                    self.set_progress(1, 1)
                self.last_output_dir = output_dir
                self.queue.put(("translated", results))
            else:
                export_options = ExportOptions(
                    save_markdown=self.md_output_var.get(),
                    save_html=self.html_output_var.get(),
                    save_pdf=self.pdf_var.get(),
                    overwrite_existing=self.overwrite_var.get(),
                )

                scraper = build_scraper(
                    url=self.url_var.get().strip(),
                    premium=self.premium_var.get(),
                    md_directory=self.md_dir_var.get().strip() or BASE_MD_DIR,
                    html_directory=self.html_dir_var.get().strip() or BASE_HTML_DIR,
                    logger=self.log,
                    progress_callback=self.set_progress,
                    headless=self.headless_var.get(),
                    email=self.email_var.get().strip(),
                    password=self.password_var.get().strip(),
                )

                result = scraper.scrape_posts(
                    num_posts_to_scrape=int(self.count_var.get().strip() or "0"),
                    export_options=export_options,
                )
                self.last_output_dir = scraper.html_save_dir
                self.queue.put(("done", result))
        except Exception as error:
            self.queue.put(("error", str(error)))

    def _process_queue(self) -> None:
        try:
            while True:
                event, payload = self.queue.get_nowait()
                if event == "log":
                    self.log_widget.configure(state="normal")
                    self.log_widget.insert("end", f"{payload}\n")
                    self.log_widget.see("end")
                    self.log_widget.configure(state="disabled")
                elif event == "progress":
                    current, total = payload
                    self.progress_bar["maximum"] = max(total, 1)
                    self.progress_bar["value"] = current
                    self.progress_var.set(f"已处理 {current} / {total}")
                elif event == "done":
                    result: ScrapeResult = payload
                    self.progress_var.set(f"已完成，导出 {len(result.processed_posts)} 篇文章。")
                    if result.processed_posts:
                        first = result.processed_posts[0]
                        if first.markdown_path:
                            self.log(f"Markdown 文件：{first.markdown_path}")
                        if first.html_path:
                            self.log(f"HTML 文件：{first.html_path}")
                        if first.pdf_path:
                            self.log(f"PDF 文件：{first.pdf_path}")
                    messagebox.showinfo("Substack Studio", f"已完成导出，共 {len(result.processed_posts)} 篇文章。")
                elif event == "translated":
                    results: List[TranslationResult] = payload
                    self.progress_var.set(f"已完成，翻译 {len(results)} 篇文章。")
                    if results:
                        if results[0].translated_markdown_path:
                            self.log(f"翻译 Markdown：{results[0].translated_markdown_path}")
                        if results[0].translated_html_path:
                            self.log(f"翻译 HTML：{results[0].translated_html_path}")
                        if results[0].translated_pdf_path:
                            self.log(f"翻译 PDF：{results[0].translated_pdf_path}")
                    messagebox.showinfo("Substack Studio", f"已完成翻译，共 {len(results)} 篇文章。")
                elif event == "error":
                    self.progress_var.set("执行失败")
                    self.log(f"错误：{payload}")
                    messagebox.showerror("Substack Studio", str(payload))
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

    def open_output(self) -> None:
        target = self.last_output_dir or self.html_dir_var.get().strip()
        if not target:
            return
        try:
            if os.name == "posix":
                subprocess.run(["open", target], check=False)
            else:
                os.startfile(target)
        except Exception as error:
            messagebox.showerror("Substack Studio", f"无法打开输出目录：{error}")

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> None:
    SubstackDownloaderGUI().run()


def main() -> int:
    args = parse_args()
    if args.gui:
        launch_gui()
        return 0

    if args.translate_file or args.translate_directory:
        save_markdown, save_html, save_pdf = resolve_output_formats(args.format, ["md", "pdf"])
        translation_config = TranslationConfig(
            enabled=True,
            api_key=args.openai_api_key,
            target_language=args.target_language,
            model=args.openai_model,
            api_base_url=args.openai_base_url,
            api_mode=args.openai_api_mode,
        )
        if args.translate_file:
            result = translate_markdown_file(
                args.translate_file,
                translation_config=translation_config,
                html_output_dir=args.html_directory,
                overwrite=args.overwrite,
                logger=print,
                save_markdown=save_markdown,
                save_html=save_html,
                save_pdf=save_pdf,
                progress_callback=lambda current, total: print(f"TRANSLATION_PROGRESS {current}/{total}"),
            )
            for path in [result.translated_markdown_path, result.translated_html_path, result.translated_pdf_path]:
                if path:
                    print(path)
            return 0

        results = translate_markdown_directory(
            args.translate_directory,
            translation_config=translation_config,
            html_output_dir=args.html_directory,
            overwrite=args.overwrite,
            logger=print,
            progress_callback=lambda current, total: print(f"TRANSLATION_PROGRESS {current}/{total}"),
            save_markdown=save_markdown,
            save_html=save_html,
            save_pdf=save_pdf,
        )
        for result in results:
            for path in [result.translated_markdown_path, result.translated_html_path, result.translated_pdf_path]:
                if path:
                    print(path)
        return 0

    url_was_provided = bool(args.url)
    if not url_was_provided:
        args.url = BASE_SUBSTACK_URL

    save_markdown, save_html, save_pdf = resolve_output_formats(args.format, ["md", "pdf"])
    scraper = build_scraper(
        url=args.url,
        premium=args.premium if url_was_provided else (args.premium or USE_PREMIUM),
        md_directory=args.directory,
        html_directory=args.html_directory,
        logger=lambda _message: None,
        progress_callback=lambda current, total: None,
        headless=args.headless,
        edge_path=args.edge_path,
        edge_driver_path=args.edge_driver_path,
        user_agent=args.user_agent,
        email=args.email or EMAIL,
        password=args.password or PASSWORD,
    )
    result = scraper.scrape_posts(
        num_posts_to_scrape=args.number if url_was_provided else (args.number or NUM_POSTS_TO_SCRAPE),
        export_options=ExportOptions(
            save_markdown=save_markdown,
            save_html=save_html,
            save_pdf=save_pdf,
            translate=TranslationConfig(
                enabled=args.translate,
                api_key=args.openai_api_key,
                target_language=args.target_language,
                model=args.openai_model,
                api_base_url=args.openai_base_url,
                api_mode=args.openai_api_mode,
            ),
            overwrite_existing=args.overwrite,
        ),
    )
    for post in result.processed_posts:
        for path in [post.markdown_path, post.html_path, post.pdf_path, post.translated_markdown_path, post.translated_html_path, post.translated_pdf_path]:
            if path:
                print(path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
