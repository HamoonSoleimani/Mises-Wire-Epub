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
    try:
        return date_parser.parse(date_str)
    except Exception:
        return datetime.min

def get_article_links(index_url, max_pages=1000):
    """
    Fetch article URLs from the Mises Wire index and paginated pages.
    Iterates through pages 1 to max_pages.
    Extracts article links from <article> elements or falls back to scanning <a> tags.
    Skips RSS feed links.
    Returns a list of absolute URLs.
    """
    all_article_links = set()

    def fetch_page_links(page_num):
        page_url = f"{index_url}?page={page_num}" if page_num > 1 else index_url
        logging.debug(f"Fetching index page: {page_url}")
        try:
            response = requests.get(page_url, headers=HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            page_links = set()
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

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_page = {executor.submit(fetch_page_links, page_num): page_num for page_num in range(1, max_pages + 1)}
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
    Extracts metadata (author, date, tags) from an article's soup object.
    """
    metadata = {}
    try:
        # Author extraction
        author_element = soup.find('meta', property='author')
        if author_element:
            metadata['author'] = author_element.get('content', '').strip()
        else:
            author_element = soup.find('a', rel='author')
            if author_element:
                metadata['author'] = author_element.get_text(strip=True)
            else:
                metadata['author'] = "Mises Wire"

        # Date extraction
        date_element = soup.find('meta', property='article:published_time')
        if date_element:
            metadata['date'] = date_element.get('content', '').strip()

        # Tags extraction
        tag_elements = soup.find_all('meta', property='article:tag')
        if tag_elements:
            metadata['tags'] = [tag.get('content', '').strip() for tag in tag_elements]

        # Summary extraction (using the first paragraph as fallback)
        summary_element = soup.find('meta', property='og:description')
        if summary_element:
            metadata['summary'] = summary_element.get('content', '').strip()
        else:
            post_entry = soup.find('div', class_='post-entry')
            if post_entry:
                first_paragraph = post_entry.find('p')
                if first_paragraph:
                    metadata['summary'] = first_paragraph.get_text(strip=True)

    except Exception as e:
        logging.error(f"Error extracting metadata from {url}: {e}")
        logging.debug(traceback.format_exc())

    return metadata

def manual_extraction_fallback(soup):
    """
    A fallback extraction method if readability fails.
    Searches for common selectors to extract the title and content.
    """
    logging.debug("Attempting manual extraction fallback.")
    try:
        title_element = (soup.find('h1', class_='page-header__title') or
                         soup.find('h1', class_='entry-title') or
                         soup.find('h1', itemprop='headline'))
        if not title_element:
            logging.warning("Manual extraction: Title element not found.")
            return None, None
        title = title_element.get_text(strip=True)
        logging.debug(f"Manual extraction: Found title: {title}")
        content_element = soup.find('div', class_='post-entry')
        if not content_element:
            logging.warning("Manual extraction: Content container not found; using entire body.")
            content = str(soup.body)
        else:
            article_paragraphs = content_element.find_all('p')
            if article_paragraphs:
                content = "\n\n".join(p.get_text(strip=True) for p in article_paragraphs)
            else:
                content = content_element.get_text(separator='\n', strip=True)
        cleaned_html_fallback = f"<h1>{title}</h1><article>{content.replace('\n\n', '<p></p>')}</article>"
        return title, cleaned_html_fallback
    except Exception as e:
        logging.error(f"Manual extraction fallback failed: {e}")
        logging.debug(traceback.format_exc())
        return None, None

def process_article(url):
    """
    Fetch an article from the URL, extract its content, header information (author, date, tags),
    and return a tuple of (title, chapter, metadata) where chapter is an EpubHtml item.
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
        doc = Document(response.text)
        title = doc.short_title() or "untitled"
        cleaned_html = doc.summary()
        logging.debug(f"Extracted title via readability: {title}")
        if not title or not cleaned_html:
            logging.error(f"Readability extraction failed for {url}; using manual fallback.")
            title, cleaned_html = manual_extraction_fallback(soup)
            if not title or not cleaned_html:
                logging.error(f"Manual extraction also failed for {url}.")
                return None, None, None
    except Exception as e:
        logging.error(f"Error during readability processing for {url}: {e}")
        logging.debug(traceback.format_exc())
        title, cleaned_html = manual_extraction_fallback(soup)
        if not title or not cleaned_html:
            logging.error(f"Manual fallback extraction failed for {url}.")
            return None, None, None

    # Create header HTML with metadata information at the beginning of the article.
    header_html = f"<h2>{title}</h2>"
    if 'author' in metadata:
        header_html += f"<p>By: {metadata['author']}</p>"
    if 'date' in metadata:
        header_html += f"<p>Date: {metadata['date']}</p>"
    if 'tags' in metadata:
        header_html += f"<p>Tags: {', '.join(metadata['tags'])}</p>"

    # Add source URL as footer.
    footer_html = f"<hr/><p>Source URL: <a href='{url}'>{url}</a></p>"

    cleaned_html = header_html + cleaned_html + footer_html

    chapter_filename = sanitize_filename(title) + '.xhtml'
    chapter = epub.EpubHtml(title=title, file_name=chapter_filename, lang='en')
    chapter.content = cleaned_html.encode('utf-8')
    return title, chapter, metadata

def create_epub(chapters, save_dir, epub_title, cover_path=None):
    """
    Create an EPUB file from a list of chapters.
    Each chapter is an EpubHtml item. The EPUB includes a robust table of contents,
    proper spine ordering, and an optional cover image.
    """
    book = epub.EpubBook()
    book.set_title(epub_title)
    book.add_author("Mises Wire")
    book.set_language('en')

    # Add cover image if provided.
    if cover_path and os.path.exists(cover_path):
        try:
            with open(cover_path, 'rb') as f:
                cover_content = f.read()
            # Resize the cover if it's too large.
            img = Image.open(cover_path)
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

    # Add an introduction chapter.
    intro_title = "Welcome"
    intro_content = f"<h1>{epub_title}</h1><p>This is a collection of articles from Mises Wire.</p>"
    intro_chapter = epub.EpubHtml(title=intro_title, file_name='intro.xhtml', lang='en')
    intro_chapter.content = intro_content
    book.add_item(intro_chapter)

    # Add each article chapter.
    chapter_objects = []
    for title, chapter, metadata in chapters:
        book.add_item(chapter)
        chapter_objects.append((title, chapter, metadata))

    # Build a neat Table of Contents (TOC) and spine list.
    # Sort chapters by date in descending order (newest first).
    chapter_objects.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)

    toc = [epub.Link('intro.xhtml', intro_title, 'intro')]
    spine = ['nav', intro_chapter]

    # Add chapters to the TOC and spine.
    for title, chapter, metadata in chapter_objects:
        toc.append(epub.Link(chapter.file_name, title, chapter.file_name))
        spine.append(chapter)

    book.toc = tuple(toc)
    book.spine = spine

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Add CSS styling.
    style = 'BODY { font-family: Times, serif; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css",
                            media_type="text/css", content=style.encode('utf-8'))
    book.add_item(nav_css)

    safe_title = sanitize_filename(epub_title)
    filename = os.path.join(save_dir, safe_title + '.epub')
    try:
        os.makedirs(save_dir, exist_ok=True)
        epub.write_epub(filename, book, {})
        logging.info(f"Saved EPUB: {filename}")
    except Exception as e:
        logging.error(f"Failed to write EPUB: {e}")
        logging.debug(traceback.format_exc())

