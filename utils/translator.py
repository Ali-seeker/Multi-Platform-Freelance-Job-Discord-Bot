"""
utils/translator.py — High-speed, zero-dependency translation utility.
Translates non-English posts into English using Google Translate's public endpoint.
If text is already English, it returns immediately without alteration.
"""

from curl_cffi import requests
from logger import get_logger

logger = get_logger(__name__)

TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"

LANGUAGE_NAMES = {
    "pt": "Portuguese",
    "pt-pt": "Portuguese",
    "pt-br": "Portuguese",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ur": "Urdu",
    "hi": "Hindi",
    "ar": "Arabic",
    "zh": "Chinese",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "ko": "Korean",
    "ru": "Russian",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "tr": "Turkish",
    "nl": "Dutch",
    "pl": "Polish",
    "uk": "Ukrainian",
    "bn": "Bengali",
    "fa": "Persian",
    "th": "Thai",
}


class TextTranslator:
    """Session-managed translator for job and post text."""

    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")
        self._cache = {}

    def translate_to_english(self, text: str) -> tuple[str, str, bool]:
        """
        Translates text to English if it is in another language.
        Returns:
            (translated_text, detected_lang_code, was_translated)
        """
        if not text or not text.strip():
            return text, "en", False

        clean_text = text.strip()
        if clean_text in self._cache:
            return self._cache[clean_text]

        try:
            resp = self.session.post(
                TRANSLATE_ENDPOINT,
                data={
                    "client": "gtx",
                    "sl": "auto",
                    "tl": "en",
                    "dt": "t",
                    "q": clean_text,
                },
                timeout=12,
            )

            if resp.status_code != 200:
                logger.debug(f"[TRANSLATE] HTTP {resp.status_code} translating text.")
                return text, "unknown", False

            data = resp.json()
            detected_lang = str(data[2]).lower() if len(data) > 2 and data[2] else "en"

            # If already English, no translation needed
            if detected_lang == "en":
                res = (clean_text, "en", False)
                self._cache[clean_text] = res
                return res

            # Stitch translated segments together
            translated_segments = []
            if data and isinstance(data[0], list):
                for segment in data[0]:
                    if segment and isinstance(segment, list) and segment[0]:
                        translated_segments.append(segment[0])

            translated_text = "".join(translated_segments).strip()
            if not translated_text:
                return clean_text, detected_lang, False

            res = (translated_text, detected_lang, True)
            self._cache[clean_text] = res
            return res

        except Exception as e:
            logger.debug(f"[TRANSLATE] Could not translate text: {e}")
            return clean_text, "error", False

    def translate_job(self, job: dict) -> dict:
        """
        Takes a job dictionary, translates title and description to English if needed,
        and adds translation metadata.
        """
        job_copy = dict(job)
        orig_title = job_copy.get("title", "")
        orig_desc = job_copy.get("description", "")

        # Test language on description or title
        sample_text = orig_desc if len(orig_desc) > 30 else orig_title
        _, detected_lang, is_foreign = self.translate_to_english(sample_text)

        if not is_foreign or detected_lang == "en":
            return job_copy

        lang_name = LANGUAGE_NAMES.get(detected_lang, detected_lang.upper())
        logger.info(f"[TRANSLATE] 🌐 Translating post from {lang_name} ({detected_lang}) to English...")

        # Translate title
        trans_title, _, _ = self.translate_to_english(orig_title)
        # Translate description
        trans_desc, _, _ = self.translate_to_english(orig_desc)

        job_copy["title"] = trans_title
        job_copy["description"] = trans_desc
        job_copy["original_language"] = lang_name
        job_copy["original_title"] = orig_title
        job_copy["original_description"] = orig_desc
        job_copy["is_translated"] = True

        return job_copy


# Global singleton instance
default_translator = TextTranslator()


def translate_job_to_english(job: dict) -> dict:
    """Convenience helper to translate a job dictionary to English."""
    return default_translator.translate_job(job)
