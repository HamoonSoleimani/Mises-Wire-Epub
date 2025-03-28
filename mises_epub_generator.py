#!/usr/bin/env python3
import os
import re
import logging
import argparse
import requests
from bs4 import BeautifulSoup
from readability import Document
from ebooklib import epub
import traceback
from urllib.parse import urljoin, urlparse
import concurrent.futures
from PIL import Image
from io import BytesIO
from datetime import datetime
from dateutil import parser as date_parser
import base64
import hashlib
import time
from tqdm import tqdm
import certifi

# Global configuration variables (updated in main())
PROXIES = {}
VERIFY = certifi.where()
TIMEOUT = 30
CACHE_DIR = None  # Global cache directory (set via --cache)

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

def get_article_links(index_url, max_pages=1000):
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

    with tqdm(total=max_pages, desc="Fetching article links") as pbar:
        page_num = 1
        end_reached = False

        while page_num <= max_pages and not end_reached:
            links, end_reached = fetch_page_links(page_num)
            all_article_links.update(links)
            pbar.update(1)
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

def process_article(url, download_images=True):
    """
    Downloads, parses, extracts content, and processes images from an article.
    Handles both regular images and data URIs.
    Uses caching if CACHE_DIR is set.
    """
    logging.debug(f"Processing URL: {url}")
    image_items = []
    image_filenames = set()  # Track processed image filenames to avoid duplicates

    try:
        html_content = cached_get(url)
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
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
        logging.warning(f"Skipping article due to extraction failure: {url}")
        return None, None, None, []

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
        for img_tag in cleaned_soup.find_all('img', src=True):
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
    return title, chapter, metadata, image_items

def create_epub(chapters, save_dir, epub_title, cover_path=None, author="Mises Wire", language='en'):
    """
    Create an EPUB file from a list of chapters, including images.
    """
    if not chapters:
        logging.error("No chapters provided to create_epub")
        return

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
        chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)
    except Exception as e:
        logging.warning(f"Failed to sort chapters by date: {e}")

    toc = [epub.Link('intro.xhtml', intro_title, 'intro')]
    spine = ['nav', intro_chapter]
    
    # Use a set to track processed image file paths to avoid duplicates
    image_filenames = set()
    all_image_items = []

    for title, chapter, metadata, image_items in chapters:
        book.add_item(chapter)
        toc.append(epub.Link(chapter.file_name, title, chapter.id))
        spine.append(chapter)
        
        # Only add unique images
        for image_item in image_items:
            if image_item.file_name not in image_filenames:
                all_image_items.append(image_item)
                image_filenames.add(image_item.file_name)

    # Add all unique images to the book
    for image_item in all_image_items:
        book.add_item(image_item)

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
        epub.write_epub(filename, book, {})
        logging.info(f"Saved EPUB: {filename}")
        return filename
    except Exception as e:
        logging.error(f"Failed to write EPUB: {e}", exc_info=True)
        return None

