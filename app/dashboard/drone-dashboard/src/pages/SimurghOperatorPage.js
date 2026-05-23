import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FaBan,
  FaBookOpen,
  FaCheckCircle,
  FaClock,
  FaFileAlt,
  FaHistory,
  FaLock,
  FaNetworkWired,
  FaPaperPlane,
  FaRobot,
  FaServer,
  FaShieldAlt,
  FaSyncAlt,
  FaTools,
  FaUserShield,
} from 'react-icons/fa';

import {
  ActionIconButton,
  EmptyState,
  MetricStrip,
  OperatorNotice,
  PageActionBar,
  PageShell,
  StatusBadge,
} from '../components/ui';
import {
  createSimurghAssistantTurnResponse,
  getSimurghAssistantTurnsResponse,
  getSimurghAuditResponse,
  getSimurghContextResponse,
  getSimurghPolicyResponse,
  getSimurghSessionsResponse,
  getSimurghStatusResponse,
  getSimurghToolsResponse,
} from '../services/gcsApiService';
import '../styles/SimurghOperatorPage.css';

const VIEW_TABS = [
  { id: 'overview', label: 'Overview', icon: FaShieldAlt },
  { id: 'assistant', label: 'Assistant', icon: FaRobot },
  { id: 'tools', label: 'Tools', icon: FaTools },
  { id: 'context', label: 'Context', icon: FaBookOpen },
  { id: 'audit', label: 'Audit', icon: FaHistory },
];

const INITIAL_DATA = Object.freeze({
  status: null,
  policy: null,
  tools: [],
  contextResources: [],
  sessions: [],
  auditEvents: [],
});

const DASHBOARD_ASSISTANT_ACTOR = 'dashboard';

const EXPOSURE_TONES = {
  allow: 'success',
  guarded: 'warning',
  exclude: 'danger',
};

const RISK_TONES = {
  observe: 'success',
  sensitive_observe: 'warning',
  plan: 'info',
  simulate: 'warning',
  operate: 'danger',
  admin: 'danger',
  destructive: 'danger',
};

function boolLabel(value, on = 'Enabled', off = 'Disabled') {
  return value ? on : off;
}

function formatToken(value) {
  return String(value || 'unknown').replace(/_/g, ' ');
}

function formatCount(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '0';
}

