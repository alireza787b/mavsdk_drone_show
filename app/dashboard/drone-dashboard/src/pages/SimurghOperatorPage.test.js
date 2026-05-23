import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockGetSimurghStatusResponse = jest.fn();
const mockGetSimurghPolicyResponse = jest.fn();
const mockGetSimurghToolsResponse = jest.fn();
const mockGetSimurghContextResponse = jest.fn();
const mockGetSimurghSessionsResponse = jest.fn();
const mockGetSimurghAuditResponse = jest.fn();
const mockGetSimurghAssistantTurnsResponse = jest.fn();
const mockCreateSimurghAssistantTurnResponse = jest.fn();

jest.mock('../services/gcsApiService', () => ({
  createSimurghAssistantTurnResponse: (...args) => mockCreateSimurghAssistantTurnResponse(...args),
  getSimurghAssistantTurnsResponse: (...args) => mockGetSimurghAssistantTurnsResponse(...args),
  getSimurghStatusResponse: (...args) => mockGetSimurghStatusResponse(...args),
  getSimurghPolicyResponse: (...args) => mockGetSimurghPolicyResponse(...args),
  getSimurghToolsResponse: (...args) => mockGetSimurghToolsResponse(...args),
  getSimurghContextResponse: (...args) => mockGetSimurghContextResponse(...args),
  getSimurghSessionsResponse: (...args) => mockGetSimurghSessionsResponse(...args),
  getSimurghAuditResponse: (...args) => mockGetSimurghAuditResponse(...args),
}));

const SimurghOperatorPage = require('./SimurghOperatorPage').default;

const statusPayload = {
  agent_enabled: false,
  mcp_enabled: false,
  gcs_mode: 'real',
  gcs_mode_source: 'env:MDS_MODE',
  mode: 'read_only',
  action_circuit_breaker_enabled: true,
  always_confirm_before_action: true,
  real_commands_enabled: false,
  tool_registry_version: 1,
  tool_count: 3,
  allowed_tool_count: 1,
  guarded_tool_count: 1,
  excluded_tool_count: 1,
  context_resource_count: 2,
  active_session_count: 1,
  audit_event_count: 1,
  assistant_provider: 'mock',
  assistant_model: 'mock-local',
  assistant_external_provider: false,
  assistant_external_provider_auth_required: false,
  policy_path: 'config/agent_policy.yaml',
  tool_registry_path: 'config/agent_tools.yaml',
  context_index_path: 'docs/agent-context/context-index.yaml',
  warnings: [],
};

const policyPayload = {
  version: 1,
  agent_enabled: false,
  mcp_enabled: false,
  mode: 'read_only',
  action_circuit_breaker_enabled: true,
  always_confirm_before_action: true,
  real_commands_enabled: false,
  allow_drone_api_exposure: false,
  unknown_tool_policy: 'deny',
  approval_ttl_seconds: 300,
  approval_required_risks: ['plan', 'simulate'],
  runtime_modes: {
    read_only: {
      allowed_risks: ['observe', 'sensitive_observe', 'plan'],
      denied_risks: ['simulate', 'operate', 'admin', 'destructive'],
      approval_required_risks: ['plan'],
    },
    sitl: {
      allowed_risks: ['observe', 'sensitive_observe', 'plan', 'simulate'],
      denied_risks: ['operate', 'admin', 'destructive'],
      approval_required_risks: ['plan', 'simulate'],
    },
  },
};

const toolsPayload = {
  version: 1,
  tools: [
    {
      id: 'mds.system.health.read',
      title: 'Read GCS health',
      description: 'Read the GCS health endpoint for service availability.',
      exposure: 'allow',
      risk_class: 'observe',
      boundary: 'gcs',
      read_only: true,
      route: { method: 'GET', path: '/api/v1/system/health' },
      required_role: 'viewer',
      requires_approval: false,
      destructive: false,
      runtime_modes: ['read_only', 'sitl', 'real'],
      side_effects: [],
      sensitivity: [],
      tags: ['system', 'health'],
      docs: ['docs/apis/gcs-api-server.md'],
      safety_notes: ['Health checks are observational.'],
    },
    {
      id: 'mds.plan.mission.generate',
      title: 'Generate mission plan',
      description: 'Generate a non-executing plan.',
      exposure: 'guarded',
      risk_class: 'plan',
      boundary: 'gcs',
      read_only: true,
      route: { method: null, path: null },
      required_role: 'operator',
      requires_approval: true,
      destructive: false,
      runtime_modes: ['read_only', 'sitl'],
      side_effects: [],
      sensitivity: ['mission_state'],
      tags: ['planning'],
      docs: ['docs/agent-context/tool-usage-guidelines.md'],
      safety_notes: [],
    },
    {
      id: 'mds.commands.raw_submit',
      title: 'Raw command submit',
      description: 'Excluded raw command route.',
      exposure: 'exclude',
      risk_class: 'operate',
      boundary: 'gcs',
      read_only: false,
      route: { method: 'POST', path: '/api/v1/commands' },
      required_role: 'admin',
      requires_approval: true,
      destructive: false,
      runtime_modes: [],
      side_effects: ['command_submission'],
      sensitivity: ['mission_state'],
      tags: ['commands'],
      docs: [],
      safety_notes: ['Raw command submission is excluded.'],
    },
  ],
};

