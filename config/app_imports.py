"""
Imports centrais do ShutdownTimer v5.0
Todos os imports (padrão e opcionais) usados pelo projeto.
"""

import os
import sys
import csv
import json
import time
import uuid
import copy
import signal
import argparse
import platform
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

import customtkinter as ctk
from tkinter import messagebox, filedialog
import tkinter as tk

# ── Imports opcionais ──────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from plyer import notification as plyer_notify
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from PIL import Image as _PIL_Image, ImageDraw as _PIL_ImageDraw, ImageFont as _PIL_ImageFont
    HAS_PIL_SHARE = True
except ImportError:
    HAS_PIL_SHARE = False

try:
    from cryptography.fernet import Fernet as _Fernet
    import base64 as _base64
    import hashlib as _hashlib
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ── Feature modules (optional — degrade gracefully) ───────────
try:
    from features.voice_engine import VoiceCommandEngine
    HAS_VOICE = True
except ImportError:
    HAS_VOICE = False
    VoiceCommandEngine = None  # type: ignore[assignment,misc]

try:
    from features.email_notifier import EmailNotifier, EMAIL_PROVIDERS
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False
    EmailNotifier = None      # type: ignore[assignment,misc]
    EMAIL_PROVIDERS = {}

try:
    from features.energy_saver import EnergySaver, get_available_plans, PLATFORM as _ES_PLATFORM
    HAS_ENERGY = True
except ImportError:
    HAS_ENERGY = False
    EnergySaver = None        # type: ignore[assignment,misc]
    get_available_plans = lambda: []  # noqa: E731

# ── Feature 3.2: Calendar Integration ─────────────────────────────────────────
try:
    from features.calendar_integration import (
        CalendarManager, BrasilAPISource, ICSSource,
        GoogleCalendarSource, BRASIL_STATES,
    )
    HAS_CALENDAR = True
    # Expose sub-dependency flags from the module
    from features import calendar_integration as _cal_mod
    HAS_GOOGLE_CAL = getattr(_cal_mod, "HAS_GOOGLE_CAL", False)
    HAS_REQUESTS   = getattr(_cal_mod, "HAS_REQUESTS",   False)
    HAS_ICALENDAR  = getattr(_cal_mod, "HAS_ICALENDAR",  False)
except ImportError:
    HAS_CALENDAR   = False
    HAS_GOOGLE_CAL = False
    HAS_REQUESTS   = False
    HAS_ICALENDAR  = False
    CalendarManager = None   # type: ignore[assignment,misc]
    BRASIL_STATES   = {}
    GoogleCalendarSource = None  # type: ignore[assignment,misc]

# ── Feature 3.1: Plugin Manager ────────────────────────────────────────────────
try:
    from managers.plugin_manager import (
        PluginManager, STORE_CATALOG, STORE_CATEGORIES, PERMISSION_LABELS,
    )
    HAS_PLUGINS = True
except ImportError:
    HAS_PLUGINS = False
    PluginManager       = None  # type: ignore[assignment,misc]
    STORE_CATALOG       = []
    STORE_CATEGORIES    = ["Todos"]
    PERMISSION_LABELS   = {}

# ── Feature 3.3: Presentation Mode Enhanced ────────────────────────────────────
try:
    from features.presentation_enhanced import (
        PresentationModeEnhanced, PresentationDecider,
        PresentationTriggers, DEFAULT_WEIGHTS,
    )
    HAS_PRES_ENHANCED = True
except ImportError:
    HAS_PRES_ENHANCED = False
    PresentationModeEnhanced = None  # type: ignore[assignment,misc]
    PresentationDecider      = None  # type: ignore[assignment,misc]
    DEFAULT_WEIGHTS          = {}
