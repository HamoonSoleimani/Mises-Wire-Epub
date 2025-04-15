#!/usr/bin/env python3
import os
import re
import sys
import logging
import argparse
import requests
import threading
import concurrent.futures
import hashlib
import time
import base64
import certifi
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin, urlparse
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
from readability import Document
from ebooklib import epub
from PIL import Image
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QSpinBox, QPushButton, QFileDialog, QComboBox, 
                           QCheckBox, QProgressBar, QTabWidget, QTextEdit, QGroupBox, 
                           QFormLayout, QRadioButton, QButtonGroup, QMessageBox, QSplitter,
                           QScrollArea, QStyle, QListWidget, QListWidgetItem, QFrame)
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, pyqtSlot, QSize, QUrl, QSettings, 
                         QCoreApplication, QTimer, QMutex)
from PyQt5.QtGui import QIcon, QPixmap, QColor, QFont, QDesktopServices, QTextCursor

# Global configuration - will be updated via UI
PROXIES = {}
VERIFY = certifi.where()
TIMEOUT = 30
CACHE_DIR = None

# Define URLs to ignore (these images will be skipped)
IGNORED_IMAGE_URLS = {
    "https://cdn.mises.org/styles/social_media/s3/images/2025-03/25_Loot%26Lobby_QUOTE_4K_20250311.jpg?itok=IkGXwPjO",
    "https://mises.org/mises-wire/images/featured_image.jpeg",
    "https://mises.org/podcasts/radio-rothbard/images/featured_image.jpeg",
    "https://mises.org/podcasts/loot-and-lobby/images/featured_image.jpeg",
    "https://mises.org/friday-philosophy/images/featured_image.jpeg",
    "https://mises.org/articles-interest/images/featured_image.jpeg",
    "https://mises.org/articles-interest/images/featured_image.webp",
    "https://mises.org/podcasts/human-action-podcast/images/featured_image.jpeg",
}

# Patterns to identify problematic URLs
IGNORED_URL_PATTERNS = [
    r'featured_image\.(jpeg|jpg|png|webp)$',
    r'/podcasts/.*/images/',
    r'/mises\.org$'  # For the invalid base domain URL
]

# User-Agent header for HTTP requests with rotation capability
USER_AGENTS = [
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) '
     'Chrome/91.0.4472.124 Safari/537.36'),
    ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
     'AppleWebKit/605.1.15 (KHTML, like Gecko) '
     'Version/15.0 Safari/605.1.15'),
    ('Mozilla/5.0 (X11; Linux x86_64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) '
     'Chrome/92.0.4515.107 Safari/537.36')
]

# --- Utility Functions ---
def get_headers():
    """Returns headers with a randomly selected User-Agent."""
    return {
        'User-Agent': USER_AGENTS[int(time.time()) % len(USER_AGENTS)],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0'
    }

def get_session():
    """Creates a requests session with custom headers, proxies and SSL settings."""
    s = requests.Session()
    s.headers.update(get_headers())
    s.proxies = PROXIES
    return s

def cached_get(url):
    """
    Retrieves the content of a URL using caching if CACHE_DIR is set.
    Cached files are stored as MD5 hashes of the URL in the cache directory.
    """
    if CACHE_DIR:
        cache_file = os.path.join(CACHE_DIR, "cache_" + hashlib.md5(url.encode()).hexdigest() + ".html")
        if os.path.exists(cache_file):
            logging.info(f"Loading cached URL: {url}")
            with open(cache_file, "r", encoding="utf-8") as f:
                return f.read()
        else:
            with get_session() as session:
                response = session.get(url, timeout=TIMEOUT, verify=VERIFY)
                response.raise_for_status()
                text = response.text
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(text)
            return text
    else:
        with get_session() as session:
            response = session.get(url, timeout=TIMEOUT, verify=VERIFY)
            response.raise_for_status()
            return response.text

def sanitize_filename(title):
    """Creates a safe filename from the given title."""
    if not title:
        return "untitled"
    filename = title.replace(" ", "_")
    filename = re.sub(r'[^\w\s.-]', '', filename)
    filename = filename.strip('_').strip()
    return filename[:200]

