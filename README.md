Python SEO and GEO Analyzer
===================

A modern SEO and GEO analysis tool that combines technical optimization and authentic human value. Beyond traditional site crawling and structure analysis, it uses AI to evaluate content's expertise signals, conversational engagement, and cross-platform presence. It helps you maintain strong technical foundations while ensuring your site demonstrates genuine authority and value to real users.

The AI features were heavily influenced by the clickbait-titled SEL article [A 13-point roadmap for thriving in the age of AI search](https://searchengineland.com/seo-roadmap-ai-search-449199).

Installation
------------

### PIP

```
pip install pyseoanalyzer
```

Command-line Usage
------------------

If you run without a sitemap it will start crawling at the homepage.

```sh
seoanalyze http://www.domain.com/
```

Or you can specify the path to a sitmap to seed the urls to scan list.

```sh
seoanalyze http://www.domain.com/ --sitemap path/to/sitemap.xml
```

HTML output can be generated from the analysis instead of json.

```sh
seoanalyze http://www.domain.com/ --output-format html
```

API
---

The `analyze` function returns a dictionary with the results of the crawl.

```python
from pyseoanalyzer import analyze

output = analyze(site, sitemap)

print(output)
```

In order to analyze heading tags (h1-h6) and other extra additional tags as well, the following options can be passed to the `analyze` function
```python
from pyseoanalyzer import analyze

output = analyze(site, sitemap, analyze_headings=True, analyze_extra_tags=True)

print(output)
```

By default, the `analyze` function analyzes all the existing inner links as well, which might be time consuming.
This default behaviour can be changed to analyze only the provided URL by passing the following option to the `analyze` function
```python
from pyseoanalyzer import analyze

output = analyze(site, sitemap, follow_links=False)

print(output)
```

NLP
-----

NLP functions are now performed by Spacy. 

Supported languages are

 - English
 - Italian
 - German
 - French
 - Spanish


Notes
-----

If you get `requests.exceptions.SSLError` at either the command-line or via the python-API, try using:
 - http://www.foo.bar
 
 **instead** of..
 
 -  https://www.foo.bar
