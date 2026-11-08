import { Link } from 'react-router'
import { useI18n } from '../../lib/i18n'
import { cx } from '../ui/cx'
import { Logo } from './Logo'

/** The logo as a link to the app home. Height is set by the caller via `className` (e.g. "h-[18px]"). */
export function BrandLink({ className, to = '/' }: { className?: string; to?: string }) {
  const { t } = useI18n()
  return (
    <Link to={to} aria-label={t('prefs.brandHome')} className="inline-flex rounded-sm">
      <Logo aria-hidden className={cx('h-[18px] w-auto', className)} />
    </Link>
  )
}