def is_valid_url(url):
    """Checks if the given string is a valid URL."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def parse_date(date_str):
    """Parses a date string into a datetime object. Returns datetime.min on failure."""
    if not date_str:
        return datetime.min
    try:
        return date_parser.parse(date_str)
    except Exception:
        return datetime.min

def clean_image_url(url):
    """Clean the image URL if it contains concatenated metadata."""
    if not url:
        return url
    if "' + og_image:" in url:
        url = url.split("' + og_image:")[0]
    return url.strip()

def should_ignore_image_url(url):
    """Check if an image URL should be ignored based on explicit list or patterns."""
    if not url:
        return True
    
    url = clean_image_url(url)
    
    # Check against explicit list
    if url in IGNORED_IMAGE_URLS:
        return True
    
    # Check against patterns
    for pattern in IGNORED_URL_PATTERNS:
        if re.search(pattern, url):
            return True
    
    return False

# --- Core Article Fetching and Processing Functions ---
def get_article_links(index_url, max_pages=1000, progress_callback=None):
    """
    Fetch article URLs from the given index site and paginated pages.
    Returns a list of unique article URLs.
    """
    all_article_links = set()

    def fetch_page_links(page_num):
        page_url = f"{index_url}?page={page_num}" if page_num > 1 else index_url
        logging.debug(f"Fetching index page: {page_url}")
        try:
            page_content = cached_get(page_url)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch index page {page_url}: {e}")
            return set(), False

        soup = BeautifulSoup(page_content, 'html.parser')
        page_links = set()

        # Try to find articles with modern class structure
        articles = soup.find_all('article')
        if articles:
            for art in articles:
                a_tag = art.find('a', href=True)
                if a_tag:
                    href = a_tag['href']
                    if 'rss.xml' in href:
                        continue
                    absolute_url = urljoin(index_url, href)
                    page_links.add(absolute_url)
        else:
            # Fallback to finding links containing '/wire/'
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/wire/' in href and 'rss.xml' not in href:
                    absolute_url = urljoin(index_url, href)
                    page_links.add(absolute_url)

        if not page_links:
            logging.info(f"No articles found on page {page_num}, might have reached the end.")
            return set(), True

        return page_links, False

    page_num = 1
    end_reached = False

    while page_num <= max_pages and not end_reached:
        links, end_reached = fetch_page_links(page_num)
        all_article_links.update(links)
        
        if progress_callback:
            progress_callback(page_num, max_pages, len(all_article_links))
            
        page_num += 1
        time.sleep(0.5)
        if page_num % 10 == 0:
            logging.info(f"Found {len(all_article_links)} unique article links so far...")

    logging.info(f"Total unique article links found: {len(all_article_links)}")
    return list(all_article_links)

def get_article_metadata(soup, url):
    """
    Extracts metadata (author, date, tags, summary) from an article's soup object.
    Uses multiple fallback methods to ensure maximal data extraction.
    """
    metadata = {
        'author': "Mises Wire",  # Default author
        'date': '',
        'tags': [],
        'summary': "",
        'title': "",
        'featured_image': None
    }

    try:
        # Extract title
        title_element = (
            soup.find('meta', property='og:title') or
            soup.find('h1', class_='page-header__title') or
            soup.find('h1', class_='entry-title') or
            soup.find('h1', itemprop='headline')
        )
        if title_element:
            metadata['title'] = title_element.get('content', title_element.get_text(strip=True)).strip()

        # Extract author with multiple fallback methods
        author_element = (
            soup.find('meta', property='author') or
            soup.find('meta', attrs={'name': 'author'}) or
            soup.find('a', rel='author')
        )
        if author_element:
            metadata['author'] = author_element.get('content', author_element.get_text(strip=True)).strip()
        else:
            details = soup.find('div', {"data-component-id": "mises:element-article-details"})
            if details:
                links = details.find_all('a', href=True)
                for link in links:
                    if "profile" in link['href']:
                        metadata['author'] = link.get_text(strip=True)
                        break
            else:
                byline = soup.find('p', class_='byline') or soup.find('span', class_='author')
                if byline:
                    metadata['author'] = byline.get_text(strip=True).replace('By ', '').strip()

        # Extract date with multiple fallback methods
        date_element = (
            soup.find('meta', property='article:published_time') or
            soup.find('meta', property='og:article:published_time') or
            soup.find('time', datetime=True) or
            soup.find('span', class_='date')
        )
        if date_element:
            metadata['date'] = date_element.get('content', date_element.get('datetime', date_element.get_text(strip=True))).strip()

        # Extract tags
        tag_elements = soup.find_all('meta', property='article:tag') or soup.find_all('a', rel='tag')
        if tag_elements:
            metadata['tags'] = [tag.get('content', tag.get_text(strip=True)).strip() for tag in tag_elements]

        if not metadata['tags']:
            tag_container = soup.find('div', class_='tags') or soup.find('ul', class_='post-tags')
            if tag_container:
                tag_links = tag_container.find_all('a')
                metadata['tags'] = [tag.get_text(strip=True) for tag in tag_links]

        # Extract summary
        summary_element = (
            soup.find('meta', property='og:description') or
            soup.find('meta', attrs={'name': 'description'})
        )
        if summary_element:
            metadata['summary'] = summary_element.get('content', '').strip()
        else:
            first_para = None
            content_div = soup.find('div', class_='post-entry') or soup.find('div', class_='entry-content')
            if content_div:
                first_para = content_div.find('p')
            if first_para:
                metadata['summary'] = first_para.get_text(strip=True).strip()

        # Extract featured image
        featured_img = (
            soup.find('meta', property='og:image') or
            (soup.find('figure', class_='post-thumbnail') and soup.find('figure', class_='post-thumbnail').find('img')) or
            (soup.find('div', class_='featured-image') and soup.find('div', class_='featured-image').find('img'))
        )
        if featured_img:
            img_url = featured_img.get('content', featured_img.get('src', ''))
            img_url = clean_image_url(img_url)
            if not should_ignore_image_url(img_url) and img_url:
                metadata['featured_image'] = urljoin(url, img_url)
    except Exception as e:
        logging.error(f"Error extracting metadata from {url}: {e}", exc_info=True)

    return metadata

def manual_extraction_fallback(soup, url):
    """
    A fallback extraction method if readability fails.
    Attempts to extract content directly from common article container elements.
    """
    logging.debug(f"Attempting manual extraction fallback for {url}")
    try:
        title_element = (
            soup.find('h1', class_='page-header__title') or
            soup.find('h1', class_='entry-title') or
            soup.find('h1', itemprop='headline') or
            soup.find('meta', property='og:title')
        )
        title = title_element.get_text(strip=True) if title_element and hasattr(title_element, 'get_text') else title_element.get('content') if title_element else "Untitled Article"
        content_element = (
            soup.find('div', class_='post-entry') or
            soup.find('div', class_='entry-content') or
            soup.find('article') or
            soup.find('div', {'id': 'content'}) or
            soup.find('div', class_='content')
        )

        if content_element:
            for unwanted in content_element.select('.social-share, .author-box, .related-posts, .comments, script, style'):
                if unwanted:
                    unwanted.decompose()
            elements = content_element.find_all(['p', 'h2', 'h3', 'h4', 'blockquote', 'ul', 'ol', 'figure'])
            content = "\n\n".join(str(el) for el in elements) if elements else str(content_element)
        else:
            logging.warning(f"Manual extraction: Content container not found for {url}; using entire body.")
            content = str(soup.body) if soup.body else ""
        cleaned_html_fallback = f"<h1>{title}</h1><article>{content}</article>"
        return title, cleaned_html_fallback
    except Exception as e:
        logging.error(f"Manual extraction fallback failed for {url}: {e}", exc_info=True)
        return "Extraction Failed", "<article>Content extraction failed</article>"

def download_image(image_url, retry_count=3):
    """
    Downloads an image from a URL and returns it as a bytes object.
    Includes retry logic and error handling.
    """
    image_url = clean_image_url(image_url)
    
    if not image_url or not is_valid_url(image_url):
        logging.debug(f"Invalid or missing image URL: {image_url}")
        return None
        
    if should_ignore_image_url(image_url):
        logging.debug(f"Skipping ignored image URL: {image_url}")
        return None

    for attempt in range(retry_count):
        try:
            logging.debug(f"Downloading image from: {image_url} (attempt {attempt+1})")
            with get_session() as session:
                response = session.get(image_url, stream=True, timeout=TIMEOUT, verify=VERIFY)
                response.raise_for_status()
            return BytesIO(response.content)
        except requests.exceptions.SSLError as e:
            logging.warning(f"SSL Error downloading image from {image_url} (attempt {attempt+1}): {e}")
            if attempt < retry_count - 1:
                time.sleep(2 ** attempt)
            else:
                logging.error(f"Failed all {retry_count} attempts (SSL error) to download image from {image_url}")
                return None
        except requests.exceptions.RequestException as e:
            logging.warning(f"Failed to download image from {image_url} (attempt {attempt+1}): {e}")
            if attempt < retry_count - 1:
                time.sleep(2 ** attempt)
                continue
            else:
                logging.error(f"Failed all {retry_count} attempts to download image from {image_url}")
                return None

def is_small_image(img):
    """Checks if an image is too small to be worth including"""
    width, height = img.size
    return width < 50 or height < 50

def process_image(img_url, url):
    """Processes an image URL and returns the image data and info if valid"""
    img_url = clean_image_url(img_url)
    
    if not img_url or should_ignore_image_url(img_url):
        return None, None, None
        
    img_data = download_image(img_url)
    if not img_data:
        return None, None, None
        
    try:
        img = Image.open(img_data)
        
        # Skip small images
        if is_small_image(img):
            logging.debug(f"Skipping small image ({img.size[0]}x{img.size[1]}): {img_url}")
            return None, None, None
            
        img_format = img.format.lower()
        if img_format not in ['jpeg', 'png', 'gif', 'webp']:
            logging.warning(f"Unsupported image format: {img_format}. Skipping.")
            return None, None, None
            
        hash_object = hashlib.md5(img_url.encode())
        img_file_name = f'image_{hash_object.hexdigest()[:8]}.{img_format}'
        img_data.seek(0)
        return img_data, img_format, img_file_name
    except Exception as e:
        logging.error(f"Error processing image {img_url} in {url}: {e}")
        return None, None, None

def process_article(url, download_images=True, status_callback=None):
    """
    Downloads, parses, extracts content, and processes images from an article.
    Handles both regular images and data URIs.
    Uses caching if CACHE_DIR is set.
    """
    if status_callback:
        status_callback(f"Processing: {url}")
        
    logging.debug(f"Processing URL: {url}")
    image_items = []
    image_filenames = set()  # Track processed image filenames to avoid duplicates

    try:
        html_content = cached_get(url)
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to fetch {url}: {e}"
        logging.error(error_msg)
        if status_callback:
            status_callback(error_msg)
        return None, None, None, []

    soup = BeautifulSoup(html_content, 'html.parser')
    metadata = get_article_metadata(soup, url)

    try:
        doc = Document(html_content)
        title = doc.short_title() or metadata.get('title', "Untitled")
        cleaned_html = doc.summary()
        if not cleaned_html or len(cleaned_html) < 200:
            raise ValueError("Readability returned insufficient content")
    except Exception as e:
        logging.warning(f"Readability extraction failed for {url}: {e}")
        title, cleaned_html = manual_extraction_fallback(soup, url)

    if not title or not cleaned_html:
        error_msg = f"Skipping article due to extraction failure: {url}"
        logging.warning(error_msg)
        if status_callback:
            status_callback(error_msg)
        return None, None, None, []

    if status_callback:
        status_callback(f"Extracted: {title}")

    # Process featured image if available
    featured_image_processed = False
    if download_images and metadata.get('featured_image'):
        featured_img_url = metadata['featured_image']
        img_data, img_format, img_file_name = process_image(featured_img_url, url)
        
        if img_data and img_format and img_file_name:
            img_file_name = 'featured_' + img_file_name  # Ensure unique naming for featured images
            epub_image = epub.EpubImage()
            epub_image.file_name = 'images/' + img_file_name
            epub_image.media_type = f'image/{img_format}'
            epub_image.content = img_data.getvalue()
            image_items.append(epub_image)
            image_filenames.add(img_file_name)
            
            featured_image_html = f'<figure class="featured-image"><img src="images/{img_file_name}" alt="{title}" /></figure>'
            cleaned_html = featured_image_html + cleaned_html
            featured_image_processed = True

    cleaned_soup = BeautifulSoup(cleaned_html, 'html.parser')

    if download_images:
        img_count = len(cleaned_soup.find_all('img', src=True))
        if status_callback and img_count > 0:
            status_callback(f"Processing {img_count} images...")
            
        for i, img_tag in enumerate(cleaned_soup.find_all('img', src=True)):
            img_url = img_tag['src']
            
            # Skip already processed images (based on src)
            if img_url.startswith('images/'):
                continue
                
            if not img_url.startswith('data:'):
                img_url = urljoin(url, img_url)
                
            # Process data URIs
            if img_url.startswith('data:'):
                try:
                    header, encoded = img_url.split(",", 1)
                    img_format = header.split(';')[0].split('/')[1].lower()
                    if img_format not in ['jpeg', 'png', 'gif', 'webp']:
                        logging.warning(f"Unsupported image format in data URI ({img_format}). Skipping.")
                        continue
                    img_data = BytesIO(base64.b64decode(encoded))
                    hash_object = hashlib.md5(encoded.encode())
                    img_file_name = f'image_{hash_object.hexdigest()[:8]}.{img_format}'
                    
                    # Skip if this image has already been processed
                    if img_file_name in image_filenames:
                        img_tag['src'] = 'images/' + img_file_name
                        continue
                        
                    epub_image = epub.EpubImage()
                    epub_image.file_name = 'images/' + img_file_name
                    epub_image.media_type = f'image/{img_format}'
                    epub_image.content = img_data.getvalue()
                    image_items.append(epub_image)
                    image_filenames.add(img_file_name)
                    img_tag['src'] = 'images/' + img_file_name
                except Exception as e:
                    logging.error(f"Error processing data URI in {url}: {e}")
                    continue
            else:
                # Regular image URL
                img_data, img_format, img_file_name = process_image(img_url, url)
                if img_data and img_format and img_file_name:
                    # Skip if this image has already been processed
                    if img_file_name in image_filenames:
                        img_tag['src'] = 'images/' + img_file_name
                        continue
                        
                    epub_image = epub.EpubImage()
                    epub_image.file_name = 'images/' + img_file_name
                    epub_image.media_type = f'image/{img_format}'
                    epub_image.content = img_data.getvalue()
                    image_items.append(epub_image)
                    image_filenames.add(img_file_name)
                    img_tag['src'] = 'images/' + img_file_name
            
            # Clean up unnecessary image attributes
            for attr in ['data-src', 'data-srcset', 'srcset', 'loading', 'sizes']:
                if attr in img_tag.attrs:
                    del img_tag.attrs[attr]
                    
            if status_callback and i % 3 == 0:  # Update status every few images
                status_callback(f"Image {i+1}/{img_count} processed")

    header_html = f"<h1>{title}</h1>"
    if metadata.get('author'):
        header_html += f"<p class='author'>By {metadata['author']}</p>"
    if metadata.get('date'):
        formatted_date = metadata['date']
        try:
            parsed_date = parse_date(metadata['date'])
            if parsed_date != datetime.min:
                formatted_date = parsed_date.strftime("%B %d, %Y")
        except:
            pass
        header_html += f"<p class='date'>Date: {formatted_date}</p>"
    if metadata.get('summary'):
        header_html += f"<p class='summary'><em>{metadata['summary']}</em></p>"
    if metadata.get('tags') and metadata['tags']:
        header_html += f"<p class='tags'>Tags: {', '.join(metadata['tags'])}</p>"

    footer_html = f"<hr/><p class='source'>Source URL: <a href='{url}'>{url}</a></p>"
    final_html = header_html + str(cleaned_soup) + footer_html

    chapter_filename = sanitize_filename(title) + '.xhtml'
    chapter = epub.EpubHtml(title=title, file_name=chapter_filename, lang='en')
    chapter.content = final_html.encode('utf-8')
    chapter.id = sanitize_filename(title).replace(".", "_")
    
    if status_callback:
        status_callback(f"Completed: {title}")
        
    return title, chapter, metadata, image_items

def create_epub(chapters, save_dir, epub_title, cover_path=None, author="Mises Wire", language='en', status_callback=None):
    """
    Create an EPUB file from a list of chapters, including images.
    """
    if not chapters:
        error_msg = "No chapters provided to create_epub"
        logging.error(error_msg)
        if status_callback:
            status_callback(error_msg)
        return None

    if status_callback:
        status_callback(f"Creating EPUB: {epub_title} with {len(chapters)} chapters")

    book = epub.EpubBook()
    book.set_title(epub_title)
    book.add_author(author)
    book.set_language(language)

    book_id = sanitize_filename(epub_title).lower().replace(" ", "_")
    book.set_identifier(f"mises-{book_id}-{datetime.now().strftime('%Y%m%d')}")
    book.add_metadata('DC', 'description', 'Collection of articles from Mises Wire')
    book.add_metadata('DC', 'publisher', 'Mises Institute')
    book.add_metadata('DC', 'date', datetime.now().strftime('%Y-%m-%d'))

    if cover_path and os.path.exists(cover_path):
        try:
            with open(cover_path, 'rb') as f:
                cover_content = f.read()
            img = Image.open(BytesIO(cover_content))
            if img.width > 1600 or img.height > 2400:
                if status_callback:
                    status_callback("Resizing cover image...")
                logging.info("Cover image is large, resizing to more optimal dimensions")
                img.thumbnail((1600, 2400))
                img_buffer = BytesIO()
                img.save(img_buffer, format=img.format)
                cover_content = img_buffer.getvalue()
            ext = os.path.splitext(cover_path)[1].lower()
            if not ext:
                ext = '.jpg'
            cover_file_name = f'images/cover{ext}'
            book.set_cover(cover_file_name, cover_content)
            logging.info(f"Added cover image: {cover_path}")
        except Exception as e:
            logging.error(f"Error adding cover image: {e}")

    intro_title = "About This Collection"
    intro_content = f"""
    <h1>{epub_title}</h1>
    <p>This is a collection of articles from Mises Wire, the Mises Institute's publication featuring contemporary news, opinion, and analysis.</p>
    <p>Contains {len(chapters)} articles.</p>
    <p>Generated on {datetime.now().strftime('%B %d, %Y')}</p>
    """
    intro_chapter = epub.EpubHtml(title=intro_title, file_name='intro.xhtml', lang=language)
    intro_chapter.content = intro_content
    book.add_item(intro_chapter)

    try:
        if status_callback:
            status_callback("Sorting chapters by date...")
        chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)
    except Exception as e:
        logging.warning(f"Failed to sort chapters by date: {e}")

    toc = [epub.Link('intro.xhtml', intro_title, 'intro')]
    spine = ['nav', intro_chapter]
    
    # Use a set to track processed image file paths to avoid duplicates
    image_filenames = set()
    all_image_items = []

    if status_callback:
        status_callback("Adding chapters to EPUB...")
        
    for i, (title, chapter, metadata, image_items) in enumerate(chapters):
        book.add_item(chapter)
        toc.append(epub.Link(chapter.file_name, title, chapter.id))
        spine.append(chapter)
        
        # Only add unique images
        for image_item in image_items:
            if image_item.file_name not in image_filenames:
                all_image_items.append(image_item)
                image_filenames.add(image_item.file_name)
                
        if status_callback and i % 10 == 0:
            status_callback(f"Added {i+1}/{len(chapters)} chapters...")

    if status_callback:
        status_callback(f"Adding {len(all_image_items)} images to EPUB...")
        
    # Add all unique images to the book
    for i, image_item in enumerate(all_image_items):
        book.add_item(image_item)
        if status_callback and i % 20 == 0:
            status_callback(f"Added {i+1}/{len(all_image_items)} images...")

    book.toc = tuple(toc)
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    css_content = """
    body {
        font-family: "Georgia", serif;
        line-height: 1.5;
        margin: 2%;
        padding: 0;
    }
    h1 {
        font-size: 1.5em;
        margin: 1em 0 0.5em;
    }
    h2 {
        font-size: 1.3em;
        margin: 1em 0 0.5em;
    }
    p {
        margin: 0.5em 0;
    }
    .author, .date, .tags, .summary {
        font-size: 0.9em;
        margin: 0.3em 0;
    }
    .summary {
        font-style: italic;
        margin-bottom: 1em;
    }
    img {
        max-width: 100%;
        height: auto;
    }
    blockquote {
        margin: 1em 2em;
        padding-left: 1em;
        border-left: 4px solid #ccc;
        font-style: italic;
    }
    .source {
        font-size: 0.8em;
        color: #666;
        margin-top: 2em;
    }
    .featured-image {
        margin: 1em 0;
        text-align: center;
    }
    """
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=css_content
    )
    book.add_item(nav_css)

    safe_title = sanitize_filename(epub_title)
    os.makedirs(save_dir, exist_ok=True)
    filename = os.path.join(save_dir, safe_title + '.epub')

    try:
        if status_callback:
            status_callback(f"Writing EPUB file to {filename}...")
        epub.write_epub(filename, book, {})
        logging.info(f"Saved EPUB: {filename}")
        if status_callback:
            status_callback(f"✅ EPUB successfully created: {filename}")
        return filename
    except Exception as e:
        error_msg = f"Failed to write EPUB: {e}"
        logging.error(error_msg, exc_info=True)
        if status_callback:
            status_callback(f"❌ {error_msg}")
        return None

# --- Worker Threads for GUI ---
class ArticleFetchWorker(QThread):
    """Worker thread to fetch articles in the background"""
    finished = pyqtSignal(list)
    progress = pyqtSignal(int, int, int)  # page, max_pages, num_articles
    status = pyqtSignal(str)
    
    def __init__(self, url, max_pages):
        super().__init__()
        self.url = url
        self.max_pages = max_pages
        
    def run(self):
        self.status.emit(f"Fetching articles from {self.url}...")
        links = get_article_links(
            self.url, 
            self.max_pages,
            progress_callback=lambda page, max_pages, num_articles: self.progress.emit(page, max_pages, num_articles)
        )
        self.finished.emit(links)

class ArticleProcessWorker(QThread):
    """Worker thread to process articles in the background"""
    progress = pyqtSignal(int, int)  # current, total
    article_processed = pyqtSignal(tuple)  # (title, chapter, metadata, image_items)
    article_failed = pyqtSignal(str)  # url
    status = pyqtSignal(str)
    finished = pyqtSignal(list)  # processed chapters
    
    def __init__(self, urls, download_images, num_threads):
        super().__init__()
        self.urls = urls
        self.download_images = download_images
        self.num_threads = min(num_threads, len(urls))
        self.processed_chapters = []
        self.mutex = QMutex()
        
    def process_article_wrapper(self, url):
        """Wrapper to handle thread-safe updating of status"""
        result = process_article(
            url, 
            self.download_images,
            status_callback=lambda status: self.status.emit(status)
        )
        title, chapter, metadata, image_items = result
        
        if title and chapter:
            # Thread-safe update of processed chapters
            self.mutex.lock()
            self.processed_chapters.append((title, chapter, metadata, image_items))
            self.mutex.unlock()
            
            # Signal that an article was processed
            self.article_processed.emit((title, chapter, metadata, image_items))
        else:
            self.article_failed.emit(url)
            
        return result
        
    def run(self):
        self.status.emit(f"Processing {len(self.urls)} articles with {self.num_threads} threads...")
        
        # Setup ThreadPoolExecutor for parallel processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            futures = []
            for url in self.urls:
                future = executor.submit(self.process_article_wrapper, url)
                futures.append(future)
                
            # Track progress
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                self.progress.emit(i + 1, len(self.urls))
                
        self.status.emit(f"Completed processing {len(self.processed_chapters)} articles successfully.")
        self.finished.emit(self.processed_chapters)

class EpubCreationWorker(QThread):
    """Worker thread to create EPUB files in the background"""
    progress = pyqtSignal(int, int)  # current, total
    status = pyqtSignal(str)
    finished = pyqtSignal(list)  # list of generated filenames
    
    def __init__(self, chapters, save_dir, epub_title, cover_path=None, split=None):
        super().__init__()
        self.chapters = chapters
        self.save_dir = save_dir
        self.epub_title = epub_title
        self.cover_path = cover_path
        self.split = split
        
    def run(self):
        if not self.chapters:
            self.status.emit("No articles to create EPUB from.")
            self.finished.emit([])
            return
            
        self.status.emit(f"Creating EPUB with {len(self.chapters)} articles...")
        
        try:
            self.chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)
        except Exception as e:
            self.status.emit(f"Warning: Could not sort articles by date: {e}")
        
        generated_files = []
        
        if self.split:
            num_files = self.split
            total_articles = len(self.chapters)
            articles_per_file = (total_articles + num_files - 1) // num_files
            
            for i in range(num_files):
                start_index = i * articles_per_file
                end_index = min((i + 1) * articles_per_file, total_articles)
                
                if start_index < end_index:
                    split_chapters = self.chapters[start_index:end_index]
                    split_title = f"{self.epub_title} - Part {i+1}"
                    
                    self.status.emit(f"Creating Part {i+1} with {len(split_chapters)} articles...")
                    
                    filename = create_epub(
                        split_chapters, 
                        self.save_dir, 
                        split_title, 
                        self.cover_path,
                        status_callback=lambda status: self.status.emit(status)
                    )
                    
                    if filename:
                        generated_files.append(filename)
                    
                    self.progress.emit(i + 1, num_files)
        else:
            filename = create_epub(
                self.chapters, 
                self.save_dir, 
                self.epub_title, 
                self.cover_path,
                status_callback=lambda status: self.status.emit(status)
            )
            
            if filename:
                generated_files.append(filename)
                
            self.progress.emit(1, 1)
            
        self.status.emit(f"EPUB creation complete. Generated {len(generated_files)} files.")
        self.finished.emit(generated_files)

# --- Custom Widgets ---
class StatusWidget(QFrame):
    """Widget to display status messages with auto-scroll"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.layout.addWidget(self.status_label)
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(120)
        self.layout.addWidget(self.log_display)
        
        self.clear_button = QPushButton("Clear Log")
        self.clear_button.clicked.connect(self.clear_log)
        self.layout.addWidget(self.clear_button)
        
    def set_status(self, message):
        """Update status label"""
        self.status_label.setText(message)
        self.add_log_message(message)
        
    def add_log_message(self, message):
        """Add message to log with timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_display.append(log_entry)
        
        # Auto-scroll to bottom
        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_display.setTextCursor(cursor)
        
    def clear_log(self):
        """Clear the log display"""
        self.log_display.clear()
        self.add_log_message("Log cleared")

class ArticleListWidget(QFrame):
    """Widget to display and manage the list of articles"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # Header with count
        self.header_layout = QHBoxLayout()
        self.count_label = QLabel("0 articles")
        self.header_layout.addWidget(self.count_label)
        
        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self.clear_articles)
        self.header_layout.addWidget(self.clear_button)
        
        self.layout.addLayout(self.header_layout)
        
        # Article list
        self.article_list = QListWidget()
        self.article_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.layout.addWidget(self.article_list)
        
        # Actions
        self.actions_layout = QHBoxLayout()
        
        self.remove_selected_button = QPushButton("Remove Selected")
        self.remove_selected_button.clicked.connect(self.remove_selected)
        self.actions_layout.addWidget(self.remove_selected_button)
        
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.select_all)
        self.actions_layout.addWidget(self.select_all_button)
        
        self.layout.addLayout(self.actions_layout)
        
        # Internal data
        self.articles = []  # [(url, title, metadata), ...]
        
    def add_article(self, url, title=None, metadata=None):
        """Add an article to the list"""
        # Don't add duplicates
        for existing_url, _, _ in self.articles:
            if existing_url == url:
                return
                
        if not title:
            title = url.split('/')[-1].replace('-', ' ').title()
            
        self.articles.append((url, title, metadata))
        
        item = QListWidgetItem(f"{title}")
        item.setToolTip(url)
        self.article_list.addItem(item)
        
        self.update_count()
        
    def add_articles(self, urls):
        """Add multiple article URLs at once"""
        for url in urls:
            self.add_article(url)
            
    def clear_articles(self):
        """Clear all articles from the list"""
        self.articles = []
        self.article_list.clear()
        self.update_count()
        
    def remove_selected(self):
        """Remove selected articles from the list"""
        selected_items = self.article_list.selectedItems()
        for item in selected_items:
            row = self.article_list.row(item)
            self.article_list.takeItem(row)
            del self.articles[row]
            
        self.update_count()
        
    def select_all(self):
        """Select all articles in the list"""
        self.article_list.selectAll()
        
    def update_count(self):
        """Update the count label"""
        count = len(self.articles)
        self.count_label.setText(f"{count} article{'s' if count != 1 else ''}")
        
    def get_urls(self):
        """Get all article URLs"""
        return [url for url, _, _ in self.articles]
        
    def update_article_metadata(self, title, metadata):
        """Update metadata for an article by title"""
        for i, (url, t, _) in enumerate(self.articles):
            if t == title:
                self.articles[i] = (url, title, metadata)
                break

