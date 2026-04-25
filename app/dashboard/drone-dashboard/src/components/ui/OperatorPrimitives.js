import React, { useEffect, useId } from 'react';
import PropTypes from 'prop-types';
import { FaBookOpen, FaExclamationTriangle, FaInfoCircle, FaTimes } from 'react-icons/fa';

import { buildDocsUrl, getRouteDoc } from '../../config/routeDocs';
import '../../styles/OperatorPrimitives.css';

const TONES = ['neutral', 'info', 'success', 'warning', 'danger', 'muted'];
const SIZES = ['sm', 'md', 'lg'];

export function StatusBadge({ tone = 'neutral', icon = null, children, className = '', ...props }) {
  return (
    <span
      {...props}
      className={['operator-status-badge', `operator-status-badge--${tone}`, className].filter(Boolean).join(' ')}
    >
      {icon ? <span className="operator-status-badge__icon" aria-hidden="true">{icon}</span> : null}
      <span className="operator-status-badge__label">{children}</span>
    </span>
  );
}

StatusBadge.propTypes = {
  tone: PropTypes.oneOf(TONES),
  icon: PropTypes.node,
  children: PropTypes.node.isRequired,
  className: PropTypes.string,
};

export function ActionIconButton({
  icon,
  label,
  children = null,
  tone = 'neutral',
  size = 'md',
  active = false,
  className = '',
  type = 'button',
  ...buttonProps
}) {
  return (
    <button
      {...buttonProps}
      type={type}
      aria-label={label}
      aria-pressed={buttonProps['aria-pressed'] ?? (active || undefined)}
      className={[
        'operator-action-icon-button',
        `operator-action-icon-button--${tone}`,
        `operator-action-icon-button--${size}`,
        active ? 'is-active' : '',
        className,
      ].filter(Boolean).join(' ')}
    >
      <span className="operator-action-icon-button__icon" aria-hidden="true">{icon}</span>
      {children ? <span className="operator-action-icon-button__text">{children}</span> : null}
    </button>
  );
}

ActionIconButton.propTypes = {
  icon: PropTypes.node.isRequired,
  label: PropTypes.string.isRequired,
  children: PropTypes.node,
  tone: PropTypes.oneOf(TONES),
  size: PropTypes.oneOf(SIZES),
  active: PropTypes.bool,
  className: PropTypes.string,
  type: PropTypes.oneOf(['button', 'submit', 'reset']),
};

export function OperatorCard({
  as: Component = 'article',
  tone = 'neutral',
  compact = false,
  selected = false,
  className = '',
  children,
  ...props
}) {
  return (
    <Component
      {...props}
      className={[
        'operator-card',
        `operator-card--${tone}`,
        compact ? 'operator-card--compact' : '',
        selected ? 'is-selected' : '',
        className,
      ].filter(Boolean).join(' ')}
    >
      {children}
    </Component>
  );
}

OperatorCard.propTypes = {
  as: PropTypes.elementType,
  tone: PropTypes.oneOf(TONES),
  compact: PropTypes.bool,
  selected: PropTypes.bool,
  className: PropTypes.string,
  children: PropTypes.node.isRequired,
};

export function MetricPill({ label, value, detail = '', icon = null, tone = 'neutral' }) {
  return (
    <OperatorCard as="div" compact tone={tone} className="operator-metric-pill" role="listitem">
      {icon ? <span className="operator-metric-pill__icon" aria-hidden="true">{icon}</span> : null}
      <span className="operator-metric-pill__body">
        <span className="operator-metric-pill__value">{value}</span>
        <span className="operator-metric-pill__label">{label}</span>
        {detail ? <span className="operator-metric-pill__detail">{detail}</span> : null}
      </span>
    </OperatorCard>
  );
}

MetricPill.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.node.isRequired,
  detail: PropTypes.node,
  icon: PropTypes.node,
  tone: PropTypes.oneOf(TONES),
};

export function MetricStrip({ items = [], label = 'Status summary', className = '' }) {
  return (
    <div className={['operator-metric-strip', className].filter(Boolean).join(' ')} role="list" aria-label={label}>
      {items.map((item) => (
        <MetricPill
          key={item.key || item.label}
          label={item.label}
          value={item.value}
          detail={item.detail}
          icon={item.icon}
          tone={item.tone || 'neutral'}
        />
      ))}
    </div>
  );
}

MetricStrip.propTypes = {
  items: PropTypes.arrayOf(PropTypes.shape({
    key: PropTypes.string,
    label: PropTypes.string.isRequired,
    value: PropTypes.node.isRequired,
    detail: PropTypes.node,
    icon: PropTypes.node,
    tone: PropTypes.oneOf(TONES),
  })),
  label: PropTypes.string,
  className: PropTypes.string,
};

