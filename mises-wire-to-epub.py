#!/usr/bin/env python3
import os
import re
import logging
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from readability import Document
from ebooklib import epub
import traceback
from urllib.parse import urljoin, urlparse
import concurrent.futures
from PIL import Image
from io import BytesIO
from datetime import datetime, timezone
from dateutil import parser as date_parser
import base64
import hashlib
import time
from tqdm import tqdm
import certifi
import json
import signal
import sys

# --- Configuration ---

# Define available sections and their base URLs
SECTION_URLS = {
    "wire": "https://mises.org/wire",
    "powermarket": "https://mises.org/power-market",
    # Add more sections here if needed in the future
    # "blog": "https://mises.org/blog", # Example
}

# Global configuration variables (updated in main())
PROXIES = {}
VERIFY_SSL = certifi.where()
REQUEST_TIMEOUT = 60  # Increased default timeout for potentially slow connections
FETCH_DELAY = 0.75    # Default delay between requests to be polite
RETRY_COUNT = 3       # Number of retries for failed requests
RETRY_BACKOFF = 1     # Backoff factor for retries (e.g., 1 -> 0s, 1s, 2s)
CACHE_DIR = "./.mises_cache"
USE_CACHE = False

# Define URLs/patterns to ignore for images (these images will be skipped)
IGNORED_IMAGE_URLS = {
    "https://cdn.mises.org/styles/social_media/s3/images/2025-03/25_Loot%26Lobby_QUOTE_4K_20250311.jpg?itok=IkGXwPjO",
    # Patterns for generic featured images that often lack specific content
    "https://mises.org/wire/images/featured_image.jpeg",
    "https://mises.org/power-market/images/featured_image.jpeg",
    "https://mises.org/power-market/images/featured_image.webp",
    "https://mises.org/podcasts/radio-rothbard/images/featured_image.jpeg",
    "https://mises.org/podcasts/loot-and-lobby/images/featured_image.jpeg",
    "https://mises.org/friday-philosophy/images/featured_image.jpeg",
    "https://mises.org/articles-interest/images/featured_image.jpeg",
    "https://mises.org/articles-interest/images/featured_image.webp",
    "https://mises.org/podcasts/human-action-podcast/images/featured_image.jpeg",
    # Add more specific problematic URLs if found
}

# Regex Patterns to identify problematic image URLs
IGNORED_IMAGE_URL_PATTERNS = [
    r'featured_image\.(jpeg|jpg|png|webp)$', # Generic featured image names often reused
    r'/podcasts/.*/images/',                # Images within podcast directories (often generic)
    r'/mises\.org$'                         # Base domain URL sometimes appears erroneously
]

# User-Agent header for HTTP requests with rotation capability
USER_AGENTS = [
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) '
     'Chrome/114.0.0.0 Safari/537.36'),
    ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
     'AppleWebKit/605.1.15 (KHTML, like Gecko) '
     'Version/16.5 Safari/605.1.15'),
    ('Mozilla/5.0 (X11; Linux x86_64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) '
     'Chrome/114.0.0.0 Safari/537.36'),
    ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) '
     'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1')
]

# --- Helper Functions ---

def get_headers():
    """Returns headers with a randomly selected User-Agent."""
    return {
        'User-Agent': USER_AGENTS[int(time.time()) % len(USER_AGENTS)],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
        'Referer': 'https://mises.org/' # Add a referer
    }

def get_session_with_retries(retries=RETRY_COUNT, backoff_factor=RETRY_BACKOFF,
                             status_forcelist=(500, 502, 503, 504), session=None):
    """Creates a requests session with retry logic and custom settings."""
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    session.headers.update(get_headers())
    session.proxies = PROXIES
    session.verify = VERIFY_SSL # Use global SSL setting
    return session

def fetch_with_retry(url, session=None, stream=False, method='GET', data=None, headers=None):
    """ Fetches a URL with retry logic using the configured session settings. """
    local_session = session or get_session_with_retries()
    req_headers = get_headers() # Get fresh headers for each request
    if headers:
        req_headers.update(headers)

    cache_key = hashlib.md5(f"{method}:{url}:{data}".encode()).hexdigest()
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.cache")
    metadata_file = os.path.join(CACHE_DIR, f"{cache_key}.meta")

    if USE_CACHE and os.path.exists(cache_file):
        try:
            with open(metadata_file, 'r') as f_meta:
                metadata = json.load(f_meta)
            with open(cache_file, 'rb') as f_cache:
                content = f_cache.read()
            logging.debug(f"Cache hit for URL: {url}")
            # Create a mock response object
            response = requests.Response()
            response.url = metadata['url']
            response.status_code = metadata['status_code']
            response.headers = requests.structures.CaseInsensitiveDict(metadata['headers'])
            response._content = content
            response.encoding = metadata.get('encoding')
            response.request = requests.PreparedRequest() # Mock request object
            response.request.method = method
            response.request.url = url
            return response
        except Exception as e:
            logging.warning(f"Cache read error for {url}: {e}. Fetching from network.")
            # Clean up potentially corrupted cache files
            if os.path.exists(cache_file): os.remove(cache_file)
            if os.path.exists(metadata_file): os.remove(metadata_file)

    logging.debug(f"Fetching URL: {url} (Method: {method})")
    time.sleep(FETCH_DELAY) # Respect the delay before making the request
    try:
        response = local_session.request(method, url, timeout=REQUEST_TIMEOUT, stream=stream,
                                         data=data, headers=req_headers, allow_redirects=True)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        if USE_CACHE and response.status_code == 200:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_file, 'wb') as f_cache:
                f_cache.write(response.content)
            metadata = {
                'url': response.url,
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'encoding': response.encoding
            }
            with open(metadata_file, 'w') as f_meta:
                json.dump(metadata, f_meta)
            logging.debug(f"Cached response for URL: {url}")

        return response
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch {url} after retries: {e}")
        return None # Return None on failure

def sanitize_filename(title):
    """Creates a safe filename from the given title."""
    if not title:
        return "untitled"
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', title)
    # Replace whitespace with underscores
    filename = re.sub(r'\s+', '_', filename)
    # Remove leading/trailing underscores/spaces/periods
    filename = filename.strip('_. ')
    # Limit length to prevent issues on some filesystems
    return filename[:200]

def is_valid_url(url):
    """Checks if the given string is a valid HTTP/HTTPS URL."""
    try:
        result = urlparse(url)
        return all([result.scheme in ['http', 'https'], result.netloc])
    except ValueError:
        return False

def parse_date_flexible(date_str):
    """Parses various date string formats into a timezone-aware datetime object. Returns None on failure."""
    if not date_str:
        return None
    try:
        # Use dateutil.parser which is quite flexible
        dt = date_parser.parse(date_str)
        # If the datetime object is naive, assume UTC (or a local timezone if more appropriate)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            # Let's assume UTC as a reasonable default for web content
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError, TypeError) as e:
        logging.warning(f"Could not parse date string '{date_str}': {e}")
        return None

