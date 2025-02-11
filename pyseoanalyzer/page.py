import asyncio
import hashlib
import json
import lxml.html as lh
import os
import re
import trafilatura
import spacy
import requests

from bs4 import BeautifulSoup
from collections import Counter
from string import punctuation
from urllib.parse import urlsplit, urljoin, urlparse, urlunsplit
from urllib3.exceptions import HTTPError
from py3langid.langid import LanguageIdentifier, MODEL_FILE 
from spacy.cli import download
from sklearn.feature_extraction.text import TfidfVectorizer


from .http import http
from .stopwords import ENGLISH_STOP_WORDS

TOKEN_REGEX = re.compile(r"(?u)\b\w\w+\b")

HEADING_TAGS_XPATHS = {
    "h1": "//h1",
    "h2": "//h2",
    "h3": "//h3",
    "h4": "//h4",
    "h5": "//h5",
    "h6": "//h6",
}

ADDITIONAL_TAGS_XPATHS = {
    "title": "//title/text()",
    "meta_desc": '//meta[@name="description"]/@content',
    "viewport": '//meta[@name="viewport"]/@content',
    "charset": "//meta[@charset]/@charset",
    "canonical": '//link[@rel="canonical"]/@href',
    "alt_href": '//link[@rel="alternate"]/@href',
    "alt_hreflang": '//link[@rel="alternate"]/@hreflang',
    "og_title": '//meta[@property="og:title"]/@content',
    "og_desc": '//meta[@property="og:description"]/@content',
    "og_url": '//meta[@property="og:url"]/@content',
    "og_image": '//meta[@property="og:image"]/@content',
}

IMAGE_EXTENSIONS = set(
    [
        ".img",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".svg",
        ".webp",
        ".avif",
    ]
)

EXCLUDE_CHARS = set(["|", "/", "\\", "-", "_", "*", "&"])



