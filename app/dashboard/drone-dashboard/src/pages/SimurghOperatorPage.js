import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FaChevronDown,
  FaChevronRight,
  FaCheckCircle,
  FaCog,
  FaCopy,
  FaExclamationTriangle,
  FaEllipsisH,
  FaPaperPlane,
  FaPause,
  FaPlay,
  FaPlus,
  FaRobot,
  FaSave,
  FaShieldAlt,
  FaStop,
  FaTimes,
  FaTrash,
  FaUserShield,
} from 'react-icons/fa';

import {
  ActionIconButton,
  OperatorNotice,
  PageShell,
  StatusBadge,
} from '../components/ui';
import {
  createSimurghAssistantTurnResponse,
  controlSimurghActionRunResponse,
  getSimurghActionRunResponse,
  getSimurghActionRunsResponse,
  streamSimurghAssistantTurnResponse,
  streamSimurghActionRunEventsResponse,
  getSimurghRuntimeSettingsResponse,
  getSimurghStatusResponse,
  getSimurghToolCandidatesResponse,
  getSimurghToolsResponse,
  updateSimurghProviderCredentialsResponse,
  updateSimurghRuntimeSettingsResponse,
} from '../services/gcsApiService';
import simurghMark from '../assets/simurgh-mark.svg';
import '../styles/SimurghOperatorPage.css';

const STORAGE_KEY = 'mds.simurgh.chat.v2';
const DASHBOARD_ACTOR = 'dashboard';
const MAX_CONVERSATIONS = 30;
const DEFAULT_MODEL = 'gpt-5.6';
const ACTIVE_ACTION_RUN_STATES = new Set(['queued', 'running', 'pause_requested', 'paused', 'cancel_requested']);
const TERMINAL_ACTION_RUN_STATES = new Set(['succeeded', 'failed', 'blocked', 'cancelled', 'interrupted']);
const ACTION_RUN_STATES = new Set([...ACTIVE_ACTION_RUN_STATES, ...TERMINAL_ACTION_RUN_STATES]);
const STARTERS = [
  'How many drones do we have configured?',
  'Is there any drone connected?',
  'What formation swarm is defined right now?',
];
const INLINE_MARKDOWN_PATTERN = /(\[([^\]\n]+)\]\(([^)\s]+)\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*)/g;
const AUTO_LINK_PATTERN = /(https:\/\/[^\s)\]]+|docs\/[A-Za-z0-9_./-]+\.md|\/[A-Za-z0-9][A-Za-z0-9/_{}.-]*)/g;
const LINKABLE_DASHBOARD_ROUTES = Object.freeze([
  '/environments',
  '/fleet-enrollment',
  '/fleet-ops',
  '/logs',
  '/manage-drone-show',
  '/mission-config',
  '/quickscout',
  '/simurgh',
  '/sitl-control',
  '/swarm-design',
  '/swarm-trajectory',
]);
const LINKABLE_DASHBOARD_ROUTE_PREFIXES = Object.freeze([
  '/fleet-ops/',
]);
const LINKABLE_DOC_ROUTE_PATTERN = /^\/api\/v1\/simurgh\/context\/[A-Za-z0-9_.-]+\/markdown$/;
const TRAILING_LINK_PUNCTUATION_PATTERN = /[.,;:]+$/;
const DOC_PATH_LINKS = Object.freeze({
  'docs/apis/gcs-api-server.md': '/api/v1/simurgh/context/mds.gcs_api/markdown',
  'docs/agent-context/safety-policy.md': '/api/v1/simurgh/context/simurgh.safety_policy/markdown',
  'docs/agent-context/tool-usage-guidelines.md': '/api/v1/simurgh/context/simurgh.tool_usage/markdown',
  'docs/features/drone-show.md': '/api/v1/simurgh/context/mds.drone_show/markdown',
  'docs/features/swarm-trajectory.md': '/api/v1/simurgh/context/mds.swarm_trajectory/markdown',
  'docs/guides/logging-system.md': '/api/v1/simurgh/context/mds.logging_system/markdown',
  'docs/guides/mavlink-routing-setup.md': '/api/v1/simurgh/context/mds.mavlink_routing_setup/markdown',
  'docs/guides/simurgh-operator.md': '/api/v1/simurgh/context/simurgh.operator_guide/markdown',
  'docs/guides/simurgh-mcp-clients.md': '/api/v1/simurgh/context/simurgh.mcp_client_recipes/markdown',
  'docs/reference/mds-environment-registry.generated.md': '/api/v1/simurgh/context/mds.environment_registry/markdown',
});

const DEFAULT_SETTINGS = Object.freeze({
  agent_enabled: true,
  mcp_enabled: false,
  action_circuit_breaker_enabled: true,
  always_confirm_before_action: true,
  provider: 'mock',
  openai_model: DEFAULT_MODEL,
  web_search_enabled: false,
});

function nowIso() {
  return new Date().toISOString();
}

