import { useEffect, useState } from 'react';
import * as api from '../lib/api';

interface Props {
  organizationId: string | undefined;
  onClose: () => void;
}

function formatPrice(cents: number, currency: string): string {
  const fmt = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency || 'USD',
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  });
  return fmt.format((cents || 0) / 100);
}

export default function BillingModal({ organizationId, onClose }: Props) {
  const [plans, setPlans] = useState<api.Plan[]>([]);
  const [sub, setSub] = useState<api.Subscription | null>(null);
  const [usage, setUsage] = useState<api.UsageItem[]>([]);
  const [config, setConfig] = useState<{ enabled: boolean } | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .listPlans()
      .then((r) => setPlans(r.plans ?? []))
      .catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load plans'));
    api
      .getBillingConfig()
      .then((c) => setConfig(c))
      .catch(() => setConfig(null));
    if (organizationId) {
      api
        .getSubscription(organizationId)
        .then((r) => setSub(r))
        .catch(() => setSub(null));
    }
    api
      .getUsage()
      .then((r) => setUsage(r.items ?? []))
      .catch(() => setUsage([]));
  }, [organizationId]);

  const upgrade = async (plan: api.Plan) => {
    if (!organizationId || busy) return;
    setBusy(true);
    setErr('');
    try {
      const session = await api.createCheckoutSession(organizationId, plan.id);
      if (session.url) {
        window.open(session.url, '_blank', 'noopener,noreferrer');
      } else {
        setErr('Checkout is not available yet.');
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Checkout failed');
    } finally {
      setBusy(false);
    }
  };

  const activePlanName = plans.find((p) => p.id === sub?.plan_id)?.name ?? null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Billing &amp; Plans</h2>
          <button className="modal-close" onClick={onClose} title="Close">
            ✕
          </button>
        </div>

        <div className="modal-body">
          {sub && (
            <div className="sub-banner">
              <div>
                <div className="sub-status-label">Current plan</div>
                <div className="sub-status-value">
                  {activePlanName ?? 'Free'} <span className={`sub-badge ${sub.status}`}>{sub.status}</span>
                </div>
                {sub.current_period_end && (
                  <div className="sub-period">
                    Renews {new Date(sub.current_period_end).toLocaleDateString()}
                  </div>
                )}
              </div>
            </div>
          )}

          {err && <div className="auth-error">{err}</div>}

          <div className="section-title">Choose a plan</div>
          <div className="plans-grid">
            {plans.map((p) => {
              const isCurrent = sub?.plan_id === p.id;
              return (
                <div key={p.id} className={`plan-card${p.is_popular ? ' popular' : ''}`}>
                  <div className="plan-name">{p.display_name ?? p.name}</div>
                  {p.is_popular && <span className="plan-tag">Popular</span>}
                  <div className="plan-price">
                    {formatPrice(p.price, p.currency)}
                    <span className="plan-interval">/{p.interval}</span>
                  </div>
                  {p.description && <div className="plan-desc">{p.description}</div>}
                  {p.features && p.features.length > 0 && (
                    <ul className="plan-features">
                      {p.features.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  )}
                  <button
                    className={`plan-cta${isCurrent ? ' current' : ''}`}
                    disabled={isCurrent || busy || config?.enabled === false}
                    onClick={() => upgrade(p)}
                    title={config?.enabled === false ? 'Billing is not configured on this server' : undefined}
                  >
                    {isCurrent ? 'Current plan' : 'Choose'}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="section-title">Usage</div>
          {usage.length === 0 ? (
            <div className="usage-empty">No usage recorded yet.</div>
          ) : (
            <div className="usage-list">
              {usage.map((u) => (
                <div key={u.type} className="usage-row">
                  <span className="usage-type">{u.type}</span>
                  <span className="usage-value">
                    {u.total_quantity} · {formatPrice(Math.round(u.total_cost * 100), 'USD')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
