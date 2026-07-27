import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockCreateSimurghAssistantTurnResponse = jest.fn();
const mockStreamSimurghAssistantTurnResponse = jest.fn();
const mockControlSimurghActionRunResponse = jest.fn();
const mockGetSimurghActionRunResponse = jest.fn();
const mockGetSimurghActionRunsResponse = jest.fn();
const mockStreamSimurghActionRunEventsResponse = jest.fn();
const mockGetSimurghRuntimeSettingsResponse = jest.fn();
const mockGetSimurghStatusResponse = jest.fn();
const mockGetSimurghToolsResponse = jest.fn();
const mockGetSimurghToolCandidatesResponse = jest.fn();
const mockUpdateSimurghRuntimeSettingsResponse = jest.fn();
const mockUpdateSimurghProviderCredentialsResponse = jest.fn();

jest.mock('../services/gcsApiService', () => ({
  createSimurghAssistantTurnResponse: (...args) => mockCreateSimurghAssistantTurnResponse(...args),
  streamSimurghAssistantTurnResponse: (...args) => mockStreamSimurghAssistantTurnResponse(...args),
  controlSimurghActionRunResponse: (...args) => mockControlSimurghActionRunResponse(...args),
  getSimurghActionRunResponse: (...args) => mockGetSimurghActionRunResponse(...args),
  getSimurghActionRunsResponse: (...args) => mockGetSimurghActionRunsResponse(...args),
  streamSimurghActionRunEventsResponse: (...args) => mockStreamSimurghActionRunEventsResponse(...args),
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
  openai_model: 'gpt-5.6-sol',
  web_search_enabled: false,
  available_providers: ['mock', 'openai'],
  available_models: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
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

function actionRunData(overrides = {}) {
  return {
    run_id: 'run-test-sequence',
    actor: 'dashboard',
    session_id: 'sess_action_run',
    draft_id: 'act-action-run',
    state: 'running',
    terminal: false,
    current_step: 1,
    total_steps: 4,
    summary: 'Executing the approved action plan.',
    control_state: '',
    available_controls: ['pause_after_current_step', 'cancel_remaining'],
    plan: {
      draft_id: 'act-action-run',
      draft_type: 'flight_action',
      mission_name: 'TAKE_OFF',
      target_drone_ids: ['1'],
      command_payload: {
        mission_type: 10,
        target_drone_ids: ['1'],
        takeoff_altitude: 10,
      },
      display_plan: {
        title: 'Test flight',
        target: 'Drone 1',
        steps: [
          { index: 1, kind: 'flight_command', label: 'Take off to 10 m' },
          { index: 2, kind: 'wait', label: 'Wait 5 seconds' },
          { index: 3, kind: 'flight_command', label: 'Move 25 m north' },
          { index: 4, kind: 'flight_command', label: 'Return to launch' },
        ],
      },
    },
    created_at: '2026-05-24T00:00:00Z',
    updated_at: '2026-05-24T00:00:01Z',
    completed_at: null,
    ...overrides,
  };
}

function mockStreamResponseOnce(data) {
  mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
    config.onEvent?.({ event: 'progress', data: { label: 'Understanding request' } });
    config.onEvent?.({ event: 'progress', data: { label: 'Using MDS context' } });
    config.onEvent?.({ event: 'delta', data: { text: data.content || '' } });
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

async function findActionRunCard(runId) {
  let runCard = null;
  await waitFor(() => {
    runCard = document.querySelector(`[data-action-run-id="${runId}"]`);
    expect(runCard).not.toBeNull();
  });
  return runCard;
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
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [] } });
    mockGetSimurghActionRunResponse.mockRejectedValue(new Error('unknown action run'));
    mockControlSimurghActionRunResponse.mockResolvedValue({ data: {} });
    mockStreamSimurghActionRunEventsResponse.mockResolvedValue({ data: null });
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
      config.onEvent?.({ event: 'delta', data: { text: defaultTurn.content } });
      config.onEvent?.({ event: 'final', data: defaultTurn });
      config.onEvent?.({ event: 'done', data: { id: defaultTurn.id, session_id: defaultTurn.session.id } });
      return { data: defaultTurn };
    });
  });

  test('renders a chat-first Simurgh surface with compact safety posture', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { level: 1, name: /operator chat/i })).toBeInTheDocument();
    expect(await screen.findByText('Agent on')).toBeInTheDocument();
    expect(screen.getByText('REAL')).toBeInTheDocument();
    expect(screen.getByText('Circuit breaker on')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /message simurgh/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start new simurgh chat/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /more chat history actions/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /clear all local simurgh chats/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText(/tool registry/i)).not.toBeInTheDocument();
  });

  test('shows unavailable posture without inventing safe runtime state', async () => {
    mockGetSimurghRuntimeSettingsResponse.mockRejectedValue(new Error('runtime settings unavailable'));
    mockGetSimurghStatusResponse.mockRejectedValue(new Error('status unavailable'));

    renderPage();

    expect(await screen.findByText('Posture unavailable')).toBeInTheDocument();
    expect(screen.getByText('Runtime unavailable')).toBeInTheDocument();
    expect(screen.queryByText('Agent off')).not.toBeInTheDocument();
    expect(screen.queryByText('Circuit breaker off')).not.toBeInTheDocument();
    expect(screen.queryByText('Provider ready')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open simurgh settings/i })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: /message simurgh/i })).toBeDisabled();
  });

  test('clears stale posture when a post-turn runtime refresh fails', async () => {
    mockGetSimurghRuntimeSettingsResponse
      .mockResolvedValueOnce({ data: runtimePayload })
      .mockRejectedValue(new Error('runtime settings unavailable'));
    mockGetSimurghStatusResponse.mockRejectedValue(new Error('status unavailable'));

    renderPage();
    expect(await screen.findByText('Agent on')).toBeInTheDocument();

    const input = screen.getByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'How many drones are configured?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('Posture unavailable')).toBeInTheDocument();
    expect(screen.queryByText('Agent on')).not.toBeInTheDocument();
    expect(screen.queryByText('Circuit breaker on')).not.toBeInTheDocument();
    expect(input).toBeDisabled();
  });

  test('collapses chat history by default at compact widths', async () => {
    const matchMediaSpy = jest.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: query === '(max-width: 980px)',
      media: query,
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() { return false; },
    }));
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-compact-primary',
        title: 'Primary operation',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:01Z',
        messages: [],
      }, {
        id: 'chat-compact-history',
        title: 'Earlier operation',
        createdAt: '2026-05-23T00:00:00Z',
        updatedAt: '2026-05-23T00:00:01Z',
        messages: [],
      }],
    }));

    renderPage();

    const history = await screen.findByLabelText('Simurgh chat history');
    const toggle = within(history).getByRole('button', { name: 'Primary operation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('simurgh-chat-history-list')).not.toBeVisible();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('simurgh-chat-history-list')).toBeVisible();
    matchMediaSpy.mockRestore();
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
    fireEvent.click(screen.getByRole('button', { name: /delete chat/i }));

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
    expect(screen.queryByRole('button', { name: /clear all chats/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /more chat history actions/i }));
    fireEvent.click(screen.getByRole('button', { name: /clear all chats/i }));

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

  test('announces the completed assistant answer without announcing streamed deltas', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_accessible_completion',
      content: 'Drone 1 is ready for the requested SITL test.',
    });
    let releaseStream;
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({ event: 'delta', data: { text: 'Drone 1 is ' } });
      await new Promise((resolve) => { releaseStream = resolve; });
      config.onEvent?.({ event: 'delta', data: { text: 'ready for the requested SITL test.' } });
      config.onEvent?.({ event: 'final', data: finalTurn });
      config.onEvent?.({ event: 'done', data: { id: finalTurn.id, session_id: finalTurn.session.id } });
      return { data: finalTurn };
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'Is it ready?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const announcement = screen.getByRole('status', { name: /simurgh answer announcements/i });
    expect(announcement).toBeEmptyDOMElement();
    expect((await screen.findAllByText('Drone 1 is')).length).toBeGreaterThan(0);
    expect(announcement).toBeEmptyDOMElement();

    releaseStream();
    await waitFor(() => {
      expect(screen.getByRole('status', { name: /simurgh answer announcements/i })).toHaveTextContent(
        'Simurgh response ready.',
      );
    });
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

  test('distinguishes requested pause and cancellation from applied control states', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_control_activity',
      content: 'The remaining sequence was cancelled.',
      session: { id: 'sess_control_activity' },
    });
    let releasePause;
    let releaseCancel;
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'action',
          state: 'pause_requested',
          label: 'Pausing after the current step',
          sequence_id: 'run-control',
        },
      });
      await new Promise((resolve) => { releasePause = resolve; });
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'action',
          state: 'cancel_requested',
          label: 'Cancelling remaining steps',
          sequence_id: 'run-control',
        },
      });
      await new Promise((resolve) => { releaseCancel = resolve; });
      config.onEvent?.({ event: 'final', data: finalTurn });
      config.onEvent?.({ event: 'done', data: { id: finalTurn.id, session_id: finalTurn.session.id } });
      return { data: finalTurn };
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'pause after this step' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const pauseLabel = await screen.findByText('Pausing after the current step');
    expect(pauseLabel.closest('.simurgh-chat__activity-current')).toHaveTextContent('Pausing');
    releasePause();

    const cancelLabel = await screen.findByText('Cancelling remaining steps');
    expect(cancelLabel.closest('.simurgh-chat__activity-current')).toHaveTextContent('Cancelling');
    releaseCancel();
    expect(
      (await screen.findAllByText('The remaining sequence was cancelled.')).length,
    ).toBeGreaterThan(0);
  });

  test('shows current guarded sequence step in compact live activity', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_sequence_activity',
      content: 'Submitted the guarded flight command.',
      session: { id: 'sess_sequence_activity' },
    });
    let releaseStream;
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'monitor',
          state: 'running',
          label: 'Step 1/4: takeoff',
          sequence_id: 'act-seq',
          step_index: 1,
          step_count: 4,
          step_label: 'takeoff',
          step_kind: 'flight_command',
          command_id: 'cmd-1',
        },
      });
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'monitor',
          state: 'running',
          label: 'Step 2/4: wait 5 second(s)',
          sequence_id: 'act-seq',
          step_index: 2,
          step_count: 4,
          step_label: 'wait 5 second(s)',
          step_kind: 'delay',
        },
      });
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'monitor',
          state: 'complete',
          label: 'Step 2/4: wait 5 second(s)',
          sequence_id: 'act-seq',
          step_index: 2,
          step_count: 4,
          step_label: 'wait 5 second(s)',
          step_kind: 'delay',
        },
      });
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'monitor',
          state: 'running',
          label: 'Step 3/4: precision move',
          sequence_id: 'act-seq',
          step_index: 3,
          step_count: 4,
          step_label: 'precision move',
          step_kind: 'flight_command',
          command_id: 'cmd-2',
        },
      });
      config.onEvent?.({
        event: 'progress',
        data: {
          stage: 'monitor',
          state: 'timeout',
          label: 'Step 4/4: return rtl',
          sequence_id: 'act-seq',
          step_index: 4,
          step_count: 4,
          step_label: 'return rtl',
          step_kind: 'flight_command',
          command_id: 'cmd-3',
        },
      });
      await new Promise((resolve) => { releaseStream = resolve; });
      config.onEvent?.({ event: 'final', data: finalTurn });
      config.onEvent?.({ event: 'done', data: { id: finalTurn.id, session_id: finalTurn.session.id } });
      return { data: finalTurn };
    });

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'confirm action act-seq' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('Step 4/4: return rtl')).toBeInTheDocument();
    expect(screen.getByText('Timed out')).toBeInTheDocument();
    expect(screen.getByText('Step 2/4: wait 5 second(s)')).toBeInTheDocument();
    expect(screen.getByText('Step 3/4: precision move')).toBeInTheDocument();
    expect(screen.getByLabelText('Step 2/4: wait 5 second(s): completed')).toBeInTheDocument();
    expect(screen.getByLabelText('Step 3/4: precision move: in progress')).toBeInTheDocument();
    await waitFor(() => expect(releaseStream).toEqual(expect.any(Function)));
    releaseStream();

    expect(await screen.findAllByText('Submitted the guarded flight command.')).not.toHaveLength(0);
  });

  test('hot-applies provider, model, and optional server-side key from the compact settings panel', async () => {
    const fakeOpenAiKey = ['sk', 'test', '12345678901234567890'].join('-');
    renderPage();

    const trigger = await screen.findByRole('button', { name: /open simurgh settings/i });
    await waitFor(() => expect(trigger).toBeEnabled());
    fireEvent.click(trigger);
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

  test('uses only server-advertised model suggestions while preserving a configured model', async () => {
    const { available_models: ignoredModels, ...runtimeWithoutModels } = runtimePayload;
    mockGetSimurghRuntimeSettingsResponse.mockResolvedValue({
      data: {
        ...runtimeWithoutModels,
        provider: 'openai',
        openai_model: 'provider-model-from-server',
      },
    });

    renderPage();
    const trigger = await screen.findByRole('button', { name: /open simurgh settings/i });
    await waitFor(() => expect(trigger).toBeEnabled());
    fireEvent.click(trigger);

    expect(screen.getByLabelText(/openai model/i)).toHaveValue('provider-model-from-server');
    expect(document.querySelectorAll('#simurgh-openai-models option')).toHaveLength(0);
  });

  test('treats mobile settings as a focus-contained dialog and restores the trigger', async () => {
    const matchMediaSpy = jest.spyOn(window, 'matchMedia').mockImplementation((query) => ({
      matches: query === '(max-width: 640px)',
      media: query,
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() { return false; },
    }));

    renderPage();
    const trigger = await screen.findByRole('button', { name: /open simurgh settings/i });
    await waitFor(() => expect(trigger).toBeEnabled());
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = await screen.findByRole('dialog', { name: /settings/i });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    const closeButton = within(dialog).getByRole('button', { name: /close simurgh settings/i });
    await waitFor(() => expect(closeButton).toHaveFocus());

    const saveButton = within(dialog).getByRole('button', { name: /save simurgh settings/i });
    saveButton.focus();
    fireEvent.keyDown(saveButton, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(closeButton, { key: 'Tab', shiftKey: true });
    expect(saveButton).toHaveFocus();

    fireEvent.keyDown(saveButton, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /settings/i })).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    matchMediaSpy.mockRestore();
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

  test('renders pending action controls and confirms with the streamed backend session', async () => {
    const actionDraftTurn = assistantTurnData({
      id: 'turn_action_draft',
      content: 'Review the guarded action plan below. No action was executed.',
      session: { id: 'sess_action_draft' },
      trace: {
        provider: 'mds-tools',
        model: 'local-action-planner',
        adapter_version: 'action-planner-v1',
        query: { domain: 'flight', confidence: 1, response_mode: 'status' },
        tool: { intent: 'flight_action', ids: ['mds.flight.command.execute'] },
        context: { resource_count: 0, retrieved_context_count: 0 },
        safety: {
          blocked_intent_count: 0,
          action_execution: 'awaiting_confirmation',
          action_draft: {
            draft_id: 'act-abc123',
            draft_type: 'flight_action',
            tool_id: 'mds.flight.command.execute',
            mission_name: 'TAKE_OFF',
            target_drone_ids: ['1'],
            command_payload: {
              mission_type: 10,
              target_drone_ids: ['1'],
              takeoff_altitude: 10,
            },
            post_actions: [
              { type: 'delay', action_label: 'wait 5 second(s)', delay_seconds: 5 },
              {
                type: 'flight_command',
                action_label: 'precision move',
                arguments: {
                  mission_type: 112,
                  precision_move: { translation_m: { north: 25, east: 0, up: 0 } },
                },
              },
              { type: 'flight_command', action_label: 'return rtl', arguments: { mission_type: 104 } },
            ],
            display_plan: {
              title: 'Review flight plan',
              target: 'drone 1',
              conditions: [
                {
                  fact_id: 'sitl.running_instance_count',
                  label: 'No SITL instance is running',
                  operator: 'eq',
                  expected: 0,
                },
                {
                  fact_id: 'fleet.telemetry_fresh',
                  label: 'Telemetry is fresh',
                  operator: 'eq',
                  expected: true,
                },
                {
                  fact_id: 'fleet.preflight_ready',
                  label: 'Preflight checks are ready',
                  operator: 'eq',
                  expected: true,
                },
                {
                  fact_id: 'fleet.target_count',
                  label: 'Exactly one target is selected',
                  operator: 'eq',
                  expected: 1,
                },
                {
                  fact_id: 'fleet.target_disarmed',
                  label: 'Target is disarmed before takeoff',
                  operator: 'eq',
                  expected: true,
                },
              ],
              steps: [
                { index: 1, kind: 'flight_command', label: 'Take off to 10 m' },
                { index: 2, kind: 'wait', label: 'Wait 5 seconds' },
                { index: 3, kind: 'flight_command', label: 'Move 25 m north' },
                { index: 4, kind: 'flight_command', label: 'Return to launch' },
              ],
            },
          },
        },
      },
    });
    const confirmedTurn = assistantTurnData({
      id: 'turn_action_confirmed',
      content: 'Submitted the guarded flight command through the canonical GCS command path.',
      session: { id: 'sess_action_draft' },
      trace: {
        safety: {
          blocked_intent_count: 0,
          action_execution: 'submitted',
          action_draft: actionDraftTurn.trace.safety.action_draft,
          action_monitor: { success: true, status: 'terminal_success' },
          post_action_results: [
            { label: 'wait 5 second(s)', status: 'completed', is_error: false },
            { label: 'precision move', status: 'terminal_success', is_error: false },
            { label: 'return rtl', status: 'terminal_success', is_error: false },
          ],
        },
        tool: { intent: 'flight_action', ids: ['mds.flight.command.execute'] },
      },
    });
    mockStreamSimurghAssistantTurnResponse
      .mockImplementationOnce(async (payload, config = {}) => {
        config.onEvent?.({ event: 'progress', data: { stage: 'plan', state: 'complete', label: 'Drafted guarded take off action' } });
        config.onEvent?.({ event: 'final', data: actionDraftTurn });
        config.onEvent?.({ event: 'done', data: { id: actionDraftTurn.id, session_id: actionDraftTurn.session.id } });
        return { data: actionDraftTurn };
      })
      .mockImplementationOnce(async (payload, config = {}) => {
        config.onEvent?.({ event: 'progress', data: { stage: 'safety', state: 'complete', label: 'Recovered pending action' } });
        config.onEvent?.({ event: 'final', data: confirmedTurn });
        config.onEvent?.({ event: 'done', data: { id: confirmedTurn.id, session_id: confirmedTurn.session.id } });
        return { data: confirmedTurn };
      });

    renderPage();

    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'Send drone 1 to takeoff to 10m' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect((await screen.findAllByText(/review flight plan/i)).length).toBeGreaterThan(0);
    expect(screen.getByText('Only if')).toBeInTheDocument();
    expect(screen.getByText('No SITL instance is running')).toBeInTheDocument();
    expect(screen.getByText('Telemetry is fresh')).toBeInTheDocument();
    expect(screen.getByText('Preflight checks are ready')).toBeInTheDocument();
    expect(screen.getByText('Exactly one target is selected')).toBeInTheDocument();
    expect(screen.getByText('Target is disarmed before takeoff')).toBeInTheDocument();
    expect(screen.getByText('Take off to 10 m')).toBeInTheDocument();
    expect(screen.getByText('Wait 5 seconds')).toBeInTheDocument();
    expect(screen.getByText('Move 25 m north')).toBeInTheDocument();
    expect(screen.getByText('Return to launch')).toBeInTheDocument();
    expect(screen.queryByText((text) => text.includes('"mission_type": 10'))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /raw action json/i }));
    expect(screen.getAllByText((text) => text.includes('"mission_type": 10')).length).toBeGreaterThan(0);

    const controls = await screen.findByLabelText('Pending guarded action controls');
    fireEvent.click(within(controls).getByRole('button', { name: /confirm/i }));

    await waitFor(() => {
      expect(mockStreamSimurghAssistantTurnResponse).toHaveBeenCalledTimes(2);
    });
    expect(mockStreamSimurghAssistantTurnResponse.mock.calls[1][0]).toEqual({
      actor: 'dashboard',
      message: 'Confirm',
      metadata: {
        source: 'simurgh-dashboard',
        action_intent: 'confirm',
        draft_id: 'act-abc123',
      },
      session_id: 'sess_action_draft',
    });
    expect((await screen.findAllByText(/submitted the guarded flight command/i)).length).toBeGreaterThan(0);
    expect(screen.getByText('Command sequence complete')).toBeInTheDocument();
    expect(screen.getByText('4 of 4 steps completed')).toBeInTheDocument();
    expect(screen.queryByLabelText('Pending guarded action controls')).not.toBeInTheDocument();
    await waitFor(() => expect(input).toHaveFocus());
  });

  test('keeps button confirmation out of the transcript and focuses its durable action card', async () => {
    const pendingDraft = {
      draft_id: 'act-button-confirm',
      draft_type: 'flight_action',
      tool_id: 'mds.flight.command.execute',
      mission_name: 'TAKE_OFF',
      target_drone_ids: ['1'],
      command_payload: { mission_type: 10, target_drone_ids: ['1'], takeoff_altitude: 10 },
      display_plan: {
        title: 'Test flight',
        target: 'Drone 1',
        steps: [{ index: 1, kind: 'flight_command', label: 'Take off to 10 m' }],
      },
    };
    const completedRun = actionRunData({
      run_id: 'run-button-confirm',
      draft_id: pendingDraft.draft_id,
      state: 'succeeded',
      terminal: true,
      current_step: 1,
      total_steps: 1,
      plan: pendingDraft,
      summary: 'Completed 1 of 1 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-button-confirm',
        backendSessionId: 'sess-button-confirm',
        title: 'Test flight',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-button-confirm',
          role: 'assistant',
          content: 'Review this action.',
          trace: {
            safety: {
              action_execution: 'awaiting_confirmation',
              action_draft: pendingDraft,
            },
          },
        }],
      }],
    }));
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      const finalTurn = assistantTurnData({
        id: 'turn-button-confirmed',
        content: 'Action accepted.',
        session: { id: 'sess-button-confirm' },
        trace: {
          safety: {
            action_execution: 'submitted',
            action_run: completedRun,
          },
        },
      });
      config.onEvent?.({ event: 'final', data: finalTurn });
      config.onEvent?.({ event: 'done', data: { id: finalTurn.id, session_id: finalTurn.session.id } });
      return { data: finalTurn };
    });

    const { container } = renderPage();
    const controls = await screen.findByLabelText('Pending guarded action controls');
    fireEvent.click(within(controls).getByRole('button', { name: /confirm/i }));

    const runCard = await findActionRunCard('run-button-confirm');
    await waitFor(() => expect(runCard).toHaveFocus());
    expect(container.querySelectorAll('.simurgh-chat__message--user')).toHaveLength(0);
    expect(mockStreamSimurghAssistantTurnResponse.mock.calls[0][0]).toMatchObject({
      message: 'Confirm',
      metadata: {
        action_intent: 'confirm',
        draft_id: pendingDraft.draft_id,
      },
    });
  });

  test('submits a pending-plan amendment as structured context without exposing its draft id', async () => {
    const pendingDraft = {
      draft_id: 'act-amend-plan',
      draft_type: 'flight_action',
      tool_id: 'mds.flight.command.execute',
      mission_name: 'TAKE_OFF',
      target_drone_ids: ['1'],
      command_payload: { mission_type: 10, target_drone_ids: ['1'], takeoff_altitude: 10 },
    };
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-amend-plan',
        backendSessionId: 'sess-amend-plan',
        title: 'Amend plan',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-amend-plan',
          role: 'assistant',
          content: 'Review this action.',
          trace: {
            safety: {
              action_execution: 'awaiting_confirmation',
              action_draft: pendingDraft,
            },
          },
        }],
      }],
    }));

    renderPage();

    const controls = await screen.findByLabelText('Pending guarded action controls');
    fireEvent.click(within(controls).getByRole('button', { name: /amend/i }));

    const composer = screen.getByRole('textbox', { name: /message simurgh/i });
    await waitFor(() => expect(composer).toHaveFocus());
    expect(composer).toHaveValue('');
    expect(screen.getByText('Amending proposed action')).toBeInTheDocument();
    expect(screen.queryByText(/act-amend-plan/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Pending guarded action controls')).toBeInTheDocument();
    expect(mockStreamSimurghAssistantTurnResponse).not.toHaveBeenCalled();

    fireEvent.change(composer, { target: { value: 'Use 15 metres for takeoff instead.' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    await waitFor(() => {
      expect(mockStreamSimurghAssistantTurnResponse).toHaveBeenCalledWith({
        actor: 'dashboard',
        message: 'Use 15 metres for takeoff instead.',
        metadata: {
          source: 'simurgh-dashboard',
          action_intent: 'amend',
          draft_id: 'act-amend-plan',
        },
        session_id: 'sess-amend-plan',
      }, expect.any(Object));
    });
    expect(screen.queryByText('Amending proposed action')).not.toBeInTheDocument();
  });

  test('does not submit Enter while an input method editor is composing', async () => {
    renderPage();

    const composer = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(composer, { target: { value: 'پرواز آزمایشی' } });
    fireEvent.keyDown(composer, {
      key: 'Enter',
      code: 'Enter',
      isComposing: true,
      keyCode: 229,
    });

    expect(mockStreamSimurghAssistantTurnResponse).not.toHaveBeenCalled();
    expect(composer).toHaveValue('پرواز آزمایشی');

    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(mockStreamSimurghAssistantTurnResponse).toHaveBeenCalledTimes(1));
  });

  test('keeps the current typed action draft confirmable after an informational follow-up', async () => {
    const pendingDraft = {
      draft_id: 'act-pending-follow-up',
      draft_type: 'flight_action',
      tool_id: 'mds.flight.command.execute',
      mission_name: 'TAKE_OFF',
      target_drone_ids: ['1'],
      command_payload: { mission_type: 10, target_drone_ids: ['1'], takeoff_altitude: 10 },
    };
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-pending-follow-up',
        backendSessionId: 'sess-pending-follow-up',
        title: 'Pending action follow-up',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:03Z',
        messages: [
          {
            id: 'turn-pending-follow-up',
            role: 'assistant',
            content: 'Review this action.',
            trace: {
              safety: {
                action_execution: 'awaiting_confirmation',
                action_draft: pendingDraft,
              },
            },
          },
          {
            id: 'user-informational-follow-up',
            role: 'user',
            content: 'What is the current battery?',
          },
          {
            id: 'turn-informational-follow-up',
            role: 'assistant',
            content: 'Battery telemetry is available.',
            trace: {
              tool: { intent: 'fleet_status', ids: ['mds.fleet.telemetry.read'] },
              safety: { action_execution: 'not_requested' },
            },
          },
        ],
      }],
    }));

    renderPage();

    const controls = await screen.findByLabelText('Pending guarded action controls');
    fireEvent.click(within(controls).getByRole('button', { name: /confirm/i }));

    await waitFor(() => expect(mockStreamSimurghAssistantTurnResponse).toHaveBeenCalled());
    expect(mockStreamSimurghAssistantTurnResponse.mock.calls[0][0]).toMatchObject({
      message: 'Confirm',
      metadata: {
        source: 'simurgh-dashboard',
        action_intent: 'confirm',
        draft_id: 'act-pending-follow-up',
      },
      session_id: 'sess-pending-follow-up',
    });
  });

  test.each(['confirmed', 'rejected'])(
    'does not resurrect a %s typed action draft',
    async (resolution) => {
      const pendingDraft = {
        draft_id: `act-${resolution}-draft`,
        draft_type: 'flight_action',
        tool_id: 'mds.flight.command.execute',
        mission_name: 'LAND',
        target_drone_ids: ['1'],
        command_payload: { mission_type: 101, target_drone_ids: ['1'] },
      };
      const resolutionSafety = resolution === 'confirmed'
        ? {
          action_execution: 'submitted',
          action_run: actionRunData({
            run_id: `run-${resolution}-draft`,
            draft_id: pendingDraft.draft_id,
            state: 'succeeded',
            terminal: true,
          }),
        }
        : {
          action_execution: 'cancelled_confirmation',
          action_draft: pendingDraft,
        };
      window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
        schema: 2,
        conversations: [{
          id: `chat-${resolution}-draft`,
          backendSessionId: `sess-${resolution}-draft`,
          title: `${resolution} action`,
          createdAt: '2026-05-24T00:00:00Z',
          updatedAt: '2026-05-24T00:00:02Z',
          messages: [
            {
              id: `turn-pending-${resolution}`,
              role: 'assistant',
              content: 'Review this action.',
              trace: {
                safety: {
                  action_execution: 'awaiting_confirmation',
                  action_draft: pendingDraft,
                },
              },
            },
            {
              id: `turn-resolved-${resolution}`,
              role: 'assistant',
              content: 'The action draft is resolved.',
              trace: { safety: resolutionSafety },
            },
          ],
        }],
      }));

      renderPage();

      expect(await screen.findByText('Agent on')).toBeInTheDocument();
      expect(screen.queryByLabelText('Pending guarded action controls')).not.toBeInTheDocument();
    }
  );

  test('does not resurrect a superseded draft after the newer typed draft is resolved', async () => {
    const olderDraft = {
      draft_id: 'act-superseded-old',
      draft_type: 'registry_action',
      tool_id: 'mds.sitl.instances.create',
      arguments: {},
    };
    const newerDraft = {
      draft_id: 'act-superseded-new',
      draft_type: 'flight_action',
      tool_id: 'mds.flight.command.execute',
      mission_name: 'LAND',
      target_drone_ids: ['1'],
      command_payload: { mission_type: 101, target_drone_ids: ['1'] },
    };
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-superseded-draft',
        backendSessionId: 'sess-superseded-draft',
        title: 'Superseded action',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:03Z',
        messages: [
          {
            id: 'turn-pending-old',
            role: 'assistant',
            content: 'Review the older action.',
            trace: { safety: { action_execution: 'awaiting_confirmation', action_draft: olderDraft } },
          },
          {
            id: 'turn-pending-new',
            role: 'assistant',
            content: 'Review the newer action.',
            trace: { safety: { action_execution: 'awaiting_confirmation', action_draft: newerDraft } },
          },
          {
            id: 'turn-rejected-new',
            role: 'assistant',
            content: 'The newer action was rejected.',
            trace: { safety: { action_execution: 'cancelled_confirmation', action_draft: newerDraft } },
          },
        ],
      }],
    }));

    renderPage();

    expect(await screen.findByText('Agent on')).toBeInTheDocument();
    expect(screen.queryByLabelText('Pending guarded action controls')).not.toBeInTheDocument();
  });

  test('recovers the durable action run when confirmation streaming disconnects', async () => {
    const pendingDraft = {
      draft_id: 'act-recover-confirm',
      draft_type: 'flight_action',
      tool_id: 'mds.flight.command.execute',
      mission_name: 'TAKE_OFF',
      target_drone_ids: ['1'],
      command_payload: { mission_type: 10, target_drone_ids: ['1'], takeoff_altitude: 10 },
    };
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-confirm-recovery',
        backendSessionId: 'sess-confirm-recovery',
        title: 'Confirm recovery',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-pending-confirm',
          role: 'assistant',
          content: 'Review this action.',
          trace: {
            safety: {
              action_execution: 'awaiting_confirmation',
              action_draft: pendingDraft,
            },
          },
        }],
      }],
    }));
    const terminalRun = actionRunData({
      draft_id: pendingDraft.draft_id,
      state: 'succeeded',
      terminal: true,
      current_step: 4,
      summary: 'Completed 4 of 4 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
    });
    mockGetSimurghActionRunsResponse.mockImplementation(({ activeOnly, limit }) => Promise.resolve({
      data: { runs: activeOnly || limit !== 50 ? [] : [terminalRun] },
    }));
    mockStreamSimurghAssistantTurnResponse.mockRejectedValueOnce(new Error('network interrupted'));

    renderPage();
    const controls = await screen.findByLabelText('Pending guarded action controls');
    fireEvent.click(within(controls).getByRole('button', { name: /confirm/i }));

    expect((await screen.findAllByText(/confirmation accepted.*action run is complete/i)).length).toBeGreaterThan(0);
    const runCard = await findActionRunCard('run-test-sequence');
    expect(within(runCard).getByText('Complete')).toBeInTheDocument();
    expect(mockGetSimurghActionRunsResponse).toHaveBeenCalledWith({
      actor: 'dashboard',
      activeOnly: false,
      limit: 50,
    });
  });

  test('restores a retryable action card when rejection status cannot be verified', async () => {
    const pendingDraft = {
      draft_id: 'act-retry-reject',
      draft_type: 'flight_action',
      tool_id: 'mds.flight.command.execute',
      mission_name: 'LAND',
      target_drone_ids: ['1'],
      command_payload: { mission_type: 101, target_drone_ids: ['1'] },
    };
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-reject-retry',
        backendSessionId: 'sess-reject-retry',
        title: 'Reject retry',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-pending-reject',
          role: 'assistant',
          content: 'Review this action.',
          trace: {
            safety: {
              action_execution: 'awaiting_confirmation',
              action_draft: pendingDraft,
            },
          },
        }],
      }],
    }));
    mockStreamSimurghAssistantTurnResponse.mockRejectedValueOnce(new Error('network interrupted'));

    renderPage();
    const controls = await screen.findByLabelText('Pending guarded action controls');
    fireEvent.click(within(controls).getByRole('button', { name: /reject/i }));

    expect((await screen.findAllByText(/connection interrupted before rejection could be verified/i)).length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Pending guarded action controls')).toBeInTheDocument();
    expect(mockStreamSimurghAssistantTurnResponse.mock.calls[0][0]).toMatchObject({
      message: 'Reject',
      metadata: {
        action_intent: 'reject',
        draft_id: 'act-retry-reject',
      },
      session_id: 'sess-reject-retry',
    });
  });

  test('tracks an approved action run as a live human-readable sequence', async () => {
    const queuedRun = actionRunData({ state: 'queued', current_step: 0, summary: 'Approved action run queued.' });
    const completedRun = actionRunData({
      state: 'succeeded',
      terminal: true,
      current_step: 4,
      summary: 'Completed 4 of 4 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
    });
    const confirmedTurn = assistantTurnData({
      id: 'turn_action_run',
      content: 'Action run started. I will keep this sequence updated here.',
      session: { id: 'sess_action_run' },
      trace: {
        safety: {
          action_execution: 'submitted',
          action_run: queuedRun,
        },
      },
    });
    mockStreamResponseOnce(confirmedTurn);
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: completedRun });
    mockStreamSimurghActionRunEventsResponse.mockImplementation(async (runId, options, config = {}) => {
      const payloads = [
        { id: 1, event_type: 'run_started', payload: { state: 'running', label: 'Starting approved action run' } },
        { id: 2, event_type: 'progress', payload: { state: 'running', step_index: 1, step_count: 4, label: 'Step 1/4: Take off to 10 m' } },
        { id: 3, event_type: 'progress', payload: { state: 'complete', step_index: 1, step_count: 4, label: 'Step 1/4: Take off to 10 m' } },
        { id: 4, event_type: 'progress', payload: { state: 'running', step_index: 2, step_count: 4, label: 'Step 2/4: Wait 5 seconds' } },
        { id: 5, event_type: 'progress', payload: { state: 'complete', step_index: 2, step_count: 4, label: 'Step 2/4: Wait 5 seconds' } },
        { id: 6, event_type: 'progress', payload: { state: 'complete', step_index: 3, step_count: 4, label: 'Step 3/4: Move 25 m north' } },
        { id: 7, event_type: 'progress', payload: { state: 'complete', step_index: 4, step_count: 4, label: 'Step 4/4: Return to launch' } },
        { id: 8, event_type: 'run_succeeded', payload: { state: 'succeeded', step_count: 4, label: 'Completed 4 of 4 planned steps.' } },
      ];
      payloads.forEach((event) => config.onEvent?.({
        event: event.event_type,
        data: { ...event, run_id: runId, created_at: '2026-05-24T00:00:02Z' },
      }));
      config.onEvent?.({ event: 'run_snapshot', data: { run: completedRun, replay_complete: true } });
      return { data: { run: completedRun, replay_complete: true } };
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'confirm action act-action-run' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const runCard = await findActionRunCard('run-test-sequence');
    expect(within(runCard).getByText('Test flight')).toBeInTheDocument();
    expect(within(runCard).getByText('Drone 1')).toBeInTheDocument();
    expect(within(runCard).getByText('Take off to 10 m')).toBeInTheDocument();
    expect(within(runCard).getByText('Wait 5 seconds')).toBeInTheDocument();
    expect(within(runCard).getByText('Move 25 m north')).toBeInTheDocument();
    expect(within(runCard).getByText('Return to launch')).toBeInTheDocument();
    expect(await within(runCard).findByText('Complete')).toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '4');
    expect(within(runCard).queryByText((text) => text.includes('"mission_type": 10'))).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /message simurgh/i })).toBeEnabled();
  });

  test('renders a dispatch-time false condition as a terminal non-error no-op', async () => {
    const queuedRun = actionRunData({
      state: 'queued',
      current_step: 0,
      summary: 'Approved action run queued.',
    });
    const skippedRun = actionRunData({
      state: 'skipped',
      terminal: true,
      current_step: 0,
      summary: 'Action skipped because its required condition is no longer met.',
      result: {
        action_execution: 'precondition_not_met',
        dispatched_steps: 0,
      },
      completed_at: '2026-05-24T00:00:03Z',
    });
    const confirmedTurn = assistantTurnData({
      id: 'turn_action_run_skipped',
      content: 'Action run started.',
      session: { id: 'sess_action_run' },
      trace: {
        safety: {
          action_execution: 'submitted',
          action_run: queuedRun,
        },
      },
    });
    mockStreamResponseOnce(confirmedTurn);
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: skippedRun });
    mockStreamSimurghActionRunEventsResponse.mockImplementation(async (runId, options, config = {}) => {
      config.onEvent?.({
        event: 'precondition_checked',
        data: {
          id: 1,
          run_id: runId,
          event_type: 'precondition_checked',
          payload: { state: 'skipped', label: 'Action no longer needed' },
        },
      });
      config.onEvent?.({
        event: 'run_skipped',
        data: {
          id: 2,
          run_id: runId,
          event_type: 'run_skipped',
          payload: { state: 'skipped', label: skippedRun.summary },
        },
      });
      config.onEvent?.({ event: 'run_snapshot', data: { run: skippedRun, replay_complete: true } });
      return { data: { run: skippedRun, replay_complete: true } };
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'confirm action act-action-run' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const runCard = await findActionRunCard('run-test-sequence');
    expect(await within(runCard).findByText('Not needed')).toBeInTheDocument();
    expect(runCard.querySelector('.simurgh-chat__action-run-current')).toHaveTextContent(
      /required condition is no longer met/i,
    );
    expect(within(runCard).getAllByText('skipped')).toHaveLength(4);
    expect(runCard).toHaveClass('simurgh-chat__action-run--warning');
    expect(runCard).not.toHaveClass('simurgh-chat__action-run--danger');
  });

  test('keeps the run active when an individual sequence step completes', async () => {
    const queuedRun = actionRunData({ state: 'queued', current_step: 0 });
    const confirmedTurn = assistantTurnData({
      id: 'turn_intermediate_step',
      content: 'Action run started.',
      session: { id: 'sess_action_run' },
      trace: { safety: { action_execution: 'submitted', action_run: queuedRun } },
    });
    mockStreamResponseOnce(confirmedTurn);
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      config.onEvent?.({
        event: 'run_started',
        data: {
          id: 1,
          run_id: runId,
          event_type: 'run_started',
          payload: { state: 'running', step_count: 4, label: 'Starting approved action run' },
        },
      });
      config.onEvent?.({
        event: 'progress',
        data: {
          id: 2,
          run_id: runId,
          event_type: 'progress',
          payload: { state: 'complete', step_index: 1, step_count: 4, label: 'Step 1/4: Take off to 10 m' },
        },
      });
      return new Promise(() => {});
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'confirm action act-action-run' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    const runCard = await findActionRunCard('run-test-sequence');
    expect(within(runCard).queryByText('Complete')).not.toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');
    expect(within(runCard).getByRole('button', { name: /pause after step/i })).toBeEnabled();
  });

  test('shows backend step-specific progress while keeping raw action JSON collapsed', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 2,
      summary: 'Step 2/4: Wait 5 seconds',
    });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      config.onEvent?.({
        event: 'progress',
        data: {
          id: 12,
          run_id: runId,
          event_type: 'progress',
          created_at: '2026-05-24T00:00:12Z',
          payload: {
            stage: 'monitor',
            state: 'running',
            sequence_id: runId,
            step_index: 2,
            step_count: 4,
            step_label: 'Wait 5 seconds',
            step_kind: 'delay',
            label: 'Step 2/4: Wait 5 seconds',
          },
        },
      });
      return new Promise(() => {});
    });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    const liveStatus = await within(runCard).findByRole('status');
    expect(liveStatus).toHaveTextContent('Step 2/4: Wait 5 seconds · in progress');
    const waitStep = within(runCard).getByText('Wait 5 seconds').closest('li');
    expect(waitStep).toHaveClass('simurgh-chat__action-run-step--running');
    expect(within(runCard).getByTitle('Action in progress')).toBeInTheDocument();
    expect(within(runCard).queryByTitle('Action succeeded')).not.toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');
    expect(runCard).toHaveAttribute('aria-label', 'Test flight for Drone 1: Running');
    const takeoffStep = within(runCard).getByText('Take off to 10 m').closest('li');
    const moveStep = within(runCard).getByText('Move 25 m north').closest('li');
    expect(takeoffStep).not.toHaveAttribute('hidden');
    expect(takeoffStep).toHaveClass('simurgh-chat__action-run-step--recent');
    expect(moveStep).toHaveAttribute('hidden');
    const stepToggle = within(runCard).getByRole('button', { name: /show all 4 steps/i });
    expect(stepToggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(stepToggle);
    expect(moveStep).not.toHaveAttribute('hidden');
    expect(within(runCard).getByRole('button', { name: /show current progress/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    const rawToggle = within(runCard).getByRole('button', { name: /raw action json/i });
    expect(rawToggle).toHaveAttribute('aria-expanded', 'false');
    expect(rawToggle).toHaveAttribute('aria-controls');
    expect(within(runCard).queryByText((text) => text.includes('"mission_type": 10'))).not.toBeInTheDocument();
  });

  test('keeps a terminal snapshot absorbing when delayed progress events arrive', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 2,
      revision: 2,
      last_event_id: 12,
    });
    const terminalRun = actionRunData({
      state: 'succeeded',
      terminal: true,
      current_step: 4,
      revision: 5,
      last_event_id: 20,
      summary: 'Completed 4 of 4 planned steps.',
      updated_at: '2026-05-24T00:01:00Z',
      completed_at: '2026-05-24T00:01:00Z',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-terminal-ordering',
        backendSessionId: 'sess_action_run',
        title: 'Terminal ordering',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-terminal-ordering',
          role: 'assistant',
          content: 'Action run started.',
          trace: { safety: { action_execution: 'submitted', action_run: runningRun } },
        }],
      }],
    }));
    let streamConfig;
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      streamConfig = config;
      return new Promise(() => {});
    });

    renderPage();
    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(streamConfig).toBeDefined());

    act(() => {
      streamConfig.onEvent?.({
        event: 'run_snapshot',
        data: { run: terminalRun, revision: 5, last_event_id: 20 },
      });
    });
    expect(await within(runCard).findByText('Complete')).toBeInTheDocument();

    act(() => {
      streamConfig.onEvent?.({
        event: 'progress',
        data: {
          id: 19,
          revision: 4,
          run_id: terminalRun.run_id,
          event_type: 'progress',
          payload: {
            state: 'running',
            step_index: 3,
            step_count: 4,
            label: 'Delayed older progress',
          },
        },
      });
      streamConfig.onEvent?.({
        event: 'progress',
        data: {
          id: 21,
          revision: 6,
          run_id: terminalRun.run_id,
          event_type: 'progress',
          payload: {
            state: 'running',
            step_index: 4,
            step_count: 4,
            label: 'Delayed progress after terminal',
          },
        },
      });
    });

    expect(within(runCard).getByText('Complete')).toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '4');
    expect(within(runCard).queryByLabelText('Active action run controls')).not.toBeInTheDocument();
  });

  test('renders backend controls for an active one-step run', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 1,
      total_steps: 1,
      available_controls: ['pause_after_current_step', 'cancel_remaining'],
      plan: {
        ...actionRunData().plan,
        display_plan: {
          ...actionRunData().plan.display_plan,
          steps: [{ index: 1, kind: 'flight_command', label: 'Land drone 1' }],
        },
      },
    });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation(() => new Promise(() => {}));

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    const controls = within(runCard).getByLabelText('Active action run controls');
    expect(within(controls).getByRole('button', { name: /pause after step/i })).toBeEnabled();
    expect(within(controls).getByRole('button', { name: /cancel remaining/i })).toBeEnabled();
  });

  test('describes action controls using current-step interruption semantics from the API', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 2,
      current_step_interruption: {
        policy: 'stop_local_wait',
        cancel_remaining: {
          stops_current_step: true,
          blocks_future_dispatches: true,
          waits_for_terminal: false,
        },
        pause_after_current_step: {
          stops_current_step: false,
          pauses_before_next_dispatch: true,
        },
      },
    });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation(() => new Promise(() => {}));

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    const cancelButton = within(runCard).getByRole('button', { name: /cancel remaining/i });
    const pauseButton = within(runCard).getByRole('button', { name: /pause after step/i });
    expect(cancelButton).toHaveAttribute(
      'title',
      'Stop the current local wait, then cancel every remaining step.',
    );
    expect(cancelButton).toHaveAccessibleDescription(
      'Stop the current local wait, then cancel every remaining step.',
    );
    expect(pauseButton).toHaveAccessibleDescription(
      'Let the current step finish, then pause before the next step is dispatched.',
    );
  });

  test('does not invent action-run controls when the backend omits them', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 1,
      available_controls: undefined,
    });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation(() => new Promise(() => {}));

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    expect(within(runCard).queryByLabelText('Active action run controls')).not.toBeInTheDocument();
  });

  test('keeps countdown ticks visual without repeatedly changing the live announcement', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 2,
      summary: 'Step 2/4: Wait 5 seconds',
    });
    let streamConfig;
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      streamConfig = config;
      return new Promise(() => {});
    });

    renderPage();
    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(streamConfig).toBeDefined());

    act(() => {
      streamConfig.onEvent?.({
        event: 'progress',
        data: {
          id: 30,
          run_id: runningRun.run_id,
          event_type: 'progress',
          payload: {
            state: 'running',
            step_index: 2,
            step_count: 4,
            step_label: 'Wait 5 seconds',
            remaining_seconds: 5,
            label: 'Step 2/4: Wait 5 seconds · 5s remaining',
          },
        },
      });
    });
    expect(await within(runCard).findByText(/5s remaining/)).toBeInTheDocument();
    const liveStatus = within(runCard).getByRole('status');
    const firstAnnouncement = liveStatus.textContent;
    expect(firstAnnouncement).toMatch(/step 2: wait 5 seconds · in progress/i);
    expect(firstAnnouncement).not.toMatch(/5s remaining/i);

    act(() => {
      streamConfig.onEvent?.({
        event: 'progress',
        data: {
          id: 31,
          run_id: runningRun.run_id,
          event_type: 'progress',
          payload: {
            state: 'running',
            step_index: 2,
            step_count: 4,
            step_label: 'Wait 5 seconds',
            remaining_seconds: 4,
            label: 'Step 2/4: Wait 5 seconds · 4s remaining',
          },
        },
      });
    });
    expect(await within(runCard).findByText(/4s remaining/)).toBeInTheDocument();
    expect(liveStatus).toHaveTextContent(firstAnnouncement);
  });

  test('auto-scrolls action progress only while the transcript remains bottom-pinned', async () => {
    const runningRun = actionRunData({ state: 'running', current_step: 2 });
    let streamConfig;
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      streamConfig = config;
      return new Promise(() => {});
    });

    const { container } = renderPage();
    await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(streamConfig).toBeDefined());
    const transcript = container.querySelector('.simurgh-chat__transcript');
    Object.defineProperties(transcript, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 200 },
    });

    transcript.scrollTop = 200;
    fireEvent.scroll(transcript);
    act(() => {
      streamConfig.onEvent?.({
        event: 'run_snapshot',
        data: {
          revision: 2,
          run: {
            ...runningRun,
            revision: 2,
            summary: 'Progress while operator reviews history',
            updated_at: '2026-05-24T00:00:02Z',
          },
        },
      });
    });
    await waitFor(() => expect(transcript.scrollTop).toBe(200));

    transcript.scrollTop = 720;
    fireEvent.scroll(transcript);
    act(() => {
      streamConfig.onEvent?.({
        event: 'run_snapshot',
        data: {
          revision: 3,
          run: {
            ...runningRun,
            revision: 3,
            current_step: 3,
            summary: 'Progress while transcript is pinned',
            updated_at: '2026-05-24T00:00:03Z',
          },
        },
      });
    });
    await waitFor(() => expect(transcript.scrollTop).toBe(1000));
  });

  test('keeps a cleanly closed nonterminal stream stale across snapshot failures and then recovers', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 2,
      summary: 'Step 2/4: Wait 5 seconds',
    });
    const terminalRun = actionRunData({
      state: 'succeeded',
      terminal: true,
      current_step: 4,
      summary: 'Completed 4 of 4 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-recovery',
        backendSessionId: 'sess_action_run',
        title: 'Recover action run',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-recovery',
          role: 'assistant',
          content: 'Action run started.',
          trace: { safety: { action_execution: 'submitted', action_run: runningRun } },
        }],
      }],
    }));
    let snapshotCall = 0;
    mockGetSimurghActionRunResponse.mockImplementation(() => {
      snapshotCall += 1;
      if (snapshotCall === 1) {
        return Promise.resolve({ data: runningRun });
      }
      if (snapshotCall <= 3) {
        return Promise.reject(new Error('snapshot temporarily unavailable'));
      }
      return Promise.resolve({ data: terminalRun });
    });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [] } });
    mockStreamSimurghActionRunEventsResponse.mockResolvedValue({ data: null });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => {
      expect(mockStreamSimurghActionRunEventsResponse).toHaveBeenCalledWith(
        'run-test-sequence',
        expect.any(Object),
        expect.any(Object),
      );
      expect(mockGetSimurghActionRunResponse).toHaveBeenCalledTimes(3);
    });
    expect(within(runCard).getByText('Reconnecting')).toBeInTheDocument();
    expect(within(runCard).getByRole('status')).toHaveTextContent(/live updates interrupted; reconnecting/i);

    await waitFor(
      () => expect(mockGetSimurghActionRunResponse.mock.calls.length).toBeGreaterThanOrEqual(4),
      { timeout: 8000 },
    );
    expect(mockStreamSimurghActionRunEventsResponse.mock.calls.length).toBeGreaterThanOrEqual(2);
    await waitFor(() => expect(within(runCard).getByText('Complete')).toBeInTheDocument());
    expect(mockGetSimurghActionRunResponse.mock.calls.filter(([runId]) => runId === 'run-test-sequence').length).toBeGreaterThanOrEqual(4);
    expect(mockGetSimurghActionRunsResponse).toHaveBeenCalledWith({
      actor: 'dashboard',
      activeOnly: true,
      limit: 20,
    });
    expect(within(runCard).getByTitle('Action succeeded')).toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '4');
    expect(within(runCard).queryByText('Reconnecting')).not.toBeInTheDocument();
  }, 10000);

  test('marks a silent half-open action stream stale when snapshot reconciliation fails', async () => {
    const runningRun = actionRunData({
      state: 'running',
      current_step: 2,
      summary: 'Step 2/4: Wait 5 seconds',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-half-open',
        backendSessionId: 'sess_action_run',
        title: 'Half-open monitor',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-half-open',
          role: 'assistant',
          content: 'Action run started.',
          trace: { safety: { action_execution: 'submitted', action_run: runningRun } },
        }],
      }],
    }));
    let streamConfig;
    let snapshotsHealthy = true;
    mockGetSimurghActionRunResponse.mockImplementation(() => (
      snapshotsHealthy
        ? Promise.resolve({ data: runningRun })
        : Promise.reject(new Error('snapshot unavailable'))
    ));
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      streamConfig = config;
      return new Promise(() => {});
    });

    renderPage();
    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(streamConfig).toBeDefined());
    snapshotsHealthy = false;

    await waitFor(
      () => expect(within(runCard).getByText('Reconnecting')).toBeInTheDocument(),
      { timeout: 7000 },
    );
    expect(within(runCard).getByRole('status')).toHaveTextContent(/live updates interrupted; reconnecting/i);

    act(() => {
      streamConfig.onEvent?.({
        event: 'run_snapshot',
        data: {
          run: {
            ...runningRun,
            state: 'succeeded',
            terminal: true,
            current_step: 4,
            summary: 'Completed 4 of 4 planned steps.',
            completed_at: '2026-05-24T00:01:00Z',
          },
          replay_complete: true,
        },
      });
    });
    await waitFor(() => expect(within(runCard).getByText('Complete')).toBeInTheDocument());
    expect(within(runCard).queryByText('Reconnecting')).not.toBeInTheDocument();
  }, 9000);

  test('does not turn accepted transport completion into action success', async () => {
    const acceptedTurn = assistantTurnData({
      id: 'turn_action_accepted',
      content: 'The GCS accepted the command and monitoring is continuing.',
      trace: {
        summary: 'GCS accepted action submission',
        safety: {
          action_execution: 'submitted',
          action_monitor: { status: 'accepted' },
          post_action_results: [],
        },
      },
    });
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({
        event: 'progress',
        data: { stage: 'monitor', state: 'monitoring', label: 'Monitoring command completion' },
      });
      config.onEvent?.({ event: 'final', data: acceptedTurn });
      config.onEvent?.({ event: 'done', data: { id: acceptedTurn.id, session_id: acceptedTurn.session.id } });
      return { data: acceptedTurn };
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'run the action and report when it is done' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('Action accepted')).toBeInTheDocument();
    expect(screen.getByText('Accepted by the GCS; completion is still pending')).toBeInTheDocument();
    expect(screen.queryByText('Command sequence complete')).not.toBeInTheDocument();
    expect(screen.getAllByTitle('Action in progress').length).toBeGreaterThan(0);
    expect(screen.getByText('Action accepted').closest('.simurgh-chat__action-result')).toHaveClass(
      'simurgh-chat__action-result--active',
    );
    const activity = screen.getByText('Working').closest('.simurgh-chat__activity');
    expect(activity).not.toBeNull();
    expect(within(activity).queryByText('Ready')).not.toBeInTheDocument();
  });

  test('keeps a received final answer when the stream closes with an error afterward', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_final_before_stream_error',
      content: '4 drones are configured and no SITL instances are active.',
    });
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce(async (payload, config = {}) => {
      config.onEvent?.({ event: 'final', data: finalTurn });
      throw new Error('stream closed after final event');
    });

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'How many drones and SITL instances are active?' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect((await screen.findAllByText(finalTurn.content)).length).toBeGreaterThan(0);
    expect(screen.queryByText('stream closed after final event')).not.toBeInTheDocument();
  });

  test.each([
    ['failed', 'Failed', 'failed'],
    ['blocked', 'Blocked', 'blocked'],
    ['cancelled', 'Cancelled', 'cancelled'],
    ['interrupted', 'Interrupted', 'interrupted'],
  ])('keeps a terminal %s run visually non-successful', async (state, label, stepState) => {
    const terminalRun = actionRunData({
      state,
      terminal: true,
      current_step: 2,
      summary: `${label} during step 2.`,
      completed_at: '2026-05-24T00:01:00Z',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: `chat-${state}`,
        backendSessionId: 'sess_action_run',
        title: `${label} action run`,
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: `turn-${state}`,
          role: 'assistant',
          content: 'Action run finished without verified success.',
          trace: { safety: { action_execution: 'submitted', action_run: terminalRun } },
        }],
      }],
    }));
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: terminalRun });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    expect(await within(runCard).findByText(label)).toBeInTheDocument();
    expect(within(runCard).getByTitle('Action needs attention')).toBeInTheDocument();
    expect(within(runCard).queryByTitle('Action succeeded')).not.toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');
    const currentStep = within(runCard).getByText('Wait 5 seconds').closest('li');
    expect(currentStep).toHaveClass(`simurgh-chat__action-run-step--${stepState}`);
  });

  test.each([
    ['LAND', 'Land at the current position'],
    ['RETURN_RTL', 'Return to launch'],
  ])('does not render a false-success %s run as complete when final verification failed', async (missionName, actionLabel) => {
    const embeddedRun = actionRunData({ state: 'queued', current_step: 0, total_steps: 2 });
    const basePlan = actionRunData().plan;
    const falseSuccessRun = actionRunData({
      state: 'succeeded',
      terminal: true,
      current_step: 2,
      total_steps: 2,
      summary: 'Completed 2 of 2 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
      plan: {
        ...basePlan,
        mission_name: missionName,
        command_payload: {
          mission_type: missionName === 'LAND' ? 101 : 104,
          target_drone_ids: ['1'],
        },
        display_plan: {
          title: 'Review flight plan',
          target: 'drone 1',
          steps: [
            { index: 1, kind: 'flight_command', label: actionLabel },
            { index: 2, kind: 'registry_action', label: 'Remove SITL instance drone-1' },
          ],
        },
      },
      result: {
        action_execution: 'submitted',
        action_response: { status: 'submitted', command_id: `cmd-${missionName.toLowerCase()}` },
        monitor_result: {
          status: 'terminal_success',
          success: true,
          timed_out: false,
          completion_verification: {
            status: 'timeout',
            verified: false,
            summary: 'Final disarm state was not confirmed from fresh telemetry.',
          },
        },
        post_action_results: [],
        rejection_detail: '',
      },
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: `chat-${missionName.toLowerCase()}-verification`,
        backendSessionId: 'sess_action_run',
        title: `${missionName} verification`,
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: `turn-${missionName.toLowerCase()}-verification`,
          role: 'assistant',
          content: 'Action run started.',
          trace: { safety: { action_execution: 'submitted', action_run: embeddedRun } },
        }],
      }],
    }));
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: falseSuccessRun });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(within(runCard).getByText('Needs review')).toBeInTheDocument());
    expect(runCard).toHaveClass('simurgh-chat__action-run--warning');
    expect(within(runCard).queryByText('Complete')).not.toBeInTheDocument();
    expect(within(runCard).getByText('Final state not confirmed')).toBeInTheDocument();
    expect(within(runCard).getByText('1 dependent step remained skipped.')).toBeInTheDocument();
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
    const flightStep = within(runCard).getByText(actionLabel).closest('li');
    const cleanupStep = within(runCard).getByText('Remove SITL instance drone-1').closest('li');
    expect(flightStep).toHaveClass('simurgh-chat__action-run-step--failed');
    expect(within(flightStep).getByText('failed')).toBeInTheDocument();
    expect(cleanupStep).toHaveClass('simurgh-chat__action-run-step--skipped');
    expect(within(cleanupStep).getByText('skipped')).toBeInTheDocument();
    const rawToggle = within(runCard).getByRole('button', { name: /raw action json/i });
    expect(rawToggle).toHaveAttribute('aria-expanded', 'false');
    expect(within(runCard).queryByText((text) => text.includes('"mission_type"'))).not.toBeInTheDocument();
  });

  test('restores a terminal action run from durable state after chat reload', async () => {
    const embeddedRun = actionRunData({ state: 'queued', current_step: 0 });
    const completedRun = actionRunData({
      state: 'succeeded',
      terminal: true,
      current_step: 4,
      summary: 'Completed 4 of 4 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-action-run',
        backendSessionId: 'sess_action_run',
        title: 'Test flight',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-action-run',
          role: 'assistant',
          content: 'Action run started.',
          trace: { safety: { action_execution: 'submitted', action_run: embeddedRun } },
        }],
      }],
    }));
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: completedRun });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(within(runCard).getByText('Complete')).toBeInTheDocument());
    expect(mockGetSimurghActionRunResponse).toHaveBeenCalledWith('run-test-sequence');
    expect(within(runCard).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '4');
  });

  test('removes a discovered cross-chat operation when it becomes terminal', async () => {
    const runningRun = actionRunData({
      run_id: 'run-discovered',
      state: 'running',
      current_step: 2,
      summary: 'Monitoring step 2.',
    });
    const terminalRun = actionRunData({
      run_id: 'run-discovered',
      state: 'succeeded',
      terminal: true,
      current_step: 4,
      summary: 'Completed 4 of 4 planned steps.',
      completed_at: '2026-05-24T00:01:00Z',
    });
    let streamConfig;
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      streamConfig = config;
      return new Promise(() => {});
    });

    renderPage();

    const runCard = await findActionRunCard('run-discovered');
    const operationsRegion = screen.getByLabelText('Active operations across chats');
    const transcript = document.querySelector('.simurgh-chat__transcript');
    expect(operationsRegion).toContainElement(runCard);
    expect(transcript).not.toContainElement(runCard);
    expect(within(runCard).getByText(/operator session sess_action_/i)).toBeInTheDocument();
    await waitFor(() => expect(streamConfig).toBeDefined());
    act(() => {
      streamConfig.onEvent?.({ event: 'run_snapshot', data: { run: terminalRun, replay_complete: true } });
    });
    await waitFor(() => {
      expect(document.querySelector('[data-action-run-id="run-discovered"]')).toBeNull();
    });
    expect(screen.queryByLabelText('Active operations across chats')).not.toBeInTheDocument();
  });

  test('does not restore terminal operations into a new chat after reload', async () => {
    const terminalRuns = [1, 2, 3, 4].map((index) => actionRunData({
      run_id: `run-terminal-${index}`,
      state: index === 3 ? 'failed' : 'succeeded',
      terminal: true,
      current_step: index === 3 ? 2 : 4,
      summary: index === 3 ? 'Step 2 failed.' : 'Completed 4 of 4 planned steps.',
      updated_at: `2026-05-24T00:0${index}:00Z`,
      completed_at: `2026-05-24T00:0${index}:00Z`,
    }));
    mockGetSimurghActionRunsResponse.mockImplementation(({ activeOnly }) => Promise.resolve({
      data: { runs: activeOnly ? [] : terminalRuns },
    }));

    renderPage();

    await waitFor(() => {
      expect(mockGetSimurghActionRunsResponse).toHaveBeenCalled();
    });
    expect(mockGetSimurghActionRunsResponse.mock.calls.every(
      ([options]) => options?.activeOnly === true
    )).toBe(true);
    expect(screen.queryByLabelText('Active operations across chats')).not.toBeInTheDocument();
    terminalRuns.forEach((run) => {
      expect(document.querySelector(`[data-action-run-id="${run.run_id}"]`)).toBeNull();
    });
  });

  test('renders contradictory succeeded run evidence as failed', async () => {
    const contradictoryRun = actionRunData({
      state: 'succeeded',
      terminal: true,
      current_step: 1,
      summary: 'Backend run state claimed success.',
      result: {
        monitor_result: {
          success: false,
          status: 'terminal_non_success',
          summary: 'Command tracker reported failure.',
        },
        post_action_results: [],
      },
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-contradictory-run',
        backendSessionId: 'sess_action_run',
        title: 'Contradictory run',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-contradictory-run',
          role: 'assistant',
          content: 'Action run finished.',
          trace: { safety: { action_execution: 'submitted', action_run: contradictoryRun } },
        }],
      }],
    }));
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: contradictoryRun });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    expect(await within(runCard).findByText('Failed')).toBeInTheDocument();
    expect(within(runCard).getByTitle('Action needs attention')).toBeInTheDocument();
    expect(within(runCard).queryByTitle('Action succeeded')).not.toBeInTheDocument();
  });

  test('exposes pause and cancel-remaining controls for active action runs', async () => {
    const runningRun = actionRunData({ state: 'running', current_step: 2, summary: 'Step 2/4: Wait 5 seconds' });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [runningRun] } });
    mockStreamSimurghActionRunEventsResponse.mockImplementation(() => new Promise(() => {}));
    mockControlSimurghActionRunResponse
      .mockResolvedValueOnce({ data: actionRunData({ state: 'pause_requested', current_step: 2 }) })
      .mockResolvedValueOnce({ data: actionRunData({ state: 'cancel_requested', current_step: 2 }) });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    fireEvent.click(within(runCard).getByRole('button', { name: /pause after step/i }));
    await waitFor(() => {
      expect(mockControlSimurghActionRunResponse).toHaveBeenNthCalledWith(
        1,
        'run-test-sequence',
        expect.objectContaining({ actor: 'dashboard', action: 'pause_after_current_step' }),
      );
    });
    expect(await within(runCard).findByText('Pausing')).toBeInTheDocument();

    fireEvent.click(within(runCard).getByRole('button', { name: /cancel remaining/i }));
    await waitFor(() => {
      expect(mockControlSimurghActionRunResponse).toHaveBeenNthCalledWith(
        2,
        'run-test-sequence',
        expect.objectContaining({ actor: 'dashboard', action: 'cancel_remaining' }),
      );
    });
    expect(await within(runCard).findByText('Cancelling')).toBeInTheDocument();
  });

  test('renders an applied pause instead of the earlier pause request', async () => {
    const pausingRun = actionRunData({
      state: 'pause_requested',
      control_state: 'pause_requested',
      current_step: 2,
      revision: 2,
      last_event_id: 12,
    });
    mockGetSimurghActionRunsResponse.mockResolvedValue({ data: { runs: [pausingRun] } });
    let streamConfig;
    mockStreamSimurghActionRunEventsResponse.mockImplementation((runId, options, config = {}) => {
      streamConfig = config;
      return new Promise(() => {});
    });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    expect(await within(runCard).findByText('Pausing')).toBeInTheDocument();
    await waitFor(() => expect(streamConfig).toBeDefined());

    act(() => {
      streamConfig.onEvent?.({
        event: 'run_paused',
        data: {
          id: 13,
          run_id: pausingRun.run_id,
          event_type: 'run_paused',
          payload: {
            state: 'paused',
            label: 'Action run paused before the next step',
          },
        },
      });
    });

    expect(await within(runCard).findByText('Paused')).toBeInTheDocument();
    expect(within(runCard).queryByText('Pausing')).not.toBeInTheDocument();
  });

  test('renders terminal action state instead of a stale control request', async () => {
    const embeddedRun = actionRunData({ state: 'cancel_requested', control_state: 'cancel_requested', current_step: 2 });
    const cancelledRun = actionRunData({
      state: 'cancelled',
      terminal: true,
      control_state: 'cancel_requested',
      current_step: 2,
      summary: 'Remaining steps were cancelled.',
    });
    window.localStorage.setItem('mds.simurgh.chat.v2', JSON.stringify({
      schema: 2,
      conversations: [{
        id: 'chat-cancelled-action-run',
        backendSessionId: 'sess_action_run',
        title: 'Cancelled test flight',
        createdAt: '2026-05-24T00:00:00Z',
        updatedAt: '2026-05-24T00:00:00Z',
        messages: [{
          id: 'turn-cancelled-action-run',
          role: 'assistant',
          content: 'Action run cancellation requested.',
          trace: { safety: { action_execution: 'submitted', action_run: embeddedRun } },
        }],
      }],
    }));
    mockGetSimurghActionRunResponse.mockResolvedValue({ data: cancelledRun });

    renderPage();

    const runCard = await findActionRunCard('run-test-sequence');
    await waitFor(() => expect(within(runCard).getByText('Cancelled')).toBeInTheDocument());
    expect(within(runCard).queryByText('Cancelling')).not.toBeInTheDocument();
    expect(within(runCard).queryByRole('button', { name: /cancel remaining/i })).not.toBeInTheDocument();
  });

  test('shows an unverified primary landing result as a warning', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_unverified_land',
      content: 'The land command completed, but final disarm was not confirmed.',
      trace: {
        safety: {
          action_execution: 'submitted',
          action_monitor: {
            success: true,
            status: 'terminal_success',
            completion_verification: {
              status: 'timeout',
              verified: false,
            },
          },
          post_action_results: [],
        },
      },
    });
    mockStreamResponseOnce(finalTurn);

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'land drone 1 and report when disarmed' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('Final state not confirmed')).toBeInTheDocument();
    expect(screen.getByText(/final disarm not confirmed/i)).toBeInTheDocument();
  });

  test('shows an unverified SITL lifecycle result without flight-state copy', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_unverified_sitl',
      content: 'The container started, but vehicle readiness was not confirmed.',
      trace: {
        safety: {
          action_execution: 'submitted',
          action_monitor: {
            success: false,
            status: 'timeout',
            completion_verification: {
              kind: 'sitl_lifecycle',
              status: 'timeout',
              verified: false,
              summary: 'MAVLink is live; preflight readiness is still pending.',
            },
          },
          post_action_results: [],
        },
      },
    });
    mockStreamResponseOnce(finalTurn);

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'create one SITL instance and report when ready' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('SITL readiness not confirmed')).toBeInTheDocument();
    expect(screen.getByText(/MAVLink is live; preflight readiness is still pending/i)).toBeInTheDocument();
    expect(screen.queryByText(/final disarm/i)).not.toBeInTheDocument();
  });

  test('ignores empty completion verification metadata for ordinary commands', async () => {
    const finalTurn = assistantTurnData({
      id: 'turn_move_without_final_state_check',
      content: 'The precision move completed.',
      trace: {
        safety: {
          action_execution: 'submitted',
          action_monitor: {
            success: true,
            status: 'terminal_success',
            completion_verification: {},
          },
          post_action_results: [],
        },
      },
    });
    mockStreamResponseOnce(finalTurn);

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'move drone 1 north 5m' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    expect(await screen.findByText('Command sequence complete')).toBeInTheDocument();
    expect(screen.queryByText('Final state not confirmed')).not.toBeInTheDocument();
  });

  test('marks aborted response activity as stopped instead of complete', async () => {
    mockStreamSimurghAssistantTurnResponse.mockImplementationOnce((payload, config = {}) => (
      new Promise((resolve, reject) => {
        config.onEvent?.({
          event: 'progress',
          data: { stage: 'monitor', state: 'running', label: 'Monitoring command step 1 of 3' },
        });
        config.signal?.addEventListener('abort', () => {
          const error = new Error('aborted');
          error.name = 'AbortError';
          reject(error);
        }, { once: true });
      })
    ));

    renderPage();
    const input = await screen.findByRole('textbox', { name: /message simurgh/i });
    fireEvent.change(input, { target: { value: 'monitor this command sequence' } });
    fireEvent.click(screen.getByRole('button', { name: /send simurgh message/i }));

    fireEvent.click(await screen.findByRole('button', { name: /stop simurgh response/i }));
    expect(await screen.findByText('Simurgh response stopped')).toBeInTheDocument();
    const stoppedActivity = screen.getByText('Simurgh response stopped').closest('.simurgh-chat__activity');
    expect(stoppedActivity).not.toBeNull();
    expect(within(stoppedActivity).getByText('Stopped')).toBeInTheDocument();
    expect(screen.queryByText('Answer ready')).not.toBeInTheDocument();
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
      content: '[good](/logs) [source](https://example.com/report) [bad](//evil.example) [js](javascript:alert(1))',
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
