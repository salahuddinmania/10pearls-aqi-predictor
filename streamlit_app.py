"""
Streamlit Cloud Entry Point
This file serves as the main entry point for Streamlit Cloud deployment.
Streamlit Cloud automatically looks for streamlit_app.py in the root directory.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app.dashboard import *