function newConversation() {
  return {
    id: `local-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    backendSessionId: '',
    title: 'New chat',
    createdAt: nowIso(),
    updatedAt: nowIso(),
    messages: [],
  };
}

function normalizeError(error, fallback = 'Simurgh request failed.') {
  return error?.response?.data?.detail
    || error?.response?.data?.message
    || error?.message
    || fallback;
}

function readStoredConversations() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
    const conversations = Array.isArray(parsed.conversations) ? parsed.conversations : [];
    return conversations
      .filter((conversation) => conversation && conversation.id)
      .map((conversation) => ({
        id: String(conversation.id),
        backendSessionId: String(conversation.backendSessionId || ''),
        title: String(conversation.title || 'New chat').slice(0, 80),
        createdAt: conversation.createdAt || nowIso(),
        updatedAt: conversation.updatedAt || conversation.createdAt || nowIso(),
        messages: Array.isArray(conversation.messages)
          ? conversation.messages.filter((message) => message && message.role && message.content)
            .map((message) => ({
              ...message,
              trace: message.trace && typeof message.trace === 'object' && !Array.isArray(message.trace) ? message.trace : undefined,
              safety_notes: Array.isArray(message.safety_notes) ? message.safety_notes.slice(0, 8) : [],
              blocked_intents: Array.isArray(message.blocked_intents) ? message.blocked_intents.slice(0, 8) : [],
              progress: Array.isArray(message.progress)
                ? message.progress.map(normalizeProgressStep).filter(Boolean).slice(-32)
                : [],
            }))
          : [],
      }))
      .slice(0, MAX_CONVERSATIONS);
  } catch (error) {
    return [];
  }
}

function writeStoredConversations(conversations) {
  try {
    const persisted = conversations.slice(0, MAX_CONVERSATIONS).map((conversation) => ({
      ...conversation,
      messages: (conversation.messages || [])
        .filter((message) => message && message.role && message.content && !message.streaming)
        .map((message) => ({
          id: message.id,
          role: message.role,
          content: message.content,
          createdAt: message.createdAt,
          provider: message.provider,
          model: message.model,
          trace: message.trace && typeof message.trace === 'object' && !Array.isArray(message.trace) ? message.trace : undefined,
          safety_notes: Array.isArray(message.safety_notes) ? message.safety_notes.slice(0, 8) : [],
          blocked_intents: Array.isArray(message.blocked_intents) ? message.blocked_intents.slice(0, 8) : [],
          progress: Array.isArray(message.progress)
            ? message.progress.map(normalizeProgressStep).filter(Boolean).slice(-32)
            : [],
        })),
    }));
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ schema: 2, conversations: persisted })
    );
  } catch (error) {
    // Local chat history is a convenience cache only.
  }
}

function clearStoredConversations() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    // Local chat history is a convenience cache only.
  }
}

function titleFromMessage(message) {
  const normalized = message.trim().replace(/\s+/g, ' ');
  if (!normalized) {
    return 'New chat';
  }
  return normalized.length > 54 ? `${normalized.slice(0, 51)}...` : normalized;
}

function normalizeProgressState(value = '') {
  const state = String(value || '').trim().toLowerCase();
  if (state === 'running' || state === 'active' || state === 'started') {
    return 'running';
  }
  if (state === 'requested' || state === 'queued' || state === 'pending') {
    return 'requested';
  }
  if (state === 'complete' || state === 'completed' || state === 'success' || state === 'done') {
    return 'complete';
  }
  if (state === 'fallback') {
    return 'fallback';
  }
  if (state === 'skipped' || state === 'skip') {
    return 'skipped';
  }
  if (state === 'warning' || state === 'warn') {
    return 'warning';
  }
  if (state === 'timeout' || state === 'timed_out' || state === 'timed-out') {
    return 'timeout';
  }
  if (state === 'error' || state === 'failed' || state === 'failure') {
    return 'error';
  }
  if (state === 'stopped' || state === 'stop') {
    return 'stopped';
  }
  if (state === 'cancelled' || state === 'canceled') {
    return 'cancelled';
  }
  if (state === 'blocked') {
    return 'blocked';
  }
  return '';
}

function normalizeProgressStep(step) {
  if (!step) {
    return null;
  }
  if (typeof step === 'string') {
    const label = step.trim();
    return label ? { label, stage: '', state: '', tool_id: '', key: label } : null;
  }
  if (typeof step !== 'object' || Array.isArray(step)) {
    return null;
  }

  const label = String(step.label || step.message || step.stage || '').trim();
  if (!label) {
    return null;
  }
  const stage = String(step.stage || '').trim();
  const state = normalizeProgressState(step.state);
  const toolId = String(step.tool_id || step.toolId || '').trim();
  const toolIds = Array.isArray(step.tool_ids)
    ? step.tool_ids.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  const intent = String(step.intent || '').trim();
  const sequenceId = String(step.sequence_id || step.sequenceId || '').trim();
  const stepIndexRaw = Number(step.step_index ?? step.stepIndex);
  const stepCountRaw = Number(step.step_count ?? step.stepCount);
  const stepIndex = Number.isFinite(stepIndexRaw) && stepIndexRaw > 0 ? stepIndexRaw : null;
  const stepCount = Number.isFinite(stepCountRaw) && stepCountRaw > 0 ? stepCountRaw : null;
  const stepLabel = String(step.step_label || step.stepLabel || '').trim();
  const stepKind = String(step.step_kind || step.stepKind || '').trim();
  const commandId = String(step.command_id || step.commandId || '').trim();
  const operationId = String(step.operation_id || step.operationId || '').trim();
  const key = sequenceId
    ? ['sequence', sequenceId, stepIndex || stepLabel || commandId || operationId || stage || label].filter(Boolean).join(':')
    : [toolId || toolIds.join(',') || intent || stage, label].filter(Boolean).join(':') || label;
  return {
    label,
    stage,
    state,
    tool_id: toolId,
    tool_ids: toolIds,
    intent,
    sequence_id: sequenceId,
    step_index: stepIndex,
    step_count: stepCount,
    step_label: stepLabel,
    step_kind: stepKind,
    command_id: commandId,
    operation_id: operationId,
    key,
  };
}

function isSpecificProgressStep(step) {
  if (!step) {
    return false;
  }
  return Boolean(
    step.tool_id
    || (Array.isArray(step.tool_ids) && step.tool_ids.length)
    || step.intent
    || step.sequence_id
    || step.step_label
    || step.step_index
    || ['tool', 'search', 'provider', 'monitor', 'action'].includes(step.stage)
  );
}

function isGenericProgressStep(step) {
  if (!step || isSpecificProgressStep(step)) {
    return false;
  }
  const label = String(step.label || '').toLowerCase();
  return ['understanding', 'policy', 'context', 'plan', 'answer'].includes(step.stage)
    || /reading request|understanding request|checking safety|selecting mds|writing answer|streaming answer/.test(label);
}

function appendProgressStep(steps = [], payload = '') {
  const normalized = normalizeProgressStep(payload);
  if (!normalized) {
    return steps;
  }
  const existing = (Array.isArray(steps) ? steps : [])
    .map(normalizeProgressStep)
    .filter(Boolean)
    .filter((step) => step.key !== normalized.key);
  const hasSpecificEvidence = existing.some(isSpecificProgressStep) || isSpecificProgressStep(normalized);
  if (isGenericProgressStep(normalized) && existing.some(isSpecificProgressStep)) {
    return existing.slice(-32);
  }
  const compactExisting = hasSpecificEvidence ? existing.filter((step) => !isGenericProgressStep(step)) : existing;
  return [...compactExisting, normalized].slice(-32);
}

function activityStatusText(state = '') {
  if (state === 'running' || state === 'requested') {
    return 'Working';
  }
  if (state === 'timeout') {
    return 'Timed out';
  }
  if (state === 'warning') {
    return 'Review';
  }
  if (state === 'error' || state === 'blocked' || state === 'stopped' || state === 'cancelled') {
    return 'Stopped';
  }
  return 'Ready';
}

function activityStepIcon(state = '') {
  if (state === 'running') {
    return <FaCog aria-hidden="true" />;
  }
  if (state === 'warning' || state === 'timeout') {
    return <FaExclamationTriangle aria-hidden="true" />;
  }
  if (state === 'error' || state === 'blocked' || state === 'stopped' || state === 'cancelled') {
    return <FaTimes aria-hidden="true" />;
  }
  return <FaCheckCircle aria-hidden="true" />;
}

function activityStateLabel(state = '') {
  if (state === 'running' || state === 'requested') {
    return 'in progress';
  }
  if (state === 'complete') {
    return 'completed';
  }
  if (state === 'timeout') {
    return 'timed out';
  }
  if (state === 'warning' || state === 'fallback') {
    return 'needs review';
  }
  if (state === 'skipped') {
    return 'skipped';
  }
  if (state === 'cancelled') {
    return 'cancelled';
  }
  if (state === 'paused') {
    return 'paused';
  }
  if (state === 'pending') {
    return 'pending';
  }
  if (state === 'failed') {
    return 'failed';
  }
  if (state === 'error' || state === 'blocked' || state === 'stopped') {
    return 'stopped';
  }
  return 'status unavailable';
}

function finalizeProgressSteps(progress = [], finalData = {}) {
  const existing = (Array.isArray(progress) ? progress : [])
    .map(normalizeProgressStep)
    .filter(Boolean)
    .filter((step) => !isGenericProgressStep(step))
    .map((step) => (step.state === 'running' ? { ...step, state: 'complete' } : step));
  const summary = getTraceSummary(finalData.trace || {}, finalData);
  const finalStep = summary
    ? { stage: 'result', state: 'complete', intent: 'assistant_answer', label: summary }
    : { stage: 'result', state: 'complete', intent: 'assistant_answer', label: 'Answer ready' };
  return appendProgressStep(existing, finalStep).slice(-32);
}

function stopProgressSteps(progress = []) {
  const existing = (Array.isArray(progress) ? progress : [])
    .map(normalizeProgressStep)
    .filter(Boolean)
    .filter((step) => !isGenericProgressStep(step))
    .map((step) => (step.state === 'running' ? { ...step, state: 'stopped' } : step));
  return appendProgressStep(existing, {
    stage: 'result',
    state: 'stopped',
    intent: 'assistant_response',
    label: 'Simurgh response stopped',
  }).slice(-32);
}

function titleCaseTraceLabel(value = '') {
  return String(value || '')
    .replace(/[_.-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function compactTraceValue(value) {
  if (value === null || value === undefined || value === '') {
    return '';
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }
  if (Array.isArray(value)) {
    return value.map(compactTraceValue).filter(Boolean).join(', ');
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : '';
  }
  return String(value).replace(/\s+/g, ' ').trim();
}

function uniqueTraceValues(values = []) {
  const seen = new Set();
  const normalized = [];
  values.forEach((value) => {
    const text = compactTraceValue(value);
    if (!text || seen.has(text)) {
      return;
    }
    seen.add(text);
    normalized.push(text);
  });
  return normalized;
}

function getTraceToolIds(trace = {}) {
  const directIds = Array.isArray(trace?.tool?.ids) ? trace.tool.ids : [];
  const plannedIds = Array.isArray(trace?.query?.read_only_plan?.tool_ids)
    ? trace.query.read_only_plan.tool_ids
    : [];
  const actualIds = uniqueTraceValues(directIds);
  return actualIds.length ? actualIds : uniqueTraceValues(plannedIds);
}

function getTraceSummary(trace = {}, message = {}) {
  const actionExecution = compactTraceValue(trace?.safety?.action_execution);
  const actionLabels = {
    awaiting_confirmation: 'Action draft ready',
    missing_arguments: 'Action needs details',
    blocked_by_circuit_breaker: 'Circuit breaker stopped action',
    policy_denied: 'Policy denied action',
    validation_rejected: 'GCS rejected action',
    submitted: 'GCS accepted action',
    cancelled_confirmation: 'Action cancelled',
  };
  if (actionLabels[actionExecution]) {
    return actionLabels[actionExecution];
  }

  const toolIds = getTraceToolIds(trace);
  if (toolIds.length === 1) {
    return 'Evidence ready';
  }
  if (toolIds.length > 1) {
    return `Evidence ready · ${toolIds.length} sources`;
  }

  if (trace?.provider_tools?.web_search_returned) {
    return 'Public web sources';
  }
  if (trace?.provider_tools?.web_search_requested) {
    return 'Public lookup requested';
  }

  const retrievedCount = Number(trace?.context?.retrieved_context_count || 0);
  const resourceCount = Number(trace?.context?.resource_count || 0);
  if (retrievedCount > 0 || resourceCount > 0 || (message.context_resources || []).length > 0) {
    return 'Checked MDS context';
  }

  if (trace?.provider === 'openai' || message.provider === 'openai') {
    return 'OpenAI answer ready';
  }

  if (trace?.query?.domain || trace?.tool?.intent || trace?.safety?.action_execution) {
    return 'Checked Simurgh policy';
  }

  return '';
}

function buildTraceRows(trace = {}, message = {}) {
  const rows = [];
  const provider = compactTraceValue(trace.provider || message.provider);
  const model = compactTraceValue(trace.model || message.model);
  if (provider || model) {
    rows.push({ label: 'Model path', value: [provider, model].filter(Boolean).join(' / ') });
  }

  const domain = compactTraceValue(trace?.query?.domain);
  const confidence = compactTraceValue(trace?.query?.confidence);
  const responseMode = compactTraceValue(trace?.query?.response_mode);
  if (domain || confidence || responseMode) {
    rows.push({
      label: 'Understanding',
      value: [
        domain && titleCaseTraceLabel(domain),
        confidence && `confidence ${confidence}`,
        responseMode && titleCaseTraceLabel(responseMode),
      ].filter(Boolean).join(' · '),
    });
  }

  const intent = compactTraceValue(trace?.tool?.intent || trace?.query?.read_only_plan?.intent);
  if (intent) {
    rows.push({ label: 'Intent', value: titleCaseTraceLabel(intent) });
  }

  const toolIds = getTraceToolIds(trace);
  if (toolIds.length) {
    rows.push({ label: 'Tools', value: toolIds.join(', ') });
  }

  if (trace?.provider_tools?.web_search_returned) {
    rows.push({ label: 'Lookup', value: 'Public web search' });
  } else if (trace?.provider_tools?.web_search_requested) {
    rows.push({ label: 'Lookup', value: 'Public web search requested' });
  }

  const sourceStatus = compactTraceValue(trace?.provider_tools?.source_status);
  const citationCount = Number(trace?.provider_tools?.citation_count || 0);
  if (sourceStatus === 'citations_returned') {
    rows.push({ label: 'Sources', value: `${citationCount || 1} citation URL(s)` });
  } else if (sourceStatus === 'search_returned_without_citations') {
    rows.push({ label: 'Sources', value: 'No citation URLs returned' });
  } else if (sourceStatus === 'search_requested_without_returned_call') {
    rows.push({ label: 'Sources', value: 'Search requested; no source call returned' });
  }

  const contextBits = [];
  const resourceCount = compactTraceValue(trace?.context?.resource_count);
  const retrievedCount = compactTraceValue(trace?.context?.retrieved_context_count);
  if (resourceCount) {
    contextBits.push(`${resourceCount} resource(s)`);
  }
  if (retrievedCount) {
    contextBits.push(`${retrievedCount} retrieved chunk(s)`);
  }
  if (!contextBits.length && Array.isArray(message.context_resources) && message.context_resources.length) {
    contextBits.push(`${message.context_resources.length} context resource(s)`);
  }
  if (contextBits.length) {
    rows.push({ label: 'Context', value: contextBits.join(' · ') });
  }

  const languageBits = uniqueTraceValues([
    trace?.language?.detected_language,
    trace?.language?.requested_language,
    trace?.language?.response_language,
    trace?.language?.tone,
  ]);
  if (languageBits.length) {
    rows.push({ label: 'Language', value: languageBits.join(' · ') });
  }

  const blockedCount = compactTraceValue(trace?.safety?.blocked_intent_count);
  const execution = compactTraceValue(trace?.safety?.action_execution);
  if (execution || blockedCount || (message.blocked_intents || []).length) {
    const safetyBits = [execution && `action execution: ${execution}`];
    if (blockedCount) {
      safetyBits.push(`${blockedCount} blocked intent(s)`);
    }
    if ((message.blocked_intents || []).length) {
      safetyBits.push(`blocked: ${message.blocked_intents.join(', ')}`);
    }
    rows.push({ label: 'Safety', value: safetyBits.filter(Boolean).join(' · ') });
  }

  return rows.filter((row) => row.value);
}

function formatConversationTime(value) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function normalizeProvider(value) {
  const provider = String(value || '').trim().toLowerCase();
  return provider === 'openai' ? 'openai' : 'mock';
}

function normalizeSettings(payload = {}) {
  const provider = normalizeProvider(payload.provider || payload.assistant_provider || DEFAULT_SETTINGS.provider);
  const openaiModel = String(payload.openai_model || payload.model || payload.assistant_model || DEFAULT_MODEL).trim();
  return {
    agent_enabled: Boolean(payload.agent_enabled ?? DEFAULT_SETTINGS.agent_enabled),
    mcp_enabled: Boolean(payload.mcp_enabled ?? DEFAULT_SETTINGS.mcp_enabled),
    action_circuit_breaker_enabled: Boolean(
      payload.action_circuit_breaker_enabled ?? DEFAULT_SETTINGS.action_circuit_breaker_enabled
    ),
    always_confirm_before_action: Boolean(
      payload.always_confirm_before_action ?? DEFAULT_SETTINGS.always_confirm_before_action
    ),
    provider,
    openai_model: openaiModel && openaiModel !== 'mock-local' ? openaiModel : DEFAULT_MODEL,
    web_search_enabled: Boolean(payload.web_search_enabled ?? DEFAULT_SETTINGS.web_search_enabled),
  };
}

function conversationPreview(conversation) {
  const lastMessage = [...(conversation.messages || [])].reverse().find((message) => message.content);
  return lastMessage?.content || 'No messages yet';
}

function SafetyChips({ status }) {
  const agentEnabled = Boolean(status?.agent_enabled);
  const circuitBreaker = Boolean(status?.action_circuit_breaker_enabled);
  const mcpEnabled = Boolean(status?.mcp_enabled);
  const gcsMode = status?.gcs_mode ? String(status.gcs_mode).toUpperCase() : 'UNKNOWN';
  const providerReady = status?.provider_ready !== false;

  return (
    <div className="simurgh-chat__chips" aria-label="Simurgh posture">
      <StatusBadge tone={agentEnabled ? 'success' : 'muted'} icon={<FaRobot />}>
        {agentEnabled ? 'Agent on' : 'Agent off'}
      </StatusBadge>
      <StatusBadge tone={gcsMode === 'REAL' ? 'warning' : 'info'} icon={<FaShieldAlt />}>
        {gcsMode}
      </StatusBadge>
      <StatusBadge tone={circuitBreaker ? 'success' : 'danger'} icon={circuitBreaker ? <FaCheckCircle /> : <FaExclamationTriangle />}>
        {circuitBreaker ? 'Circuit breaker on' : 'Circuit breaker off'}
      </StatusBadge>
      <StatusBadge tone={mcpEnabled ? 'warning' : 'muted'}>
        {mcpEnabled ? 'MCP on' : 'MCP off'}
      </StatusBadge>
      <StatusBadge tone={providerReady ? 'success' : 'warning'}>
        {providerReady ? 'Provider ready' : 'Provider key missing'}
      </StatusBadge>
    </div>
  );
}

function SimurghMark({ className = '' }) {
  return <img className={['simurgh-chat__mark', className].filter(Boolean).join(' ')} src={simurghMark} alt="" />;
}

function CandidateReviewSummary({ review }) {
  if (!review) {
    return null;
  }
  const summary = review.summary || {};
  const total = Number(summary.total || review.candidate_count || 0);
  const eligible = Number(summary.eligible_read_only_mcp_candidates || 0);
  const promoted = Number(summary.promoted_registry_route_matches || 0);
  const guarded = Number(summary.candidate_exclude_or_guard_after_review || 0);
  return (
    <section className="simurgh-chat__candidate-review" aria-label="MCP candidate review">
      <header>
        <span>MCP review</span>
        <a href="/api/v1/simurgh/tool-candidates?limit=200" target="_blank" rel="noopener noreferrer">
          Open
        </a>
      </header>
      <dl>
        <div>
          <dt>Discovered</dt>
          <dd>{Number.isFinite(total) ? total : 0}</dd>
        </div>
        <div>
          <dt>Eligible</dt>
          <dd>{Number.isFinite(eligible) ? eligible : 0}</dd>
        </div>
        <div>
          <dt>Active</dt>
          <dd>{Number.isFinite(promoted) ? promoted : 0}</dd>
        </div>
        <div>
          <dt>Guarded</dt>
          <dd>{Number.isFinite(guarded) ? guarded : 0}</dd>
        </div>
      </dl>
      <small>{review.artifact_path || 'Generated candidates are review-only until registry and policy approval.'}</small>
    </section>
  );
}

function ActiveToolSummary({ toolList }) {
  if (!toolList) {
    return null;
  }
  const tools = Array.isArray(toolList.tools) ? toolList.tools : [];
  const readOnly = tools.filter((tool) => tool?.read_only).length;
  const guarded = tools.filter((tool) => tool?.requires_approval || !tool?.read_only || tool?.destructive).length;
  const preview = tools
    .filter((tool) => tool?.read_only)
    .slice(0, 5)
    .map((tool) => tool.title || tool.id)
    .filter(Boolean);

  return (
    <section className="simurgh-chat__tool-summary" aria-label="Active Simurgh MCP tools">
      <header>
        <span>Active tools</span>
        <a href="/api/v1/simurgh/tools?include_excluded=false" target="_blank" rel="noopener noreferrer">
          Open
        </a>
      </header>
      <dl>
        <div>
          <dt>Visible</dt>
          <dd>{tools.length}</dd>
        </div>
        <div>
          <dt>Read-only</dt>
          <dd>{readOnly}</dd>
        </div>
        <div>
          <dt>Guarded</dt>
          <dd>{guarded}</dd>
        </div>
      </dl>
      {preview.length ? (
        <ul>
          {preview.map((title) => <li key={title}>{title}</li>)}
        </ul>
      ) : (
        <small>No read-only tools are currently visible.</small>
      )}
    </section>
  );
}

function SettingsPanel({
  open,
  settings,
  status,
  candidateReview,
  activeTools,
  busy,
  notice,
  credentialDraft,
  onCredentialDraftChange,
  onChange,
  onSave,
  onClose,
}) {
  if (!open) {
    return null;
  }
  const availableModels = Array.from(new Set(
    status?.available_models?.length ? status.available_models : [DEFAULT_MODEL, 'gpt-5.6-terra', 'gpt-5.6-luna']
  ));
  const openAiCredential = status?.credentials?.openai || {};
  const keyReady = Boolean(openAiCredential.ready || status?.openai_key_file_ready);
  const keyFingerprint = openAiCredential.fingerprint || status?.openai_key_fingerprint || '';

  return (
    <aside className="simurgh-chat__settings" aria-label="Simurgh settings">
      <header>
        <h2>Settings</h2>
        <button type="button" onClick={onClose} aria-label="Close Simurgh settings">
          <FaTimes aria-hidden="true" />
        </button>
      </header>
      {notice ? <OperatorNotice tone={notice.tone} title={notice.title}>{notice.detail}</OperatorNotice> : null}
      <div className="simurgh-chat__settings-grid">
        <label className="simurgh-chat__toggle">
          <input
            type="checkbox"
            checked={settings.agent_enabled}
            disabled={busy}
            onChange={(event) => onChange({ agent_enabled: event.target.checked })}
          />
          <span>Simurgh agent</span>
        </label>
        <label className="simurgh-chat__toggle">
          <input
            type="checkbox"
            checked={settings.mcp_enabled}
            disabled={busy}
            onChange={(event) => onChange({ mcp_enabled: event.target.checked })}
          />
          <span>MCP exposure</span>
        </label>
        <label className="simurgh-chat__toggle">
          <input
            type="checkbox"
            checked={settings.action_circuit_breaker_enabled}
            disabled={busy}
            onChange={(event) => onChange({ action_circuit_breaker_enabled: event.target.checked })}
          />
          <span>Circuit breaker</span>
        </label>
        <label className="simurgh-chat__toggle">
          <input
            type="checkbox"
            checked={settings.always_confirm_before_action}
            disabled={busy}
            onChange={(event) => onChange({ always_confirm_before_action: event.target.checked })}
          />
          <span>Always confirm</span>
        </label>
        <label className="simurgh-chat__toggle">
          <input
            type="checkbox"
            checked={settings.web_search_enabled}
            disabled={busy || settings.provider !== "openai"}
            onChange={(event) => onChange({ web_search_enabled: event.target.checked })}
          />
          <span>Web search</span>
        </label>
      </div>
      <label className="simurgh-chat__field">
        <span>Provider</span>
        <select
          aria-label="Simurgh provider"
          value={settings.provider}
          disabled={busy}
          onChange={(event) => onChange({ provider: normalizeProvider(event.target.value) })}
        >
          <option value="mock">Mock</option>
          <option value="openai">OpenAI</option>
        </select>
      </label>
      <label className="simurgh-chat__field">
        <span>Model</span>
        {settings.provider === 'openai' ? (
          <>
            <input
              aria-label="OpenAI model"
              list="simurgh-openai-models"
              value={settings.openai_model}
              disabled={busy}
              onChange={(event) => onChange({ openai_model: event.target.value })}
            />
            <datalist id="simurgh-openai-models">
              {availableModels.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
            </datalist>
          </>
        ) : (
          <input aria-label="OpenAI model" value="mock-local" disabled readOnly />
        )}
      </label>
      <label className="simurgh-chat__field">
        <span>OpenAI API key</span>
        <input
          aria-label="OpenAI API key"
          type="password"
          value={credentialDraft}
          autoComplete="off"
          disabled={busy}
          placeholder={keyReady ? `Configured (${keyFingerprint || 'ready'})` : 'Paste key to store on GCS'}
          onChange={(event) => onCredentialDraftChange(event.target.value)}
        />
        <small className={keyReady ? 'is-ready' : 'is-warning'}>
          {keyReady ? 'Stored server-side; raw key is never returned.' : 'Key missing for OpenAI provider.'}
        </small>
      </label>
      <ActiveToolSummary toolList={activeTools} />
      <CandidateReviewSummary review={candidateReview} />
      <footer>
        <ActionIconButton
          icon={<FaSave />}
          label="Save Simurgh settings"
          onClick={onSave}
          disabled={busy}
        >
          {busy ? 'Saving' : 'Save'}
        </ActionIconButton>
      </footer>
    </aside>
  );
}

function ConversationList({ conversations, activeConversationId, onSelect, onNewChat, onClearChats, onDeleteChat }) {
  const [openActionsId, setOpenActionsId] = useState('');
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false);
  const historyRef = useRef(null);

  const closeActions = useCallback(() => {
    setOpenActionsId('');
    setHeaderMenuOpen(false);
  }, []);

  useEffect(() => {
    if (!openActionsId && !headerMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event) => {
      if (historyRef.current?.contains(event.target)) {
        return;
      }
      closeActions();
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        closeActions();
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [closeActions, headerMenuOpen, openActionsId]);

  return (
    <aside className="simurgh-chat__history" aria-label="Simurgh chat history" ref={historyRef}>
      <div className="simurgh-chat__history-header">
        <h2>Chats</h2>
        <div className="simurgh-chat__history-controls">
          <ActionIconButton icon={<FaPlus />} label="Start new Simurgh chat" size="sm" onClick={() => { closeActions(); onNewChat(); }} />
          <button
            type="button"
            className="simurgh-chat__history-overflow"
            aria-label="More chat history actions"
            title="More chat history actions"
            aria-haspopup="menu"
            aria-expanded={headerMenuOpen}
            onClick={() => {
              setOpenActionsId('');
              setHeaderMenuOpen((open) => !open);
            }}
          >
            <FaEllipsisH aria-hidden="true" />
          </button>
          {headerMenuOpen ? (
            <div className="simurgh-chat__history-menu simurgh-chat__history-menu--header" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={(event) => {
                  event.stopPropagation();
                  closeActions();
                  onClearChats();
                }}
              >
                <FaTrash aria-hidden="true" />
                Clear all chats
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <div className="simurgh-chat__history-list">
        {conversations.map((conversation) => {
          const active = conversation.id === activeConversationId;
          return (
            <div
              key={conversation.id}
              className={`simurgh-chat__history-item${active ? ' is-active' : ''}`}
            >
              <button
                type="button"
                className="simurgh-chat__history-select"
                onClick={() => { closeActions(); onSelect(conversation.id); }}
                aria-pressed={active}
              >
                <strong>{conversation.title}</strong>
                <span>{conversationPreview(conversation)}</span>
                <small>{formatConversationTime(conversation.updatedAt)}</small>
              </button>
              <button
                type="button"
                className="simurgh-chat__history-action"
                aria-label={`More actions for ${conversation.title}`}
                title="Chat actions"
                aria-haspopup="menu"
                aria-expanded={openActionsId === conversation.id}
                onClick={(event) => {
                  event.stopPropagation();
                  setHeaderMenuOpen(false);
                  setOpenActionsId((current) => (current === conversation.id ? '' : conversation.id));
                }}
              >
                <FaEllipsisH aria-hidden="true" />
              </button>
              {openActionsId === conversation.id ? (
                <div className="simurgh-chat__history-menu" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={(event) => {
                      event.stopPropagation();
                      closeActions();
                      onDeleteChat(conversation.id);
                    }}
                  >
                    <FaTrash aria-hidden="true" />
                    Delete chat
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function isSafeMarkdownHref(href = '') {
  if (!href) {
    return false;
  }
  if (href.startsWith('/')) {
    return isLinkableInternalHref(href);
  }
  try {
    const url = new URL(href);
    return url.protocol === 'https:';
  } catch (error) {
    return false;
  }
}

function isLinkableInternalHref(href = '') {
  if (!href.startsWith('/') || href.startsWith('//')) {
    return false;
  }
  if (LINKABLE_DOC_ROUTE_PATTERN.test(href)) {
    return true;
  }
  return LINKABLE_DASHBOARD_ROUTES.includes(href)
    || LINKABLE_DASHBOARD_ROUTE_PREFIXES.some((prefix) => href.startsWith(prefix));
}

function SafeMarkdownLink({ href, children }) {
  if (!isSafeMarkdownHref(href)) {
    return <span>{children}</span>;
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function splitTrailingLinkPunctuation(value) {
  const trailing = value.match(TRAILING_LINK_PUNCTUATION_PATTERN)?.[0] || '';
  if (!trailing) {
    return { core: value, trailing: '' };
  }
  return { core: value.slice(0, -trailing.length), trailing };
}

function hrefForAutoLinkToken(token) {
  const { core, trailing } = splitTrailingLinkPunctuation(String(token || ''));
  return {
    href: DOC_PATH_LINKS[core] || core,
    label: core,
    trailing,
  };
}

function renderPlainTextSegment(text, keyPrefix) {
  const value = String(text || '');
  if (!value) {
    return [];
  }

  const nodes = [];
  let lastIndex = 0;
  AUTO_LINK_PATTERN.lastIndex = 0;
  value.replace(AUTO_LINK_PATTERN, (match, token, offset) => {
    if (offset > lastIndex) {
      nodes.push(value.slice(lastIndex, offset));
    }
    const { href, label, trailing } = hrefForAutoLinkToken(token || match);
    const key = `${keyPrefix}-autolink-${offset}`;
    if (label && isSafeMarkdownHref(href)) {
      nodes.push(<SafeMarkdownLink key={key} href={href}>{label}</SafeMarkdownLink>);
    } else {
      nodes.push(label || match);
    }
    if (trailing) {
      nodes.push(trailing);
    }
    lastIndex = offset + match.length;
    return match;
  });

  if (lastIndex < value.length) {
    nodes.push(value.slice(lastIndex));
  }
  return nodes.length ? nodes : [value];
}

function renderInlineMarkdown(text, keyPrefix) {
  const value = String(text || '');
  const nodes = [];
  let lastIndex = 0;

  value.replace(
    INLINE_MARKDOWN_PATTERN,
    (match, _token, linkLabel, href, codeValue, strongValue, offset) => {
      if (offset > lastIndex) {
        nodes.push(...renderPlainTextSegment(value.slice(lastIndex, offset), `${keyPrefix}-text-${lastIndex}`));
      }
      const key = `${keyPrefix}-${offset}`;
      if (linkLabel && href) {
        nodes.push(
          <SafeMarkdownLink key={key} href={href}>
            {linkLabel}
          </SafeMarkdownLink>
        );
      } else if (codeValue) {
        nodes.push(<code key={key}>{codeValue}</code>);
      } else if (strongValue) {
        nodes.push(<strong key={key}>{strongValue}</strong>);
      }
      lastIndex = offset + match.length;
      return match;
    }
  );

  if (lastIndex < value.length) {
    nodes.push(...renderPlainTextSegment(value.slice(lastIndex), `${keyPrefix}-text-${lastIndex}`));
  }
  return nodes.length ? nodes : value;
}

async function writeClipboardText(value) {
  const text = String(value || '');
  if (!text) {
    return;
  }
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

function CopyButton({ text, label, className = '' }) {
  const [copied, setCopied] = useState(false);
  const copyText = useCallback(async () => {
    try {
      await writeClipboardText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch (error) {
      setCopied(false);
    }
  }, [text]);

  return (
    <button
      type="button"
      className={`simurgh-chat__copy-button ${className}`.trim()}
      aria-label={copied ? 'Copied' : label}
      title={copied ? 'Copied' : label}
      onClick={copyText}
    >
      <FaCopy aria-hidden="true" />
    </button>
  );
}

function parseTableCells(line, { dropEmpty = false } = {}) {
  let value = String(line || '').trim();
  if (value.startsWith('|')) {
    value = value.slice(1);
  }
  if (value.endsWith('|')) {
    value = value.slice(0, -1);
  }
  const cells = value.split('|').map((cell) => cell.trim());
  return dropEmpty ? cells.filter((cell) => cell.length > 0) : cells;
}

function isTableRow(line) {
  const value = String(line || '').trim();
  return value.startsWith('|') && value.endsWith('|') && parseTableCells(value).length >= 2;
}

function isTableDivider(line) {
  const cells = parseTableCells(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function canonicalTableRow(cells) {
  return `| ${cells.map((cell) => String(cell || '').trim()).join(' | ')} |`;
}

function expandCollapsedTableLine(line) {
  const value = String(line || '').trim();
  if (!value.startsWith('|') || !value.includes('---')) {
    return [line];
  }
  const dividerMatch = value.match(/\|(?:\s*:?-{3,}:?\s*\|)+/);
  if (!dividerMatch || !dividerMatch.index) {
    return [line];
  }

  const headerCells = parseTableCells(value.slice(0, dividerMatch.index), { dropEmpty: true });
  const dividerCells = parseTableCells(dividerMatch[0], { dropEmpty: true });
  const columnCount = dividerCells.length;
  if (columnCount < 2 || headerCells.length !== columnCount || !dividerCells.every((cell) => /^:?-{3,}:?$/.test(cell))) {
    return [line];
  }

  const bodyCells = parseTableCells(value.slice(dividerMatch.index + dividerMatch[0].length), { dropEmpty: true });
  const rows = [canonicalTableRow(headerCells), canonicalTableRow(Array(columnCount).fill('---'))];
  for (let index = 0; index < bodyCells.length; index += columnCount) {
    const row = bodyCells.slice(index, index + columnCount);
    if (row.length === columnCount) {
      rows.push(canonicalTableRow(row));
    }
  }
  return rows.length > 2 ? rows : [line];
}

function normalizeMarkdownContent(content) {
  return String(content || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .flatMap((line) => expandCollapsedTableLine(line))
    .join('\n');
}

function getFenceLanguage(line) {
  const language = String(line || '').trim().replace(/^```/, '').trim().split(/\s+/)[0] || '';
  return language.replace(/[^A-Za-z0-9_+.#-]/g, '').slice(0, 32);
}

function isBlockBoundary(lines, index) {
  const line = lines[index] || '';
  const trimmed = line.trim();
  if (!trimmed) {
    return true;
  }
  if (trimmed.startsWith('```') || /^#{1,4}\s+/.test(trimmed) || /^>\s+/.test(trimmed)) {
    return true;
  }
  if (/^\s*[-*]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
    return true;
  }
  return isTableRow(trimmed) && isTableDivider(lines[index + 1] || '');
}

function parseMarkdownBlocks(content) {
  const lines = normalizeMarkdownContent(content).split('\n');
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith('```')) {
      const codeLines = [];
      const language = getFenceLanguage(trimmed);
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ type: 'code', content: codeLines.join('\n'), language });
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      blocks.push({ type: 'heading', depth: heading[1].length, content: heading[2].trim() });
      index += 1;
      continue;
    }

    if (isTableRow(trimmed) && isTableDivider(lines[index + 1] || '')) {
      const headers = parseTableCells(trimmed);
      index += 2;
      const rows = [];
      while (index < lines.length && isTableRow(lines[index])) {
        const cells = parseTableCells(lines[index]);
        rows.push(headers.map((_, cellIndex) => cells[cellIndex] || ''));
        index += 1;
      }
      blocks.push({ type: 'table', headers, rows });
      continue;
    }

    const quote = trimmed.match(/^>\s+(.+)$/);
    if (quote) {
      const quoteLines = [];
      while (index < lines.length) {
        const quoteMatch = lines[index].trim().match(/^>\s?(.*)$/);
        if (!quoteMatch) {
          break;
        }
        quoteLines.push(quoteMatch[1].trim());
        index += 1;
      }
      blocks.push({ type: 'quote', content: quoteLines.join(' ') });
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const type = unordered ? 'ul' : 'ol';
      const items = [];
      while (index < lines.length) {
        const itemMatch = type === 'ul'
          ? lines[index].match(/^\s*[-*]\s+(.+)$/)
          : lines[index].match(/^\s*\d+[.)]\s+(.+)$/);
        if (!itemMatch) {
          break;
        }
        items.push(itemMatch[1].trim());
        index += 1;
      }
      blocks.push({ type, items });
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (index < lines.length && !isBlockBoundary(lines, index)) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: 'p', content: paragraphLines.join(' ') });
  }

  return blocks;
}