# --- Main Application ---
class MisesWireApp(QMainWindow):
    """Main application window for the Mises Wire EPUB Generator"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mises Wire EPUB Generator")
        self.setMinimumSize(900, 700)
        
        # Setup UI
        self.setup_ui()
        
        # Restore settings
        self.load_settings()
        
        # Initialize data
        self.processed_chapters = []  # Will hold processed article data
        self.current_worker = None  # Current background worker
        
    def setup_ui(self):
        """Setup the main user interface"""
        # Main widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout()
        self.central_widget.setLayout(self.main_layout)
        
        # Create tab widget for different functions
        self.tab_widget = QTabWidget()
        self.main_layout.addWidget(self.tab_widget)
        
        # Create tabs
        self.setup_source_tab()
        self.setup_processing_tab()
        self.setup_export_tab()
        self.setup_settings_tab()
        
        # Status area at bottom
        self.status_widget = StatusWidget()
        self.main_layout.addWidget(self.status_widget)
        
        # Initial status message
        self.status_widget.set_status("Ready to fetch articles from Mises Wire.")
        
    def setup_source_tab(self):
        """Setup the Source tab for fetching articles"""
        source_tab = QWidget()
        layout = QVBoxLayout()
        source_tab.setLayout(layout)
        
        # Source options
        source_group = QGroupBox("Article Source")
        source_layout = QFormLayout()
        source_group.setLayout(source_layout)
        
        # Add source types
        self.source_type_group = QButtonGroup()
        
        self.source_index_radio = QRadioButton("Fetch from Index")
        self.source_index_radio.setChecked(True)
        self.source_type_group.addButton(self.source_index_radio)
        source_layout.addRow(self.source_index_radio, QWidget())
        
        # Index URL input
        self.index_url_layout = QHBoxLayout()
        self.index_url_input = QLineEdit("https://mises.org/wire")
        self.index_url_input.setPlaceholderText("https://mises.org/wire")
        self.index_url_layout.addWidget(self.index_url_input)
        
        self.include_power_market = QCheckBox("Include Power Market")
        self.index_url_layout.addWidget(self.include_power_market)
        
        source_layout.addRow("Index URL:", self.index_url_layout)
        
        # Pages to fetch
        self.pages_spinbox = QSpinBox()
        self.pages_spinbox.setRange(1, 1000)
        self.pages_spinbox.setValue(50)
        source_layout.addRow("Pages to fetch:", self.pages_spinbox)
        
        # Specific URL radio
        self.source_url_radio = QRadioButton("Specific Article URL")
        self.source_type_group.addButton(self.source_url_radio)
        source_layout.addRow(self.source_url_radio, QWidget())
        
        # Specific URL input
        self.specific_url_input = QLineEdit()
        self.specific_url_input.setPlaceholderText("https://mises.org/wire/article-title")
        source_layout.addRow("Article URL:", self.specific_url_input)
        
        # Custom list radio
        self.source_list_radio = QRadioButton("Custom List of URLs")
        self.source_type_group.addButton(self.source_list_radio)
        source_layout.addRow(self.source_list_radio, QWidget())
        
        # Add to layout
        layout.addWidget(source_group)
        
        # Article list
        self.article_list_widget = ArticleListWidget()
        layout.addWidget(self.article_list_widget)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.fetch_button = QPushButton("Fetch Articles")
        self.fetch_button.clicked.connect(self.fetch_articles)
        button_layout.addWidget(self.fetch_button)
        
        self.add_url_button = QPushButton("Add URL")
        self.add_url_button.clicked.connect(self.add_specific_url)
        button_layout.addWidget(self.add_url_button)
        
        layout.addLayout(button_layout)
        
        # Progress bar
        self.fetch_progress = QProgressBar()
        self.fetch_progress.setRange(0, 100)
        self.fetch_progress.setValue(0)
        self.fetch_progress.setVisible(False)
        layout.addWidget(self.fetch_progress)
        
        # Add the tab
        self.tab_widget.addTab(source_tab, "Source")
        
    def setup_processing_tab(self):
        """Setup the Processing tab for downloading and processing articles"""
        processing_tab = QWidget()
        layout = QVBoxLayout()
        processing_tab.setLayout(layout)
        
        # Processing options
        options_group = QGroupBox("Processing Options")
        options_layout = QFormLayout()
        options_group.setLayout(options_layout)
        
        # Download images checkbox
        self.download_images_checkbox = QCheckBox("Download Images")
        self.download_images_checkbox.setChecked(True)
        options_layout.addRow(self.download_images_checkbox, QWidget())
        
        # Threads for processing
        self.threads_spinbox = QSpinBox()
        self.threads_spinbox.setRange(1, 20)
        self.threads_spinbox.setValue(5)
        options_layout.addRow("Processing Threads:", self.threads_spinbox)
        
        # Cache options
        cache_layout = QHBoxLayout()
        self.use_cache_checkbox = QCheckBox("Use Cache")
        self.use_cache_checkbox.setChecked(False)
        cache_layout.addWidget(self.use_cache_checkbox)
        
        self.cache_dir_input = QLineEdit()
        self.cache_dir_input.setPlaceholderText("Cache Directory (optional)")
        cache_layout.addWidget(self.cache_dir_input)
        
        self.browse_cache_button = QPushButton("Browse...")
        self.browse_cache_button.clicked.connect(self.browse_cache_dir)
        cache_layout.addWidget(self.browse_cache_button)
        
        options_layout.addRow("Cache:", cache_layout)
        
        layout.addWidget(options_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.process_button = QPushButton("Process Articles")
        self.process_button.clicked.connect(self.process_articles)
        button_layout.addWidget(self.process_button)
        
        layout.addLayout(button_layout)
        
        # Progress indicators
        self.process_progress = QProgressBar()
        self.process_progress.setRange(0, 100)
        self.process_progress.setValue(0)
        self.process_progress.setVisible(False)
        layout.addWidget(self.process_progress)
        
        # Processed articles display
        self.processed_count_label = QLabel("0 articles processed")
        layout.addWidget(self.processed_count_label)
        
        self.processed_list = QListWidget()
        layout.addWidget(self.processed_list)
        
        # Add the tab
        self.tab_widget.addTab(processing_tab, "Processing")
        
    def setup_export_tab(self):
        """Setup the Export tab for creating EPUB files"""
        export_tab = QWidget()
        layout = QVBoxLayout()
        export_tab.setLayout(layout)
        
        # EPUB options
        epub_group = QGroupBox("EPUB Options")
        epub_layout = QFormLayout()
        epub_group.setLayout(epub_layout)
        
        # EPUB title
        self.epub_title_input = QLineEdit("Mises Wire Collection")
        epub_layout.addRow("EPUB Title:", self.epub_title_input)
        
        # Output directory
        output_layout = QHBoxLayout()
        self.output_dir_input = QLineEdit("./mises_epub")
        output_layout.addWidget(self.output_dir_input)
        
        self.browse_output_button = QPushButton("Browse...")
        self.browse_output_button.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(self.browse_output_button)
        
        epub_layout.addRow("Output Directory:", output_layout)
        
        # Cover image
        cover_layout = QHBoxLayout()
        self.cover_path_input = QLineEdit()
        self.cover_path_input.setPlaceholderText("Cover Image Path (optional)")
        cover_layout.addWidget(self.cover_path_input)
        
        self.browse_cover_button = QPushButton("Browse...")
        self.browse_cover_button.clicked.connect(self.browse_cover_image)
        cover_layout.addWidget(self.browse_cover_button)
        
        epub_layout.addRow("Cover Image:", cover_layout)
        
        # Split options
        split_layout = QHBoxLayout()
        self.use_split_checkbox = QCheckBox("Split into multiple EPUBs")
        split_layout.addWidget(self.use_split_checkbox)
        
        self.split_spinbox = QSpinBox()
        self.split_spinbox.setRange(2, 100)
        self.split_spinbox.setValue(5)
        split_layout.addWidget(self.split_spinbox)
        
        split_layout.addWidget(QLabel("files"))
        
        epub_layout.addRow("Split:", split_layout)
        
        layout.addWidget(epub_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.create_epub_button = QPushButton("Create EPUB")
        self.create_epub_button.clicked.connect(self.create_epub_files)
        button_layout.addWidget(self.create_epub_button)
        
        self.open_output_button = QPushButton("Open Output Directory")
        self.open_output_button.clicked.connect(self.open_output_directory)
        button_layout.addWidget(self.open_output_button)
        
        layout.addLayout(button_layout)
        
        # Progress indicators
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        self.export_progress.setValue(0)
        self.export_progress.setVisible(False)
        layout.addWidget(self.export_progress)
        
        # Results display
        self.results_group = QGroupBox("Created EPUB Files")
        results_layout = QVBoxLayout()
        self.results_group.setLayout(results_layout)
        
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.open_epub_file)
        results_layout.addWidget(self.results_list)
        
        layout.addWidget(self.results_group)
        
        # Add the tab
        self.tab_widget.addTab(export_tab, "Export")
        
    def setup_settings_tab(self):
        """Setup the Settings tab for configuring the application"""
        settings_tab = QWidget()
        layout = QVBoxLayout()
        settings_tab.setLayout(layout)
        
        # Network settings
        network_group = QGroupBox("Network Settings")
        network_layout = QFormLayout()
        network_group.setLayout(network_layout)
        
        # Timeout
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(5, 300)
        self.timeout_spinbox.setValue(30)
        self.timeout_spinbox.setSuffix(" seconds")
        network_layout.addRow("Request Timeout:", self.timeout_spinbox)
        
        # Proxy
        proxy_layout = QHBoxLayout()
        self.use_proxy_checkbox = QCheckBox("Use Proxy")
        proxy_layout.addWidget(self.use_proxy_checkbox)
        
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://proxy:port")
        proxy_layout.addWidget(self.proxy_input)
        
        network_layout.addRow("Proxy:", proxy_layout)
        
        # SSL verification
        self.verify_ssl_checkbox = QCheckBox("Verify SSL Certificates")
        self.verify_ssl_checkbox.setChecked(True)
        network_layout.addRow(self.verify_ssl_checkbox, QWidget())
        
        layout.addWidget(network_group)
        
        # Logging settings
        logging_group = QGroupBox("Logging Settings")
        logging_layout = QFormLayout()
        logging_group.setLayout(logging_layout)
        
        # Log level
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        logging_layout.addRow("Log Level:", self.log_level_combo)
        
        layout.addWidget(logging_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.apply_settings_button = QPushButton("Apply Settings")
        self.apply_settings_button.clicked.connect(self.apply_settings)
        button_layout.addWidget(self.apply_settings_button)
        
        self.reset_settings_button = QPushButton("Reset to Defaults")
        self.reset_settings_button.clicked.connect(self.reset_settings)
        button_layout.addWidget(self.reset_settings_button)
        
        layout.addLayout(button_layout)
        
        # Add the tab
        self.tab_widget.addTab(settings_tab, "Settings")
        
    def load_settings(self):
        """Load application settings"""
        settings = QSettings("MisesWire", "EpubGenerator")
        
        # Source settings
        self.index_url_input.setText(settings.value("source/index_url", "https://mises.org/wire"))
        self.pages_spinbox.setValue(int(settings.value("source/pages", 50)))
        self.include_power_market.setChecked(settings.value("source/include_power_market", False, type=bool))
        
        # Processing settings
        self.download_images_checkbox.setChecked(settings.value("processing/download_images", True, type=bool))
        self.threads_spinbox.setValue(int(settings.value("processing/threads", 5)))
        self.use_cache_checkbox.setChecked(settings.value("processing/use_cache", False, type=bool))
        self.cache_dir_input.setText(settings.value("processing/cache_dir", ""))
        
        # Export settings
        self.epub_title_input.setText(settings.value("export/epub_title", "Mises Wire Collection"))
        self.output_dir_input.setText(settings.value("export/output_dir", "./mises_epub"))
        self.cover_path_input.setText(settings.value("export/cover_path", ""))
        self.use_split_checkbox.setChecked(settings.value("export/use_split", False, type=bool))
        self.split_spinbox.setValue(int(settings.value("export/split_count", 5)))
        
        # Network settings
        self.timeout_spinbox.setValue(int(settings.value("network/timeout", 30)))
        self.use_proxy_checkbox.setChecked(settings.value("network/use_proxy", False, type=bool))
        self.proxy_input.setText(settings.value("network/proxy", ""))
        self.verify_ssl_checkbox.setChecked(settings.value("network/verify_ssl", True, type=bool))
        
        # Logging settings
        self.log_level_combo.setCurrentText(settings.value("logging/level", "INFO"))
        
        # Apply settings
        self.apply_settings()
        
    def save_settings(self):
        """Save application settings"""
        settings = QSettings("MisesWire", "EpubGenerator")
        
        # Source settings
        settings.setValue("source/index_url", self.index_url_input.text())
        settings.setValue("source/pages", self.pages_spinbox.value())
        settings.setValue("source/include_power_market", self.include_power_market.isChecked())
        
        # Processing settings
        settings.setValue("processing/download_images", self.download_images_checkbox.isChecked())
        settings.setValue("processing/threads", self.threads_spinbox.value())
        settings.setValue("processing/use_cache", self.use_cache_checkbox.isChecked())
        settings.setValue("processing/cache_dir", self.cache_dir_input.text())
        
        # Export settings
        settings.setValue("export/epub_title", self.epub_title_input.text())
        settings.setValue("export/output_dir", self.output_dir_input.text())
        settings.setValue("export/cover_path", self.cover_path_input.text())
        settings.setValue("export/use_split", self.use_split_checkbox.isChecked())
        settings.setValue("export/split_count", self.split_spinbox.value())
        
        # Network settings
        settings.setValue("network/timeout", self.timeout_spinbox.value())
        settings.setValue("network/use_proxy", self.use_proxy_checkbox.isChecked())
        settings.setValue("network/proxy", self.proxy_input.text())
        settings.setValue("network/verify_ssl", self.verify_ssl_checkbox.isChecked())
        
        # Logging settings
        settings.setValue("logging/level", self.log_level_combo.currentText())
        
    def apply_settings(self):
        """Apply current settings to the application"""
        global PROXIES, VERIFY, TIMEOUT, CACHE_DIR
        
        # Update global settings
        TIMEOUT = self.timeout_spinbox.value()
        
        # Configure proxy
        if self.use_proxy_checkbox.isChecked() and self.proxy_input.text():
            PROXIES = {"http": self.proxy_input.text(), "https": self.proxy_input.text()}
        else:
            PROXIES = {}
            
        # Configure SSL verification
        if self.verify_ssl_checkbox.isChecked():
            VERIFY = certifi.where()
        else:
            VERIFY = False
            
        # Configure cache
        if self.use_cache_checkbox.isChecked() and self.cache_dir_input.text():
            CACHE_DIR = self.cache_dir_input.text()
            os.makedirs(CACHE_DIR, exist_ok=True)
        else:
            CACHE_DIR = None
            
        # Configure logging
        log_level = getattr(logging, self.log_level_combo.currentText())
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("mises_scraper.log"),
                logging.StreamHandler()
            ],
            force=True
        )
        
        self.status_widget.set_status("Settings applied successfully.")
        self.save_settings()
        
    def reset_settings(self):
        """Reset settings to defaults"""
        # Source settings
        self.index_url_input.setText("https://mises.org/wire")
        self.pages_spinbox.setValue(50)
        self.include_power_market.setChecked(False)
        
        # Processing settings
        self.download_images_checkbox.setChecked(True)
        self.threads_spinbox.setValue(5)
        self.use_cache_checkbox.setChecked(False)
        self.cache_dir_input.setText("")
        
        # Export settings
        self.epub_title_input.setText("Mises Wire Collection")
        self.output_dir_input.setText("./mises_epub")
        self.cover_path_input.setText("")
        self.use_split_checkbox.setChecked(False)
        self.split_spinbox.setValue(5)
        
        # Network settings
        self.timeout_spinbox.setValue(30)
        self.use_proxy_checkbox.setChecked(False)
        self.proxy_input.setText("")
        self.verify_ssl_checkbox.setChecked(True)
        
        # Logging settings
        self.log_level_combo.setCurrentText("INFO")
        
        # Apply the default settings
        self.apply_settings()
        self.status_widget.set_status("Settings reset to defaults.")
        
    def browse_cache_dir(self):
        """Browse for cache directory"""
        directory = QFileDialog.getExistingDirectory(self, "Select Cache Directory")
        if directory:
            self.cache_dir_input.setText(directory)
            
    def browse_output_dir(self):
        """Browse for output directory"""
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_input.setText(directory)
            
    def browse_cover_image(self):
        """Browse for cover image file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Cover Image", "", "Image Files (*.jpg *.jpeg *.png);;All Files (*)"
        )
        if file_path:
            self.cover_path_input.setText(file_path)
            
    def open_output_directory(self):
        """Open the output directory in file explorer"""
        output_dir = self.output_dir_input.text()
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(output_dir)))
        
    def open_epub_file(self, item):
        """Open the selected EPUB file with the default application"""
        file_path = item.text()
        if os.path.exists(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
        else:
            self.status_widget.set_status(f"File not found: {file_path}")
            
    def fetch_articles(self):
        """Fetch articles from the selected source"""
        # Validate source selection
        if self.source_index_radio.isChecked():
            index_url = self.index_url_input.text()
            if not is_valid_url(index_url):
                self.status_widget.set_status("❌ Invalid index URL provided.")
                return
                
            max_pages = self.pages_spinbox.value()
            
            # Setup progress tracking
            self.fetch_progress.setRange(0, max_pages)
            self.fetch_progress.setValue(0)
            self.fetch_progress.setVisible(True)
            
            # Disable the fetch button while working
            self.fetch_button.setEnabled(False)
            
            # Create and start worker thread
            self.status_widget.set_status(f"Fetching articles from {index_url}...")
            self.worker = ArticleFetchWorker(index_url, max_pages)
            
            # Connect signals
            self.worker.progress.connect(self.update_fetch_progress)
            self.worker.status.connect(self.status_widget.set_status)
            self.worker.finished.connect(self.fetch_completed)
            
            # Start the worker
            self.worker.start()
            
        elif self.source_url_radio.isChecked():
            url = self.specific_url_input.text()
            if not is_valid_url(url):
                self.status_widget.set_status("❌ Invalid article URL provided.")
                return
                
            self.article_list_widget.add_article(url)
            self.status_widget.set_status(f"Added article URL: {url}")
            
        elif self.source_list_radio.isChecked():
            self.status_widget.set_status("Please add URLs manually using the 'Add URL' button.")
            
    def update_fetch_progress(self, page, max_pages, num_articles):
        """Update the progress bar during article fetching"""
        self.fetch_progress.setValue(page)
        self.status_widget.set_status(f"Fetching page {page}/{max_pages} - Found {num_articles} articles")
        
    def fetch_completed(self, article_links):
        """Handle the completion of article fetching"""
        self.fetch_progress.setVisible(False)
        self.fetch_button.setEnabled(True)
        
        # Add the fetched article links
        self.article_list_widget.add_articles(article_links)
        
        # Check if we should include Power Market articles
        if self.include_power_market.isChecked():
            self.status_widget.set_status("Fetching articles from Power Market...")
            
            # Create and start a new worker thread for Power Market
            self.worker = ArticleFetchWorker("https://mises.org/power-market", self.pages_spinbox.value())
            
            # Connect signals
            self.worker.progress.connect(self.update_fetch_progress)
            self.worker.status.connect(self.status_widget.set_status)
            self.worker.finished.connect(lambda links: self.power_market_completed(links))
            
            # Start the worker
            self.worker.start()
        else:
            self.status_widget.set_status(f"✅ Fetched {len(article_links)} articles.")
            
    def power_market_completed(self, article_links):
        """Handle the completion of Power Market article fetching"""
        self.fetch_progress.setVisible(False)
        self.fetch_button.setEnabled(True)
        
        # Add the fetched article links
        self.article_list_widget.add_articles(article_links)
        
        self.status_widget.set_status(f"✅ Added {len(article_links)} Power Market articles.")
        
    def add_specific_url(self):
        """Add a specific URL to the article list"""
        url = self.specific_url_input.text()
        if not url:
            self.status_widget.set_status("Please enter a URL first.")
            return
            
        if not is_valid_url(url):
            self.status_widget.set_status("❌ Invalid URL format.")
            return
            
        self.article_list_widget.add_article(url)
        self.specific_url_input.clear()
        self.status_widget.set_status(f"Added article URL: {url}")
        
    def process_articles(self):
        """Process the articles in the list"""
        urls = self.article_list_widget.get_urls()
        if not urls:
            self.status_widget.set_status("No articles to process. Please fetch or add some first.")
            return
            
        # Clear previous processed results
        self.processed_chapters = []
        self.processed_list.clear()
        self.processed_count_label.setText("0 articles processed")
        
        # Setup progress tracking
        self.process_progress.setRange(0, len(urls))
        self.process_progress.setValue(0)
        self.process_progress.setVisible(True)
        
        # Disable the process button while working
        self.process_button.setEnabled(False)
        
        # Create and start worker thread
        download_images = self.download_images_checkbox.isChecked()
        threads = self.threads_spinbox.value()
        
        self.status_widget.set_status(f"Processing {len(urls)} articles with {threads} threads...")
        self.worker = ArticleProcessWorker(urls, download_images, threads)
        
        # Connect signals
        self.worker.progress.connect(self.update_process_progress)
        self.worker.status.connect(self.status_widget.set_status)
        self.worker.article_processed.connect(self.article_processed)
        self.worker.article_failed.connect(lambda url: self.status_widget.add_log_message(f"Failed to process: {url}"))
        self.worker.finished.connect(self.processing_completed)
        
        # Start the worker
        self.worker.start()
        
    def update_process_progress(self, current, total):
        """Update the progress bar during article processing"""
        self.process_progress.setValue(current)
        
    def article_processed(self, article_data):
        """Handle a successfully processed article"""
        title, chapter, metadata, image_items = article_data
        
        # Add to our processed chapters list
        self.processed_chapters.append((title, chapter, metadata, image_items))
        
        # Update UI
        self.processed_list.addItem(title)
        self.processed_count_label.setText(f"{len(self.processed_chapters)} articles processed")
        
    def processing_completed(self, processed_chapters):
        """Handle the completion of article processing"""
        self.process_progress.setVisible(False)
        self.process_button.setEnabled(True)
        
        total = len(processed_chapters)
        self.status_widget.set_status(f"✅ Processed {total} articles successfully.")
        
        # Switch to the Export tab
        self.tab_widget.setCurrentIndex(2)
        
    def create_epub_files(self):
        """Create EPUB files from the processed articles"""
        if not self.processed_chapters:
            self.status_widget.set_status("No processed articles available. Please process some first.")
            return
            
        # Get export settings
        epub_title = self.epub_title_input.text()
        save_dir = self.output_dir_input.text()
        cover_path = self.cover_path_input.text() if os.path.exists(self.cover_path_input.text()) else None
        
        # Create output directory if it doesn't exist
        os.makedirs(save_dir, exist_ok=True)
        
        # Check if we should split the EPUB
        split = None
        if self.use_split_checkbox.isChecked():
            split = self.split_spinbox.value()
            
        # Setup progress tracking
        self.export_progress.setValue(0)
        self.export_progress.setVisible(True)
        
        # Disable the create button while working
        self.create_epub_button.setEnabled(False)
        
        # Clear previous results
        self.results_list.clear()
        
        # Create and start worker thread
        self.status_widget.set_status(f"Creating EPUB with {len(self.processed_chapters)} articles...")
        self.worker = EpubCreationWorker(self.processed_chapters, save_dir, epub_title, cover_path, split)
        
        # Connect signals
        self.worker.progress.connect(lambda current, total: self.export_progress.setValue(int(100 * current / total)))
        self.worker.status.connect(self.status_widget.set_status)
        self.worker.finished.connect(self.epub_creation_completed)
        
        # Start the worker
        self.worker.start()
        
    def epub_creation_completed(self, generated_files):
        """Handle the completion of EPUB creation"""
        self.export_progress.setVisible(False)
        self.create_epub_button.setEnabled(True)
        
        if not generated_files:
            self.status_widget.set_status("❌ Failed to create any EPUB files.")
            return
            
        self.status_widget.set_status(f"✅ Successfully created {len(generated_files)} EPUB file(s).")
        
        # Add files to the results list
        for file_path in generated_files:
            self.results_list.addItem(file_path)
            
        # Ask if user wants to open the output directory
        reply = QMessageBox.question(
            self, 
            "EPUB Creation Completed", 
            f"Successfully created {len(generated_files)} EPUB file(s).\n\nWould you like to open the output directory?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.open_output_directory()

# --- Main Function ---
def main():
    # Configure application
    QCoreApplication.setApplicationName("Mises Wire EPUB Generator")
    QCoreApplication.setOrganizationName("MisesWire")
    
    # Create and run application
    app = QApplication(sys.argv)
    window = MisesWireApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