const contextPayload = {
  version: 1,
  resources: [
    {
      id: 'simurgh.safety_policy',
      title: 'Simurgh safety policy',
      path: 'docs/agent-context/safety-policy.md',
      mime_type: 'text/markdown',
      audience: 'agent',
      sensitivity: 'public',
      summary: 'Human-readable companion to the enforced policy artifact.',
      tags: ['simurgh', 'policy'],
      content_hash: 'abcdef0123456789',
    },
    {
      id: 'simurgh.tool_usage',
      title: 'Simurgh tool usage guidelines',
      path: 'docs/agent-context/tool-usage-guidelines.md',
      mime_type: 'text/markdown',
      audience: 'agent',
      sensitivity: 'public',
      summary: 'Tool registry semantics and adapter expectations.',
      tags: ['simurgh', 'tools'],
      content_hash: '123456abcdef7890',
    },
  ],
};

const sessionsPayload = {
  sessions: [
    {
      id: 'sess_1',
      actor: 'operator',
      mode: 'read_only',
      created_at: '2026-05-19T00:00:00Z',
      expires_at: '2026-05-19T01:00:00Z',
      closed_at: null,
      closed: false,
      metadata: { channel: 'dashboard' },
    },
  ],
};

const assistantSession = {
  id: 'sess_assist',
  actor: 'dashboard',
  mode: 'read_only',
  created_at: '2026-05-19T00:00:00Z',
  expires_at: '2026-05-19T01:00:00Z',
  closed_at: null,
  closed: false,
  metadata: { channel: 'assistant', source: 'simurgh-dashboard' },
};

const otherActorAssistantSession = {
  ...assistantSession,
  id: 'sess_other',
  actor: 'other-operator',
};

const auditPayload = {
  events: [
    {
      id: 'evt_1',
      event_type: 'session_created',
      created_at: '2026-05-19T00:00:01Z',
      session_id: 'sess_1',
      actor: 'operator',
      tool_id: null,
      decision: 'allow',
      payload_hash: 'fedcba9876543210',
      metadata: { mode: 'read_only' },
    },
  ],
};

const assistantHistoryTurn = {
  id: 'turn_1',
  provider: 'mock',
  model: 'mock-local',
  adapter_version: 'mock-v1',
  created_at: '2026-05-19T00:00:02Z',
  session_id: 'sess_assist',
  actor: 'dashboard',
  mode: 'read_only',
  message: '',
  content: '',
  context_resources: [{ id: 'simurgh.safety_policy' }],
  blocked_intents: ['arm'],
  safety_notes: ['No tool execution was attempted.'],
  audit_event_id: 'evt_assist',
  message_hash: 'abcdef1234567890',
  message_chars: 21,
};

function renderPage() {
  return render(
    <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <SimurghOperatorPage />
    </MemoryRouter>
  );
}

