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
import traceback
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin, urlparse
from dateutil import parser as date_parser
from bs4 import BeautifulSoup
from readability.readability import Document

from ebooklib import epub
from PIL import Image

# Suppress annoying PIL logs if necessary
# logging.getLogger('PIL').setLevel(logging.WARNING)

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                           QLabel, QLineEdit, QSpinBox, QPushButton, QFileDialog, QComboBox,
                           QCheckBox, QProgressBar, QTabWidget, QTextEdit, QGroupBox,
                           QFormLayout, QRadioButton, QButtonGroup, QMessageBox, QSplitter,
                           QScrollArea, QStyle, QListWidget, QListWidgetItem, QFrame,
                           QSlider, QGridLayout, QTreeWidget, QTreeWidgetItem, QHeaderView,
                           QToolBar, QAction, QStatusBar, QSystemTrayIcon, QMenu, QSizePolicy,
                           QTextBrowser, QDial, QToolButton,
                           QStackedWidget, QWizard, QWizardPage, QCalendarWidget,
                           QTimeEdit, QDateEdit, QFontComboBox, QColorDialog, QInputDialog,
                           QTableWidget, QTableWidgetItem, QAbstractItemView,
                           QStyledItemDelegate, QStyleOptionViewItem,
                           QPlainTextEdit, QSizeGrip, QRubberBand, QGraphicsView,
                           QGraphicsScene, QGraphicsPixmapItem, QGraphicsTextItem, QDialog,
                           QDialogButtonBox)
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, pyqtSlot, QSize, QUrl, QSettings,
                         QCoreApplication, QTimer, QMutex, QPropertyAnimation, QRect,
                         QEasingCurve, QParallelAnimationGroup, QSequentialAnimationGroup,
                         QAbstractAnimation, QVariantAnimation, QPointF, QSizeF,
                         QDateTime, QDate, QTime, QLocale, QTranslator, QLibraryInfo,
                         QStandardPaths, QDir, QFileSystemWatcher, QMimeData,
                         QProcess, QTextStream, QIODevice, QBuffer,
                         QByteArray, QDataStream, QFileInfo, QTemporaryDir,
                         QTemporaryFile, QTextCodec, QRegularExpression,
                         QSortFilterProxyModel, QStringListModel, QAbstractTableModel,
                         QModelIndex, QVariant, QItemSelectionModel, QItemSelection)
from PyQt5.QtGui import (QIcon, QPixmap, QColor, QFont, QDesktopServices, QTextCursor,
                        QPalette, QBrush, QPen, QLinearGradient, QRadialGradient,
                        QConicalGradient, QTransform, QPolygon, QPolygonF,QPainter, QPainterPath,
                        QKeySequence, QTextCharFormat, QTextBlockFormat, QTextListFormat,
                        QTextFrameFormat, QTextTableFormat, QTextImageFormat,
                        QSyntaxHighlighter, QTextDocument, QFontMetrics, QFontInfo,
                        QValidator, QIntValidator, QDoubleValidator, QRegExpValidator,
                        QMovie, QImageReader, QImageWriter, QDrag, QCursor,QClipboard)

# Global configuration variables
PROXIES = {}
VERIFY = certifi.where()
TIMEOUT = 30
CACHE_DIR = None
APP_VERSION = "2.0.0"
APP_NAME = "Enhanced Mises Wire EPUB Generator"

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
    r'/mises\.org$'
]

# User-Agent header for HTTP requests with rotation capability
USER_AGENTS = [
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) '
     'Chrome/120.0.0.0 Safari/537.36'),
    ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
     'AppleWebKit/605.1.15 (KHTML, like Gecko) '
     'Version/17.0 Safari/605.1.15'),
    ('Mozilla/5.0 (X11; Linux x86_64) '
     'AppleWebKit/537.36 (KHTML, like Gecko) '
     'Chrome/120.0.0.0 Safari/537.36'),
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) '
     'Gecko/20100101 Firefox/120.0'),
    ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) '
     'Gecko/20100101 Firefox/120.0')
]

# Dark mode stylesheet
DARK_STYLESHEET = """
QMainWindow {
    background-color: #2b2b2b;
    color: #ffffff;
}

QWidget {
    background-color: #2b2b2b;
    color: #ffffff;
    selection-background-color: #3daee9;
    selection-color: #ffffff;
}

QTabWidget::pane {
    border: 1px solid #555555;
    background-color: #3c3c3c;
}

QTabWidget::tab-bar {
    alignment: center;
}

QTabBar::tab {
    background-color: #4a4a4a;
    color: #ffffff;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #3daee9;
    color: #ffffff;
}

QTabBar::tab:hover {
    background-color: #5a5a5a;
}

QPushButton {
    background-color: #3daee9;
    color: #ffffff;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #4fc3f7;
}

QPushButton:pressed {
    background-color: #0288d1;
}

QPushButton:disabled {
    background-color: #555555;
    color: #999999;
}

QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: #404040;
    color: #ffffff;
    border: 2px solid #555555;
    padding: 6px;
    border-radius: 4px;
}

QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #3daee9;
}

QGroupBox {
    font-weight: bold;
    border: 2px solid #555555;
    border-radius: 4px;
    margin-top: 1ex;
    color: #3daee9;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px 0 5px;
}

QListWidget {
    background-color: #404040;
    border: 1px solid #555555;
    border-radius: 4px;
}

QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #555555;
}

QListWidget::item:selected {
    background-color: #3daee9;
}

QListWidget::item:hover {
    background-color: #5a5a5a;
}

QProgressBar {
    border: 2px solid #555555;
    border-radius: 4px;
    text-align: center;
    background-color: #404040;
    color: #ffffff;
}

QProgressBar::chunk {
    background-color: #3daee9;
    border-radius: 2px;
}

QCheckBox {
    color: #ffffff;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
}

QCheckBox::indicator:unchecked {
    background-color: #404040;
    border: 2px solid #555555;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    background-color: #3daee9;
    border: 2px solid #3daee9;
    border-radius: 3px;
}

QRadioButton {
    color: #ffffff;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
}

QRadioButton::indicator:unchecked {
    background-color: #404040;
    border: 2px solid #555555;
    border-radius: 9px;
}

QRadioButton::indicator:checked {
    background-color: #3daee9;
    border: 2px solid #3daee9;
    border-radius: 9px;
}

QSlider::groove:horizontal {
    border: 1px solid #555555;
    height: 8px;
    background-color: #404040;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background-color: #3daee9;
    border: 1px solid #3daee9;
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background-color: #3daee9;
    border-radius: 4px;
}

QScrollBar:vertical {
    background-color: #404040;
    width: 12px;
    border-radius: 6px;
    margin: 0px 0px 0px 0px;
}

QScrollBar::handle:vertical {
    background-color: #3daee9;
    border-radius: 6px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4fc3f7;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #404040;
    height: 12px;
    border-radius: 6px;
    margin: 0px 0px 0px 0px;
}

QScrollBar::handle:horizontal {
    background-color: #3daee9;
    border-radius: 6px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #4fc3f7;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QMenuBar {
    background-color: #2b2b2b;
    color: #ffffff;
    border-bottom: 1px solid #555555;
}

QMenuBar::item {
    background-color: transparent;
    padding: 6px 12px;
}

QMenuBar::item:selected {
    background-color: #3daee9;
}

QMenu {
    background-color: #404040;
    color: #ffffff;
    border: 1px solid #555555;
}

QMenu::item {
    padding: 6px 12px;
}

QMenu::item:selected {
    background-color: #3daee9;
}

QStatusBar {
    background-color: #2b2b2b;
    color: #ffffff;
    border-top: 1px solid #555555;
}

QToolBar {
    background-color: #3c3c3c;
    border: none;
    spacing: 4px;
}

QToolButton {
    background-color: transparent;
    color: #ffffff;
    padding: 6px;
    border-radius: 4px;
}

QToolButton:hover {
    background-color: #5a5a5a;
}

QToolButton:pressed {
    background-color: #3daee9;
}

QTreeWidget {
    background-color: #404040;
    border: 1px solid #555555;
    border-radius: 4px;
    alternate-background-color: #4a4a4a;
}

QTreeWidget::item {
    padding: 4px;
    border-bottom: 1px solid #555555;
}

QTreeWidget::item:selected {
    background-color: #3daee9;
}

QTreeWidget::item:hover {
    background-color: #5a5a5a;
}

QHeaderView::section {
    background-color: #4a4a4a;
    color: #ffffff;
    padding: 6px;
    border: none;
    border-right: 1px solid #555555;
    border-bottom: 1px solid #555555;
}

QSplitter::handle {
    background-color: #555555;
}

QSplitter::handle:horizontal {
    width: 3px;
}

QSplitter::handle:vertical {
    height: 3px;
}

QTableWidget {
    background-color: #404040;
    border: 1px solid #555555;
    border-radius: 4px;
    gridline-color: #555555;
    alternate-background-color: #4a4a4a;
}

QTableWidget::item {
    padding: 8px;
}

QTableWidget::item:selected {
    background-color: #3daee9;
}
"""

