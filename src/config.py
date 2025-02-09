import os

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Paths
PARENT_DIR = os.path.dirname(BASE_DIR)
SETTINGS_FILE = os.path.join(PARENT_DIR, "settings.cfg")
HISTORY_DIR = os.path.join(PARENT_DIR, "history")
CHATGTK_SCRIPT = os.path.join(BASE_DIR, "ChatGTK.py")