function CodeBlock({ content, language, blockId }) {
  return (
    <div className="simurgh-chat__code-block">
      <div className="simurgh-chat__code-header">
        <span>{language || 'code'}</span>
        <CopyButton text={content} label="Copy code snippet" className="simurgh-chat__copy-button--code" />
      </div>
      <pre><code className={language ? `language-${language}` : undefined}>{content}</code></pre>
    </div>
  );
}

function MarkdownTable({ headers, rows, blockId }) {
  return (
    <div className="simurgh-chat__table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header, headerIndex) => (
              <th key={`${blockId}-header-${headerIndex}`}>{renderInlineMarkdown(header, `${blockId}-header-${headerIndex}`)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${blockId}-row-${rowIndex}`}>
              {headers.map((_, cellIndex) => (
                <td key={`${blockId}-cell-${rowIndex}-${cellIndex}`}>
                  {renderInlineMarkdown(row[cellIndex] || '', `${blockId}-cell-${rowIndex}-${cellIndex}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MessageContent({ content }) {
  const blocks = parseMarkdownBlocks(content);
  return (
    <div className="simurgh-chat__markdown">
      {blocks.map((block, index) => {
        const blockId = `block-${index}`;
        if (block.type === 'heading') {
          const HeadingTag = block.depth <= 2 ? 'h2' : block.depth === 3 ? 'h3' : 'h4';
          return <HeadingTag key={`heading-${index}`}>{renderInlineMarkdown(block.content, `heading-${index}`)}</HeadingTag>;
        }
        if (block.type === 'code') {
          return <CodeBlock key={`code-${index}`} content={block.content} language={block.language} blockId={blockId} />;
        }
        if (block.type === 'table') {
          return <MarkdownTable key={`table-${index}`} headers={block.headers} rows={block.rows} blockId={blockId} />;
        }
        if (block.type === 'quote') {
          return <blockquote key={`quote-${index}`}>{renderInlineMarkdown(block.content, `quote-${index}`)}</blockquote>;
        }
        if (block.type === 'ul' || block.type === 'ol') {
          const ListTag = block.type;
          return (
            <ListTag key={`list-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`item-${index}-${itemIndex}`}>
                  {renderInlineMarkdown(item, `item-${index}-${itemIndex}`)}
                </li>
              ))}
            </ListTag>
          );
        }
        return <p key={`p-${index}`}>{renderInlineMarkdown(block.content, `p-${index}`)}</p>;
      })}
    </div>
  );
}

function MessageActivity({ progress = [], streaming = false }) {
  const [expanded, setExpanded] = useState(false);
  const steps = (Array.isArray(progress) ? progress : [])
    .map(normalizeProgressStep)
    .filter(Boolean)
    .filter((step, index, allSteps) => {
      if (!isGenericProgressStep(step)) {
        return true;
      }
      return !allSteps.some((candidate) => candidate !== step && isSpecificProgressStep(candidate));
    });
  const latestStep = steps.length
    ? steps[steps.length - 1]
    : (streaming ? { label: 'Thinking', stage: 'understanding', state: 'running', tool_id: '', key: 'thinking' } : null);
  if (!latestStep && !streaming) {
    return null;
  }
  const previousSteps = steps.slice(Math.max(0, steps.length - 3), -1);
  const detailSteps = steps.slice(0, -1);
  const currentState = latestStep?.state || (streaming ? 'running' : 'complete');
  return (
    <div className="simurgh-chat__activity" role={streaming ? 'status' : undefined} aria-live={streaming ? 'polite' : undefined}>
      <div className={`simurgh-chat__activity-current simurgh-chat__activity-current--${currentState}`}>
        <span className="simurgh-chat__thinking">{activityStatusText(currentState)}</span>
        {latestStep ? <span className="simurgh-chat__activity-label">{latestStep.label}</span> : null}
        {detailSteps.length > 0 ? (
          <button
            type="button"
            className="simurgh-chat__activity-toggle"
            aria-label={expanded ? 'Hide Simurgh activity details' : 'Show Simurgh activity details'}
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? <FaChevronDown aria-hidden="true" /> : <FaChevronRight aria-hidden="true" />}
          </button>
        ) : null}
      </div>
      {previousSteps.length && !expanded ? (
        <ol className="simurgh-chat__activity-list" aria-label="Recent Simurgh activity preview">
          {previousSteps.map((step, index) => {
            const state = step.state || 'complete';
            return (
              <li
                key={`${step.key}-${index}`}
                className={`simurgh-chat__activity-step simurgh-chat__activity-step--${state} simurgh-chat__activity-step--preview-${previousSteps.length - index}`}
                aria-label={`${step.label}: ${activityStateLabel(state)}`}
              >
                {activityStepIcon(state)}
                <span>{step.label}</span>
              </li>
            );
          })}
        </ol>
      ) : null}
      {expanded && detailSteps.length ? (
        <ol className="simurgh-chat__activity-details" aria-label="Simurgh activity details">
          {detailSteps.map((step, index) => {
            const state = step.state || 'complete';
            return (
              <li
                key={`detail-${step.key}-${index}`}
                className={`simurgh-chat__activity-detail simurgh-chat__activity-detail--${state}`}
                aria-label={`${step.label}: ${activityStateLabel(state)}`}
              >
                <span className="simurgh-chat__activity-detail-dot" aria-hidden="true" />
                <span>{step.label}</span>
              </li>
            );
          })}
        </ol>
      ) : null}
    </div>
  );
}

function MessageTrace({ message }) {
  const [open, setOpen] = useState(false);
  const trace = message.trace && typeof message.trace === 'object' && !Array.isArray(message.trace)
    ? message.trace
    : {};
  const summary = getTraceSummary(trace, message);
  const rows = buildTraceRows(trace, message);

  if (message.streaming || (!summary && !rows.length)) {
    return null;
  }

  return (
    <div className={`simurgh-chat__trace${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="simurgh-chat__trace-toggle"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? <FaChevronDown aria-hidden="true" /> : <FaChevronRight aria-hidden="true" />}
        <FaCheckCircle aria-hidden="true" />
        <span>{summary || 'Checked Simurgh context'}</span>
      </button>
      {open ? (
        <dl className="simurgh-chat__trace-details" aria-label="Simurgh response evidence">
          {rows.map((row) => (
            <div key={row.label} className="simurgh-chat__trace-row">
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function getPendingActionDraft(message) {
  const safety = message?.trace?.safety;
  const draft = safety?.action_draft;
  if (
    message?.role !== 'assistant'
    || message?.streaming
    || safety?.action_execution !== 'awaiting_confirmation'
    || !draft
    || typeof draft !== 'object'
    || !draft.draft_id
  ) {
    return null;
  }
  return draft;
}

function actionDraftRawPayload(draft = {}) {
  if (draft?.draft_type === 'flight_action' || draft?.tool_id === 'mds.flight.command.execute') {
    const payload = {
      ...(draft.command_payload && typeof draft.command_payload === 'object' ? draft.command_payload : {}),
    };
    if (draft.wait_condition) {
      payload.wait_condition = draft.wait_condition;
    }
    if (Array.isArray(draft.post_actions) && draft.post_actions.length) {
      payload.post_actions = draft.post_actions;
    }
    return Object.keys(payload).length ? payload : draft;
  }
  if (draft?.arguments && typeof draft.arguments === 'object') {
    return draft.arguments;
  }
  return draft || {};
}

function compactNumber(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '';
  }
  return Number.isInteger(numeric) ? String(numeric) : String(Number(numeric.toFixed(2)));
}

function actionTargetLabel(draft = {}) {
  const targets = Array.isArray(draft.target_drone_ids)
    ? draft.target_drone_ids.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  if (!targets.length) {
    return '';
  }
  return targets.length === 1 ? `Drone ${targets[0]}` : `Drones ${targets.join(', ')}`;
}

function actionDraftPlanSteps(draft = {}) {
  const displaySteps = Array.isArray(draft?.display_plan?.steps) ? draft.display_plan.steps : [];
  if (displaySteps.length) {
    return displaySteps.map((step) => ({
      title: String(step?.label || 'Action step'),
      kind: String(step?.kind || 'action'),
    }));
  }

  const primary = String(draft?.action_label || draft?.mission_name || draft?.tool_title || 'Run guarded action')
    .replace(/_/g, ' ');
  const steps = [{ title: primary, kind: 'action' }];
  (Array.isArray(draft?.post_actions) ? draft.post_actions : []).forEach((item) => {
    const seconds = compactNumber(item?.delay_seconds);
    const title = String(item?.action_label || item?.tool_title || (seconds ? `Wait ${seconds} seconds` : 'Action step'));
    steps.push({ title, kind: String(item?.type || 'action') });
  });
  return steps;
}

function getMessageActionRun(message) {
  const run = message?.trace?.safety?.action_run;
  return run && typeof run === 'object' && String(run.run_id || '').trim() ? run : null;
}

function getMessageActionRunId(message) {
  return String(getMessageActionRun(message)?.run_id || '').trim();
}

function actionRunStateLabel(state) {
  return {
    queued: 'Queued',
    running: 'Running',
    pause_requested: 'Pausing',
    paused: 'Paused',
    cancel_requested: 'Cancelling',
    succeeded: 'Complete',
    failed: 'Failed',
    blocked: 'Blocked',
    cancelled: 'Cancelled',
    interrupted: 'Interrupted',
  }[String(state || '').trim()] || 'Pending';
}

function actionRunStepState(value) {
  const state = String(value || '').trim().toLowerCase();
  if (['complete', 'completed', 'succeeded', 'success', 'terminal_success'].includes(state)) {
    return 'complete';
  }
  if (['failed', 'failure', 'error', 'terminal_non_success'].includes(state)) {
    return 'failed';
  }
  if (['timeout', 'timed_out'].includes(state)) {
    return 'timeout';
  }
  if (['blocked', 'rejected'].includes(state)) {
    return 'blocked';
  }
  if (['cancelled', 'canceled'].includes(state)) {
    return 'cancelled';
  }
  if (state === 'skipped') {
    return 'skipped';
  }
  if (state === 'paused') {
    return 'paused';
  }
  if (['running', 'monitoring', 'submitted', 'accepted'].includes(state)) {
    return 'running';
  }
  return 'pending';
}

function actionRunStepView(run = {}, events = []) {
  const steps = actionDraftPlanSteps(run.plan || {});
  const states = steps.map(() => 'pending');
  const runState = String(run.terminal ? run.state : (run.control_state || run.state || ''));
  (Array.isArray(events) ? events : []).forEach((event) => {
    const payload = event?.payload && typeof event.payload === 'object' ? event.payload : {};
    const index = Number(payload.step_index);
    if (!Number.isInteger(index) || index < 1 || index > states.length) {
      return;
    }
    states[index - 1] = actionRunStepState(payload.state);
  });

  const currentStep = Math.max(0, Number(run.current_step) || 0);
  if (runState === 'succeeded') {
    states.fill('complete');
  } else {
    states.forEach((state, index) => {
      if (state === 'pending' && index + 1 < currentStep) {
        states[index] = 'complete';
      }
    });
    if (currentStep > 0 && currentStep <= states.length && states[currentStep - 1] === 'pending') {
      states[currentStep - 1] = runState === 'paused' ? 'paused' : ACTIVE_ACTION_RUN_STATES.has(runState) ? 'running' : states[currentStep - 1];
    }
  }
  if (['cancelled', 'blocked', 'interrupted'].includes(runState)) {
    states.forEach((state, index) => {
      if (state === 'pending' && index + 1 > currentStep) {
        states[index] = runState === 'cancelled' ? 'cancelled' : 'skipped';
      }
    });
  }
  return steps.map((step, index) => ({ ...step, state: states[index] }));
}

function latestActionRunActivity(events = []) {
  const candidates = (Array.isArray(events) ? events : []).filter((event) => (
    event?.payload && typeof event.payload === 'object' && String(event.payload.label || '').trim()
  ));
  return candidates.length ? candidates[candidates.length - 1].payload : null;
}

function PendingActionPlan({ draft }) {
  const steps = actionDraftPlanSteps(draft);
  const target = String(draft?.display_plan?.target || actionTargetLabel(draft) || 'Guarded GCS operation');
  const title = String(draft?.display_plan?.title || 'Review action');
  return (
    <section className="simurgh-chat__action-plan" aria-label="Action plan awaiting confirmation">
      <header className="simurgh-chat__action-plan-header">
        <FaShieldAlt aria-hidden="true" />
        <div>
          <strong>{title}</strong>
          <span>{target}</span>
        </div>
      </header>
      <ol className="simurgh-chat__action-plan-steps">
        {steps.map((step, index) => (
          <li key={`${draft?.draft_id || 'draft'}-${index}-${step.title}`}>
            <span className="simurgh-chat__action-plan-index">{index + 1}</span>
            <span>{step.title}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ActionResultSummary({ message }) {
  const safety = message?.trace?.safety;
  if (
    message?.role !== 'assistant'
    || message?.streaming
    || safety?.action_execution !== 'submitted'
    || String(safety?.action_run?.run_id || '').trim()
  ) {
    return null;
  }
  const monitor = safety?.action_monitor && typeof safety.action_monitor === 'object'
    ? safety.action_monitor
    : {};
  const postActions = Array.isArray(safety?.post_action_results) ? safety.post_action_results : [];
  const hasVerificationResult = (value) => value
    && typeof value === 'object'
    && Object.prototype.hasOwnProperty.call(value, 'verified');
  const completionVerification = [...postActions]
    .reverse()
    .map((item) => item?.completion_verification)
    .find(hasVerificationResult)
    || (hasVerificationResult(monitor?.completion_verification)
      ? monitor.completion_verification
      : null);
  const failed = monitor.success === false || postActions.some((item) => item?.is_error);
  const timedOut = Boolean(monitor.timed_out) || postActions.some((item) => /timeout/i.test(String(item?.status || '')));
  const unverifiedFinalState = Boolean(completionVerification && !completionVerification.verified);
  const monitored = Object.keys(monitor).length > 0 || postActions.length > 0;
  const title = timedOut
    ? 'Monitoring timed out'
    : failed
      ? 'Sequence stopped'
      : unverifiedFinalState
        ? 'Final state not confirmed'
      : monitored
        ? 'Command sequence complete'
        : 'Action submitted';
  let detail = postActions.length
    ? `${postActions.filter((item) => !item?.is_error).length + (monitor.success === true ? 1 : 0)} of ${postActions.length + 1} steps completed`
    : monitor.success === true ? 'Command reached a successful terminal state' : 'Accepted by the GCS';
  if (completionVerification?.verified) {
    detail += ' · final disarm confirmed';
  } else if (unverifiedFinalState) {
    detail += ' · final disarm not confirmed';
  }
  return (
    <div className={`simurgh-chat__action-result simurgh-chat__action-result--${failed || timedOut || unverifiedFinalState ? 'warning' : 'success'}`}>
      {failed || timedOut || unverifiedFinalState ? <FaExclamationTriangle aria-hidden="true" /> : <FaCheckCircle aria-hidden="true" />}
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
    </div>
  );
}

function PendingActionDraftRawPayload({ draft }) {
  const [open, setOpen] = useState(false);
  const rawPayload = actionDraftRawPayload(draft);
  const rawJson = JSON.stringify(rawPayload, null, 2);
  if (!rawJson || rawJson === '{}') {
    return null;
  }
  return (
    <div className={`simurgh-chat__action-draft-raw${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="simurgh-chat__action-draft-raw-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <FaChevronDown aria-hidden="true" /> : <FaChevronRight aria-hidden="true" />}
        <span>Raw action JSON</span>
      </button>
      {open ? <CodeBlock content={rawJson} language="json" blockId={`draft-raw-${draft?.draft_id || 'payload'}`} /> : null}
    </div>
  );
}

function ActionRunCard({ run, events = [], onControl, controlBusy = '' }) {
  const runId = String(run?.run_id || '').trim();
  if (!runId) {
    return null;
  }
  const steps = actionRunStepView(run, events);
  const activity = latestActionRunActivity(events);
  const state = String(run.terminal ? run.state : (run.control_state || run.state || 'queued'));
  const active = ACTIVE_ACTION_RUN_STATES.has(state);
  const totalSteps = Math.max(1, Number(run.total_steps) || steps.length || 1);
  const currentStep = Math.min(totalSteps, Math.max(0, Number(run.current_step) || 0));
  const completedSteps = state === 'succeeded'
    ? totalSteps
    : steps.filter((step) => step.state === 'complete').length;
  const progressValue = state === 'succeeded'
    ? totalSteps
    : Math.max(completedSteps, currentStep > 0 ? currentStep - (active ? 1 : 0) : 0);
  const title = String(run?.plan?.display_plan?.title || (steps.length > 1 ? 'Action sequence' : 'Guarded action'));
  const target = String(run?.plan?.display_plan?.target || actionTargetLabel(run.plan || {}) || 'GCS operation');
  const currentLabel = String(activity?.label || run.summary || actionRunStateLabel(state));
  const busy = controlBusy === runId;
  const canResume = state === 'paused' || state === 'pause_requested';
  const canPause = state === 'queued' || state === 'running';
  const tone = ['failed', 'blocked', 'interrupted'].includes(state)
    ? 'danger'
    : state === 'cancelled' ? 'warning' : state === 'succeeded' ? 'success' : 'active';

  return (
    <section className={`simurgh-chat__action-run simurgh-chat__action-run--${tone}`} aria-label={`Action run ${runId}`}>
      <header className="simurgh-chat__action-run-header">
        <div className="simurgh-chat__action-run-title">
          {tone === 'danger' || tone === 'warning'
            ? <FaExclamationTriangle aria-hidden="true" />
            : <FaCheckCircle aria-hidden="true" />}
          <div>
            <strong>{title}</strong>
            <span>{target}</span>
          </div>
        </div>
        <span className={`simurgh-chat__action-run-state simurgh-chat__action-run-state--${state}`}>
          {actionRunStateLabel(state)}
        </span>
      </header>
      <div className="simurgh-chat__action-run-progress-row">
        <div
          className="simurgh-chat__action-run-progress"
          role="progressbar"
          aria-label={`${title} progress`}
          aria-valuemin="0"
          aria-valuemax={totalSteps}
          aria-valuenow={Math.min(totalSteps, Math.max(0, progressValue))}
        >
          <span style={{ width: `${Math.min(100, Math.max(0, (progressValue / totalSteps) * 100))}%` }} />
        </div>
        <span>{Math.min(totalSteps, Math.max(0, completedSteps))}/{totalSteps}</span>
      </div>
      <div className="simurgh-chat__action-run-current" role={active ? 'status' : undefined} aria-live={active ? 'polite' : undefined}>
        <span className={`simurgh-chat__action-run-pulse${active ? ' is-active' : ''}`} aria-hidden="true" />
        <span>{currentLabel}</span>
      </div>
      <ol className="simurgh-chat__action-run-steps" aria-label="Action sequence progress">
        {steps.map((step, index) => (
          <li key={`${runId}-step-${index}`} className={`simurgh-chat__action-run-step simurgh-chat__action-run-step--${step.state}`}>
            <span className="simurgh-chat__action-run-step-icon" aria-hidden="true">
              {step.state === 'complete' ? <FaCheckCircle /> : index + 1}
            </span>
            <span>{step.title}</span>
            <small>{activityStateLabel(step.state)}</small>
          </li>
        ))}
      </ol>
      {active ? (
        <div className="simurgh-chat__action-run-controls" aria-label="Active action run controls">
          {canPause ? (
            <button
              type="button"
              disabled={busy}
              title="Pause after the current dispatched step finishes"
              onClick={() => onControl?.(runId, 'pause_after_current_step')}
            >
              <FaPause aria-hidden="true" />
              <span>Pause after step</span>
            </button>
          ) : null}
          {canResume ? (
            <button
              type="button"
              disabled={busy}
              title="Resume the remaining approved steps"
              onClick={() => onControl?.(runId, 'resume')}
            >
              <FaPlay aria-hidden="true" />
              <span>Resume</span>
            </button>
          ) : null}
          <button
            type="button"
            className="simurgh-chat__action-run-cancel"
            disabled={busy || state === 'cancel_requested'}
            title="Let the current dispatched step finish, then cancel the remaining steps"
            onClick={() => onControl?.(runId, 'cancel_remaining')}
          >
            <FaStop aria-hidden="true" />
            <span>Cancel remaining</span>
          </button>
        </div>
      ) : null}
      <PendingActionDraftRawPayload draft={run.plan || {}} />
    </section>
  );
}

function MessageBubble({
  message,
  onSubmitPrompt,
  submitting = false,
  actionControlsEnabled = false,
  actionRun = null,
  actionRunEvents = [],
  onActionRunControl,
  actionRunControlBusy = '',
}) {
  const roleLabel = message.role === 'assistant' ? 'Simurgh' : 'You';
  const copyLabel = message.role === 'assistant' ? 'Copy Simurgh message' : 'Copy your message';
  const pendingDraft = actionControlsEnabled ? getPendingActionDraft(message) : null;
  return (
    <article className={`simurgh-chat__message simurgh-chat__message--${message.role}${message.streaming ? ' simurgh-chat__message--streaming' : ''}`}>
      <div className="simurgh-chat__avatar" aria-hidden="true">
        {message.role === 'assistant' ? <SimurghMark /> : <FaUserShield />}
      </div>
      <div className="simurgh-chat__bubble">
        <div className="simurgh-chat__bubble-header">
          <span>{roleLabel}</span>
          <CopyButton text={message.content} label={copyLabel} className="simurgh-chat__copy-button--message" />
        </div>
        {message.role === 'assistant' ? <MessageActivity progress={message.progress || []} streaming={Boolean(message.streaming)} /> : null}
        {message.role === 'assistant' ? <MessageTrace message={message} /> : null}
        {pendingDraft ? <PendingActionPlan draft={pendingDraft} /> : null}
        {actionRun ? (
          <ActionRunCard
            run={actionRun}
            events={actionRunEvents}
            onControl={onActionRunControl}
            controlBusy={actionRunControlBusy}
          />
        ) : null}
        {message.role === 'assistant' ? <ActionResultSummary message={message} /> : null}
        {message.content ? <MessageContent content={message.content} /> : null}
        {pendingDraft ? (
          <>
            <PendingActionDraftRawPayload draft={pendingDraft} />
            <div className="simurgh-chat__action-draft-controls" aria-label="Pending guarded action controls">
              <button
                type="button"
                className="simurgh-chat__action-draft-button simurgh-chat__action-draft-button--confirm"
                disabled={submitting}
                onClick={() => onSubmitPrompt?.(`confirm action ${pendingDraft.draft_id}`)}
              >
                <FaCheckCircle aria-hidden="true" />
                <span>Confirm</span>
              </button>
              <button
                type="button"
                className="simurgh-chat__action-draft-button"
                disabled={submitting}
                onClick={() => onSubmitPrompt?.(`cancel action ${pendingDraft.draft_id}`)}
              >
                <FaTimes aria-hidden="true" />
                <span>Reject</span>
              </button>
            </div>
          </>
        ) : null}
      </div>
    </article>
  );
}

function EmptyChat({ onPickPrompt }) {
  return (
    <div className="simurgh-chat__empty">
      <SimurghMark className="simurgh-chat__mark--empty" />
      <h2>Simurgh</h2>
      <div className="simurgh-chat__starters" aria-label="Prompt starters">
        {STARTERS.map((prompt) => (
          <button key={prompt} type="button" onClick={() => onPickPrompt(prompt)}>
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function SimurghOperatorPage() {
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsNotice, setSettingsNotice] = useState(null);
  const [candidateReview, setCandidateReview] = useState(null);
  const [activeTools, setActiveTools] = useState(null);
  const [credentialDraft, setCredentialDraft] = useState('');
  const [conversations, setConversations] = useState(() => {
    const stored = readStoredConversations();
    return stored.length ? stored : [newConversation()];
  });
  const [activeConversationId, setActiveConversationId] = useState(() => readStoredConversations()[0]?.id || '');
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [chatError, setChatError] = useState('');
  const [actionRuns, setActionRuns] = useState({});
  const [actionRunEvents, setActionRunEvents] = useState({});
  const [actionRunControlBusy, setActionRunControlBusy] = useState('');
  const abortRef = useRef(null);
  const actionRunStreamsRef = useRef(new Map());
  const actionRunCursorsRef = useRef(new Map());
  const hydratedActionRunsRef = useRef(new Set());
  const transcriptRef = useRef(null);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) || conversations[0],
    [activeConversationId, conversations]
  );

  useEffect(() => {
    if (!activeConversationId && conversations[0]?.id) {
      setActiveConversationId(conversations[0].id);
    }
  }, [activeConversationId, conversations]);

  useEffect(() => {
    writeStoredConversations(conversations);
  }, [conversations]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) {
      return;
    }
    transcript.scrollTop = transcript.scrollHeight;
  }, [activeConversation?.updatedAt, submitting]);

  const loadCandidateReview = useCallback(async () => {
    try {
      const response = await getSimurghToolCandidatesResponse({ limit: 8 });
      setCandidateReview(response?.data || null);
    } catch (error) {
      setCandidateReview(null);
    }
  }, []);

  const loadActiveTools = useCallback(async () => {
    try {
      const response = await getSimurghToolsResponse({ includeExcluded: false });
      setActiveTools(response?.data || null);
    } catch (error) {
      setActiveTools(null);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setPageError('');
    try {
      const runtimeResponse = await getSimurghRuntimeSettingsResponse();
      const runtimeStatus = runtimeResponse?.data || null;
      setStatus(runtimeStatus);
      setSettings(normalizeSettings(runtimeStatus));
    } catch (runtimeError) {
      try {
        const statusResponse = await getSimurghStatusResponse();
        const legacyStatus = statusResponse?.data || null;
        setStatus(legacyStatus);
        setSettings(normalizeSettings(legacyStatus));
        setPageError(normalizeError(runtimeError, 'Runtime settings are unavailable; showing status only.'));
      } catch (statusError) {
        setPageError(normalizeError(statusError, 'Could not load Simurgh status.'));
      }
    } finally {
      await Promise.all([loadCandidateReview(), loadActiveTools()]);
      setLoading(false);
    }
  }, [loadActiveTools, loadCandidateReview]);

  useEffect(() => {
    loadStatus();
    return () => abortRef.current?.abort();
  }, [loadStatus]);

  const updateConversation = useCallback((conversationId, updater) => {
    setConversations((current) => current.map((conversation) => (
      conversation.id === conversationId ? updater(conversation) : conversation
    )));
  }, []);

  const updateConversationMessage = useCallback((conversationId, messageId, updater) => {
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      updatedAt: nowIso(),
      messages: conversation.messages.map((message) => (
        message.id === messageId ? updater(message) : message
      )),
    }));
  }, [updateConversation]);

  const upsertActionRun = useCallback((candidate) => {
    const runId = String(candidate?.run_id || '').trim();
    if (!runId) {
      return null;
    }
    setActionRuns((current) => ({
      ...current,
      [runId]: {
        ...(current[runId] || {}),
        ...candidate,
        plan: candidate?.plan || current[runId]?.plan || {},
      },
    }));
    return runId;
  }, []);

  const appendActionRunEvent = useCallback((runId, event) => {
    const eventId = Number(event?.id);
    if (!runId || !Number.isFinite(eventId)) {
      return;
    }
    actionRunCursorsRef.current.set(runId, Math.max(Number(actionRunCursorsRef.current.get(runId) || 0), eventId));
    setActionRunEvents((current) => {
      const existing = Array.isArray(current[runId]) ? current[runId] : [];
      if (existing.some((item) => Number(item?.id) === eventId)) {
        return current;
      }
      return {
        ...current,
        [runId]: [...existing, event]
          .sort((left, right) => Number(left?.id || 0) - Number(right?.id || 0))
          .slice(-500),
      };
    });
  }, []);

  const applyActionRunStreamEvent = useCallback((runId, streamEvent, data) => {
    if (streamEvent === 'run_snapshot') {
      upsertActionRun(data?.run);
      return;
    }
    if (!data || typeof data !== 'object') {
      return;
    }
    appendActionRunEvent(runId, data);
    const payload = data.payload && typeof data.payload === 'object' ? data.payload : {};
    const state = ACTION_RUN_STATES.has(String(payload.state || '')) ? String(payload.state) : '';
    const stepIndex = Number(payload.step_index);
    setActionRuns((current) => {
      const existing = current[runId];
      if (!existing) {
        return current;
      }
      const effectiveState = (
        state
        && !TERMINAL_ACTION_RUN_STATES.has(state)
        && ['pause_requested', 'cancel_requested'].includes(String(existing.control_state || ''))
      ) ? String(existing.control_state) : state;
      return {
        ...current,
        [runId]: {
          ...existing,
          ...(effectiveState ? { state: effectiveState, terminal: TERMINAL_ACTION_RUN_STATES.has(effectiveState) } : {}),
          ...(Number.isInteger(stepIndex) && stepIndex > 0 ? { current_step: stepIndex } : {}),
          ...(Number(payload.step_count) > 0 ? { total_steps: Number(payload.step_count) } : {}),
          ...(payload.summary || payload.label ? { summary: String(payload.summary || payload.label) } : {}),
        },
      };
    });
  }, [appendActionRunEvent, upsertActionRun]);

  const trackActionRun = useCallback((candidate) => {
    const runId = typeof candidate === 'string'
      ? String(candidate).trim()
      : String(candidate?.run_id || '').trim();
    const state = typeof candidate === 'object' ? String(candidate?.state || '') : '';
    if (!runId || TERMINAL_ACTION_RUN_STATES.has(state) || actionRunStreamsRef.current.has(runId)) {
      return;
    }
    const controller = new AbortController();
    actionRunStreamsRef.current.set(runId, controller);
    const after = Number(actionRunCursorsRef.current.get(runId) || 0);
    streamSimurghActionRunEventsResponse(runId, { after }, {
      signal: controller.signal,
      onEvent: ({ event, data }) => applyActionRunStreamEvent(runId, event, data),
    })
      .then(async () => {
        const response = await getSimurghActionRunResponse(runId);
        upsertActionRun(response?.data);
      })
      .catch(async (error) => {
        if (error?.name === 'AbortError' || error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') {
          return;
        }
        try {
          const response = await getSimurghActionRunResponse(runId);
          upsertActionRun(response?.data);
        } catch (refreshError) {
          // Periodic active-run discovery retries transient stream and snapshot failures.
        }
      })
      .finally(() => {
        if (actionRunStreamsRef.current.get(runId) === controller) {
          actionRunStreamsRef.current.delete(runId);
        }
      });
  }, [applyActionRunStreamEvent, upsertActionRun]);

  const registerActionRunFromTurn = useCallback((turn) => {
    const run = turn?.trace?.safety?.action_run;
    const runId = upsertActionRun(run);
    if (runId && !run?.terminal) {
      trackActionRun(run);
    }
  }, [trackActionRun, upsertActionRun]);

  useEffect(() => {
    let mounted = true;
    const actionRunStreams = actionRunStreamsRef.current;
    const refreshActiveRuns = async () => {
      try {
        const response = await getSimurghActionRunsResponse({ actor: DASHBOARD_ACTOR, activeOnly: true, limit: 20 });
        if (!mounted) {
          return;
        }
        const runs = Array.isArray(response?.data?.runs) ? response.data.runs : [];
        runs.forEach((run) => {
          upsertActionRun(run);
          trackActionRun(run);
        });
      } catch (error) {
        // Chat remains available; the next refresh retries action-run discovery.
      }
    };
    refreshActiveRuns();
    const intervalId = window.setInterval(refreshActiveRuns, 5000);
    return () => {
      mounted = false;
      window.clearInterval(intervalId);
      actionRunStreams.forEach((controller) => controller.abort());
      actionRunStreams.clear();
    };
  }, [trackActionRun, upsertActionRun]);

  const linkedActionRunIds = useMemo(() => Array.from(new Set(
    conversations.flatMap((conversation) => (
      (Array.isArray(conversation.messages) ? conversation.messages : [])
        .map(getMessageActionRunId)
        .filter(Boolean)
    ))
  )), [conversations]);

  useEffect(() => {
    linkedActionRunIds.forEach((runId) => {
      if (hydratedActionRunsRef.current.has(runId)) {
        return;
      }
      hydratedActionRunsRef.current.add(runId);
      getSimurghActionRunResponse(runId)
        .then((response) => {
          const run = response?.data;
          upsertActionRun(run);
          if (run && !run.terminal) {
            trackActionRun(run);
          }
        })
        .catch(() => {
          hydratedActionRunsRef.current.delete(runId);
        });
    });
  }, [linkedActionRunIds, trackActionRun, upsertActionRun]);

  const handleNewChat = useCallback(() => {
    const conversation = newConversation();
    setConversations((current) => [conversation, ...current].slice(0, MAX_CONVERSATIONS));
    setActiveConversationId(conversation.id);
    setDraft('');
    setChatError('');
  }, []);

  const handleClearChats = useCallback(() => {
    const conversation = newConversation();
    clearStoredConversations();
    setConversations([conversation]);
    setActiveConversationId(conversation.id);
    setDraft('');
    setChatError('');
  }, []);

  const handleDeleteChat = useCallback((conversationId) => {
    setConversations((current) => {
      const remaining = current.filter((conversation) => conversation.id !== conversationId);
      return remaining.length ? remaining : [newConversation()];
    });
    setActiveConversationId((activeId) => (activeId === conversationId ? '' : activeId));
    setDraft('');
    setChatError('');
  }, []);

  const handleSettingsChange = useCallback((patch) => {
    setSettings((current) => {
      const next = { ...current, ...patch };
      next.provider = normalizeProvider(next.provider);
      if (!next.openai_model || next.openai_model === 'mock-local') {
        next.openai_model = DEFAULT_MODEL;
      }
      return next;
    });
    setSettingsNotice(null);
  }, []);

  const saveSettings = useCallback(async () => {
    setSettingsBusy(true);
    setSettingsNotice(null);
    try {
      if (credentialDraft.trim()) {
        await updateSimurghProviderCredentialsResponse({
          openai_api_key: credentialDraft.trim(),
          set_provider_openai: settings.provider === 'openai',
          openai_model: settings.openai_model,
        });
      }
      const response = await updateSimurghRuntimeSettingsResponse(settings);
      const nextStatus = response?.data || null;
      setStatus(nextStatus);
      setSettings(normalizeSettings(nextStatus));
      setCredentialDraft('');
      setSettingsNotice({
        tone: 'success',
        title: 'Settings applied',
        detail: credentialDraft.trim()
          ? 'Settings were saved and the OpenAI key was stored server-side.'
          : 'Simurgh runtime settings were hot-applied and saved to the GCS environment.',
      });
    } catch (error) {
      setSettingsNotice({
        tone: 'danger',
        title: 'Settings not saved',
        detail: normalizeError(error, 'Could not update Simurgh settings.'),
      });
    } finally {
      setSettingsBusy(false);
    }
  }, [credentialDraft, settings]);

  const handleActionRunControl = useCallback(async (runId, action) => {
    const stableRunId = String(runId || '').trim();
    if (!stableRunId || actionRunControlBusy) {
      return;
    }
    setActionRunControlBusy(stableRunId);
    setChatError('');
    try {
      const response = await controlSimurghActionRunResponse(stableRunId, {
        actor: DASHBOARD_ACTOR,
        action,
        reason: 'Operator control from Simurgh dashboard',
        control_id: `ctl-dashboard-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      });
      const run = response?.data;
      upsertActionRun(run);
      if (run && !run.terminal) {
        trackActionRun(run);
      }
    } catch (error) {
      setChatError(normalizeError(error, 'Could not update the active action run.'));
    } finally {
      setActionRunControlBusy('');
    }
  }, [actionRunControlBusy, trackActionRun, upsertActionRun]);

  const submitMessage = useCallback(async (rawMessage) => {
    const message = String(rawMessage || '').trim();
    if (!message || submitting || !activeConversation) {
      return;
    }

    const conversationId = activeConversation.id;
    const assistantMessageId = `assistant-stream-${Date.now()}`;
    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      createdAt: nowIso(),
    };
    const assistantPlaceholder = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: nowIso(),
      streaming: true,
      progress: [{ stage: 'understanding', state: 'running', label: 'Reading request' }],
    };
    setDraft('');
    setSubmitting(true);
    setChatError('');
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      title: conversation.messages.length ? conversation.title : titleFromMessage(message),
      updatedAt: nowIso(),
      messages: [...conversation.messages, userMessage, assistantPlaceholder],
    }));

    try {
      const controller = new AbortController();
      abortRef.current = controller;
      const payload = {
        actor: DASHBOARD_ACTOR,
        message,
        metadata: { source: 'simurgh-dashboard' },
      };
      if (activeConversation.backendSessionId) {
        payload.session_id = activeConversation.backendSessionId;
      }

      let finalData = null;
      try {
        const response = await streamSimurghAssistantTurnResponse(payload, {
          signal: controller.signal,
          onEvent: ({ event: streamEvent, data }) => {
            if (streamEvent === 'progress') {
              updateConversationMessage(conversationId, assistantMessageId, (currentMessage) => ({
                ...currentMessage,
                progress: appendProgressStep(currentMessage.progress || [], data),
              }));
            } else if (streamEvent === 'delta') {
              const text = String(data?.text || '');
              if (text) {
                updateConversationMessage(conversationId, assistantMessageId, (currentMessage) => ({
                  ...currentMessage,
                  content: `${currentMessage.content || ''}${text}`,
                }));
              }
            } else if (streamEvent === 'final') {
              finalData = data || {};
              registerActionRunFromTurn(finalData);
              const sessionId = finalData.session?.id;
              if (sessionId) {
                updateConversation(conversationId, (conversation) => ({
                  ...conversation,
                  backendSessionId: sessionId,
                  updatedAt: nowIso(),
                }));
              }
              updateConversationMessage(conversationId, assistantMessageId, (currentMessage) => ({
                ...currentMessage,
                id: finalData.id || currentMessage.id,
                content: finalData.content || currentMessage.content || 'No Simurgh response content was returned.',
                createdAt: finalData.created_at || currentMessage.createdAt || nowIso(),
                provider: finalData.provider,
                model: finalData.model,
                trace: finalData.trace || currentMessage.trace,
                context_resources: finalData.context_resources || currentMessage.context_resources || [],
                blocked_intents: finalData.blocked_intents || currentMessage.blocked_intents || [],
                safety_notes: finalData.safety_notes || currentMessage.safety_notes || [],
                audit_event_id: finalData.audit_event_id || currentMessage.audit_event_id,
                streaming: false,
                progress: finalizeProgressSteps(currentMessage.progress || [], finalData),
              }));
            } else if (streamEvent === 'done') {
              const sessionId = String(data?.session_id || '');
              if (sessionId) {
                updateConversation(conversationId, (conversation) => ({
                  ...conversation,
                  backendSessionId: sessionId,
                  updatedAt: nowIso(),
                }));
              }
            }
          },
        });
        finalData = response?.data || finalData || {};
      } catch (streamError) {
        const canFallback = /not available|not readable/i.test(streamError?.message || '');
        if (!canFallback) {
          throw streamError;
        }
        const response = await createSimurghAssistantTurnResponse(payload, { signal: controller.signal });
        finalData = response?.data || {};
      }

      updateConversation(conversationId, (conversation) => ({
        ...conversation,
        backendSessionId: finalData.session?.id || conversation.backendSessionId,
        updatedAt: nowIso(),
        messages: conversation.messages.map((currentMessage) => (
          currentMessage.id === assistantMessageId || currentMessage.id === finalData.id
            ? {
              ...currentMessage,
              id: finalData.id || currentMessage.id,
              role: 'assistant',
              content: finalData.content || currentMessage.content || 'No Simurgh response content was returned.',
              createdAt: finalData.created_at || currentMessage.createdAt || nowIso(),
              provider: finalData.provider,
              model: finalData.model,
              trace: finalData.trace || currentMessage.trace,
              context_resources: finalData.context_resources || currentMessage.context_resources || [],
              blocked_intents: finalData.blocked_intents || currentMessage.blocked_intents || [],
              safety_notes: finalData.safety_notes || currentMessage.safety_notes || [],
              audit_event_id: finalData.audit_event_id || currentMessage.audit_event_id,
              streaming: false,
              progress: finalizeProgressSteps(currentMessage.progress || [], finalData),
            }
            : currentMessage
        )),
      }));
      registerActionRunFromTurn(finalData);
      await loadStatus();
    } catch (error) {
      if (error.name === 'AbortError' || error.name === 'CanceledError' || error.code === 'ERR_CANCELED') {
        updateConversationMessage(conversationId, assistantMessageId, (currentMessage) => ({
          ...currentMessage,
          streaming: false,
          progress: stopProgressSteps(currentMessage.progress || []),
          content: currentMessage.content || 'Response stopped.',
        }));
      } else {
        const detail = normalizeError(error);
        setChatError(detail);
        updateConversationMessage(conversationId, assistantMessageId, (currentMessage) => ({
          ...currentMessage,
          streaming: false,
          progress: appendProgressStep(currentMessage.progress || [], { stage: 'error', state: 'error', label: 'Request failed' }),
          content: detail,
        }));
      }
    } finally {
      setSubmitting(false);
      abortRef.current = null;
    }
  }, [activeConversation, loadStatus, registerActionRunFromTurn, submitting, updateConversation, updateConversationMessage]);

  const handleSubmit = useCallback((event) => {
    event.preventDefault();
    submitMessage(draft);
  }, [draft, submitMessage]);

  const stopRequest = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const activeMessages = activeConversation?.messages || [];
  const latestMessageId = activeMessages[activeMessages.length - 1]?.id || '';
  const activeMessageActionRunIds = new Set(activeMessages.map(getMessageActionRunId).filter(Boolean));
  const unlinkedActiveRuns = Object.values(actionRuns)
    .filter((run) => ACTIVE_ACTION_RUN_STATES.has(String(run?.state || '')))
    .filter((run) => !activeMessageActionRunIds.has(String(run?.run_id || '')))
    .sort((left, right) => String(left?.created_at || '').localeCompare(String(right?.created_at || '')));
  const canSend = draft.trim().length > 0 && !submitting && Boolean(status?.agent_enabled);
  const subtitle = status
    ? `${status.provider || status.assistant_provider || 'mock'} / ${status.openai_model || status.model || status.assistant_model || 'mock-local'}`
    : loading ? 'Loading runtime' : 'Runtime unavailable';

  return (
    <PageShell
      className="simurgh-chat-page"
      eyebrow="Simurgh"
      title="Operator Chat"
      subtitle={subtitle}
      icon={<SimurghMark className="simurgh-chat__mark--shell" />}
      status={<SafetyChips status={status} />}
      actions={(
        <ActionIconButton
          icon={<FaCog />}
          label="Open Simurgh settings"
          active={settingsOpen}
          onClick={() => setSettingsOpen((open) => !open)}
        />
      )}
    >
      <div className="simurgh-chat__notice-slot">
        {pageError ? <OperatorNotice tone="warning" title="Runtime notice">{pageError}</OperatorNotice> : null}
      </div>
      <section className="simurgh-chat">
        <ConversationList
          conversations={conversations}
          activeConversationId={activeConversation?.id || ''}
          onSelect={setActiveConversationId}
          onNewChat={handleNewChat}
          onClearChats={handleClearChats}
          onDeleteChat={handleDeleteChat}
        />
        <section className="simurgh-chat__main" aria-label="Simurgh assistant">
          <div className="simurgh-chat__transcript" ref={transcriptRef}>
            {activeMessages.length === 0 ? <EmptyChat onPickPrompt={setDraft} /> : null}
            {activeMessages.map((message) => {
              const embeddedRun = getMessageActionRun(message);
              const runId = String(embeddedRun?.run_id || '');
              return (
                <MessageBubble
                  key={message.id}
                  message={message}
                  onSubmitPrompt={submitMessage}
                  submitting={submitting}
                  actionControlsEnabled={message.id === latestMessageId}
                  actionRun={runId ? (actionRuns[runId] || embeddedRun) : null}
                  actionRunEvents={runId ? (actionRunEvents[runId] || []) : []}
                  onActionRunControl={handleActionRunControl}
                  actionRunControlBusy={actionRunControlBusy}
                />
              );
            })}
            {unlinkedActiveRuns.length ? (
              <section className="simurgh-chat__active-runs" aria-label="Active Simurgh operations">
                <span className="simurgh-chat__active-runs-label">Active operations</span>
                {unlinkedActiveRuns.map((run) => (
                  <ActionRunCard
                    key={run.run_id}
                    run={run}
                    events={actionRunEvents[run.run_id] || []}
                    onControl={handleActionRunControl}
                    controlBusy={actionRunControlBusy}
                  />
                ))}
              </section>
            ) : null}
          </div>
          {chatError ? <div className="simurgh-chat__error" role="alert">{chatError}</div> : null}
          <form className="simurgh-chat__composer" onSubmit={handleSubmit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  handleSubmit(event);
                }
              }}
              rows={1}
              placeholder={status?.agent_enabled ? 'Message Simurgh' : 'Simurgh agent is disabled'}
              aria-label="Message Simurgh"
              disabled={!status?.agent_enabled}
            />
            {submitting ? (
              <ActionIconButton icon={<FaStop />} label="Stop Simurgh response" onClick={stopRequest}>
                Stop
              </ActionIconButton>
            ) : (
              <ActionIconButton icon={<FaPaperPlane />} label="Send Simurgh message" type="submit" disabled={!canSend}>
                Send
              </ActionIconButton>
            )}
          </form>
        </section>
        <SettingsPanel
          open={settingsOpen}
          settings={settings}
          status={status}
          candidateReview={candidateReview}
          activeTools={activeTools}
          busy={settingsBusy}
          notice={settingsNotice}
          credentialDraft={credentialDraft}
          onCredentialDraftChange={setCredentialDraft}
          onChange={handleSettingsChange}
          onSave={saveSettings}
          onClose={() => setSettingsOpen(false)}
        />
      </section>
    </PageShell>
  );
}