# Light mode stylesheet
LIGHT_STYLESHEET = """
QMainWindow {
    background-color: #ffffff;
    color: #333333;
}

QWidget {
    background-color: #ffffff;
    color: #333333;
    selection-background-color: #3daee9;
    selection-color: #ffffff;
}

QTabWidget::pane {
    border: 1px solid #cccccc;
    background-color: #f5f5f5;
}

QTabWidget::tab-bar {
    alignment: center;
}

QTabBar::tab {
    background-color: #e0e0e0;
    color: #333333;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #3daee9;
    color: #ffffff;
}

QTabBar::tab:hover {
    background-color: #f0f0f0;
}

QPushButton {
    background-color: #3daee9;
    color: #ffffff;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #4fc3f7;
}

QPushButton:pressed {
    background-color: #0288d1;
}

QPushButton:disabled {
    background-color: #cccccc;
    color: #666666;
}

QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    color: #333333;
    border: 2px solid #cccccc;
    padding: 6px;
    border-radius: 4px;
}

QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #3daee9;
}

QGroupBox {
    font-weight: bold;
    border: 2px solid #cccccc;
    border-radius: 4px;
    margin-top: 1ex;
    color: #3daee9;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px 0 5px;
}

QListWidget {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
}

QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #eeeeee;
}

QListWidget::item:selected {
    background-color: #3daee9;
    color: #ffffff;
}

QListWidget::item:hover {
    background-color: #f0f0f0;
}

QProgressBar {
    border: 2px solid #cccccc;
    border-radius: 4px;
    text-align: center;
    background-color: #ffffff;
    color: #333333;
}

QProgressBar::chunk {
    background-color: #3daee9;
    border-radius: 2px;
}

QCheckBox {
    color: #333333;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
}

QCheckBox::indicator:unchecked {
    background-color: #ffffff;
    border: 2px solid #cccccc;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    background-color: #3daee9;
    border: 2px solid #3daee9;
    border-radius: 3px;
}

QRadioButton {
    color: #333333;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
}

QRadioButton::indicator:unchecked {
    background-color: #ffffff;
    border: 2px solid #cccccc;
    border-radius: 9px;
}

QRadioButton::indicator:checked {
    background-color: #3daee9;
    border: 2px solid #3daee9;
    border-radius: 9px;
}

QSlider::groove:horizontal {
    border: 1px solid #cccccc;
    height: 8px;
    background-color: #f0f0f0;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background-color: #3daee9;
    border: 1px solid #3daee9;
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}

QSlider::sub-page:horizontal {
    background-color: #3daee9;
    border-radius: 4px;
}

QScrollBar:vertical {
    background-color: #f0f0f0;
    width: 12px;
    border-radius: 6px;
    margin: 0px 0px 0px 0px;
}

QScrollBar::handle:vertical {
    background-color: #3daee9;
    border-radius: 6px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4fc3f7;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #f0f0f0;
    height: 12px;
    border-radius: 6px;
    margin: 0px 0px 0px 0px;
}

QScrollBar::handle:horizontal {
    background-color: #3daee9;
    border-radius: 6px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #4fc3f7;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QMenuBar {
    background-color: #ffffff;
    color: #333333;
    border-bottom: 1px solid #cccccc;
}

QMenuBar::item {
    background-color: transparent;
    padding: 6px 12px;
}

QMenuBar::item:selected {
    background-color: #3daee9;
    color: #ffffff;
}

QMenu {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #cccccc;
}

QMenu::item {
    padding: 6px 12px;
}

QMenu::item:selected {
    background-color: #3daee9;
    color: #ffffff;
}

QStatusBar {
    background-color: #ffffff;
    color: #333333;
    border-top: 1px solid #cccccc;
}

QToolBar {
    background-color: #f5f5f5;
    border: none;
    spacing: 4px;
}

QToolButton {
    background-color: transparent;
    color: #333333;
    padding: 6px;
    border-radius: 4px;
}

QToolButton:hover {
    background-color: #e0e0e0;
}

QToolButton:pressed {
    background-color: #3daee9;
    color: #ffffff;
}

QTreeWidget {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    alternate-background-color: #f9f9f9;
}

QTreeWidget::item {
    padding: 4px;
    border-bottom: 1px solid #eeeeee;
}

QTreeWidget::item:selected {
    background-color: #3daee9;
    color: #ffffff;
}

QTreeWidget::item:hover {
    background-color: #f0f0f0;
}

QHeaderView::section {
    background-color: #f0f0f0;
    color: #333333;
    padding: 6px;
    border: none;
    border-right: 1px solid #cccccc;
    border-bottom: 1px solid #cccccc;
}

QSplitter::handle {
    background-color: #cccccc;
}

QSplitter::handle:horizontal {
    width: 3px;
}

QSplitter::handle:vertical {
    height: 3px;
}

QTableWidget {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    gridline-color: #cccccc;
    alternate-background-color: #f9f9f9;
}

QTableWidget::item {
    padding: 8px;
}

QTableWidget::item:selected {
    background-color: #3daee9;
    color: #ffffff;
}
"""

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
            os.makedirs(CACHE_DIR, exist_ok=True)
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
    
    if url in IGNORED_IMAGE_URLS:
        return True
    
    for pattern in IGNORED_URL_PATTERNS:
        if re.search(pattern, url):
            return True
    
    return False

# --- Core Article Fetching and Processing Functions ---
def get_article_links(index_url, max_pages=9999, progress_callback=None, stop_callback=None, unique_links_check=True, num_threads=8):
    """
    Fetch article URLs from the given index site and paginated pages using a thread pool for concurrency.
    """
    all_article_links = set()
    consecutive_no_new = 0
    max_consecutive_no_new = 3 * num_threads  # Scale the stop condition with thread count

    target_path = urlparse(index_url).path
    if not target_path.endswith('/'): target_path += '/'
    logging.info(f"Scraping context detected. Targeting links for path: '{target_path}' with {num_threads} threads.")
    
    aliased_target_path = '/mises-wire/' if target_path == '/wire/' else None
    if aliased_target_path:
        logging.info(f"Applying special alias: Actual link path to check for is '{aliased_target_path}'")

    def fetch_page_links(page_num):
        # This inner function remains the same, it will be called by multiple threads.
        if stop_callback and stop_callback(): return set(), True
        page_url = f"{index_url}?page={page_num}" if page_num > 0 else index_url
        try:
            page_content = cached_get(page_url)
            soup = BeautifulSoup(page_content, 'html.parser')
            page_links = set()
            potential_links = soup.select('article a[href], div.views-field-title span.field-content a[href]')
            for a_tag in potential_links:
                href = a_tag.get('href', '')
                if href and href.startswith('/'):
                    absolute_url = urljoin(index_url, href)
                    parsed_url = urlparse(absolute_url)
                    path_is_valid = parsed_url.path.startswith(target_path) or \
                                    (aliased_target_path and parsed_url.path.startswith(aliased_target_path))
                    if path_is_valid:
                        page_links.add(absolute_url)
            if not page_links:
                return set(), True # Returns (links, end_reached_flag)
            return page_links, False
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch index page {page_url}: {e}")
            return set(), True # Treat failure as an end condition for this page

    page_num = 0
    total_pages_processed = 0
    # Process pages in chunks to manage memory and requests
    chunk_size = num_threads * 4 # Fetch a few chunks ahead to keep threads busy
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        while page_num < max_pages:
            if stop_callback and stop_callback():
                logging.info("Fetching stopped by user")
                break

            page_range = range(page_num, page_num + chunk_size)
            future_to_page = {executor.submit(fetch_page_links, p): p for p in page_range}
            
            chunk_had_new_links = False
            for future in concurrent.futures.as_completed(future_to_page):
                if stop_callback and stop_callback(): break
                links, end_reached = future.result()
                total_pages_processed += 1
                
                new_links = links - all_article_links
                if new_links:
                    all_article_links.update(links)
                    consecutive_no_new = 0 # Reset counter if any thread finds new links
                    chunk_had_new_links = True
                    logging.info(f"Page {future_to_page[future]}: Found {len(new_links)} new unique links. Total: {len(all_article_links)}")
                else:
                    consecutive_no_new += 1

                if progress_callback:
                    # Show progress based on pages processed so far
                    progress_callback(total_pages_processed, max_pages, len(all_article_links))
                
                if end_reached and not unique_links_check:
                    logging.info(f"Stopping because page {future_to_page[future]} indicated the end.")
                    page_num = max_pages # Force outer loop to exit
                    break
            
            if unique_links_check and consecutive_no_new >= max_consecutive_no_new:
                 logging.info(f"Stopping: No new unique links found in the last {max_consecutive_no_new} attempts.")
                 break
            
            page_num += chunk_size
            time.sleep(0.1) # Small delay between chunks

    logging.info(f"Total unique article links found for '{target_path}': {len(all_article_links)}")
    return list(all_article_links)
    
def get_article_metadata(soup, url):
    """
    Extracts metadata from an article's soup object.
    """
    metadata = {
        'author': "Mises Wire", 'date': '', 'tags': [], 'summary': "",
        'title': "", 'featured_image': None
    }
    try:
        title_selectors = [
            'meta[property="og:title"]', 'h1.page-header__title', 'h1.entry-title',
            'h1[itemprop="headline"]', '.article-title h1', '.node-title', 'title'
        ]
        for selector in title_selectors:
            title_element = soup.select_one(selector)
            if title_element:
                metadata['title'] = (title_element.get('content', '').strip() if title_element.name == 'meta'
                                     else title_element.get_text(strip=True))
                if metadata['title']: break

        author_selectors = [
            'meta[property="author"]', 'meta[name="author"]', 'a[rel="author"]',
            '.byline a', '.author-name', '.field-name-field-author a',
            '[data-component-id="mises:element-article-details"] a[href*="profile"]'
        ]
        for selector in author_selectors:
            author_element = soup.select_one(selector)
            if author_element:
                author = (author_element.get('content', '').strip() if author_element.name == 'meta'
                          else author_element.get_text(strip=True))
                if author and author.lower() not in ['by', 'author']:
                    metadata['author'] = author.replace('By ', '').strip()
                    break

        date_selectors = [
            'meta[property="article:published_time"]', 'meta[property="og:article:published_time"]',
            'time[datetime]', '.date-display-single', '.field-name-post-date', '.published'
        ]
        for selector in date_selectors:
            date_element = soup.select_one(selector)
            if date_element:
                metadata['date'] = (date_element.get('content', '').strip() if date_element.name == 'meta'
                                  else date_element.get('datetime', date_element.get_text(strip=True)).strip())
                if metadata['date']: break

        tag_selectors = [
            'meta[property="article:tag"]', 'a[rel="tag"]', '.tags a',
            '.field-name-field-tags a', '.post-tags a'
        ]
        for selector in tag_selectors:
            tag_elements = soup.select(selector)
            if tag_elements:
                tags = []
                for tag in tag_elements:
                    tag_text = (tag.get('content', '').strip() if tag.name == 'meta'
                                else tag.get_text(strip=True))
                    if tag_text: tags.append(tag_text)
                if tags:
                    metadata['tags'] = tags
                    break

        summary_selectors = [
            'meta[property="og:description"]', 'meta[name="description"]',
            '.field-name-body p:first-child', '.post-entry p:first-child',
            '.entry-content p:first-child'
        ]
        for selector in summary_selectors:
            summary_element = soup.select_one(selector)
            if summary_element:
                summary = (summary_element.get('content', '').strip() if summary_element.name == 'meta'
                           else summary_element.get_text(strip=True))
                if summary and len(summary) > 50:
                    metadata['summary'] = summary[:500]
                    break

        image_selectors = [
            'meta[property="og:image"]', '.field-name-field-image img',
            '.post-thumbnail img', '.featured-image img', '.article-image img'
        ]
        for selector in image_selectors:
            img_element = soup.select_one(selector)
            if img_element:
                img_url = (img_element.get('content', '') if img_element.name == 'meta'
                           else img_element.get('src', ''))
                img_url = clean_image_url(img_url)
                if img_url and not should_ignore_image_url(img_url):
                    metadata['featured_image'] = urljoin(url, img_url)
                    break
    except Exception as e:
        logging.error(f"Error extracting metadata from {url}: {e}", exc_info=True)
    return metadata

