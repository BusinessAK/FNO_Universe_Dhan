import streamlit as st

class UIStateService:
    """
    Centralized Streamlit Session State Management Service.
    Standardizes state keys, prevents runtime key collisions, and abstracts widget state mutations.
    """
    def __init__(self, trading_dates: list, all_symbols: list):
        self.trading_dates = trading_dates
        self.all_symbols = all_symbols

    def initialize_defaults(self):
        """Seeds default key states in st.session_state if they do not exist."""
        if "selected_date" not in st.session_state and self.trading_dates:
            st.session_state.selected_date = self.trading_dates[-1]
            
        if "selected_symbol" not in st.session_state and self.all_symbols:
            st.session_state.selected_symbol = self.all_symbols[0]
            
        if "view_mode" not in st.session_state:
            st.session_state.view_mode = "⚡ VANGUARD SCREENER TERMINAL"

    @property
    def selected_date(self) -> str:
        return st.session_state.get("selected_date", self.trading_dates[-1] if self.trading_dates else "")

    @selected_date.setter
    def selected_date(self, val: str):
        st.session_state.selected_date = val

    @property
    def selected_symbol(self) -> str:
        return st.session_state.get("selected_symbol", self.all_symbols[0] if self.all_symbols else "")

    @selected_symbol.setter
    def selected_symbol(self, val: str):
        st.session_state.selected_symbol = val
        st.session_state.symbol_selector = val # Keep in sync with sidebar selector widget key!

    @property
    def view_mode(self) -> str:
        return st.session_state.get("view_mode", "⚡ VANGUARD SCREENER TERMINAL")

    @view_mode.setter
    def view_mode(self, val: str):
        st.session_state.view_mode = val
