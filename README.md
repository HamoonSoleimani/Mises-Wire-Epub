# Mises.org EPUB Generator

A Python script to download articles from selected sections of Mises.org (currently Mises Wire and Power & Market) and compile them into well-formatted EPUB e-books, complete with metadata and images.

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Key Features

*   **Multi-Section Support:** Fetch articles from `Mises Wire` and `Power & Market`. Easily extendable.
*   **Flexible Input:**
    *   Fetch recent articles from specified sections.
    *   Process a single article URL.
    *   Process a list of URLs from a text file.
*   **Robust Content Extraction:** Uses `readability-lxml` for main content extraction with a custom fallback mechanism for difficult pages.
*   **Metadata Preservation:** Extracts and includes title, author, publication date, tags, and summary in the EPUB.
*   **Image Handling:**
    *   Downloads and embeds images (including featured images).
    *   Handles `data:` URI images.
    *   Validates images and skips tiny or corrupt ones.
    *   Configurable list/patterns for ignoring problematic images (e.g., generic banners).
    *   Option to skip image processing entirely (`--skip-images`).
*   **EPUB Generation:**
    *   Creates EPUB 3 compatible files.
    *   Sorts articles by publication date (most recent first).
    *   Adds a cover image (optional).
    *   Includes an "About This Collection" page.
    *   Applies CSS for improved formatting and readability.
    *   Organizes EPUB internal structure (folders for chapters, images, styles).
    *   Option to split large collections into multiple volumes (`--split`).
*   **Filtering:** Filter articles by publication date range (`--start-date`, `--end-date`). Limit total articles processed (`--max-articles`).
*   **Network Robustness:**
    *   Automatic retries for failed network requests (articles, images).
    *   Configurable delay between requests to be polite to the server.
    *   Configurable request timeout.
    *   Proxy support.
    *   User-Agent rotation.
    *   SSL verification control.
*   **Performance:**
    *   Uses multithreading to process articles concurrently.
    *   Optional file-based caching to speed up subsequent runs.
*   **Configuration:** Controlled via command-line arguments.
*   **Logging:** Detailed logging to console and file (`mises_epub_generator.log`) with configurable levels.
*   **Graceful Shutdown:** Attempts to shut down cleanly on `Ctrl+C`.

## Prerequisites

*   Python 3.7 or higher

## Installation

1.  **Clone the repository or download the script:**
    ```bash
    # If using git
    git clone <repository_url>
    cd <repository_directory>
    # Or just download mises_epub_generator.py
    ```