def main():
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description='Convert Mises Wire articles into EPUB files.')
    parser.add_argument('--all', action='store_true', help='Convert all articles from Mises Wire index pages.')
    parser.add_argument('--pages', type=int, default=1000, help='Number of index pages to check when using --all.')
    parser.add_argument('--save_dir', type=str, default="mises_epubs", help='Directory to save the EPUB files.') # changed default here
    parser.add_argument('--epub_title', type=str, default="Mises Wire Collection", help='Base title for the EPUB files.')
    parser.add_argument('--split', type=int, default=None,
                        help='Number of EPUB files to split the articles into. For example, --split 10 will distribute all articles evenly among 10 EPUB files.')
    parser.add_argument('--cover', type=str, default=None, help='Path to an image file to use as the cover.')
    args = parser.parse_args()

    if args.all:
        index_url = "https://mises.org/wire"
        article_links = get_article_links(index_url, max_pages=args.pages)
        logging.info(f"Found {len(article_links)} article links; starting processing.")

        processed_chapters = []
        # Process articles concurrently.
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
            # If --split parameter is provided, treat it as the number of EPUB files desired.
            if args.split:
                num_files = args.split
                total_articles = len(processed_chapters)
                # Calculate the number of articles per file (using ceiling division).
                articles_per_file = -(-total_articles // num_files)
                for i in range(num_files):
                    start_index = i * articles_per_file
                    end_index = min((i + 1) * articles_per_file, total_articles)
                    # Only create an EPUB if there are articles in this slice.
                    if start_index < total_articles:
                        split_chapters = processed_chapters[start_index:end_index]
                        split_title = f"{args.epub_title} - Part {i+1}"
                        create_epub(split_chapters, args.save_dir, split_title, args.cover)
            else:
                create_epub(processed_chapters, args.save_dir, args.epub_title, args.cover)
        else:
            logging.error("No chapters were successfully processed. EPUB not created.")
    else:
        logging.error("No mode specified. Use --all to process all articles.")

if __name__ == '__main__':
    main()
