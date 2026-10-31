# DeepClient Design System & UI Specification

> **Version:** 1.0.0  
> **Target Platforms:** Web (React / Next.js / Tailwind CSS) & Mobile (React Native / iOS / Android)  
> **Theme Model:** Strict Dual-Mode (Light Mode & Executive Dark Mode)

---

## 1. Executive Color Palette

The DeepClient color system is a curated, executive slate palette engineered for maximum contrast, zero eye fatigue, and visual elegance in both light and dark environments.

### 1.1 Core Theme Tokens

| Token Name | HEX | RGB | HSL | Primary Semantic Usage |
| :--- | :--- | :--- | :--- | :--- |
| `canvas-dark` | `#06141B` | `rgb(6, 20, 27)` | `hsl(200, 64%, 6%)` | Dark mode main app canvas & page background |
| `card-dark` | `#11212D` | `rgb(17, 33, 45)` | `hsl(206, 45%, 12%)` | Dark mode cards, modals, sidebar, dossiers |
| `surface-dark` | `#162736` | `rgb(22, 39, 54)` | `hsl(208, 42%, 15%)` | Dark mode elevated elements, inputs, hover items |
| `brand-primary` | `#253745` | `rgb(37, 55, 69)` | `hsl(206, 30%, 21%)` | Primary action buttons, badges, dark borders |
| `brand-accent` | `#4A5C6A` | `rgb(74, 92, 106)` | `hsl(206, 18%, 35%)` | Muted borders, hover strokes, secondary badges |
| `text-muted` | `#9BA8AB` | `rgb(155, 168, 171)` | `hsl(188, 9%, 64%)` | Secondary metadata, timestamps, input placeholders |
| `text-secondary`| `#CCD0CF` | `rgb(204, 208, 207)` | `hsl(170, 4%, 81%)` | Body text in dark mode, active secondary links |
| `text-primary` | `#F1F5F9` | `rgb(241, 245, 249)` | `hsl(210, 40%, 96%)` | Headings, active states, high-contrast dark text |
| `canvas-light` | `#F8FAFC` | `rgb(248, 250, 252)` | `hsl(210, 40%, 98%)` | Light mode page canvas background |
| `card-light` | `#FFFFFF` | `rgb(255, 255, 255)` | `hsl(0, 0%, 100%)` | Light mode cards, dropdowns, sidebar, popovers |
| `border-light` | `#E2E8F0` | `rgb(226, 232, 240)` | `hsl(214, 32%, 91%)` | Light mode card borders, divider rules, inputs |
| `text-dark` | `#06141B` | `rgb(6, 20, 27)` | `hsl(200, 64%, 6%)` | Light mode primary headings & body text |

---

### 1.2 Semantic Status & Indicator Colors

| Status | Mode | Background | Border | Text / Icon |
| :--- | :--- | :--- | :--- | :--- |
| **Success / Connected** | Light | `#ECFDF5` (emerald-50) | `#A7F3D0` (emerald-200) | `#047857` (emerald-700) |
| | Dark | `rgba(6, 78, 59, 0.4)` | `rgba(6, 95, 70, 0.6)` | `#34D399` (emerald-400) |
| **Error / Delivery Risk**| Light | `#FFF1F2` (rose-50) | `#FECDD3` (rose-200) | `#BE123C` (rose-700) |
| | Dark | `rgba(136, 19, 55, 0.4)` | `rgba(159, 18, 57, 0.5)` | `#FB7185` (rose-400) |
| **Warning / Queued** | Light | `#FFFBEB` (amber-50) | `#FDE68A` (amber-200) | `#B45309` (amber-700) |
| | Dark | `rgba(120, 53, 15, 0.4)` | `rgba(146, 64, 14, 0.6)` | `#FBBF24` (amber-400) |
| **Info / Integration** | Light | `#F0F9FF` (sky-50) | `#BAE6FD` (sky-200) | `#0369A1` (sky-700) |
| | Dark | `rgba(12, 74, 110, 0.4)`| `rgba(3, 105, 161, 0.6)`| `#38BDF8` (sky-400) |

---

## 2. Dual-Mode UI Token Mapping

Every UI component maps to predefined semantic tokens. Ad-hoc colors outside this specification are strictly disallowed.

