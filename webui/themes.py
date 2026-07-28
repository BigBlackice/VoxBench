from dataclasses import dataclass

from webui.config import read_asset


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    outline: str
    text: str
    surface_mix_percent: float

    def css_variables(self) -> str:
        mix = max(0.0, min(100.0, self.surface_mix_percent))
        return (
            ":root {\n"
            f"    --voxbench-theme-background: {self.background};\n"
            f"    --voxbench-theme-outline: {self.outline};\n"
            f"    --voxbench-theme-text: {self.text};\n"
            f"    --voxbench-theme-surface-mix: {mix:g}%;\n"
            "}\n"
        )


THEMES = {
    "voxbench-dark": Theme(
        name="VoxBench Dark",
        background="#0f0f11",
        outline="#3f3f46",
        text="#f4f4f5",
        surface_mix_percent=6,
    ),
}

DEFAULT_THEME_NAME = "voxbench-dark"


def active_theme() -> Theme:
    return THEMES[DEFAULT_THEME_NAME]


def themed_styles() -> str:
    theme = active_theme()
    return f"{theme.css_variables()}\n{read_asset('styles.css')}"