def main():
    global PROXIES, VERIFY, TIMEOUT, CACHE_DIR
    parser = argparse.ArgumentParser(
        description='Convert Mises Wire articles into EPUB files with enhanced image handling.'
    )
    parser.add_argument('--all', action='store_true', help='Convert all articles.')
    parser.add_argument('--url', type=str, help='URL of a specific article to convert.')
    parser.add_argument('--index', type=str, default="https://mises.org/wire", help='Index URL to fetch articles from.')
    parser.add_argument('--pages', type=int, default=50, help='Number of index pages to check.')
    parser.add_argument('--save_dir', type=str, default="./mises_epub", help='Directory to save the EPUB files.')
    parser.add_argument('--epub_title', type=str, default="Mises Wire Collection", help='Base title for the EPUB.')
    parser.add_argument('--split', type=int, default=None, help='Split into multiple EPUBs with N articles each.')
    parser.add_argument('--cover', type=str, default=None, help='Path to a cover image.')
    parser.add_argument('--threads', type=int, default=5, help='Number of threads to use for processing.')
    parser.add_argument('--skip_images', action='store_true', help='Skip downloading images (faster, smaller EPUB).')
    parser.add_argument('--log', type=str, default='info', choices=['debug', 'info', 'warning', 'error'],
                        help='Logging level.')
    parser.add_argument('--timeout', type=int, default=120, help='Timeout in seconds for article processing.')
    parser.add_argument('--proxy', type=str, default=None, help='Proxy URL to use for requests (e.g. http://127.0.0.1:8080).')
    parser.add_argument('--no_ssl_verify', action='store_true', help='Disable SSL certificate verification.')
    # New arguments for caching and including additional source
    parser.add_argument('--cache', type=str, default=None, help='Directory for cached HTML files (enable caching if provided).')
    parser.add_argument('--include', type=str, default=None, help='Additional sources to include. Use "powermarket" to include https://mises.org/power-market.')
    args = parser.parse_args()

    log_level = getattr(logging, args.log.upper())
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("mises_scraper.log"),
            logging.StreamHandler()
        ]
    )

    logging.info(f"Mises Wire EPUB Generator - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Save directory: {os.path.abspath(args.save_dir)}")
    logging.info(f"Threads: {args.threads}")
    logging.info(f"Image download: {'disabled' if args.skip_images else 'enabled'}")

    TIMEOUT = args.timeout
    if args.proxy:
        PROXIES = {"http": args.proxy, "https": args.proxy}
    else:
        PROXIES = {}
    if args.no_ssl_verify:
        VERIFY = False
    else:
        VERIFY = certifi.where()

    if args.cache:
        CACHE_DIR = args.cache
        os.makedirs(CACHE_DIR, exist_ok=True)

    processed_chapters = []
    if args.all:
        article_links = get_article_links(args.index, max_pages=args.pages)
        logging.info(f"Found {len(article_links)} article links to process.")
        if args.include and 'powermarket' in args.include.lower():
            logging.info("Including articles from Mises Power Market")
            pm_links = get_article_links("https://mises.org/power-market", max_pages=args.pages)
            article_links = list(set(article_links) | set(pm_links))

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
            future_to_url = {executor.submit(process_article, url, not args.skip_images): url for url in article_links}
            for future in tqdm(concurrent.futures.as_completed(future_to_url), total=len(article_links), desc="Processing articles"):
                url = future_to_url[future]
                try:
                    title, chapter, metadata, chapter_image_items = future.result()
                    if title and chapter:
                        processed_chapters.append((title, chapter, metadata, chapter_image_items))
                    else:
                        logging.error(f"Skipping article at {url} due to processing errors.")
                except Exception as exc:
                    logging.error(f"Article at {url} generated an exception: {exc}", exc_info=True)
    elif args.url:
        if is_valid_url(args.url):
            title, chapter, metadata, chapter_image_items = process_article(args.url, not args.skip_images)
            if title and chapter:
                processed_chapters.append((title, chapter, metadata, chapter_image_items))
            else:
                logging.error(f"Failed to process single article at {args.url}")
        else:
            logging.error("Invalid URL provided with --url.")
    else:
        logging.error("No action specified. Use --all, --url.")
        return

    if not processed_chapters:
        logging.error("No articles were successfully processed. EPUB not created.")
        return

    try:
        processed_chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)
    except Exception as e:
        logging.warning(f"Failed to sort globally: {e}")

    if args.split:
        num_files = args.split
        total_articles = len(processed_chapters)
        articles_per_file = (total_articles + num_files - 1) // num_files
        for i in range(num_files):
            start_index = i * articles_per_file
            end_index = min((i + 1) * articles_per_file, total_articles)
            if start_index < end_index:
                split_chapters = processed_chapters[start_index:end_index]
                split_title = f"{args.epub_title} - Part {i+1}"
                create_epub(split_chapters, args.save_dir, split_title, args.cover)
    else:
        create_epub(processed_chapters, args.save_dir, args.epub_title, args.cover)

    logging.info("Finished.")

if __name__ == '__main__':
    main()