def parse_date_arg(date_str):
    """Parses a date argument (YYYY-MM-DD) into a timezone-aware datetime object."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Make it timezone-aware (start of the day in UTC)
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Not a valid date: '{date_str}'. Expected YYYY-MM-DD format.")


def clean_image_url(url):
    """Clean the image URL, removing potential JS concatenation artifacts."""
    if not url:
        return url
    # Example pattern found in some sites: "' + og_image:"
    url = re.sub(r"\s*\'\s*\+\s*og_image:.*", "", url)
    return url.strip().strip("'\"") # Remove surrounding quotes

def should_ignore_image_url(url):
    """Check if an image URL should be ignored based on explicit list or patterns."""
    if not url:
        return True

    cleaned_url = clean_image_url(url)
    if not is_valid_url(cleaned_url): # Also check validity after cleaning
        return True

    # Check against explicit list
    if cleaned_url in IGNORED_IMAGE_URLS:
        logging.debug(f"Ignoring image (explicit list): {cleaned_url}")
        return True

    # Check against patterns
    for pattern in IGNORED_IMAGE_URL_PATTERNS:
        if re.search(pattern, cleaned_url, re.IGNORECASE):
            logging.debug(f"Ignoring image (pattern match '{pattern}'): {cleaned_url}")
            return True

    return False

# --- Core Scraping Logic ---

def get_article_links(index_urls, max_pages_per_section=1000):
    """
    Fetch article URLs from specified Mises index URLs and their paginated pages.
    Returns a set of unique article URLs.
    """
    all_article_links = set()
    total_fetched_pages = 0

    for base_index_url in index_urls:
        section_name = urlparse(base_index_url).path.strip('/') or "home"
        logging.info(f"--- Starting link fetch for section: {section_name} ({base_index_url}) ---")

        with tqdm(total=max_pages_per_section, desc=f"Fetching links [{section_name}]", unit="page") as pbar:
            page_num = 1
            end_reached = False
            pages_fetched_this_section = 0

            while pages_fetched_this_section < max_pages_per_section and not end_reached:
                # Page 1 is the base URL, subsequent pages use ?page=N
                page_url = f"{base_index_url}?page={page_num-1}" if page_num > 1 else base_index_url

                logging.debug(f"Fetching index page: {page_url}")
                response = fetch_with_retry(page_url)
                if not response:
                    logging.error(f"Failed to fetch index page {page_url}, skipping section.")
                    break # Stop trying for this section

                pages_fetched_this_section += 1
                total_fetched_pages += 1
                pbar.update(1)

                soup = BeautifulSoup(response.text, 'html.parser')
                page_links_found = 0

                # Primary target: Modern <article> structure
                articles = soup.find_all('article', class_=re.compile(r'views-row|node')) # Common patterns
                if articles:
                    for art in articles:
                        # Look for the main link within the article, often wrapping the title
                        title_link = art.find(['h2', 'h3'], class_=re.compile(r'title|node-title'))
                        a_tag = title_link.find('a', href=True) if title_link else art.find('a', href=True)

                        if a_tag:
                            href = a_tag['href']
                            # Basic sanity checks
                            if not href or href.startswith('#') or 'javascript:' in href or 'rss.xml' in href:
                                continue
                            absolute_url = urljoin(base_index_url, href)
                            # Ensure it's likely an article URL on mises.org
                            parsed_abs_url = urlparse(absolute_url)
                            if parsed_abs_url.netloc == urlparse(base_index_url).netloc and \
                               any(absolute_url.startswith(sec_url) for sec_url in SECTION_URLS.values()):
                                if absolute_url not in all_article_links:
                                    all_article_links.add(absolute_url)
                                    page_links_found += 1
                else:
                    # Fallback: Find links generally within the main content area
                    # This is less precise and might need adjustment based on site structure
                    main_content = soup.find('main') or soup.find('div', id='content') or soup.body
                    if main_content:
                         for a_tag in main_content.find_all('a', href=True):
                            href = a_tag['href']
                            if not href or href.startswith('#') or 'javascript:' in href or 'rss.xml' in href:
                                continue
                            absolute_url = urljoin(base_index_url, href)
                            parsed_abs_url = urlparse(absolute_url)
                            # Check if it belongs to *any* of the known sections
                            if parsed_abs_url.netloc == urlparse(base_index_url).netloc and \
                               any(absolute_url.startswith(sec_url) for sec_url in SECTION_URLS.values()):
                                if absolute_url not in all_article_links:
                                    all_article_links.add(absolute_url)
                                    page_links_found += 1

                if page_links_found == 0 and page_num > 1: # Don't assume end on page 1 if nothing found
                    logging.info(f"No new article links found on page {page_num} for {section_name}. Assuming end of section pagination.")
                    end_reached = True
                    pbar.total = pages_fetched_this_section # Adjust progress bar total
                    pbar.refresh()
                else:
                    logging.debug(f"Found {page_links_found} new links on page {page_num}. Total unique links: {len(all_article_links)}")

                page_num += 1

                # Add a small delay even if using cache, reduces rapid requests if cache misses
                # time.sleep(FETCH_DELAY / 2)

    logging.info(f"Finished fetching links. Found {len(all_article_links)} unique article URLs across {total_fetched_pages} index pages.")
    return list(all_article_links)


def get_article_metadata(soup, url):
    """
    Extracts metadata (author, date, tags, summary, title, featured_image) from an article's soup object.
    Uses multiple fallback methods for robustness.
    Returns a dictionary.
    """
    metadata = {
        'author': "Mises Institute", # Default author if none found
        'date_str': '',             # Raw date string
        'date_dt': None,            # Parsed datetime object
        'tags': [],
        'summary': "",
        'title': "Untitled Article", # Default title
        'featured_image': None
    }

    try:
        # --- Title ---
        og_title = soup.find('meta', property='og:title')
        h1_title = soup.find('h1', class_=re.compile(r'page-header__title|entry-title|title', re.I))
        meta_title = soup.find('title')

        if og_title and og_title.get('content'):
            metadata['title'] = og_title['content'].strip()
        elif h1_title:
            metadata['title'] = h1_title.get_text(strip=True)
        elif meta_title:
             metadata['title'] = meta_title.get_text(strip=True).split('|')[0].strip() # Often includes site name

        # --- Author ---
        # Look for specific meta tags first
        author_meta_props = ['article:author', 'og:article:author', 'author']
        for prop in author_meta_props:
             meta_tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
             if meta_tag and meta_tag.get('content'):
                 metadata['author'] = meta_tag['content'].strip()
                 break
        else: # If no meta tag found, try common HTML patterns
            # Drupal/Mises specific structure
            details_div = soup.find('div', {"data-component-id": "mises:element-article-details"})
            if details_div:
                profile_link = details_div.find('a', href=re.compile(r'/profile/'))
                if profile_link:
                    metadata['author'] = profile_link.get_text(strip=True)

            # General patterns
            if metadata['author'] == "Mises Institute": # Only if not found yet
                author_link_rel = soup.find('a', rel='author')
                if author_link_rel:
                    metadata['author'] = author_link_rel.get_text(strip=True)
                else:
                    byline = soup.find(class_=re.compile(r'byline|author-name|submitted', re.I))
                    if byline:
                        # Extract text, remove "By ", handle potential links inside
                        author_text = byline.get_text(separator=' ', strip=True)
                        author_text = re.sub(r'^(By|Authored by)\s+', '', author_text, flags=re.IGNORECASE).strip()
                        # Sometimes date is included, try to remove it
                        author_text = re.split(r'\s+on\s+|\s+-\s+', author_text)[0].strip()
                        if author_text:
                             metadata['author'] = author_text

        # Clean up common noise in author field
        metadata['author'] = re.sub(r'\s*\|\s*Mises Institute', '', metadata['author']).strip()


        # --- Date ---
        date_str = None
        date_meta_props = ['article:published_time', 'og:article:published_time', 'datePublished', 'dcterms.date']
        for prop in date_meta_props:
            meta_tag = soup.find('meta', property=prop) or soup.find('meta', itemprop=prop) or soup.find('meta', attrs={'name':prop})
            if meta_tag and meta_tag.get('content'):
                date_str = meta_tag['content'].strip()
                break
        else: # Fallback to <time> tag or visible date elements
            time_tag = soup.find('time', datetime=True)
            if time_tag and time_tag.get('datetime'):
                date_str = time_tag['datetime'].strip()
            elif time_tag:
                 date_str = time_tag.get_text(strip=True)
            else:
                # Look for common date display classes
                date_span = soup.find(class_=re.compile(r'date|published|submitted|timestamp', re.I))
                if date_span:
                    # Extract text, handle potential nested elements
                    possible_date_text = date_span.get_text(strip=True)
                    # Basic check to see if it looks like a date
                    if re.search(r'\d{1,2}/\d{1,2}/\d{2,4}|\w+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}', possible_date_text):
                        date_str = possible_date_text

        if date_str:
            metadata['date_str'] = date_str
            metadata['date_dt'] = parse_date_flexible(date_str)

        # --- Tags ---
        tags = set()
        tag_meta_props = ['article:tag', 'keywords']
        for prop in tag_meta_props:
             meta_tags = soup.find_all('meta', property=prop) or soup.find_all('meta', attrs={'name': prop})
             for tag in meta_tags:
                 content = tag.get('content')
                 if content:
                     # Keywords often comma-separated
                     tags.update(t.strip() for t in content.split(',') if t.strip())

        # Look for tag links
        tag_links = soup.find_all('a', rel='tag') or \
                    soup.find_all('a', href=re.compile(r'/topics/|/tags/'))
        for link in tag_links:
            tag_text = link.get_text(strip=True)
            if tag_text:
                tags.add(tag_text)

        # Look in specific container divs
        tag_containers = soup.find_all(class_=re.compile(r'tags|taxonomy|field-name-field-tags', re.I))
        for container in tag_containers:
            links = container.find_all('a')
            for link in links:
                 tag_text = link.get_text(strip=True)
                 if tag_text:
                     tags.add(tag_text)

        metadata['tags'] = sorted(list(tags))


        # --- Summary ---
        summary = None
        og_desc = soup.find('meta', property='og:description')
        meta_desc = soup.find('meta', attrs={'name': 'description'})

        if og_desc and og_desc.get('content'):
            summary = og_desc['content'].strip()
        elif meta_desc and meta_desc.get('content'):
            summary = meta_desc['content'].strip()
        else: # Fallback: Try the first paragraph if no meta description
            # Find a likely content container
            content_div = soup.find('div', class_=re.compile(r'content|entry|post-entry', re.I)) or \
                          soup.find('article')
            if content_div:
                first_p = content_div.find('p')
                if first_p:
                    summary_text = first_p.get_text(strip=True)
                    # Basic check to avoid overly short/non-prose paragraphs
                    if len(summary_text) > 50 and '.' in summary_text:
                        summary = summary_text

        metadata['summary'] = summary if summary else ""


        # --- Featured Image ---
        img_url = None
        og_image = soup.find('meta', property='og:image')
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})

        if og_image and og_image.get('content'):
            img_url = og_image['content']
        elif twitter_image and twitter_image.get('content'):
            img_url = twitter_image['content']
        else: # Fallback: Look for common image structures
            # Drupal pattern
            img_figure = soup.find('figure', class_=re.compile(r'figure|post-thumbnail|featured-image', re.I))
            if img_figure:
                 img_tag = img_figure.find('img', src=True)
                 if img_tag:
                     img_url = img_tag['src']
            else: # Look for image directly within header/top of article
                 header = soup.find('header') or soup.find('div', class_='article-header')
                 if header:
                      img_tag = header.find('img', src=True)
                      if img_tag:
                           img_url = img_tag['src']

        if img_url:
            cleaned_img_url = urljoin(url, clean_image_url(img_url))
            if not should_ignore_image_url(cleaned_img_url):
                metadata['featured_image'] = cleaned_img_url
            else:
                 logging.debug(f"Ignoring featured image for {url}: {cleaned_img_url}")


    except Exception as e:
        logging.error(f"Error extracting metadata from {url}: {e}", exc_info=True)
        # Keep defaults if extraction fails

    # Final check for title (important)
    if not metadata['title'] or metadata['title'] == "Untitled Article":
        title_tag = soup.find('title')
        if title_tag:
             metadata['title'] = title_tag.get_text(strip=True).split('|')[0].strip()

    return metadata


def manual_extraction_fallback(soup, url):
    """
    A fallback extraction method if readability fails or yields poor results.
    Attempts to extract content directly from common article container elements.
    Returns (title, html_content)
    """
    logging.warning(f"Attempting manual extraction fallback for {url}")
    title = "Untitled Article (Fallback Extraction)"
    content_html = "<p>Content extraction failed using fallback method.</p>"

    try:
        # Try to find title again, as readability might have failed before metadata
        h1_title = soup.find('h1', class_=re.compile(r'page-header__title|entry-title|title', re.I))
        if h1_title:
            title = h1_title.get_text(strip=True)
        else:
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title['content'].strip()
            else:
                title_tag = soup.find('title')
                if title_tag:
                     title = title_tag.get_text(strip=True).split('|')[0].strip()


        # Find potential content containers
        content_selectors = [
            'div.article--full__content', # Specific to Mises?
            'div.field--name-body',       # Common Drupal field
            'div.post-entry',
            'div.entry-content',
            'article.node',
            'article',
            'div#content',
            'main#main-content',
            'div.content',
            'div.main'
        ]
        content_element = None
        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                logging.debug(f"Manual extraction found content container: {selector}")
                break

        if content_element:
            # Remove common unwanted elements (ads, related posts, comments, etc.)
            selectors_to_remove = [
                '.social-share', '.social-links', '.related-posts', '.jp-relatedposts',
                '.comments', '#comments', '.comment-respond', 'div.tags', '.post-tags',
                '.author-box', '.article-footer', '.breadcrumb', 'nav', 'script', 'style',
                'aside', 'form', '.newsletter', '.sidebar', '.advertisement', '.ad-container'
            ]
            for sel in selectors_to_remove:
                for unwanted in content_element.select(sel):
                    if unwanted:
                        unwanted.decompose()

            # Basic cleaning: remove empty paragraphs, excessive line breaks
            for p in content_element.find_all('p'):
                if not p.get_text(strip=True) and not p.find('img'):
                     p.decompose()

            # Convert the cleaned container to string
            content_html = str(content_element)

            # Very basic check if content seems reasonable
            if len(content_html) < 200 or content_html.count('<p>') < 2:
                logging.warning(f"Manual extraction for {url} yielded very short content. May be incomplete.")

        else:
            logging.warning(f"Manual extraction: Could not find a suitable content container for {url}.")
            # As a last resort, try using the whole body, but this is risky
            # content_html = str(soup.body) if soup.body else ""
            # Let's stick to the failure message if no container found

        # Wrap in basic article structure
        cleaned_html_fallback = f"<article>{content_html}</article>"
        return title, cleaned_html_fallback

    except Exception as e:
        logging.error(f"Manual extraction fallback failed severely for {url}: {e}", exc_info=True)
        return title, f"<article><p>Content extraction failed due to an error: {e}</p></article>"


def download_image(image_url):
    """
    Downloads an image from a URL and returns it as a BytesIO object.
    Uses fetch_with_retry for robustness. Returns None on failure or if ignored.
    """
    image_url = clean_image_url(image_url) # Clean before checking

    if not image_url or not is_valid_url(image_url):
        logging.debug(f"Invalid or missing image URL: '{image_url}'")
        return None

    if should_ignore_image_url(image_url):
        # Logging is handled within should_ignore_image_url
        return None

    logging.debug(f"Downloading image: {image_url}")
    response = fetch_with_retry(image_url, stream=True)

    if response and response.status_code == 200:
         # Check content type to be more certain it's an image
         content_type = response.headers.get('Content-Type', '').lower()
         if 'image' in content_type:
             try:
                 # Read into memory
                 img_data = BytesIO(response.content)
                 img_data.seek(0) # Reset stream position
                 return img_data
             except Exception as e:
                 logging.error(f"Error reading image data from {image_url}: {e}")
                 return None
         else:
              logging.warning(f"URL {image_url} did not return an image content type ({content_type}). Skipping.")
              return None
    else:
        # Error logged by fetch_with_retry
        return None


def is_valid_image(img_data):
    """Checks if the BytesIO object contains a valid, non-trivial image."""
    if not img_data:
        return False, None, None
    try:
        img_data.seek(0)
        img = Image.open(img_data)
        img.verify() # Verify core image structure
        # Reload after verify
        img_data.seek(0)
        img = Image.open(img_data)

        # Basic checks for size (skip tiny icons/spacers)
        min_dim = 50
        if img.width < min_dim or img.height < min_dim:
            logging.debug(f"Skipping small image ({img.width}x{img.height}).")
            return False, None, None

        # Check format support
        img_format = img.format.lower() if img.format else None
        supported_formats = ['jpeg', 'jpg', 'png', 'gif', 'webp']
        if img_format not in supported_formats:
            # Try to infer format if missing (e.g., from data URI)
            if img.mode == 'RGBA': img_format = 'png'
            elif img.mode == 'RGB': img_format = 'jpeg'
            else: # Fallback if mode doesn't help
                logging.warning(f"Unsupported or unknown image format: {img.format}. Skipping.")
                return False, None, None

        # Ensure format is one of the common types for EPUB
        if img_format == 'jpg': img_format = 'jpeg'

        img_data.seek(0) # Reset for later use
        return True, img_data, img_format
    except (IOError, SyntaxError, ValueError, TypeError, Image.UnidentifiedImageError) as e:
        logging.warning(f"Invalid or corrupt image data: {e}")
        return False, None, None


def process_image(img_url_or_data, base_url, processed_images_cache):
    """
    Processes an image URL or data URI. Downloads if necessary, validates,
    generates a filename, and checks cache.
    Returns (epub_image_item, image_filename) or (None, None)
    """
    img_data = None
    img_src_identifier = None # URL or hash of data URI

    if isinstance(img_url_or_data, str) and img_url_or_data.startswith('data:'):
        # --- Handle Data URI ---
        try:
            img_src_identifier = hashlib.md5(img_url_or_data.encode()).hexdigest()
            if img_src_identifier in processed_images_cache:
                 logging.debug("Image (data URI) found in cache.")
                 return None, processed_images_cache[img_src_identifier] # Return cached filename

            header, encoded = img_url_or_data.split(",", 1)
            img_format = header.split(';')[0].split('/')[-1].lower()
            if img_format not in ['jpeg', 'jpg', 'png', 'gif', 'webp']:
                logging.warning(f"Unsupported image format in data URI ({img_format}). Skipping.")
                return None, None
            if img_format == 'jpg': img_format = 'jpeg'

            img_bytes = base64.b64decode(encoded)
            img_data = BytesIO(img_bytes)

            # Generate filename based on content hash
            content_hash = hashlib.md5(img_bytes).hexdigest()[:10]
            img_file_name = f'image_{content_hash}.{img_format}'

        except Exception as e:
            logging.error(f"Error processing data URI in {base_url}: {e}")
            return None, None
    else:
        # --- Handle URL ---
        img_url = clean_image_url(img_url_or_data)
        img_url = urljoin(base_url, img_url) # Ensure absolute URL
        img_src_identifier = img_url

        if img_src_identifier in processed_images_cache:
            logging.debug(f"Image URL found in cache: {img_url}")
            return None, processed_images_cache[img_src_identifier] # Return cached filename

        if should_ignore_image_url(img_url):
            return None, None

        img_data = download_image(img_url)
        if not img_data:
             return None, None # Download failed or skipped

        # Generate filename based on URL hash (or could use content hash)
        url_hash = hashlib.md5(img_url.encode()).hexdigest()[:10]
        # Try to get extension from URL first
        path = urlparse(img_url).path
        ext = os.path.splitext(path)[1].lower().strip('.')
        if ext not in ['jpeg', 'jpg', 'png', 'gif', 'webp']:
             ext = None # Will determine from image data later

    # --- Validate and Create EpubItem ---
    is_valid, valid_img_data, img_format = is_valid_image(img_data)

    if not is_valid or not valid_img_data or not img_format:
        return None, None

    # If extension wasn't determined from URL, use the validated format
    if ext is None:
        ext = img_format

    # Refine filename if needed
    if 'img_file_name' not in locals(): # If wasn't a data URI
         img_file_name = f'image_{url_hash}.{ext}'

    # Create EPUB item
    epub_image = epub.EpubImage()
    # Use a subdirectory for images
    epub_image.file_name = f'images/{img_file_name}'
    epub_image.media_type = f'image/{img_format}'
    epub_image.content = valid_img_data.getvalue()

    # Add to cache before returning
    processed_images_cache[img_src_identifier] = img_file_name
    logging.debug(f"Processed image: {img_src_identifier} -> {img_file_name}")

    return epub_image, img_file_name

# --- Main Article Processing ---
# Flag to signal exit
exit_flag = False

def signal_handler(sig, frame):
    global exit_flag
    logging.warning(f"Signal {sig} received. Requesting graceful shutdown...")
    print(f"\nSignal {sig} received. Requesting graceful shutdown... (finish current tasks)")
    exit_flag = True

def process_article(url, download_images=True, start_date=None, end_date=None):
    """
    Downloads, parses, extracts content, processes images, and filters by date for a single article.
    Returns (title, chapter, metadata, image_items) or (None, None, None, []) on failure or filter.
    """
    global exit_flag
    if exit_flag:
        logging.info(f"Skipping {url} due to shutdown request.")
        return None, None, None, []

    logging.info(f"Processing article: {url}")
    processed_images_cache = {} # Cache for images within this article {src: filename}
    image_items_for_chapter = []

    response = fetch_with_retry(url)
    if not response:
        return None, None, None, [] # Error already logged

    soup = BeautifulSoup(response.text, 'html.parser')
    metadata = get_article_metadata(soup, url)

    # --- Date Filtering ---
    article_date = metadata.get('date_dt')
    if article_date:
        if start_date and article_date < start_date:
            logging.info(f"Skipping article (published {article_date.date()} before start date {start_date.date()}): {url}")
            return None, None, None, []
        if end_date and article_date > end_date:
             logging.info(f"Skipping article (published {article_date.date()} after end date {end_date.date()}): {url}")
             return None, None, None, []
    elif start_date or end_date:
        # If filtering by date, but we couldn't parse the date, skip it
        logging.warning(f"Skipping article (date filtering active, but could not parse date '{metadata.get('date_str')}'): {url}")
        return None, None, None, []

    # --- Content Extraction ---
    title = metadata['title'] # Use metadata title as primary
    try:
        # Use Readability to get main content
        doc = Document(response.text)
        # Prefer metadata title, but use readability's as fallback
        title = title or doc.short_title() or "Untitled"
        cleaned_html = doc.summary()
        # Check if readability content is substantial enough
        if not cleaned_html or len(cleaned_html) < 200 or cleaned_html.count('<p>') < 1:
            raise ValueError(f"Readability content too short ({len(cleaned_html)} chars)")
        logging.debug(f"Readability extraction successful for {url}")
    except Exception as e:
        logging.warning(f"Readability extraction failed or yielded poor content for {url}: {e}")
        # Attempt fallback manual extraction
        title, cleaned_html = manual_extraction_fallback(soup, url)
        if "Content extraction failed" in cleaned_html:
             logging.error(f"Both Readability and manual extraction failed for: {url}")
             return None, None, None, [] # Give up on this article

    # --- Image Processing ---
    cleaned_soup = BeautifulSoup(cleaned_html, 'html.parser')
    featured_image_html = ""

    if download_images:
        # 1. Process Featured Image (if exists and not already ignored)
        if metadata.get('featured_image'):
            epub_img_item, img_filename = process_image(metadata['featured_image'], url, processed_images_cache)
            if epub_img_item and img_filename:
                 image_items_for_chapter.append(epub_img_item)
                 # Prepend featured image to content
                 featured_image_html = f'<figure class="featured-image"><img src="images/{img_filename}" alt="{title}" /></figure>\n'
                 logging.debug(f"Added featured image for {url}")

        # 2. Process Images within the extracted content (Readability/Manual)
        for img_tag in cleaned_soup.find_all('img', src=True):
            img_src = img_tag['src']

            # Skip placeholder/empty srcs
            if not img_src or img_src.startswith('data:image/gif;base64,R0lGODlh'): # Common spacer gif
                 img_tag.decompose() # Remove the tag entirely
                 continue

            epub_img_item, img_filename = process_image(img_src, url, processed_images_cache)

            if epub_img_item and img_filename:
                # Add the image item to the list for the EPUB manifest
                image_items_for_chapter.append(epub_img_item)
                # Update the img tag's src to the local path
                img_tag['src'] = f'images/{img_filename}'
                # Remove potentially problematic attributes
                for attr in ['srcset', 'sizes', 'loading', 'decoding', 'data-src', 'data-srcset', 'lowsrc', 'longdesc', 'style']:
                     if attr in img_tag.attrs:
                         del img_tag.attrs[attr]
                # Ensure alt text exists
                if not img_tag.get('alt'):
                    img_tag['alt'] = "Image" # Generic alt text
            else:
                 # If image failed processing or was skipped, remove the tag from content
                 logging.debug(f"Removing img tag for failed/skipped src: {img_src[:100]}...")
                 img_tag.decompose()

    # --- Assemble Final Chapter HTML ---
    header_html = f"<h1>{title}</h1>\n"
    if metadata.get('author'):
        header_html += f"<p class='author'>By {metadata['author']}</p>\n"
    if article_date: # Use the parsed datetime object for consistent formatting
        try:
            formatted_date = article_date.strftime("%B %d, %Y")
            header_html += f"<p class='date'>Published: {formatted_date}</p>\n"
        except ValueError: # Handle potential errors with strftime for very old/weird dates
             header_html += f"<p class='date'>Published: {metadata['date_str']}</p>\n" # Fallback to raw string
    elif metadata.get('date_str'): # If parsing failed but we have the string
        header_html += f"<p class='date'>Published: {metadata['date_str']}</p>\n"

    if metadata.get('summary'):
        header_html += f"<hr class='meta-sep'/>\n<p class='summary'><em>{metadata['summary']}</em></p>\n<hr class='meta-sep'/>\n"
    if metadata.get('tags'):
        tags_html = ', '.join(metadata['tags'])
        header_html += f"<p class='tags'>Tags: {tags_html}</p>\n"

    footer_html = f"<hr class='source-sep'/>\n<p class='source'>Original URL: <a href='{url}'>{url}</a></p>\n"

    # Combine all parts
    final_html = featured_image_html + header_html + str(cleaned_soup) + footer_html

    # Create EpubHtml object
    chapter_filename = sanitize_filename(title) + '.xhtml'
    chapter = epub.EpubHtml(title=title, file_name=chapter_filename, lang='en')
    chapter.content = final_html # Assign string content, ebooklib handles encoding
    chapter.id = sanitize_filename(title).replace(".", "_")[:50] # Make ID safe and reasonably short

    # Link CSS
    chapter.add_link(href='style/style.css', rel='stylesheet', type='text/css')

    logging.info(f"Successfully processed: {title} ({url})")
    return title, chapter, metadata, image_items_for_chapter

# --- EPUB Creation ---

def create_epub(chapters_data, save_dir, epub_filename_base, included_sections, cover_path=None, author="Mises Institute", language='en'):
    """
    Create an EPUB file from a list of processed chapter data.
    chapters_data format: list of tuples [(title, chapter, metadata, image_items), ...]
    """
    if not chapters_data:
        logging.error("No chapters provided to create_epub. EPUB creation aborted.")
        return None

    book = epub.EpubBook()

    # --- Metadata ---
    epub_title = f"{epub_filename_base}"
    if len(chapters_data) > 1:
        # Try to get date range
        try:
            # Sort by date for range calculation (use None dates as earliest)
            chapters_data.sort(key=lambda x: x[2].get('date_dt') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            first_date = chapters_data[0][2].get('date_dt')
            last_date = chapters_data[-1][2].get('date_dt')
            if first_date and last_date and first_date.year == last_date.year:
                epub_title += f" ({first_date.year})"
            elif first_date and last_date:
                epub_title += f" ({last_date.strftime('%Y-%m')} to {first_date.strftime('%Y-%m')})"
        except Exception as e:
            logging.warning(f"Could not determine date range for title: {e}")
            # Use number of articles if date range fails
            epub_title += f" ({len(chapters_data)} Articles)"
    elif len(chapters_data) == 1:
         epub_title = chapters_data[0][0] # Use article title for single article epub


    book.set_title(epub_title)
    book.add_author(author)
    book.set_language(language)

    # Unique Identifier
    uid_hash = hashlib.md5(epub_title.encode()).hexdigest()[:16]
    book_id = f"urn:uuid:mises-epubgen-{uid_hash}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    book.set_identifier(book_id)

    book.add_metadata('DC', 'publisher', 'Mises Institute (via mises-epub-generator)')
    book.add_metadata('DC', 'date', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')) # ISO 8601 format
    book.add_metadata('DC', 'source', 'https://mises.org')
    book.add_metadata('DC', 'subject', f"Economics, Libertarianism, Austrian School, Politics, {' '.join(included_sections)}")
    generator_meta = epub.EpubItem(uid="generator_meta", file_name="misc/generator.xhtml", media_type="application/xhtml+xml", content=b"") # Dummy item
    generator_meta.add_meta(name='generator', value='mises-epub-generator v1.0')
    book.add_item(generator_meta)

    # --- Cover ---
    cover_item = None
    if cover_path and os.path.exists(cover_path):
        try:
            with open(cover_path, 'rb') as f:
                cover_content = f.read()
            # Basic validation and potential resizing
            img = Image.open(BytesIO(cover_content))
            img.verify()
            cover_content = BytesIO(cover_content) # Re-open after verify
            img = Image.open(cover_content)
            max_cover_dim = 2400
            if img.width > max_cover_dim or img.height > max_cover_dim:
                logging.info(f"Resizing large cover image ({img.width}x{img.height}) to max {max_cover_dim}px dimension.")
                img.thumbnail((max_cover_dim, max_cover_dim))
                img_buffer = BytesIO()
                img_format = img.format or 'JPEG' # Default to JPEG if format unknown
                img.save(img_buffer, format=img_format)
                cover_content = img_buffer.getvalue()
            else:
                 cover_content = cover_content.getvalue() # Use original if within limits

            ext = os.path.splitext(cover_path)[1].lower() or '.jpeg' # Default ext
            cover_format = ext.strip('.')
            if cover_format == 'jpg': cover_format = 'jpeg'
            cover_mimetype = f'image/{cover_format}'
            cover_file_name = f'images/cover{ext}'

            book.set_cover(cover_file_name, cover_content, create_page=False) # create_page=False recommended
            cover_item = book.get_item_with_href(cover_file_name) # Get the item to add properties
            if cover_item:
                 cover_item.properties.append('cover-image') # Explicitly set property for some readers
            logging.info(f"Added cover image: {cover_path}")

        except (IOError, SyntaxError, Image.UnidentifiedImageError, FileNotFoundError) as e:
            logging.error(f"Error processing cover image '{cover_path}': {e}. Skipping cover.")
            cover_item = None # Ensure cover_item is None if it failed
        except Exception as e:
             logging.error(f"Unexpected error adding cover image: {e}", exc_info=True)
             cover_item = None
    else:
        if cover_path: # Log if path provided but not found
             logging.warning(f"Cover image path specified but not found: {cover_path}")


    # --- Introduction / About Page ---
    intro_title = "About This Collection"
    intro_content = f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{language}">
<head>
    <title>{intro_title}</title>
    <link href="style/style.css" rel="stylesheet" type="text/css"/>
</head>
<body>
    <h1>{epub_title}</h1>
    <hr/>
    <p>This EPUB contains a collection of {len(chapters_data)} articles, generated on {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M %Z')}.</p>
    <p>Source Sections: {', '.join(included_sections)}</p>
    <p>Source Website: <a href="https://mises.org">Mises.org</a></p>
    <p>Generated by: <a href="https://github.com/example/mises-epub-generator">mises-epub-generator</a> (Example link)</p>
    <p><em>Note: Formatting and content extraction are automated and may contain imperfections. Refer to the original URLs linked at the end of each article for the definitive source.</em></p>
</body>
</html>
"""
    intro_chapter = epub.EpubHtml(title=intro_title, file_name='nav/intro.xhtml', lang=language)
    intro_chapter.content = intro_content
    book.add_item(intro_chapter)


    # --- Chapters and Images ---
    # Sort chapters by date (most recent first), handling potential None dates
    try:
         chapters_data.sort(key=lambda x: x[2].get('date_dt') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
         logging.info("Chapters sorted by publication date (most recent first).")
    except Exception as e:
         logging.warning(f"Failed to sort chapters by date: {e}. Using processing order.")

    toc = []
    spine = []
    # Add cover page to spine if it exists and is HTML page (some readers need this)
    # cover_html_page = book.get_item_with_id('cover') # Check if set_cover created an HTML page
    # if cover_html_page:
    #     spine.append('cover') # Add the ID string 'cover'
    # elif cover_item:
    #      spine.append(cover_item) # Try adding the image item itself (less common)

    # Add Intro page
    spine.append(intro_chapter)
    toc.append(epub.Link(intro_chapter.file_name, intro_title, 'intro'))

    # Keep track of unique image items added to the book manifest
    all_unique_image_items = {} # {filename: item}

    for i, (title, chapter, metadata, image_items) in enumerate(chapters_data):
        chapter.id = f"chap_{i+1}_{chapter.id}" # Ensure unique chapter ID
        chapter.file_name = f"chapters/{chapter.file_name}" # Put chapters in subdirectory

        logging.debug(f"Adding chapter {i+1}: {title} ({chapter.file_name})")
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, title, chapter.id))

        # Add unique images from this chapter to the book manifest
        for img_item in image_items:
            if img_item.file_name not in all_unique_image_items:
                all_unique_image_items[img_item.file_name] = img_item
                book.add_item(img_item)
            #else:
                #logging.debug(f"Image already added: {img_item.file_name}")


    # --- NCX (Table of Contents - EPUB 2) ---
    book.toc = tuple(toc)

    # --- Nav Document (Table of Contents - EPUB 3) ---
    nav_doc = epub.EpubNav(file_name='nav/nav.xhtml', uid='nav') # Place in nav subdir
    nav_doc.add_link(href='style/style.css', rel='stylesheet', type='text/css') # Link CSS
    book.add_item(nav_doc)

    # --- Spine ---
    # Define spine order: Cover(optional), Intro, Chapters, Nav
    # spine = ['cover'] + [intro_chapter] + [ch[1] for ch in chapters_data] # If cover generates page
    spine = [intro_chapter] + [ch[1] for ch in chapters_data] # Spine contains chapter items
    # Add Nav and NCX items (required by spec)
    book.spine = ['nav'] + spine # Add 'nav' page first (standard practice), then intro, then chapters
    book.add_item(epub.EpubNcx())


    # --- CSS Styling ---
    css_content = """
/* EPUB CSS Reset and Basic Styling */
html, body, div, span, h1, h2, h3, h4, h5, h6, p, blockquote, pre, a, img, ol, ul, li, figure, figcaption, footer, header, nav, section {
    margin: 0;
    padding: 0;
    border: 0;
    font: inherit;
    vertical-align: baseline;
}
body {
    font-family: "Georgia", serif; /* Serif for readability */
    line-height: 1.6;
    margin: 5% 5%; /* Margins for reading area */
    widows: 2; /* Prevent single lines at top/bottom of pages */
    orphans: 2;
    font-size: 1em; /* Base font size */
    color: #333;
}

/* Headings */
h1, h2, h3, h4, h5, h6 {
    font-family: "Helvetica Neue", "Arial", sans-serif; /* Sans-serif for headings */
    font-weight: bold;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
    line-height: 1.2;
    page-break-after: avoid; /* Keep headings with following content */
}
h1 { font-size: 2em; margin-top: 0; border-bottom: 1px solid #ddd; padding-bottom: 0.3em; }
h2 { font-size: 1.6em; }
h3 { font-size: 1.3em; }
h4 { font-size: 1.1em; font-style: italic; }

/* Paragraphs */
p {
    margin-bottom: 1em;
    text-align: justify; /* Justify text for book-like feel */
    hyphens: auto; /* Enable hyphenation if supported */
}

/* Links */
a {
    color: #0056b3; /* Standard link blue */
    text-decoration: none; /* No underlines by default */
}
a:hover, a:focus {
    text-decoration: underline;
}

/* Images and Figures */
img {
    max-width: 100%;
    height: auto;
    display: block; /* Prevent extra space below images */
    margin: 1em auto; /* Center images */
}
figure {
    margin: 1.5em 0;
    page-break-inside: avoid; /* Try to keep figure and caption together */
}
figcaption {
    font-size: 0.9em;
    font-style: italic;
    text-align: center;
    margin-top: 0.5em;
    color: #555;
}
figure.featured-image {
    margin-top: 0; /* Less top margin for featured image */
    margin-bottom: 1.5em;
}

/* Blockquotes */
blockquote {
    margin: 1.5em 2em;
    padding-left: 1.5em;
    border-left: 3px solid #ccc;
    font-style: italic;
    color: #555;
}
blockquote p {
    margin-bottom: 0.5em;
}

/* Lists */
ul, ol {
    margin: 1em 0 1em 2em; /* Indent lists */
}
li {
    margin-bottom: 0.5em;
}

/* Metadata Styles */
.author, .date, .tags, .summary, .source {
    font-family: "Helvetica Neue", "Arial", sans-serif;
    font-size: 0.9em;
    color: #666;
    margin-bottom: 0.5em;
    text-align: left; /* Align metadata left */
    hyphens: none;
}
.author { font-weight: bold; }
.summary { font-style: italic; margin: 1em 0; padding: 0.5em 0; border-top: 1px dashed #eee; border-bottom: 1px dashed #eee; }
.tags { font-size: 0.8em; }
.source { font-size: 0.8em; margin-top: 2em; padding-top: 1em; border-top: 1px solid #ddd; }
.source a { word-break: break-all; } /* Break long URLs */

/* Separators */
hr {
    border: 0;
    height: 1px;
    background-color: #eee;
    margin: 2em 0;
}
hr.meta-sep { margin: 0.5em 0; background-color: #f5f5f5; }
hr.source-sep { margin: 1.5em 0; }

/* Intro page specific */
body#intro-page h1 { text-align: center; border-bottom: none; }
body#intro-page p { text-align: left; }
    """
    style_item = epub.EpubItem(
        uid="style_main",
        file_name="style/style.css",
        media_type="text/css",
        content=css_content
    )
    book.add_item(style_item)

    # --- Write EPUB File ---
    safe_title = sanitize_filename(epub_filename_base)
    os.makedirs(save_dir, exist_ok=True)
    final_filename = os.path.join(save_dir, safe_title + '.epub')

    logging.info(f"Writing EPUB file: {final_filename}")
    try:
        epub.write_epub(final_filename, book, {'epub3_pages': True, 'toc_depth': 2})
        logging.info(f"Successfully created EPUB: {final_filename}")
        return final_filename
    except Exception as e:
        logging.error(f"Failed to write EPUB file '{final_filename}': {e}", exc_info=True)
        return None

