# Mises Wire EPUB Converter

A versatile Python script that converts articles from [Mises Wire](https://mises.org/wire) into a single, well-indexed EPUB file. The script crawls through the paginated index pages (up to 1000 by default), extracts article content, and compiles all the articles into one combined EPUB file with proper chapter titles and a table of contents.

## Features

- **Bulk Processing:** Scans up to 1000 index pages to collect all article links.
- **Article Extraction:** Uses the `readability-lxml` library for content extraction with a robust manual fallback.
- **Single EPUB Output:** Combines all processed articles into one EPUB file, with each article as a separate chapter.
- **Clean Indexing:** Automatically generates a table of contents for easy navigation within the EPUB.
- **Customizable Settings:** Command-line options allow you to specify the number of pages to process, output directory, and EPUB title.

## Requirements

- Python 3.x
- [requests](https://pypi.org/project/requests/)
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/)
- [readability-lxml](https://pypi.org/project/readability-lxml/)
- [EbookLib](https://pypi.org/project/EbookLib/)


## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/mises-wire-epub-converter.git
   cd mises-wire-epub-converter

2. **Install the required packages:**

   ```bash
   pip install -r requirements.txt

## Usage

   ```bash
   python convert_mises_wire.py --all

## Example
python convert_mises_wire.py --all --pages 1000 --save_dir ./output --epub_title "My Mises Wire Collection"