def manual_extraction_fallback(soup, url):
    """Fallback extraction method if readability fails."""
    logging.debug(f"Attempting manual extraction fallback for {url}")
    try:
        title_selectors = [
            'h1.page-header__title', 'h1.entry-title', 'h1[itemprop="headline"]',
            '.article-title h1', '.node-title', 'meta[property="og:title"]', 'title'
        ]
        title = "Untitled Article"
        for selector in title_selectors:
            title_element = soup.select_one(selector)
            if title_element:
                title = (title_element.get('content', '').strip() if title_element.name == 'meta'
                         else title_element.get_text(strip=True))
                if title: break

        content_selectors = [
            '.field-name-body', '.post-entry', '.entry-content', '.article-content',
            '.node-content', 'article .content', '.main-content', '#content'
        ]
        content = ""
        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                for unwanted in content_element.select('.social-share, .author-box, .related-posts, .comments, script, style, .advertisement, .ads'):
                    if unwanted: unwanted.decompose()
                elements = content_element.select('p, h2, h3, h4, h5, h6, blockquote, ul, ol, figure, img')
                content = "\n\n".join(str(el) for el in elements) if elements else str(content_element)
                break
        if not content and soup.body:
            logging.warning(f"Manual extraction: Content container not found for {url}; using entire body.")
            for unwanted in soup.body.select('script, style, nav, header, footer, .sidebar, .menu'):
                if unwanted: unwanted.decompose()
            content = str(soup.body)
        
        return title, f"<h1>{title}</h1><article>{content or '<p>Content extraction failed</p>'}</article>"
    except Exception as e:
        logging.error(f"Manual extraction fallback failed for {url}: {e}", exc_info=True)
        return "Extraction Failed", "<article>Content extraction failed</article>"

def download_image(image_url, retry_count=3):
    """Downloads an image from a URL and returns it as a bytes object."""
    image_url = clean_image_url(image_url)
    if not image_url or not is_valid_url(image_url) or should_ignore_image_url(image_url):
        return None

    for attempt in range(retry_count):
        try:
            logging.debug(f"Downloading image from: {image_url} (attempt {attempt+1})")
            with get_session() as session:
                response = session.get(image_url, stream=True, timeout=TIMEOUT, verify=VERIFY)
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').lower()
                if not any(img_type in content_type for img_type in ['image/', 'jpeg', 'png', 'gif', 'webp']):
                    logging.warning(f"Invalid content type for image: {content_type}")
                    return None
                content_length = response.headers.get('content-length')
                if content_length and int(content_length) > 10 * 1024 * 1024:
                    logging.warning(f"Image too large: {content_length} bytes")
                    return None
                return BytesIO(response.content)
        except requests.exceptions.RequestException as e:
            logging.warning(f"Failed to download image {image_url} (attempt {attempt+1}): {e}")
            if attempt < retry_count - 1: time.sleep(2 ** attempt)
            else: logging.error(f"Failed all {retry_count} attempts to download image {image_url}")
    return None

def is_small_image(img):
    """Checks if an image is too small to be worth including"""
    width, height = img.size
    return width < 50 or height < 50

def process_image(img_url, url):
    """Processes an image URL and returns the image data and info if valid."""
    img_url = clean_image_url(img_url)
    if not img_url or should_ignore_image_url(img_url):
        return None, None, None
        
    img_data = download_image(img_url)
    if not img_data:
        return None, None, None
        
    try:
        img = Image.open(img_data)
        if is_small_image(img):
            logging.debug(f"Skipping small image ({img.size[0]}x{img.size[1]}): {img_url}")
            return None, None, None
        
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P': img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        
        max_width, max_height = 1200, 1600
        if img.size[0] > max_width or img.size[1] > max_height:
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        
        img_buffer = BytesIO()
        img.save(img_buffer, format='JPEG', quality=85, optimize=True)
        img_buffer.seek(0)
        
        hash_object = hashlib.md5(img_url.encode())
        img_file_name = f'image_{hash_object.hexdigest()[:8]}.jpg'
        return img_buffer, 'jpeg', img_file_name
    except Exception as e:
        logging.error(f"Error processing image {img_url} in {url}: {e}")
        return None, None, None

def process_article(url, download_images=True, status_callback=None, stop_callback=None):
    """Downloads, parses, extracts content, and processes images from an article."""
    if stop_callback and stop_callback(): return None, None, None, []
    if status_callback: status_callback(f"Processing: {url}")
    logging.debug(f"Processing URL: {url}")

    try:
        html_content = cached_get(url)
    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to fetch {url}: {e}"
        logging.error(error_msg)
        if status_callback: status_callback(error_msg)
        return None, None, None, []

    if stop_callback and stop_callback(): return None, None, None, []

    soup = BeautifulSoup(html_content, 'html.parser')
    metadata = get_article_metadata(soup, url)

    try:
        doc = Document(html_content)
        title = doc.short_title() or metadata.get('title', "Untitled")
        cleaned_html = doc.summary()
        if not cleaned_html or len(cleaned_html) < 200: raise ValueError("Readability returned insufficient content")
    except Exception as e:
        logging.warning(f"Readability extraction failed for {url}: {e}")
        title, cleaned_html = manual_extraction_fallback(soup, url)

    if not title or not cleaned_html:
        error_msg = f"Skipping article due to extraction failure: {url}"
        logging.warning(error_msg)
        if status_callback: status_callback(error_msg)
        return None, None, None, []

    if stop_callback and stop_callback(): return None, None, None, []
    if status_callback: status_callback(f"Extracted: {title}")

    image_items, image_filenames = [], set()
    if download_images and metadata.get('featured_image'):
        if stop_callback and stop_callback(): return None, None, None, []
        img_data, img_format, img_file_name = process_image(metadata['featured_image'], url)
        if img_data and img_format and img_file_name:
            img_file_name = 'featured_' + img_file_name
            epub_image = epub.EpubImage(file_name='images/' + img_file_name,
                                      media_type=f'image/{img_format}',
                                      content=img_data.getvalue())
            image_items.append(epub_image)
            image_filenames.add(img_file_name)
            cleaned_html = f'<figure class="featured-image"><img src="images/{img_file_name}" alt="{title}" /></figure>' + cleaned_html

    cleaned_soup = BeautifulSoup(cleaned_html, 'html.parser')
    if download_images:
        img_tags = cleaned_soup.find_all('img', src=True)
        for i, img_tag in enumerate(img_tags):
            if stop_callback and stop_callback(): break
            img_url = img_tag.get('src', '')
            if img_url.startswith('images/'): continue
            
            if img_url.startswith('data:'):
                try:
                    header, encoded = img_url.split(",", 1)
                    img_format = header.split(';')[0].split('/')[1].lower()
                    if img_format not in ['jpeg', 'jpg', 'png', 'gif', 'webp']: continue
                    img_data = BytesIO(base64.b64decode(encoded))
                    img_file_name = f'image_{hashlib.md5(encoded.encode()).hexdigest()[:8]}.{img_format}'
                    if img_file_name in image_filenames:
                        img_tag['src'] = 'images/' + img_file_name
                        continue
                    epub_image = epub.EpubImage(file_name='images/' + img_file_name,
                                              media_type=f'image/{img_format}',
                                              content=img_data.getvalue())
                    image_items.append(epub_image)
                    image_filenames.add(img_file_name)
                    img_tag['src'] = 'images/' + img_file_name
                except Exception as e:
                    logging.error(f"Error processing data URI in {url}: {e}")
            else:
                full_img_url = urljoin(url, img_url)
                img_data, img_format, img_file_name = process_image(full_img_url, url)
                if img_data and img_format and img_file_name:
                    if img_file_name in image_filenames:
                        img_tag['src'] = 'images/' + img_file_name
                        continue
                    epub_image = epub.EpubImage(file_name='images/' + img_file_name,
                                              media_type=f'image/{img_format}',
                                              content=img_data.getvalue())
                    image_items.append(epub_image)
                    image_filenames.add(img_file_name)
                    img_tag['src'] = 'images/' + img_file_name

            for attr in ['data-src', 'data-srcset', 'srcset', 'loading', 'sizes', 'width', 'height']:
                if attr in img_tag.attrs: del img_tag.attrs[attr]

    header_html = f"<h1>{title}</h1>"
    if metadata.get('author'): header_html += f"<p class='author'>By {metadata['author']}</p>"
    if metadata.get('date'):
        try:
            parsed_date = parse_date(metadata['date'])
            formatted_date = parsed_date.strftime("%B %d, %Y") if parsed_date != datetime.min else metadata['date']
            header_html += f"<p class='date'>Published: {formatted_date}</p>"
        except:
             header_html += f"<p class='date'>Published: {metadata['date']}</p>"
    if metadata.get('summary'): header_html += f"<div class='summary'><em>{metadata['summary']}</em></div>"
    if metadata.get('tags'): header_html += f"<p class='tags'>Tags: {', '.join(metadata['tags'])}</p>"
    footer_html = f"<hr/><p class='source'>Source: <a href='{url}'>{url}</a></p>"
    
    chapter_filename = sanitize_filename(title) + '.xhtml'
    chapter = epub.EpubHtml(title=title, file_name=chapter_filename, lang='en',
                            content=(header_html + str(cleaned_soup) + footer_html).encode('utf-8'))
    chapter.id = sanitize_filename(title).replace(".", "_")
    
    if status_callback: status_callback(f"Completed: {title}")
    return title, chapter, metadata, image_items