# --- Main Execution ---

def main():
    global PROXIES, VERIFY_SSL, REQUEST_TIMEOUT, FETCH_DELAY, RETRY_COUNT, RETRY_BACKOFF, USE_CACHE, CACHE_DIR, exit_flag

    # Setup signal handling for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler) # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # kill

    parser = argparse.ArgumentParser(
        description='Generate EPUB collections from Mises.org articles (Wire, Power & Market).',
        formatter_class=argparse.RawTextHelpFormatter
    )

    # --- Source Selection ---
    source_group = parser.add_argument_group('Article Source Options')
    source_group.add_argument('--include', type=str, default='wire',
                              help='Sections to include, separated by "+".\n'
                                   f'Available: {", ".join(SECTION_URLS.keys())}\n'
                                   'Example: --include wire+powermarket (default: wire)')
    source_group.add_argument('--url', type=str, help='URL of a single specific article to convert.')
    source_group.add_argument('--input-file', type=str, metavar='FILE',
                              help='Path to a text file containing one article URL per line.')
    source_group.add_argument('--all-pages', action='store_true',
                              help='Attempt to fetch all available pages from index (overrides --pages).')
    source_group.add_argument('--pages', type=int, default=50, metavar='N',
                              help='Number of index pages per section to check (default: 50). Use --all-pages for unlimited.')
    source_group.add_argument('--max-articles', type=int, default=None, metavar='N',
                              help='Maximum total number of articles to process.')

    # --- Filtering ---
    filter_group = parser.add_argument_group('Filtering Options')
    filter_group.add_argument('--start-date', type=parse_date_arg, metavar='YYYY-MM-DD',
                              help='Only include articles published on or after this date.')
    filter_group.add_argument('--end-date', type=parse_date_arg, metavar='YYYY-MM-DD',
                               help='Only include articles published on or before this date.')

    # --- Output Configuration ---
    output_group = parser.add_argument_group('Output Options')
    output_group.add_argument('--save-dir', type=str, default="./mises_epub", metavar='DIR',
                              help='Directory to save the EPUB file(s) (default: ./mises_epub).')
    output_group.add_argument('--epub-title', type=str, default=None, metavar='TITLE',
                              help='Custom base title for the EPUB file. \n'
                                   '(Default: generated from included sections/date range)')
    output_group.add_argument('--split', type=int, default=None, metavar='N',
                              help='Split into multiple EPUBs with approx. N articles each.')
    output_group.add_argument('--cover', type=str, default=None, metavar='PATH',
                              help='Path to a local cover image (JPEG, PNG, GIF, WebP).')
    output_group.add_argument('--skip-images', action='store_true', help='Do not download or include any images.')

    # --- Network & Performance ---
    network_group = parser.add_argument_group('Network and Performance Options')
    network_group.add_argument('--threads', type=int, default=4, metavar='N',
                               help='Number of parallel threads for processing articles (default: 4).')
    network_group.add_argument('--timeout', type=int, default=REQUEST_TIMEOUT, metavar='SEC',
                               help=f'HTTP request timeout in seconds (default: {REQUEST_TIMEOUT}).')
    network_group.add_argument('--delay', type=float, default=FETCH_DELAY, metavar='SEC',
                               help=f'Delay between HTTP requests in seconds (default: {FETCH_DELAY}).')
    network_group.add_argument('--retries', type=int, default=RETRY_COUNT, metavar='N',
                               help=f'Number of retries for failed HTTP requests (default: {RETRY_COUNT}).')
    network_group.add_argument('--proxy', type=str, default=None, metavar='URL',
                               help='Proxy URL (e.g., http://user:pass@host:port).')
    network_group.add_argument('--no-ssl-verify', action='store_true', help='Disable SSL certificate verification (use with caution!).')
    network_group.add_argument('--cache', action='store_true', help='Enable simple file caching for fetched URLs.')
    network_group.add_argument('--clear-cache', action='store_true', help='Clear the cache directory before starting.')

    # --- Logging & Debugging ---
    log_group = parser.add_argument_group('Logging and Debugging')
    log_group.add_argument('--log', type=str, default='info', choices=['debug', 'info', 'warning', 'error', 'critical'],
                           help='Set logging level (default: info).')
    log_group.add_argument('--log-file', type=str, default='mises_epub_generator.log', metavar='FILE',
                           help='File to write logs to (default: mises_epub_generator.log).')

    args = parser.parse_args()

    # --- Setup Logging ---
    log_level = getattr(logging, args.log.upper())
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s')
    log_handlers = []

    # File Handler
    try:
        file_handler = logging.FileHandler(args.log_file, mode='w', encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        log_handlers.append(file_handler)
    except Exception as e:
        print(f"Error setting up log file '{args.log_file}': {e}. Logging to console only.")

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    log_handlers.append(console_handler)

    logging.basicConfig(level=log_level, handlers=log_handlers)

    # Mute libraries that are too verbose at DEBUG level
    if log_level == logging.DEBUG:
         logging.getLogger("urllib3").setLevel(logging.INFO)
         logging.getLogger("requests").setLevel(logging.INFO)
         logging.getLogger("PIL").setLevel(logging.INFO)

    logging.info("--- Mises EPUB Generator Started ---")
    logging.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logging.info(f"Arguments: {vars(args)}")

    # --- Apply Global Configurations ---
    REQUEST_TIMEOUT = args.timeout
    FETCH_DELAY = args.delay
    RETRY_COUNT = args.retries
    USE_CACHE = args.cache
    if args.proxy:
        PROXIES = {"http": args.proxy, "https": args.proxy}
        logging.info(f"Using proxy: {args.proxy}")
    if args.no_ssl_verify:
        VERIFY_SSL = False
        logging.warning("SSL certificate verification is DISABLED.")
        # Disable urllib3 warnings about insecure requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    else:
        # Ensure certifi path is valid
        try:
             if not os.path.exists(certifi.where()):
                  raise FileNotFoundError("Certifi CA bundle not found.")
             VERIFY_SSL = certifi.where()
             logging.debug(f"Using SSL CA bundle: {VERIFY_SSL}")
        except Exception as e:
             logging.error(f"Error setting SSL verification path: {e}. Disabling SSL verification.")
             VERIFY_SSL = False


    # --- Cache Management ---
    if USE_CACHE:
        CACHE_DIR = os.path.abspath(CACHE_DIR)
        logging.info(f"Using cache directory: {CACHE_DIR}")
        if args.clear_cache:
            if os.path.exists(CACHE_DIR):
                try:
                    import shutil
                    shutil.rmtree(CACHE_DIR)
                    logging.info("Cache directory cleared.")
                except Exception as e:
                    logging.error(f"Failed to clear cache directory: {e}")
            else:
                 logging.info("Cache directory does not exist, nothing to clear.")
        os.makedirs(CACHE_DIR, exist_ok=True)


    # --- Determine Article URLs to Process ---
    article_links_to_process = []
    included_sections = []

    if args.url:
        logging.info(f"Processing single URL: {args.url}")
        if is_valid_url(args.url):
            article_links_to_process.append(args.url)
            # Try to guess section for title generation
            parsed_url_path = urlparse(args.url).path
            for name, sec_url in SECTION_URLS.items():
                 if parsed_url_path.startswith(urlparse(sec_url).path):
                      included_sections.append(name)
                      break
            if not included_sections: included_sections.append("Single Article")
        else:
            logging.error(f"Invalid URL provided with --url: {args.url}")
            sys.exit(1)
    elif args.input_file:
        logging.info(f"Processing URLs from input file: {args.input_file}")
        try:
            with open(args.input_file, 'r', encoding='utf-8') as f:
                for line in f:
                    url = line.strip()
                    if url and not url.startswith('#') and is_valid_url(url):
                         article_links_to_process.append(url)
                    elif url and not url.startswith('#'):
                         logging.warning(f"Skipping invalid URL from file: {url}")
            if not article_links_to_process:
                 logging.error("Input file did not contain any valid URLs.")
                 sys.exit(1)
            included_sections.append("From File")
        except FileNotFoundError:
            logging.error(f"Input file not found: {args.input_file}")
            sys.exit(1)
        except Exception as e:
             logging.error(f"Error reading input file '{args.input_file}': {e}")
             sys.exit(1)
    else:
        # Process sections from --include
        sections_to_scrape = [s.strip().lower() for s in args.include.split('+') if s.strip()]
        index_urls_to_fetch = []
        valid_sections = []
        for section in sections_to_scrape:
            if section in SECTION_URLS:
                index_urls_to_fetch.append(SECTION_URLS[section])
                valid_sections.append(section)
            else:
                logging.warning(f"Unknown section '{section}' requested in --include. Ignoring.")

        if not index_urls_to_fetch:
            logging.error("No valid sections specified or defaulted. Use --include with valid section names.")
            logging.info(f"Available sections: {', '.join(SECTION_URLS.keys())}")
            sys.exit(1)

        included_sections = valid_sections
        logging.info(f"Fetching articles from sections: {', '.join(included_sections)}")
        max_pages = 10000 if args.all_pages else args.pages # Effectively unlimited if --all-pages
        article_links_to_process = get_article_links(index_urls_to_fetch, max_pages_per_section=max_pages)
        if not article_links_to_process:
             logging.warning("No article links found from the specified sections/pages.")
             # Don't exit yet, maybe filtering is the reason

    if not article_links_to_process:
        logging.info("No article URLs to process. Exiting.")
        sys.exit(0)

    logging.info(f"Found {len(article_links_to_process)} potential article URLs.")

    # Apply Max Articles Limit early if specified
    if args.max_articles is not None and len(article_links_to_process) > args.max_articles:
        logging.info(f"Limiting processing to {args.max_articles} articles due to --max-articles.")
        # Optional: could shuffle before truncating for random sample
        # random.shuffle(article_links_to_process)
        article_links_to_process = article_links_to_process[:args.max_articles]


    # --- Process Articles Concurrently ---
    processed_chapters_data = [] # List to store [(title, chapter, metadata, image_items), ...]
    total_articles = len(article_links_to_process)
    articles_processed_count = 0
    articles_succeeded_count = 0
    articles_failed_count = 0
    articles_skipped_count = 0 # For filtering

    logging.info(f"Starting article processing using {args.threads} threads...")

    # Use ThreadPoolExecutor for I/O bound tasks (network requests)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads, thread_name_prefix='Worker') as executor:
        # Submit all jobs
        future_to_url = {
            executor.submit(process_article, url, not args.skip_images, args.start_date, args.end_date): url
            for url in article_links_to_process
        }

        try:
            # Process results as they complete
            for future in tqdm(concurrent.futures.as_completed(future_to_url), total=total_articles, desc="Processing articles", unit="article"):
                if exit_flag:
                    logging.warning("Shutdown requested, cancelling remaining tasks...")
                    # Attempt to cancel pending futures (may not work if already running)
                    for f in future_to_url:
                        if not f.done():
                            f.cancel()
                    break # Exit the completion loop

                url = future_to_url[future]
                articles_processed_count += 1
                try:
                    result = future.result()
                    if result is None: # Should not happen if process_article handles errors
                        articles_failed_count += 1
                        logging.error(f"Processing returned None unexpectedly for {url}")
                    else:
                        title, chapter, metadata, chapter_image_items = result
                        if title and chapter:
                            processed_chapters_data.append((title, chapter, metadata, chapter_image_items))
                            articles_succeeded_count += 1
                        elif title is None and chapter is None and metadata is None:
                             # This indicates filtering or recoverable error handled in process_article
                             articles_skipped_count += 1
                             # Logged within process_article
                        else:
                             # Indicates an unexpected partial failure state
                             articles_failed_count += 1
                             logging.error(f"Incomplete result received for {url}. Title: {title is not None}, Chapter: {chapter is not None}")

                except concurrent.futures.CancelledError:
                     logging.warning(f"Task for {url} was cancelled.")
                     articles_failed_count += 1
                except Exception:
                    articles_failed_count += 1
                    logging.error(f"Article processing failed with exception: {url}", exc_info=True)

        except KeyboardInterrupt: # Handle Ctrl+C during the as_completed loop
            signal_handler(signal.SIGINT, None) # Trigger graceful shutdown logic
            # Executor shutdown is handled by the 'with' block ending

    logging.info(f"--- Article Processing Summary ---")
    logging.info(f"Total URLs attempted: {total_articles}")
    logging.info(f"Successfully processed: {articles_succeeded_count}")
    logging.info(f"Skipped (filtered/recoverable error): {articles_skipped_count}")
    logging.info(f"Failed/Cancelled: {articles_failed_count}")

    if exit_flag:
         logging.warning("Processing was interrupted.")

    if not processed_chapters_data:
        logging.error("No articles were successfully processed or passed filters. Cannot create EPUB.")
        sys.exit(1)


    # --- Create EPUB(s) ---
    # Generate base filename
    if args.epub_title:
        base_filename = args.epub_title
    else:
        # Auto-generate title based on sections
        section_part = "_".join(sorted(included_sections)).replace(" ", "_")
        base_filename = f"Mises_{section_part}_Collection"

    if args.split:
        num_articles_total = len(processed_chapters_data)
        articles_per_split = args.split
        num_splits = (num_articles_total + articles_per_split - 1) // articles_per_split
        logging.info(f"Splitting {num_articles_total} articles into {num_splits} EPUB file(s) with ~{articles_per_split} articles each.")

        for i in range(num_splits):
            start_index = i * articles_per_split
            end_index = min((i + 1) * articles_per_split, num_articles_total)
            split_chapters_data = processed_chapters_data[start_index:end_index]

            if not split_chapters_data: continue # Should not happen, but safety check

            split_filename_base = f"{base_filename}_Part_{i+1:02d}"
            logging.info(f"--- Creating EPUB Part {i+1} ({len(split_chapters_data)} articles) ---")
            create_epub(split_chapters_data, args.save_dir, split_filename_base, included_sections, args.cover, author="Mises Institute", language='en')
            if exit_flag:
                logging.warning("EPUB creation interrupted during splitting.")
                break
    else:
        logging.info(f"--- Creating Single EPUB ({len(processed_chapters_data)} articles) ---")
        create_epub(processed_chapters_data, args.save_dir, base_filename, included_sections, args.cover, author="Mises Institute", language='en')


    logging.info("--- Mises EPUB Generator Finished ---")
    if exit_flag:
         logging.warning("Run completed after interruption signal.")

if __name__ == '__main__':
    # Set thread name for main thread
    import threading
    threading.current_thread().name = "Main"
    main()
