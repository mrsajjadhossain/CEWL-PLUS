#!/usr/bin/env python3
"""
CeWL++ - Advanced Web Content Analyzer & Wordlist Generator
Superior to standard CeWL with AI-powered analysis and advanced features
"""

import requests
from bs4 import BeautifulSoup
import re
import argparse
import sys
import os
import time
from urllib.parse import urljoin, urlparse
from collections import Counter, defaultdict
import threading
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import sqlite3
from contextlib import contextmanager
import logging

class AdvancedCeWL:
    def __init__(self, max_depth=2, threads=10, delay=1, min_word_length=3):
        self.max_depth = max_depth
        self.threads = threads
        self.delay = delay
        self.min_word_length = min_word_length
        self.visited_urls = set()
        self.words = Counter()
        self.emails = set()
        self.phone_numbers = set()
        self.metadata = defaultdict(list)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger('CeWL++')
        
        # Initialize headless browser for JavaScript-heavy sites
        self.setup_selenium()

    def setup_selenium(self):
        """Setup headless Chrome for JavaScript rendering"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.set_page_load_timeout(30)
        except Exception as e:
            self.logger.warning(f"Selenium setup failed: {e}")
            self.driver = None

    def extract_words_advanced(self, text):
        """Advanced word extraction with multiple techniques"""
        words = set()
        
        # Basic word extraction
        basic_words = re.findall(r'\b[a-zA-Z0-9]{%d,}\b' % self.min_word_length, text.lower())
        words.update(basic_words)
        
        # Extract camelCase words
        camel_case = re.findall(r'[a-z]+[A-Z][a-z]+', text)
        for word in camel_case:
            # Split camelCase into separate words
            split_words = re.findall(r'[A-Z]?[a-z]+', word)
            words.update([w.lower() for w in split_words if len(w) >= self.min_word_length])
        
        # Extract words with special characters (for passwords)
        special_words = re.findall(r'\b\w+[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?]+\w*\b', text)
        words.update([w.lower() for w in special_words])
        
        # Extract product names, brands (Title Case)
        title_case = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        for phrase in title_case:
            words.update([w.lower() for w in phrase.split() if len(w) >= self.min_word_length])
        
        return words

    def extract_entities(self, text, url):
        """Extract various entities from text"""
        # Email addresses
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        self.emails.update(emails)
        
        # Phone numbers (international formats)
        phone_patterns = [
            r'\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}',
            r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}',
            r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}'
        ]
        for pattern in phone_patterns:
            phones = re.findall(pattern, text)
            self.phone_numbers.update(phones)
        
        # Copyright years and versions
        years = re.findall(r'\b(19|20)\d{2}\b', text)
        versions = re.findall(r'\b(v|version)?\s*[0-9]+\.[0-9]+(\.[0-9]+)?\b', text, re.IGNORECASE)
        
        # Add to metadata
        self.metadata['years'].extend(years)
        self.metadata['versions'].extend([v[0] for v in versions if v[0]])

    def get_page_content(self, url):
        """Get page content with multiple methods"""
        content = ""
        
        try:
            # Try requests first
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            content = response.text
            
            # If minimal content, try Selenium for JS-rendered pages
            if len(content) < 1000 and self.driver:
                self.logger.info(f"Using Selenium for JS-heavy page: {url}")
                try:
                    self.driver.get(url)
                    time.sleep(2)  # Wait for JS execution
                    content = self.driver.page_source
                except:
                    pass
                    
        except Exception as e:
            self.logger.warning(f"Failed to fetch {url}: {e}")
            
        return content

    def extract_metadata(self, soup, url):
        """Extract metadata from HTML"""
        # Meta tags
        meta_tags = soup.find_all('meta')
        for meta in meta_tags:
            name = meta.get('name', '').lower()
            content = meta.get('content', '')
            if content:
                self.metadata[f'meta_{name}'].append(content)
        
        # OpenGraph tags
        og_tags = soup.find_all('meta', property=re.compile(r'^og:'))
        for tag in og_tags:
            prop = tag.get('property', '')
            content = tag.get('content', '')
            if content:
                self.metadata[prop].append(content)
        
        # JSON-LD structured data
        json_ld = soup.find_all('script', type='application/ld+json')
        for script in json_ld:
            try:
                data = json.loads(script.string)
                self.extract_json_ld(data)
            except:
                pass

    def extract_json_ld(self, data):
        """Extract information from JSON-LD structured data"""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and len(value) > 2:
                    self.metadata['json_ld'].append(f"{key}: {value}")
                elif isinstance(value, (list, dict)):
                    self.extract_json_ld(value)
        elif isinstance(data, list):
            for item in data:
                self.extract_json_ld(item)

    def analyze_page(self, url, depth=0):
        """Comprehensive page analysis"""
        if depth > self.max_depth or url in self.visited_urls:
            return
            
        self.visited_urls.add(url)
        self.logger.info(f"Analyzing [{depth}]: {url}")
        
        content = self.get_page_content(url)
        if not content:
            return
            
        soup = BeautifulSoup(content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Extract text content
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        # Extract words and entities
        words = self.extract_words_advanced(text)
        for word in words:
            self.words[word] += 1
        
        self.extract_entities(text, url)
        self.extract_metadata(soup, url)
        
        # Extract links for recursive crawling
        if depth < self.max_depth:
            links = soup.find_all('a', href=True)
            for link in links:
                full_url = urljoin(url, link['href'])
                if self.should_follow_link(full_url, url):
                    time.sleep(self.delay)  # Be polite
                    self.analyze_page(full_url, depth + 1)

    def should_follow_link(self, link, base_url):
        """Determine if we should follow a link"""
        parsed_link = urlparse(link)
        parsed_base = urlparse(base_url)
        
        # Skip external domains
        if parsed_link.netloc and parsed_link.netloc != parsed_base.netloc:
            return False
            
        # Skip common non-content links
        skip_patterns = [
            r'\.(pdf|doc|docx|xls|xlsx|ppt|pptx|zip|rar|tar|gz)$',
            r'\.(jpg|jpeg|png|gif|bmp|svg|webp)$',
            r'\.(css|js)$',
            r'^javascript:',
            r'^mailto:',
            r'^tel:',
            r'^#',
        ]
        
        for pattern in skip_patterns:
            if re.search(pattern, link, re.IGNORECASE):
                return False
                
        return True

    def generate_wordlists(self):
        """Generate multiple specialized wordlists"""
        wordlists = {}
        
        # Basic wordlist (sorted by frequency)
        wordlists['basic'] = [word for word, count in self.words.most_common()]
        
        # Password wordlist (words + numbers/special chars)
        password_words = set()
        for word in self.words:
            if len(word) >= 6:
                password_words.add(word)
                password_words.add(f"{word}123")
                password_words.add(f"{word}!")
                password_words.add(f"{word}2024")
                password_words.add(f"{word}1")
        wordlists['passwords'] = sorted(password_words)
        
        # Username wordlist (shorter words)
        wordlists['usernames'] = [word for word in self.words if 3 <= len(word) <= 12]
        
        # Directory wordlist (for fuzzing)
        wordlists['directories'] = [f"/{word}/" for word in self.words if len(word) >= 3]
        
        # API endpoints (common patterns)
        api_patterns = ['api', 'v1', 'v2', 'rest', 'graphql']
        wordlists['endpoints'] = []
        for pattern in api_patterns:
            wordlists['endpoints'].extend([f"/{pattern}/{word}", f"/{word}/{pattern}"] for word in self.words if len(word) >= 3)
        
        return wordlists

    def save_results(self, base_filename):
        """Save all results to files"""
        # Generate wordlists
        wordlists = self.generate_wordlists()
        
        # Save wordlists
        for list_type, words in wordlists.items():
            filename = f"{base_filename}_{list_type}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                for word in words:
                    f.write(f"{word}\n")
            self.logger.info(f"Saved {len(words)} words to {filename}")
        
        # Save emails
        if self.emails:
            with open(f"{base_filename}_emails.txt", 'w') as f:
                for email in sorted(self.emails):
                    f.write(f"{email}\n")
        
        # Save phone numbers
        if self.phone_numbers:
            with open(f"{base_filename}_phones.txt", 'w') as f:
                for phone in sorted(self.phone_numbers):
                    f.write(f"{phone}\n")
        
        # Save metadata
        with open(f"{base_filename}_metadata.json", 'w') as f:
            json.dump(dict(self.metadata), f, indent=2)
        
        # Save analysis report
        report = {
            'urls_analyzed': len(self.visited_urls),
            'unique_words': len(self.words),
            'emails_found': len(self.emails),
            'phones_found': len(self.phone_numbers),
            'top_words': self.words.most_common(20)
        }
        
        with open(f"{base_filename}_report.json", 'w') as f:
            json.dump(report, f, indent=2)

    def analyze_site(self, start_url):
        """Main analysis function"""
        self.logger.info(f"Starting advanced analysis of: {start_url}")
        start_time = time.time()
        
        self.analyze_page(start_url)
        
        # Multi-threaded analysis for larger sites
        if len(self.visited_urls) < 50:  # If small site, analyze more deeply
            with ThreadPoolExecutor(max_workers=self.threads) as executor:
                futures = []
                for url in list(self.visited_urls):
                    futures.append(executor.submit(self.analyze_page, url, 1))
                
                for future in futures:
                    future.result()
        
        analysis_time = time.time() - start_time
        self.logger.info(f"Analysis completed in {analysis_time:.2f} seconds")
        self.logger.info(f"Analyzed {len(self.visited_urls)} pages")
        self.logger.info(f"Found {len(self.words)} unique words")
        self.logger.info(f"Found {len(self.emails)} email addresses")
        self.logger.info(f"Found {len(self.phone_numbers)} phone numbers")

    def __del__(self):
        """Cleanup Selenium driver"""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()

def main():
    parser = argparse.ArgumentParser(description='CeWL++ - Advanced Web Content Analyzer')
    parser.add_argument('url', help='Target URL to analyze')
    parser.add_argument('-d', '--depth', type=int, default=2, help='Crawling depth (default: 2)')
    parser.add_argument('-t', '--threads', type=int, default=10, help='Number of threads (default: 10)')
    parser.add_argument('--delay', type=float, default=1, help='Delay between requests (default: 1)')
    parser.add_argument('-m', '--min-length', type=int, default=3, help='Minimum word length (default: 3)')
    parser.add_argument('-o', '--output', help='Output filename base')
    
    args = parser.parse_args()
    
    if not args.output:
        domain = urlparse(args.url).netloc
        args.output = f"cewlpp_{domain}_{int(time.time())}"
    
    # Create analyzer
    analyzer = AdvancedCeWL(
        max_depth=args.depth,
        threads=args.threads,
        delay=args.delay,
        min_word_length=args.min_length
    )
    
    try:
        # Perform analysis
        analyzer.analyze_site(args.url)
        
        # Save results
        analyzer.save_results(args.output)
        
        print(f"\n🎯 Analysis Complete!")
        print(f"📁 Results saved with base name: {args.output}")
        print(f"📊 Pages analyzed: {len(analyzer.visited_urls)}")
        print(f"🔤 Unique words: {len(analyzer.words)}")
        print(f"📧 Emails found: {len(analyzer.emails)}")
        print(f"📞 Phone numbers: {len(analyzer.phone_numbers)}")
        
        # Show top words
        print(f"\n🏆 Top 10 words:")
        for word, count in analyzer.words.most_common(10):
            print(f"  {word}: {count} occurrences")
            
    except KeyboardInterrupt:
        print("\n⚠️  Analysis interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if hasattr(analyzer, 'driver') and analyzer.driver:
            analyzer.driver.quit()

if __name__ == "__main__":
    main()
