"""Well-known websites and browsers, by spoken name (Greek or English)."""

SITES = {
    "youtube": "https://www.youtube.com", "γιουτιουμπ": "https://www.youtube.com",
    "google": "https://www.google.com", "γκουγκλ": "https://www.google.com",
    "gmail": "https://mail.google.com", "τζιμειλ": "https://mail.google.com",
    "github": "https://github.com", "γκιτχαμπ": "https://github.com",
    "wikipedia": "https://www.wikipedia.org", "βικιπαιδεια": "https://el.wikipedia.org",
    "facebook": "https://www.facebook.com", "φεισμπουκ": "https://www.facebook.com",
    "instagram": "https://www.instagram.com", "ινσταγκραμ": "https://www.instagram.com",
    "twitter": "https://x.com", "reddit": "https://www.reddit.com", "netflix": "https://www.netflix.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "outlook": "https://outlook.live.com",
    "google maps": "https://www.google.com/maps", "maps": "https://www.google.com/maps",
    "χαρτεσ": "https://www.google.com/maps", "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com", "translate": "https://translate.google.com",
    "google translate": "https://translate.google.com", "eclass": "https://eclass.upatras.gr",
    "ceid": "https://www.ceid.upatras.gr", "upatras": "https://www.upatras.gr", "linkedin": "https://www.linkedin.com",
    "stack overflow": "https://stackoverflow.com", "stackoverflow": "https://stackoverflow.com",
}

# spoken name -> site key used by web_search
SEARCHABLE = {"youtube": "youtube", "γιουτιουμπ": "youtube", "wikipedia": "wikipedia", "βικιπαιδεια": "wikipedia",
              "google": "web", "γκουγκλ": "web", "maps": "maps", "google maps": "maps", "χαρτεσ": "maps"}

BROWSERS = {
    "chrome": "chrome", "google chrome": "chrome", "κρομ": "chrome", "κροουμ": "chrome", "χρωμ": "chrome",
    "edge": "msedge", "microsoft edge": "msedge", "εντζ": "msedge", "firefox": "firefox", "φαιαρφοξ": "firefox",
    "opera": "opera", "οπερα": "opera", "brave": "brave", "comet": "comet", "browser": "", "the browser": "",
    "φυλλομετρητη": "", "φυλλομετρητησ": "", "μπραουζερ": "", "ιντερνετ": "",
}

SEARCH_URLS = {
    "web": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "wikipedia": "https://el.wikipedia.org/w/index.php?search={q}",
    "maps": "https://www.google.com/maps/search/{q}",
}
