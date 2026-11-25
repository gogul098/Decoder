"""Languages the app supports. Stories are decoded directly in the reader's language and
headlines are translated (both cached per language)."""

LANGS = {
    "en": ("English", "English"),
    "hi": ("Hindi", "हिन्दी"),
    "ta": ("Tamil", "தமிழ்"),
    "te": ("Telugu", "తెలుగు"),
    "kn": ("Kannada", "ಕನ್ನಡ"),
    "ml": ("Malayalam", "മലയാളം"),
    "mr": ("Marathi", "मराठी"),
    "bn": ("Bengali", "বাংলা"),
    "gu": ("Gujarati", "ગુજરાતી"),
    "pa": ("Punjabi", "ਪੰਜਾਬੀ"),
    "or": ("Odia", "ଓଡ଼ିଆ"),
    "ur": ("Urdu", "اردو"),
}

# Category names for the widget and notifications
LABELS = {
    "en": {"tech": "Tech & AI", "india": "Indian Politics", "world": "World Politics", "markets": "Markets", "oil": "Oil & Energy", "security": "Terror & Security"},
    "hi": {"tech": "टेक और AI", "india": "भारतीय राजनीति", "world": "विश्व राजनीति", "markets": "शेयर बाज़ार", "oil": "तेल और ऊर्जा", "security": "आतंक और सुरक्षा"},
    "ta": {"tech": "தொழில்நுட்பம் & AI", "india": "இந்திய அரசியல்", "world": "உலக அரசியல்", "markets": "பங்குச் சந்தை", "oil": "எண்ணெய் & எரிசக்தி", "security": "பயங்கரவாதம் & பாதுகாப்பு"},
    "te": {"tech": "టెక్ & AI", "india": "భారత రాజకీయాలు", "world": "ప్రపంచ రాజకీయాలు", "markets": "స్టాక్ మార్కెట్", "oil": "చమురు & ఇంధనం", "security": "ఉగ్రవాదం & భద్రత"},
    "kn": {"tech": "ಟೆಕ್ & AI", "india": "ಭಾರತೀಯ ರಾಜಕೀಯ", "world": "ವಿಶ್ವ ರಾಜಕೀಯ", "markets": "ಷೇರು ಮಾರುಕಟ್ಟೆ", "oil": "ತೈಲ & ಇಂಧನ", "security": "ಭಯೋತ್ಪಾದನೆ & ಭದ್ರತೆ"},
    "ml": {"tech": "ടെക് & AI", "india": "ഇന്ത്യൻ രാഷ്ട്രീയം", "world": "ലോക രാഷ്ട്രീയം", "markets": "ഓഹരി വിപണി", "oil": "എണ്ണ & ഊർജം", "security": "ഭീകരത & സുരക്ഷ"},
    "mr": {"tech": "टेक आणि AI", "india": "भारतीय राजकारण", "world": "जागतिक राजकारण", "markets": "शेअर बाजार", "oil": "तेल आणि ऊर्जा", "security": "दहशतवाद आणि सुरक्षा"},
    "bn": {"tech": "প্রযুক্তি ও AI", "india": "ভারতের রাজনীতি", "world": "বিশ্ব রাজনীতি", "markets": "শেয়ার বাজার", "oil": "তেল ও জ্বালানি", "security": "সন্ত্রাস ও নিরাপত্তা"},
    "gu": {"tech": "ટેક અને AI", "india": "ભારતીય રાજકારણ", "world": "વિશ્વ રાજકારણ", "markets": "શેરબજાર", "oil": "તેલ અને ઊર્જા", "security": "આતંક અને સુરક્ષા"},
    "pa": {"tech": "ਟੈੱਕ ਅਤੇ AI", "india": "ਭਾਰਤੀ ਰਾਜਨੀਤੀ", "world": "ਵਿਸ਼ਵ ਰਾਜਨੀਤੀ", "markets": "ਸ਼ੇਅਰ ਬਾਜ਼ਾਰ", "oil": "ਤੇਲ ਅਤੇ ਊਰਜਾ", "security": "ਅੱਤਵਾਦ ਅਤੇ ਸੁਰੱਖਿਆ"},
    "or": {"tech": "ଟେକ୍ ଓ AI", "india": "ଭାରତୀୟ ରାଜନୀତି", "world": "ବିଶ୍ୱ ରାଜନୀତି", "markets": "ସେୟାର ବଜାର", "oil": "ତେଲ ଓ ଶକ୍ତି", "security": "ଆତଙ୍କବାଦ ଓ ସୁରକ୍ଷା"},
    "ur": {"tech": "ٹیک اور AI", "india": "بھارتی سیاست", "world": "عالمی سیاست", "markets": "اسٹاک مارکیٹ", "oil": "تیل اور توانائی", "security": "دہشت گردی اور سلامتی"},
}


def norm(lang: str | None) -> str:
    lang = (lang or "en").lower()[:2]
    return lang if lang in LANGS else "en"


def story_key(story_id: str, lang: str) -> str:
    """Cache/queue/channel key for one story in one language (English keeps the old key)."""
    return story_id if lang == "en" else f"{story_id}:{lang}"


def instruction(lang: str) -> str:
    if lang == "en":
        return ""
    name, native = LANGS[lang]
    return (f"\n\nLANGUAGE: Write every text value in {name} ({native}), in its own script, in simple everyday "
            f"{name} that a newspaper reader in India would use. Keep names of people, places, companies and "
            f"numbers accurate (write them in {name} script, adding the English name in brackets the first "
            f"time if it helps). Keep the JSON keys in English, and keep every \"likelihood\" value exactly "
            f"one of: likely, possible, unlikely (in English).")