class Page:
    """
    Container for each page and the core analyzer.
    """
    
    checked_links = []

    def __init__(
        self,
        url="",
        base_domain="",
        analyze_headings=False,
        analyze_extra_tags=False,
        encoding="utf-8",
    ):
        """
        Variables go here, *not* outside of __init__
        """

        self.base_domain = urlsplit(base_domain)
        self.parsed_url = urlsplit(url)
        self.url = url
        self.analyze_headings = analyze_headings
        self.analyze_extra_tags = analyze_extra_tags
        self.encoding = encoding
        self.title: str = ""
        self.author: str = ""
        self.description: str = ""
        self.hostname: str = ""
        self.sitename: str = ""
        self.date: str = ""
        self.keywords = {}
        self.warnings = []
        self.translation = bytes.maketrans(
            punctuation.encode(encoding), str(" " * len(punctuation)).encode(encoding)
        )
        self.links = []
        self.total_word_count = 0
        self.wordcount = Counter()
        self.bigrams = Counter()
        self.trigrams = Counter()
        self.stem_to_word = {}
        self.content: str = None
        self.content_hash: str = None
        self.nlp_keywords = []
        self.is_mobile_friendly: bool = False
        self.page_language: str = ""

        if analyze_headings:
            self.headings = {}

        if analyze_extra_tags:
            self.additional_info = {}


    def as_dict(self):
        """
        Returns a dictionary that can be printed
        """

        context = {
            "url": self.url,
            "title": self.title or "No title",
            "description": self.description or "No description",
            "author": self.author or "No author",
            "hostname": self.hostname or "No hostname",
            "sitename": self.sitename or "No sitename",
            "date": self.date or "No date",
            "word_count": self.total_word_count,
            "keywords": self.sort_freq_dist(self.keywords, limit=5),
            "bigrams": self.bigrams,
            "trigrams": self.trigrams,
            "warnings": self.warnings,
            "content_hash": self.content_hash,
            "nlp_keywords": self.nlp_keywords,
            "is_mobile_friendly": self.is_mobile_friendly,
            "page_language": self.page_language
        }

        if self.analyze_headings:
            context["headings"] = self.headings

        if self.analyze_extra_tags:
            context["additional_info"] = self.additional_info

        return context

    def analyze_heading_tags(self, bs):
        """
        Analyze the heading tags and populate the headings
        """

        try:
            dom = lh.fromstring(str(bs))
        except ValueError as _:
            dom = lh.fromstring(bs.encode(self.encoding))
        for tag, xpath in HEADING_TAGS_XPATHS.items():
            value = [heading.text_content() for heading in dom.xpath(xpath)]
            if value:
                self.headings.update({tag: value})

    def analyze_additional_tags(self, bs):
        """
        Analyze additional tags and populate the additional info
        """

        try:
            dom = lh.fromstring(str(bs))
        except ValueError as _:
            dom = lh.fromstring(bs.encode(self.encoding))
        for tag, xpath in ADDITIONAL_TAGS_XPATHS.items():
            value = dom.xpath(xpath)
            if value:
                self.additional_info.update({tag: value})

    def analyze(self, raw_html=None):
        """
        Analyze the page and populate the warnings list
        """

        if not raw_html:
            valid_prefixes = []

            # only allow http:// https:// and //
            for s in [
                "http://",
                "https://",
                "//",
            ]:
                valid_prefixes.append(self.url.startswith(s))

            if True not in valid_prefixes:
                self.warn(f"{self.url} does not appear to have a valid protocol.")
                return

            if self.url.startswith("//"):
                self.url = f"{self.base_domain.scheme}:{self.url}"

            if self.parsed_url.netloc != self.base_domain.netloc:
                self.warn(f"{self.url} is not part of {self.base_domain.netloc}.")
                return

            try:
                page = http.get(self.url)
            except HTTPError as e:
                self.warn(f"Returned {e}")
                return

            encoding = "utf8"

            if "content-type" in page.headers:
                encoding = page.headers["content-type"].split("charset=")[-1]

            if encoding.lower() not in ("text/html", "text/plain", self.encoding):
                self.warn(f"Can not read {encoding}")
                return
            else:
                raw_html = page.data.decode(self.encoding)

        self.content_hash = hashlib.sha1(raw_html.encode(self.encoding)).hexdigest()

        # Use trafilatura to extract metadata
        metadata = trafilatura.extract_metadata(
            filecontent=raw_html,
            default_url=self.url,
            extensive=True,
        )

        # I want to grab values from this even if they don't exist
        metadata = metadata.as_dict() if metadata else {}

        self.title = metadata.get("title", "")
        self.author = metadata.get("author", "")
        self.description = metadata.get("description", "")
        self.hostname = metadata.get("hostname", "")
        self.sitename = metadata.get("sitename", "")
        self.date = metadata.get("date", "")
        metadata_keywords = metadata.get("keywords", "")

        if len(metadata_keywords) > 0:
            self.warn(
                f"Keywords should be avoided as they are a spam indicator and no longer used by Search Engines"
            )

        self.content = self.get_all_text_from_html(raw_html)

        # remove comments, they screw with BeautifulSoup
        html_without_comments = re.sub(r"<!--.*?-->", r"", raw_html, flags=re.DOTALL)

        # use BeautifulSoup to parse the more nuanced tags
        soup_lower = BeautifulSoup(html_without_comments.lower(), "html.parser")
        soup_unmodified = BeautifulSoup(html_without_comments, "html.parser")

        self.check_canonical_tag(soup_unmodified)
        self.find_broken_links(soup_unmodified, self.base_domain)

        self.process_text(self.content["text"])

        self.analyze_noindex(soup_lower)
        self.analyze_title()
        self.analyze_description()
        self.analyze_og(soup_lower)
        self.analyze_a_tags(soup_unmodified)
        self.analyze_img_tags(soup_lower)
        self.analyze_h1_tags(soup_lower)

        if self.analyze_headings:
            self.analyze_heading_tags(soup_unmodified)

        if self.analyze_extra_tags:
            self.analyze_additional_tags(soup_unmodified)

        self.is_mobile_friendly = self.mobile_friendly_check(raw_html)

        return True

    def word_list_freq_dist(self, wordlist):
        freq = [wordlist.count(w) for w in wordlist]
        return dict(zip(wordlist, freq))

    def sort_freq_dist(self, freqdist, limit=1):
        aux = [
            (freqdist[key], self.stem_to_word[key])
            for key in freqdist
            if freqdist[key] >= limit
        ]
        aux.sort()
        aux.reverse()
        return aux

    def raw_tokenize(self, rawtext):
        return TOKEN_REGEX.findall(rawtext.lower())

    def tokenize(self, rawtext):
        return [
            word
            for word in TOKEN_REGEX.findall(rawtext.lower())
            if word not in ENGLISH_STOP_WORDS
        ]

    def process_text(self, page_text):

        language = self.rtv_text_language(page_text)
        self.page_language = language

        doc = self.create_nlp_document(page_text, language)
        tokens, raw_tokens = self.tokenize_text(doc)

        self.total_word_count = len(raw_tokens)

        self.nlp_keywords = self.extract_keywords_tfidf([" ".join(tokens)], 30)

        self.bigrams = self.extract_n_grams(doc, 2)

        self.trigrams = self.extract_n_grams(doc, 3)

        freq_dist = self.word_list_freq_dist(tokens)

        for word in freq_dist:
            cnt = freq_dist[word]

            if word not in self.stem_to_word:
                self.stem_to_word[word] = word

            if word in self.wordcount:
                self.wordcount[word] += cnt
            else:
                self.wordcount[word] = cnt

            if word in self.keywords:
                self.keywords[word] += cnt
            else:
                self.keywords[word] = cnt

    def analyze_og(self, bs):
        """
        Validate open graph tags
        """
        og_title = bs.findAll("meta", attrs={"property": "og:title"})
        og_description = bs.findAll("meta", attrs={"property": "og:description"})
        og_image = bs.findAll("meta", attrs={"property": "og:image"})

        if len(og_title) == 0:
            self.warn("Missing og:title")

        if len(og_description) == 0:
            self.warn("Missing og:description")

        if len(og_image) == 0:
            self.warn("Missing og:image")

    def analyze_title(self):
        """
        Validate the title
        """

        # getting lazy, create a local variable so save having to
        # type self.x a billion times
        t = self.title

        # calculate the length of the title once
        length = len(t)

        if length == 0:
            self.warn("Missing title tag")
            return
        elif length < 10:
            self.warn("Title tag is too short (less than 10 characters): {0}".format(t))
        elif length > 70:
            self.warn("Title tag is too long (more than 70 characters): {0}".format(t))

    def analyze_description(self):
        """
        Validate the description
        """

        # getting lazy, create a local variable so save having to
        # type self.x a billion times
        d = self.description

        # calculate the length of the description once
        length = len(d)

        if length == 0:
            self.warn("Missing description")
            return
        elif length < 140:
            self.warn(
                "Description is too short (less than 140 characters): {0}".format(d)
            )
        elif length > 255:
            self.warn(
                "Description is too long (more than 255 characters): {0}".format(d)
            )

    def analyze_noindex(self, bs):

        meta_robots = bs.find("meta", attrs={"name": "robots"})
        if meta_robots and "noindex" in meta_robots.get("content", "").lower():
            self.warn("Found tag noindex")

    def visible_tags(self, element):
        if element.parent.name in ["style", "script", "[document]"]:
            return False

        return True

    def analyze_img_tags(self, bs):
        """
        Verifies that each img has an alt and title
        """
        images = bs.find_all("img")

        for image in images:
            src = ""
            if "src" in image:
                src = image["src"]
            elif "data-src" in image:
                src = image["data-src"]
            else:
                src = image

            if len(image.get("alt", "")) == 0:
                self.warn("Image missing alt tag: {0}".format(src))

    def analyze_h1_tags(self, bs):
        """
        Make sure each page has at least one H1 tag
        """
        htags = bs.find_all("h1")

        if len(htags) == 0:
            self.warn("Each page should have at least one h1 tag")

    def analyze_a_tags(self, bs):
        """
        Add any new links (that we didn't find in the sitemap)
        """
        anchors = bs.find_all("a", href=True)

        for tag in anchors:
            tag_href = tag["href"]
            tag_text = tag.text.lower().strip()

            if len(tag.get("title", "")) == 0:
                self.warn("Anchor missing title tag: {0}".format(tag_href))

            if tag_text in ["click here", "page", "article"]:
                self.warn("Anchor text contains generic text: {0}".format(tag_text))

            if self.base_domain.netloc not in tag_href and ":" in tag_href:
                continue

            modified_url = self.rel_to_abs_url(tag_href)

            url_filename, url_file_extension = os.path.splitext(modified_url)

            # ignore links to images
            if url_file_extension in IMAGE_EXTENSIONS:
                continue

            # remove hash links to all urls
            if "#" in modified_url:
                modified_url = modified_url[: modified_url.rindex("#")]

            self.links.append(modified_url)

    def rel_to_abs_url(self, link):
        if ":" in link:
            return link

        relative_path = link
        domain = self.base_domain.netloc

        if domain[-1] == "/":
            domain = domain[:-1]

        if len(relative_path) > 0 and relative_path[0] == "?":
            if "?" in self.url:
                return f'{self.url[:self.url.index("?")]}{relative_path}'

            return f"{self.url}{relative_path}"

        if len(relative_path) > 0 and relative_path[0] != "/":
            relative_path = f"/{relative_path}"

        return f"{self.base_domain.scheme}://{domain}{relative_path}"

    def warn(self, warning):
        self.warnings.append(warning)

    def get_all_text_from_html(self, html_content):
        # Analizza l'HTML grezzo con BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Estrai tutto il testo (rimuove script, stili, ecc.)
        text = soup.get_text(separator=' ', strip=True)
        
        return {"text":text,
                "comments":""}
    
    def rtv_text_language(self, text):
        """
        Identifica la lingua del testo tra un insieme specifico di lingue: {en, de, it, fr, es}.
        
        Args:
            text (str): Il testo da analizzare.
            
        Returns:
            str: Il codice della lingua con la probabilità maggiore all'interno dell'insieme specificato,
                o 'unknown' se nessuna delle lingue dell'insieme è rilevata.
        """
        identifier = LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)
        
        # Classifica il testo
        lang, prob = identifier.classify(text)
        
        # Insieme di lingue consentite
        allowed_languages = {'en', 'it', 'fr', 'es'}
        
        # Verifica se la lingua classificata è nell'insieme consentito
        if lang in allowed_languages:
            return lang
        
        # Calcola le probabilità per tutte le lingue
        probs = identifier.rank(text)
        
        # Filtra solo le lingue nell'insieme consentito
        filtered_langs = [(language, probability) for language, probability in probs if language in allowed_languages]
        
        # Ordina per probabilità decrescente
        if filtered_langs:
            filtered_langs.sort(key=lambda x: x[1], reverse=True)
            return filtered_langs[0][0]  # Restituisci la lingua con la probabilità maggiore
        
        # Se nessuna lingua dell'insieme è trovata, assegna inglese
        return 'en'

    def create_nlp_document(self, text, language):

        if language == 'it':
            model = 'it_core_news_md'
        elif language == 'en':
            model = 'en_core_web_sm'
        elif language == 'fr':
            model = 'fr_core_news_md'
        elif language == 'es':
            model = 'es_core_news_md'
        elif language == 'de':
            model = 'de_core_news_md'
        else:
            model = 'en_core_web_sm'

        try:
            nlp = spacy.load(model)
        except OSError:
            download(model)
            nlp = spacy.load(model)

        doc = nlp(text)

        return doc

    def tokenize_text(self, doc):

        tokens = [token.text for token in doc if not token.is_punct and not token.text in EXCLUDE_CHARS and not token.is_stop]

        raw_tokens = [token.text for token in doc if not token.is_punct and not token.text in EXCLUDE_CHARS]

        return tokens, raw_tokens
    
    def extract_keywords_tfidf(self, texts, top_n=5):

        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(texts)
        feature_names = vectorizer.get_feature_names_out()
        first_doc_vector = tfidf_matrix[0].T.todense()
        tfidf_scores = [
            {"word": feature_names[i], "score": round(first_doc_vector[i, 0], 5)}
            for i in range(len(feature_names))
        ]
        return sorted(tfidf_scores, key=lambda x: x["score"], reverse=True)[:top_n]
    
    def mobile_friendly_check(self, html):

        soup = BeautifulSoup(html, "html.parser")
        # Controlla la presenza del meta-tag "viewport"
        viewport_meta = soup.find("meta", attrs={"name": "viewport"})
        if viewport_meta and "width=device-width" in viewport_meta.get("content", ""):
            return True
        # Cerca media query CSS che indicano responsività
        styles = soup.find_all("style")
        for style in styles:
            if "@media" in style.text:
                return True
        return False
    
    def extract_n_grams(self, doc, n=3):

        tokens = [token for token in doc if not token.is_punct and token.text not in EXCLUDE_CHARS and not token.is_stop]

    # Genera gli n-grammi
        ngrams = [
            " ".join(tokens[i + j].text for j in range(n))
            for i in range(len(tokens) - n + 1)
        ]
        return ngrams

    def check_canonical_tag(self, soup):
        """
        Verifica la presenza del tag <link rel="canonical"> in un oggetto BeautifulSoup.
        
        Args:
            soup (BeautifulSoup): Oggetto BeautifulSoup che rappresenta il documento HTML.

        """

        # Trova il tag canonical
        canonical_tag = soup.find("link", rel="canonical")
        
        if not (canonical_tag and canonical_tag.has_attr("href")):
            self.warn("Canonical tag not found or href attribute is missing")

    def find_broken_links(self, soup, base_url):
        """
        Trova i link non raggiungibili in una pagina web.

        Args:
            soup (BeautifulSoup): Oggetto BeautifulSoup contenente il DOM della pagina web.
            base_url (str): L'URL base da cui risolvere i link relativi.

        """
        
        # Trova tutti i tag <a> con attributo href
        for tag in soup.find_all('a', href=True):
            href = tag['href']
            
            # Escludi link mailto:
            if href.startswith(('mailto:', 'tel:')):
                continue
            
            # Controlla se il link è assoluto o relativo
            parsed_href = urlparse(href)
            if parsed_href.netloc:
                # Il link è assoluto
                link_assoluto = href
            else:
                # Il link è relativo, risolvilo rispetto alla base URL
                link_assoluto = urljoin(urlunsplit(base_url), href)

            
            link_status = self.get_link_status(link_assoluto)
            if link_status == 'broken':
                self.warn(f"Url {link_assoluto} is broken")
                continue
            elif link_status == 'good':
                continue
            
            try:
                # Effettua una richiesta HEAD per controllare il link
                response = requests.head(link_assoluto, timeout=5)
                
                # Consideriamo non raggiungibili i link con status_code >= 400
                if response.status_code >= 400:
                    self.warn(f"Url {link_assoluto} is broken")
                    Page.checked_links.append({'url':link_assoluto,
                                              'status':'broken'})
                else:
                    Page.checked_links.append({'url':link_assoluto,
                                              'status':'good'})
            except requests.RequestException:
                # Se c'è un errore nella richiesta, il link è considerato non raggiungibile
                self.warn(f"Url {link_assoluto} is broken")
                Page.checked_links.append({'url':link_assoluto,
                                            'status':'broken'})


    def get_link_status(self, url_to_check):
        """
        Trova lo status di un URL nella lista senza usare un ciclo for esplicito.
        Ritorna None se l'URL non è presente.
        """
        # Usa next() per trovare il primo elemento che corrisponde
        entry = next((item for item in Page.checked_links if item['url'] == url_to_check), None)
        return entry['status'] if entry else None