def create_epub(chapters, save_dir, epub_title, cover_path=None, author="Mises Wire", language='en', status_callback=None):
    """Create an EPUB file from a list of chapters, including images."""
    if not chapters:
        if status_callback: status_callback("No chapters provided to create EPUB")
        return None

    if status_callback: status_callback(f"Creating EPUB: {epub_title} with {len(chapters)} chapters")
    book = epub.EpubBook()
    book.set_title(epub_title)
    book.add_author(author)
    book.set_language(language)
    book.set_identifier(f"mises-{sanitize_filename(epub_title).lower()}-{datetime.now().strftime('%Y%m%d')}")
    book.add_metadata('DC', 'publisher', 'Mises Institute')
    book.add_metadata('DC', 'date', datetime.now().strftime('%Y-%m-%d'))
    book.add_metadata('DC', 'creator', f'{APP_NAME} v{APP_VERSION}')

    if cover_path and os.path.exists(cover_path):
        try:
            with open(cover_path, 'rb') as f: content = f.read()
            img = Image.open(BytesIO(content))
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P': img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            if img.width > 1600 or img.height > 2400:
                if status_callback: status_callback("Resizing cover image...")
                img.thumbnail((1600, 2400), Image.Resampling.LANCZOS)
                buf = BytesIO()
                img.save(buf, format='JPEG', quality=90, optimize=True)
                content = buf.getvalue()
            book.set_cover("images/cover.jpg", content)
        except Exception as e:
            logging.error(f"Error adding cover image: {e}")

    intro_title = "About This Collection"
    intro_content = f"""<div style="text-align: center; margin: 2em 0;">
        <h1>{epub_title}</h1>
        <p style="font-size: 1.2em; margin: 1em 0;">A curated collection of articles from Mises.org</p><hr style="width: 50%; margin: 2em auto;"/></div>
        <div style="margin: 2em 0;"><h2>About This Collection</h2><p>This book contains articles from Mises.org, featuring contemporary news, opinion, and analysis from the Austrian School of economics perspective.</p>
        <h2>Collection Details</h2><ul><li><strong>Articles:</strong> {len(chapters)}</li><li><strong>Generated:</strong> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</li><li><strong>Generator:</strong> {APP_NAME} v{APP_VERSION}</li></ul>
        <h2>Reading Notes</h2><p>This collection is organized by publication date, with the most recent articles first. Each article includes the original publication date, author information, and source URL.</p></div>"""
    intro_chapter = epub.EpubHtml(title=intro_title, file_name='intro.xhtml', content=intro_content, lang=language)
    book.add_item(intro_chapter)

    try:
        if status_callback: status_callback("Sorting chapters by date...")
        chapters.sort(key=lambda x: parse_date(x[2].get('date', '')), reverse=True)
    except Exception as e:
        logging.warning(f"Failed to sort chapters by date: {e}")

    toc, spine = [epub.Link('intro.xhtml', intro_title, 'intro')], ['nav', intro_chapter]
    image_filenames, all_image_items = set(), []
    
    if status_callback: status_callback("Adding chapters to EPUB...")
    for i, (title, chapter, metadata, image_items) in enumerate(chapters):
        book.add_item(chapter)
        toc.append(epub.Link(chapter.file_name, title, chapter.id))
        spine.append(chapter)
        for image_item in image_items:
            if image_item.file_name not in image_filenames:
                all_image_items.append(image_item)
                image_filenames.add(image_item.file_name)
        if status_callback and (i + 1) % 10 == 0: status_callback(f"Added {i+1}/{len(chapters)} chapters...")

    if status_callback: status_callback(f"Adding {len(all_image_items)} images to EPUB...")
    for i, image_item in enumerate(all_image_items):
        book.add_item(image_item)
        if status_callback and (i + 1) % 20 == 0: status_callback(f"Added {i+1}/{len(all_image_items)} images...")

    book.toc, book.spine = tuple(toc), spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    css_content = """@namespace epub "http://www.idpf.org/2007/ops"; body{font-family:"Georgia","Times New Roman",serif;line-height:1.6;margin:0;padding:2%;color:#333;text-align:left}h1{font-size:1.8em;font-weight:700;margin:1.5em 0 1em;color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:.5em}h2{font-size:1.4em;font-weight:700;margin:1.3em 0 .8em;color:#dddddd}h3{font-size:1.2em;font-weight:700;margin:1.2em 0 .6em;color:#dddddd}p{margin:.8em 0;text-align:justify;text-indent:1.2em}p.author{font-style:italic;color:#7f8c8d;margin:.5em 0;text-indent:0;font-size:.95em}p.date{color:#95a5a6;margin:.3em 0 1em;text-indent:0;font-size:.9em}p.tags{color:#3498db;margin:.5em 0;text-indent:0;font-size:.9em}.summary{background-color:#ecf0f1;border-left:4px solid #3498db;padding:1em;margin:1em 0 2em;font-style:italic;border-radius:0 4px 4px 0}.summary p{margin:0;text-indent:0}img{max-width:100%;height:auto;display:block;margin:1em auto;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.1)}.featured-image{margin:2em 0;text-align:center}.featured-image img{max-width:90%;box-shadow:0 4px 12px rgba(0,0,0,.15)}blockquote{margin:1.5em 2em;padding:1em;background-color:#f8f9fa;border-left:4px solid #3498db;font-style:italic;border-radius:0 4px 4px 0}blockquote p{margin:.5em 0;text-indent:0}ul,ol{margin:1em 0;padding-left:2em}li{margin:.5em 0}.source{margin-top:3em;padding-top:1em;border-top:1px solid #bdc3c7;font-size:.85em;color:#7f8c8d;text-align:center;text-indent:0}.source a{color:#3498db;text-decoration:none}hr{border:none;height:1px;background-color:#bdc3c7;margin:2em 0}table{width:100%;border-collapse:collapse;margin:1em 0}th,td{border:1px solid #bdc3c7;padding:.5em;text-align:left}th{background-color:#ecf0f1;font-weight:700}code{background-color:#f8f9fa;padding:.2em .4em;border-radius:3px;font-family:"Courier New",monospace;font-size:.9em}pre{background-color:#f8f9fa;padding:1em;border-radius:4px;overflow-x:auto;margin:1em 0}pre code{background-color:transparent;padding:0}@media print{body{font-size:12pt;line-height:1.4}h1{font-size:18pt}h2{font-size:14pt}h3{font-size:12pt}.featured-image img{max-width:100%}}"""
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=css_content)
    book.add_item(nav_css)

    safe_title = sanitize_filename(epub_title)
    os.makedirs(save_dir, exist_ok=True)
    filename = os.path.join(save_dir, safe_title + '.epub')

    try:
        if status_callback: status_callback(f"Writing EPUB file to {filename}...")
        epub.write_epub(filename, book, {})
        logging.info(f"Saved EPUB: {filename}")
        if status_callback: status_callback(f"✅ EPUB successfully created: {filename}")
        return filename
    except Exception as e:
        error_msg = f"Failed to write EPUB: {e}"
        logging.error(error_msg, exc_info=True)
        if status_callback: status_callback(f"❌ {error_msg}")
        return None

# --- Enhanced Worker Threads for GUI ---
class ArticleFetchWorker(QThread):
    finished = pyqtSignal(list)
    progress = pyqtSignal(int, int, int)
    status = pyqtSignal(str)

    def __init__(self, fetch_tasks, stop_on_no_new_links=True, num_threads=8):
        super().__init__()
        self.fetch_tasks = fetch_tasks
        self.stop_on_no_new_links = stop_on_no_new_links
        self.num_threads = num_threads
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def is_stop_requested(self):
        return self._stop_requested

    def run(self):
        all_article_links = set()
        try:
            for task in self.fetch_tasks:
                if self._stop_requested:
                    self.status.emit("Fetching stopped by user")
                    break
                
                self.status.emit(f"Fetching articles from {task['name']}...")
                
                links_for_task = get_article_links(
                    task['url'], task['pages'],
                    progress_callback=lambda p, mp, na: self.progress.emit(p, mp, na),
                    stop_callback=self.is_stop_requested,
                    unique_links_check=self.stop_on_no_new_links,
                    num_threads=self.num_threads
                )
                
                if not self._stop_requested:
                    newly_found = len(set(links_for_task) - all_article_links)
                    self.status.emit(f"Found {newly_found} new articles from {task['name']}. Total unique: {len(all_article_links) + newly_found}")
                    all_article_links.update(links_for_task)

            final_links = list(all_article_links) if not self._stop_requested else []
            self.finished.emit(final_links)
        except Exception as e:
            logging.error(f"Error in ArticleFetchWorker: {e}", exc_info=True)
            self.status.emit(f"Error fetching articles: {str(e)}")
            self.finished.emit([])

