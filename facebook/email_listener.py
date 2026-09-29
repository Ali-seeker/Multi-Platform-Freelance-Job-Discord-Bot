"""
facebook/email_listener.py — IMAP-based listener for Facebook group email notifications.
Connects via IMAP SSL to detect, parse, and structure new post notifications from Facebook.
"""

import email
from email.header import decode_header
import imaplib
import re
import urllib.parse
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from facebook.config import (
    FB_EMAIL_USER,
    FB_EMAIL_PASSWORD,
    FB_EMAIL_HOST,
    FB_EMAIL_PORT,
    FB_EMAIL_FOLDER,
    MARK_AS_READ,
    TRACKED_QUERIES,
    TRACKED_GROUPS,
)
from logger import get_logger

logger = get_logger(__name__)


def _decode_mime_str(header_str: str) -> str:
    """Decodes MIME encoded header strings (e.g. '=?UTF-8?B?...?=')."""
    if not header_str:
        return ""
    decoded_parts = decode_header(header_str)
    result = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            except Exception:
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result).strip()


def clean_facebook_url(raw_url: str) -> str:
    """
    Extracts direct Facebook group post URL from email tracking redirects.
    E.g.:
      https://www.facebook.com/n/?groups%2F123456%2Fposts%2F7891011%2F&...
      -> https://www.facebook.com/groups/123456/posts/7891011/
    """
    if not raw_url:
        return ""

    raw_unquoted = urllib.parse.unquote(raw_url)

    # 1. Search for groups/<id>/posts/<id> pattern
    match = re.search(
        r"facebook\.com/(?:n/\?)?groups/([^/&?#]+)/posts/([^/&?#]+)",
        raw_unquoted,
        re.IGNORECASE,
    )
    if match:
        group_id = match.group(1)
        post_id = match.group(2)
        return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/"

    # 2. Search for groups/<id>/permalink/<id> pattern
    match_permalink = re.search(
        r"facebook\.com/(?:n/\?)?groups/([^/&?#]+)/permalink/([^/&?#]+)",
        raw_unquoted,
        re.IGNORECASE,
    )
    if match_permalink:
        group_id = match_permalink.group(1)
        post_id = match_permalink.group(2)
        return f"https://www.facebook.com/groups/{group_id}/permalink/{post_id}/"

    # 3. Check for query parameter 'u' (redirect wrappers)
    if "/n/?" in raw_url or "facebook.com/l.php" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "u" in qs:
            return clean_facebook_url(qs["u"][0])

    # Strip tracker queries (fbclid, aref, notif_id, etc.)
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return raw_url


