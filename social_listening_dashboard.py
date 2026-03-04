"""
Social Listening Dashboard - Streamlit UI
Search public posts from Instagram, X (Twitter), Facebook by keyword

BUG FIXES:
- [FIX 1] DataFrame processing dipindahkan keluar dari 'if fb_count == 0' block
- [FIX 2] Sentiment keyword matching guna word boundary (regex) supaya 'ok' tak match 'book'
- [FIX 3] API credentials guna environment variable
"""

import streamlit as st
import pandas as pd
from apify_social_scraper import ApifySocialScraper
from apify_credentials import APIFY_API_TOKEN, APIFY_API_TOKEN_FB, DEFAULT_POSTS_PER_KEYWORD
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import re

# ============================================================
# SENTIMENT ANALYSIS (Hybrid: BM keyword-based + TextBlob EN)
# ============================================================
def analyze_sentiment(text):
    """
    Analyze sentiment of a post (supports Bahasa Melayu + English)
    Returns: ('Positive'/'Negative'/'Neutral', score float, emoji)
    """
    if not text or str(text) == 'nan' or text.strip() == '' or text == '(no text)':
        return 'Neutral', 0.0, '😐'
    
    text_lower = str(text).lower()
    
    # --- BM Keyword-based sentiment ---
    negative_bm = [
        'teruk', 'slow', 'lambat', 'lag', 'down', 'rosak', 'hancur', 'bodoh', 'bangang',
        'sampah', 'busuk', 'marah', 'geram', 'kecewa', 'sedih', 'sakit', 'susah', 'gagal',
        'rugi', 'tipu', 'scam', 'penipu', 'tak boleh', 'takde', 'xde', 'xbleh', 'xleh',
        'complaint', 'komplen', 'aduan', 'masalah', 'problem', 'issue', 'error',
        'putus', 'disconnect', 'gangguan', 'tak stabil', 'lembab', 'bengong',
        'worst', 'bad', 'terrible', 'horrible', 'awful', 'poor', 'hate', 'suck',
        'annoying', 'frustrated', 'angry', 'disappointed', 'waste', 'useless',
        'tak puas', 'tak guna', 'membazir', 'bazir', 'boring', 'bosan',
        'hampeh', 'hampas', 'celaka', 'sial', 'lemah', 'tarak',
        'potong line', 'line putus', 'signal hilang', 'coverage teruk',
    ]
    
    positive_bm = [
        'bagus', 'baik', 'best', 'terbaik', 'mantap', 'power', 'gempak', 'syok',
        'cantik', 'laju', 'pantas', 'cepat', 'stabil', 'puas', 'suka', 'happy',
        'gembira', 'seronok', 'senang', 'mudah', 'sempurna', 'perfect', 'hebat',
        'awesome', 'amazing', 'great', 'good', 'excellent', 'fantastic', 'wonderful',
        'love', 'nice', 'recommend', 'recommended', 'worth', 'satisfied',
        'thank', 'thanks', 'terima kasih', 'tq', 'syukur', 'alhamdulillah',
        'bestnya', 'fuyoh', 'tahniah', 'congratulations', 'congrats',
        'smooth', 'lancar', 'ok', 'reliable', 'improve', 'improved',
        'laju gila', 'coverage ok', 'signal ok', 'line ok', 'internet laju',
    ]
    
    # [FIX 2] Guna word boundary matching supaya 'ok' tak match 'book', 'token' dll
    def count_keyword_matches(keywords, text):
        count = 0
        for word in keywords:
            # Untuk frasa berbilang perkataan (cth: 'tak boleh', 'line putus'),
            # guna re.search dengan word boundary
            pattern = r'(?<!\w)' + re.escape(word) + r'(?!\w)'
            if re.search(pattern, text):
                count += 1
        return count
    
    neg_count = count_keyword_matches(negative_bm, text_lower)
    pos_count = count_keyword_matches(positive_bm, text_lower)
    
    # BM score
    bm_score = (pos_count - neg_count) / max(pos_count + neg_count, 1)
    
    # --- English TextBlob fallback ---
    tb_score = 0.0
    try:
        from textblob import TextBlob
        blob = TextBlob(str(text))
        tb_score = blob.sentiment.polarity  # -1 to 1
    except ImportError:
        pass
    except Exception:
        pass
    
    # Combine scores (BM weighted more if BM keywords found)
    if neg_count + pos_count > 0:
        final_score = bm_score * 0.7 + tb_score * 0.3
    else:
        final_score = tb_score
    
    # Classify
    if final_score > 0.1:
        return 'Positive', round(final_score, 2), '😊'
    elif final_score < -0.1:
        return 'Negative', round(final_score, 2), '😡'
    else:
        return 'Neutral', round(final_score, 2), '😐'

# Page config
st.set_page_config(
    page_title="Social Listening Dashboard",
    page_icon="🔍",
    layout="wide"
)

# Initialize session state
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'search_stats' not in st.session_state:
    st.session_state.search_stats = None
if 'selected_location' not in st.session_state:
    st.session_state.selected_location = 'All Locations'
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False  # Default: Light mode
if 'keyword_input' not in st.session_state:
    st.session_state.keyword_input = ''

# Sidebar - Search Configuration
with st.sidebar:
    # Theme toggle at the very top
    col_theme1, col_theme2 = st.columns([1, 1])
    with col_theme1:
        if st.button("🌙 Dark" if not st.session_state.dark_mode else "☀️ Light", use_container_width=True):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()

    st.title("⚙️ Search Configuration")

# Apply theme CSS
dark_mode = st.session_state.dark_mode

