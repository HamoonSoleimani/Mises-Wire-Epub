# Mises Wire EPUB Generator

This Python script scrapes articles from the [Mises Wire](https://mises.org/wire) website and converts them into EPUB ebooks, with a focus on robust image handling and metadata extraction. It offers various options for customization, including multi-threading, proxy support, and image skipping.

## Features

*   **Comprehensive Article Scraping:**  Fetches articles from the Mises Wire index page, including pagination support.  Can also process a single article URL.
*   **Robust Metadata Extraction:**  Extracts article metadata (author, date, tags, summary, title, and featured image) using multiple fallback methods to ensure maximum data retrieval, even with variations in website structure.
*   **Advanced Image Handling:**
    *   Downloads and embeds images within the EPUB.
    *   Handles both regular image URLs and data URIs (Base64 encoded images).
    *   Filters out small or irrelevant images.
    *   Retries image downloads with exponential backoff.
    *   Option to skip image downloading for faster processing and smaller EPUB files.
    * **New:**  Filters out a predefined list of "noisy" or undesired images (e.g., social media share images) and images that match specific URL patterns.
*   **Readability Enhancement:** Uses the `readability-lxml` library for improved content extraction, with a fallback to manual extraction for cases where Readability fails.
*   **EPUB Creation:**  Generates well-formed EPUB files with:
    *   Table of Contents.
    *   Customizable title and cover image.
    *   Article metadata inclusion (author, date, tags, summary).
    *   Proper image embedding.
    *   Basic CSS styling.
*   **Multi-threading:** Uses a thread pool for concurrent article processing, significantly speeding up the conversion of multiple articles.
*   **Proxy Support:**  Allows specifying a proxy server for all HTTP requests.
*   **SSL Verification Control:** Option to disable SSL certificate verification (use with caution).
*   **Command-Line Interface:**  Provides a flexible command-line interface with various options.
*   **Logging:** Detailed logging with configurable levels (debug, info, warning, error) to both a file and the console.
* **New:** Dynamically rotates through a list of user-agents to reduce the chance of being blocked.
* **New:** Sanitizes titles for safe filename creation, and adds more robust URL validation.
* **New:** Handles concatenated metadata in image URLs
* **New:** Introduces a timeout to article processing with argparse
* **New:** Improved sorting of chapters by date
* **New:** Option to split the collected articles in multiple ebooks.

## Requirements

*   Python 3.7+
*   `requests`
*   `beautifulsoup4`
*   `readability-lxml`
*   `ebooklib`
*   `Pillow` (PIL)
*   `python-dateutil`
*   `tqdm`
*   `certifi`

Install the required packages using pip:

```bash
pip install requests beautifulsoup4 readability-lxml ebooklib Pillow python-dateutil tqdm certifi
```

## Options
--all: Scrape and convert all articles from Mises Wire index pages. This is the primary mode for bulk conversion.

--pages PAGES: Specify the number of index pages to check when using the --all option. Defaults to 1000.

--save_dir SAVE_DIR: Specify the directory where the generated EPUB file(s) will be saved. Defaults to mises_epubs (a folder created in the same directory as the script).

--epub_title EPUB_TITLE: Set the base title for the generated EPUB file(s). Defaults to "Mises Wire Collection".

--split SPLIT: Split the articles into a specified number of EPUB files. For example, --split 10 will create 10 EPUB files, distributing the articles evenly among them.

--cover COVER: Provide the path to an image file to use as the cover for the EPUB. Supported image formats are those supported by Pillow (PIL).

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/HamoonSoleimani/Mises-Wire-Epub
   cd Mises-Wire-Epub


## Usage

   ```bash
python convert mises-wire-to-epub.py [OPTIONS]
```

## [OPTIONS]
```bash
mises-wire-to-epub.py [-h] [--all] [--url URL] [--index INDEX] [--pages PAGES] [--save_dir SAVE_DIR] [--epub_title EPUB_TITLE] [--split SPLIT] [--cover COVER] [--threads THREADS] [--skip_images] [--log {debug,info,warning,error}] [--timeout TIMEOUT] [--proxy PROXY] [--no_ssl_verify]

Convert Mises Wire articles into EPUB files with enhanced image handling.

options:
  -h, --help            show this help message and exit
  --all                 Convert all articles.
  --url URL             URL of a specific article to convert.
  --index INDEX         Index URL to fetch articles from.
  --pages PAGES         Number of index pages to check.
  --save_dir SAVE_DIR   Directory to save the EPUB files.
  --epub_title EPUB_TITLE
                        Base title for the EPUB.
  --split SPLIT         Split into multiple EPUBs with N articles each.
  --cover COVER         Path to a cover image.
  --threads THREADS     Number of threads to use for processing.
  --skip_images         Skip downloading images (faster, smaller EPUB).
  --log {debug,info,warning,error}
                        Logging level.
  --timeout TIMEOUT     Timeout in seconds for article processing.
  --proxy PROXY         Proxy URL to use for requests (e.g. http://127.0.0.1:8080).
  --no_ssl_verify       Disable SSL certificate verification.
```

