"""Company identity and conservative evidence checks; no unsupported translation."""
import re
import unicodedata
from urllib.parse import urlsplit


def normalize(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", unicodedata.normalize("NFKC", text).casefold())


def aliases(name):
    parts = [name, *re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z][a-zA-Z\s&.-]*", name)]
    return {normalize(part) for part in parts if len(normalize(part)) >= 2}


def matches(name, hit):
    body = normalize(hit.title + "\n" + hit.site_name + "\n" + hit.evidence)
    return any(alias in body for alias in aliases(name))


def source_type(hit):
    host = urlsplit(hit.url).hostname or ""
    return "百科" if (host.startswith("baike.") or host.endswith("wikipedia.org")
                       or "百科" in hit.site_name) else "网页"


def official_score(name, hit):
    if not matches(name, hit) or source_type(hit) == "百科":
        return 0
    host = urlsplit(hit.url).hostname or ""
    # Aggregators and articles cannot become official sites from SEO titles.
    if any(host == domain or host.endswith("." + domain) for domain in
           ("zhihu.com", "zhipin.com", "liepin.com", "qcc.com", "tianyancha.com", "baidu.com", "sohu.com", "163.com")):
        return 0
    labels = host.casefold().split(".")
    latin = [alias for alias in aliases(name) if re.fullmatch(r"[a-z0-9]+", alias)]
    domain_match = any(alias in labels for alias in latin)
    official_title = bool(re.search(r"官网|官方网站|official (?:site|website)", hit.title, re.I))
    return 2 * domain_match + official_title


def supported_paraphrase(text, quote):
    """Allow reordered/shortened wording, reject new numbers, negation and claims.

    This deliberately accepts only strong lexical coverage; ambiguous semantic
    rewrites are omitted rather than billed for another model call.
    """
    if not set(re.findall(r"\d+(?:\.\d+)?", text)) <= set(re.findall(r"\d+(?:\.\d+)?", quote)):
        return False
    for marker in ("不", "未", "无", "非", "领先", "最大", "第一", "唯一", "上市", "成立"):
        if (marker in text) != (marker in quote):
            return False
    if text in quote:
        return True

    def keywords(value):
        value = unicodedata.normalize("NFKC", value).casefold()
        value = re.sub(r"是一家|一家公司|公司|企业|行业|主要|专注于|致力于|提供|属于|从事|一家|的|了|和|以及|及|与", " ", value)
        chunks = re.findall(r"[a-z][a-z0-9]*|[\u4e00-\u9fff]+", value)
        return {token for chunk in chunks for token in
                ([chunk] if re.search(r"[a-z]", chunk) or len(chunk) < 2 else
                 [chunk[i:i+2] for i in range(len(chunk)-1)])}

    proposed, original = keywords(text), keywords(quote)
    return bool(proposed and len(proposed & original) / len(proposed) >= 0.8)


def evidence_field(hit, text, quote):
    return {"text": text[:500], "quote": quote[:1000], "url": hit.url,
            "site_name": hit.site_name, "source_type": source_type(hit)}
