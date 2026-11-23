import type { AgentKind } from '../types';

/**
 * Identity of the two agents. Colors are categorical slots 1 and 2 of the validated
 * dark palette (blue, orange): both pass contrast, CVD and normal-vision checks on
 * the slate-800 surface. Color always appears next to the agent's name, never alone.
 */
export const AGENT_META: Record<AgentKind, { label: string; short: string; color: string; description: string }> = {
  memory: {
    label: 'With persistent learning',
    short: 'Learning',
    color: '#3987e5',
    description: "Reasons from the numbers like the other agent, plus rules and odds it discovered in past games (its own and the other agent's), so it guesses less and wastes fewer moves.",
  },
  baseline: {
    label: 'Without learning',
    short: 'No learning',
    color: '#d95926',
    description: 'Reasons from the numbers and solves every game on its own, never using any memory. Its experience and mistakes are still saved for the learning agent.',
  },
};

/** Descriptions for the (disabled-by-default) LLM agents, shown on older LLM experiments. */
export const LLM_DESCRIPTIONS: Record<AgentKind, string> = {
  memory: 'LLM that reads its playbook of lessons before every move and updates it after every game and mistake.',
  baseline: 'Same LLM, prompt and boards, but starts every game from scratch.',
};

/** Hand-written rules player: a reference line on the charts, not one of the compared agents. */
export const EXPERT_META = { label: 'Expert rules (reference)', short: 'Expert', color: '#94a3b8' };
