"""
Event Classifier Module (Hybrid Semantic + Structural Pre-Filter)
Classifies scraped social media captions into 'EVENT' or 'NON_EVENT' before passing to LLMs.
"""

import os
import re
import logging
from typing import Tuple, Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Lightweight Multilingual Model for Semantic Sentence Embeddings
DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Curated Prototype Vectors
POSITIVE_EVENT_PROTOTYPES = [
    "Public event, concert, bazaar, exhibition, festival, party, movie night, comedy show, ticket price, date, time, and venue location",
    "ለአዲስ አመት ወይም ለበዓል የሚደረግ ባዛር፣ ኮንሰርት፣ ኤግዚቢሽን፣ የሙዚቃ ድግስ፣ የፊልም ምሽት፣ መግቢያ ዋጋ፣ ቦታ፣ ቀን እና ሰዓት ያለው የኢቨንት ጥሪ",
    "Join us for an exciting upcoming event in Addis Ababa with live music, food, drinks, tickets, date and venue details",
    "የቲኬት ዋጋ፣ የገባበት ቦታ፣ የመግቢያ ሰዓት እና ቀን ያለው ህዝባዊ ዝግጅት ወይም ስብሰባ"
]

NEGATIVE_NON_EVENT_PROTOTYPES = [
    "General news update, politics, sports score, opinion blog, personal opinion piece, meme, general advertisement without event date or venue",
    "የግል አስተያየት፣ አጠቃላይ ዜና፣ ፖለቲካ፣ አጠቃላይ ማስታወቂያ ያለ ቦታ እና ቀን፣ የግል ፎቶ፣ ወሬ"
]

class EventClassifier:
    """
    Modular Event Classifier using Semantic Embeddings & Structural Pattern Matching.
    """
    _instance: Optional["EventClassifier"] = None

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, threshold: float = 0.30):
        self.threshold = threshold
        self.model_name = model_name
        self._model = None
        self._pos_embeddings = None
        self._neg_embeddings = None

    @classmethod
    def get_instance(cls, threshold: float = 0.30) -> "EventClassifier":
        if cls._instance is None:
            cls._instance = EventClassifier(threshold=threshold)
        return cls._instance

    def _lazy_init_model(self):
        """Lazy load the sentence transformer model once into memory."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading local embedding model: {self.model_name}...")
            self._model = SentenceTransformer(self.model_name)
            self._pos_embeddings = self._model.encode(POSITIVE_EVENT_PROTOTYPES, convert_to_tensor=True)
            self._neg_embeddings = self._model.encode(NEGATIVE_NON_EVENT_PROTOTYPES, convert_to_tensor=True)
            logger.info("Local Event Classifier model loaded successfully!")
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer model ({e}). Classifier will fallback to Rule Engine.")
            self._model = None

    def _extract_structural_signals(self, text: str) -> Dict[str, Any]:
        """Extract explicit structural indicators (dates, times, prices, venue keywords)."""
        text_lower = text.lower()

        # Date signals (Months, Days of Week, Date Formats)
        date_patterns = (
            r'(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|'
            r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|'
            r'ነሐሴ|ጳጉሜ|መስከረም|ጥቅምት|ሕዳር|ታኅሣሥ|ጥር|የካቲት|መጋቢት|ሚያዝያ|ግንቦት|ሰኔ|ሐምሌ|'
            r'ሰኞ|ማክሰኞ|ረቡዕ|ሐሙስ|አርብ|ቅዳሜ|እሁድ)\b|\b\d{1,2}\s*[-/.]\s*\d{1,2}(\s*[-/.]\s*\d{2,4})?\b'
        )
        has_date = bool(re.search(date_patterns, text))

        # Time signals
        time_patterns = r'(?i)\b\d{1,2}(:\d{2})?\s*(am|pm|hrs?|o\'clock|ምሽት|ቀን|ጠዋት|ሰዓት)\b'
        has_time = bool(re.search(time_patterns, text))

        # Price / Reservation / Ticket signals
        price_patterns = r'(?i)\b\d+\s*(birr|etb|ብር)\b|\b(free entrance|entrance free|free entry|entry free|ነፃ|መግቢያ|ticket|tickets|ቲኬት|reservation|reservations|booking)\b'
        has_price = bool(re.search(price_patterns, text))

        # Venue / Location / Address signals
        venue_patterns = (
            r'(?i)\b(venue|location|located|park|hotel|hall|lounge|cinema|bar|restaurant|pub|club|bistro|cafe|kafi|center|centre|building|square|street|road|intersection|subcity|bole|atlas|kazanchis|piassa|sarbet|gotera|cmc|'
            r'ቦታ|ፓርክ|ሆቴል|አዳራሽ|ሲኒማ|ባር|ሬስቶራንት|ካፌ|ፊትለፊት|አጠገብ)\b'
        )
        has_venue = bool(re.search(venue_patterns, text))

        # Event keywords & Hosting verbs
        event_keywords = (
            r'(?i)\b(event|events|hosting|host|hosts|presents|presents:|bazaar|concert|expo|festival|party|night|show|exhibition|edition|music|culture|live|dj|performance|comedy|hangout|meetup|summit|conference|workshop|'
            r'ኢቨንት|ባዛር|ኮንሰርት|ኤግዚቢሽን|ፌስቲቫል|ድግስ|ዝግጅት|ምሽት)\b'
        )
        has_event_kw = bool(re.search(event_keywords, text))

        score = 0.0
        if has_event_kw: score += 0.30
        if has_date: score += 0.30
        if has_venue: score += 0.25
        if has_price: score += 0.15
        if has_time: score += 0.15

        return {
            "structural_score": min(score, 1.0),
            "has_date": has_date,
            "has_time": has_time,
            "has_price": has_price,
            "has_venue": has_venue,
            "has_event_kw": has_event_kw
        }

    def classify(self, text: str) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Classify a post text as EVENT (True) or NON_EVENT (False).
        Returns: (is_event, confidence_score, metadata)
        """
        if not text or len(text.strip()) < 10:
            return False, 0.0, {"reason": "text_too_short"}

        struct_meta = self._extract_structural_signals(text)
        struct_score = struct_meta["structural_score"]

        # Fast Pass: If event keyword + date or venue signals exist (score >= 0.35)
        if struct_score >= 0.35:
            return True, struct_score, {
                "method": "structural_fast_pass",
                "structural": struct_meta,
                "semantic_score": None
            }

        # Lazy init model if not loaded
        self._lazy_init_model()

        semantic_score = 0.0
        if self._model is not None:
            try:
                from sentence_transformers import util
                text_emb = self._model.encode(text, convert_to_tensor=True)
                
                pos_sims = util.cos_sim(text_emb, self._pos_embeddings)[0]
                neg_sims = util.cos_sim(text_emb, self._neg_embeddings)[0]

                max_pos = float(pos_sims.max())
                max_neg = float(neg_sims.max())

                semantic_score = max_pos - (max_neg * 0.5)
            except Exception as e:
                logger.warning(f"Semantic scoring error: {e}")
                semantic_score = 0.0

        # Combine Structural and Semantic Scores
        total_score = (struct_score * 0.4) + (semantic_score * 0.6)
        is_event = total_score >= self.threshold

        return is_event, round(total_score, 3), {
            "method": "hybrid_semantic_structural",
            "total_score": round(total_score, 3),
            "semantic_score": round(semantic_score, 3),
            "structural": struct_meta
        }
