# Substack2Markdown

Substack2Markdown now contains two desktop clients and a shared Python backend:

- A Python/Tkinter client for quick local usage
- A native SwiftUI macOS client that acts as a frontend for the Python backend

The backend can download free or premium Substack posts and export them as Markdown, HTML, and PDF. It can also translate already-downloaded Markdown articles with the OpenAI API and generate translated HTML/PDF outputs.

🆕 @Firevvork has built a web version of this tool at [Substack Reader](https://www.substacktools.com/reader) - no 
installation required! (Works for free Substacks only.)


![Substack2Markdown Interface](./assets/images/screenshot.png)

Once you run the tool, it creates a folder named after the Substack under the chosen output directories and saves the requested article formats. The current app can export only the file types you select.

## Features

- Converts Substack posts into Markdown files.
- Generates HTML files and an HTML index for browsing.
- Exports articles to PDF.
- Supports direct post URLs as well as full Substack home pages.
- Adds optional OpenAI-powered translation for already-downloaded Markdown articles, including new HTML and PDF outputs.
- Includes a desktop GUI for running the workflow without terminal commands.
- Includes a native SwiftUI macOS app with Chinese UI, saved settings, bundled icon, progress display, and log output.
- Supports free and premium content (with subscription).

## Installation

Clone the repo and install the dependencies:

```bash
git clone https://github.com/timf34/Substack2Markdown.git
cd Substack2Markdown

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

For premium scraping, update `config.py` or provide credentials at runtime:

```python
EMAIL = "your-email@domain.com"
PASSWORD = "your-password"
```

You'll also need Microsoft Edge installed for Selenium-based premium scraping.

For OpenAI translation, set an API key in your shell or enter it in the GUI:

```bash
export OPENAI_API_KEY="your_api_key"
```

## Usage

### Desktop GUI

Launch the desktop app:

```bash
python3 substack_gui.py
```

The GUI supports:

- Free and premium scraping
- Full-site or single-article export
- Markdown, HTML, and PDF generation
- Translation of downloaded Markdown files into new translated Markdown/HTML/PDF files
- Output directory selection and run logs

### SwiftUI macOS Client

The native macOS client lives under:

```bash
Package.swift
Sources/SubstackStudioApp/
```

Its UI is fully in Chinese and it delegates work to the existing Python backend:

```bash
.venv/bin/python3 substack_scraper.py
```

Recommended local workflow:

1. Install or keep a working Python virtual environment in this repo.
2. Open the folder in Xcode.
3. Let Xcode resolve the Swift Package.
4. Run the `SubstackStudio` app target.

### CLI

Free Substack site or direct article URL:

```bash
python3 substack_scraper.py --url https://example.substack.com --directory /path/to/save/posts
```

Single article with PDF export:

```bash
python3 substack_scraper.py \
  --url https://example.substack.com/p/some-post \
  --directory ./substack_md_files \
  --html-directory ./substack_html_pages \
  --pdf
```

Premium Substack site:

```bash
python3 substack_scraper.py \
  --url https://example.substack.com \
  --directory ./substack_md_files \
  --html-directory ./substack_html_pages \
  --premium \
  --email your-email@domain.com \
  --password 'your-password'
```

Translate an already-downloaded Markdown article to Chinese and generate a new PDF:

```bash
python3 substack_scraper.py \
  --translate-file ./downloads_md/citriniresearch/2028gic.md \
  --target-language Chinese \
  --html-directory ./translated_output \
  --openai-api-key "$OPENAI_API_KEY"
```

Translate every downloaded Markdown file in a folder:

```bash
python3 substack_scraper.py \
  --translate-directory ./downloads_md/citriniresearch \
  --target-language Chinese \
  --html-directory ./translated_output \
  --openai-api-key "$OPENAI_API_KEY"
```

Scrape a specific number of posts:

```bash
python3 substack_scraper.py --url https://example.substack.com --number 5
```

### Online Version

For a hassle-free experience without any local setup:

1. Visit [Substack Reader](https://www.substacktools.com/reader)
2. Enter the Substack URL you want to read or export
3. Click "Go" to instantly view the content or "Export" to download Markdown files

This online version provides a user-friendly web interface for reading and exporting free Substack articles, with no installation required. However, please note that the online version currently does not support exporting premium content. For full functionality, including premium content export, please use the local script as described above. Built by @Firevvork. 

## Notes

- `substack_scraper.py` remains the main CLI entry point.
- `substack_gui.py` launches the desktop interface.
- The SwiftUI app stores output directories, API key, base URL, model, API mode, and target language in local user defaults.
- Translation runs against existing `.md` article files and requires a valid OpenAI-compatible API key.
- Translation supports custom OpenAI-compatible base URLs and can switch between `Responses` and `Chat Completions`.
- Premium scraping still depends on a valid Substack subscription and successful browser login.

## Build macOS Apps

### Python/Tkinter app

Install PyInstaller into the virtual environment, then run:

```bash
./build_macos_app.sh
```

The generated app bundle will be written to:

```bash
dist/Substack Studio.app
```

### SwiftUI app

Use the packaging script below. It builds the SwiftUI app, generates the app icon, bundles the Python backend, and signs the final `.app`:

```bash
./package_swiftui_app.sh
```

The generated app bundle will be written to:

```bash
dist/Substack Studio SwiftUI.app
```
