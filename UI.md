# DeepClient UI Specification & Theme Design System

> For the comprehensive, full-length specification, please see **[THEME.md](file:///d:/Trella/THEME.md)**.

---

## Quick Reference Summary

### 1. Dual-Mode Color Tokens

| Token | Light Mode | Dark Mode | Semantic Role |
| :--- | :--- | :--- | :--- |
| **Canvas** | `#F8FAFC` | `#06141B` | App background |
| **Card / Surface** | `#FFFFFF` | `#11212D` | Cards, modals, sidebars |
| **Elevated / Input** | `#F1F5F9` | `#162736` | Text inputs, hover states |
| **Brand Primary** | `#253745` | `#253745` | Action buttons, primary badges |
| **Accent / Stroke** | `#4A5C6A` | `#4A5C6A` | Borders, hover strokes, chips |
| **Text Primary** | `#06141B` | `#F1F5F9` | Headings, active text |
| **Text Secondary** | `#334155` | `#CCD0CF` | Body descriptions |
| **Text Muted** | `#64748B` | `#9BA8AB` | Timestamps, placeholders |
| **Border Divider** | `#E2E8F0` | `#253745` | Card borders, table dividers |

---

### 2. Border Radius Standard

- `rounded-md` (6px): Tooltips, checkboxes, small indicators.
- `rounded-lg` (8px): Dropdown list items, table rows, inner form widgets.
- `rounded-xl` (12px): Standard buttons, text inputs, metric boxes.
- `rounded-2xl` (16px): Main cards, dossier profiles, modal dialogs, drawers.
- `rounded-full` (9999px): Status badges, avatar circles, switch toggles.

---

### 3. Font Sizes & Typography

- `text-xs` (12px / 16px line-height): Badges, status pills, timestamps.
- `text-sm` (14px / 20px line-height): Nav items, form labels, body text.
- `text-base` (16px / 24px line-height): Lead paragraphs, modal content.
- `text-lg` (18px / 28px line-height): Section headers, card titles.
- `text-2xl` (24px / 32px line-height): Screen headings, KPI metrics.
- `text-3xl` (30px / 36px line-height): Page titles.
- `text-4xl` - `text-5xl`: Marketing & Auth hero titles.

---

### 4. Logo Assets

- **Light Mode Logo**: `/public/DeepClient-light.png` (`dark:hidden`)
- **Dark Mode Logo**: `/public/DeepClient-dark.png` (`hidden dark:block`)

---

### 5. Animation Curves

- **Framer Motion Page Transitions**:
  - `duration`: `0.26s`
  - `ease`: `[0.22, 1, 0.36, 1]` (custom cubic bezier)
  - `initial`: `{ opacity: 0, y: 8 }` -> `animate`: `{ opacity: 1, y: 0 }`
- **Shimmer Animation**:
  - `animation`: `shimmer 1.8s infinite linear`
  - `background-size`: `200% 100%`

*Refer to [THEME.md](file:///d:/Trella/THEME.md) for full React Native / Mobile blueprints and theme providers.*
