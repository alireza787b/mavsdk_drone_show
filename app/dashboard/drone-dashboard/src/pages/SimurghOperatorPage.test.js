import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockCreateSimurghAssistantTurnResponse = jest.fn();
const mockStreamSimurghAssistantTurnResponse = jest.fn();
const mockGetSimurghRuntimeSettingsResponse = jest.fn();
const mockGetSimurghStatusResponse = jest.fn();
const mockGetSimurghToolsResponse = jest.fn();
const mockGetSimurghToolCandidatesResponse = jest.fn();
const mockUpdateSimurghRuntimeSettingsResponse = jest.fn();
const mockUpdateSimurghProviderCredentialsResponse = jest.fn();

jest.mock('../services/gcsApiService', () => ({
  createSimurghAssistantTurnResponse: (...args) => mockCreateSimurghAssistantTurnResponse(...args),
  streamSimurghAssistantTurnResponse: (...args) => mockStreamSimurghAssistantTurnResponse(...args),
  getSimurghRuntimeSettingsResponse: (...args) => mockGetSimurghRuntimeSettingsResponse(...args),
  getSimurghStatusResponse: (...args) => mockGetSimurghStatusResponse(...args),
  getSimurghToolsResponse: (...args) => mockGetSimurghToolsResponse(...args),
  getSimurghToolCandidatesResponse: (...args) => mockGetSimurghToolCandidatesResponse(...args),
  updateSimurghRuntimeSettingsResponse: (...args) => mockUpdateSimurghRuntimeSettingsResponse(...args),
  updateSimurghProviderCredentialsResponse: (...args) => mockUpdateSimurghProviderCredentialsResponse(...args),
}));

const SimurghOperatorPage = require('./SimurghOperatorPage').default;

const runtimePayload = {
  agent_enabled: true,
  mcp_enabled: false,
  gcs_mode: 'real',
  gcs_mode_source: 'env:MDS_MODE',
  mode: 'read_only',
  action_circuit_breaker_enabled: true,
  always_confirm_before_action: true,
  actions_blocked: true,
  action_policy_source: 'circuit_breaker_and_mds_mode',
  provider: 'mock',
  model: 'mock-local',
  openai_model: 'gpt-5.5',
  web_search_enabled: false,
  available_providers: ['mock', 'openai'],
  available_models: ['gpt-5.5', 'gpt-5.4-mini', 'gpt-5.4-nano'],
  provider_ready: true,
  credentials: {
    openai: {
      configured: true,
      ready: true,
      fingerprint: 'abc123def456',
      updated_at: '2026-05-24T00:00:00Z',
    },
  },
  warnings: [],
};

const candidateReviewPayload = {
  artifact_path: 'docs/agent-context/generated/simurgh-openapi-tool-candidates.yaml',
  candidate_count: 196,
  summary: {
    total: 196,
    eligible_read_only_mcp_candidates: 72,
    promoted_registry_route_matches: 28,
    candidate_exclude_or_guard_after_review: 124,
  },
  candidates: [],
};

const activeToolsPayload = {
  version: 1,
  tools: [
    {
      id: 'mds.config.fleet.read',
      title: 'Read fleet configuration',
      read_only: true,
      requires_approval: false,
      destructive: false,
    },
    {
      id: 'mds.fleet.telemetry.read',
      title: 'Read fleet telemetry',
      read_only: true,
      requires_approval: false,
      destructive: false,
    },
    {
      id: 'mds.commands.submit.plan',
      title: 'Plan guarded command submission',
      read_only: false,
      requires_approval: true,
      destructive: false,
    },
  ],
};

