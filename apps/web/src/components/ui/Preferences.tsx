import { Moon, Sun } from 'lucide-react'
import { LANGUAGE_CODES, LANGUAGE_NAMES, LOCALES, useI18n } from '../../lib/i18n'
import { useTheme } from '../../lib/theme'
import { cx } from './cx'

/**
 * One-click light/dark toggle. It shows the theme you would switch TO, and an explicit choice replaces
 * "system" (the three-way system/light/dark control lives in Settings).
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { t } = useI18n()
  const { resolved, toggle } = useTheme()
  const toDark = resolved === 'light'
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={toDark ? t('prefs.toDark') : t('prefs.toLight')}
      title={toDark ? t('prefs.toDark') : t('prefs.toLight')}
      className={cx(
        'inline-flex size-8 shrink-0 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-surface-muted hover:text-fg',
        className,
      )}
    >
      {toDark ? <Moon size={16} aria-hidden /> : <Sun size={16} aria-hidden />}
    </button>
  )
}

/** Compact segmented language switcher (RU / ҚАЗ / EN). Each option is announced in its own language. */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n()
  return (
    <div
      role="group"
      aria-label={t('prefs.language')}
      className={cx('inline-flex h-8 items-center gap-0.5 rounded-md bg-surface-muted p-0.5', className)}
    >
      {LOCALES.map((l) => (
        <button
          key={l}
          type="button"
          lang={l}
          aria-pressed={locale === l}
          aria-label={LANGUAGE_NAMES[l]}
          title={LANGUAGE_NAMES[l]}
          onClick={() => setLocale(l)}
          className={cx(
            'h-7 min-w-9 rounded-sm px-2 text-xs font-medium transition-colors',
            locale === l ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg',
          )}
        >
          {LANGUAGE_CODES[l]}
        </button>
      ))}
    </div>
  )
}