| UI Element | Light Mode | Dark Mode | Mobile (React Native / iOS / Android) |
| :--- | :--- | :--- | :--- |
| **Screen Background** | `#F8FAFC` | `#06141B` | `SafeAreaView` / `Scaffold` background |
| **Navigation / Sidebar**| `#FFFFFF` (border: `#E2E8F0`)| `#11212D` (border: `#253745`)| Bottom Navigation Bar / Drawer |
| **Card / Tile Surface** | `#FFFFFF` (border: `#E2E8F0`)| `#11212D` (border: `#253745`)| `Card` / `SurfaceView` |
| **Elevated Hover/Active**| `#F1F5F9` | `#162736` | `pressedState` overlay |
| **Primary Button** | `#253745` (text: `#FFFFFF`)| `#253745` (border: `#4A5C6A`)| Accent fill with 12px radius |
| **Secondary Button** | `#FFFFFF` (border: `#E2E8F0`)| `#162736` (border: `#253745`)| Outlined pill button |
| **Form Input Surface** | `#FFFFFF` (border: `#E2E8F0`)| `#162736` (border: `#253745`)| Text input container |
| **Active Focus Ring** | `rgba(74, 92, 106, 0.2)` | `rgba(155, 168, 171, 0.25)`| Accent highlight border |
| **Divider / Separator**| `#E2E8F0` | `#253745` | 1px horizontal / vertical separator |
| **Primary Heading** | `#06141B` | `#F1F5F9` | `HeadlineLarge` / `Title1` |
| **Body Text** | `#1E293B` | `#CCD0CF` | `BodyMedium` / `Body` |
| **Muted Metadata** | `#4A5C6A` | `#9BA8AB` | `LabelSmall` / `Caption` |
| **Modal Backdrop** | `rgba(6, 20, 27, 0.4)` | `rgba(6, 20, 27, 0.7)` | Scrim overlay + blur |

---

## 3. Typography Hierarchy

The typography uses clean, modern sans-serif fonts: **Inter** (Web) and **San Francisco** / **Roboto** (Mobile).

| Token | Size (px) | Size (rem) | Line Height | Tracking | Weight | Example Usage |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `text-xs` | 12px | 0.75rem | 16px (1.33) | `+0.01em` | 500 / 600 | Badges, status pills, timestamps |
| `text-sm` | 14px | 0.875rem | 20px (1.42) | `0em` | 400 / 500 | Body text, input labels, nav links |
| `text-base` | 16px | 1.00rem | 24px (1.50) | `0em` | 400 / 500 | Card descriptions, modal body |
| `text-lg` | 18px | 1.125rem | 28px (1.55) | `-0.01em` | 600 | Section headers, card titles |
| `text-xl` | 20px | 1.25rem | 28px (1.40) | `-0.015em`| 600 / 700 | Subsection highlights, drawer titles |
| `text-2xl` | 24px | 1.50rem | 32px (1.33) | `-0.02em` | 700 | Screen headers, metric numbers |
| `text-3xl` | 30px | 1.875rem | 36px (1.20) | `-0.025em`| 700 / 800 | Primary page title, KPIs |
| `text-4xl` | 36px | 2.25rem | 40px (1.11) | `-0.03em` | 800 | Hero headlines (Auth, marketing) |
| `text-5xl` | 48px | 3.00rem | 52px (1.08) | `-0.035em`| 800 | Display hero statements |

### Font Weight Conventions
- `Regular (400)`: Paragraph text, detailed descriptions, markdown content.
- `Medium (500)`: Interactive links, table cells, secondary buttons, subheadings.
- `Semibold (600)`: Primary buttons, card headers, active navigation items, badges.
- `Bold (700)`: Screen titles, metric figures, modal headings.
- `Extrabold (800)`: Display headlines, hero banners.

---

## 4. Border Radius System

Corner rounding is systematically applied based on component scale and elevation:

| Radius Token | Value | Applied Components | Mobile Equivalent |
| :--- | :--- | :--- | :--- |
| `rounded-md` | 6px | Checkboxes, tooltips, small chip elements | 6dp |
| `rounded-lg` | 8px | Dropdown menu items, table rows, inner form widgets | 8dp |
| `rounded-xl` | 12px | Action buttons, form inputs, metric stat boxes, notification toasts | 12dp |
| `rounded-2xl` | 16px | Dashboard cards, dossiers, modals, drawers, sidebar logos | 16dp |
| `rounded-3xl` | 24px | Hero banners, floating action surfaces | 24dp |
| `rounded-full`| 9999px | Status badges, pills, avatar circles, switch toggles | Continuous capsule |

> **Mobile Rule**: When designing for iOS, use continuous / squircle corner rounding matching `12` (buttons) and `16` (cards). On Android, map to Material 3 `Shape.medium` (12dp) and `Shape.large` (16dp).

---

## 5. Spacing & Layout Tokens

Spacing follows a strict 4-point (4px) scale:

| Token | Pixels | Common Application |
| :--- | :--- | :--- |
| `space-1` | 4px | Micro gaps, badge inner padding, border padding |
| `space-1.5` | 6px | Dropdown items vertical gap (prevents edge overlapping) |
| `space-2` | 8px | Button icons gap, compact element spacing |
| `space-3` | 12px | Grid gap for compact chips, list item spacing |
| `space-4` | 16px | Standard card inner padding (mobile), card element stack |
| `space-5` | 20px | Standard card inner padding (desktop), header spacing |
| `space-6` | 24px | Section margin, modal container padding |
| `space-8` | 32px | Page grid gap, layout row margin |
| `space-10` | 40px | Major page section separation |
| `space-12` | 48px | Screen top/bottom padding |

---

## 6. Official Brand Logos

The DeepClient identity features two dedicated high-resolution, vector-cropped PNG marks with transparent backgrounds.

