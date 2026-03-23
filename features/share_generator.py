"""
ShareGenerator — geração de cards PNG de estatísticas para compartilhamento.
"""

from config.app_imports import (
    subprocess,
    Path, Optional,
    HAS_PIL_SHARE,
    _PIL_Image, _PIL_ImageDraw, _PIL_ImageFont,
)
from core.system_controller import SystemController
from ui.ui_helpers import COLORS


# ══════════════════════════════════════════════════════════════
# 5D. SHARE GENERATOR
# ══════════════════════════════════════════════════════════════

class ShareGenerator:
    """
    Generates shareable stat cards (PNG) from usage statistics.
    Requires Pillow. Falls back to text-only if not available.
    """

    CARD_W = 800
    CARD_H = 420

    def __init__(self, config):
        self._config = config

    def get_stats(self) -> dict:
        s      = self._config.get("stats") or {}
        total_min   = s.get("total_minutes", 0)
        total_done  = s.get("total_completed", 0)
        kwh         = round(total_min * 0.05 / 60, 1)
        co2         = round(kwh * 0.5, 1)
        money       = round(kwh * 0.60, 2)

        achievements = []
        if total_done >= 10:
            achievements.append("🌱 Economizador Iniciante")
        if total_done >= 100:
            achievements.append("🏆 Guerreiro da Energia")
        if kwh >= 100:
            achievements.append("💪 Herói do Planeta")

        by_action = s.get("by_action", {})
        return {
            "minutes":      f"{total_min:,}",
            "minutes_raw":  total_min,
            "actions":      total_done,
            "kwh":          kwh,
            "co2":          co2,
            "money":        f"R$ {money:.2f}",
            "achievements": achievements,
            "by_action":    by_action,
        }

    def generate_card(self, layout: str = "minimal",
                      custom_text: str = "",
                      include_achievements: bool = True) -> Optional[Path]:
        """Generate a PNG card. Returns path or None on error."""
        if not HAS_PIL_SHARE:
            return None
        stats = self.get_stats()
        try:
            if layout == "gamer":
                img = self._make_gamer_card(stats, custom_text,
                                            include_achievements)
            else:
                img = self._make_minimal_card(stats, custom_text,
                                              include_achievements)
            out = Path.home() / "shutdown_timer_card.png"
            img.save(str(out), "PNG")
            return out
        except Exception as e:
            print(f"[ShareGen] {e}")
            return None

    def _load_font(self, size: int, bold: bool = False):
        try:
            style = "Bold" if bold else "Regular"
            return _PIL_ImageFont.truetype(
                f"C:/Windows/Fonts/segoeui{'b' if bold else ''}.ttf", size)
        except Exception:
            try:
                return _PIL_ImageFont.truetype("arial.ttf", size)
            except Exception:
                return _PIL_ImageFont.load_default()

    def _hex_to_rgb(self, h: str) -> tuple:
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _make_minimal_card(self, stats, custom_text, include_achievements):
        bg    = self._hex_to_rgb(COLORS["surface"])
        text  = self._hex_to_rgb(COLORS["text"])
        dim   = self._hex_to_rgb(COLORS["text_dim"])
        acc   = self._hex_to_rgb(COLORS["accent"])
        acc2  = self._hex_to_rgb(COLORS["accent2"])
        suc   = self._hex_to_rgb(COLORS["success"])

        img  = _PIL_Image.new("RGB", (self.CARD_W, self.CARD_H), bg)
        draw = _PIL_ImageDraw.Draw(img)

        # Accent bar top
        draw.rectangle([0, 0, self.CARD_W, 6], fill=acc)

        f_title  = self._load_font(18, bold=True)
        f_big    = self._load_font(72, bold=True)
        f_normal = self._load_font(20)
        f_small  = self._load_font(14)
        f_tag    = self._load_font(16, bold=True)

        # Title
        draw.text((50, 30), "⏻  ShutdownTimer", fill=acc, font=f_title)

        # Main stat
        draw.text((50, 80), stats["minutes"], fill=text, font=f_big)
        draw.text((50, 168), "minutos economizados", fill=dim, font=f_normal)

        # Stats row
        y = 220
        for label, val in [
            ("🌿  CO₂ evitado",    f"{stats['co2']} kg"),
            ("💡  Energia",         f"{stats['kwh']} kWh"),
            ("💰  Economia est.",   stats["money"]),
            ("⚡  Ações concluídas", str(stats["actions"])),
        ]:
            draw.text((50, y),    label, fill=dim,  font=f_small)
            draw.text((260, y),   val,   fill=text, font=f_small)
            y += 28

        # Achievements
        if include_achievements and stats["achievements"]:
            draw.text((50, y + 8), "  ".join(stats["achievements"]),
                      fill=suc, font=f_small)

        # Custom text
        if custom_text:
            draw.text((50, 330), custom_text[:80], fill=dim, font=f_small)

        # Hashtags
        draw.text((50, 370), "#ShutdownTimer  #EconomiaDeEnergia",
                  fill=acc2, font=f_tag)

        # Subtle logo area right
        draw.text((620, 80), "⏻", fill=acc, font=self._load_font(120))

        return img

    def _make_gamer_card(self, stats, custom_text, include_achievements):
        bg    = self._hex_to_rgb("#0d0f18")
        text  = self._hex_to_rgb(COLORS["text"])
        dim   = self._hex_to_rgb(COLORS["text_dim"])
        acc   = self._hex_to_rgb(COLORS["accent"])
        warn  = self._hex_to_rgb(COLORS["warning"])
        suc   = self._hex_to_rgb(COLORS["success"])
        acc2  = self._hex_to_rgb(COLORS["accent2"])

        img  = _PIL_Image.new("RGB", (self.CARD_W, self.CARD_H), bg)
        draw = _PIL_ImageDraw.Draw(img)

        # Glow bar
        draw.rectangle([0, 0, self.CARD_W, 8], fill=warn)

        f_title  = self._load_font(22, bold=True)
        f_big    = self._load_font(64, bold=True)
        f_normal = self._load_font(18)
        f_small  = self._load_font(14)
        f_tag    = self._load_font(16, bold=True)

        draw.text((50, 30), "⚡  POWER SAVED  ⚡", fill=warn, font=f_title)

        # Box
        draw.rectangle([40, 90, 600, 200],
                       fill=self._hex_to_rgb(COLORS["surface"]),
                       outline=acc, width=2)
        draw.text((60, 100), stats["minutes"] + " MIN", fill=text, font=f_big)
        draw.text((60, 172), "de economia de energia", fill=dim, font=f_normal)

        y = 220
        rows = [
            (f"🌿  CO₂ evitado: {stats['co2']} kg",   suc),
            (f"💡  Energia:      {stats['kwh']} kWh",  acc),
            (f"💰  Economia:     {stats['money']}",     warn),
        ]
        for txt, color in rows:
            draw.text((50, y), txt, fill=color, font=f_small)
            y += 26

        if include_achievements and stats["achievements"]:
            draw.text((50, y + 6), "  ".join(stats["achievements"]),
                      fill=suc, font=f_small)

        if custom_text:
            draw.text((50, 330), custom_text[:80], fill=dim, font=f_small)

        draw.text((50, 372), "#ShutdownTimer  #GameOnSaveOn",
                  fill=acc2, font=f_tag)

        # Decorative game icon
        draw.text((650, 80), "🎮", fill=warn, font=self._load_font(100))

        return img

    def get_share_text(self, stats: dict) -> str:
        lines = [
            f"⏻ ShutdownTimer — meu PC economizou {stats['minutes']} minutos!",
            f"🌿 CO₂ evitado: {stats['co2']} kg",
            f"💡 Energia: {stats['kwh']} kWh",
            f"💰 Economia estimada: {stats['money']}",
            "#ShutdownTimer #EconomiaDeEnergia",
        ]
        return "\n".join(lines)

    def copy_image_to_clipboard(self, path: Path) -> bool:
        """Copy PNG to clipboard (Windows only via PowerShell)."""
        if SystemController.PLATFORM != "Windows":
            return False
        try:
            script = (
                f'Add-Type -AssemblyName System.Windows.Forms; '
                f'[System.Windows.Forms.Clipboard]::SetImage('
                f'[System.Drawing.Image]::FromFile("{path}"))'
            )
            subprocess.run(
                ["powershell", "-Command", script],
                check=True, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            print(f"[ShareGen] clipboard: {e}")
            return False
