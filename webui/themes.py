from dataclasses import dataclass

@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    outline: str
    text: str
    accent: str
    surface_mix_percent: float

    def css_variables(self) -> str:
        mix = max(0.0, min(100.0, self.surface_mix_percent))
        return (
            ":root {\n"
            f"    --voxbench-theme-background: {self.background};\n"
            f"    --voxbench-theme-outline: {self.outline};\n"
            f"    --voxbench-theme-text: {self.text};\n"
            f"    --voxbench-theme-accent: {self.accent};\n"
            f"    --voxbench-theme-surface-mix: {mix:g}%;\n"
            "}\n"
        )


THEMES = {
    "voxbench-dark": Theme(
        name="VoxBench Dark",
        background="#0f0f11",
        outline="#3f3f46",
        text="#f4f4f5",
        accent="#ff8a1f",
        surface_mix_percent=6,
    ),
}

DEFAULT_THEME_NAME = "voxbench-dark"


def active_theme() -> Theme:
    return THEMES[DEFAULT_THEME_NAME]


def themed_styles() -> str:
    """Return the compact, framework-neutral stylesheet for the active palette."""
    return f"""
{active_theme().css_variables()}
:root {{ color-scheme: dark; --q-primary: var(--voxbench-theme-accent); --q-dark: var(--voxbench-theme-background); --q-dark-page: var(--voxbench-theme-background); }}
body, .q-page, .q-layout, .q-dialog__backdrop {{ background: var(--voxbench-theme-background); color: var(--voxbench-theme-text); }}
.q-card, .q-menu, .q-dialog__inner > div {{ background: var(--voxbench-theme-background); color: var(--voxbench-theme-text); }}
.q-tab, .q-item, .q-field__native, .q-field__input, .q-field__label, .q-field__marginal, .q-select__dropdown-icon {{ color: var(--voxbench-theme-text) !important; }}
.q-field__native::placeholder, .q-field__input::placeholder {{ color: color-mix(in srgb, var(--voxbench-theme-text), var(--voxbench-theme-background) 45%) !important; opacity: 1; }}
.q-field--outlined .q-field__control:before {{ border-color: var(--voxbench-theme-outline) !important; }}
.q-field--outlined .q-field__control:after {{ border-color: var(--voxbench-theme-outline) !important; }}
.q-field--focused .q-field__control:after {{ border-color: var(--voxbench-theme-accent) !important; }}
.q-field__control, .q-field__control-container {{ background: transparent !important; }}
.vox-secret-input .q-field__native {{ color: var(--voxbench-theme-outline) !important; }}
.vox-card {{ background: color-mix(in srgb, var(--voxbench-theme-background), var(--voxbench-theme-text) var(--voxbench-theme-surface-mix)); border: 1px solid var(--voxbench-theme-outline); border-radius: 10px; }}
.vox-page-title, .vox-primary-heading {{ color: var(--voxbench-theme-accent) !important; }}
.vox-button {{ background: transparent !important; border: 1px solid var(--voxbench-theme-outline) !important; color: var(--voxbench-theme-accent) !important; border-radius: 6px; }}
.vox-button .q-icon {{ color: var(--voxbench-theme-accent) !important; }}
.vox-button:hover {{ border-color: var(--voxbench-theme-accent) !important; background: color-mix(in srgb, var(--voxbench-theme-accent), transparent 92%) !important; }}
.q-tab--active, .q-tab--active .q-icon, .q-tab__indicator, .q-checkbox__inner--truthy, .q-radio__inner--truthy {{ color: var(--voxbench-theme-accent) !important; }}
.q-menu .q-item, .q-menu .q-item *, .q-menu .q-item--active, .q-menu .q-item--active * {{ color: var(--voxbench-theme-text) !important; }}
.q-table tbody tr.q-tr--selected {{ background: color-mix(in srgb, var(--voxbench-theme-accent), transparent 90%) !important; }}
.q-linear-progress__model {{ background: var(--voxbench-theme-accent) !important; }}
.q-link {{ color: var(--voxbench-theme-accent) !important; }}
.q-tab-panel {{ padding: 0 !important; }}
.vox-upload-shell {{ position: relative; min-height: 124px; }}
.vox-upload {{ min-height: 124px; border: 1px dashed var(--voxbench-theme-outline); border-radius: 8px; background: transparent !important; box-shadow: none !important; color: var(--voxbench-theme-text); }}
.vox-upload .q-uploader__header {{ min-height: 122px; height: 122px; background: transparent !important; color: var(--voxbench-theme-text) !important; }}
.vox-upload .q-uploader__header-content, .vox-upload .q-uploader__header-content > div {{ width: 100%; height: 100%; padding: 0; }}
.vox-upload .q-uploader__header-content .col, .vox-upload .q-uploader__list {{ display: none !important; }}
.vox-upload .q-uploader__header .q-btn {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; }}
.vox-upload.q-uploader--dnd .q-uploader__dnd {{ background: color-mix(in srgb, var(--voxbench-theme-accent), transparent 92%) !important; color: var(--voxbench-theme-text); }}
.vox-upload-icon {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: var(--voxbench-theme-outline); font-size: 52px; opacity: 0.62; pointer-events: none; }}
.vox-upload-status {{ min-height: 34px; padding: 6px 8px; border: 1px solid var(--voxbench-theme-outline); border-radius: 6px; background: transparent; }}
.vox-upload-progress {{ height: 4px; border-radius: 999px; }}
.vox-upload-success {{ color: var(--voxbench-theme-accent); font-size: 20px; }}
.vox-upload-file-label {{ flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.vox-upload-remove {{ min-width: 28px !important; min-height: 28px !important; padding: 2px !important; color: var(--voxbench-theme-accent) !important; background: transparent !important; border: 0 !important; }}
.vox-upload-remove:hover {{ color: var(--voxbench-theme-accent) !important; background: color-mix(in srgb, var(--voxbench-theme-accent), transparent 88%) !important; }}
.vox-text-input .q-field__control {{ min-height: 124px; max-height: 236px; overflow: hidden; }}
.vox-text-input textarea.q-field__native {{ min-height: 96px; max-height: 208px; overflow-y: auto !important; resize: vertical; }}
.vox-section-table .q-table__middle {{ max-height: 74vh; overflow-y: auto; }}
.vox-document-editor .q-field__control {{ height: 74vh; }}
.vox-document-editor textarea.q-field__native {{ height: calc(74vh - 28px); overflow-y: auto !important; resize: vertical; }}
.vox-global-page-counter {{ position: absolute; left: 50%; bottom: 16px; transform: translateX(-50%); z-index: 2; }}
.vox-source-chapter-controls {{ position: absolute; left: calc(50% + 92px); bottom: 16px; z-index: 2; }}
.vox-page-navigator {{ padding: 12px 18px; margin: -12px -18px; }}
.vox-muted {{ color: color-mix(in srgb, var(--voxbench-theme-text), var(--voxbench-theme-background) 38%); }}
.document-source-frame {{ width: 100%; height: 74vh; border: 1px solid var(--voxbench-theme-outline); border-radius: 6px; background: white; }}
.document-source-document {{ min-height: 74vh; overflow: auto; padding: 1rem; border: 1px solid var(--voxbench-theme-outline); border-radius: 6px; }}
"""