export function DocsLink({
  route,
  doc = null,
  repoUrl = '',
  repoWebUrl = '',
  branch = '',
  label = '',
  compact = false,
  className = '',
}) {
  const resolvedDoc = doc || getRouteDoc(route);
  const href = buildDocsUrl(resolvedDoc, { repoUrl, repoWebUrl, branch });

  if (!resolvedDoc || !href) {
    return null;
  }

  const resolvedLabel = label || resolvedDoc.label || 'Guide';

  return (
    <a
      className={['operator-docs-link', compact ? 'operator-docs-link--compact' : '', className].filter(Boolean).join(' ')}
      href={href}
      aria-label={resolvedLabel}
      target={href.startsWith('http') ? '_blank' : undefined}
      rel={href.startsWith('http') ? 'noreferrer' : undefined}
    >
      <FaBookOpen aria-hidden="true" />
      <span>{resolvedLabel}</span>
    </a>
  );
}

DocsLink.propTypes = {
  route: PropTypes.string,
  doc: PropTypes.shape({
    label: PropTypes.string,
    docPath: PropTypes.string.isRequired,
  }),
  repoUrl: PropTypes.string,
  repoWebUrl: PropTypes.string,
  branch: PropTypes.string,
  label: PropTypes.string,
  compact: PropTypes.bool,
  className: PropTypes.string,
};

export function PageShell({
  eyebrow = '',
  title,
  subtitle = '',
  icon = null,
  docsRoute = '',
  docsOptions = {},
  actions = null,
  status = null,
  children,
  className = '',
}) {
  return (
    <main className={['operator-page-shell', className].filter(Boolean).join(' ')}>
      <header className="operator-page-shell__header">
        <div className="operator-page-shell__identity">
          {icon ? <span className="operator-page-shell__icon" aria-hidden="true">{icon}</span> : null}
          <div className="operator-page-shell__copy">
            {eyebrow ? <span className="operator-page-shell__eyebrow">{eyebrow}</span> : null}
            <h1>{title}</h1>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </div>
        <div className="operator-page-shell__tools">
          {status}
          {docsRoute ? <DocsLink route={docsRoute} compact {...docsOptions} /> : null}
          {actions}
        </div>
      </header>
      {children}
    </main>
  );
}

PageShell.propTypes = {
  eyebrow: PropTypes.string,
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.string,
  icon: PropTypes.node,
  docsRoute: PropTypes.string,
  docsOptions: PropTypes.object,
  actions: PropTypes.node,
  status: PropTypes.node,
  children: PropTypes.node.isRequired,
  className: PropTypes.string,
};

export function OperatorNotice({
  tone = 'info',
  title,
  children = null,
  icon = null,
  action = null,
  className = '',
  role = tone === 'danger' ? 'alert' : 'status',
}) {
  const defaultIcon = tone === 'warning' || tone === 'danger' ? <FaExclamationTriangle /> : <FaInfoCircle />;
  return (
    <div
      className={['operator-notice', `operator-notice--${tone}`, className].filter(Boolean).join(' ')}
      role={role}
    >
      <span className="operator-notice__icon" aria-hidden="true">{icon || defaultIcon}</span>
      <div className="operator-notice__body">
        <strong>{title}</strong>
        {children ? <div className="operator-notice__detail">{children}</div> : null}
      </div>
      {action ? <div className="operator-notice__action">{action}</div> : null}
    </div>
  );
}

OperatorNotice.propTypes = {
  tone: PropTypes.oneOf(['info', 'success', 'warning', 'danger', 'neutral']),
  title: PropTypes.string.isRequired,
  children: PropTypes.node,
  icon: PropTypes.node,
  action: PropTypes.node,
  className: PropTypes.string,
  role: PropTypes.string,
};

export function EmptyState({ icon = null, title, detail = '', action = null, className = '' }) {
  return (
    <OperatorCard as="section" compact tone="muted" className={['operator-empty-state', className].filter(Boolean).join(' ')}>
      {icon ? <span className="operator-empty-state__icon" aria-hidden="true">{icon}</span> : null}
      <div className="operator-empty-state__body">
        <h2>{title}</h2>
        {detail ? <p>{detail}</p> : null}
      </div>
      {action ? <div className="operator-empty-state__action">{action}</div> : null}
    </OperatorCard>
  );
}

EmptyState.propTypes = {
  icon: PropTypes.node,
  title: PropTypes.string.isRequired,
  detail: PropTypes.node,
  action: PropTypes.node,
  className: PropTypes.string,
};

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'neutral',
  busy = false,
  onConfirm,
  onCancel,
}) {
  const titleId = useId();

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onCancel();
      }
    };

    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onCancel, open]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="operator-confirm-dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <section
        className={`operator-confirm-dialog__panel operator-confirm-dialog__panel--${tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="operator-confirm-dialog__header">
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            className="operator-confirm-dialog__close"
            onClick={onCancel}
            aria-label="Close confirmation dialog"
          >
            <FaTimes aria-hidden="true" />
          </button>
        </header>
        <div className="operator-confirm-dialog__message">{message}</div>
        <footer className="operator-confirm-dialog__actions">
          <button type="button" className="operator-button operator-button--ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`operator-button operator-button--${tone === 'danger' ? 'danger' : 'primary'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Working...' : confirmLabel}
          </button>
        </footer>
      </section>
    </div>
  );
}

ConfirmDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string.isRequired,
  message: PropTypes.node.isRequired,
  confirmLabel: PropTypes.string,
  cancelLabel: PropTypes.string,
  tone: PropTypes.oneOf(['neutral', 'danger']),
  busy: PropTypes.bool,
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};