function assistantTurnData(overrides = {}) {
  return {
    id: 'turn_1',
    provider: 'mds-tools',
    model: 'local-read-only',
    adapter_version: 'mds-read-tools-v1',
    created_at: '2026-05-24T00:00:00Z',
    content: 'Fleet status from GCS configuration: 2 configured drone(s).\n\n- [MDS init setup](/api/v1/simurgh/context/mds.init_setup/markdown)',
    session: {
      id: 'sess_assist',
      actor: 'dashboard',
      mode: 'read_only',
      closed: false,
      ...(overrides.session || {}),
    },
    actor: 'dashboard',
    mode: 'read_only',
    message_hash: 'abcdef1234567890',
    message_chars: 34,
    context_resources: [],
    blocked_intents: [],
    safety_notes: ['Answered by local read-only MDS/GCS context tools.'],
    audit_event_id: 'evt_assist',
    ...overrides,
  };
}

function mockStreamResponseOnce(data) {
  mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
    config.onEvent?.({ event: 'progress', data: { label: 'Understanding request' } });
    config.onEvent?.({ event: 'progress', data: { label: 'Using MDS context' } });
    config.onEvent?.({ event: 'final', data });
    config.onEvent?.({ event: 'done', data: { id: data.id, session_id: data.session?.id } });
    return { data };
  });
}

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
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: jest.fn().mockResolvedValue(undefined) },
    });
    window.localStorage.clear();
    mockGetSimurghRuntimeSettingsResponse.mockResolvedValue({ data: runtimePayload });
    mockGetSimurghStatusResponse.mockResolvedValue({ data: runtimePayload });
    mockGetSimurghToolsResponse.mockResolvedValue({ data: activeToolsPayload });
    mockGetSimurghToolCandidatesResponse.mockResolvedValue({ data: candidateReviewPayload });
    mockUpdateSimurghRuntimeSettingsResponse.mockResolvedValue({
      data: {
        ...runtimePayload,
        provider: 'openai',
        model: 'gpt-5.4-nano',
        openai_model: 'gpt-5.4-nano',
        web_search_enabled: true,
      },
    });
    mockUpdateSimurghProviderCredentialsResponse.mockResolvedValue({
      data: {
        success: true,
        credentials: runtimePayload.credentials,
      },
    });
    const defaultTurn = assistantTurnData();
    mockCreateSimurghAssistantTurnResponse.mockResolvedValue({ data: defaultTurn });
    mockStreamSimurghAssistantTurnResponse.mockImplementation(async (payload, config = {}) => {
      config.onEvent?.({ event: 'progress', data: { label: 'Understanding request' } });
      config.onEvent?.({ event: 'progress', data: { label: 'Using MDS context' } });
      config.onEvent?.({ event: 'final', data: defaultTurn });
      config.onEvent?.({ event: 'done', data: { id: defaultTurn.id, session_id: defaultTurn.session.id } });
      return { data: defaultTurn };
    });
  });

  test('renders a chat-first Simurgh surface with compact safety posture', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { level: 1, name: /operator chat/i })).toBeInTheDocument();
    expect(await screen.findByText('mock / mock-local')).toBeInTheDocument();
    expect(await screen.findByText('Agent on')).toBeInTheDocument();
    expect(screen.getByText('REAL')).toBeInTheDocument();
    expect(screen.getByText('Circuit breaker on')).toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveAttribute('aria-relevant', 'additions');
    expect(screen.getByRole('textbox', { name: /message simurgh/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start new simurgh chat/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /more chat history actions/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /clear all local simurgh chats/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText(/tool registry/i)).not.toBeInTheDocument();
  });

  test('deletes one local chat from the row actions menu without clearing all history', async () => {
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [
        {
          id: 'chat-drone-status',
          backendSessionId: 'sess_drone_status',
          title: 'Drone status',
          createdAt: '2026-05-24T00:00:00Z',
          updatedAt: '2026-05-24T00:00:00Z',
          messages: [{ id: 'msg_1', role: 'user', content: 'which drones are connected?' }],
        },
        {
          id: 'chat-show-check',
          backendSessionId: 'sess_show_check',
          title: 'Show check',
          createdAt: '2026-05-24T00:01:00Z',
          updatedAt: '2026-05-24T00:01:00Z',
          messages: [{ id: 'msg_2', role: 'user', content: 'is a drone show uploaded?' }],
        },
      ],
    }));

    renderPage();

    expect(await screen.findByText('Drone status')).toBeInTheDocument();
    expect(screen.getByText('Show check')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /more actions for drone status/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /delete chat/i }));

    await waitFor(() => {
      expect(screen.queryByText('Drone status')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Show check')).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem('mds.simurgh.chat.v2')).conversations.map((conversation) => conversation.id)).toEqual(['chat-show-check']);
  });

  test('keeps the destructive clear-all action behind the compact history menu', async () => {
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [
        {
          id: 'chat-a',
          backendSessionId: 'sess_a',
          title: 'Fleet check',
          createdAt: '2026-05-24T00:00:00Z',
          updatedAt: '2026-05-24T00:00:00Z',
          messages: [{ id: 'msg_a', role: 'user', content: 'fleet status?' }],
        },
      ],
    }));

    renderPage();

    expect(await screen.findByText('Fleet check')).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /clear all chats/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /more chat history actions/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /clear all chats/i }));

    await waitFor(() => {
      expect(screen.queryByText('Fleet check')).not.toBeInTheDocument();
    });
    expect(screen.getByText('New chat')).toBeInTheDocument();
  });

  test('submits a PM read-only prompt as a normal chat turn', async () => {
    const finalTurn = assistantTurnData({
      content: 'Fleet status from GCS configuration: 2 configured drone(s).',
    });
    let releaseStream;
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({ event: 'progress', data: { label: 'Using MDS context' } });
      config.onEvent?.({ event: 'delta', data: { text: 'Fleet status from GCS configuration: ' } });
      await new Promise((resolve) => { releaseStream = resolve; });
      config.onEvent?.({ event: 'delta', data: { text: '2 configured drone(s).' } });
      config.onEvent?.({ event: 'final', data: finalTurn });
      config.onEvent?.({ event: 'done', data: { id: finalTurn.id, session_id: finalTurn.session.id } });
      return { data: finalTurn };
    });

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'How many drones do we have configured?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    await waitFor(() => {
      expect(mockStreamSimurghAssistantTurnResponse).toHaveBeenCalledWith({
        actor: 'dashboard',
        message: 'How many drones do we have configured?',
        metadata: { source: 'simurgh-dashboard' },
      }, expect.any(Object));
    });
    expect(await screen.findByText(/using mds context/i)).toBeInTheDocument();
    expect((await screen.findAllByText(/Fleet status from GCS configuration:/i)).length).toBeGreaterThan(0);
    await waitFor(() => expect(releaseStream).toEqual(expect.any(Function)));
    releaseStream();
    const fleetMentions = await screen.findAllByText(/2 configured drone/i);
    expect(fleetMentions.length).toBeGreaterThan(0);
    expect(screen.getAllByText('How many drones do we have configured?').length).toBeGreaterThan(0);
  });

  test('recovers an expired backend session once without duplicating the user turn', async () => {
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      activeConversationId: 'chat-stale-session',
      conversations: [{
        id: 'chat-stale-session',
        backendSessionId: 'session-expired',
        title: 'Fleet follow-up',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [
          { id: 'old-user', role: 'user', content: 'Which drones are connected?' },
          {
            id: 'old-assistant',
            role: 'assistant',
            content: 'Connectivity from GCS state: 0/2 drone(s) currently look live.',
            trace: {
              query: { domain: 'fleet', response_mode: 'status' },
              tool: { intent: 'fleet_connectivity' },
            },
          },
        ],
      }],
    }));
    const recoveredTurn = assistantTurnData({
      id: 'turn_recovered',
      content: 'No drones are currently connected.',
      session: { id: 'session-fresh' },
    });
    const expiredError = new Error('unknown Simurgh session: session-expired');
    expiredError.statusCode = 404;
    mockStreamSimurghAssistantTurnResponse
      .mockRejectedValueOnce(expiredError)
      .mockImplementationOnce(async (payload, config = {}) => {
        config.onEvent?.({
          event: 'final',
          data: recoveredTurn,
        });
        config.onEvent?.({
          event: 'done',
          data: { id: recoveredTurn.id, session_id: recoveredTurn.session.id },
        });
        return { data: recoveredTurn };
      });

    renderPage();
    const [storedChatButton] = await screen.findAllByRole('button', { name: /fleet follow-up/i });
    fireEvent.click(storedChatButton);
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'And now?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    await waitFor(() => expect(mockStreamSimurghAssistantTurnResponse).toHaveBeenCalledTimes(2));
    expect(mockStreamSimurghAssistantTurnResponse.mock.calls[0][0]).toEqual(expect.objectContaining({
      message: 'And now?',
      session_id: 'session-expired',
    }));
    expect(mockStreamSimurghAssistantTurnResponse.mock.calls[1][0]).toEqual({
      actor: 'dashboard',
      message: 'And now?',
      metadata: {
        source: 'simurgh-dashboard',
        last_domain: 'fleet',
        last_intent: 'fleet_connectivity',
        last_response_mode: 'status',
      },
    });
    await waitFor(() => {
      expect(screen.getAllByText('No drones are currently connected.').length).toBeGreaterThanOrEqual(1);
    });
    const transcriptUserMessages = Array.from(document.querySelectorAll('.simurgh-chat__message--user'))
      .filter((element) => element.textContent.includes('And now?'));
    expect(transcriptUserMessages).toHaveLength(1);
  });

  test('renders compact live activity and keeps final evidence without debug noise', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_activity',
      content: 'Connectivity from GCS state: 1/2 drone(s) currently look live.',
      session: { id: 'sess_activity' },
    });
    let releaseStream;
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({ event: 'progress', data: { stage: 'understanding', state: 'running', label: 'Reading request' } });
      config.onEvent?.({ event: 'progress', data: { stage: 'context', state: 'complete', label: 'Retrieved MDS context' } });
      config.onEvent?.({ event: 'progress', data: { stage: 'plan', state: 'complete', label: 'Planned read-only checks' } });
      config.onEvent?.({ event: 'progress', data: { stage: 'tool', state: 'running', tool_id: 'mds.fleet.telemetry.read', label: 'Checking fleet telemetry' } });
      config.onEvent?.({ event: 'delta', data: { text: 'Connectivity from GCS state: ' } });
      await new Promise((resolve) => { releaseStream = resolve; });
      config.onEvent?.({ event: 'delta', data: { text: '1/2 drone(s) currently look live.' } });
      config.onEvent?.({ event: 'final', data: finalTurn });
      config.onEvent?.({ event: 'done', data: { id: finalTurn.id, session_id: finalTurn.session.id } });
      return { data: finalTurn };
    });

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'which drones are connected?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('Checking fleet telemetry')).toBeInTheDocument();
    expect(screen.queryByText('Retrieved MDS context')).not.toBeInTheDocument();
    expect(screen.queryByText('Planned read-only checks')).not.toBeInTheDocument();
    await waitFor(() => expect(releaseStream).toEqual(expect.any(Function)));
    releaseStream();

    expect((await screen.findAllByText(/1\/2 drone\(s\) currently look live/i)).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(screen.getByText('Answer ready')).toBeInTheDocument();
      expect(screen.getByText('Checking fleet telemetry')).toBeInTheDocument();
      expect(screen.queryByText('Retrieved MDS context')).not.toBeInTheDocument();
    });
  });

  test('hot-applies provider, model, and optional server-side key from the compact settings panel', async () => {
    const fakeOpenAiKey = ['sk', 'test', '12345678901234567890'].join('-');
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /open simurgh settings/i }));
    await waitFor(() => {
      expect(mockGetSimurghToolsResponse).toHaveBeenCalledWith({ includeExcluded: false });
    });
    expect(screen.getByText('Active tools')).toBeInTheDocument();
    const openLinks = screen.getAllByRole('link', { name: 'Open' });
    expect(openLinks.map((link) => link.getAttribute('href'))).toEqual(expect.arrayContaining([
      '/api/v1/simurgh/tools?include_excluded=false',
      '/api/v1/simurgh/tool-candidates?limit=200',
    ]));
    openLinks.forEach((link) => expect(link).toHaveAttribute('target', '_blank'));
    const activeToolsPanel = screen.getByLabelText('Active Simurgh MCP tools');
    expect(within(activeToolsPanel).getByText('Read fleet configuration')).toBeInTheDocument();
    expect(within(activeToolsPanel).getByText('Read fleet telemetry')).toBeInTheDocument();
    expect(within(activeToolsPanel).getByText('Guarded')).toBeInTheDocument();
    expect(await screen.findByText('MCP review')).toBeInTheDocument();
    expect(screen.getByText('196')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/simurgh provider/i), { target: { value: 'openai' } });
    fireEvent.change(screen.getByLabelText(/openai model/i), { target: { value: 'gpt-5.4-nano' } });
    fireEvent.click(screen.getByLabelText(/web search/i));
    fireEvent.change(screen.getByLabelText(/openai api key/i), { target: { value: fakeOpenAiKey } });
    fireEvent.click(screen.getByRole('button', { name: /save simurgh settings/i }));

    await waitFor(() => {
      expect(mockUpdateSimurghProviderCredentialsResponse).toHaveBeenCalledWith(expect.objectContaining({
        openai_api_key: fakeOpenAiKey,
        set_provider_openai: true,
        openai_model: 'gpt-5.4-nano',
      }));
      expect(mockUpdateSimurghRuntimeSettingsResponse).toHaveBeenCalledWith(expect.objectContaining({
        provider: 'openai',
        openai_model: 'gpt-5.4-nano',
        web_search_enabled: true,
        action_circuit_breaker_enabled: true,
        always_confirm_before_action: true,
      }));
    });
    expect(await screen.findByText('Settings applied')).toBeInTheDocument();
  });

  test('renders safe markdown links in assistant answers', async () => {
    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'give me setup docs' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const link = await screen.findByRole('link', { name: /mds init setup/i });
    expect(link).toHaveAttribute('href', '/api/v1/simurgh/context/mds.init_setup/markdown');
    expect(link).toHaveAttribute('target', '_blank');
  });

  test('renders tables, code snippets, and copy controls in assistant answers', async () => {
    const markdownAnswer = [
      'Drone Show has two workflow families and several launch/control modes:',
      '',
      '| Area | Mode | Use it when | |---|---|---| | Show workflow | **SkyBrush ZIP** | Normal multi-drone show import. | | Launch/control mode | GLOBAL | Outdoor show with launch correction. |',
      '',
      '**Normal path:** use `Show Design` after readiness is green.',
      '',
      '```bash',
      'mds show validate --dry-run',
      '```',
    ].join('\n');
    mockStreamResponseOnce(assistantTurnData({
      id: 'turn_rich_markdown',
      content: markdownAnswer,
      session: { id: 'sess_rich' },
      message_hash: 'rich-markdown',
      message_chars: markdownAnswer.length,
      safety_notes: [],
      audit_event_id: 'evt_rich',
    }));

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'show launch modes' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Area' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: /Normal multi-drone show import/i })).toBeInTheDocument();
    expect(screen.getByText('SkyBrush ZIP').tagName).toBe('STRONG');
    expect(screen.getByText('Normal path:').tagName).toBe('STRONG');
    expect(screen.getByText('Show Design').tagName).toBe('CODE');
    expect(screen.getByText('mds show validate --dry-run')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /copy simurgh message/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(markdownAnswer);
    });

    fireEvent.click(screen.getByRole('button', { name: /copy code snippet/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('mds show validate --dry-run');
    });
  });

  test('keeps streamed turn trace in a compact per-message evidence disclosure', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_trace',
      content: 'Connectivity from GCS state: 1/2 drone(s) currently look live.',
      session: { id: 'sess_trace' },
      trace: {
        provider: 'openai',
        model: 'gpt-5.5',
        adapter_version: 'openai-responses-v1',
        query: {
          domain: 'fleet',
          confidence: 0.94,
          response_mode: 'mds_read_only_evidence',
          read_only_plan: { tool_ids: ['mds.config.fleet.read'] },
        },
        tool: {
          intent: 'fleet_connectivity',
          ids: ['mds.fleet.heartbeats.read', 'mds.fleet.telemetry.read'],
        },
        context: {
          resource_count: 2,
          retrieved_context_count: 1,
        },
        language: {
          detected_language: 'en',
          tone: 'operator',
        },
        safety: {
          blocked_intent_count: 0,
          action_execution: 'none',
        },
      },
    });
    mockStreamResponseOnce(finalTurn);

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'which drones are connected?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const disclosure = await screen.findByRole('button', { name: /evidence ready · 2 sources/i });
    const answerText = screen
      .getAllByText(/Connectivity from GCS state: 1\/2 drone\(s\) currently look live/i)
      .find((node) => node.closest('.simurgh-chat__markdown'));
    expect(answerText).toBeTruthy();
    expect(Boolean(disclosure.compareDocumentPosition(answerText) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(disclosure);

    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Model path')).toBeInTheDocument();
    expect(screen.getByText(/openai \/ gpt-5\.5/i)).toBeInTheDocument();
    expect(screen.getByText('Intent')).toBeInTheDocument();
    expect(screen.getByText('Fleet Connectivity')).toBeInTheDocument();
    expect(screen.getByText('Tools')).toBeInTheDocument();
    expect(screen.getByText(/mds\.fleet\.heartbeats\.read/)).toBeInTheDocument();
    expect(screen.getByText('Context')).toBeInTheDocument();
    expect(screen.getByText(/2 resource\(s\).*1 retrieved chunk\(s\)/)).toBeInTheDocument();

    const stored = JSON.parse(window.localStorage.getItem('mds.simurgh.chat.v2'));
    expect(stored.conversations[0].messages.find((message) => message.id === 'turn_trace').trace.tool.ids).toEqual([
      'mds.fleet.heartbeats.read',
      'mds.fleet.telemetry.read',
    ]);
  });

  test('summarizes public web search turns without exposing debug noise', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_web_search',
      provider: 'openai',
      model: 'gpt-5.5',
      content: 'Use a local aviation weather source before flight.\n\nSources:\n- [Example Weather](https://example.com/weather)',
      session: { id: 'sess_web_search' },
      trace: {
        provider: 'openai',
        model: 'gpt-5.5',
        adapter_version: 'openai-responses-v1',
        provider_tools: {
          web_search_enabled: true,
          web_search_requested: true,
          web_search_returned: true,
          web_search_scope: 'public_general_only',
          citation_count: 1,
          source_status: 'citations_returned',
        },
        query: {
          domain: 'general',
          confidence: 0.85,
          response_mode: 'interpret',
        },
        tool: { intent: '', ids: [] },
        context: { resource_count: 0, retrieved_context_count: 0 },
        safety: { blocked_intent_count: 0, action_execution: 'none' },
      },
    });
    mockStreamResponseOnce(finalTurn);

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'how is the weather today in Taipei?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const disclosure = await screen.findByRole('button', { name: /public web sources/i });
    fireEvent.click(disclosure);

    expect(screen.getByText('Lookup')).toBeInTheDocument();
    expect(screen.getByText('Public web search')).toBeInTheDocument();
    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('1 citation URL(s)')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Example Weather' })).toHaveAttribute('href', 'https://example.com/weather');
    expect(screen.queryByText(/web_search_call/i)).not.toBeInTheDocument();
  });

  test('marks web search answers that return no citation URLs', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_web_search_no_citations',
      provider: 'openai',
      model: 'gpt-5.5',
      content: 'Current public weather should be verified before flight.\n\nSource note: Public web search ran, but the provider did not return citation URLs for this response.',
      session: { id: 'sess_web_search_no_citations' },
      trace: {
        provider: 'openai',
        model: 'gpt-5.5',
        adapter_version: 'openai-responses-v1',
        provider_tools: {
          web_search_enabled: true,
          web_search_requested: true,
          web_search_returned: true,
          web_search_scope: 'public_general_only',
          citation_count: 0,
          source_status: 'search_returned_without_citations',
        },
        query: { domain: 'general', confidence: 0.85, response_mode: 'interpret' },
        tool: { intent: '', ids: [] },
        context: { resource_count: 0, retrieved_context_count: 0 },
        safety: { blocked_intent_count: 0, action_execution: 'none' },
      },
    });
    mockStreamResponseOnce(finalTurn);

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'how is the weather today in Taipei?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const disclosure = await screen.findByRole('button', { name: /public web sources/i });
    fireEvent.click(disclosure);

    expect(screen.getByText('No citation URLs returned')).toBeInTheDocument();
    expect(screen.getAllByText(/Source note: Public web search ran/).length).toBeGreaterThan(0);
    expect(screen.queryByText('Sources:')).not.toBeInTheDocument();
  });

  test('auto-links safe dashboard routes and known docs paths in assistant answers', async () => {
    mockStreamResponseOnce(assistantTurnData({
      id: 'turn_links',
      content: 'Open /manage-drone-show or /quickscout. Read docs/features/drone-show.md and docs/guides/simurgh-mcp-clients.md and call /api/v1/shows/skybrush/import.',
      session: { id: 'sess_links' },
      message_hash: 'links',
      message_chars: 18,
      safety_notes: [],
      audit_event_id: 'evt_links',
    }));

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'show upload links' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const routeLink = await screen.findByRole('link', { name: '/manage-drone-show' });
    expect(routeLink).toHaveAttribute('href', '/manage-drone-show');
    expect(routeLink).toHaveAttribute('target', '_blank');
    const quickScoutLink = screen.getByRole('link', { name: '/quickscout' });
    expect(quickScoutLink).toHaveAttribute('href', '/quickscout');
    expect(quickScoutLink).toHaveAttribute('target', '_blank');
    expect(screen.getByRole('link', { name: 'docs/features/drone-show.md' })).toHaveAttribute('href', '/api/v1/simurgh/context/mds.drone_show/markdown');
    expect(screen.getByRole('link', { name: 'docs/guides/simurgh-mcp-clients.md' })).toHaveAttribute('href', '/api/v1/simurgh/context/simurgh.mcp_client_recipes/markdown');
    expect(screen.queryByRole('link', { name: '/api/v1/shows/skybrush/import' })).not.toBeInTheDocument();
    expect(document.body).toHaveTextContent('/api/v1/shows/skybrush/import');
  });

  test('rejects unsafe markdown links in assistant answers', async () => {
    mockStreamResponseOnce(assistantTurnData({
      id: 'turn_unsafe_links',
      content: '[good](/logs) [source](https://example.com/report) [bad](//evil.example) [js](javascript:alert(1)) [https://evil.example](javascript:alert(1)) [https://example.com/good](https://example.com/good)',
      session: { id: 'sess_unsafe_links' },
      message_hash: 'unsafe-links',
      message_chars: 18,
      safety_notes: [],
      audit_event_id: 'evt_unsafe_links',
    }));

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'unsafe links' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const goodLink = await screen.findByRole('link', { name: 'good' });
    expect(goodLink).toHaveAttribute('href', '/logs');
    expect(goodLink).toHaveAttribute('target', '_blank');
    const sourceLink = screen.getByRole('link', { name: 'source' });
    expect(sourceLink).toHaveAttribute('href', 'https://example.com/report');
    expect(sourceLink).toHaveAttribute('target', '_blank');
    expect(screen.queryByRole('link', { name: 'bad' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'js' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'https://evil.example' })).not.toBeInTheDocument();
    expect(document.body).toHaveTextContent('https://evil.example');
    expect(screen.getByRole('link', { name: 'https://example.com/good' })).toHaveAttribute('href', 'https://example.com/good');
  });

  test('disables the composer when the agent is off', async () => {
    mockGetSimurghRuntimeSettingsResponse.mockResolvedValue({
      data: {
        ...runtimePayload,
        agent_enabled: false,
      },
    });

    renderPage();

    expect(await screen.findByText('Agent off')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /message simurgh/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /send simurgh message/i })).toBeDisabled();
  });
});
