import os
import streamlit as st

# Cuba baca dari Streamlit secrets dulu, fallback ke env var
try:
    APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
    APIFY_API_TOKEN_FB = st.secrets["APIFY_API_TOKEN_FB"]
except:
    APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
    APIFY_API_TOKEN_FB = os.environ.get("APIFY_API_TOKEN_FB", "")

DEFAULT_POSTS_PER_KEYWORD = 5
AVAILABLE_PLATFORMS = ["instagram", "tiktok", "facebook"]
