/** @type {import('tailwindcss').Config} */

// Every color resolves to a CSS variable from src/styles/tokens.css, so one class
// works in both themes (`bg-surface`, `text-muted`, `border-line`, `bg-primary/10`).
const v = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

// Legacy palette names (slate, emerald, brand, ...) still appear in older
// components.  They are mapped onto the semantic tokens instead of raw hex values,
// so any remaining usage follows the active theme rather than assuming dark mode.
const ramp = (soft, strong, text = strong) => ({
  50: v(soft), 100: v(soft), 200: v(text), 300: v(text), 400: v(text),
  500: v(strong), 600: v(strong), 700: v(strong), 800: v(soft), 900: v(soft), 950: v(soft),
})
const neutral = {
  50: v('fg'), 100: v('fg'), 150: v('line-muted'), 200: v('fg'), 300: v('muted'), 400: v('muted'),
  500: v('subtle'), 600: v('subtle'), 700: v('line-strong'), 800: v('line'), 850: v('surface-muted'),
  900: v('surface'), 950: v('bg'),
}

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)'],
      },
      // A deliberately short type scale (px / line-height).
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px' }],
        xs: ['12px', { lineHeight: '16px' }],
        sm: ['13px', { lineHeight: '20px' }],
        base: ['14px', { lineHeight: '22px' }],
        md: ['15px', { lineHeight: '24px' }],
        lg: ['16px', { lineHeight: '24px' }],
        xl: ['18px', { lineHeight: '26px' }],
        '2xl': ['22px', { lineHeight: '30px', letterSpacing: '-0.01em' }],
        '3xl': ['28px', { lineHeight: '36px', letterSpacing: '-0.015em' }],
        '4xl': ['36px', { lineHeight: '44px', letterSpacing: '-0.02em' }],
        '5xl': ['44px', { lineHeight: '52px', letterSpacing: '-0.02em' }],
        '6xl': ['56px', { lineHeight: '62px', letterSpacing: '-0.025em' }],
      },
      colors: {
        bg: v('bg'),
        surface: v('surface'),
        'surface-muted': v('surface-muted'),
        elevated: v('elevated'),
        sunken: v('sunken'),
        line: v('line'),
        'line-muted': v('line-muted'),
        'line-strong': v('line-strong'),
        fg: v('fg'),
        muted: v('muted'),
        subtle: v('subtle'),
        ink: v('ink'),
        primary: {
          DEFAULT: v('primary'),
          hover: v('primary-hover'),
          text: v('primary-text'),
          soft: v('primary-soft'),
        },
        'on-primary': v('on-primary'),
        success: { DEFAULT: v('success'), soft: v('success-soft') },
        warning: { DEFAULT: v('warning'), soft: v('warning-soft') },
        danger: { DEFAULT: v('danger'), soft: v('danger-soft') },
        info: { DEFAULT: v('info'), soft: v('info-soft') },
        focus: v('focus'),
        chart: {
          1: v('chart-1'), 2: v('chart-2'), 3: v('chart-3'), 4: v('chart-4'), 5: v('chart-5'), 6: v('chart-6'),
        },

        // ── Legacy names → semantic tokens ───────────────────────────────
        white: v('ink'),
        slate: neutral,
        gray: neutral,
        zinc: neutral,
        brand: ramp('primary-soft', 'primary', 'primary-text'),
        indigo: ramp('primary-soft', 'primary', 'primary-text'),
        violet: ramp('primary-soft', 'primary', 'primary-text'),
        purple: ramp('primary-soft', 'primary', 'primary-text'),
        blue: ramp('info-soft', 'info'),
        sky: ramp('info-soft', 'info'),
        cyan: ramp('info-soft', 'info'),
        teal: ramp('success-soft', 'success'),
        emerald: ramp('success-soft', 'success'),
        green: ramp('success-soft', 'success'),
        amber: ramp('warning-soft', 'warning'),
        yellow: ramp('warning-soft', 'warning'),
        orange: ramp('warning-soft', 'warning'),
        rose: ramp('danger-soft', 'danger'),
        red: ramp('danger-soft', 'danger'),
        pink: ramp('danger-soft', 'danger'),
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        DEFAULT: 'var(--radius-control)',
        md: 'var(--radius-control)',
        lg: 'var(--radius-card)',
        xl: 'var(--radius-card)',
        '2xl': 'var(--radius-dialog)',
        '3xl': 'var(--radius-dialog)',
      },
      boxShadow: {
        sm: 'none',
        DEFAULT: 'none',
        md: 'var(--shadow-float)',
        lg: 'var(--shadow-float)',
        xl: 'var(--shadow-float)',
        '2xl': 'var(--shadow-dialog)',
        float: 'var(--shadow-float)',
        dialog: 'var(--shadow-dialog)',
      },
      spacing: {
        4.5: '1.125rem',
      },
      transitionDuration: {
        fast: 'var(--motion-fast)',
        base: 'var(--motion-base)',
      },
      animation: {
        'fade-in': 'fadeIn var(--motion-base) var(--ease-out)',
        'slide-up': 'slideUp var(--motion-base) var(--ease-out)',
        'pop-in': 'popIn var(--motion-base) var(--ease-out)',
        shimmer: 'shimmer 1.4s linear infinite',
        caret: 'caret 1s steps(1) infinite',
      },
      keyframes: {
        fadeIn: { from: { opacity: 0 }, to: { opacity: 1 } },
        slideUp: { from: { opacity: 0, transform: 'translateY(4px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
        popIn: { from: { opacity: 0, transform: 'scale(0.98)' }, to: { opacity: 1, transform: 'scale(1)' } },
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
        caret: { '0%, 100%': { opacity: 1 }, '50%': { opacity: 0 } },
      },
    },
  },
  plugins: [],
}
