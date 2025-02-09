# Mises Wire EPUB Converter

A Python script to convert articles from [Mises Wire](https://mises.org/wire) into EPUB files. This script efficiently scrapes article links from Mises Wire index pages, extracts content using readability and a manual fallback, and compiles them into well-structured EPUB documents. You can create a single comprehensive EPUB or split the articles into multiple EPUB files for easier reading.

## Features

- **Comprehensive Article Scraping:**  Crawls through Mises Wire index pages (up to a specified limit) to gather links to all articles.
- **Efficient Link Discovery:** Uses concurrent requests to quickly fetch and parse index pages, identifying article links.
- **Robust Content Extraction:** Leverages the `readability-lxml` library to extract the main content of articles, ensuring clean and readable text. Includes a manual fallback extraction method for websites where readability fails.
- **Metadata Inclusion:** Extracts and includes article metadata such as author, publication date, and tags within the EPUB chapters.
- **Flexible EPUB Output:**
    - Creates a single EPUB file containing all scraped articles.
    - Option to split articles into multiple EPUB files, dividing content evenly across a specified number of files.
- **Customizable EPUB Structure:**
    - Generates a table of contents for easy navigation within the EPUB.
    - Includes an introductory chapter for the collection.
    - Sorts articles within the EPUB by date, newest first.
- **Cover Image Support:** Allows you to add a custom cover image to your EPUB for a more polished look. Automatically resizes large cover images to optimal dimensions.
- **Command-Line Interface:**  Provides a user-friendly command-line interface to control scraping, EPUB creation, splitting, and other options.
- **Error Handling and Logging:** Implements detailed logging and error handling to track the script's progress and diagnose any issues.
- **Date Parsing:** Uses `python-dateutil` for robust parsing of various date formats found on web pages.


## Requirements

- Python 3.x
- [requests](https://pypi.org/project/requests/) (`pip install requests`)
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) (`pip install beautifulsoup4`)
- [readability-lxml](https://pypi.org/project/readability-lxml/) (`pip install readability-lxml`)
- [EbookLib](https://pypi.org/project/EbookLib/) (`pip install EbookLib`)
- [python-dateutil](https://pypi.org/project/python-dateutil/) (`pip install python-dateutil`)
- [Pillow](https://pypi.org/project/Pillow/) (`pip install Pillow`)

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
   cd mises-wire-epub-converter


## Usage

   ```bash
python convert_mises_wire.py [OPTIONS]


