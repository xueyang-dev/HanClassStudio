import { useI18n } from "../i18n";

/** Stable loading surface for deep links and recent-project navigation. */
export function ProjectLoadingSkeleton() {
  const { t } = useI18n();
  return (
    <section className="panel project-loading" role="status" aria-live="polite" aria-label={t("status.loadingProject")}>
      <div className="skeleton-block skeleton-block-heading" aria-hidden="true" />
      <div className="skeleton-block skeleton-block-copy" aria-hidden="true" />
      <div className="skeleton-block skeleton-block-copy short" aria-hidden="true" />
      <div className="skeleton-grid" aria-hidden="true">
        <div className="skeleton-block" />
        <div className="skeleton-block" />
        <div className="skeleton-block" />
        <div className="skeleton-block" />
      </div>
      <span className="sr-only">{t("status.loadingProject")}</span>
    </section>
  );
}