describe('SimurghOperatorPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetSimurghStatusResponse.mockResolvedValue({ data: statusPayload });
    mockGetSimurghPolicyResponse.mockResolvedValue({ data: policyPayload });
    mockGetSimurghToolsResponse.mockResolvedValue({ data: toolsPayload });
    mockGetSimurghContextResponse.mockResolvedValue({ data: contextPayload });
    mockGetSimurghSessionsResponse.mockResolvedValue({ data: sessionsPayload });
    mockGetSimurghAuditResponse.mockResolvedValue({ data: auditPayload });
    mockGetSimurghAssistantTurnsResponse.mockResolvedValue({ data: { turns: [] } });
    mockCreateSimurghAssistantTurnResponse.mockResolvedValue({
      data: {
        id: 'turn_1',
        provider: 'mock',
        model: 'mock-local',
        adapter_version: 'mock-v1',
        created_at: '2026-05-19T00:00:02Z',
        content: 'Mock response',
        session: {
          id: 'sess_assist',
          actor: 'dashboard',
          mode: 'read_only',
          closed: false,
        },
        actor: 'dashboard',
        mode: 'read_only',
        message_hash: 'abcdef1234567890',
        message_chars: 21,
        context_resources: [{ id: 'simurgh.safety_policy' }],
        blocked_intents: ['arm'],
        safety_notes: ['No tool execution was attempted.'],
        audit_event_id: 'evt_assist',
      },
    });
  });

  test('renders disabled Simurgh posture and read-only metadata views', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { level: 1, name: /agent control plane/i })).toBeInTheDocument();
    expect(await screen.findByText('Agent runtime disabled')).toBeInTheDocument();
    expect(screen.getByText('GCS Mode')).toBeInTheDocument();
    expect(screen.getByText('Policy Profile')).toBeInTheDocument();
    expect(screen.getAllByText('No actions').length).toBeGreaterThan(0);
    expect(screen.getByText('GCS only')).toBeInTheDocument();
    expect(screen.getByText('Blocked')).toBeInTheDocument();
    expect(screen.getByText('config/agent_policy.yaml')).toBeInTheDocument();
    expect(mockGetSimurghToolsResponse).toHaveBeenCalledWith({ includeExcluded: true });
    expect(mockGetSimurghSessionsResponse).toHaveBeenCalledWith({ includeClosed: true });

    fireEvent.click(screen.getByRole('tab', { name: /tools/i }));
    expect(screen.getByText('Read GCS health')).toBeInTheDocument();
    expect(screen.getByText('mds.commands.raw_submit')).toBeInTheDocument();
    expect(screen.getByText('POST /api/v1/commands')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /context/i }));
    expect(screen.getByText('Simurgh safety policy')).toBeInTheDocument();
    expect(screen.getByText('docs/agent-context/safety-policy.md')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /audit/i }));
    expect(screen.getAllByText('operator').length).toBeGreaterThan(0);
    expect(screen.getByText('session created')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  test('keeps the assistant shell disabled when the agent runtime is off', async () => {
    renderPage();

    expect(await screen.findByText('Agent runtime disabled')).toBeInTheDocument();
    expect(mockGetSimurghAssistantTurnsResponse).toHaveBeenCalledWith({ limit: 20 });
    fireEvent.click(screen.getByRole('tab', { name: /assistant/i }));

    expect(screen.getByText('Assistant runtime disabled')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /operator message/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /generate advisory reply/i })).toBeDisabled();
    expect(mockCreateSimurghAssistantTurnResponse).not.toHaveBeenCalled();
  });

  test('submits a mock assistant turn without exposing command controls', async () => {
    mockGetSimurghStatusResponse.mockResolvedValue({
      data: {
        ...statusPayload,
        agent_enabled: true,
        active_session_count: 0,
        audit_event_count: 0,
      },
    });
    mockGetSimurghPolicyResponse.mockResolvedValue({
      data: {
        ...policyPayload,
        agent_enabled: true,
      },
    });
    mockGetSimurghAssistantTurnsResponse
      .mockResolvedValueOnce({ data: { turns: [] } })
      .mockResolvedValue({ data: { turns: [assistantHistoryTurn] } });

    renderPage();

    expect(await screen.findByText('Policy Posture')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /assistant/i }));
    expect(screen.getByText(/stay local in mock mode/i)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Simurgh safety policy/i));
    fireEvent.change(screen.getByRole('textbox', { name: /operator message/i }), {
      target: { value: 'Can you arm drone 1?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /generate advisory reply/i }));

    await waitFor(() => {
      expect(mockCreateSimurghAssistantTurnResponse).toHaveBeenCalledWith({
        actor: 'dashboard',
        message: 'Can you arm drone 1?',
        metadata: {
          source: 'simurgh-dashboard',
        },
        context_resource_ids: ['simurgh.safety_policy'],
      });
    });
    expect(await screen.findByText('Guarded')).toBeInTheDocument();
    expect(screen.getByText('abcdef123456')).toBeInTheDocument();
    expect(screen.queryByText('Can you arm drone 1?')).not.toBeInTheDocument();
    expect(screen.getByText('arm')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /arm/i })).not.toBeInTheDocument();
  });

  test('warns operators when assistant text may use the OpenAI provider', async () => {
    mockGetSimurghStatusResponse.mockResolvedValue({
      data: {
        ...statusPayload,
        agent_enabled: true,
        assistant_provider: 'openai',
        assistant_model: 'gpt-5.5',
        assistant_external_provider: true,
        assistant_external_provider_auth_required: true,
      },
    });
    mockGetSimurghPolicyResponse.mockResolvedValue({
      data: {
        ...policyPayload,
        agent_enabled: true,
      },
    });

    renderPage();

    expect(await screen.findByText('Policy Posture')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /assistant/i }));

    expect(screen.getByText(/may be sent to the configured OpenAI provider/i)).toBeInTheDocument();
    expect(screen.getByText(/external providers require an authenticated MDS operator session/i)).toBeInTheDocument();
    expect(screen.getByText(/do not enter raw field artifacts/i)).toBeInTheDocument();
  });

  test('reuses only an active dashboard assistant session for follow-up turns', async () => {
    mockGetSimurghStatusResponse.mockResolvedValue({
      data: {
        ...statusPayload,
        agent_enabled: true,
      },
    });
    mockGetSimurghPolicyResponse.mockResolvedValue({
      data: {
        ...policyPayload,
        agent_enabled: true,
      },
    });
    mockGetSimurghSessionsResponse.mockResolvedValue({
      data: { sessions: [assistantSession] },
    });
    mockGetSimurghAssistantTurnsResponse.mockResolvedValue({ data: { turns: [assistantHistoryTurn] } });

    renderPage();

    expect(await screen.findByText('Policy Posture')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /assistant/i }));
    expect(await screen.findByText(/Session sess_assist/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: /operator message/i }), {
      target: { value: 'Follow up on the policy.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /generate advisory reply/i }));

    await waitFor(() => {
      expect(mockCreateSimurghAssistantTurnResponse).toHaveBeenCalledWith(expect.objectContaining({
        actor: 'dashboard',
        message: 'Follow up on the policy.',
        session_id: 'sess_assist',
      }));
    });
  });

  test('does not reuse stale assistant history when no active session exists', async () => {
    mockGetSimurghStatusResponse.mockResolvedValue({
      data: {
        ...statusPayload,
        agent_enabled: true,
        active_session_count: 0,
      },
    });
    mockGetSimurghPolicyResponse.mockResolvedValue({
      data: {
        ...policyPayload,
        agent_enabled: true,
      },
    });
    mockGetSimurghSessionsResponse.mockResolvedValue({ data: { sessions: [] } });
    mockGetSimurghAssistantTurnsResponse.mockResolvedValue({ data: { turns: [assistantHistoryTurn] } });

    renderPage();

    expect(await screen.findByText('Policy Posture')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /assistant/i }));
    expect(await screen.findByText(/New advisory session/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: /operator message/i }), {
      target: { value: 'Start fresh after restart.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /generate advisory reply/i }));

    await waitFor(() => {
      expect(mockCreateSimurghAssistantTurnResponse).toHaveBeenCalledWith(expect.not.objectContaining({
        session_id: 'sess_assist',
      }));
    });
  });

  test('does not auto-select another actor assistant session from admin-visible sessions', async () => {
    mockGetSimurghStatusResponse.mockResolvedValue({
      data: {
        ...statusPayload,
        agent_enabled: true,
      },
    });
    mockGetSimurghPolicyResponse.mockResolvedValue({
      data: {
        ...policyPayload,
        agent_enabled: true,
      },
    });
    mockGetSimurghSessionsResponse.mockResolvedValue({ data: { sessions: [otherActorAssistantSession] } });
    mockGetSimurghAssistantTurnsResponse.mockResolvedValue({ data: { turns: [assistantHistoryTurn] } });

    renderPage();

    expect(await screen.findByText('Policy Posture')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /assistant/i }));
    expect(await screen.findByText(/New advisory session/i)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: /operator message/i }), {
      target: { value: 'Do not reuse another operator session.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /generate advisory reply/i }));

    await waitFor(() => {
      expect(mockCreateSimurghAssistantTurnResponse).toHaveBeenCalledWith(expect.not.objectContaining({
        session_id: 'sess_other',
      }));
    });
  });

  test('supports roving keyboard focus across Simurgh tabs', async () => {
    renderPage();

    expect(await screen.findByText('Agent runtime disabled')).toBeInTheDocument();
    const overviewTab = screen.getByRole('tab', { name: /overview/i });
    overviewTab.focus();
    fireEvent.keyDown(overviewTab, { key: 'ArrowRight' });

    expect(screen.getByRole('tab', { name: /assistant/i })).toHaveAttribute('aria-selected', 'true');
  });

  test('refreshes all Simurgh metadata endpoints', async () => {
    renderPage();

    expect(await screen.findByText('Agent runtime disabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /refresh simurgh status/i }));

    await waitFor(() => {
      expect(mockGetSimurghStatusResponse).toHaveBeenCalledTimes(2);
      expect(mockGetSimurghPolicyResponse).toHaveBeenCalledTimes(2);
      expect(mockGetSimurghAuditResponse).toHaveBeenCalledTimes(2);
    });
  });

  test('shows a config error without rendering stale metadata', async () => {
    mockGetSimurghStatusResponse.mockRejectedValueOnce({
      response: { data: { detail: 'unknown Simurgh mode: unsafe' } },
    });

    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('unknown Simurgh mode: unsafe');
    expect(screen.queryByText('config/agent_policy.yaml')).not.toBeInTheDocument();
  });
});