function formatDateTime(value) {
  if (!value) {
    return 'n/a';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function shortHash(value) {
  if (!value) {
    return 'n/a';
  }
  return String(value).slice(0, 12);
}

function normalizedAssistantProvider(provider) {
  return String(provider || 'mock').trim().toLowerCase() || 'mock';
}

function routeLabel(tool) {
  const method = tool?.route?.method || 'n/a';
  const path = tool?.route?.path || 'unbound';
  return `${method} ${path}`;
}

function errorMessage(error) {
  return error?.response?.data?.detail || error?.message || 'Unable to load Simurgh metadata.';
}

function sessionIdForTurn(turn) {
  return turn?.session?.id || turn?.session_id || '';
}

function isActiveDashboardAssistantSession(session) {
  return Boolean(
    session
    && !session.closed
    && session.metadata?.channel === 'assistant'
    && session.metadata?.source === 'simurgh-dashboard'
  );
}

function activeDefaultDashboardAssistantSessionId(sessions = []) {
  const activeSessions = sessions.filter((session) => (
    session.actor === DASHBOARD_ASSISTANT_ACTOR && isActiveDashboardAssistantSession(session)
  ));
  return activeSessions.length ? activeSessions[activeSessions.length - 1].id : '';
}

function hasActiveDashboardAssistantSession(sessions = [], sessionId = '') {
  return Boolean(sessionId && sessions.some((session) => session.id === sessionId && isActiveDashboardAssistantSession(session)));
}

function PreservedText({ children }) {
  return <p className="simurgh-page__assistant-text">{children}</p>;
}

function BadgeList({ values = [], tone = 'muted', empty = 'none' }) {
  if (!values.length) {
    return <span className="simurgh-page__muted">{empty}</span>;
  }
  return (
    <span className="simurgh-page__badge-list">
      {values.map((value) => (
        <StatusBadge key={value} tone={tone}>{formatToken(value)}</StatusBadge>
      ))}
    </span>
  );
}

function DetailGrid({ items = [] }) {
  return (
    <dl className="simurgh-page__detail-grid">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PolicyOverview({ policy, status }) {
  if (!policy) {
    return (
      <EmptyState
        icon={<FaShieldAlt />}
        title="Policy unavailable"
        detail="The policy endpoint did not return metadata."
      />
    );
  }

  const items = [
    {
      label: 'Agent',
      value: (
        <StatusBadge tone={policy.agent_enabled ? 'success' : 'muted'}>
          {boolLabel(policy.agent_enabled)}
        </StatusBadge>
      ),
    },
    {
      label: 'MCP',
      value: (
        <StatusBadge tone={policy.mcp_enabled ? 'success' : 'muted'}>
          {boolLabel(policy.mcp_enabled)}
        </StatusBadge>
      ),
    },
    {
      label: 'Drone API',
      value: (
        <StatusBadge tone={policy.allow_drone_api_exposure ? 'danger' : 'success'}>
          {policy.allow_drone_api_exposure ? 'Exposed' : 'GCS only'}
        </StatusBadge>
      ),
    },
    {
      label: 'Circuit breaker',
      value: (
        <StatusBadge tone={policy.action_circuit_breaker_enabled ? 'success' : 'danger'}>
          {policy.action_circuit_breaker_enabled ? 'No actions' : 'Actions possible'}
        </StatusBadge>
      ),
    },
    {
      label: 'Always confirm',
      value: (
        <StatusBadge tone={policy.always_confirm_before_action ? 'success' : 'warning'}>
          {policy.always_confirm_before_action ? 'Enabled' : 'Policy driven'}
        </StatusBadge>
      ),
    },
    {
      label: 'Real-command guard',
      value: (
        <StatusBadge tone={policy.real_commands_enabled ? 'danger' : 'success'}>
          {policy.real_commands_enabled ? 'Enabled' : 'Blocked'}
        </StatusBadge>
      ),
    },
    {
      label: 'Unknown tools',
      value: <StatusBadge tone={policy.unknown_tool_policy === 'deny' ? 'success' : 'warning'}>{policy.unknown_tool_policy}</StatusBadge>,
    },
    {
      label: 'Approval TTL',
      value: `${policy.approval_ttl_seconds}s`,
    },
    {
      label: 'Approval risks',
      value: <BadgeList values={policy.approval_required_risks || []} tone="warning" />,
    },
    {
      label: 'Registry version',
      value: status?.tool_registry_version ? `v${status.tool_registry_version}` : `v${policy.version}`,
    },
  ];

  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-policy-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-policy-heading">Policy Posture</h2>
      </div>
      <div className="simurgh-page__fact-grid">
        {items.map((item) => (
          <article className="simurgh-page__fact" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </article>
        ))}
      </div>
    </section>
  );
}

function RuntimeModes({ policy }) {
  const modes = Object.entries(policy?.runtime_modes || {});
  if (!modes.length) {
    return null;
  }

  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-modes-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-modes-heading">Runtime Modes</h2>
      </div>
      <div className="simurgh-page__mode-grid">
        {modes.map(([mode, modePolicy]) => (
          <article className="simurgh-page__mode-card" key={mode}>
            <header>
              <h3>{formatToken(mode)}</h3>
              {mode === policy.mode ? <StatusBadge tone="info">Active</StatusBadge> : null}
            </header>
            <DetailGrid
              items={[
                { label: 'Allowed', value: <BadgeList values={modePolicy.allowed_risks || []} tone="success" /> },
                { label: 'Approval', value: <BadgeList values={modePolicy.approval_required_risks || []} tone="warning" /> },
                { label: 'Denied', value: <BadgeList values={modePolicy.denied_risks || []} tone="danger" /> },
              ]}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

function ArtifactPaths({ status }) {
  if (!status) {
    return null;
  }
  const paths = [
    { label: 'Policy', value: status.policy_path },
    { label: 'Tools', value: status.tool_registry_path },
    { label: 'Context', value: status.context_index_path },
  ];
  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-artifacts-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-artifacts-heading">Artifacts</h2>
      </div>
      <div className="simurgh-page__artifact-list">
        {paths.map((item) => (
          <article className="simurgh-page__artifact" key={item.label}>
            <FaFileAlt aria-hidden="true" />
            <span>{item.label}</span>
            <code>{item.value}</code>
          </article>
        ))}
      </div>
    </section>
  );
}

function ToolsView({ tools }) {
  if (!tools.length) {
    return (
      <EmptyState
        icon={<FaTools />}
        title="No tools registered"
        detail="The registry endpoint returned an empty tool list."
      />
    );
  }

  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-tools-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-tools-heading">Tool Registry</h2>
      </div>
      <div className="simurgh-page__tool-grid">
        {tools.map((tool) => (
          <article className="simurgh-page__tool-card" key={tool.id}>
            <header>
              <div>
                <h3>{tool.title}</h3>
                <code>{tool.id}</code>
              </div>
              <span className="simurgh-page__tool-badges">
                <StatusBadge tone={EXPOSURE_TONES[tool.exposure] || 'neutral'}>{formatToken(tool.exposure)}</StatusBadge>
                <StatusBadge tone={RISK_TONES[tool.risk_class] || 'neutral'}>{formatToken(tool.risk_class)}</StatusBadge>
              </span>
            </header>
            <p>{tool.description}</p>
            <DetailGrid
              items={[
                { label: 'Route', value: <code>{routeLabel(tool)}</code> },
                { label: 'Boundary', value: tool.boundary },
                { label: 'Role', value: tool.required_role },
                { label: 'Read only', value: boolLabel(tool.read_only, 'yes', 'no') },
                { label: 'Modes', value: <BadgeList values={tool.runtime_modes || []} tone="info" /> },
                { label: 'Sensitivity', value: <BadgeList values={tool.sensitivity || []} tone="warning" /> },
              ]}
            />
            {tool.safety_notes?.length ? (
              <ul className="simurgh-page__note-list">
                {tool.safety_notes.slice(0, 2).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function ContextView({ resources }) {
  if (!resources.length) {
    return (
      <EmptyState
        icon={<FaBookOpen />}
        title="No context resources"
        detail="The context index endpoint returned an empty resource list."
      />
    );
  }

  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-context-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-context-heading">Context Index</h2>
      </div>
      <div className="simurgh-page__resource-grid">
        {resources.map((resource) => (
          <article className="simurgh-page__resource-card" key={resource.id}>
            <header>
              <div>
                <h3>{resource.title}</h3>
                <code>{resource.id}</code>
              </div>
              <StatusBadge tone={resource.sensitivity === 'public' ? 'success' : 'warning'}>
                {resource.sensitivity}
              </StatusBadge>
            </header>
            <p>{resource.summary}</p>
            <DetailGrid
              items={[
                { label: 'Audience', value: resource.audience },
                { label: 'Type', value: resource.mime_type },
                { label: 'Path', value: <code>{resource.path}</code> },
                { label: 'Hash', value: <code>{shortHash(resource.content_hash)}</code> },
                { label: 'Tags', value: <BadgeList values={resource.tags || []} tone="info" /> },
              ]}
            />
          </article>
        ))}
      </div>
    </section>
  );
}

function SessionList({ sessions }) {
  if (!sessions.length) {
    return (
      <EmptyState
        icon={<FaUserShield />}
        title="No sessions"
        detail="No Simurgh agent sessions are active or recorded."
      />
    );
  }

  return (
    <div className="simurgh-page__record-list">
      {sessions.map((session) => (
        <article className="simurgh-page__record" key={session.id}>
          <header>
            <h3>{session.actor}</h3>
            <StatusBadge tone={session.closed ? 'muted' : 'success'}>{session.closed ? 'Closed' : 'Active'}</StatusBadge>
          </header>
          <DetailGrid
            items={[
              { label: 'Session', value: <code>{session.id}</code> },
              { label: 'Mode', value: formatToken(session.mode) },
              { label: 'Created', value: formatDateTime(session.created_at) },
              { label: 'Expires', value: formatDateTime(session.expires_at) },
            ]}
          />
        </article>
      ))}
    </div>
  );
}

function AuditList({ events }) {
  if (!events.length) {
    return (
      <EmptyState
        icon={<FaHistory />}
        title="No audit events"
        detail="The Simurgh audit sink has not recorded events in this process."
      />
    );
  }

  return (
    <div className="simurgh-page__record-list">
      {events.map((event) => (
        <article className="simurgh-page__record" key={event.id}>
          <header>
            <h3>{formatToken(event.event_type)}</h3>
            {event.decision ? <StatusBadge tone={event.decision === 'allow' ? 'success' : 'warning'}>{event.decision}</StatusBadge> : null}
          </header>
          <DetailGrid
            items={[
              { label: 'Event', value: <code>{event.id}</code> },
              { label: 'Actor', value: event.actor || 'n/a' },
              { label: 'Tool', value: event.tool_id || 'n/a' },
              { label: 'Created', value: formatDateTime(event.created_at) },
              { label: 'Payload', value: <code>{shortHash(event.payload_hash)}</code> },
            ]}
          />
        </article>
      ))}
    </div>
  );
}

function AuditView({ sessions, auditEvents }) {
  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-audit-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-audit-heading">Sessions And Audit</h2>
      </div>
      <div className="simurgh-page__audit-grid">
        <div>
          <h3>Sessions</h3>
          <SessionList sessions={sessions} />
        </div>
        <div>
          <h3>Events</h3>
          <AuditList events={auditEvents} />
        </div>
      </div>
    </section>
  );
}

function AssistantTurnList({ turns }) {
  if (!turns.length) {
    return (
      <EmptyState
        icon={<FaRobot />}
        title="No assistant turns"
        detail="No turns have been created from this dashboard session."
      />
    );
  }

  return (
    <div className="simurgh-page__assistant-turn-list">
      {turns.map((turn) => {
        const blockedIntents = turn.blocked_intents || [];
        const contextIds = (turn.context_resources || []).map((resource) => resource.id || resource);
        return (
          <article className="simurgh-page__assistant-turn" key={turn.id}>
            <header>
              <div>
                <h3>{formatToken(turn.provider || 'assistant')}</h3>
                <code>{turn.id}</code>
              </div>
              <StatusBadge tone={blockedIntents.length ? 'warning' : 'success'}>
                {blockedIntents.length ? 'Guarded' : 'No execution'}
              </StatusBadge>
            </header>
            {turn.message ? (
              <div className="simurgh-page__assistant-message">
                <span>Operator</span>
                <PreservedText>{turn.message}</PreservedText>
              </div>
            ) : null}
            <PreservedText>{turn.content}</PreservedText>
            <DetailGrid
              items={[
                { label: 'Session', value: <code>{sessionIdForTurn(turn) || 'n/a'}</code> },
                { label: 'Audit', value: <code>{turn.audit_event_id || 'n/a'}</code> },
                { label: 'Created', value: formatDateTime(turn.created_at) },
                { label: 'Prompt', value: turn.message_hash ? <code>{shortHash(turn.message_hash)}</code> : 'n/a' },
                { label: 'Context', value: <BadgeList values={contextIds} tone="info" empty="default" /> },
                { label: 'Blocked intents', value: <BadgeList values={blockedIntents} tone="warning" /> },
              ]}
            />
            {turn.safety_notes?.length ? (
              <ul className="simurgh-page__note-list">
                {turn.safety_notes.slice(0, 3).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function AssistantView({
  enabled,
  resources,
  message,
  selectedContextIds,
  turns,
  submitting,
  error,
  historyLoading,
  historyError,
  activeSessionId,
  provider,
  externalProviderAuthRequired,
  onMessageChange,
  onToggleContext,
  onNewConversation,
  onSubmit,
}) {
  const selectableResources = resources.filter((resource) => resource.sensitivity === 'public');
  const canSubmit = enabled && !submitting && message.trim().length > 0;
  const assistantProvider = normalizedAssistantProvider(provider);
  const usesExternalProvider = assistantProvider !== 'mock';

  return (
    <section className="simurgh-page__section" aria-labelledby="simurgh-assistant-heading">
      <div className="simurgh-page__section-heading">
        <h2 id="simurgh-assistant-heading">Assistant Shell</h2>
        <StatusBadge tone={enabled ? 'success' : 'muted'}>{enabled ? 'Enabled' : 'Disabled'}</StatusBadge>
      </div>

      {!enabled ? (
        <OperatorNotice tone="info" title="Assistant runtime disabled">
          Assistant turns are unavailable while the Simurgh agent runtime is disabled.
        </OperatorNotice>
      ) : null}

      {error ? (
        <OperatorNotice tone="danger" title="Assistant turn failed" role="alert">
          {error}
        </OperatorNotice>
      ) : null}

      {historyError ? (
        <OperatorNotice tone="warning" title="Assistant history unavailable">
          {historyError}
        </OperatorNotice>
      ) : null}

      {enabled ? (
        <OperatorNotice tone="info" title="Advisory only">
          {usesExternalProvider
            ? 'Assistant replies do not execute tools, call MCP tools, or submit drone commands. Operator text may be sent to the configured OpenAI provider; do not enter raw field artifacts, customer identifiers, coordinates, peer IDs, screenshots, logs, or secrets.'
            : 'Assistant replies stay local in mock mode and do not execute tools, call MCP tools, submit drone commands, or contact a model provider.'}
          {externalProviderAuthRequired
            ? ' External providers require an authenticated MDS operator session or bearer token.'
            : ''}
        </OperatorNotice>
      ) : null}

      <form className="simurgh-page__assistant-form" onSubmit={onSubmit}>
        <label htmlFor="simurgh-assistant-message">Operator message</label>
        <span className="simurgh-page__badge-list">
          <StatusBadge tone="success">No commands executed</StatusBadge>
          <StatusBadge tone={usesExternalProvider ? 'warning' : 'success'}>
            {usesExternalProvider ? 'OpenAI provider' : 'Mock local'}
          </StatusBadge>
        </span>
        <textarea
          id="simurgh-assistant-message"
          value={message}
          onChange={(event) => onMessageChange(event.target.value)}
          disabled={!enabled || submitting}
          rows={5}
        />
        <div className="simurgh-page__assistant-actions">
          <span className="simurgh-page__muted">
            {activeSessionId ? `Session ${activeSessionId.slice(0, 18)}` : 'New advisory session'} · {formatCount(message.length)} chars
          </span>
          <ActionIconButton
            icon={<FaSyncAlt />}
            label="Start new assistant session"
            onClick={onNewConversation}
            disabled={!enabled || submitting || !activeSessionId}
          >
            New Session
          </ActionIconButton>
          <ActionIconButton
            type="submit"
            icon={<FaPaperPlane />}
            label="Generate advisory reply"
            disabled={!canSubmit}
          >
            {submitting ? 'Generating' : 'Generate advisory reply'}
          </ActionIconButton>
        </div>
      </form>

      <div className="simurgh-page__assistant-layout">
        <section className="simurgh-page__assistant-context" aria-labelledby="simurgh-assistant-context-heading">
          <h3 id="simurgh-assistant-context-heading">Context</h3>
          <span className="simurgh-page__muted">
            {selectedContextIds.length ? `${formatCount(selectedContextIds.length)} selected` : 'Default configured context'}
          </span>
          {selectableResources.length ? (
            <div className="simurgh-page__context-checklist">
              {selectableResources.map((resource) => (
                <label className="simurgh-page__context-option" key={resource.id}>
                  <input
                    type="checkbox"
                    checked={selectedContextIds.includes(resource.id)}
                    disabled={!enabled || submitting}
                    onChange={() => onToggleContext(resource.id)}
                  />
                  <span>
                    <strong>{resource.title}</strong>
                    <code>{resource.id}</code>
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<FaBookOpen />}
              title="No public context"
              detail="The context index did not return selectable public resources."
            />
          )}
        </section>

        <section className="simurgh-page__assistant-turns" aria-labelledby="simurgh-assistant-turns-heading">
          <h3 id="simurgh-assistant-turns-heading">{historyLoading ? 'Loading Turns' : 'Recent Turns'}</h3>
          <AssistantTurnList turns={turns} />
        </section>
      </div>
    </section>
  );
}

function SimurghOperatorPage() {
  const [data, setData] = useState(INITIAL_DATA);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeView, setActiveView] = useState('overview');
  const [assistantMessage, setAssistantMessage] = useState('');
  const [assistantContextIds, setAssistantContextIds] = useState([]);
  const [assistantTurns, setAssistantTurns] = useState([]);
  const [assistantSessionId, setAssistantSessionId] = useState('');
  const [assistantHistoryLoading, setAssistantHistoryLoading] = useState(false);
  const [assistantSubmitting, setAssistantSubmitting] = useState(false);
  const [assistantError, setAssistantError] = useState('');
  const [assistantHistoryError, setAssistantHistoryError] = useState('');

  const loadSimurgh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [
        statusResponse,
        policyResponse,
        toolsResponse,
        contextResponse,
        sessionsResponse,
        auditResponse,
      ] = await Promise.all([
        getSimurghStatusResponse(),
        getSimurghPolicyResponse(),
        getSimurghToolsResponse({ includeExcluded: true }),
        getSimurghContextResponse(),
        getSimurghSessionsResponse({ includeClosed: true }),
        getSimurghAuditResponse(),
      ]);

      const nextData = {
        status: statusResponse?.data || null,
        policy: policyResponse?.data || null,
        tools: toolsResponse?.data?.tools || [],
        contextResources: contextResponse?.data?.resources || [],
        sessions: sessionsResponse?.data?.sessions || [],
        auditEvents: auditResponse?.data?.events || [],
      };
      setData(nextData);
      setAssistantSessionId((current) => {
        if (hasActiveDashboardAssistantSession(nextData.sessions, current)) {
          return current;
        }
        return activeDefaultDashboardAssistantSessionId(nextData.sessions);
      });
    } catch (loadError) {
      setData(INITIAL_DATA);
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAssistantHistory = useCallback(async () => {
    setAssistantHistoryLoading(true);
    setAssistantHistoryError('');
    try {
      const response = await getSimurghAssistantTurnsResponse({ limit: 20 });
      const turns = response?.data?.turns || [];
      setAssistantTurns(turns);
    } catch (historyLoadError) {
      setAssistantHistoryError(errorMessage(historyLoadError));
    } finally {
      setAssistantHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSimurgh();
    loadAssistantHistory();
  }, [loadAssistantHistory, loadSimurgh]);

  const assistantEnabled = Boolean(data.status?.agent_enabled);

  const toggleAssistantContext = useCallback((resourceId) => {
    setAssistantContextIds((current) => (
      current.includes(resourceId)
        ? current.filter((id) => id !== resourceId)
        : [...current, resourceId]
    ));
  }, []);

  const submitAssistantTurn = useCallback(async (event) => {
    event.preventDefault();
    const message = assistantMessage.trim();
    if (!assistantEnabled || !message || assistantSubmitting) {
      return;
    }

    setAssistantSubmitting(true);
    setAssistantError('');
    try {
      const availableContextIds = new Set(data.contextResources.map((resource) => resource.id));
      const contextResourceIds = assistantContextIds.filter((resourceId) => availableContextIds.has(resourceId));
      const reusableSessionId = hasActiveDashboardAssistantSession(data.sessions, assistantSessionId)
        ? assistantSessionId
        : '';
      const payload = {
        actor: DASHBOARD_ASSISTANT_ACTOR,
        message,
        ...(reusableSessionId ? { session_id: reusableSessionId } : {}),
        metadata: {
          source: 'simurgh-dashboard',
        },
        ...(contextResourceIds.length ? { context_resource_ids: contextResourceIds } : {}),
      };
      const response = await createSimurghAssistantTurnResponse(payload);
      const nextSessionId = response?.data?.session?.id || assistantSessionId;
      setAssistantSessionId(nextSessionId);
      setAssistantMessage('');
      await Promise.all([loadSimurgh(), loadAssistantHistory()]);
    } catch (submitError) {
      setAssistantError(errorMessage(submitError));
    } finally {
      setAssistantSubmitting(false);
    }
  }, [
    assistantContextIds,
    assistantEnabled,
    assistantMessage,
    assistantSessionId,
    assistantSubmitting,
    data.contextResources,
    data.sessions,
    loadAssistantHistory,
    loadSimurgh,
  ]);

  const startNewAssistantSession = useCallback(() => {
    setAssistantSessionId('');
    setAssistantError('');
  }, []);

  const focusTab = useCallback((tabId) => {
    setActiveView(tabId);
    window.requestAnimationFrame(() => {
      document.getElementById(`simurgh-tab-${tabId}`)?.focus();
    });
  }, []);

  const handleTabKeyDown = useCallback((event) => {
    const currentIndex = VIEW_TABS.findIndex((tab) => tab.id === activeView);
    if (currentIndex < 0) {
      return;
    }
    let nextIndex = currentIndex;
    if (['ArrowRight', 'ArrowDown'].includes(event.key)) {
      nextIndex = (currentIndex + 1) % VIEW_TABS.length;
    } else if (['ArrowLeft', 'ArrowUp'].includes(event.key)) {
      nextIndex = (currentIndex - 1 + VIEW_TABS.length) % VIEW_TABS.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = VIEW_TABS.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    focusTab(VIEW_TABS[nextIndex].id);
  }, [activeView, focusTab]);

  const metrics = useMemo(() => {
    const { status, policy, tools, contextResources, sessions, auditEvents } = data;
    return [
      {
        key: 'agent',
        label: 'Agent',
        value: boolLabel(status?.agent_enabled),
        tone: status?.agent_enabled ? 'success' : 'muted',
        icon: <FaRobot />,
      },
      {
        key: 'mcp',
        label: 'MCP',
        value: boolLabel(status?.mcp_enabled),
        tone: status?.mcp_enabled ? 'success' : 'muted',
        icon: <FaNetworkWired />,
      },
      {
        key: 'provider',
        label: 'Provider',
        value: formatToken(status?.assistant_provider || 'mock'),
        detail: status?.assistant_external_provider
          ? (status?.assistant_external_provider_auth_required ? 'External API, auth required' : 'External API')
          : 'Local mock',
        tone: status?.assistant_external_provider ? 'warning' : 'success',
        icon: <FaRobot />,
      },
      {
        key: 'circuit',
        label: 'Circuit',
        value: status?.action_circuit_breaker_enabled ? 'No actions' : 'Actions possible',
        detail: status?.always_confirm_before_action ? 'Always confirm' : 'Policy confirms',
        tone: status?.action_circuit_breaker_enabled ? 'success' : 'danger',
        icon: <FaShieldAlt />,
      },
      {
        key: 'gcs-mode',
        label: 'GCS Mode',
        value: formatToken(status?.gcs_mode),
        detail: status?.gcs_mode_source || 'MDS_MODE',
        tone: status?.gcs_mode === 'real' ? 'warning' : 'info',
        icon: <FaServer />,
      },
      {
        key: 'mode',
        label: 'Policy Profile',
        value: formatToken(status?.mode || policy?.mode),
        detail: 'advanced',
        tone: 'info',
        icon: <FaServer />,
      },
      {
        key: 'tools',
        label: 'Tools',
        value: formatCount(status?.tool_count ?? tools.length),
        detail: `${formatCount(status?.allowed_tool_count)} allow / ${formatCount(status?.guarded_tool_count)} guarded`,
        icon: <FaTools />,
      },
      {
        key: 'excluded',
        label: 'Excluded',
        value: formatCount(status?.excluded_tool_count),
        detail: 'Blocked registry entries',
        tone: 'danger',
        icon: <FaBan />,
      },
      {
        key: 'context',
        label: 'Context',
        value: formatCount(status?.context_resource_count ?? contextResources.length),
        detail: 'Model-readable resources',
        icon: <FaBookOpen />,
      },
      {
        key: 'sessions',
        label: 'Sessions',
        value: formatCount(status?.active_session_count ?? sessions.filter((session) => !session.closed).length),
        detail: 'Active agent sessions',
        icon: <FaUserShield />,
      },
      {
        key: 'audit',
        label: 'Audit',
        value: formatCount(status?.audit_event_count ?? auditEvents.length),
        detail: 'Recorded events',
        icon: <FaHistory />,
      },
    ];
  }, [data]);

  const statusBadge = data.status ? (
    <StatusBadge
      tone={data.status.agent_enabled ? 'success' : 'muted'}
      icon={data.status.agent_enabled ? <FaCheckCircle /> : <FaLock />}
    >
      {boolLabel(data.status.agent_enabled)}
    </StatusBadge>
  ) : (
    <StatusBadge tone={loading ? 'info' : 'muted'} icon={<FaClock />}>
      {loading ? 'Loading' : 'Unknown'}
    </StatusBadge>
  );

  const actions = (
    <PageActionBar
      primary={[
        <ActionIconButton
          key="refresh"
          icon={<FaSyncAlt />}
          label="Refresh Simurgh status"
          onClick={loadSimurgh}
          disabled={loading}
        >
          {loading ? 'Refreshing' : 'Refresh'}
        </ActionIconButton>,
      ]}
    />
  );

  return (
    <PageShell
      className="simurgh-page"
      eyebrow="Simurgh Operator"
      title="Agent Control Plane"
      subtitle="GCS-only agent posture, policy registry, context, sessions, and audit."
      icon={<FaUserShield />}
      docsRoute="/simurgh"
      actions={actions}
      status={statusBadge}
    >
      <MetricStrip items={metrics} label="Simurgh status summary" />

      {error ? (
        <OperatorNotice tone="danger" title="Simurgh metadata unavailable" role="alert">
          {error}
        </OperatorNotice>
      ) : null}

      {!error && data.status && !data.status.agent_enabled ? (
        <OperatorNotice tone="info" title="Agent runtime disabled">
          Execution adapters are not enabled from this dashboard.
        </OperatorNotice>
      ) : null}

      {!error && data.status?.warnings?.length ? (
        <OperatorNotice tone="warning" title="Simurgh posture warnings">
          {data.status.warnings.join(' ')}
        </OperatorNotice>
      ) : null}

      {!error && !data.status && loading ? (
        <OperatorNotice tone="info" title="Loading Simurgh control plane">
          Reading GCS metadata endpoints.
        </OperatorNotice>
      ) : null}

      <div className="simurgh-page__tabs" role="tablist" aria-label="Simurgh views">
        {VIEW_TABS.map((tab) => {
          const Icon = tab.icon;
          const selected = activeView === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`simurgh-tab-${tab.id}`}
              aria-controls={`simurgh-panel-${tab.id}`}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              className={selected ? 'is-active' : ''}
              onClick={() => setActiveView(tab.id)}
              onKeyDown={handleTabKeyDown}
            >
              <Icon aria-hidden="true" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {activeView === 'overview' ? (
        <div
          id="simurgh-panel-overview"
          role="tabpanel"
          aria-labelledby="simurgh-tab-overview"
          className="simurgh-page__panel"
        >
          <PolicyOverview policy={data.policy} status={data.status} />
          <RuntimeModes policy={data.policy} />
          <ArtifactPaths status={data.status} />
        </div>
      ) : null}
      {activeView === 'assistant' ? (
        <div
          id="simurgh-panel-assistant"
          role="tabpanel"
          aria-labelledby="simurgh-tab-assistant"
          className="simurgh-page__panel"
        >
          <AssistantView
            enabled={assistantEnabled}
            resources={data.contextResources}
            message={assistantMessage}
            selectedContextIds={assistantContextIds}
            turns={assistantTurns}
            submitting={assistantSubmitting}
            error={assistantError}
            historyLoading={assistantHistoryLoading}
            historyError={assistantHistoryError}
            activeSessionId={assistantSessionId}
            provider={data.status?.assistant_provider}
            externalProviderAuthRequired={data.status?.assistant_external_provider_auth_required}
            onMessageChange={setAssistantMessage}
            onToggleContext={toggleAssistantContext}
            onNewConversation={startNewAssistantSession}
            onSubmit={submitAssistantTurn}
          />
        </div>
      ) : null}
      {activeView === 'tools' ? (
        <div
          id="simurgh-panel-tools"
          role="tabpanel"
          aria-labelledby="simurgh-tab-tools"
          className="simurgh-page__panel"
        >
          <ToolsView tools={data.tools} />
        </div>
      ) : null}
      {activeView === 'context' ? (
        <div
          id="simurgh-panel-context"
          role="tabpanel"
          aria-labelledby="simurgh-tab-context"
          className="simurgh-page__panel"
        >
          <ContextView resources={data.contextResources} />
        </div>
      ) : null}
      {activeView === 'audit' ? (
        <div
          id="simurgh-panel-audit"
          role="tabpanel"
          aria-labelledby="simurgh-tab-audit"
          className="simurgh-page__panel"
        >
          <AuditView sessions={data.sessions} auditEvents={data.auditEvents} />
        </div>
      ) : null}
    </PageShell>
  );
}

export default SimurghOperatorPage;
