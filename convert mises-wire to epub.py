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
from dateutil import parser as date_parser  # pip install python-dateutil

# User-Agent header for HTTP requests.
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/91.0.4472.124 Safari/537.36')
}

def sanitize_filename(title):
    """Sanitizes a title to create a valid filename."""
    filename = title.replace(" ", "_")
    filename = re.sub(r'[^\w\s.-]', '', filename)
    filename = filename.strip('_').strip()
    return filename[:200]  # Limit filename length

def is_valid_url(url):
    """Checks if the given string is a valid URL."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def parse_date(date_str):
    """Parses a date string into a datetime object.

    Returns datetime.min on failure.
    """
    try:
        return date_parser.parse(date_str)
    except Exception:
        return datetime.min

def get_article_links(index_url, max_pages=1000):
    """
    Fetches article URLs from the Mises Wire index and paginated pages.

    Args:
        index_url: The base URL of the Mises Wire index.
        max_pages: The maximum number of pages to fetch.

    Returns:
        A list of absolute article URLs.
    """
    all_article_links = set()

    def fetch_page_links(page_num):
        """Fetches article links from a single index page."""
        page_url = f"{index_url}?page={page_num}" if page_num > 1 else index_url
        logging.debug(f"Fetching index page: {page_url}")
        try:
            response = requests.get(page_url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            page_links = set()

            # Find article links within <article> tags if they exist, otherwise fallback to all <a> tags
            articles = soup.find_all('article')
            if articles:
                for art in articles:
                    a_tag = art.find('a', href=True)
                    if a_tag:
                        href = a_tag['href']
                        if 'rss.xml' in href:  # Skip RSS feed links
                            continue
                        absolute_url = urljoin(index_url, href)
                        page_links.add(absolute_url)
            else:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '/wire/' in href and 'rss.xml' not in href:
                        absolute_url = urljoin(index_url, href)
                        page_links.add(absolute_url)

            return page_links
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch index page {page_url}: {e}")
            logging.debug(traceback.format_exc())
            return set()

    # Use ThreadPoolExecutor for concurrent fetching of index pages
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_page = {executor.submit(fetch_page_links, page_num): page_num
                          for page_num in range(1, max_pages + 1)}
        for future in concurrent.futures.as_completed(future_to_page):
            page_num = future_to_page[future]
            try:
                page_links = future.result()
                all_article_links.update(page_links)
                logging.debug(f"Accumulated {len(all_article_links)} unique links so far after page {page_num}.")
            except Exception as exc:
                logging.error(f"Page {page_num} generated an exception: {exc}")

    article_links_list = list(all_article_links)
    logging.info(f"Total article links found across {max_pages} pages: {len(article_links_list)}")
    return article_links_list

def get_article_metadata(soup, url):
    """
    Extracts metadata (author, date, tags, summary) from an article's soup object.
    """
    metadata = {}
    try:
        # Author extraction (multiple methods)
        author_element = soup.find('meta', property='author')
        if author_element:
            metadata['author'] = author_element.get('content', '').strip()
        else:
            author_element = soup.find('a', rel='author')
            if author_element:
                metadata['author'] = author_element.get_text(strip=True)
            else:
                details = soup.find('div', {"data-component-id": "mises:element-article-details"})
                if details:
                    profile_link = details.find('a', href=lambda href: href and "profile" in href)
                    if profile_link:
                        metadata['author'] = profile_link.get_text(strip=True)
                if 'author' not in metadata:
                    metadata['author'] = "Mises Wire"  # Default author

        # Date extraction (meta tag or <time> element)
        date_element = soup.find('meta', property='article:published_time')
        if date_element:
            metadata['date'] = date_element.get('content', '').strip()
        else:
            time_element = soup.find('time', datetime=True)
            if time_element:
                metadata['date'] = time_element['datetime'].strip()

        # Tags extraction
        tag_elements = soup.find_all('meta', property='article:tag')
        metadata['tags'] = [tag.get('content', '').strip() for tag in tag_elements] if tag_elements else []

        # Summary extraction (meta description or first paragraph)
        summary_element = soup.find('meta', property='og:description')
        if summary_element:
            metadata['summary'] = summary_element.get('content', '').strip()
        else:
            first_paragraph = soup.find('div', class_='post-entry').find('p') if soup.find('div', class_='post-entry') else None
            if first_paragraph:
                metadata['summary'] = first_paragraph.get_text(strip=True)

    except Exception as e:
        logging.error(f"Error extracting metadata from {url}: {e}")
        logging.debug(traceback.format_exc())

    return metadata

def manual_extraction_fallback(soup):
    """
    Fallback method to extract title and content if readability fails.
    """
    logging.debug("Attempting manual extraction fallback.")
    try:
        # Find title using common selectors
        title_element = (soup.find('h1', class_='page-header__title') or
                         soup.find('h1', class_='entry-title') or
                         soup.find('h1', itemprop='headline'))
        title = title_element.get_text(strip=True) if title_element else None

        # Find content container or use the entire body as a last resort
        content_element = soup.find('div', class_='post-entry')
        if content_element:
            # Extract text from paragraphs within the content container
            article_paragraphs = content_element.find_all('p')
            content = "\n\n".join(p.get_text(strip=True) for p in article_paragraphs) if article_paragraphs else content_element.get_text(separator='\n', strip=True)
        else:
            logging.warning("Manual extraction: Content container not found; using entire body.")
            content = soup.body.get_text(separator='\n', strip=True)

        # Construct basic HTML structure
        cleaned_html_fallback = f"<h1>{title}</h1><article>{content.replace('\n\n', '<p></p>')}</article>" if title else None
        return title, cleaned_html_fallback

    except Exception as e:
        logging.error(f"Manual extraction fallback failed: {e}")
        logging.debug(traceback.format_exc())
        return None, None

def process_article(url):
    """
    Fetches, extracts, and prepares an article for EPUB conversion.

    Args:
        url: The URL of the article.

    Returns:
        A tuple: (title, chapter, metadata), where:
            - title: The article title.
            - chapter: An EpubHtml object containing the article content.
            - metadata: A dictionary of article metadata.
        Returns (None, None, None) if processing fails.
    """
    logging.debug(f"Processing URL: {url}")
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
        logging.debug(traceback.format_exc())
        return None, None, None

    soup = BeautifulSoup(response.text, 'html.parser')
    metadata = get_article_metadata(soup, url)

    try:
        # Use readability to extract main content
        doc = Document(response.text)
        title = doc.short_title()
        cleaned_html = doc.summary()
        logging.debug(f"Extracted title via readability: {title}")

        # Fallback to manual extraction if readability fails or returns empty content
        if not title or not cleaned_html:
            logging.error(f"Readability extraction failed for {url}; using manual fallback.")
            title, cleaned_html = manual_extraction_fallback(soup)
            if not title or not cleaned_html:
                logging.error(f"Manual extraction also failed for {url}.")
                return None, None, None

    except Exception as e:
        logging.error(f"Error during readability/manual extraction for {url}: {e}")
        logging.debug(traceback.format_exc())
        return None, None, None

    # Create header HTML with metadata
    header_html = f"<h2>{title}</h2>"
    if 'author' in metadata:
        header_html += f"<p>By {metadata['author']}</p>"
    if 'date' in metadata:
        header_html += f"<p>Date: {metadata['date']}</p>"
    if 'tags' in metadata:
        header_html += f"<p>Tags: {', '.join(metadata['tags'])}</p>"

    # Create footer HTML with source URL
    footer_html = f"<hr/><p>Source URL: <a href='{url}'>{url}</a></p>"

    # Combine header, content, and footer
    full_content_html = header_html + cleaned_html + footer_html

    # Create EpubHtml chapter
    chapter_filename = sanitize_filename(title) + '.xhtml'
    chapter = epub.EpubHtml(title=title, file_name=chapter_filename, lang='en')
    chapter.content = full_content_html.encode('utf-8')

    return title, chapter, metadata

def create_epub(chapters, save_dir, epub_title, cover_path=None):
    """
    Creates an EPUB file from a list of chapters.

    Args:
        chapters: A list of tuples: (title, chapter, metadata).
        save_dir: The directory to save the EPUB file.
        epub_title: The title of the EPUB.
        cover_path: (Optional) Path to a cover image.
    """
    book = epub.EpubBook()
    book.set_title(epub_title)
    book.add_author("Mises Wire")  # Default author for the book
    book.set_language('en')

    # Add cover image (resizing if necessary)
    if cover_path and os.path.exists(cover_path):
        try:
            with open(cover_path, 'rb') as f:
                cover_content = f.read()
            img = Image.open(BytesIO(cover_content))
            if img.width > 600 or img.height > 800:
                logging.warning("Cover image is too large, resizing to 600x800")
                img.thumbnail((600, 800))
                img_buffer = BytesIO()
                img.save(img_buffer, format=img.format)
                cover_content = img_buffer.getvalue()
            cover_file_name = 'images/cover' + os.path.splitext(cover_path)[1]
            book.set_cover(cover_file_name, cover_content)
            logging.debug(f"Added cover image: {cover_path}")
        except Exception as e:
            logging.error(f"Error adding cover image: {e}")
            logging.debug(traceback.format_exc())

    # Add introduction chapter
    intro_title = "Welcome"
    intro_content = f"<h1>{epub_title}</h1><p>This is a collection of articles from Mises Wire.</p>"
    intro_chapter = epub.EpubHtml(title=intro_title, file_name='intro.xhtml', lang='en')
    intro_chapter.content = intro_content
    book.add_item(intro_chapter)

    # Sort chapters by date (newest first)
    chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)

    # Add chapters to the book and build TOC/spine
    toc = [epub.Link('intro.xhtml', intro_title, 'intro')]
    spine = ['nav', intro_chapter]
    for title, chapter, metadata in chapters:
        book.add_item(chapter)
        toc.append(epub.Link(chapter.file_name, title, chapter.file_name))
        spine.append(chapter)

    book.toc = tuple(toc)
    book.spine = spine

    # Add NCX and navigation
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Add basic CSS styling
    style = 'BODY { font-family: Times, serif; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css",
                            media_type="text/css", content=style.encode('utf-8'))
    book.add_item(nav_css)

    # Write the EPUB file
    safe_title = sanitize_filename(epub_title)
    filename = os.path.join(save_dir, safe_title + '.epub')
    try:
        os.makedirs(save_dir, exist_ok=True)  # Create directory if it doesn't exist
        epub.write_epub(filename, book, {})
        logging.info(f"Saved EPUB: {filename}")
    except Exception as e:
        logging.error(f"Failed to write EPUB: {e}")
        logging.debug(traceback.format_exc())

def main():
    """
    Main function to handle command-line arguments and control the workflow.
    """
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description='Convert Mises Wire articles into EPUB files.')
    parser.add_argument('--all', action='store_true', help='Convert all articles from Mises Wire index pages.')
    parser.add_argument('--pages', type=int, default=1000,
                        help='Number of index pages to check when using --all (default: 1000).')
    parser.add_argument('--save_dir', type=str, default=os.path.join(os.path.expanduser("~"), "Desktop", "mises.org"),
                        help='Directory to save the EPUB files (default: ~/Desktop/mises.org).')
    parser.add_argument('--epub_title', type=str, default="Mises Wire Collection",
                        help='Base title for the EPUB files (default: "Mises Wire Collection").')
    parser.add_argument('--split', type=int, default=None,
                        help='Number of EPUB files to split the articles into (e.g., --split 10).')
    parser.add_argument('--cover', type=str, default=None,
                        help='Path to an image file to use as the cover.')
    args = parser.parse_args()

    if args.all:
        index_url = "https://mises.org/wire"
        article_links = get_article_links(index_url, max_pages=args.pages)

        if not article_links:
            logging.error("No article links found. Exiting.")
            return

        logging.info(f"Found {len(article_links)} article links; starting processing.")

        processed_chapters = []
        # Process articles concurrently using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_url = {executor.submit(process_article, url): url for url in article_links}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    title, chapter, metadata = future.result()
                    if title and chapter:
                        logging.info(f"Processed article: {title}")
                        processed_chapters.append((title, chapter, metadata))
                    else:
                        logging.error(f"Skipping article at {url} due to processing errors.")
                except Exception as exc:
                    logging.error(f"Article at {url} generated an exception: {exc}")

        if processed_chapters:
            # Sort all chapters globally by date
            processed_chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)

            # Split into multiple EPUBs if requested
            if args.split:
                num_splits = args.split
                articles_per_epub = (len(processed_chapters) + num_splits - 1) // num_splits  # Ceiling division
                for i in range(num_splits):
                    start_index = i * articles_per_epub
                    end_index = min((i + 1) * articles_per_epub, len(processed_chapters))
                    split_chapters = processed_chapters[start_index:end_index]
                    if split_chapters:
                        split_title = f"{args.epub_title} - Part {i + 1}"
                        create_epub(split_chapters, args.save_dir, split_title, args.cover)
            else:
                create_epub(processed_chapters, args.save_dir, args.epub_title, args.cover)
        else:
            logging.error("No chapters were successfully processed. EPUB not created.")
    else:
        logging.error("No mode specified. Use --all to process all articles.")

if __name__ == '__main__':
    main()