def parse_notification_subject(subject: str) -> tuple[str, str]:
    """
    Parses Subject lines such as:
    - 'John Doe posted in Python Developers'
    - 'John Doe shared a post in React Developers'
    - 'John Doe posted in Python Freelancers: "Need a Python developer"'
    Returns (author, group_name).
    """
    clean_sub = re.sub(r"^(?:Fwd|Re):\s*", "", subject, flags=re.IGNORECASE).strip()

    # Pattern 1: Author posted/shared in Group Name
    m = re.search(
        r"^(.+?)\s+(?:posted|shared a post)\s+in\s+([^:\"]+)(?::\s*.*)?$",
        clean_sub,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Pattern 2: New post in [Group Name] by [Author]
    m2 = re.search(r"new post in\s+(.+?)\s+by\s+(.+)", clean_sub, re.IGNORECASE)
    if m2:
        return m2.group(2).strip(), m2.group(1).strip()

    # Pattern 3: [Group Name] has a new post
    m3 = re.search(r"^(.+?)\s+(?:has\s+(?:a|\d+)\s+new\s+posts?|added\s+a\s+new\s+post)", clean_sub, re.IGNORECASE)
    if m3:
        return "Facebook Member", m3.group(1).strip()

    return "Facebook Member", "Facebook Group"


class FacebookEmailListener:
    """
    IMAP client that connects to an email account, searches for unseen
    Facebook notification emails, parses group post details, and formats
    standardized job records.
    """

    def __init__(self):
        self.user = FB_EMAIL_USER
        self.password = FB_EMAIL_PASSWORD
        self.host = FB_EMAIL_HOST
        self.port = FB_EMAIL_PORT
        self.folder = FB_EMAIL_FOLDER
        self.mark_as_read = MARK_AS_READ

    def is_configured(self) -> bool:
        """Returns True if email credentials are configured in .env."""
        return bool(self.user and self.password)

    def _connect(self) -> imaplib.IMAP4_SSL | None:
        """Establishes an authenticated IMAP SSL connection."""
        if not self.is_configured():
            logger.warning(
                "[FACEBOOK] ⚠️ Email credentials not set in .env! Please set FB_EMAIL_USER and FB_EMAIL_PASSWORD."
            )
            return None

        try:
            client = imaplib.IMAP4_SSL(self.host, self.port)
            client.login(self.user, self.password)
            client.select(self.folder)
            return client
        except Exception as e:
            logger.error(f"[FACEBOOK] 💥 Failed to connect to IMAP server ({self.host}): {e}")
            return None

    def fetch_new_posts(self) -> list[dict]:
        """
        Polls IMAP folder for unseen Facebook notification emails.
        Extracts and parses all group posts.
        Returns a list of standardized job dictionaries.
        """
        if not self.is_configured():
            return []

        client = self._connect()
        if not client:
            return []

        posts = []
        try:
            # Search for unseen emails from Facebook
            # Facebook sends from notification@facebookmail.com, groupnotification@facebookmail.com, etc.
            status, data = client.search(None, '(UNSEEN FROM "facebookmail.com")')
            if status != "OK" or not data or not data[0]:
                # Fallback to searching without UNSEEN constraint for recent items if inbox flags are reset
                return []

            email_ids = data[0].split()
            if not email_ids:
                return []

            logger.info(f"[FACEBOOK] 📧 Found {len(email_ids)} new Facebook notification email(s).")

            for e_id in email_ids:
                try:
                    res, msg_data = client.fetch(e_id, "(RFC822)")
                    if res != "OK" or not msg_data:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    parsed_post = self._parse_email_message(msg)
                    if parsed_post:
                        # Check group filter (if configured)
                        if TRACKED_GROUPS:
                            group_lower = parsed_post["group_name"].lower()
                            if not any(tg.lower() in group_lower for tg in TRACKED_GROUPS):
                                logger.debug(
                                    f"[FACEBOOK] Skipping post from unmonitored group: {parsed_post['group_name']}"
                                )
                                continue

                        posts.append(parsed_post)

                    # Mark email as read / Seen
                    if self.mark_as_read:
                        client.store(e_id, "+FLAGS", "\\Seen")

                except Exception as ex:
                    logger.error(f"[FACEBOOK] Error parsing email ID {e_id}: {ex}")

        except Exception as e:
            logger.error(f"[FACEBOOK] Error during IMAP fetch loop: {e}")
        finally:
            try:
                client.close()
                client.logout()
            except Exception:
                pass

        return posts

    def _parse_email_message(self, msg: email.message.Message) -> dict | None:
        """
        Extracts job/post information from a single Facebook notification MIME message.
        """
        raw_subject = msg.get("Subject", "")
        subject = _decode_mime_str(raw_subject)
        from_hdr = _decode_mime_str(msg.get("From", ""))
        message_id = msg.get("Message-ID", "").strip("<>")
        date_hdr = msg.get("Date", "")

        # Only process group post notifications
        group_keywords = [
            "posted in", "shared a post in", "new post in",
            "has a new post", "has new posts", "added a new post", "new post"
        ]
        if not any(kw in subject.lower() for kw in group_keywords):
            logger.debug(f"[FACEBOOK] Ignoring non-group email subject: {subject}")
            return None

        author, group_name = parse_notification_subject(subject)

        # Extract text and html bodies
        text_body = ""
        html_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    decoded_text = payload.decode(charset, errors="replace")

                    if content_type == "text/plain":
                        text_body += decoded_text + "\n"
                    elif content_type == "text/html":
                        html_body += decoded_text + "\n"
                except Exception:
                    continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                decoded_text = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html_body = decoded_text
                else:
                    text_body = decoded_text
            except Exception:
                pass

        # Parse links and content using BeautifulSoup if HTML is present
        post_url = ""
        description = ""

        if html_body:
            soup = BeautifulSoup(html_body, "html.parser")

            # Find all Facebook group post links in email
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "facebook.com" in href and ("posts" in href or "permalink" in href or "/n/?" in href):
                    clean_url = clean_facebook_url(href)
                    if "groups" in clean_url:
                        post_url = clean_url
                        break

            # Extract post description text
            # Often contained in tables or paragraphs after author name
            for tag in soup(["script", "style", "header", "footer"]):
                tag.decompose()

            raw_text = soup.get_text(separator="\n")
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            
            # Filter out generic Facebook email boilerplate
            cleaned_lines = []
            skip_phrases = [
                "see post", "view post", "reply to this email", "manage your notifications",
                "unsubscribe", "this message was sent to", "facebook, inc.", "meta platforms",
                "log in to facebook", "view more posts", "notifications", "change email"
            ]
            for line in lines:
                lower = line.lower()
                if any(sp in lower for sp in skip_phrases):
                    continue
                if line == author or line == group_name:
                    continue
                cleaned_lines.append(line)

            description = "\n".join(cleaned_lines)

        if not description and text_body:
            description = text_body.strip()

        # If post_url not found from HTML, check text_body links
        if not post_url and text_body:
            urls = re.findall(r"https?://[^\s<>\"']+", text_body)
            for u in urls:
                if "facebook.com" in u and ("posts" in u or "permalink" in u or "/n/?" in u):
                    clean_u = clean_facebook_url(u)
                    if "groups" in clean_u:
                        post_url = clean_u
                        break

        # Fallback URL if none resolved
        if not post_url:
            post_url = "https://www.facebook.com/notifications"

        # Unique post ID resolution
        post_id = ""
        id_match = re.search(r"/(?:posts|permalink)/([^/?#]+)", post_url)
        if id_match:
            post_id = id_match.group(1)
        else:
            post_id = message_id or f"fb_{abs(hash(subject + post_url))}"

        # Posted time resolution
        posted_iso = ""
        if date_hdr:
            try:
                parsed_date = email.utils.parsedate_to_datetime(date_hdr)
                posted_iso = parsed_date.astimezone(timezone.utc).isoformat()
            except Exception:
                posted_iso = datetime.now(timezone.utc).isoformat()
        else:
            posted_iso = datetime.now(timezone.utc).isoformat()

        # Check matched keywords for tagging
        matched_query = "All Posts"
        content_full = f"{subject} {description}".lower()
        for tq in TRACKED_QUERIES:
            q = tq.get("query", "all")
            lbl = tq.get("label", q)
            if q == "all" or q.lower() in content_full:
                matched_query = lbl
                break

        return {
            "job_id": post_id,
            "title": subject,
            "description": description[:4000].strip(),
            "url": post_url,
            "budget": "Not specified",
            "skills": matched_query,
            "posted_time": posted_iso,
            "author": author,
            "group_name": group_name,
            "query_label": matched_query,
        }
