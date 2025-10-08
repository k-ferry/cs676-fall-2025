# scorer.py
# Hybrid, interpretable credibility scorer specialized for soccer-card sources.
# Public contract:
#   score_url(url) -> {
#     "url": str,
#     "status": "ok" | "invalid_url" | "fetch_error" | ...,
#     "score": {"absolute": float, "percentile": float|None},
#     "signals": [{"name","value","weight","rationale"}, ...],
#     "errors": [str, ...],
#     "meta": {"host": str, "is_ebay": bool, "fetched_at": iso, "elapsed_ms": int, "fetch_ms": int|None, "version": str}
#   }
#   rank_listings(urls, dry_run=False) -> list[that dict], sorted by score desc

from __future__ import annotations
import dataclasses
import math
import re
import time
import typing as t
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

# Optional deps (graceful fallbacks)
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None

try:
    import requests
except Exception:
    requests = None

# ----------------- Small utilities -----------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)

def _cheap_text(html: str) -> str:
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        txt = soup.get_text(" ", strip=True)
        return re.sub(r"\s+", " ", txt).strip()
    txt = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    txt = re.sub(r"<style[\s\S]*?</style>", " ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()

def _count_images(html: str) -> int:
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")
        return len(soup.find_all("img"))
    return len(re.findall(r"<img\b", html, re.I))

def _squash_0_100(raw: float) -> float:
    # logistic squash → user-friendly 0..100
    x = raw - 0.8
    sig = 1 / (1 + math.exp(-3.5 * x))
    return round(100 * sig, 2)

def _percentile(x: float, arr: list[float]) -> float:
    if not arr:
        return float("nan")
    rank = sum(1 for a in arr if a <= x)
    return round(100 * rank / len(arr), 2)

# ----------------- Data containers -----------------

@dataclass
class Signal:
    name: str
    value: float     # normalized [0,1], higher = better
    weight: float    # relative influence [0,1]
    rationale: str

    def contribution(self) -> float:
        return self.value * self.weight

@dataclass
class ScoreResult:
    url: str
    status: str
    score_abs: float
    score_pct: float | None
    signals: list[Signal]
    errors: list[str]
    meta: dict[str, t.Any]

def response_json(result: ScoreResult) -> dict:
    return {
        "url": result.url,
        "status": result.status,
        "score": {"absolute": result.score_abs, "percentile": result.score_pct},
        "signals": [dataclasses.asdict(s) for s in result.signals],
        "errors": result.errors,
        "meta": result.meta,
    }

# ----------------- Host detectors -----------------

EbayLike = re.compile(r"(^|\.)ebay\.(com|co\.[a-z]{2}|[a-z]{2})$", re.I)
COMCLike = re.compile(r"(^|\.)comc\.com$", re.I)
PWCClike = re.compile(r"(^|\.)pwccmarketplace\.com$", re.I)
GoldinLike = re.compile(r"(^|\.)goldin\.co(m)?$", re.I)
ToppsLike = re.compile(r"(^|\.)topps\.com$", re.I)
PaniniLike = re.compile(r"(^|\.)paniniamerica\.net$", re.I)
PSALike = re.compile(r"(^|\.)psacard\.com$", re.I)
SGCLike = re.compile(r"(^|\.)gosgc\.com$", re.I)
BGSLike = re.compile(r"(^|\.)beckett\.com$", re.I)

def _synthetic_page_for(host: str) -> str:
    if EbayLike.search(host or ""):
        return (
            "<html><body>"
            "Top Rated Seller (99.7% positive feedback) (12450) feedback. "
            "2024 Topps Chrome UEFA Refractor PSA 10 Rookie /99 auto. "
            "Ships from New York. 30 day returns. "
            "<img/><img/><img/><img/><img/><img/>"
            "</body></html>"
        )
    if COMCLike.search(host or ""):
        return (
            "<html><body>"
            "COMC Listing — Seller: COMC. Returns accepted. "
            "2020 Panini Prizm EPL Silver RC. Multiple images. "
            "<img/><img/><img/><img/>"
            "</body></html>"
        )
    return "<html><body>By John Doe. Published 2023. Sample article text with some length and a doi.org/10.x link.</body></html>"

# ----------------- Signals -----------------

def _signal_domain_baseline(host: str) -> Signal:
    h = (host or "").lower()
    if EbayLike.search(h):
        return Signal("domain_prior", 0.75, 0.10, "Marketplace prior (eBay)")
    if COMCLike.search(h):
        return Signal("domain_prior", 0.72, 0.10, "Marketplace prior (COMC)")
    if PWCClike.search(h) or GoldinLike.search(h):
        return Signal("domain_prior", 0.78, 0.10, "Auction platform prior (PWCC/Goldin)")
    if ToppsLike.search(h) or PaniniLike.search(h):
        return Signal("domain_prior", 0.76, 0.08, "Manufacturer prior (Topps/Panini)")
    if PSALike.search(h) or SGCLike.search(h) or BGSLike.search(h):
        return Signal("domain_prior", 0.80, 0.08, "Grading company prior (PSA/SGC/BGS)")
    if h.endswith(".com"):
        return Signal("domain_prior", 0.60, 0.06, ".com baseline")
    return Signal("domain_prior", 0.50, 0.05, "Unknown/low-signal domain")

def _signal_transport_security(scheme: str) -> Signal:
    return Signal("https", 1.0 if scheme == "https" else 0.4, 0.04, "HTTPS vs HTTP transport")

def _signals_content_quality(html: str) -> list[Signal]:
    s: list[Signal] = []
    text = _cheap_text(html)
    n = len(text.split())
    if n <= 30:
        v, why = 0.25, "Very short body"
    elif n <= 120:
        v, why = 0.6, "Short body"
    elif n <= 2500:
        v, why = 0.82, "Reasonable body length"
    else:
        v, why = 0.65, "Very long body"
    s.append(Signal("content_length", v, 0.07, why))
    cites = len(re.findall(r"(doi\.org/|https?://)\S+", text))
    s.append(Signal("citations_links", min(cites / 5, 1.0), 0.04, "Outbound refs/links density"))
    has_authorish = bool(re.search(r"\bby\s+[A-Z][a-z]+", text))
    s.append(Signal("author_block_hint", 1.0 if has_authorish else 0.55, 0.03, "Author/date hints"))
    return s

# Hobby lexicon
CARD_TERMS = {
    "rookie": 0.12, "rc": 0.08,
    "psa 10": 0.16, "bgs 9.5": 0.10, "sgc 10": 0.08, "gem mint": 0.12,
    "auto": 0.12, "autograph": 0.12, "/": 0.10,  # catches /10, /25, etc.
    "refractor": 0.08, "sapphire": 0.08, "logofractor": 0.08, "color match": 0.10, "prizm": 0.08,
    "topps": 0.06, "merlin": 0.06, "select": 0.06, "optic": 0.06, "chrome": 0.06
}
_POS = {"grail","pc","beautiful","clean","crisp","gem","iconic","undervalued","deal","bargain","legend","heat"}
_NEG = {"creased","damage","ding","scratches","off-center","offcenter","trimmed","fake","reprint","altered","stain","worst","overpriced"}

def _sentiment_signal(text: str) -> list[Signal]:
    toks = re.findall(r"[a-zA-Z\-]+", text.lower())
    pos = sum(1 for w in toks if w in _POS)
    neg = sum(1 for w in toks if w in _NEG)
    total = max(pos + neg, 1)
    polarity = (pos - neg) / total
    val = (polarity + 1) / 2
    return [Signal("sentiment", val, 0.05, f"lexicon polarity {polarity:.2f}")]

def _signals_ebay_listing(html: str) -> list[Signal]:
    s: list[Signal] = []
    text = _cheap_text(html); lower = text.lower()
    s.extend(_sentiment_signal(text))
    m = re.search(r"(\d{1,3}\.\d)\%\s*positive feedback", text, re.I)
    if m:
        pct = float(m.group(1))
        v = 0.2 + 0.8 * (pct / 100.0)
        s.append(Signal("seller_feedback_pct", min(v, 1.0), 0.12, f"Seller feedback {pct}%"))
    else:
        s.append(Signal("seller_feedback_pct", 0.55, 0.06, "Feedback % not found"))
    m2 = re.search(r"\((\d{2,6})\)\s*feedback", text, re.I)
    if m2:
        cnt = int(m2.group(1))
        v = min(math.log10(max(cnt, 1)) / 5.0 + 0.4, 1.0)
        s.append(Signal("seller_feedback_count", v, 0.08, f"Feedback count {cnt}"))
    if re.search(r"top rated seller", text, re.I):
        s.append(Signal("top_rated", 1.0, 0.06, "Top Rated Seller badge"))
    if re.search(r"\b(30|60)\s*day returns?\b", text, re.I):
        s.append(Signal("returns_policy", 0.92, 0.05, "30/60-day returns"))
    elif re.search(r"no returns", text, re.I):
        s.append(Signal("returns_policy", 0.50, 0.05, "No returns"))
    term_score = 0.0
    for k, w in CARD_TERMS.items():
        if k in lower:
            term_score += w
    if re.search(r"\b#?\d{1,2}\b", lower):
        term_score += 0.04
    term_score = min(term_score, 1.0)
    s.append(Signal("card_specificity_terms", term_score, 0.14, "Hobby keywords present"))
    any_year = bool(re.search(r"\b(19|20)\d{2}\b", text))
    any_set  = bool(re.search(r"(prizm|topps|merlin|select|optic|megacracks|chrome)", lower))
    s.append(Signal("year_set_hint", 1.0 if (any_year and any_set) else 0.6, 0.06, "Year+Set mentioned"))
    imgs = _count_images(html)
    if imgs >= 8:
        s.append(Signal("image_count", 0.95, 0.05, f"{imgs} images"))
    elif imgs >= 4:
        s.append(Signal("image_count", 0.75, 0.05, f"{imgs} images"))
    else:
        s.append(Signal("image_count", 0.55, 0.05, f"{imgs} images"))
    if re.search(r"ships from\s+[A-Za-z ]+", lower):
        s.append(Signal("shipping_from", 0.70, 0.03, "Ships-from present"))
    return s

# ----------------- Core scoring -----------------

def score_url(
    url: str,
    *,
    dry_run: bool = False,
    cohort_scores: t.Sequence[float] | None = None,
    session: t.Any | None = None,
) -> dict:
    t0 = time.perf_counter()
    errors: list[str] = []
    signals: list[Signal] = []

    # 1) validate URL
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must include http(s) scheme and host")
        host = parsed.hostname or ""
    except Exception as e:
        result = ScoreResult(
            url=url,
            status="invalid_url",
            score_abs=0.0,
            score_pct=None,
            signals=[],
            errors=[f"invalid_url: {e}"],
            meta={"fetched_at": _now_iso(), "elapsed_ms": _elapsed_ms(t0)},
        )
        return response_json(result)

    # 2) priors
    signals.append(_signal_domain_baseline(host))
    signals.append(_signal_transport_security(parsed.scheme))

    # 3) fetch or synthesize
    html: str | None = None
    status: str = "ok"
    fetched_ms = None

    if dry_run:
        html = _synthetic_page_for(host)
        fetched_ms = _elapsed_ms(t0)
    else:
        if requests is None:
            errors.append("requests_not_available")
            status = "fetch_error"
        else:
            try:
                sess = session or requests.Session()
                r = sess.get(url, headers={"User-Agent": "CredScorer/0.1"}, timeout=8.0)
                fetched_ms = _elapsed_ms(t0)
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}")
                html = r.text
            except Exception as e:
                errors.append(f"fetch_error: {e}")
                status = "fetch_error"

    # 4) content + platform signals
    if html:
        try:
            signals.extend(_signals_content_quality(html))
        except Exception as e:
            errors.append(f"content_parse_error: {e}")
        try:
            if EbayLike.search(host or ""):
                signals.extend(_signals_ebay_listing(html))
            # (Optional) add COMC/PWCC/Goldin specific signals later
        except Exception as e:
            errors.append(f"platform_parse_error: {e}")

    # 5) aggregate
    raw = sum(s.contribution() for s in signals)
    abs_score = _squash_0_100(raw)
    pct = None
    if cohort_scores:
        try:
            pct = _percentile(abs_score, list(cohort_scores))
        except Exception as e:
            errors.append(f"percentile_error: {e}")

    result = ScoreResult(
        url=url,
        status=status,
        score_abs=abs_score,
        score_pct=pct,
        signals=signals,
        errors=errors,
        meta={
            "host": host,
            "is_ebay": bool(EbayLike.search(host or "")),
            "fetched_at": _now_iso(),
            "elapsed_ms": _elapsed_ms(t0),
            "fetch_ms": fetched_ms,
            "version": "d3-0.1",
        },
    )
    return response_json(result)

def rank_listings(urls: list[str], *, dry_run: bool = False) -> list[dict]:
    rows: list[dict] = []
    tmp: list[dict] = []
    abs_scores: list[float] = []
    for u in urls:
        r = score_url(u, dry_run=dry_run)
        tmp.append(r)
        abs_scores.append(r["score"]["absolute"])
    for r in tmp:
        r["score"]["percentile"] = _percentile(r["score"]["absolute"], abs_scores)
        rows.append(r)
    rows.sort(key=lambda d: d["score"]["absolute"], reverse=True)
    return rows