if dark_mode:
    # Dark mode (current theme - keep as is, Streamlit dark theme handles most of it)
    st.markdown("""
    <style>
    /* Dark mode background */
    .stApp {
        background-color: #0e1117 !important;
        color: #e0e0e0 !important;
    }
    header[data-testid="stHeader"] {
        background-color: #0e1117 !important;
    }
    [data-testid="stSidebar"] {
        background-color: #1a1c23 !important;
    }
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] .stCheckbox label span {
        color: #e2e8f0 !important;
    }
    [data-testid="stSidebar"] .stSlider label,
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stTextInput label {
        color: #e2e8f0 !important;
    }
    [data-testid="stSidebar"] small, 
    [data-testid="stSidebar"] .stCaption {
        color: #94a3b8 !important;
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #e0e0e0;
        margin-bottom: 1rem;
    }
    .platform-tag {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        margin: 2px;
    }
    .instagram-tag {
        background: linear-gradient(45deg, #f09433 0%,#e6683c 25%,#dc2743 50%,#cc2366 75%,#bc1888 100%);
        color: white;
    }
    .x-tag {
        background: #1d9bf0;
        color: white;
    }
    .facebook-tag {
        background: #1877f2;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)
    plotly_template = "plotly_dark"
    pie_colors = ['#1877f2', '#e1306c', '#333333']
    bar_colors = ['#3b82f6', '#10b981']
else:
    # Light mode
    st.markdown("""
    <style>
    /* Light mode overrides */
    .stApp {
        background-color: #ffffff !important;
        color: #1f2937 !important;
    }
    
    /* Fix top header/toolbar bar */
    header[data-testid="stHeader"] {
        background-color: #ffffff !important;
    }
    .stAppDeployButton, [data-testid="stToolbar"] {
        color: #1f2937 !important;
    }
    
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 1rem;
    }
    
    /* Sidebar light */
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa !important;
    }
    section[data-testid="stSidebar"] * {
        color: #1f2937 !important;
    }
    section[data-testid="stSidebar"] .stButton > button {
        color: #1f2937 !important;
        background-color: #e9ecef !important;
        border: 1px solid #ced4da !important;
    }
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
        color: white !important;
        background-color: #dc3545 !important;
        border: none !important;
    }
    
    /* Main content light */
    .stMetric label, .stMetric [data-testid="stMetricValue"] {
        color: #1f2937 !important;
    }
    
    h1, h2, h3, h4, h5, h6, p, span, div, label {
        color: #1f2937 !important;
    }
    
    /* Info/Warning/Success boxes */
    .stAlert {
        background-color: #f0f7ff !important;
    }
    
    /* Selectbox and inputs */
    .stSelectbox > div > div,
    .stSelectbox [data-baseweb="select"] > div {
        background-color: #ffffff !important;
        color: #1f2937 !important;
        border: 1px solid #ced4da !important;
    }
    .stSelectbox [data-baseweb="select"] span {
        color: #1f2937 !important;
    }
    
    .stTextInput > div > div > input {
        background-color: #ffffff !important;
        color: #1f2937 !important;
        border: 1px solid #ced4da !important;
        caret-color: #1f2937 !important;
        -webkit-text-fill-color: #1f2937 !important;
    }
    .stTextInput > div > div > input::placeholder {
        color: #9ca3af !important;
        -webkit-text-fill-color: #9ca3af !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
    }
    
    /* Cards and containers */
    [data-testid="stVerticalBlock"] {
        color: #1f2937;
    }
    
    /* Platform tags */
    .platform-tag {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        margin: 2px;
    }
    .instagram-tag {
        background: linear-gradient(45deg, #f09433 0%,#e6683c 25%,#dc2743 50%,#cc2366 75%,#bc1888 100%);
        color: white !important;
    }
    .x-tag {
        background: #1d9bf0;
        color: white !important;
    }
    .facebook-tag {
        background: #1877f2;
        color: white !important;
    }
    
    /* Metric cards */
    [data-testid="stMetric"] {
        background-color: #f8f9fa;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #e9ecef;
    }
    
    /* Divider */
    hr {
        border-color: #e9ecef !important;
    }
    
    /* Download button */
    .stDownloadButton > button {
        background-color: #1f2937 !important;
        color: white !important;
    }
    
    /* Dropdown/popover menus - aggressive override */
    [data-baseweb="popover"],
    [data-baseweb="popover"] > div,
    [data-baseweb="menu"],
    [data-baseweb="menu"] > div,
    [data-baseweb="select"] [data-baseweb="popover"],
    div[data-floating-ui-portal] > div,
    div[data-floating-ui-portal] > div > div,
    div[data-floating-ui-portal] ul,
    div[data-floating-ui-portal] li,
    body > div[data-baseweb="popover"],
    body > div[data-baseweb="layer"] > div,
    body > div > div[data-baseweb="popover"],
    ul[role="listbox"],
    ul[role="listbox"] > li,
    li[role="option"],
    [data-baseweb="menu"] li,
    [data-baseweb="list"] li,
    [data-baseweb="menu-item"],
    [role="listbox"],
    [role="option"] {
        background-color: #ffffff !important;
        color: #1f2937 !important;
    }
    ul[role="listbox"] li:hover,
    li[role="option"]:hover,
    [data-baseweb="menu"] li:hover,
    [data-baseweb="menu-item"]:hover,
    [role="option"]:hover,
    [role="option"][aria-selected="true"] {
        background-color: #dbeafe !important;
        color: #1f2937 !important;
    }
    /* Force all floating/portal overlays to light */
    div[data-baseweb="layer"],
    div[data-baseweb="layer"] > div,
    div[data-baseweb="layer"] > div > div {
        background-color: #ffffff !important;
        color: #1f2937 !important;
    }
    
    /* Date picker */
    [data-baseweb="calendar"],
    [data-baseweb="datepicker"],
    [data-baseweb="calendar"] > div,
    [data-baseweb="calendar"] th,
    [data-baseweb="calendar"] td,
    [data-baseweb="calendar"] div,
    [data-baseweb="calendar"] button {
        background-color: #ffffff !important;
        color: #1f2937 !important;
    }
    [data-baseweb="calendar"] td:hover,
    [data-baseweb="calendar"] button:hover {
        background-color: #e9ecef !important;
    }
    /* Date picker header (month/year navigation) */
    [data-baseweb="calendar-header"],
    [data-baseweb="calendar-header"] button,
    [data-baseweb="calendar-header"] div {
        background-color: #ffffff !important;
        color: #1f2937 !important;
    }
    /* Date input fields */
    [data-baseweb="input"],
    [data-baseweb="input"] input,
    [data-baseweb="base-input"] {
        background-color: #ffffff !important;
        color: #1f2937 !important;
        caret-color: #1f2937 !important;
        -webkit-text-fill-color: #1f2937 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    plotly_template = "plotly_white"
    pie_colors = ['#1877f2', '#e1306c', '#000000']
    bar_colors = ['#3b82f6', '#10b981']

# Scrollable posts feed CSS
st.markdown("""
<style>
/* Make the right panel posts scrollable */
.posts-feed-container {
    max-height: 80vh;
    overflow-y: auto;
    padding-right: 8px;
}
.posts-feed-container::-webkit-scrollbar {
    width: 6px;
}
.posts-feed-container::-webkit-scrollbar-thumb {
    background: #888;
    border-radius: 3px;
}
.posts-feed-container::-webkit-scrollbar-thumb:hover {
    background: #555;
}
.post-card {
    padding: 12px 0;
    border-bottom: 1px solid rgba(128,128,128,0.2);
}
</style>
""", unsafe_allow_html=True)

# Header - Government/Corporate style banner
if dark_mode:
    header_bg = "linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0c4a6e 100%)"
    header_text = "#ffffff"
    header_sub = "#94a3b8"
    header_accent = "#38bdf8"
    header_border = "#1e40af"
else:
    header_bg = "linear-gradient(135deg, #2563eb 0%, #3b82f6 40%, #60a5fa 100%)"
    header_text = "#ffffff"
    header_sub = "#dbeafe"
    header_accent = "#3b82f6"
    header_border = "#1e40af"

st.markdown(f"""
<div style="
    background: {header_bg};
    padding: 28px 36px;
    border-radius: 12px;
    margin-bottom: 24px;
    border-bottom: 4px solid {header_accent};
    position: relative;
    overflow: hidden;
">
    <div style="position: relative; z-index: 1;">
        <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 8px;">
            <div style="
                width: 44px; height: 44px;
                background: rgba(255,255,255,0.15);
                border-radius: 10px;
                display: flex; align-items: center; justify-content: center;
                font-size: 1.5rem;
            ">📡</div>
            <div>
                <h1 style="margin: 0; font-size: 1.8rem; font-weight: 700; color: {header_text}; letter-spacing: -0.5px;">
                    Social Listening Dashboard
                </h1>
            </div>
        </div>
        <p style="margin: 0; font-size: 0.95rem; color: {header_sub}; padding-left: 58px;">
            Real-time public sentiment monitoring &amp; social media intelligence platform
        </p>
    </div>
    <div style="
        position: absolute; top: -20px; right: -20px;
        width: 120px; height: 120px;
        background: rgba(255,255,255,0.03);
        border-radius: 50%;
    "></div>
    <div style="
        position: absolute; bottom: -30px; right: 60px;
        width: 80px; height: 80px;
        background: rgba(255,255,255,0.03);
        border-radius: 50%;
    "></div>
</div>
""", unsafe_allow_html=True)

# Continue Sidebar
with st.sidebar:
    
    # Keyword input
    st.markdown("### 🔎 Keyword")
    keyword_input = st.text_input(
        "Enter keyword to search",
        value=st.session_state.keyword_input,
        placeholder="e.g., line teruk, digital marketing",
        help="Enter any keyword to search across social media platforms",
        key="keyword_input_widget"
    )
    # Save to session state
    st.session_state.keyword_input = keyword_input
    
    # Number of posts
    st.markdown("### 📊 Results")
    posts_limit = st.select_slider(
        "Posts per platform",
        options=[5, 10, 20, 30, 50, 100],
        value=DEFAULT_POSTS_PER_KEYWORD,
        help="Number of posts to retrieve per platform"
    )
    
    # Platform selection
    st.markdown("### 📱 Platforms")
    platforms = {
        'Facebook': st.checkbox("Facebook", value=True),
        'Instagram': st.checkbox("Instagram", value=True),
        'X': st.checkbox("X (Twitter)", value=True)
    }
    
    selected_platforms = [p for p, checked in platforms.items() if checked]
    
    # Location filter
    st.markdown("### 🌍 Location")
    location_options = [
        "All Locations", 
        "Malaysia Only",
        "── Negeri ──",
        "Johor", "Kedah", "Kelantan", "Melaka", 
        "Negeri Sembilan", "Pahang", "Perak", "Perlis",
        "Pulau Pinang", "Sabah", "Sarawak", "Selangor",
        "Terengganu", "W.P. Kuala Lumpur", "W.P. Putrajaya", "W.P. Labuan"
    ]
    selected_location = st.selectbox(
        "Filter by location",
        options=location_options,
        index=0,  # Default: All Locations (show everything first)
        help="Filter posts by geographic location based on content, author, and hashtags"
    )
    
    # Store in session state
    st.session_state.selected_location = selected_location
    
    # Network Provider filter
    st.markdown("### 📶 Network Provider")
    provider_options = ["All Providers", "CelcomDigi", "Maxis/Hotlink", "U Mobile", "Unifi", "YES"]
    selected_provider = st.selectbox(
        "Filter by telco provider",
        options=provider_options,
        index=0,
        help="Filter posts mentioning specific Malaysian network providers"
    )
    st.session_state.selected_provider = selected_provider
    
    # Date range filter
    st.markdown("### 📅 Date Range")
    use_date_filter = st.checkbox("Filter by date", value=False, help="Filter posts by publication date")
    
    if use_date_filter:
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "From",
                value=datetime.now() - pd.Timedelta(days=30),
                help="Start date for filtering posts"
            )
        with col2:
            end_date = st.date_input(
                "To",
                value=datetime.now(),
                help="End date for filtering posts"
            )
    else:
        start_date = None
        end_date = None
    
    # Search button
    st.markdown("---")
    search_button = st.button("🔍 Search Posts", type="primary", use_container_width=True)
    
    # Info
    st.markdown("---")
    st.info("💡 **Tip:** Results may take 1-3 minutes depending on number of platforms selected.")

# Main content
if search_button:
    if not keyword_input or not keyword_input.strip():
        st.error("⚠️ Please enter a keyword to search!")
    elif not selected_platforms:
        st.error("⚠️ Please select at least one platform!")
    else:
        # Initialize scraper
        scraper = ApifySocialScraper(APIFY_API_TOKEN, api_token_fb=APIFY_API_TOKEN_FB)
        
        # Professional loading animation
        loading_placeholder = st.empty()
        
        def show_loading(platform_name, platform_icon, platform_color, step, total_steps):
            """Show professional animated loading UI"""
            progress_pct = int((step / total_steps) * 100)
            
            # Platform status indicators
            platforms_status = []
            platform_list = selected_platforms
            for i, p in enumerate(platform_list):
                if p == 'Facebook':
                    icon, color = '📘', '#1877f2'
                elif p == 'Instagram':
                    icon, color = '📸', '#e1306c'
                elif p == 'X':
                    icon, color = '🐦', '#1d9bf0'
                else:
                    icon, color = '🔍', '#6b7280'
                
                if i < step - 1:
                    status = f'<span style="color: #10b981; font-weight: 600;">✅ {p}</span>'
                elif i == step - 1:
                    status = f'<span style="color: {color}; font-weight: 700;">🔄 {p}</span>'
                else:
                    status = f'<span style="color: #6b7280;">⏳ {p}</span>'
                platforms_status.append(status)
            
            status_html = ' &nbsp;&nbsp;→&nbsp;&nbsp; '.join(platforms_status)
            
            # Use components.html for proper CSS animation rendering
            import streamlit.components.v1 as components
            
            html_content = f"""
            <div style="
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                border-radius: 16px;
                padding: 40px 30px;
                text-align: center;
                box-shadow: 0 10px 40px rgba(0,0,0,0.3);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                position: relative;
                overflow: hidden;
            ">
                <!-- Animated glow bg -->
                <div style="
                    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                    background: radial-gradient(circle at 50% 50%, {platform_color}18, transparent 70%);
                    animation: bgPulse 2s ease-in-out infinite;
                "></div>
                
                <!-- Spinner ring -->
                <div style="
                    width: 90px; height: 90px;
                    margin: 0 auto 24px;
                    border-radius: 50%;
                    border: 3px solid #334155;
                    border-top: 3px solid {platform_color};
                    animation: spin 1s linear infinite;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    position: relative;
                ">
                    <div style="
                        width: 70px; height: 70px;
                        border-radius: 50%;
                        background: #1e293b;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        position: absolute;
                    ">
                        <span style="font-size: 32px;">{platform_icon}</span>
                    </div>
                </div>
                
                <h3 style="color: #ffffff; margin: 0 0 8px; font-size: 1.3rem; font-weight: 600; position: relative;">
                    Scanning {platform_name}
                </h3>
                <p style="color: #94a3b8; margin: 0 0 24px; font-size: 0.9rem; position: relative;">
                    Searching for &ldquo;<span style="color: {platform_color}; font-weight: 600;">{keyword_input}</span>&rdquo; across public posts
                </p>
                
                <!-- Progress bar -->
                <div style="
                    background: #0f172a;
                    border-radius: 10px;
                    height: 8px;
                    margin: 0 auto 20px;
                    max-width: 350px;
                    overflow: hidden;
                    border: 1px solid #334155;
                ">
                    <div style="
                        background: linear-gradient(90deg, {platform_color}, {platform_color}bb);
                        height: 100%;
                        width: {progress_pct}%;
                        border-radius: 10px;
                        transition: width 0.5s ease;
                        box-shadow: 0 0 12px {platform_color}50;
                        position: relative;
                        overflow: hidden;
                    ">
                        <div style="
                            position: absolute; top: 0; left: -100%; width: 200%; height: 100%;
                            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
                            animation: shimmer 1.5s infinite;
                        "></div>
                    </div>
                </div>
                
                <!-- Platform status -->
                <div style="color: #94a3b8; font-size: 0.85rem; position: relative;">
                    {status_html}
                </div>
                
                <!-- Dots animation -->
                <div style="margin-top: 16px; position: relative;">
                    <span class="dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:{platform_color}; margin:0 4px; animation: dotBounce 1.4s ease-in-out infinite;"></span>
                    <span class="dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:{platform_color}; margin:0 4px; animation: dotBounce 1.4s ease-in-out 0.2s infinite;"></span>
                    <span class="dot" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:{platform_color}; margin:0 4px; animation: dotBounce 1.4s ease-in-out 0.4s infinite;"></span>
                </div>
            </div>
            
            <style>
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
                @keyframes bgPulse {{
                    0%, 100% {{ opacity: 0.4; }}
                    50% {{ opacity: 1; }}
                }}
                @keyframes shimmer {{
                    0% {{ transform: translateX(-100%); }}
                    100% {{ transform: translateX(100%); }}
                }}
                @keyframes dotBounce {{
                    0%, 80%, 100% {{ transform: scale(0.6); opacity: 0.4; }}
                    40% {{ transform: scale(1.2); opacity: 1; }}
                }}
            </style>
            """
            
            loading_placeholder.empty()
            with loading_placeholder:
                components.html(html_content, height=320)
        
        try:
            # Search based on selected platforms
            all_results = []
            total_steps = len(selected_platforms)
            current_step = 0
            
            if 'Facebook' in selected_platforms:
                current_step += 1
                show_loading("Facebook", "📘", "#1877f2", current_step, total_steps)
                facebook_posts = scraper.search_facebook_posts(keyword_input, posts_limit)
                all_results.extend(facebook_posts)
            
            if 'Instagram' in selected_platforms:
                current_step += 1
                show_loading("Instagram", "📸", "#e1306c", current_step, total_steps)
                instagram_posts = scraper.search_instagram_hashtag(keyword_input, posts_limit)
                all_results.extend(instagram_posts)
            
            if 'X' in selected_platforms:
                current_step += 1
                show_loading("X (Twitter)", "🐦", "#1d9bf0", current_step, total_steps)
                x_posts = scraper.search_x_twitter(keyword_input, posts_limit)
                all_results.extend(x_posts)
            
            # Clear loading animation
            loading_placeholder.empty()
            
            # Show per-platform breakdown
            ig_count = len([r for r in all_results if r.get('platform') == 'Instagram'])
            x_count = len([r for r in all_results if r.get('platform') == 'X'])
            fb_count = len([r for r in all_results if r.get('platform') == 'Facebook'])
            
            # Show completion summary
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, #064e3b, #065f46);
                border-radius: 12px;
                padding: 16px 24px;
                margin: 10px 0;
                display: flex;
                align-items: center;
                gap: 16px;
                border: 1px solid #10b981;
            ">
                <span style="font-size: 24px;">✅</span>
                <div>
                    <div style="color: #ffffff; font-weight: 600; font-size: 0.95rem;">Scan Complete</div>
                    <div style="color: #a7f3d0; font-size: 0.8rem;">
                        📘 Facebook: {fb_count} &nbsp;·&nbsp; 📸 Instagram: {ig_count} &nbsp;·&nbsp; 🐦 X: {x_count} &nbsp;·&nbsp; Total: {fb_count + ig_count + x_count} posts
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # [FIX 1] Warning untuk Facebook 0 posts sekarang BERASINGAN dari DataFrame processing
            if fb_count == 0 and 'Facebook' in selected_platforms:
                st.warning("⚠️ Facebook returned 0 posts. Check terminal/console for debug logs.")
            
            # [FIX 1] DataFrame processing sekarang SENTIASA jalan kalau ada results
            # (sebelum ni tersangkut dalam 'if fb_count == 0' block)
            if all_results:
                df = pd.DataFrame(all_results)
                df['scraped_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Apply sentiment analysis
                sentiments = df['content'].apply(analyze_sentiment)
                df['sentiment'] = sentiments.apply(lambda x: x[0])
                df['sentiment_score'] = sentiments.apply(lambda x: x[1])
                df['sentiment_emoji'] = sentiments.apply(lambda x: x[2])
                
                # Get stats
                stats = scraper.get_summary_stats(df)
                
                # Add sentiment stats
                stats['sentiment'] = df['sentiment'].value_counts().to_dict()
                
                # Store in session state
                st.session_state.search_results = df
                st.session_state.search_stats = stats
                
                st.success(f"✅ Found {len(df)} posts!")
            else:
                st.warning("⚠️ No results found. Try different keywords or platforms.")
                st.session_state.search_results = None
                st.session_state.search_stats = None
            
        except Exception as e:
            loading_placeholder.empty()
            st.error(f"❌ Error: {str(e)}")
            st.session_state.search_results = None
            st.session_state.search_stats = None

# Display results if available
if st.session_state.search_results is not None and not st.session_state.search_results.empty:
    df = st.session_state.search_results
    stats = st.session_state.search_stats
    
    # === TWO-PANEL LAYOUT: Left (stats) | Right (posts feed) ===
    left_panel, right_panel = st.columns([3, 2])
    
    # =============================================
    # LEFT PANEL - Stats, Charts, Sentiment
    # =============================================
    with left_panel:
        # Summary Statistics
        st.markdown("### 📊 Summary Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Posts", stats['total_posts'])
        with col2:
            st.metric("Total Likes", f"{stats['total_engagement']['likes']:,}")
        with col3:
            st.metric("Total Comments", f"{stats['total_engagement']['comments']:,}")
        with col4:
            total_engagement = stats['total_engagement']['likes'] + stats['total_engagement']['comments']
            st.metric("Total Engagement", f"{total_engagement:,}")
        
        # Platform breakdown
        st.markdown("---")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 📱 Posts by Platform")
            platform_data = pd.DataFrame(list(stats['by_platform'].items()), columns=['Platform', 'Posts'])
            fig_platform = px.pie(platform_data, values='Posts', names='Platform', 
                                 color_discrete_sequence=pie_colors,
                                 template=plotly_template)
            fig_platform.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280)
            if not dark_mode:
                fig_platform.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#1f2937'
                )
            st.plotly_chart(fig_platform, use_container_width=True, config={'displayModeBar': False})
        
        with col2:
            st.markdown("#### 📈 Engagement by Platform")
            engagement_data = df.groupby('platform')[['likes', 'comments']].sum().reset_index()
            fig_engagement = px.bar(engagement_data, x='platform', y=['likes', 'comments'],
                                   barmode='group', color_discrete_sequence=bar_colors,
                                   template=plotly_template)
            fig_engagement.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280)
            if not dark_mode:
                fig_engagement.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#1f2937'
                )
            st.plotly_chart(fig_engagement, use_container_width=True, config={'displayModeBar': False})
        
        # Sentiment Analysis Section
        if 'sentiment' in df.columns:
            st.markdown("---")
            st.markdown("### 🎭 Sentiment Analysis")
            
            sentiment_counts = df['sentiment'].value_counts().to_dict()
            pos_count = sentiment_counts.get('Positive', 0)
            neg_count = sentiment_counts.get('Negative', 0)
            neu_count = sentiment_counts.get('Neutral', 0)
            total = pos_count + neg_count + neu_count
            
            # Sentiment KPI cards
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("😊 Positive", f"{pos_count}", f"{pos_count/total*100:.0f}%" if total > 0 else "0%")
            with col2:
                st.metric("😡 Negative", f"{neg_count}", f"{neg_count/total*100:.0f}%" if total > 0 else "0%")
            with col3:
                st.metric("😐 Neutral", f"{neu_count}", f"{neu_count/total*100:.0f}%" if total > 0 else "0%")
            with col4:
                avg_score = df['sentiment_score'].mean()
                if avg_score > 0.1:
                    overall = "Mostly Positive 👍"
                elif avg_score < -0.1:
                    overall = "Mostly Negative 👎"
                else:
                    overall = "Mixed / Neutral ➖"
                st.metric("Overall Sentiment", overall)
            
            # Sentiment charts
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 🎭 Sentiment Distribution")
                sent_data = pd.DataFrame({
                    'Sentiment': ['Positive', 'Negative', 'Neutral'],
                    'Count': [pos_count, neg_count, neu_count]
                })
                fig_sent = px.pie(sent_data, values='Count', names='Sentiment',
                                 color='Sentiment',
                                 color_discrete_map={
                                     'Positive': '#10b981',
                                     'Negative': '#ef4444', 
                                     'Neutral': '#6b7280'
                                 },
                                 template=plotly_template)
                fig_sent.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280)
                if not dark_mode:
                    fig_sent.update_layout(
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        font_color='#1f2937'
                    )
                st.plotly_chart(fig_sent, use_container_width=True, config={'displayModeBar': False})
            
            with col2:
                st.markdown("#### 📊 Sentiment by Platform")
                if 'platform' in df.columns:
                    sent_platform = df.groupby(['platform', 'sentiment']).size().reset_index(name='count')
                    fig_sent_plat = px.bar(sent_platform, x='platform', y='count', color='sentiment',
                                           barmode='group',
                                           color_discrete_map={
                                               'Positive': '#10b981',
                                               'Negative': '#ef4444',
                                               'Neutral': '#6b7280'
                                           },
                                           template=plotly_template)
                    fig_sent_plat.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=280)
                    if not dark_mode:
                        fig_sent_plat.update_layout(
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            font_color='#1f2937'
                        )
                    st.plotly_chart(fig_sent_plat, use_container_width=True, config={'displayModeBar': False})
        
        # Export button
        st.markdown("---")
        st.markdown("### 💾 Export Results")
        csv = df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"social_listening_{keyword_input.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="export_csv_left"
        )
    
    # =============================================
    # RIGHT PANEL - Scrollable Posts Feed
    # =============================================
    with right_panel:
        st.markdown("### 📋 Posts Feed")
        
        # Compact filter row
        fc1, fc2 = st.columns(2)
        with fc1:
            filter_platform = st.selectbox("Platform", ['All'] + list(stats['by_platform'].keys()), key="rp_platform")
        with fc2:
            filter_sentiment = st.selectbox("Sentiment", ['All', '😊 Positive', '😡 Negative', '😐 Neutral'], key="rp_sentiment")
        
        sort_by = st.selectbox("Sort by", ['Most Recent', 'Most Likes', 'Most Comments'], key="rp_sort")
        
        # Apply filters
        filtered_df = df.copy()
        
        # Platform filter
        if filter_platform != 'All':
            filtered_df = filtered_df[filtered_df['platform'] == filter_platform]
        
        # Sentiment filter
        if filter_sentiment != 'All':
            sent_map = {'😊 Positive': 'Positive', '😡 Negative': 'Negative', '😐 Neutral': 'Neutral'}
            filtered_df = filtered_df[filtered_df['sentiment'] == sent_map.get(filter_sentiment, filter_sentiment)]
    
        # Network Provider + Location filter (OR logic)
        # Post matches if it contains Location OR Provider keywords
        selected_provider = st.session_state.get('selected_provider', 'All Providers')
        selected_location = st.session_state.get('selected_location', 'All Locations')
        
        provider_active = selected_provider != 'All Providers'
        location_active = selected_location not in ['All Locations', '── Negeri ──']
        
        if provider_active or location_active:
            # Provider keywords
            provider_keywords_map = {
                'CelcomDigi': [
                    'celcom', 'digi', 'celcomdigi', 'celcom digi',
                    '#celcom', '#digi', '#celcomdigi', 'celcom axiata', 'digi telecommunications'
                ],
                'Maxis/Hotlink': [
                    'maxis', 'hotlink', 'maxis berhad', '#maxis', '#hotlink',
                    'maxisone', 'maxis fibre'
                ],
                'U Mobile': [
                    'u mobile', 'umobile', '#umobile', '#umobilemy', 'u-mobile',
                    'giler unlimited', 'gooma'
                ],
                'Unifi': [
                    'unifi', 'tm unifi', '#unifi', '#unifimy', 'unifimobile',
                    'unifi mobile', 'telekom malaysia', 'tm',
                    'unifi air', 'unifi lite', 'unifi turbo'
                ],
                'YES': [
                    'yes 4g', 'yes 5g', 'yes4g', 'yes5g', '#yes4g', '#yes5g',
                    'ytl communications', 'yes network', 'yes lte'
                ]
            }
            
            # State keywords
            state_keywords_map = {
                'Johor': ['johor', 'johor bahru', 'jb', 'iskandar', 'batu pahat', 'muar', 'kluang', 'pontian', 'segamat', 'mersing', 'kulai', 'pasir gudang', 'skudai', 'gelang patah', 'nusajaya'],
                'Kedah': ['kedah', 'alor setar', 'langkawi', 'sungai petani', 'kulim', 'jitra', 'baling', 'yan', 'padang terap'],
                'Kelantan': ['kelantan', 'kota bharu', 'kb', 'pasir mas', 'tumpat', 'machang', 'tanah merah', 'gua musang', 'bachok'],
                'Melaka': ['melaka', 'malacca', 'ayer keroh', 'alor gajah', 'jasin', 'masjid tanah'],
                'Negeri Sembilan': ['negeri sembilan', 'n9', 'ns', 'seremban', 'port dickson', 'pd', 'nilai', 'jelebu', 'kuala pilah', 'rembau', 'tampin'],
                'Pahang': ['pahang', 'kuantan', 'temerloh', 'bentong', 'raub', 'cameron highlands', 'cameron', 'genting', 'fraser hill', 'jerantut', 'pekan', 'rompin', 'lipis'],
                'Perak': ['perak', 'ipoh', 'taiping', 'teluk intan', 'sitiawan', 'manjung', 'lumut', 'kampar', 'slim river', 'batu gajah', 'gopeng', 'seri iskandar'],
                'Perlis': ['perlis', 'kangar', 'arau', 'padang besar', 'kuala perlis'],
                'Pulau Pinang': ['penang', 'pulau pinang', 'george town', 'georgetown', 'bayan lepas', 'butterworth', 'bukit mertajam', 'bm', 'seberang perai', 'nibong tebal', 'balik pulau', 'tanjung bungah', 'gurney'],
                'Sabah': ['sabah', 'kota kinabalu', 'kk', 'sandakan', 'tawau', 'lahad datu', 'semporna', 'keningau', 'ranau', 'kundasang', 'beaufort', 'papar', 'tuaran'],
                'Sarawak': ['sarawak', 'kuching', 'miri', 'sibu', 'bintulu', 'sri aman', 'kapit', 'limbang', 'sarikei', 'mukah'],
                'Selangor': ['selangor', 'shah alam', 'petaling jaya', 'pj', 'subang', 'subang jaya', 'klang', 'ampang', 'cheras', 'kajang', 'bangi', 'cyberjaya', 'puchong', 'rawang', 'gombak', 'sepang', 'serdang', 'setia alam', 'kota damansara', 'damansara', 'ss2', 'usj', 'sunway'],
                'Terengganu': ['terengganu', 'kuala terengganu', 'kt', 'dungun', 'kemaman', 'marang', 'besut', 'setiu', 'hulu terengganu', 'redang', 'perhentian'],
                'W.P. Kuala Lumpur': ['kuala lumpur', 'kl', 'bukit bintang', 'klcc', 'bangsar', 'mont kiara', 'kepong', 'sentul', 'wangsa maju', 'titiwangsa', 'chow kit', 'brickfields', 'mid valley', 'pavilion', 'setapak', 'segambut', 'lembah pantai'],
                'W.P. Putrajaya': ['putrajaya', 'presint', 'ioi city', 'cyberjaya'],
                'W.P. Labuan': ['labuan'],
            }
            
            # Malay language keywords for Malaysia Only
            malay_keywords = [
                'teruk', 'memang', 'sangat', 'betul', 'gila', 'macam', 'takde', 'tak boleh',
                'kenapa', 'sebab', 'masalah', 'boleh', 'lepas', 'dekat', 'nak', 'dah',
                'korang', 'aku', 'ko', 'kau', 'dia', 'dorang', 'diorang',
                'wei', 'weh', 'lah', 'kan', 'ni', 'tu', 'je', 'jer',
                'bestnya', 'gempak', 'mantap', 'power', 'fuyoh', 'alamak', 'syok',
                'mamak', 'tapau', 'lepak', 'komplen', 'rosak', 'hancur',
                'celcom', 'digi', 'maxis', 'unifi', 'hotlink', 'umobile',
                'ringgit', 'rm', 'sdn bhd', 'berhad',
                'assalamualaikum', 'alhamdulillah', 'insyaallah',
                'kampung', 'taman', 'jalan', 'bandar',
            ]
            
            # Exclude keywords
            exclude_keywords = ['indonesia', 'jakarta', 'bali', 'surabaya', 'bandung', 'singapore', 'singapura']
            
            # Build keyword lists
            provider_kw = provider_keywords_map.get(selected_provider, []) if provider_active else []
            
            if location_active:
                if selected_location == 'Malaysia Only':
                    malaysia_general = ['malaysia', 'msia', 'my'] + [kw for kwlist in state_keywords_map.values() for kw in kwlist]
                    location_kw = malaysia_general + malay_keywords
                else:
                    location_kw = state_keywords_map.get(selected_location, [])
            else:
                location_kw = []
            
            def matches_filter(row):
                content = str(row.get('content', '')).lower()
                author = str(row.get('author', '')).lower()
                hashtags = str(row.get('hashtags', '')).lower()
                page = str(row.get('page', '')).lower()
                combined = f"{content} {author} {hashtags} {page}"
                
                # Exclude non-Malaysia content
                if location_active:
                    for kw in exclude_keywords:
                        if kw in combined:
                            return False
                
                # OR logic: match if provider OR location found
                provider_match = any(kw in combined for kw in provider_kw) if provider_kw else False
                location_match = any(kw in combined for kw in location_kw) if location_kw else False
                
                if provider_active and location_active:
                    return provider_match or location_match  # OR: either one matches
                elif provider_active:
                    return provider_match
                else:
                    return location_match
            
            filtered_df = filtered_df[filtered_df.apply(matches_filter, axis=1)]
    
        # Sort
        # Always sort by platform order first: Facebook → Instagram → X
        platform_order = {'Facebook': 0, 'Instagram': 1, 'X': 2}
        filtered_df['_platform_order'] = filtered_df['platform'].map(platform_order).fillna(3)
    
        if sort_by == 'Most Likes':
            filtered_df = filtered_df.sort_values(['_platform_order', 'likes'], ascending=[True, False])
        elif sort_by == 'Most Comments':
            filtered_df = filtered_df.sort_values(['_platform_order', 'comments'], ascending=[True, False])
        elif sort_by == 'Most Recent' and 'date' in filtered_df.columns:
            try:
                if 'date_parsed' not in filtered_df.columns:
                    filtered_df['date_parsed'] = pd.to_datetime(filtered_df['date'], errors='coerce')
                filtered_df = filtered_df.sort_values(['_platform_order', 'date_parsed'], ascending=[True, False])
            except Exception:
                filtered_df = filtered_df.sort_values('_platform_order', ascending=True)
        else:
            filtered_df = filtered_df.sort_values('_platform_order', ascending=True)
    
        # Clean up temp column
        filtered_df = filtered_df.drop(columns=['_platform_order'], errors='ignore')
    
        # Show count
        has_active_filter = provider_active or location_active
        if has_active_filter:
            # Build filter label
            filter_labels = []
            if location_active:
                filter_labels.append(selected_location)
            if provider_active:
                filter_labels.append(selected_provider)
            filter_label = ' + '.join(filter_labels)
            
            filtered_count = len(filtered_df)
            total_count = len(df)
            excluded_count = total_count - filtered_count
            if excluded_count > 0:
                st.warning(f"📊 Showing {filtered_count} of {total_count} posts ({excluded_count} posts excluded by '{filter_label}' filter)")
                show_all = st.checkbox("🔓 Show all posts (ignore filters)", value=False)
                if show_all:
                    filtered_df = df.copy()
                    if filter_platform != 'All':
                        filtered_df = filtered_df[filtered_df['platform'] == filter_platform]
                    st.info(f"📊 Showing all {len(filtered_df)} posts")
            else:
                st.info(f"📊 Showing {filtered_count} of {total_count} posts")
        else:
            st.info(f"📊 Showing {len(filtered_df)} of {len(df)} posts")
    
        # Display posts in scrollable container
        posts_container = st.container(height=700)
        
        # Provider & State detection keywords for tagging
        _provider_detect = {
            'CelcomDigi': ['celcom', 'digi', 'celcomdigi'],
            'Maxis': ['maxis', 'hotlink', 'maxisone'],
            'U Mobile': ['u mobile', 'umobile'],
            'Unifi': ['unifi', 'unifimobile', 'unifi mobile'],
            'YES': ['yes 4g', 'yes 5g', 'yes4g', 'yes5g'],
        }
        
        # Two-level location: {negeri: {area_display_name: [keywords]}}
        # Keyword pertama setiap negeri (cth 'johor') = match negeri je tanpa daerah
        _location_detect = {
            'Johor': {
                '_state': ['johor'],
                'Johor Bahru': ['johor bahru', 'jb'],
                'Iskandar Puteri': ['iskandar puteri', 'nusajaya'],
                'Batu Pahat': ['batu pahat'],
                'Muar': ['muar'],
                'Kluang': ['kluang'],
                'Pontian': ['pontian'],
                'Segamat': ['segamat'],
                'Mersing': ['mersing'],
                'Kulai': ['kulai'],
                'Pasir Gudang': ['pasir gudang'],
                'Skudai': ['skudai'],
                'Gelang Patah': ['gelang patah'],
                'Tangkak': ['tangkak'],
                'Kota Tinggi': ['kota tinggi'],
                'Senai': ['senai'],
            },
            'Kedah': {
                '_state': ['kedah'],
                'Alor Setar': ['alor setar'],
                'Langkawi': ['langkawi'],
                'Sungai Petani': ['sungai petani'],
                'Kulim': ['kulim'],
                'Jitra': ['jitra'],
                'Baling': ['baling'],
                'Yan': ['yan kedah'],
                'Pendang': ['pendang'],
                'Pokok Sena': ['pokok sena'],
                'Kubang Pasu': ['kubang pasu'],
            },
            'Kelantan': {
                '_state': ['kelantan'],
                'Kota Bharu': ['kota bharu', 'kota baru'],
                'Pasir Mas': ['pasir mas'],
                'Tumpat': ['tumpat'],
                'Machang': ['machang'],
                'Tanah Merah': ['tanah merah'],
                'Gua Musang': ['gua musang'],
                'Bachok': ['bachok'],
                'Kuala Krai': ['kuala krai'],
                'Jeli': ['jeli'],
            },
            'Melaka': {
                '_state': ['melaka', 'malacca'],
                'Ayer Keroh': ['ayer keroh'],
                'Alor Gajah': ['alor gajah'],
                'Jasin': ['jasin'],
                'Masjid Tanah': ['masjid tanah'],
            },
            'N. Sembilan': {
                '_state': ['negeri sembilan', 'n9', 'n.sembilan'],
                'Seremban': ['seremban'],
                'Port Dickson': ['port dickson'],
                'Nilai': ['nilai'],
                'Jelebu': ['jelebu'],
                'Kuala Pilah': ['kuala pilah'],
                'Rembau': ['rembau'],
                'Tampin': ['tampin'],
            },
            'Pahang': {
                '_state': ['pahang'],
                'Kuantan': ['kuantan'],
                'Temerloh': ['temerloh'],
                'Bentong': ['bentong'],
                'Raub': ['raub'],
                'Cameron Highlands': ['cameron highlands', 'cameron'],
                'Genting': ['genting'],
                'Fraser Hill': ['fraser hill'],
                'Jerantut': ['jerantut'],
                'Pekan': ['pekan pahang', 'daerah pekan'],
                'Rompin': ['rompin'],
                'Lipis': ['lipis'],
                'Bera': ['bera'],
                'Maran': ['maran'],
            },
            'Perak': {
                '_state': ['perak'],
                'Ipoh': ['ipoh'],
                'Taiping': ['taiping'],
                'Teluk Intan': ['teluk intan'],
                'Sitiawan': ['sitiawan'],
                'Manjung': ['manjung'],
                'Lumut': ['lumut'],
                'Kampar': ['kampar'],
                'Slim River': ['slim river'],
                'Batu Gajah': ['batu gajah'],
                'Gopeng': ['gopeng'],
                'Seri Iskandar': ['seri iskandar'],
                'Tapah': ['tapah'],
                'Gerik': ['gerik'],
            },
            'Perlis': {
                '_state': ['perlis'],
                'Kangar': ['kangar'],
                'Arau': ['arau'],
                'Padang Besar': ['padang besar'],
                'Kuala Perlis': ['kuala perlis'],
            },
            'P. Pinang': {
                '_state': ['penang', 'pulau pinang'],
                'George Town': ['george town', 'georgetown'],
                'Bayan Lepas': ['bayan lepas'],
                'Butterworth': ['butterworth'],
                'Bukit Mertajam': ['bukit mertajam'],
                'Seberang Perai': ['seberang perai'],
                'Nibong Tebal': ['nibong tebal'],
                'Balik Pulau': ['balik pulau'],
                'Tanjung Bungah': ['tanjung bungah'],
                'Gurney': ['gurney'],
                'Air Itam': ['air itam'],
                'Jelutong': ['jelutong'],
                'Batu Ferringhi': ['batu ferringhi'],
            },
            'Sabah': {
                '_state': ['sabah'],
                'Kota Kinabalu': ['kota kinabalu'],
                'Sandakan': ['sandakan'],
                'Tawau': ['tawau'],
                'Lahad Datu': ['lahad datu'],
                'Semporna': ['semporna'],
                'Keningau': ['keningau'],
                'Ranau': ['ranau'],
                'Kundasang': ['kundasang'],
                'Beaufort': ['beaufort'],
                'Papar': ['papar'],
                'Tuaran': ['tuaran'],
                'Penampang': ['penampang'],
                'Putatan': ['putatan'],
                'Kudat': ['kudat'],
                'Kota Belud': ['kota belud'],
                'Sipitang': ['sipitang'],
                'Telipok': ['telipok'],
                'Inanam': ['inanam'],
                'Kinabatangan': ['kinabatangan'],
                'Beluran': ['beluran'],
                'Kunak': ['kunak'],
                'Tongod': ['tongod'],
                'Nabawan': ['nabawan'],
                'Kota Marudu': ['kota marudu'],
                'Pitas': ['pitas'],
            },
            'Sarawak': {
                '_state': ['sarawak'],
                'Kuching': ['kuching'],
                'Miri': ['miri'],
                'Sibu': ['sibu'],
                'Bintulu': ['bintulu'],
                'Sri Aman': ['sri aman'],
                'Kapit': ['kapit'],
                'Limbang': ['limbang'],
                'Sarikei': ['sarikei'],
                'Mukah': ['mukah'],
                'Betong': ['betong'],
                'Serian': ['serian'],
                'Lundu': ['lundu'],
                'Lawas': ['lawas'],
                'Marudi': ['marudi'],
                'Saratok': ['saratok'],
            },
            'Selangor': {
                '_state': ['selangor'],
                'Shah Alam': ['shah alam'],
                'Petaling Jaya': ['petaling jaya'],
                'Subang Jaya': ['subang jaya', 'subang'],
                'Klang': ['klang'],
                'Ampang': ['ampang'],
                'Cheras': ['cheras'],
                'Kajang': ['kajang'],
                'Bangi': ['bangi'],
                'Cyberjaya': ['cyberjaya'],
                'Puchong': ['puchong'],
                'Rawang': ['rawang'],
                'Gombak': ['gombak'],
                'Sepang': ['sepang'],
                'Serdang': ['serdang'],
                'Setia Alam': ['setia alam'],
                'Kota Damansara': ['kota damansara'],
                'Damansara': ['damansara'],
                'USJ': ['usj'],
                'Sunway': ['sunway'],
                'Dengkil': ['dengkil'],
                'Kuala Selangor': ['kuala selangor'],
                'Sabak Bernam': ['sabak bernam'],
                'Hulu Langat': ['hulu langat'],
                'Hulu Selangor': ['hulu selangor'],
            },
            'Terengganu': {
                '_state': ['terengganu'],
                'Kuala Terengganu': ['kuala terengganu'],
                'Dungun': ['dungun'],
                'Kemaman': ['kemaman'],
                'Marang': ['marang'],
                'Besut': ['besut'],
                'Setiu': ['setiu'],
                'Hulu Terengganu': ['hulu terengganu'],
                'Redang': ['redang'],
                'Perhentian': ['perhentian'],
            },
            'KL': {
                '_state': ['kuala lumpur'],
                'Bukit Bintang': ['bukit bintang'],
                'KLCC': ['klcc'],
                'Bangsar': ['bangsar'],
                'Mont Kiara': ['mont kiara'],
                'Kepong': ['kepong'],
                'Sentul': ['sentul'],
                'Wangsa Maju': ['wangsa maju'],
                'Titiwangsa': ['titiwangsa'],
                'Chow Kit': ['chow kit'],
                'Brickfields': ['brickfields'],
                'Mid Valley': ['mid valley'],
                'Setapak': ['setapak'],
                'Segambut': ['segambut'],
                'Lembah Pantai': ['lembah pantai'],
                'Sri Petaling': ['sri petaling'],
                'Desa Petaling': ['desa petaling'],
                'Bukit Jalil': ['bukit jalil'],
                'Taman Tun': ['taman tun'],
                'Hartamas': ['hartamas'],
                'Jalan Ipoh': ['jalan ipoh'],
            },
            'Putrajaya': {
                '_state': ['putrajaya'],
                'Presint': ['presint'],
                'IOI City': ['ioi city'],
            },
            'Labuan': {
                '_state': ['labuan'],
            },
        }
        
        def detect_provider(text):
            text_l = text.lower()
            for provider, kws in _provider_detect.items():
                for kw in kws:
                    if kw in text_l:
                        return provider
            return None
        
        def detect_location(text):
            """
            Detect location from text. Returns (area, state) tuple.
            - Kalau jumpa daerah/bandar: ('Sandakan', 'Sabah')
            - Kalau jumpa negeri je: (None, 'Sabah')
            - Kalau takde: (None, None)
            
            Strategy: Collect ALL matches, then pick the LONGEST keyword match
            (most specific). This prevents "pekan" (Pahang) overriding "kota belud" (Sabah).
            """
            text_l = text.lower()
            
            # Collect all area-level matches: (keyword_length, area_name, state)
            area_matches = []
            for state, areas in _location_detect.items():
                for area_name, kws in areas.items():
                    if area_name == '_state':
                        continue
                    for kw in kws:
                        if kw in text_l:
                            area_matches.append((len(kw), area_name, state))
            
            # If we have area matches, pick the longest keyword (most specific)
            if area_matches:
                area_matches.sort(key=lambda x: x[0], reverse=True)
                best = area_matches[0]
                return (best[1], best[2])
            
            # No area match — check state-level keywords
            state_matches = []
            for state, areas in _location_detect.items():
                state_kws = areas.get('_state', [])
                for kw in state_kws:
                    if kw in text_l:
                        state_matches.append((len(kw), state))
            
            if state_matches:
                state_matches.sort(key=lambda x: x[0], reverse=True)
                return (None, state_matches[0][1])
            
            return (None, None)
        
        with posts_container:
            for idx, row in filtered_df.iterrows():
                platform = row['platform']
                platform_class = f"{platform.lower()}-tag"
            
                with st.container():
                    # Platform tag + Sentiment badge
                    sentiment = row.get('sentiment', 'Neutral')
                    sentiment_emoji = row.get('sentiment_emoji', '😐')
                    if sentiment == 'Positive':
                        sent_color = "#10b981"
                        sent_bg = "rgba(16, 185, 129, 0.15)"
                    elif sentiment == 'Negative':
                        sent_color = "#ef4444"
                        sent_bg = "rgba(239, 68, 68, 0.15)"
                    else:
                        sent_color = "#6b7280"
                        sent_bg = "rgba(107, 114, 128, 0.15)"
                    
                    # Detect provider & location from content
                    post_text = f"{row.get('content', '')} {row.get('hashtags', '')} {row.get('author', '')}"
                    detected_provider = detect_provider(post_text)
                    detected_area, detected_state = detect_location(post_text)
                    
                    # Build tags HTML
                    # 1) Platform tag
                    tags_html = f'<span class="platform-tag {platform_class}">{platform}</span>'
                    
                    # 2) Sentiment tag
                    tags_html += f' <span style="display:inline-block; padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: 600; background: {sent_bg}; color: {sent_color}; margin-left: 4px;">{sentiment_emoji} {sentiment}</span>'
                    
                    # 3) Keyword tag (sentiasa papar)
                    tags_html += f' <span style="display:inline-block; padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: 600; background: rgba(99, 102, 241, 0.15); color: #818cf8; margin-left: 4px;">🔍 {row.get("keyword", "")}</span>'
                    
                    # 4) Provider tag (hanya kalau detected)
                    if detected_provider:
                        tags_html += f' <span style="display:inline-block; padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: 600; background: rgba(245, 158, 11, 0.15); color: #f59e0b; margin-left: 4px;">📶 {detected_provider}</span>'
                    
                    # 5) Location tag (daerah + negeri, atau negeri sahaja)
                    if detected_state:
                        if detected_area:
                            location_label = f"{detected_area}, {detected_state}"
                        else:
                            location_label = detected_state
                        tags_html += f' <span style="display:inline-block; padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: 600; background: rgba(34, 197, 94, 0.15); color: #22c55e; margin-left: 4px;">📍 {location_label}</span>'
                    
                    st.markdown(tags_html, unsafe_allow_html=True)
                    st.markdown(f"**@{row['author']}**")
                    
                    # Content (truncated for compact view)
                    content = str(row['content'])
                    st.write(content[:200] + ('...' if len(content) > 200 else ''))
                    
                    if row.get('hashtags'):
                        st.caption(f"#{row['hashtags']}")
                    
                    # Compact metrics row
                    likes_val = f"{row['likes']:,}"
                    comments_val = f"{row['comments']:,}"
                    views_str = ""
                    if 'views' in row and pd.notna(row.get('views')) and row['views'] > 0:
                        views_str = f" · 👁️ {int(row['views']):,}"
                    shares_str = ""
                    if 'shares' in row and pd.notna(row.get('shares')) and row['shares'] > 0:
                        shares_str = f" · 🔄 {int(row['shares']):,}"
                    
                    # Date
                    date_str = ""
                    if row.get('date'):
                        try:
                            date_str = pd.to_datetime(row['date']).strftime('%b %d, %Y %I:%M %p')
                        except Exception:
                            date_str = str(row['date'])
                    
                    st.caption(f"👍 {likes_val} · 💬 {comments_val}{views_str}{shares_str}")
                    if date_str:
                        st.caption(f"📅 {date_str}")
                
                    if row.get('url'):
                        st.markdown(f"[🔗 View Post]({row['url']})")
                
                    st.markdown("---")