class ArticleProcessWorker(QThread):
    progress = pyqtSignal(int, int)
    article_processed = pyqtSignal(tuple)
    article_failed = pyqtSignal(str)
    status = pyqtSignal(str)
    finished = pyqtSignal()

    
    def __init__(self, urls, download_images, num_threads):
            super().__init__()
            self.urls = urls
            self.download_images = download_images
            self.num_threads = min(num_threads, len(urls))
            self._stop_requested = False

        
    def stop(self): self._stop_requested = True
    def is_stop_requested(self): return self._stop_requested
        
    def process_article_wrapper(self, url):
        """Wrapper to handle thread-safe updating of status"""
        if self._stop_requested:
            return None
            
        result = process_article(
            url, 
            self.download_images,
            status_callback=lambda status: self.status.emit(status),
            stop_callback=self.is_stop_requested
        )
        
        if self._stop_requested:
            return None
            
        title, chapter, metadata, image_items = result
        
        if title and chapter:
            # Signal that an article was processed
            self.article_processed.emit(result)
        else:
            self.article_failed.emit(url)
            
        return result
        
    def run(self):
        try:
            self.status.emit(f"Processing {len(self.urls)} articles with {self.num_threads} threads...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_threads) as executor:
                # Use a list to hold future objects for potential cancellation
                future_list = [executor.submit(self.process_article_wrapper, url) for url in self.urls]
                
                for i, future in enumerate(concurrent.futures.as_completed(future_list)):
                    if self._stop_requested:
                        # Cancel any futures that have not yet started running
                        for f in future_list:
                            if not f.done():
                                f.cancel()
                        break
                    self.progress.emit(i + 1, len(self.urls))
            
            # Corrected logic for emitting the final status message
            if self._stop_requested:
                self.status.emit("Processing stopped by user")
            else:
                self.status.emit("Processing complete.")
                
            self.finished.emit()
        except Exception as e:
            logging.error(f"Error in ArticleProcessWorker: {e}", exc_info=True)
            self.status.emit(f"Error processing articles: {str(e)}")
            self.finished.emit()


class EpubCreationWorker(QThread):
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    finished = pyqtSignal(list)


    
    def __init__(self, chapters, save_dir, epub_title, author, cover_path=None, split=None):
        super().__init__()
        self.chapters = chapters
        self.save_dir = save_dir
        self.epub_title = epub_title
        self.author = author
        self.cover_path = cover_path
        self.split = split
        self._stop_requested = False
        
    def stop(self): self._stop_requested = True
        
    def run(self):
        try:
            if not self.chapters:
                self.status.emit("No articles to create EPUB from."); self.finished.emit([]); return
            self.status.emit(f"Creating EPUB with {len(self.chapters)} articles...")
            
            generated_files = []
            if self.split:
                num_files = self.split
                total = len(self.chapters)
                chunk_size = (total + num_files - 1) // num_files
                for i in range(num_files):
                    if self._stop_requested: break
                    start, end = i * chunk_size, min((i + 1) * chunk_size, total)
                    if start < end:
                        split_chapters = self.chapters[start:end]
                        split_title = f"{self.epub_title} - Part {i+1}"
                        self.status.emit(f"Creating Part {i+1}/{num_files} with {len(split_chapters)} articles...")
                        filename = create_epub(split_chapters, self.save_dir, split_title, self.cover_path, self.author,
                                             status_callback=lambda s: self.status.emit(s))
                        if filename: generated_files.append(filename)
                        self.progress.emit(i + 1, num_files)
            else:
                filename = create_epub(self.chapters, self.save_dir, self.epub_title, self.cover_path, self.author,
                                     status_callback=lambda s: self.status.emit(s))
                if filename: generated_files.append(filename)
                self.progress.emit(1, 1)
                
            self.status.emit("EPUB creation stopped by user" if self._stop_requested else
                             f"EPUB creation complete. Generated {len(generated_files)} files.")
            self.finished.emit(generated_files)
        except Exception as e:
            logging.error(f"Error in EpubCreationWorker: {e}", exc_info=True)
            self.status.emit(f"Error creating EPUB: {str(e)}"); self.finished.emit([])

# --- Enhanced Custom Widgets ---
class StatusWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        header_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: bold; padding: 5px;")
        header_layout.addWidget(self.status_label)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Info", "Warning", "Error", "Success"])
        self.filter_combo.currentTextChanged.connect(self.filter_logs)
        header_layout.addWidget(QLabel("Filter:"))
        header_layout.addWidget(self.filter_combo)
        layout.addLayout(header_layout)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(150)
        self.log_display.setMaximumHeight(300)
        layout.addWidget(self.log_display)
        button_layout = QHBoxLayout()
        self.clear_button = QPushButton("Clear Log")
        self.clear_button.clicked.connect(self.clear_log)
        self.export_button = QPushButton("Export Log")
        self.export_button.clicked.connect(self.export_log)
        self.auto_scroll_checkbox = QCheckBox("Auto Scroll")
        self.auto_scroll_checkbox.setChecked(True)
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.auto_scroll_checkbox)
        layout.addLayout(button_layout)
        self.all_log_entries = []
        
    def set_status(self, message):
        self.status_label.setText(message)
        self.add_log_message(message, "info")
        
    def add_log_message(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = {'timestamp': timestamp, 'message': message, 'level': level,
                     'full_text': f"[{timestamp}] [{level.upper()}] {message}"}
        self.all_log_entries.append(log_entry)
        if len(self.all_log_entries) > 1000: self.all_log_entries.pop(0)
        self.refresh_display()
        
    def filter_logs(self): self.refresh_display()
    def refresh_display(self):
        filter_level = self.filter_combo.currentText().lower()
        self.log_display.clear()

        for entry in self.all_log_entries:
            if filter_level == "all" or entry['level'] == filter_level:
                # Only apply special colors for non-info levels
                if entry['level'] == "error":
                    color = "#e74c3c"  # Red
                    formatted_text = f'<span style="color: {color};">{entry["full_text"]}</span>'
                    self.log_display.append(formatted_text)
                elif entry['level'] == "warning":
                    color = "#f39c12"  # Orange
                    formatted_text = f'<span style="color: {color};">{entry["full_text"]}</span>'
                    self.log_display.append(formatted_text)
                elif entry['level'] == "success":
                    color = "#27ae60"  # Green
                    formatted_text = f'<span style="color: {color};">{entry["full_text"]}</span>'
                    self.log_display.append(formatted_text)
                else:
                    # For "info" and other levels, append plain text.
                    # This allows the main stylesheet to control the color (e.g., black for light mode).
                    self.log_display.append(entry["full_text"])
        
        if self.auto_scroll_checkbox.isChecked():
            # Scroll to the bottom
            self.log_display.verticalScrollBar().setValue(self.log_display.verticalScrollBar().maximum())
            
    def clear_log(self):
        self.all_log_entries = []
        self.log_display.clear()
        self.add_log_message("Log cleared", "info")
        
    def export_log(self):
        try:
            filename, _ = QFileDialog.getSaveFileName(self, "Export Log",
                f"mises_epub_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", "Text Files (*.txt)")
            if filename:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"Mises Wire EPUB Generator Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" + "="*50 + "\n\n")
                    for entry in self.all_log_entries: f.write(entry['full_text'] + '\n')
                self.add_log_message(f"Log exported to {filename}", "success")
        except Exception as e:
            self.add_log_message(f"Failed to export log: {e}", "error")

class ArticleListWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        self.header_layout = QHBoxLayout()
        self.count_label = QLabel("0 articles")
        self.count_label.setStyleSheet("font-weight: bold;")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search articles...")
        self.search_input.textChanged.connect(self.filter_articles)
        self.header_layout.addWidget(self.count_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.search_input)
        layout.addLayout(self.header_layout)
        self.article_list = QListWidget()
        self.article_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.article_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.article_list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.article_list)
        self.actions_layout = QGridLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.article_list.selectAll)
        self.select_none_button = QPushButton("Select None")
        self.select_none_button.clicked.connect(self.article_list.clearSelection)
        self.remove_selected_button = QPushButton("Remove Selected")
        self.remove_selected_button.clicked.connect(self.remove_selected)
        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self.clear_articles)
        self.actions_layout.addWidget(self.select_all_button, 0, 0)
        self.actions_layout.addWidget(self.select_none_button, 0, 1)
        self.actions_layout.addWidget(self.remove_selected_button, 1, 0)
        self.actions_layout.addWidget(self.clear_button, 1, 1)
        layout.addLayout(self.actions_layout)
        self.articles = {}  # {url: (title, metadata, status)}
        
    def add_article(self, url, title=None, metadata=None, status="pending"):
        if url in self.articles: return False
        self.articles[url] = (title or self.extract_title_from_url(url), metadata, status)
        self.filter_articles()
        return True
        
    def add_articles(self, urls):
        # This method is for BATCH additions and is now efficient.
        added = 0
        # First, update the internal dictionary without touching the UI.
        for url in urls:
            if url not in self.articles:
                self.articles[url] = (self.extract_title_from_url(url), None, "pending")
                added += 1
        
        # After all dictionary updates, refresh the UI widget once.
        if added > 0:
            self.filter_articles()
        
        return added

        
    def update_article_status(self, url, status, title=None):
        if url in self.articles:
            old_title, old_metadata, _ = self.articles[url]
            self.articles[url] = (title or old_title, old_metadata, status)
            self.filter_articles()

    def update_article_statuses(self, urls, status):
        """Efficiently updates the status for a batch of URLs and refreshes the UI once."""
        for url in urls:
            if url in self.articles:
                # Unpack, update status, and repack the tuple
                title, metadata, _ = self.articles[url]
                self.articles[url] = (title, metadata, status)
        
        # After updating all the data, refresh the visual list just once.
        self.filter_articles()
        
        
    def clear_articles(self):
        if self.articles and QMessageBox.question(self, "Confirm Clear",
            "Are you sure you want to clear all articles?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.articles.clear()
            self.filter_articles()
        
    def remove_selected(self):
        selected_items = self.article_list.selectedItems()
        if not selected_items: return
        if QMessageBox.question(self, "Confirm Removal",
            f"Remove {len(selected_items)} selected article(s)?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            urls_to_remove = {item.data(Qt.UserRole) for item in selected_items}
            self.articles = {url: data for url, data in self.articles.items() if url not in urls_to_remove}
            self.filter_articles()
        
    # EDIT THIS METHOD
    def filter_articles(self):
        search_text = self.search_input.text().lower()
        
        self.article_list.setUpdatesEnabled(False)  # <<< ADD THIS
        try:
            self.article_list.clear()
            filtered_count = 0
            sorted_articles = sorted(self.articles.items(), key=lambda item: item[1][0]) # Sort by title
            for url, (title, metadata, status) in sorted_articles:
                if search_text in title.lower() or search_text in url.lower() or search_text in status.lower():
                    item = QListWidgetItem()
                    status_color = {"pending": "#f39c12", "processing": "#3498db", "completed": "#27ae60",
                                    "failed": "#e74c3c"}.get(status, "#95a5a6")
                    item.setText(f"[{status.upper()}] {title}")
                    item.setToolTip(f"URL: {url}\nStatus: {status}")
                    item.setData(Qt.UserRole, url)
                    item.setForeground(QColor(status_color))
                    self.article_list.addItem(item)
                    filtered_count += 1
            self.update_count(filtered_count)
        finally:
            self.article_list.setUpdatesEnabled(True) # <<< ADD THIS
            
        
    def update_count(self, filtered_count):
        total = len(self.articles)
        self.count_label.setText(f"{total} article{'s' if total != 1 else ''}" if filtered_count == total
                                 else f"{filtered_count}/{total} article{'s' if total != 1 else ''}")
        
    def get_urls(self): return list(self.articles.keys())
    def get_selected_urls(self): return [item.data(Qt.UserRole) for item in self.article_list.selectedItems()]
        
    def extract_title_from_url(self, url):
        try:
            from urllib.parse import unquote
            path = unquote(url.split('/')[-1])
            return ' '.join(word.capitalize() for word in path.replace('-', ' ').replace('_', ' ').split())[:100]
        except: return "Unknown Article"
            
    def show_context_menu(self, position):
        item = self.article_list.itemAt(position)
        if not item: return
        menu = QMenu(self)
        open_url_action = menu.addAction("Open URL in Browser")
        copy_url_action = menu.addAction("Copy URL")
        copy_title_action = menu.addAction("Copy Title")
        menu.addSeparator()
        remove_action = menu.addAction("Remove Article")
        action = menu.exec_(self.article_list.mapToGlobal(position))
        url = item.data(Qt.UserRole)
        if action == open_url_action and url: QDesktopServices.openUrl(QUrl(url))
        elif action == copy_url_action and url: QApplication.clipboard().setText(url)
        elif action == copy_title_action: QApplication.clipboard().setText(item.text().split('] ', 1)[-1])
        elif action == remove_action and url:
            self.articles.pop(url, None)
            self.filter_articles()

class CoverPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(200, 300)
        self.setMaximumSize(300, 400)
        layout = QVBoxLayout(self)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(250)
        self.browse_button = QPushButton("Browse for Cover Image")
        self.browse_button.clicked.connect(self.browse_image)
        self.clear_button = QPushButton("Clear Cover")
        self.clear_button.clicked.connect(self.clear_image)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.browse_button)
        layout.addWidget(self.clear_button)
        self.current_image_path = None
        self.clear_image()
            
    def browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Cover Image", "",
            "Image Files (*.jpg *.jpeg *.png *.bmp *.gif)")
        if file_path: self.set_image(file_path)
            
    def set_image(self, file_path):
        try:
            pixmap = QPixmap(file_path)
            if pixmap.isNull(): raise ValueError("Invalid image file")
            self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview_label.setText("")
            self.current_image_path = file_path
            self.clear_button.setEnabled(True)
            self.preview_label.setStyleSheet("border: 2px solid #3498db; border-radius: 8px; background-color: #ffffff;")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load image: {e}")
            
    def clear_image(self):
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("Drop cover image here\nor click to browse")
        self.current_image_path = None
        self.clear_button.setEnabled(False)
        self.preview_label.setStyleSheet("border: 2px dashed #cccccc; border-radius: 8px; color: #666666;")
        
    def get_image_path(self): return self.current_image_path
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                fp = urls[0].toLocalFile()
                if any(fp.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']):
                    event.acceptProposedAction()
                    
    def dropEvent(self, event):
        if event.mimeData().hasUrls(): self.set_image(event.mimeData().urls()[0].toLocalFile())

class AdvancedSettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Advanced Settings")
        self.setMinimumSize(500, 400)
        layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        self.setup_network_tab()
        self.setup_processing_tab()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self.reset_to_defaults)
        layout.addWidget(buttons)
        self.load_settings()
        
    def setup_network_tab(self):
        tab, layout = QWidget(), QFormLayout()
        tab.setLayout(layout)
        self.timeout_spinbox = QSpinBox()
        self.timeout_spinbox.setRange(5, 300); self.timeout_spinbox.setSuffix(" s")
        layout.addRow("Request Timeout:", self.timeout_spinbox)
        self.use_proxy_checkbox = QCheckBox("Use Proxy")
        layout.addRow(self.use_proxy_checkbox)
        self.proxy_input = QLineEdit(); self.proxy_input.setPlaceholderText("http://proxy:port")
        layout.addRow("Proxy URL:", self.proxy_input)
        self.verify_ssl_checkbox = QCheckBox("Verify SSL Certificates")
        layout.addRow(self.verify_ssl_checkbox)
        self.tab_widget.addTab(tab, "Network")
        
    def setup_processing_tab(self):
        tab, layout = QWidget(), QFormLayout()
        tab.setLayout(layout)
        self.enable_cache_checkbox = QCheckBox("Enable Caching")
        layout.addRow(self.enable_cache_checkbox)
        cache_layout = QHBoxLayout()
        self.cache_dir_input = QLineEdit()
        cache_browse_button = QPushButton("Browse...")
        cache_browse_button.clicked.connect(self.browse_cache_dir)
        cache_layout.addWidget(self.cache_dir_input)
        cache_layout.addWidget(cache_browse_button)
        layout.addRow("Cache Directory:", cache_layout)
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        layout.addRow("Log Level:", self.log_level_combo)
        self.tab_widget.addTab(tab, "Processing & Cache")

    def browse_cache_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Cache Directory")
        if directory: self.cache_dir_input.setText(directory)
            
    def load_settings(self):
        self.timeout_spinbox.setValue(self.settings.value("advanced/timeout", 30, type=int))
        self.use_proxy_checkbox.setChecked(self.settings.value("advanced/use_proxy", False, type=bool))
        self.proxy_input.setText(self.settings.value("advanced/proxy_url", "", type=str))
        self.verify_ssl_checkbox.setChecked(self.settings.value("advanced/verify_ssl", True, type=bool))
        self.enable_cache_checkbox.setChecked(self.settings.value("advanced/enable_cache", False, type=bool))
        self.cache_dir_input.setText(self.settings.value("advanced/cache_dir",
            os.path.join(QStandardPaths.writableLocation(QStandardPaths.CacheLocation), "html_cache"), type=str))
        self.log_level_combo.setCurrentText(self.settings.value("advanced/log_level", "INFO", type=str))

    def save_settings(self):
        self.settings.setValue("advanced/timeout", self.timeout_spinbox.value())
        self.settings.setValue("advanced/use_proxy", self.use_proxy_checkbox.isChecked())
        self.settings.setValue("advanced/proxy_url", self.proxy_input.text())
        self.settings.setValue("advanced/verify_ssl", self.verify_ssl_checkbox.isChecked())
        self.settings.setValue("advanced/enable_cache", self.enable_cache_checkbox.isChecked())
        self.settings.setValue("advanced/cache_dir", self.cache_dir_input.text())
        self.settings.setValue("advanced/log_level", self.log_level_combo.currentText())
        
    def reset_to_defaults(self):
        if QMessageBox.question(self, "Reset Settings", "Reset all settings to defaults?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            for key in self.settings.allKeys():
                if key.startswith("advanced/"): self.settings.remove(key)
            self.load_settings()
            
    def accept(self): self.save_settings(); super().accept()

# --- Enhanced Main Application ---
class MisesWireApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.setWindowIcon(QIcon(self.style().standardPixmap(QStyle.SP_FileIcon)))
        self.settings = QSettings()
        self.processed_chapters, self.current_worker = [], None
        self.is_dark_theme = self.settings.value("ui/dark_theme", False, type=bool)
        self.setup_ui()
        self.setup_menu_bar()
        self.setup_tool_bar()
        self.setup_status_bar()
        self.load_settings()
        self.apply_theme()
        self.setup_signal_connections()
        
    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.main_splitter)
        self.setup_left_panel()
        self.setup_right_panel()
        self.main_splitter.setSizes([450, 750])
        
    def setup_left_panel(self):
        self.tab_widget = QTabWidget()
        self.main_splitter.addWidget(self.tab_widget)
        self.setup_source_tab()
        self.setup_processing_tab()
        self.setup_export_tab()
        
    def setup_right_panel(self):
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        self.article_list_widget = ArticleListWidget()
        self.status_widget = StatusWidget()
        right_layout.addWidget(self.article_list_widget)
        right_layout.addWidget(self.status_widget)
        self.main_splitter.addWidget(right_widget)

    def setup_source_tab(self):
        tab, layout = QWidget(), QVBoxLayout()
        tab.setLayout(layout)

        # Group for picking the source type
        source_type_groupbox = QGroupBox("📚 Source Type")
        source_type_layout = QVBoxLayout(source_type_groupbox)
        self.source_type_group = QButtonGroup()
        
        self.source_index_radio = QRadioButton("Fetch from Index Pages")
        self.source_index_radio.setChecked(True)
        self.source_url_radio = QRadioButton("Add Single Article URL")
        self.source_list_radio = QRadioButton("Add from Custom List of URLs")
        
        self.source_type_group.addButton(self.source_index_radio, 0)
        self.source_type_group.addButton(self.source_url_radio, 1)
        self.source_type_group.addButton(self.source_list_radio, 2)
        
        source_type_layout.addWidget(self.source_index_radio)
        source_type_layout.addWidget(self.source_url_radio)
        source_type_layout.addWidget(self.source_list_radio)
        layout.addWidget(source_type_groupbox)
        
        # Group for Index Fetch configuration
        self.index_config_group = QGroupBox("Index Source Configuration")
        index_config_layout = QFormLayout(self.index_config_group)
        
        self.wire_checkbox = QCheckBox("Mises Wire")
        self.wire_checkbox.setChecked(True)
        self.wire_pages_spinbox = QSpinBox(); self.wire_pages_spinbox.setRange(1, 9999); self.wire_pages_spinbox.setValue(50)
        wire_layout = QHBoxLayout(); wire_layout.addWidget(QLabel("Max Pages:")); wire_layout.addWidget(self.wire_pages_spinbox)
        index_config_layout.addRow(self.wire_checkbox, wire_layout)
        
        self.pm_checkbox = QCheckBox("Power & Market")
        self.pm_pages_spinbox = QSpinBox(); self.pm_pages_spinbox.setRange(1, 9999); self.pm_pages_spinbox.setValue(10)
        pm_layout = QHBoxLayout(); pm_layout.addWidget(QLabel("Max Pages:")); pm_layout.addWidget(self.pm_pages_spinbox)
        index_config_layout.addRow(self.pm_checkbox, pm_layout)
        
        # Add thread controls for fetching
        threads_layout = QHBoxLayout()
        self.fetch_threads_spinbox = QSpinBox()
        self.fetch_threads_spinbox.setRange(1, 32)
        self.fetch_threads_spinbox.setValue(8) # A good default for fetching
        self.fetch_threads_slider = QSlider(Qt.Horizontal)
        self.fetch_threads_slider.setRange(1, 32)
        self.fetch_threads_slider.setValue(8)
        threads_layout.addWidget(self.fetch_threads_spinbox)
        threads_layout.addWidget(self.fetch_threads_slider)
        index_config_layout.addRow("Fetching Threads:", threads_layout)
        
        self.stop_on_no_new_links = QCheckBox("Stop when no new unique links are found"); self.stop_on_no_new_links.setChecked(True)
        index_config_layout.addRow(self.stop_on_no_new_links)
        layout.addWidget(self.index_config_group)
        
        # Controls for Single URL / List
        self.specific_url_input = QLineEdit(); self.specific_url_input.setPlaceholderText("https://mises.org/wire/article-title")
        layout.addWidget(self.specific_url_input)
        
        self.url_list_text = QTextEdit(); self.url_list_text.setPlaceholderText("Enter URLs, one per line..."); self.url_list_text.setMaximumHeight(150)
        layout.addWidget(self.url_list_text)
        
        # Connect radio button to UI update function
        self.source_type_group.buttonClicked.connect(self.update_source_ui)
        
        button_layout = QHBoxLayout()
        self.fetch_button = QPushButton("🔍 Fetch / Add Articles")
        self.stop_button = QPushButton("⏹️ Stop"); self.stop_button.setVisible(False)
        button_layout.addWidget(self.fetch_button); button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)
        
        self.fetch_progress = QProgressBar(); self.fetch_progress.setVisible(False)
        self.fetch_status_label = QLabel(""); self.fetch_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.fetch_progress); layout.addWidget(self.fetch_status_label)
        layout.addStretch()
        self.tab_widget.addTab(tab, "📚 Source")

        # Initial UI state
        self.update_source_ui()

    def update_source_ui(self):
        source_type = self.source_type_group.checkedId()
        self.index_config_group.setVisible(source_type == 0)
        self.specific_url_input.setVisible(source_type == 1)
        self.url_list_text.setVisible(source_type == 2)
        
    def setup_processing_tab(self):
        tab, layout = QWidget(), QVBoxLayout()
        tab.setLayout(layout)
        options_group = QGroupBox("⚙️ Processing Configuration")
        options_layout = QFormLayout(options_group)
        self.download_images_checkbox = QCheckBox("Download and embed images"); self.download_images_checkbox.setChecked(True)
        options_layout.addRow("Images:", self.download_images_checkbox)
        
        threads_layout = QHBoxLayout(); self.threads_spinbox = QSpinBox(); self.threads_spinbox.setRange(1, 32); self.threads_spinbox.setValue(5)
        self.threads_slider = QSlider(Qt.Horizontal); self.threads_slider.setRange(1, 32); self.threads_slider.setValue(5)
        threads_layout.addWidget(self.threads_spinbox); threads_layout.addWidget(self.threads_slider)
        options_layout.addRow("Processing Threads:", threads_layout)
        layout.addWidget(options_group)
        
        self.process_button = QPushButton("🚀 Process Articles"); self.process_button.setEnabled(False)
        layout.addWidget(self.process_button)
        self.process_progress = QProgressBar(); self.process_progress.setVisible(False)
        self.process_status_label = QLabel(""); self.process_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.process_progress); layout.addWidget(self.process_status_label)
        
        stats_group = QGroupBox("📊 Processing Statistics")
        stats_layout = QGridLayout(stats_group)
        self.stats_labels = {'total': QLabel("0"), 'processed': QLabel("0"), 'failed': QLabel("0"), 'images': QLabel("0")}
        stats_layout.addWidget(QLabel("Total Queued:"), 0, 0); stats_layout.addWidget(self.stats_labels['total'], 0, 1)
        stats_layout.addWidget(QLabel("Processed:"), 1, 0); stats_layout.addWidget(self.stats_labels['processed'], 1, 1)
        stats_layout.addWidget(QLabel("Failed:"), 2, 0); stats_layout.addWidget(self.stats_labels['failed'], 2, 1)
        layout.addWidget(stats_group)
        layout.addStretch()
        self.tab_widget.addTab(tab, "⚙️ Processing")
        
    def setup_export_tab(self):
        tab, layout = QWidget(), QVBoxLayout()
        tab.setLayout(layout)
        export_group = QGroupBox("📦 EPUB Export Configuration")
        export_layout = QFormLayout(export_group)
        self.epub_title_input = QLineEdit("Mises.org Collection"); export_layout.addRow("EPUB Title:", self.epub_title_input)
        self.author_input = QLineEdit("Mises.org"); export_layout.addRow("Author:", self.author_input)
        
        save_layout = QHBoxLayout(); self.save_dir_input = QLineEdit()
        browse_save_button = QPushButton("Browse..."); browse_save_button.clicked.connect(self.browse_save_dir)
        save_layout.addWidget(self.save_dir_input); save_layout.addWidget(browse_save_button)
        export_layout.addRow("Save Directory:", save_layout)

        split_layout = QHBoxLayout(); self.split_epub_checkbox = QCheckBox("Split into multiple files");
        self.split_count_spinbox = QSpinBox(); self.split_count_spinbox.setRange(2, 100); self.split_count_spinbox.setEnabled(False)
        split_layout.addWidget(self.split_epub_checkbox); split_layout.addWidget(self.split_count_spinbox);
        export_layout.addRow("Splitting:", split_layout)
        layout.addWidget(export_group)

        self.cover_preview = CoverPreviewWidget()
        layout.addWidget(self.cover_preview)
        
        export_button_layout = QHBoxLayout()
        self.create_epub_button = QPushButton("💾 Create EPUB"); self.create_epub_button.setEnabled(False)
        self.open_folder_button = QPushButton("📂 Open Folder"); self.open_folder_button.setEnabled(False)
        export_button_layout.addWidget(self.create_epub_button)
        export_button_layout.addWidget(self.open_folder_button)
        layout.addLayout(export_button_layout)
        self.epub_progress = QProgressBar(); self.epub_progress.setVisible(False)
        layout.addWidget(self.epub_progress)
        layout.addStretch()
        self.tab_widget.addTab(tab, "💾 Export")

    def setup_menu_bar(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction("E&xit", self.close, QKeySequence.Quit)
        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction("&Advanced Settings...", self.show_advanced_settings)
        view_menu = menu.addMenu("&View")
        self.toggle_theme_action = view_menu.addAction("Toggle Dark/Light Theme", self.toggle_theme)
        help_menu = menu.addMenu("&Help")
        help_menu.addAction("&About", self.show_about_dialog)

    def setup_tool_bar(self):
        toolbar = self.addToolBar("Main Toolbar")
        toolbar.addAction(self.toggle_theme_action)
        toolbar.addAction("Settings", self.show_advanced_settings)
    
    def setup_status_bar(self):
        self.statusBar().showMessage("Ready")

    def setup_signal_connections(self):
        # --- Source Tab Connections ---
        self.fetch_button.clicked.connect(self.fetch_articles)
        self.stop_button.clicked.connect(self.stop_current_worker)
        
        # Connect the new fetching thread slider and spinbox to keep them in sync
        self.fetch_threads_slider.valueChanged.connect(self.fetch_threads_spinbox.setValue)
        self.fetch_threads_spinbox.valueChanged.connect(self.fetch_threads_slider.setValue)

        # --- Processing Tab Connections ---
        # Connect the processing thread slider and spinbox to keep them in sync
        self.threads_slider.valueChanged.connect(self.threads_spinbox.setValue)
        self.threads_spinbox.valueChanged.connect(self.threads_slider.setValue)
        self.process_button.clicked.connect(self.process_articles)

        # --- Export Tab Connections ---
        self.create_epub_button.clicked.connect(self.create_epub_file)
        self.split_epub_checkbox.stateChanged.connect(self.split_count_spinbox.setEnabled)
        self.open_folder_button.clicked.connect(self.open_destination_folder)

        # --- Article List Widget Connections ---
        # CRITICAL FIX: The following line is commented out. Connecting it causes the UI to freeze
        # by trying to update the stats thousands of times during a batch add.
        # The UI is now updated manually at the end of batch operations.
        # self.article_list_widget.article_list.model().rowsInserted.connect(self.update_ui_state)
        
        # This connection is safe because removing items is not a batch operation.
        self.article_list_widget.article_list.model().rowsRemoved.connect(self.update_ui_state)

    def closeEvent(self, event):
        self.save_settings()
        event.accept()
    def open_destination_folder(self):
            folder_path = self.save_dir_input.text()
            if os.path.isdir(folder_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))
            else:
                QMessageBox.warning(self, "Folder Not Found", f"The directory does not exist:\n{folder_path}")

    def load_settings(self):
        self.restoreGeometry(self.settings.value("ui/geometry", QByteArray()))
        self.restoreState(self.settings.value("ui/windowState", QByteArray()))
        self.main_splitter.restoreState(self.settings.value("ui/splitterState", QByteArray()))
        self.save_dir_input.setText(self.settings.value("paths/save_dir", QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)))
        self.apply_advanced_settings()

    def save_settings(self):
        self.settings.setValue("ui/geometry", self.saveGeometry())
        self.settings.setValue("ui/windowState", self.saveState())
        self.settings.setValue("ui/splitterState", self.main_splitter.saveState())
        self.settings.setValue("ui/dark_theme", self.is_dark_theme)
        self.settings.setValue("paths/save_dir", self.save_dir_input.text())
        
    def apply_advanced_settings(self):
        global TIMEOUT, PROXIES, VERIFY, CACHE_DIR
        TIMEOUT = self.settings.value("advanced/timeout", 30, type=int)
        if self.settings.value("advanced/use_proxy", False, type=bool):
            proxy_url = self.settings.value("advanced/proxy_url", "", type=str)
            PROXIES = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
        else: PROXIES = {}
        VERIFY = certifi.where() if self.settings.value("advanced/verify_ssl", True, type=bool) else False
        CACHE_DIR = self.settings.value("advanced/cache_dir", "") if self.settings.value("advanced/enable_cache", False, type=bool) else None

    def toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        self.apply_theme()
    
    def apply_theme(self):
        self.setStyleSheet(DARK_STYLESHEET if self.is_dark_theme else LIGHT_STYLESHEET)
        self.cover_preview.clear_image() # Re-apply style

    def browse_save_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.save_dir_input.text())
        if directory: self.save_dir_input.setText(directory)

    def show_advanced_settings(self):
        dialog = AdvancedSettingsDialog(self.settings, self)
        if dialog.exec_(): self.apply_advanced_settings()
    
    def show_about_dialog(self):
        QMessageBox.about(self, f"About {APP_NAME}", f"Version {APP_VERSION}\n\nA tool to download and compile Mises.org articles into EPUB format.")

    def update_ui_state(self):
        has_articles = self.article_list_widget.article_list.count() > 0
        has_processed = len(self.processed_chapters) > 0
        self.process_button.setEnabled(has_articles)
        self.create_epub_button.setEnabled(has_processed)
        self.stats_labels['total'].setText(str(self.article_list_widget.article_list.count()))
        self.stats_labels['processed'].setText(str(len(self.processed_chapters)))
        failed_count = sum(1 for _, (_, _, status) in self.article_list_widget.articles.items() if status == 'failed')
        self.stats_labels['failed'].setText(str(failed_count))

    def stop_current_worker(self):
        if self.current_worker and self.current_worker.isRunning():
            self.status_widget.add_log_message("Stop request sent to worker.", "warning")
            self.current_worker.stop()

    def set_busy(self, busy, task=""):
        self.fetch_button.setVisible(not busy)
        self.process_button.setVisible(not busy)
        self.create_epub_button.setVisible(not busy)
        self.stop_button.setVisible(busy)
        for i in range(self.tab_widget.count()): self.tab_widget.widget(i).setEnabled(not busy)
        if task == "fetch": self.fetch_progress.setVisible(busy)
        elif task == "process": self.process_progress.setVisible(busy)
        elif task == "epub": self.epub_progress.setVisible(busy)
        if not busy:
            self.fetch_progress.setVisible(False); self.process_progress.setVisible(False); self.epub_progress.setVisible(False)
            self.current_worker = None

    def fetch_articles(self):
        source_type = self.source_type_group.checkedId()
        
        if source_type == 0: # Index Fetch
            fetch_tasks = []
            if self.wire_checkbox.isChecked():
                fetch_tasks.append({
                    'name': 'Mises Wire',
                    'url': 'https://mises.org/wire',
                    'pages': self.wire_pages_spinbox.value()
                })
            if self.pm_checkbox.isChecked():
                fetch_tasks.append({
                    'name': 'Power & Market',
                    'url': 'https://mises.org/power-market',
                    'pages': self.pm_pages_spinbox.value()
                })
            
            if not fetch_tasks:
                QMessageBox.warning(self, "No Source Selected", "Please select at least one source to fetch articles from.")
                return

            self.set_busy(True, "fetch")
            # Pass the new thread count from the UI to the worker
            self.current_worker = ArticleFetchWorker(
                fetch_tasks, 
                self.stop_on_no_new_links.isChecked(),
                num_threads=self.fetch_threads_spinbox.value()
            )
            self.current_worker.progress.connect(self.update_fetch_progress)
            self.current_worker.finished.connect(self.handle_fetch_finished)
            self.current_worker.status.connect(self.status_widget.set_status)
            self.current_worker.start()
            
        elif source_type == 1: # Single URL
            url = self.specific_url_input.text().strip()
            if is_valid_url(url):
                if self.article_list_widget.add_article(url):
                    self.status_widget.add_log_message(f"Added URL: {url}", "info")
                    self.specific_url_input.clear()
                    self.update_ui_state()
                else:
                    self.status_widget.add_log_message(f"URL already in list: {url}", "warning")
            else:
                QMessageBox.warning(self, "Invalid URL", "Please enter a valid article URL.")
                
        elif source_type == 2: # URL List
            urls = [line.strip() for line in self.url_list_text.toPlainText().splitlines() if line.strip()]
            if not urls:
                 QMessageBox.warning(self, "Empty List", "Please enter some URLs into the text box.")
                 return
            added = self.article_list_widget.add_articles(urls)
            self.status_widget.add_log_message(f"Added {added} new URLs from list.", "info")
            self.update_ui_state()

    def update_fetch_progress(self, page, max_pages, count):
        # This progress will reset for each source type, which is acceptable behavior.
        self.fetch_progress.setRange(0, max_pages)
        self.fetch_progress.setValue(page)
        self.fetch_status_label.setText(f"Scanning Page {page}/{max_pages}... | Total Found: {count}")
    
    def handle_fetch_finished(self, links):
        added = self.article_list_widget.add_articles(links)
        self.status_widget.add_log_message(f"Fetch complete. Added {added} new article URLs.", "success")
        self.fetch_status_label.setText(f"Fetch complete. Found {len(links)} total articles.")
        self.set_busy(False)
        self.update_ui_state()
        if links: self.tab_widget.setCurrentIndex(1) # Move to processing tab

    def process_articles(self):
        urls_to_process = self.article_list_widget.get_urls()
        if not urls_to_process:
            QMessageBox.information(self, "No Articles", "No articles to process.")
            return
        self.processed_chapters.clear()
        self.set_busy(True, "process")


        self.article_list_widget.update_article_statuses(urls_to_process, "processing")
        
        self.current_worker = ArticleProcessWorker(urls_to_process, self.download_images_checkbox.isChecked(), self.threads_spinbox.value())
        self.current_worker.progress.connect(self.update_process_progress)
        self.current_worker.article_processed.connect(self.handle_article_processed)
        self.current_worker.article_failed.connect(self.handle_article_failed)
        self.current_worker.finished.connect(self.handle_process_finished)
        self.current_worker.status.connect(self.status_widget.add_log_message)
        self.current_worker.start()

    def update_process_progress(self, current, total):
        self.process_progress.setRange(0, total)
        self.process_progress.setValue(current)
        self.process_status_label.setText(f"Processing {current}/{total}")

    def handle_article_processed(self, result):
            self.processed_chapters.append(result)
            title, chapter, metadata, image_items = result
            # A more robust way to get the URL
            url_match = re.search(r"href=['\"](https?://[^'\"]+)['\"]", chapter.content.decode('utf-8', errors='ignore'))
            if url_match:
                url = url_match.group(1)
                self.article_list_widget.update_article_status(url, "completed", title)

    def handle_article_failed(self, url):
        self.article_list_widget.update_article_status(url, "failed")
    
    def handle_process_finished(self):
            self.status_widget.add_log_message(f"Processing finished. {len(self.processed_chapters)} articles ready for EPUB.", "success")
            self.set_busy(False)
            self.update_ui_state()
            if self.processed_chapters: self.tab_widget.setCurrentIndex(2) # Move to export tab


    def create_epub_file(self):
        save_dir = self.save_dir_input.text()
        if not save_dir or not os.path.isdir(save_dir):
            QMessageBox.warning(self, "Invalid Directory", "Please select a valid directory to save the EPUB.")
            return
        
        self.set_busy(True, "epub")
        self.current_worker = EpubCreationWorker(
            self.processed_chapters,
            save_dir,
            self.epub_title_input.text(),
            self.author_input.text(),
            self.cover_preview.get_image_path(),
            self.split_count_spinbox.value() if self.split_epub_checkbox.isChecked() else None
        )
        self.current_worker.progress.connect(self.update_epub_progress)
        self.current_worker.finished.connect(self.handle_epub_finished)
        self.current_worker.status.connect(self.status_widget.add_log_message)
        self.current_worker.start()

    def update_epub_progress(self, current, total):
        self.epub_progress.setRange(0, total)
        self.epub_progress.setValue(current)
        if total > 1: self.status_widget.set_status(f"Creating EPUB file {current} of {total}")

    def handle_epub_finished(self, filenames):
            self.set_busy(False)
            if filenames:
                self.open_folder_button.setEnabled(True)
                folder_path = os.path.dirname(filenames[0])
                reply = QMessageBox.information(self, "Success", f"EPUB file(s) created successfully in:\n{folder_path}",
                                                QMessageBox.Ok | QMessageBox.Open)
                if reply == QMessageBox.Open:
                    self.open_destination_folder()


def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format)
    # You can add a file handler if needed
    # file_handler = logging.FileHandler("app.log")
    # file_handler.setFormatter(logging.Formatter(log_format))
    # logging.getLogger().addHandler(file_handler)

if __name__ == '__main__':
    setup_logging()
    app = QApplication(sys.argv)
    QCoreApplication.setOrganizationName("MisesWire")
    QCoreApplication.setApplicationName("EpubGenerator")
    
    main_window = MisesWireApp()
    main_window.show()
    sys.exit(app.exec_())
