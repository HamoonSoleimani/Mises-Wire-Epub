# Mises Wire EPUB Generator

## Overview

This Python script is a versatile tool for scraping, processing, and converting Mises Wire articles into EPUB e-books. It offers advanced features for web scraping, article extraction, image processing, and e-book generation.

## Features

- Scrape articles from Mises Wire and Power Market
- Extract article metadata (title, author, date, tags, summary)
- Download and process article images
- Generate high-quality EPUB e-books
- Configurable processing with multiple command-line options
- Concurrent article processing
- Caching mechanism for improved performance
- Flexible image handling

## Prerequisites

### Python Dependencies

- beautifulsoup4
- requests
- readability-lxml
- ebooklib
- Pillow
- python-dateutil
- tqdm
- certifi

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install beautifulsoup4 requests readability-lxml ebooklib Pillow python-dateutil tqdm certifi
   ```

## Usage

### Basic Usage

```bash
python mises_epub_generator.py --all
```

This will scrape and convert all available articles from Mises Wire.

### Advanced Options

```bash
python mises_epub_generator.py [OPTIONS]
```

#### Options

- `--all`: Convert all articles
- `--url URL`: Convert a specific article
- `--index URL`: Custom index URL (default: https://mises.org/wire)
- `--pages N`: Number of index pages to check
- `--save_dir DIR`: Directory to save EPUB files
- `--epub_title TITLE`: Base title for the EPUB
- `--split N`: Split into multiple EPUBs with N articles each
- `--cover PATH`: Path to a cover image
- `--threads N`: Number of threads for processing
- `--skip_images`: Skip downloading images
- `--log LEVEL`: Logging level (debug, info, warning, error)
- `--timeout SECONDS`: Request timeout
- `--proxy URL`: Proxy for requests
- `--no_ssl_verify`: Disable SSL verification
- `--cache DIR`: Enable HTML caching
- `--include SOURCE`: Include additional sources

### Examples

1. Convert all Mises Wire articles:
   ```bash
   python mises_epub_generator.py --all
   ```

2. Convert a specific article:
   ```bash
   python mises_epub_generator.py --url https://mises.org/wire/example-article
   ```

3. Split articles into multiple EPUBs with 50 articles per file:
   ```bash
   python mises_epub_generator.py --all --split 50
   ```

4. Include Power Market articles:
   ```bash
   python mises_epub_generator.py --all --include powermarket
   ```

## Logging

The script generates detailed logs in `mises_epub_generator.log`, which can help diagnose issues during scraping and processing.

## Caching

Use the `--cache` option to enable HTML caching, which can significantly speed up repeated runs by storing previously downloaded HTML content.

## Image Handling

- Images are processed and embedded in the EPUB
- Small images are automatically skipped
- Featured images are given special treatment
- Data URIs and regular image URLs are supported

## Troubleshooting

- Ensure stable internet connection
- Check proxy settings if experiencing network issues
- Verify SSL certificate configuration
- Adjust timeout and thread settings for performance

## Legal and Ethical Considerations

- Respect the Mises Institute's terms of service
- Use this script responsibly and for personal, non-commercial purposes
- Do not distribute copyrighted content

## Contributing

Contributions, issues, and feature requests are welcome. Please open an issue or submit a pull request.