else:
    # Government / Corporate Analytics Landing Page
    
    if dark_mode:
        card_bg = "#1e293b"
        card_border = "#334155"
        text_primary = "#e2e8f0"
        text_secondary = "#94a3b8"
        text_muted = "#64748b"
        section_bg = "#0f172a"
        accent = "#38bdf8"
        accent2 = "#2563eb"
        stat_num = "#38bdf8"
        divider = "#334155"
        kpi_bg = "#1e293b"
        kpi_border = "#334155"
        tag_bg = "rgba(56, 189, 248, 0.15)"
        tag_text = "#38bdf8"
        tag_border = "rgba(56, 189, 248, 0.3)"
    else:
        card_bg = "#ffffff"
        card_border = "#e5e7eb"
        text_primary = "#111827"
        text_secondary = "#374151"
        text_muted = "#6b7280"
        section_bg = "#f9fafb"
        accent = "#1d4ed8"
        accent2 = "#2563eb"
        stat_num = "#1d4ed8"
        divider = "#e5e7eb"
        kpi_bg = "#ffffff"
        kpi_border = "#e5e7eb"
        tag_bg = "#eef2ff"
        tag_text = "#3730a3"
        tag_border = "#c7d2fe"
    
    # KPI box shadow for depth
    kpi_shadow = "box-shadow: 0 1px 3px rgba(0,0,0,0.08);" if not dark_mode else ""
    section_shadow = "box-shadow: 0 1px 3px rgba(0,0,0,0.06);" if not dark_mode else ""
    card_shadow = "box-shadow: 0 2px 8px rgba(0,0,0,0.06);" if not dark_mode else ""
    
    # Overview KPI boxes (placeholder stats)
    st.markdown(f"""
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 28px;">
        <div style="
            background: {kpi_bg}; border: 1px solid {kpi_border}; border-radius: 10px;
            padding: 20px; text-align: center; {kpi_shadow}
        ">
            <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; color: {text_muted}; margin-bottom: 6px;">Platforms</div>
            <div style="font-size: 1.8rem; font-weight: 700; color: {stat_num};">3</div>
            <div style="font-size: 0.75rem; color: {text_muted};">FB · IG · X</div>
        </div>
        <div style="
            background: {kpi_bg}; border: 1px solid {kpi_border}; border-radius: 10px;
            padding: 20px; text-align: center; {kpi_shadow}
        ">
            <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; color: {text_muted}; margin-bottom: 6px;">Data Points</div>
            <div style="font-size: 1.8rem; font-weight: 700; color: {stat_num};">10+</div>
            <div style="font-size: 0.75rem; color: {text_muted};">Per post extracted</div>
        </div>
        <div style="
            background: {kpi_bg}; border: 1px solid {kpi_border}; border-radius: 10px;
            padding: 20px; text-align: center; {kpi_shadow}
        ">
            <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; color: {text_muted}; margin-bottom: 6px;">Location Filter</div>
            <div style="font-size: 1.8rem; font-weight: 700; color: {stat_num};">4</div>
            <div style="font-size: 0.75rem; color: {text_muted};">MY · SG · ID · All</div>
        </div>
        <div style="
            background: {kpi_bg}; border: 1px solid {kpi_border}; border-radius: 10px;
            padding: 20px; text-align: center; {kpi_shadow}
        ">
            <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; color: {text_muted}; margin-bottom: 6px;">Export</div>
            <div style="font-size: 1.8rem; font-weight: 700; color: {stat_num};">CSV</div>
            <div style="font-size: 0.75rem; color: {text_muted};">One-click download</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Workflow section
    st.markdown(f"""
    <div style="
        background: {section_bg}; border: 1px solid {card_border}; border-radius: 10px;
        padding: 28px 32px; margin-bottom: 24px; {section_shadow}
    ">
        <div style="font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px; color: {accent}; font-weight: 600; margin-bottom: 12px;">
            ■ HOW IT WORKS
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px;">
            <div style="position: relative;">
                <div style="
                    width: 32px; height: 32px; background: {accent}; color: white;
                    border-radius: 50%; display: flex; align-items: center; justify-content: center;
                    font-size: 0.8rem; font-weight: 700; margin-bottom: 10px;
                ">1</div>
                <div style="font-weight: 600; color: {text_primary}; font-size: 0.9rem; margin-bottom: 4px;">Configure Search</div>
                <div style="font-size: 0.8rem; color: {text_muted}; line-height: 1.5;">Enter keyword, select platforms and set location filter</div>
            </div>
            <div>
                <div style="
                    width: 32px; height: 32px; background: {accent}; color: white;
                    border-radius: 50%; display: flex; align-items: center; justify-content: center;
                    font-size: 0.8rem; font-weight: 700; margin-bottom: 10px;
                ">2</div>
                <div style="font-weight: 600; color: {text_primary}; font-size: 0.9rem; margin-bottom: 4px;">Scrape Data</div>
                <div style="font-size: 0.8rem; color: {text_muted}; line-height: 1.5;">System queries Facebook, Instagram &amp; X (Twitter) via Apify API</div>
            </div>
            <div>
                <div style="
                    width: 32px; height: 32px; background: {accent}; color: white;
                    border-radius: 50%; display: flex; align-items: center; justify-content: center;
                    font-size: 0.8rem; font-weight: 700; margin-bottom: 10px;
                ">3</div>
                <div style="font-weight: 600; color: {text_primary}; font-size: 0.9rem; margin-bottom: 4px;">Analyze &amp; Filter</div>
                <div style="font-size: 0.8rem; color: {text_muted}; line-height: 1.5;">Review engagement metrics, filter by location &amp; platform</div>
            </div>
            <div>
                <div style="
                    width: 32px; height: 32px; background: {accent}; color: white;
                    border-radius: 50%; display: flex; align-items: center; justify-content: center;
                    font-size: 0.8rem; font-weight: 700; margin-bottom: 10px;
                ">4</div>
                <div style="font-weight: 600; color: {text_primary}; font-size: 0.9rem; margin-bottom: 4px;">Export Report</div>
                <div style="font-size: 0.8rem; color: {text_muted}; line-height: 1.5;">Download filtered results as CSV for further analysis</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Data Sources section
    st.markdown(f"""
    <div style="
        background: {section_bg}; border: 1px solid {card_border}; border-radius: 10px;
        padding: 28px 32px; margin-bottom: 24px; {section_shadow}
    ">
        <div style="font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px; color: {accent}; font-weight: 600; margin-bottom: 16px;">
            ■ DATA SOURCES
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">
            <div style="
                background: {card_bg}; border: 1px solid {card_border}; border-radius: 8px;
                padding: 20px; border-top: 3px solid #1877f2; {card_shadow}
            ">
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                    <div style="
                        width: 36px; height: 36px; background: #1877f2; border-radius: 8px;
                        display: flex; align-items: center; justify-content: center; color: white; font-weight: 700; font-size: 1.1rem;
                    ">f</div>
                    <div style="font-weight: 600; color: {text_primary}; font-size: 1rem;">Facebook</div>
                </div>
                <div style="font-size: 0.8rem; color: {text_secondary}; line-height: 1.6;">
                    Public post search by keyword · Reactions, comments &amp; share counts · Author &amp; page details · Post URL &amp; timestamp
                </div>
            </div>
            <div style="
                background: {card_bg}; border: 1px solid {card_border}; border-radius: 8px;
                padding: 20px; border-top: 3px solid #e1306c; {card_shadow}
            ">
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                    <div style="
                        width: 36px; height: 36px; background: linear-gradient(45deg, #f09433, #dc2743, #bc1888); border-radius: 8px;
                        display: flex; align-items: center; justify-content: center; color: white; font-weight: 700; font-size: 1.1rem;
                    ">IG</div>
                    <div style="font-weight: 600; color: {text_primary}; font-size: 1rem;">Instagram</div>
                </div>
                <div style="font-size: 0.8rem; color: {text_secondary}; line-height: 1.6;">
                    Hashtag-based search · Likes &amp; comment counts · Caption text &amp; hashtags · Post date &amp; author profile
                </div>
            </div>
            <div style="
                background: {card_bg}; border: 1px solid {card_border}; border-radius: 8px;
                padding: 20px; border-top: 3px solid {'#e2e8f0' if dark_mode else '#000000'}; {card_shadow}
            ">
                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                    <div style="
                        width: 36px; height: 36px; background: {'#333' if dark_mode else '#000'}; border-radius: 8px;
                        display: flex; align-items: center; justify-content: center; color: white; font-weight: 700; font-size: 0.8rem;
                    ">TT</div>
                    <div style="font-weight: 600; color: {text_primary}; font-size: 1rem;">X (Twitter)</div>
                </div>
                <div style="font-size: 0.8rem; color: {text_secondary}; line-height: 1.6;">
                    Keyword video search · Views, likes, shares &amp; comments · Hashtag extraction · Video URL &amp; creator info
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Quick start
    st.markdown(f"""
    <div style="
        background: {section_bg}; border: 1px solid {card_border}; border-radius: 10px;
        padding: 24px 32px; {section_shadow}
    ">
        <div style="font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px; color: {accent}; font-weight: 600; margin-bottom: 14px;">
            ■ SUGGESTED QUERIES
        </div>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <span style="padding: 6px 16px; background: {tag_bg}; color: {tag_text}; border: 1px solid {tag_border}; border-radius: 6px; font-size: 0.82rem; font-weight: 500;">line teruk</span>
            <span style="padding: 6px 16px; background: {tag_bg}; color: {tag_text}; border: 1px solid {tag_border}; border-radius: 6px; font-size: 0.82rem; font-weight: 500;">line celcom</span>
            <span style="padding: 6px 16px; background: {tag_bg}; color: {tag_text}; border: 1px solid {tag_border}; border-radius: 6px; font-size: 0.82rem; font-weight: 500;">internet laju</span>
            <span style="padding: 6px 16px; background: {tag_bg}; color: {tag_text}; border: 1px solid {tag_border}; border-radius: 6px; font-size: 0.82rem; font-weight: 500;">digital marketing</span>
            <span style="padding: 6px 16px; background: {tag_bg}; color: {tag_text}; border: 1px solid {tag_border}; border-radius: 6px; font-size: 0.82rem; font-weight: 500;">content creator</span>
            <span style="padding: 6px 16px; background: {tag_bg}; color: {tag_text}; border: 1px solid {tag_border}; border-radius: 6px; font-size: 0.82rem; font-weight: 500;">social media</span>
        </div>
    </div>
    """, unsafe_allow_html=True)