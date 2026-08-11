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
        """Extract explicit structural indicators (dates, times, prices, venue keywords, contact info)."""
        text_lower = text.lower()

        # Date signals (Months, Days of Week, Date Formats, Relative Days)
        date_patterns = (
            r'(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|'
            r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|'
            r'today|tomorrow|tonight|weekend|this weekend|next week|this week|date|when|doors open|starts|schedule|'
            r'ነሐሴ|ጳጉሜ|መስከረም|ጥቅምት|ሕዳር|ታኅሣሥ|ጥር|የካቲት|መጋቢት|ሚያዝያ|ግንቦት|ሰኔ|ሐምሌ|'
            r'ሰኞ|ማክሰኞ|ረቡዕ|ሐሙስ|አርብ|ቅዳሜ|እሁድ|ዛሬ|ነገ|ከነገ ወዲያ|ሳምንት)\b|\b\d{1,2}(st|nd|rd|th)?\s*(of)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b|\b\d{1,2}\s*[-/.]\s*\d{1,2}(\s*[-/.]\s*\d{2,4})?\b'
        )
        has_date = bool(re.search(date_patterns, text))

        # Time signals
        time_patterns = r'(?i)\b\d{1,2}(:\d{2})?\s*(am|pm|hrs?|o\'clock|ምሽት|ቀን|ጠዋት|ሰዓት|ከምሽቱ|ከቀኑ|ከጠዋቱ)\b'
        has_time = bool(re.search(time_patterns, text))

        # Price / Reservation / Ticket signals
        price_patterns = (
            r'(?i)\b\d+\s*(birr|etb|ብር)\b|\b(free entrance|entrance free|free entry|entry free|no entrance fee|free admission|free|regular|vip|early bird|presale|pre-sale|at the door|'
            r'ነፃ|ነፃ መግቢያ|መግቢያ|ticket|tickets|ቲኬት|reservation|reservations|booking|register|registration|price|fee|cost|ዋጋ)\b'
        )
        has_price = bool(re.search(price_patterns, text))

        # Venue / Location / Address / Subcity signals
        venue_patterns = (
            r'(?i)\b(venue|location|located|address|where|place|space|park|hotel|hall|lounge|cinema|bar|restaurant|pub|club|bistro|cafe|kafi|center|centre|building|square|street|road|intersection|subcity|gallery|stadium|garden|rooftop|terrace|patio|resort|auditorium|compound|complex|hub|house|villa|plaza|tower|mall|arena|stage|'
            r'bole|atlas|kazanchis|piassa|sarbet|gotera|cmc|gerji|hayahulet|4kilo|6kilo|mexico|lebu|jomo|megenagna|chirkos|kera|'
            r'ቦታ|አድራሻ|መገኛ|ፓርክ|ሆቴል|አዳራሽ|ሲኒማ|ባር|ሬስቶራንት|ካፌ|ፊትለፊት|አጠገብ|ክፍለ ከተማ|አካባቢ|ህንፃ|ህንጻ|ፎቅ|አደባባይ|ሜዳ|ስታዲየም|ጋለሪ)\b'
        )
        has_venue = bool(re.search(venue_patterns, text))

        # Contact & Inquiries signals
        contact_patterns = r'(?i)(\+?251\s*\d{8,9}|09\d{8}|07\d{8}|\b(call|phone|contact|inquiries|info|dms|link in bio)\b)'
        has_contact = bool(re.search(contact_patterns, text))

        # Event keywords, Verbs & Invitation phrases
        event_keywords = (
            r'(?i)\b(event|events|hosting|host|hosts|presents|presents:|bazaar|concert|expo|festival|fest|party|night|show|exhibition|edition|music|culture|live|dj|performance|comedy|standup|open mic|jam|hangout|meetup|summit|conference|workshop|training|masterclass|webinar|seminar|forum|panel|hackathon|pitch|launch|release|screening|movie|film|play|theater|theatre|gala|soiree|dinner|brunch|marathon|hike|hiking|tour|camping|picnic|market|popup|pop-up|fair|carnival|'
            r'save the date|mark your calendar|don\'t miss|dont miss|are you ready|join us|happening|invites|cordially|'
            r'ኢቨንት|ባዛር|ኮንሰርት|ኤግዚቢሽን|ፌስቲቫል|ድግስ|ዝግጅት|ምሽት|ትስስር|ስልጠና|ወርክሾፕ|ስብሰባ|ሴሚናር|ጉዞ|እግር ጉዞ|ሩጫ|ጨዋታ)\b'
        )
        has_event_kw = bool(re.search(event_keywords, text))

        score = 0.0
        if has_event_kw: score += 0.30
        if has_date: score += 0.30
        if has_venue: score += 0.25
        if has_price: score += 0.15
        if has_time: score += 0.15
        if has_contact: score += 0.15

        return {
            "structural_score": min(score, 1.0),
            "has_date": has_date,
            "has_time": has_time,
            "has_price": has_price,
            "has_venue": has_venue,
            "has_contact": has_contact,
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

        # Fast Pass: If event keyword + date/venue/contact signals exist (score >= 0.25)
        if struct_score >= 0.25 or (struct_meta["has_event_kw"] and (struct_meta["has_date"] or struct_meta["has_venue"] or struct_meta["has_contact"])):
            return True, max(struct_score, 0.35), {
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
