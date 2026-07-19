import streamlit as st
import os

def inject_styles():
    """Loads assets/theme.css and injects it into Streamlit's HTML output."""
    theme_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "theme.css")
    if os.path.exists(theme_path):
        with open(theme_path, "r") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    else:
        st.warning("⚠ Premium Vanguard CSS theme stylesheet is missing.")
