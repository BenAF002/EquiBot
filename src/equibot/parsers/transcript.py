import requests
from bs4 import BeautifulSoup
import time
import re
import os


class TranscriptScraper:
    """
    Scrapes call transcripts from Yahoo Finance
    """
    def __init__(self, ticker: str):
        self.ticker = ticker.upper()

        # yfinance robots.txt permits scraping transcripts, but blocks un-spoofed user-agents 
        # so we set a common user-agent string and include optional project/contact info for transparency
        self.project_id = os.getenv("YFINANCE_IDENTIFIER")  # optional project ID for user-agent
        self.contact = os.getenv("YFINANCE_CONTACT")        # optional contact info for user-agent

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "X-Project-Info": self.project_id if self.project_id else "",
            "X-Contact": self.contact if self.contact else "",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.get("https://finance.yahoo.com/")  # initial request to set cookies
        time.sleep(1)  # polite delay

        self.quote_page = f"https://finance.yahoo.com/quote/{ticker}"
        self.calls_page = f"{self.quote_page}/earnings-calls"

    
    def get_call_links(self) -> list[str]:
        """Get list of transcript links from earnings-calls page"""
        response = self.session.get(self.calls_page, headers={"Referer": self.quote_page})
        if response.status_code != 200:
            raise Exception(f"Failed to fetch calls page: {response.status_code}")
        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=True)
        transcript_links = [link['href'] for link in links if f'/quote/{self.ticker}/earnings/' in link['href']]
        return transcript_links
    

    def get_transcript(self, transcript_url: str | None = None, quarter: str | int | None = None, year: int | None = None) -> list[dict]:
        """
        Fetch transcript page and parse. If url or quarter/year not provided, defaults to most recent transcript.
        Args:
            transcript_url: full URL to transcript page
            quarter: quarter number (1-4) to identify transcript if url not provided
            year: year to identify transcript if url not provided
        """
        if transcript_url:
            url = transcript_url
        else:
            links = self.get_call_links()
            if quarter and year:
                pattern = f"/quote/{self.ticker}/earnings/{self.ticker}-Q{quarter}-{year}-earnings_call"
                url = next((link for link in links if pattern in link), None)
                if not url:
                    raise Exception(f"No transcript found for Q{quarter} {year}\nLinks found: {links}")
            elif links:
                url = links[0]  # default to most recent
            else:
                raise Exception("No transcripts found")

        full_url = f"https://finance.yahoo.com{url}"
        response = self.session.get(full_url, headers={"Referer": self.calls_page})
        if response.status_code != 200:
            raise Exception(f"Failed to fetch transcript page: {response.status_code}")
        
        transcript_data = []
        soup = BeautifulSoup(response.text, 'html.parser')
        blocks = soup.find_all('div', class_=lambda c: c and 'item ' in c.lower())
        
        for block in blocks:
            # get speaker name and title
            speaker = block.find('div', class_=lambda c: c and 'speaker' in c.lower())
            if speaker:
                speaker_info = speaker.find_all('span')
                speaker_name = speaker_info[0].get_text(strip=True)
                speaker_title = speaker_info[1].get_text(strip=True) if len(speaker_info) > 1 else ""
            else:
                speaker_name = "Unknown"
                speaker_title = ""

            # parse text from transcript block
            paragraphs = block.find_all('p')
            speech_text = " ".join(p.text.strip() for p in paragraphs)

            # get time-stamp if available
            ts_match = re.search(r'\d{1,2}:\d{2}:\d{2}\s', speech_text)
            if ts_match:
                speech_text = speech_text[ts_match.end():].strip()
                time_stamp = ts_match.group().strip()

            # bundle as dict in transcript data
            if len(speech_text.strip()) > 0:  # only include if there's text content
                transcript_data.append({
                    "speaker": speaker_name,
                    "title": speaker_title,
                    "time": time_stamp if ts_match else "",
                    "text": speech_text
                })

        return transcript_data