### 6.1 Light Mode Logo
- **File**: `/public/DeepClient-light.png`
- **Background**: 100% Transparent
- **"Deep"**: Deep Ink `#06141B`
- **"Client"**: Executive Steel Slate `#253745` / `#254B69`
- **"D" Mark**: 3D folded ribbon shaded from `#06141B` through `#162736` and `#324B5F` to `#CCD0CF`
- **Application**: Rendered when theme is `light` (Tailwind: `dark:hidden`)

### 6.2 Dark Mode Logo
- **File**: `/public/DeepClient-dark.png`
- **Background**: 100% Transparent (seamless on `#11212D`)
- **"Deep"**: Crisp White `#F1F5F9`
- **"Client"**: Luminous Platinum / Slate Cyan `#9BBAD0` / `#CCD0CF`
- **"D" Mark**: Illuminated metallic ribbon shaded from `#162736` through `#4A5C6A` to `#F1F5F9` glow
- **Application**: Rendered when theme is `dark` (Tailwind: `hidden dark:block`)

### 6.3 Implementation Pattern
```tsx
// Web (Next.js / Tailwind)
<div className="flex items-center" aria-label="DeepClient">
  <Image
    src="/DeepClient-light.png"
    alt="DeepClient"
    width={380}
    height={98}
    priority
    className="h-8 w-auto dark:hidden"
  />
  <Image
    src="/DeepClient-dark.png"
    alt="DeepClient"
    width={380}
    height={98}
    priority
    className="hidden h-8 w-auto dark:block"
  />
</div>
```

---

## 7. Motion, Transition & Shimmer Specifications

Motion in DeepClient is designed to be **snappy, modern, and silky-smooth**—never slow or sluggish.

### 7.1 Page Transition Specs (Framer Motion)
```ts
export const pageMotion = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
  transition: {
    duration: 0.26,             // Snappy quarter-second duration
    ease: [0.22, 1, 0.36, 1],  // Custom smooth cubic-bezier curve
  },
};
```

### 7.2 Micro-Card Stagger Specs
```ts
export const cardMotion = (index: number = 0) => ({
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  transition: {
    duration: 0.24,
    delay: index * 0.04,        // 40ms stagger per child
    ease: [0.22, 1, 0.36, 1],
  },
});
```

### 7.3 Shimmer Skeleton Animation (CSS)
Instead of static "Loading..." text placeholders, all pages show GPU-accelerated skeleton shimmer cards:

```css
@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* Light Mode Shimmer */
.animate-shimmer {
  background: linear-gradient(
    90deg,
    rgba(226, 232, 240, 0.7) 0%,
    rgba(241, 245, 249, 1) 50%,
    rgba(226, 232, 240, 0.7) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.8s infinite linear;
}

/* Dark Mode Shimmer */
.dark .animate-shimmer {
  background: linear-gradient(
    90deg,
    rgba(22, 39, 54, 0.6) 0%,
    rgba(37, 55, 69, 0.95) 50%,
    rgba(22, 39, 54, 0.6) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.8s infinite linear;
}
```

---

## 8. Mobile App Implementation Guidelines (React Native)

For engineers implementing the React Native / Flutter / native mobile versions of DeepClient, use this mapping:

### 8.1 Color Theme Provider Object
```typescript
export const themes = {
  light: {
    canvas: '#F8FAFC',
    card: '#FFFFFF',
    surface: '#F1F5F9',
    primary: '#253745',
    accent: '#4A5C6A',
    border: '#E2E8F0',
    textPrimary: '#06141B',
    textSecondary: '#334155',
    textMuted: '#64748B',
    successBg: '#ECFDF5',
    successText: '#047857',
    errorBg: '#FFF1F2',
    errorText: '#BE123C',
  },
  dark: {
    canvas: '#06141B',
    card: '#11212D',
    surface: '#162736',
    primary: '#253745',
    accent: '#4A5C6A',
    border: '#253745',
    textPrimary: '#F1F5F9',
    textSecondary: '#CCD0CF',
    textMuted: '#9BA8AB',
    successBg: 'rgba(6, 78, 59, 0.4)',
    successText: '#34D399',
    errorBg: 'rgba(136, 19, 55, 0.4)',
    errorText: '#FB7185',
  },
} as const;
```

### 8.2 Mobile Component Blueprints
- **App Bar / Header**: Height `56dp`, background `card`, 1px bottom border `border`.
- **Card**: Border radius `16dp`, background `card`, border `1dp solid border`, inner padding `16dp`.
- **Primary Button**: Height `48dp`, border radius `12dp`, background `primary`, text `textPrimary` (dark) or `#FFFFFF` (light), font-weight `600`.
- **Text Input**: Height `48dp`, border radius `12dp`, background `surface`, border `1dp solid border`, placeholder `textMuted`.
- **Bottom Tab Navigation**: Height `64dp` (plus safe-area insets), background `card`, active tint `#F1F5F9` (dark) / `#06141B` (light), inactive tint `textMuted`.