2.  **Install required Python libraries:**
    ```bash
    pip install requests beautifulsoup4 readability-lxml ebooklib Pillow python-dateutil tqdm certifi urllib3
    ```
    *(It's recommended to use a virtual environment)*

## Usage

Run the script from your terminal using `python mises_epub_generator.py` followed by the desired options.

**Examples:**

1.  **Get recent articles from Mises Wire (default):**
    ```bash
    python mises_epub_generator.py
    ```
    *(This will fetch articles from the first 50 pages of Mises Wire and save as `Mises_wire_Collection.epub` in `./mises_epub`)*

2.  **Get articles from both Wire and Power & Market, increase pages:**
    ```bash
    python mises_epub_generator.py --include wire+powermarket --pages 100
    ```
    *(Saves as `Mises_powermarket_wire_Collection.epub`)*

3.  **Process a single specific article:**
    ```bash
    python mises_epub_generator.py --url "https://mises.org/power-market/public-funding-universities-inefficient-and-immoral"
    ```
    *(Saves using the article's title as the filename)*

4.  **Fetch Wire articles from a specific date range:**
    ```bash
    python mises_epub_generator.py --include wire --start-date 2023-01-01 --end-date 2023-12-31
    ```

5.  **Fetch Power & Market articles, add a cover, and split into volumes of 50:**
    ```bash
    python mises_epub_generator.py --include powermarket --cover ./my_cover.jpg --split 50 --epub-title "Power_Market_Vol"
    ```
    *(Saves as `Power_Market_Vol_Part_01.epub`, `Power_Market_Vol_Part_02.epub`, etc.)*

6.  **Process URLs from a file, skipping images, using cache:**
    ```bash
    python mises_epub_generator.py --input-file ./my_article_list.txt --skip-images --cache
    ```
    *(`my_article_list.txt` should contain one URL per line)*

7.  **Fetch all available pages from Wire (be careful, can be slow):**
    ```bash
    python mises_epub_generator.py --include wire --all-pages
    ```

8.  **See all available options:**
    ```bash
    python mises_epub_generator.py --help
    ```

## Command-Line Options


usage: mises_epub_generator.py [-h] [--include SECTIONS] [--url URL] [--input-file FILE] [--all-pages] [--pages N] [--max-articles N]
[--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] [--save-dir DIR] [--epub-title TITLE] [--split N] [--cover PATH] [--skip-images]
[--threads N] [--timeout SEC] [--delay SEC] [--retries N] [--proxy URL] [--no-ssl-verify] [--cache] [--clear-cache]
[--log {debug,info,warning,error,critical}] [--log-file FILE]

Generate EPUB collections from Mises.org articles (Wire, Power & Market).

Article Source Options:
--include SECTIONS Sections to include, separated by "+".
Available: wire, powermarket
Example: --include wire+powermarket (default: wire)
--url URL URL of a single specific article to convert.
--input-file FILE Path to a text file containing one article URL per line.
--all-pages Attempt to fetch all available pages from index (overrides --pages).
--pages N Number of index pages per section to check (default: 50). Use --all-pages for unlimited.
--max-articles N Maximum total number of articles to process.

Filtering Options:
--start-date YYYY-MM-DD
Only include articles published on or after this date.
--end-date YYYY-MM-DD
Only include articles published on or before this date.

Output Options:
--save-dir DIR Directory to save the EPUB file(s) (default: ./mises_epub).
--epub-title TITLE Custom base title for the EPUB file.
(Default: generated from included sections/date range)
--split N Split into multiple EPUBs with approx. N articles each.
--cover PATH Path to a local cover image (JPEG, PNG, GIF, WebP).
--skip-images Do not download or include any images.

Network and Performance Options:
--threads N Number of parallel threads for processing articles (default: 4).
--timeout SEC HTTP request timeout in seconds (default: 60).
--delay SEC Delay between HTTP requests in seconds (default: 0.75).
--retries N Number of retries for failed HTTP requests (default: 3).
--proxy URL Proxy URL (e.g., http://user:pass@host:port).
--no-ssl-verify Disable SSL certificate verification (use with caution!).
--cache Enable simple file caching for fetched URLs.
--clear-cache Clear the cache directory before starting.

Logging and Debugging:
--log {debug,info,warning,error,critical}
Set logging level (default: info).
--log-file FILE File to write logs to (default: mises_epub_generator.log).

## Caching

Using the `--cache` flag enables simple file-based caching in the `./.mises_cache` directory. This stores the raw HTML content and downloaded images. If you run the script again with `--cache` for the same articles/images, it will use the cached files instead of re-downloading, significantly speeding up subsequent runs or resuming after interruptions.

Use `--clear-cache` to remove the cache directory before starting a new run if you suspect cached data is stale or corrupted.

## Error Handling & Logging

*   The script attempts to handle network errors gracefully with retries.
*   Errors during article processing are logged, and the script will typically skip the problematic article and continue.
*   Detailed logs are written to `mises_epub_generator.log` (and the console). Check this file for troubleshooting. Use `--log debug` for maximum detail.

## Contributing

Contributions (bug reports, feature requests, pull requests) are welcome! Please open an issue or PR on the repository (if applicable).

## License

This project is licensed under the MIT License - see the LICENSE file (if available) or the header in this README for details.

## Disclaimer

*   This script is provided "as is", without warranty of any kind. Use it responsibly.
*   **Respect Mises.org's Terms of Service and copyright.** This tool is intended for personal, offline reading convenience. Do not abuse the site or redistribute the generated content inappropriately.
*   Web scraping scripts can break if the source website's structure changes. Future updates to Mises.org may require modifications to this script.
